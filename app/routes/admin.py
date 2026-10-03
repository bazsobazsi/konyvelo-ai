from flask import (Blueprint, render_template, jsonify, request, send_file,
                   abort, current_app, redirect, url_for)
from flask_login import login_required, current_user
from app import db
from app.models import (SearchLog, User, ChatSession, ChatMessage,
                        Subscription, PasswordResetToken)
from datetime import datetime, timezone, timedelta
from functools import wraps
import hashlib
import io
import json
import csv
import secrets

bp = Blueprint('admin', __name__, url_prefix='/admin')


def is_admin_user(user=None):
    """Admin-e a felhasználó? ADMIN_EMAIL egyezés VAGY is_admin flag."""
    u = user or current_user
    if not getattr(u, 'is_authenticated', False):
        return False
    admin_email = (current_app.config.get('ADMIN_EMAIL') or '').strip().lower()
    if admin_email and (u.email or '').lower() == admin_email:
        return True
    return bool(getattr(u, 'is_admin', False))


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not is_admin_user():
            abort(404)
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ──

@bp.route('/')
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    total_sessions = ChatSession.query.count()
    total_messages = ChatMessage.query.count()
    total_searches = db.session.query(SearchLog).count()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_searches = db.session.query(SearchLog).filter(
        SearchLog.created_at >= today_start).count()

    recent_logs = db.session.query(SearchLog)\
        .order_by(SearchLog.created_at.desc()).limit(50).all()

    return render_template(
        'admin.html',
        total_users=total_users,
        total_sessions=total_sessions,
        total_messages=total_messages,
        total_searches=total_searches,
        today_searches=today_searches,
        recent_logs=recent_logs,
        users=User.query.order_by(User.id).all(),
    )


# ── Összes beszélgetés (admin) ──

@bp.route('/conversations')
@admin_required
def admin_conversations():
    sessions = db.session.query(ChatSession)\
        .order_by(ChatSession.updated_at.desc()).limit(500).all()
    rows = []
    for s in sessions:
        owner = db.session.get(User, s.user_id)
        rows.append({
            'id': s.id,
            'title': s.title or '(cím nélkül)',
            'owner_name': owner.name if owner else '?',
            'owner_email': owner.email if owner else '?',
            'message_count': ChatMessage.query.filter_by(session_id=s.id).count(),
            'updated_at': s.updated_at.strftime('%Y.%m.%d %H:%M') if s.updated_at else '',
        })
    return render_template('admin_conversations.html', rows=rows)


@bp.route('/conversations/<int:session_id>')
@admin_required
def admin_conversation_detail(session_id):
    s = db.session.get(ChatSession, session_id)
    if not s:
        abort(404)
    owner = db.session.get(User, s.user_id)
    messages = ChatMessage.query.filter_by(session_id=s.id)\
        .order_by(ChatMessage.created_at).all()
    return render_template('chat.html', session=s, messages=messages,
                           admin_view=True, owner=owner)


# ── Naplók / export ──

@bp.route('/api/logs')
@admin_required
def api_logs():
    limit = request.args.get('limit', 100, type=int)
    logs = db.session.query(SearchLog)\
        .order_by(SearchLog.created_at.desc()).limit(limit).all()
    return jsonify([l.to_dict() for l in logs])


@bp.route('/api/logs/export/json')
@admin_required
def export_json():
    logs = db.session.query(SearchLog).order_by(SearchLog.created_at.asc()).all()
    system_prompt = (
        "Te egy tapasztalt könyvelő asszisztens vagy, aki a magyar jogszabályok "
        "és NAV tájékoztatók alapján válaszol. Csak a megadott forrásokra hivatkozva adj választ."
    )
    buf = io.StringIO()
    for log in logs:
        entry = {
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': log.search_query},
                {'role': 'assistant', 'content': log.ai_response},
            ],
            'sources': json.loads(log.sources_used) if log.sources_used else [],
            'timestamp': log.created_at.isoformat() if log.created_at else None,
        }
        buf.write(json.dumps(entry, ensure_ascii=False) + '\n')

    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    return send_file(mem, mimetype='application/jsonl', as_attachment=True,
                     download_name=f'konyveloai-export-{datetime.now().strftime("%Y%m%d")}.jsonl')


@bp.route('/api/logs/export/csv')
@admin_required
def export_csv():
    logs = db.session.query(SearchLog).order_by(SearchLog.created_at.asc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['id', 'user_id', 'query', 'response', 'sources', 'created_at'])
    for log in logs:
        writer.writerow([
            log.id, log.user_id, log.search_query, log.ai_response,
            log.sources_used, log.created_at.isoformat() if log.created_at else '',
        ])
    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    return send_file(mem, mimetype='text/csv', as_attachment=True,
                     download_name=f'konyveloai-export-{datetime.now().strftime("%Y%m%d")}.csv')


@bp.route('/api/stats')
@admin_required
def api_stats():
    total = db.session.query(SearchLog).count()
    today = db.session.query(SearchLog).filter(
        SearchLog.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    ).count()
    return jsonify({
        'total_searches': total,
        'today_searches': today,
        'total_users': User.query.count(),
        'total_sessions': ChatSession.query.count(),
    })


# ── Felhasználók + jelszó reset link generálás ──

@bp.route('/users')
@admin_required
def admin_users():
    users = User.query.order_by(User.id).all()
    rows = []
    for u in users:
        sub = Subscription.query.filter_by(user_id=u.id).first()
        rows.append({
            'id': u.id, 'name': u.name, 'email': u.email,
            'is_admin': u.is_admin, 'created_at': u.created_at,
            'sub_status': sub.status if sub else 'nincs',
        })
    return render_template('admin_users.html', rows=rows)


@bp.route('/users/<int:user_id>/reset-link', methods=['POST'])
@admin_required
def admin_generate_reset_link(user_id):
    """Új jelszó-reset link generálása egy felhasználónak — egyszer megjelenik."""
    u = db.session.get(User, user_id)
    if not u:
        abort(404)

    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expiry_min = current_app.config['RESET_TOKEN_EXPIRY_MINUTES']

    PasswordResetToken.query.filter_by(user_id=u.id, used=False).update({'used': True})
    db.session.add(PasswordResetToken(
        user_id=u.id, token_hash=token_hash,
        ip_address=request.remote_addr or '',
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expiry_min),
    ))
    db.session.commit()

    domain = current_app.config['DOMAIN'].rstrip('/')
    return jsonify({
        'ok': True,
        'url': f'{domain}/auth/reset/{raw}',
        'expires_minutes': expiry_min,
        'email': u.email,
    })


@bp.route('/users/<int:user_id>/make-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(user_id):
    u = db.session.get(User, user_id)
    if not u:
        abort(404)
    u.is_admin = not bool(u.is_admin)
    db.session.commit()
    return jsonify({'ok': True, 'is_admin': u.is_admin, 'email': u.email})
