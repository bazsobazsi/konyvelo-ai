from flask import Blueprint, redirect, url_for, session as flask_session, current_app
from flask_login import login_user, logout_user, login_required
from authlib.integrations.flask_client import OAuthError
from app import oauth, db
from app.models import User
from datetime import datetime, timezone, timedelta
import logging

logger = logging.getLogger(__name__)
bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/google')
def google_login():
    try:
        domain = current_app.config['DOMAIN'].rstrip('/')
        redirect_uri = f'{domain}/auth/google/callback'
        logger.info(f'Google login redirect URI: {redirect_uri}')
        return oauth.google.authorize_redirect(redirect_uri)
    except Exception as e:
        logger.error(f'Google login init error: {e}', exc_info=True)
        return f'<h1>Google belépés hiba</h1><p>{e}</p><p>Ellenőrizd a DOMAIN env var-t és a Google OAuth beállításokat.</p>', 500


@bp.route('/google/callback')
def google_callback():
    try:
        try:
            token = oauth.google.authorize_access_token()
        except OAuthError as e:
            logger.error(f'OAuth token hiba: {e}')
            return f'<h1>OAuth hiba</h1><p>{e}</p><p>Ellenőrizd a Google OAuth redirect URI-t és a kliens id/secret-et.</p>', 400
        except Exception as e:
            logger.error(f'Token kérés hiba: {e}', exc_info=True)
            return f'<h1>Token hiba</h1><p>{e}</p><p>Google token lekérése hihozliesz. Ellenőrizd a GOOGLE_CLIENT_ID és GOOGLE_CLIENT_SECRET env vars-okat.</p>', 400

        # Try multiple ways to get userinfo
        userinfo = None
        userinfo = token.get('userinfo')
        if not userinfo:
            try:
                userinfo = oauth.google.parse_id_token(token)
            except Exception as e:
                logger.warning(f'parse_id_token failed: {e}, trying userinfo endpoint')
                try:
                    resp = oauth.google.get('https://www.googleapis.com/oauth2/v3/userinfo')
                    userinfo = resp.json()
                except Exception as e2:
                    logger.error(f'Fallback userinfo endpoint also failed: {e2}', exc_info=True)
                    return '<h1>Nem sikerült lekérni a felhasználói adatokat</h1><p>Próbáld újra vagy kontaktáld a támogatást.</p>', 400

        if not userinfo:
            return '<h1>Nem sikerült lekérni a felhasználói adatokat</h1><p>Próbáld újra.</p>', 400

        provider_id = userinfo.get('sub')
        email = userinfo.get('email', '')
        name = userinfo.get('name', '')
        avatar = userinfo.get('picture', '')

        if not provider_id:
            return '<h1>Hiányzó felhasználói azonosító</h1><p>Provider ID nem található.</p>', 400

        # Find or create user
        user = User.query.filter_by(provider='google', provider_id=provider_id).first()

        if not user:
            existing = User.query.filter_by(email=email).first() if email else None
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
            sub = Subscription(
                user_id=user.id, status='trial',
                trial_start=datetime.now(timezone.utc),
                trial_end=datetime.now(timezone.utc) + timedelta(days=current_app.config['TRIAL_DAYS']),
            )
            db.session.add(sub)
            db.session.commit()

        logger.info(f'Google login successful: user={user.id} email={email}')
        return redirect(url_for('main.dashboard'))

    except Exception as e:
        logger.error(f'Google callback unhandled error: {e}', exc_info=True)
        return f'<h1>Belépés hiba</h1><p>{e}</p>', 500


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flask_session.clear()
    return redirect(url_for('main.dashboard'))