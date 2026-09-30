import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', os.urandom(24).hex())
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'konyveloai.db')
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    DOMAIN = os.environ.get('DOMAIN', 'http://localhost:8770')

    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', '')
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', '')

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