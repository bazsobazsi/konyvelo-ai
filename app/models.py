from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
import json


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    avatar = db.Column(db.String(500), default='')
    is_admin = db.Column(db.Boolean, default=False)  # admin flag (email-based)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


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
    search_query = db.Column('query', db.Text, nullable=False)
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
            'query': self.search_query,
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


# ── Phase 2 models ──────────────────────────────

class AuditTrail(db.Model):
    """Minden változás naplózása: ki, mikor, mit, miért, kontextus."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)   # mapping_change | threshold_alert | onboarding | profile_edit
    entity_type = db.Column(db.String(50), default='')  # tax_mapping | client_profile | threshold
    entity_id = db.Column(db.Integer, default=0)
    old_value = db.Column(db.Text, default='')
    new_value = db.Column(db.Text, default='')
    reason = db.Column(db.Text, default='')              # Miért? (emberi indok)
    ip_address = db.Column(db.String(45), default='')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('audit_logs', lazy='dynamic'))


class TaxMapping(db.Model):
    """Adókód mapping: belső kategória → NAV sztenderd kód, ügyfél-specifikus felülírásokkal."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    client_name = db.Column(db.String(200), default='default')
    internal_code = db.Column(db.String(50), nullable=False)       # pl. "BELFOLD_IRODAI_SZOLGALTATAS"
    nav_code = db.Column(db.String(50), nullable=False)            # NAV adókód
    description = db.Column(db.String(500), default='')
    vat_rate = db.Column(db.String(10), default='27%')
    reverse_charge = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    approved_by = db.Column(db.String(100), default='ai')          # 'ai' | 'human'
    approved_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    source = db.Column(db.String(50), default='manual')            # ai_suggestion | template | manual
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('tax_mappings', lazy='dynamic'))
    __table_args__ = (db.UniqueConstraint('user_id', 'client_name', 'internal_code'),)


class ClientProfile(db.Model):
    """Ügyfél profil: adókör, sablon, határérték-figyeléshez."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    tax_number = db.Column(db.String(20), default='')
    profile_type = db.Column(db.String(30), default='kft')  # ev | kft | kiva | afakoros | alanyi_mentes
    annual_revenue = db.Column(db.Integer, default=0)       # forint
    employee_count = db.Column(db.Integer, default=0)
    vat_quarterly = db.Column(db.Boolean, default=False)    # negyedéves áfás?
    vat_exempt = db.Column(db.Boolean, default=False)       # alanyi mentes?
    kiva_elective = db.Column(db.Boolean, default=False)     # KIVA választott?
    notes = db.Column(db.Text, default='')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('clients', lazy='dynamic'))


class ThresholdAlert(db.Model):
    """Határérték-figyelő riasztások: mikor melyik ügyfél érint egy küszöböt."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('client_profile.id'), nullable=True)
    threshold_type = db.Column(db.String(50), nullable=False)  # alanyi_mentes | kiva_headcount | quarterly_vat
    threshold_name = db.Column(db.String(200), default='')
    current_value = db.Column(db.String(50), default='')
    limit_value = db.Column(db.String(50), default='')
    direction = db.Column(db.String(10), default='above')      # above | below | approaching
    severity = db.Column(db.String(20), default='info')        # info | warning | critical
    dismissed = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('threshold_alerts', lazy='dynamic'))
    client = db.relationship('ClientProfile', backref=db.backref('alerts', lazy='dynamic'))


class OnboardingChecklist(db.Model):
    """Regisztrációs checklist ügyfelenként."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey('client_profile.id'), nullable=True)
    step_name = db.Column(db.String(200), nullable=False)
    step_order = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='pending')      # pending | in_progress | done | skipped
    assigned_to = db.Column(db.String(100), default='')
    notes = db.Column(db.Text, default='')
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship('User', backref=db.backref('onboarding_steps', lazy='dynamic'))