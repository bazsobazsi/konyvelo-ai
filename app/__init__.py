from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix
import os

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
oauth = OAuth()


def create_app():
    app = Flask(__name__)
    app.config.from_object('app.config.Config')

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.google_login'
    oauth.init_app(app)

    oauth.register(
        name='google',
        client_id=app.config['GOOGLE_CLIENT_ID'],
        client_secret=app.config['GOOGLE_CLIENT_SECRET'],
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'},
    )

    with app.app_context():
        from app.routes import auth, main, admin
        app.register_blueprint(auth.bp)
        app.register_blueprint(main.bp)
        app.register_blueprint(admin.bp)
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

    return app