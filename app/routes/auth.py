from flask import Blueprint, render_template, redirect, url_for, request, flash, session as flask_session, current_app
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, Subscription, PasswordResetToken
from app.mailer import send_password_reset, is_configured as mail_configured
from datetime import datetime, timezone, timedelta
import hashlib
import secrets

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'GET':
        return render_template('login.html')

    email = request.form.get('email', '').strip().lower()
    password = request.form.get('password', '')

    if not email or not password:
        flash('Add meg az e-mailt és a jelszót!', 'error')
        return render_template('login.html')

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash('Érvénytelen e-mail vagy jelszó.', 'error')
        return render_template('login.html')

    login_user(user)
    next_url = request.args.get('next') or url_for('main.dashboard')
    return redirect(next_url)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'GET':
        return render_template('register.html')

    email = request.form.get('email', '').strip().lower()
    name = request.form.get('name', '').strip()
    password = request.form.get('password', '')
    confirm = request.form.get('confirm', '')

    if not email or not name or not password:
        flash('Minden mező feltétele kötelező!', 'error')
        return render_template('register.html')

    if password != confirm:
        flash('A jelszavak nem egyeznek!', 'error')
        return render_template('register.html')

    if len(password) < 6:
        flash('A jelszó legalább 6 karakter hosszú legyen!', 'error')
        return render_template('register.html')

    existing = User.query.filter_by(email=email).first()
    if existing:
        flash('Ez e-mail már regisztrálva.', 'error')
        return render_template('register.html')

    admin_email = (current_app.config.get('ADMIN_EMAIL') or '').strip().lower()
    user = User(email=email, name=name, is_admin=bool(admin_email and admin_email == email))
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    trial_days = int(current_app.config.get('TRIAL_DAYS', 30))
    sub = Subscription(
        user_id=user.id, status='trial',
        trial_start=datetime.now(timezone.utc),
        trial_end=datetime.now(timezone.utc) + timedelta(days=trial_days),
    )
    db.session.add(sub)
    db.session.commit()

    login_user(user)
    flash('Regisztráció sikeres!', 'success')
    return redirect(url_for('main.dashboard'))


@bp.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    """Jelszó-emlékeztető kérése."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    mail_ok = mail_configured()

    if request.method == 'GET':
        return render_template('forgot.html', mail_ok=mail_ok)

    email = request.form.get('email', '').strip().lower()
    if not email:
        flash('Add meg az e-mail címed!', 'error')
        return render_template('forgot.html', mail_ok=mail_ok)

    user = User.query.filter_by(email=email).first()

    # Biztonsági okokból mindig ugyanaz a válasz (nem szivárogtatjuk ki, létezik-e a fiók)
    generic_msg = ('Ha létezik fiók ezzel az e-mail címmel, elküldtük a '
                   'jelszó-visszaállítási linket. Ellenőrizd a postaládádat (és a spam mappát is).')

    if user:
        # Token generálás
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expiry_min = current_app.config['RESET_TOKEN_EXPIRY_MINUTES']

        # Régi tokenek érvénytelenítése
        PasswordResetToken.query.filter_by(user_id=user.id, used=False).update({'used': True})

        reset_token = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            ip_address=request.remote_addr or '',
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=expiry_min),
        )
        db.session.add(reset_token)
        db.session.commit()

        domain = current_app.config['DOMAIN'].rstrip('/')
        reset_url = f'{domain}/auth/reset/{raw_token}'

        ok, info = send_password_reset(user.email, user.name, reset_url, expiry_min)

        if not ok and info == 'smtp_not_configured':
            current_app.logger.warning(
                f'=== JELSZÓ RESET LINK (SMTP nincs beállítva) ===\n'
                f'Felhasználó: {user.email}\nLink: {reset_url}\n'
                f'Érvényes: {expiry_min} perc\n'
                f'=== / JELSZÓ RESET LINK ==='
            )
            # Fejlesztői/első-beállítási mód: mutassuk a linket a felületen,
            # de CSAK admin fiók esetén (ADMIN_EMAIL egyezés VAGY is_admin flag).
            admin_email = (current_app.config.get('ADMIN_EMAIL') or '').strip().lower()
            is_admin = bool(user.is_admin) or (bool(admin_email) and admin_email == email)
            if is_admin:
                flash('SMTP nincs beállítva. Admin módban a link közvetlenül itt látható:', 'error')
                return render_template('forgot.html', mail_ok=mail_ok, dev_reset_url=reset_url)
            flash('Az e-mail küldés jelenleg nincs beállítva. Vedd fel a kapcsolatot az adminnal.', 'error')
            return render_template('forgot.html', mail_ok=mail_ok, smtp_missing=True)

        if ok:
            flash(generic_msg, 'success')
            return render_template('forgot.html', mail_ok=mail_ok)

        # Egyéb küldési hiba
        current_app.logger.error(f'Reset e-mail küldés hiba: {info}')
        flash('Az e-mail küldése nem sikerült. Próbáld újra később, vagy vedd fel a kapcsolatot az adminnal.', 'error')
        return render_template('forgot.html', mail_ok=mail_ok)

    flash(generic_msg, 'success')
    return render_template('forgot.html', mail_ok=mail_ok)


@bp.route('/reset/<token>', methods=['GET', 'POST'])
def reset_password(token):
    """Jelszó visszaállítás tokennel."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    reset_token = PasswordResetToken.query.filter_by(token_hash=token_hash).first()

    if not reset_token or not reset_token.is_valid():
        return render_template('reset.html', invalid=True)

    if request.method == 'GET':
        return render_template('reset.html', invalid=False, token=token)

    password = request.form.get('password', '')
    confirm = request.form.get('confirm', '')

    if not password or len(password) < 6:
        flash('A jelszó legalább 6 karakter hosszú legyen!', 'error')
        return render_template('reset.html', invalid=False, token=token)

    if password != confirm:
        flash('A jelszavak nem egyeznek!', 'error')
        return render_template('reset.html', invalid=False, token=token)

    user = db.session.get(User, reset_token.user_id)
    user.set_password(password)
    reset_token.used = True
    db.session.commit()

    current_app.logger.info(f'Jelszó visszaállítva: user={user.id} email={user.email}')
    flash('A jelszavad sikeresen megváltozott. Most már be tudsz lépni.', 'success')
    return redirect(url_for('auth.login'))


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flask_session.clear()
    return redirect(url_for('main.dashboard'))