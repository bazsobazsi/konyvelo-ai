from flask import Blueprint, render_template, request, jsonify, session as flask_session
from flask_login import login_required, current_user
from app import db
from app.models import ChatSession, ChatMessage, SearchLog, Subscription
from app.agents.accountant import AccountantAgent
from datetime import datetime, timezone
import json
import time

bp = Blueprint('main', __name__)


@bp.route('/')
def dashboard():
    if current_user.is_authenticated:
        sessions = ChatSession.query.filter_by(
            user_id=current_user.id
        ).order_by(ChatSession.updated_at.desc()).limit(20).all()

        log_count = SearchLog.query.filter_by(user_id=current_user.id).count()
        sub = Subscription.query.filter_by(user_id=current_user.id).first()

        return render_template('dashboard.html',
                               sessions=sessions,
                               log_count=log_count,
                               subscription=sub)
    return render_template('dashboard.html',
                           sessions=[],
                           log_count=0,
                           subscription=None)


@bp.route('/chat/new')
@login_required
def new_chat():
    session = ChatSession(user_id=current_user.id, title='Új beszélgetés')
    db.session.add(session)
    db.session.commit()
    return render_template('chat.html', session=session)


@bp.route('/chat/<int:session_id>')
@login_required
def chat(session_id):
    session = ChatSession.query.get_or_404(session_id)
    if session.user_id != current_user.id:
        return 'Hozzáférés megtagadva', 403
    messages = ChatMessage.query.filter_by(session_id=session.id).order_by(ChatMessage.created_at).all()
    return render_template('chat.html', session=session, messages=messages)


@bp.route('/api/chat/<int:session_id>', methods=['POST'])
@login_required
def api_chat(session_id):
    s = ChatSession.query.get_or_404(session_id)
    if s.user_id != current_user.id:
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403

    data = request.get_json()
    user_msg = data.get('message', '').strip()
    if not user_msg:
        return jsonify({'error': 'Üres üzenet'}), 400

    # Check subscription usage limit
    from app.routes.subscription import check_usage_limit
    usage = check_usage_limit(current_user.id)
    if not usage['allowed']:
        return jsonify({
            'error': f'Elérted a napi keresési limitet ({usage.limit}). Válts előfizetésre vagy várj holnapig!',
            'usage': usage,
        }), 429
    user_msg_obj = ChatMessage(session_id=s.id, role='user', content=user_msg)
    db.session.add(user_msg_obj)

    # Auto-title from first message
    if s.title == 'Új beszélgetés' or not s.title:
        s.title = user_msg[:80]
        if len(user_msg) > 80:
            s.title += '…'

    # Build message history for AI
    history = []
    for m in ChatMessage.query.filter_by(session_id=s.id).order_by(ChatMessage.created_at).all():
        history.append({'role': m.role, 'content': m.content})

    # Call agent with RAG
    agent = AccountantAgent()
    t0 = time.time()
    reply, sources = agent.generate(history)
    elapsed = int((time.time() - t0) * 1000)

    # Save AI response
    ai_msg = ChatMessage(
        session_id=s.id, role='assistant',
        content=reply, sources_json=json.dumps(sources, ensure_ascii=False),
    )
    db.session.add(ai_msg)

    s.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    # Log search
    log = SearchLog(
        user_id=current_user.id,
        query=user_msg,
        ai_response=reply,
        sources_used=json.dumps(sources, ensure_ascii=False),
        sources_text='\n\n'.join([s.get('text', '') for s in sources[:3]]),
        response_time_ms=elapsed,
        ip_address=request.remote_addr or '',
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({
        'reply': reply,
        'sources': sources,
        'response_time_ms': elapsed,
        'session_id': s.id,
        'title': s.title,
    })


@bp.route('/api/sessions')
@login_required
def list_sessions():
    sessions = ChatSession.query.filter_by(user_id=current_user.id)\
        .order_by(ChatSession.updated_at.desc()).limit(50).all()
    return jsonify([{
        'id': s.id,
        'title': s.title,
        'message_count': ChatMessage.query.filter_by(session_id=s.id).count(),
        'updated_at': s.updated_at.isoformat() if s.updated_at else None,
    } for s in sessions])


@bp.route('/api/sessions/<int:session_id>', methods=['DELETE'])
@login_required
def delete_session(session_id):
    s = ChatSession.query.get_or_404(session_id)
    if s.user_id != current_user.id:
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403
    ChatMessage.query.filter_by(session_id=s.id).delete()
    db.session.delete(s)
    db.session.commit()
    return jsonify({'ok': True})