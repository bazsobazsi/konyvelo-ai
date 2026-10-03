from flask import (Blueprint, render_template, request, jsonify, Response,
                   stream_with_context, current_app)
from flask_login import login_required, current_user
from app import db
from app.models import ChatSession, ChatMessage, SearchLog, Subscription
from app.agents.accountant import AccountantAgent
from app.rag.retriever import get_collector_status
from app.routes.admin import is_admin_user
from datetime import datetime, timezone
import json
import time
import requests

bp = Blueprint('main', __name__)

MAX_HISTORY_MESSAGES = 12  # hány korábbi üzenetet küldünk az AI-nak


# ── Segédek ──

def _can_access(session):
    """A tulajdonos ÉS az admin is hozzáfér."""
    return session.user_id == current_user.id or is_admin_user()


def _history_for(session_id, limit=MAX_HISTORY_MESSAGES):
    msgs = ChatMessage.query.filter_by(session_id=session_id)\
        .order_by(ChatMessage.created_at.desc()).limit(limit).all()
    msgs.reverse()
    return [{'role': m.role, 'content': m.content} for m in msgs]


def _save_answer(session, user_msg, reply, sources, elapsed_ms, weak=False):
    """AI válasz + keresési napló mentése. Visszaadja az üzenet id-t."""
    ai_msg = ChatMessage(
        session_id=session.id, role='assistant',
        content=reply, sources_json=json.dumps(sources, ensure_ascii=False),
    )
    db.session.add(ai_msg)
    session.updated_at = datetime.now(timezone.utc)

    if session.title in ('Új beszélgetés', '', None):
        session.title = user_msg[:80] + ('…' if len(user_msg) > 80 else '')

    log = SearchLog(
        user_id=session.user_id,
        search_query=user_msg,
        ai_response=reply,
        sources_used=json.dumps(sources, ensure_ascii=False),
        sources_text='\n\n'.join([s.get('text', '') for s in sources[:3]]),
        response_time_ms=elapsed_ms,
        ip_address=request.remote_addr or '',
    )
    db.session.add(log)
    db.session.commit()
    return ai_msg.id


def _check_limit():
    from app.routes.subscription import check_usage_limit
    usage = check_usage_limit(current_user.id)
    if not usage['allowed']:
        return usage
    return None


# ── Oldalak ──

@bp.route('/')
def dashboard():
    if current_user.is_authenticated:
        sessions = ChatSession.query.filter_by(
            user_id=current_user.id
        ).order_by(ChatSession.updated_at.desc()).limit(20).all()

        log_count = db.session.query(SearchLog).filter_by(user_id=current_user.id).count()
        sub = Subscription.query.filter_by(user_id=current_user.id).first()
        collector = get_collector_status()

        return render_template('dashboard.html',
                               sessions=sessions,
                               log_count=log_count,
                               subscription=sub,
                               collector=collector)
    return render_template('dashboard.html',
                           sessions=[], log_count=0,
                           subscription=None, collector=None)


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
    if not _can_access(session):
        return 'Hozzáférés megtagadva', 403
    messages = ChatMessage.query.filter_by(session_id=session.id)\
        .order_by(ChatMessage.created_at).all()
    return render_template('chat.html', session=session, messages=messages)


# ── Streaming chat (SSE) ──

@bp.route('/api/chat/<int:session_id>/stream', methods=['POST'])
@login_required
def api_chat_stream(session_id):
    s = ChatSession.query.get_or_404(session_id)
    if not _can_access(s):
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403

    data = request.get_json(silent=True) or {}
    user_msg = (data.get('message') or '').strip()
    if not user_msg:
        return jsonify({'error': 'Üres üzenet'}), 400

    usage = _check_limit()
    if usage:
        return jsonify({
            'error': f"Elérted a napi keresési limitet ({usage['limit']}). "
                     f"Válts előfizetésre vagy várj holnapig!",
            'usage': usage,
        }), 429

    db.session.add(ChatMessage(session_id=s.id, role='user', content=user_msg))
    if s.title in ('Új beszélgetés', '', None):
        s.title = user_msg[:80] + ('…' if len(user_msg) > 80 else '')
    db.session.commit()

    history = _history_for(s.id)
    session_id_local = s.id
    session_title = s.title

    def sse(event, payload):
        return f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'

    @stream_with_context
    def generate():
        agent = AccountantAgent()
        t0 = time.time()
        parts = []
        sources = []
        stopped = False

        try:
            full_messages, sources = agent.prepare_stream(history)
        except GeneratorExit:
            return
        except Exception as e:
            current_app.logger.error(f'RAG prepare error: {e}', exc_info=True)
            yield sse('error', {'error': 'Hiba a forráskeresés közben.'})
            return

        yield sse('sources', {'sources': sources, 'title': session_title})

        error_msg = None
        try:
            for piece in agent.stream_tokens(full_messages):
                parts.append(piece)
                yield sse('delta', {'t': piece})
        except GeneratorExit:
            # A kliens leállította (Stop gomb) — nincs több yield, csak mentés
            stopped = True
        except requests.exceptions.Timeout:
            error_msg = 'Az AI nem válaszolt időben. Próbáld újra.'
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if getattr(e, 'response', None) is not None else '?'
            error_msg = f'AI hiba (HTTP {status}).'
        except RuntimeError as e:
            error_msg = str(e)
        except (BrokenPipeError, ConnectionResetError):
            stopped = True
        except Exception as e:
            current_app.logger.error(f'Stream error: {e}', exc_info=True)
            error_msg = 'Hiba történt az AI hívás közben.'

        # ── Mentés (yield NÉLKÜL, hogy GeneratorExit közben se legyen gond) ──
        reply = ''.join(parts).strip()
        elapsed = int((time.time() - t0) * 1000)
        saved = False
        if reply:
            try:
                sess = db.session.get(ChatSession, session_id_local)
                if sess:
                    _save_answer(sess, user_msg, reply, sources, elapsed)
                    saved = True
            except Exception as e:
                current_app.logger.error(f'Mentés hiba: {e}', exc_info=True)

        if stopped:
            current_app.logger.info(f'Stream leállítva a kliens által (mentve: {saved}).')
            return

        if error_msg:
            yield sse('error', {'error': error_msg, 'partial_saved': saved})
            return

        if not saved and reply:
            yield sse('error', {'error': 'A válasz mentése nem sikerült.'})
            return

        yield sse('done', {'title': session_title, 'response_time_ms': elapsed,
                           'partial': False})

    resp = Response(generate(), mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'   # nginx/Coolify proxy ne bufferelje
    resp.headers['Connection'] = 'keep-alive'
    return resp


# ── Nem-streaming chat (fallback) ──

@bp.route('/api/chat/<int:session_id>', methods=['POST'])
@login_required
def api_chat(session_id):
    s = ChatSession.query.get_or_404(session_id)
    if not _can_access(s):
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403

    data = request.get_json(silent=True) or {}
    user_msg = (data.get('message') or '').strip()
    if not user_msg:
        return jsonify({'error': 'Üres üzenet'}), 400

    usage = _check_limit()
    if usage:
        return jsonify({
            'error': f"Elérted a napi keresési limitet ({usage['limit']}). "
                     f"Válts előfizetésre vagy várj holnapig!",
            'usage': usage,
        }), 429

    db.session.add(ChatMessage(session_id=s.id, role='user', content=user_msg))
    db.session.commit()
    history = _history_for(s.id)

    agent = AccountantAgent()
    t0 = time.time()
    reply, sources = agent.generate(history)
    elapsed = int((time.time() - t0) * 1000)

    _save_answer(s, user_msg, reply, sources, elapsed)

    return jsonify({
        'reply': reply,
        'sources': sources,
        'response_time_ms': elapsed,
        'session_id': s.id,
        'title': s.title,
    })


# ── Session lista / törlés ──

@bp.route('/api/sessions')
@login_required
def list_sessions():
    sessions = ChatSession.query.filter_by(user_id=current_user.id)\
        .order_by(ChatSession.updated_at.desc()).limit(100).all()
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
    if not _can_access(s):
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403
    ChatMessage.query.filter_by(session_id=s.id).delete()
    db.session.delete(s)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/api/sessions/<int:session_id>/messages')
@login_required
def session_messages(session_id):
    s = ChatSession.query.get_or_404(session_id)
    if not _can_access(s):
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403
    msgs = ChatMessage.query.filter_by(session_id=s.id).order_by(ChatMessage.created_at).all()
    return jsonify([{
        'id': m.id, 'role': m.role, 'content': m.content,
        'sources': m.get_sources_json(),
        'created_at': m.created_at.isoformat() if m.created_at else None,
    } for m in msgs])
