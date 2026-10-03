import os
import hashlib
from dotenv import load_dotenv

load_dotenv()


class Config:
    # SECRET_KEY: ha nincs beállítva env var-ba, stabil fallback (fájlpath + konstans)
    # Ezért a session nem elvesz a container restart után
    _fallback_key = hashlib.sha256(
        (__file__ + '::konyveloai-secret-v1').encode()
    ).hexdigest()[:32]

    SECRET_KEY = os.environ.get('SECRET_KEY', _fallback_key)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'konyveloai.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DOMAIN = os.environ.get('DOMAIN', 'http://localhost:8770')

    # Session cookie — HTTPS hez
    SESSION_COOKIE_SECURE = os.environ.get('DOMAIN', '').startswith('https://')
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')
    OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL', 'deepseek/deepseek-v4-flash:free')
    OPENROUTER_BASE_URL = 'https://openrouter.ai/api/v1'

    # RAG
    CHROMA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'chroma')
    EMBEDDING_MODEL = 'intfloat/multilingual-e5-small'
    RAG_TOP_K = 5
    RAG_SIMILARITY_THRESHOLD = 0.45

    # Stripe (előkészítve, még nem aktív)
    STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY', '')
    STRIPE_PUBLISHABLE_KEY = os.environ.get('STRIPE_PUBLISHABLE_KEY', '')
    STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

    # Próbaidőszak
    TRIAL_DAYS = int(os.environ.get('TRIAL_DAYS', '30'))

    # Admin (ha ez nem beállítva, a /admin elérhetetlen)
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', '')

    # ── E-mail (jelszó-emlékeztetőhöz) ──
    # Ha SMTP_HOST nincs beállítva, a reset link nem e-mailben megy,
    # hanem a szerver logba íródik (fejlesztés / első beállítás).
    SMTP_HOST = os.environ.get('SMTP_HOST', '')
    SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
    SMTP_USER = os.environ.get('SMTP_USER', '')
    SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD', '')
    SMTP_FROM = os.environ.get('SMTP_FROM', SMTP_USER)
    SMTP_USE_TLS = os.environ.get('SMTP_USE_TLS', 'true').lower() in ('1', 'true', 'yes')
    MAIL_FROM_NAME = os.environ.get('MAIL_FROM_NAME', 'KönyvelőAI')

    # Jelszó reset token élettartam (perc)
    RESET_TOKEN_EXPIRY_MINUTES = int(os.environ.get('RESET_TOKEN_EXPIRY_MINUTES', '60'))