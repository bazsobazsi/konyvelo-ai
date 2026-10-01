from flask import Blueprint, render_template, jsonify, request, send_file, abort, current_app
from flask_login import login_required, current_user
from app import db
from app.models import SearchLog, User, ChatMessage, Subscription
from datetime import datetime, timezone
import json
import io
import csv
from functools import wraps

bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    """Dekorátor — csak a beállított ADMIN_EMAIL-elérhető."""
    @wraps(f)
    def decorated(*args, **kwargs):
        admin_email = current_app.config.get('ADMIN_EMAIL', '')
        if not admin_email or current_user.email != admin_email:
            abort(404)  # 404, nem 403 — minek "mine" van
        return f(*args, **kwargs)
    return decorated


@bp.route('/')
@login_required
@admin_required
def admin_dashboard():
    # Only admin (first user or specific email) or show own stats
    search_count = SearchLog.query.filter_by(user_id=current_user.id).count()
    session_count = len(current_user.chat_sessions.all())
    recent = SearchLog.query.filter_by(user_id=current_user.id)\
        .order_by(SearchLog.created_at.desc()).limit(50).all()
    sub = Subscription.query.filter_by(user_id=current_user.id).first()
    return render_template('admin.html',
                           search_count=search_count,
                           session_count=session_count,
                           recent_logs=recent,
                           subscription=sub)


@bp.route('/api/logs')
@login_required
@admin_required
def api_logs():
    limit = request.args.get('limit', 100, type=int)
    logs = SearchLog.query.filter_by(user_id=current_user.id)\
        .order_by(SearchLog.created_at.desc()).limit(limit).all()
    return jsonify([l.to_dict() for l in logs])


@bp.route('/api/logs/export/json')
@login_required
@admin_required
def export_json():
    """Export all user's Q&A pairs for fine-tuning in JSONL format."""
    logs = SearchLog.query.filter_by(user_id=current_user.id)\
        .order_by(SearchLog.created_at.asc()).all()

    export = []
    for log in logs:
        # Build fine-tuning format: messages array
        system_prompt = (
            "Te egy tapasztalt könyvelő asszisztens vagy, aki a magyar jogszabályok "
            "és NAV tájékoztatók alapján válaszol. Csak a megadott forrásokra hivatkozva adj választ."
        )
        entry = {
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': log.search_query},
                {'role': 'assistant', 'content': log.ai_response},
            ],
            'sources': json.loads(log.sources_used) if log.sources_used else [],
            'timestamp': log.created_at.isoformat() if log.created_at else None,
        }
        export.append(entry)

    buf = io.StringIO()
    for entry in export:
        buf.write(json.dumps(entry, ensure_ascii=False) + '\n')

    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    return send_file(
        mem,
        mimetype='application/jsonl',
        as_attachment=True,
        download_name=f'konyveloai-export-{datetime.now().strftime("%Y%m%d")}.jsonl'
    )


@bp.route('/api/logs/export/csv')
@login_required
@admin_required
def export_csv():
    logs = SearchLog.query.filter_by(user_id=current_user.id)\
        .order_by(SearchLog.created_at.asc()).all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['id', 'query', 'response', 'sources', 'created_at'])
    for log in logs:
        writer.writerow([
            log.id, log.search_query, log.ai_response,
            log.sources_used, log.created_at.isoformat() if log.created_at else '',
        ])

    mem = io.BytesIO(buf.getvalue().encode('utf-8'))
    return send_file(
        mem,
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'konyveloai-export-{datetime.now().strftime("%Y%m%d")}.csv'
    )


@bp.route('/api/stats')
@login_required
@admin_required
def api_stats():
    total = SearchLog.query.filter_by(user_id=current_user.id).count()
    today = SearchLog.query.filter(
        SearchLog.user_id == current_user.id,
        SearchLog.created_at >= datetime.now(timezone.utc).replace(hour=0, minute=0, second=0)
    ).count()

    sub = Subscription.query.filter_by(user_id=current_user.id).first()
    trial_days_left = 0
    if sub and sub.trial_end:
        trial_days_left = (sub.trial_end - datetime.now(timezone.utc)).days

    return jsonify({
        'total_searches': total,
        'today_searches': today,
        'subscription_status': sub.status if sub else 'none',
        'trial_days_left': max(0, trial_days_left),
        'is_premium': sub and sub.status == 'active',
    })