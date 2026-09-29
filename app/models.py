from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime, timezone
import json


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(20), nullable=False, default='google')
    provider_id = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    avatar = db.Column(db.String(500), default='')
    role = db.Column(db.String(20), default='')  # '' = not set
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (db.UniqueConstraint('provider', 'provider_id'),)


class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='trial')  # trial | active | cancelled
    trial_start = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    trial_end = db.Column(db.DateTime)
    plan_type = db.Column(db.String(20), default='monthly')
    stripe_subscription_id = db.Column(db.String(100), default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('subscription', uselist=False))


class SearchLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    query = db.Column(db.Text, nullable=False)
    ai_response = db.Column(db.Text, default='')
    sources_used = db.Column(db.Text, default='[]')  # JSON array
    sources_text = db.Column(db.Text, default='')  # Context chunks for fine-tuning
    response_time_ms = db.Column(db.Integer, default=0)
    ip_address = db.Column(db.String(45), default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('searches', lazy='dynamic'))

    def to_dict(self):
        return {
            'id': self.id,
            'query': self.query,
            'ai_response': self.ai_response,
            'sources_used': json.loads(self.sources_used) if self.sources_used else [],
            'context_text': self.sources_text[:2000] if self.sources_text else '',
            'response_time_ms': self.response_time_ms,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ChatSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(200), default='')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('chat_sessions', lazy='dynamic'))

    def get_messages(self):
        msgs = ChatMessage.query.filter_by(session_id=self.id).order_by(ChatMessage.created_at).all()
        return [{'role': m.role, 'content': m.content, 'sources': m.get_sources_json()} for m in msgs]


class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('chat_session.id'), nullable=False)
    role = db.Column(db.String(10), nullable=False)  # user | assistant
    content = db.Column(db.Text, nullable=False)
    sources_json = db.Column(db.Text, default='[]')  # JSON: source docs used
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    session = db.relationship('ChatSession', backref=db.backref('messages', lazy='dynamic'))

    def get_sources_json(self):
        try:
            return json.loads(self.sources_json) if self.sources_json else []
        except (json.JSONDecodeError, TypeError):
            return []


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))