from flask import Blueprint, render_template, redirect, url_for, request, flash, session as flask_session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models import User, Subscription
from datetime import datetime, timezone, timedelta

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
        flash('Add meg az e-mailt és a parolt!', 'error')
        return render_template('login.html')

    user = User.query.filter_by(email=email).first()
    if not user or not user.check_password(password):
        flash('Érvénytelen e-mail vagy parol.', 'error')
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
        flash('A parolok nem egyeznek!', 'error')
        return render_template('register.html')

    if len(password) < 6:
        flash('A parol minimum 6 karakter hosszú kelljen!', 'error')
        return render_template('register.html')

    existing = User.query.filter_by(email=email).first()
    if existing:
        flash('Ez e-mail már regisztrálva.', 'error')
        return render_template('register.html')

    user = User(email=email, name=name)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    sub = Subscription(
        user_id=user.id, status='trial',
        trial_start=datetime.now(timezone.utc),
        trial_end=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.session.add(sub)
    db.session.commit()

    login_user(user)
    flash('Regisztráció sikeres!', 'success')
    return redirect(url_for('main.dashboard'))


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flask_session.clear()
    return redirect(url_for('main.dashboard'))