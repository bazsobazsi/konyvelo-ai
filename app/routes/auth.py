from flask import Blueprint, redirect, url_for, session as flask_session, current_app
from flask_login import login_user, logout_user, login_required
from authlib.integrations.flask_client import OAuthError
from app import oauth, db
from app.models import User
from datetime import datetime, timezone

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/google')
def google_login():
    domain = current_app.config['DOMAIN'].rstrip('/')
    redirect_uri = f'{domain}/auth/google/callback'
    return oauth.google.authorize_redirect(redirect_uri)


@bp.route('/google/callback')
def google_callback():
    try:
        token = oauth.google.authorize_access_token()
    except OAuthError as e:
        return f'OAuth hiba: {e}', 400

    userinfo = token.get('userinfo') or oauth.google.parse_id_token(token)
    if not userinfo:
        return 'Nem sikerült lekérni a felhasználói adatokat.', 400

    provider_id = userinfo['sub']
    email = userinfo.get('email', '')
    name = userinfo.get('name', '')
    avatar = userinfo.get('picture', '')

    user = User.query.filter_by(provider='google', provider_id=provider_id).first()

    if not user:
        # Check if email already registered
        existing = User.query.filter_by(email=email).first()
        if existing:
            existing.provider = 'google'
            existing.provider_id = provider_id
            user = existing
        else:
            user = User(
                provider='google', provider_id=provider_id,
                email=email, name=name, avatar=avatar,
            )
            db.session.add(user)

    user.name = name
    user.avatar = avatar
    db.session.commit()
    login_user(user)

    # Create trial subscription if not exists
    from app.models import Subscription
    sub = Subscription.query.filter_by(user_id=user.id).first()
    if not sub:
        trial_start = datetime.now(timezone.utc)
        from datetime import timedelta
        sub = Subscription(
            user_id=user.id, status='trial',
            trial_start=trial_start,
            trial_end=trial_start + timedelta(days=current_app.config['TRIAL_DAYS']),
        )
        db.session.add(sub)
        db.session.commit()

    return redirect(url_for('main.dashboard'))


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flask_session.clear()
    return redirect(url_for('main.dashboard'))