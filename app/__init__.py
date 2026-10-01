from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
from apscheduler.schedulers.background import BackgroundScheduler
import os
import atexit

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
scheduler = BackgroundScheduler(daemon=True)
scheduler.start()
atexit.register(lambda: scheduler.shutdown(wait=False))


def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')

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
        from app import models
        db.create_all()

        # Auto-migration: add columns if needed
        from sqlalchemy import inspect, text as sa_text
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()

        if 'search_log' in tables:
            cols = [c['name'] for c in inspector.get_columns('search_log')]
            if 'ip_address' not in cols:
                with db.engine.connect() as conn:
                    conn.execute(sa_text('ALTER TABLE search_log ADD COLUMN ip_address VARCHAR(45) DEFAULT \'\''))
                    conn.commit()

    # Context processor for templates
    @app.context_processor
    def inject_now():
        from datetime import datetime, timezone
        return {'now': lambda: datetime.now(timezone.utc)}

    # Schedule daily document collection (06:00 CET = 04:00 UTC during CEST)
    def run_collector_job():
        with app.app_context():
            try:
                import sys
                sys.path.insert(0, app.root_path + '/..')
                from collectors.run import run
                run()
            except Exception as e:
                app.logger.error(f'Collector job failed: {e}')

    # Add job (runs daily at 04:00 UTC = 06:00 CEST)
    try:
        scheduler.add_job(
            func=run_collector_job,
            trigger='cron',
            hour=4,
            minute=0,
            id='konyvelo_daily_collector',
            replace_existing=True,
            misfire_grace_time=3600,
        )
    except Exception as e:
        app.logger.warning(f'Scheduler init failed (non-fatal): {e}')

    return app