from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler
import os
import atexit
import logging
import time as _time

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
scheduler = BackgroundScheduler(daemon=True)
_atexit_registered = False


def _init_db_safely(app):
    """Idempotens DB init — több gunicorn worker esetén sem hal el.

    A 'table already exists' versenyhelyzetet kezeli (checkfirst=True mellett is
    előfordulhat race két worker között), ezért try/except + retry.
    """
    from sqlalchemy import inspect, text as sa_text
    from sqlalchemy.exc import OperationalError, ProgrammingError

    for attempt in range(3):
        try:
            db.create_all()
            break
        except (OperationalError, ProgrammingError) as e:
            if 'already exists' in str(e).lower():
                app.logger.warning(f'create_all race (attempt {attempt + 1}) — folytatás.')
                _time.sleep(0.5)
                continue
            raise

    # Auto-migration: hiányzó oszlopok pótlása (idempotens)
    try:
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        migrations = [
            ('search_log', 'ip_address', "ALTER TABLE search_log ADD COLUMN ip_address VARCHAR(45) DEFAULT ''"),
            ('user', 'is_admin', "ALTER TABLE user ADD COLUMN is_admin BOOLEAN DEFAULT 0"),
        ]
        for table, column, ddl in migrations:
            if table not in tables:
                continue
            cols = [c['name'] for c in inspector.get_columns(table)]
            if column not in cols:
                with db.engine.connect() as conn:
                    conn.execute(sa_text(ddl))
                    conn.commit()
                app.logger.info(f'Migráció: {table}.{column} hozzáadva.')
    except Exception as e:
        app.logger.warning(f'Auto-migration kihagyva: {e}')


def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')

    logging.basicConfig(level=logging.INFO)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'

    with app.app_context():
        from app.routes import auth, main, admin, mapping, clients, subscription
        app.register_blueprint(auth.bp)
        app.register_blueprint(main.bp)
        app.register_blueprint(admin.bp)
        app.register_blueprint(mapping.bp)
        app.register_blueprint(clients.bp)
        app.register_blueprint(subscription.bp)
        from app import models  # noqa: F401
        _init_db_safely(app)

    # Context processor — sablonokban elérhető segédfüggvények
    @app.context_processor
    def inject_globals():
        from datetime import datetime, timezone
        from app.routes.admin import is_admin_user
        return {
            'now': lambda: datetime.now(timezone.utc),
            'is_admin_user': is_admin_user,
        }

    # ── Napi adatgyűjtés (04:00 UTC = 06:00 CEST) ──
    def run_collector_job():
        with app.app_context():
            try:
                from collectors.run import run
                run()
                app.logger.info('Napi adatgyűjtés kész.')
            except Exception as e:
                app.logger.error(f'Collector job failed: {e}', exc_info=True)

    try:
        from apscheduler.triggers.cron import CronTrigger
        scheduler.add_job(
            func=run_collector_job,
            trigger=CronTrigger(hour=4, minute=0),
            id='konyvelo_daily_collector',
            replace_existing=True,
            misfire_grace_time=3600,
            max_instances=1,
        )
    except Exception as e:
        app.logger.warning(f'Scheduler init failed (non-fatal): {e}')

    global _atexit_registered
    if not _atexit_registered:
        try:
            if not scheduler.running:
                scheduler.start()
            atexit.register(lambda: scheduler.shutdown(wait=False) if scheduler.running else None)
            _atexit_registered = True
        except Exception as e:
            app.logger.warning(f'Scheduler start failed (non-fatal): {e}')

    return app
