#!/usr/bin/env python3
"""
KönyvelőAI admin CLI — jelszó reset, felhasználók listája, admin beállítás.

Használat:
  python3 manage.py users                      # felhasználók listája
  python3 manage.py reset-password <email>     # új jelszó (interaktív vagy env: NEW_PASSWORD)
  python3 manage.py make-admin <email>         # admin flag beállítása
  python3 manage.py set-trial <email> <days>   # próbaidő beállítása
"""
import sys
import os
import getpass
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, Subscription
from datetime import datetime, timezone, timedelta


def cmd_users(app):
    with app.app_context():
        users = User.query.order_by(User.id).all()
        if not users:
            print('Nincs felhasználó.')
            return
        print(f'{"ID":<5} {"Email":<35} {"Név":<25} {"Admin":<6} {"Létrehozva":<20}')
        print('-' * 95)
        for u in users:
            created = u.created_at.strftime('%Y.%m.%d %H:%M') if u.created_at else '-'
            print(f'{u.id:<5} {u.email:<35} {u.name:<25} {"igen" if u.is_admin else "nem":<6} {created:<20}')


def cmd_reset_password(app, email):
    with app.app_context():
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            print(f'❌ Nincs ilyen felhasználó: {email}')
            return 1

        new_pw = os.environ.get('NEW_PASSWORD')
        if not new_pw:
            pw1 = getpass.getpass('Új jelszó: ')
            pw2 = getpass.getpass('Új jelszó újra: ')
            if pw1 != pw2:
                print('❌ A jelszavak nem egyeznek.')
                return 1
            new_pw = pw1

        if len(new_pw) < 6:
            print('❌ A jelszó legalább 6 karakter legyen.')
            return 1

        user.set_password(new_pw)
        db.session.commit()
        print(f'✅ {user.email} jelszava megváltoztatva.')
        return 0


def cmd_make_admin(app, email):
    with app.app_context():
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            print(f'❌ Nincs ilyen felhasználó: {email}')
            return 1
        user.is_admin = True
        db.session.commit()
        print(f'✅ {user.email} mostantól admin.')
        return 0


def cmd_set_trial(app, email, days):
    with app.app_context():
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            print(f'❌ Nincs ilyen felhasználó: {email}')
            return 1
        sub = Subscription.query.filter_by(user_id=user.id).first()
        if not sub:
            sub = Subscription(user_id=user.id)
            db.session.add(sub)
        sub.status = 'trial'
        sub.trial_start = datetime.now(timezone.utc)
        sub.trial_end = datetime.now(timezone.utc) + timedelta(days=int(days))
        db.session.commit()
        print(f'✅ {user.email} próbaidő: {days} nap (eddig: {sub.trial_end.strftime("%Y.%m.%d")})')
        return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]
    app = create_app()

    if cmd == 'users':
        cmd_users(app)
    elif cmd == 'reset-password' and len(sys.argv) >= 3:
        return cmd_reset_password(app, sys.argv[2])
    elif cmd == 'make-admin' and len(sys.argv) >= 3:
        return cmd_make_admin(app, sys.argv[2])
    elif cmd == 'set-trial' and len(sys.argv) >= 4:
        return cmd_set_trial(app, sys.argv[2], sys.argv[3])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())