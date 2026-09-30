from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import ClientProfile, ThresholdAlert, OnboardingChecklist, AuditTrail
from app.rag.thresholds import check_client_thresholds
from datetime import datetime, timezone
import json

bp = Blueprint('clients', __name__, url_prefix='/clients')


# ── Ügyfél profilok ──

@bp.route('/')
@login_required
def clients_page():
    clients = ClientProfile.query.filter_by(user_id=current_user.id, is_active=True)\
        .order_by(ClientProfile.name).all()
    alerts = ThresholdAlert.query.filter_by(user_id=current_user.id, dismissed=False)\
        .order_by(ThresholdAlert.created_at.desc()).limit(20).all()
    return render_template('clients.html', clients=clients, alerts=alerts)


@bp.route('/api/list')
@login_required
def api_clients():
    clients = ClientProfile.query.filter_by(user_id=current_user.id).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'tax_number': c.tax_number or '',
        'profile_type': c.profile_type,
        'annual_revenue': c.annual_revenue,
        'employee_count': c.employee_count,
        'vat_quarterly': c.vat_quarterly,
        'vat_exempt': c.vat_exempt,
        'kiva_elective': c.kiva_elective,
        'is_active': c.is_active,
    } for c in clients])


@bp.route('/api/save', methods=['POST'])
@login_required
def api_save():
    data = request.get_json()
    client_id = data.get('id')
    name = data.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Ügyfél név kötelező'}), 400

    old_values = {}

    if client_id:
        client = ClientProfile.query.get_or_404(client_id)
        if client.user_id != current_user.id:
            return jsonify({'error': 'Hozzáférés megtagadva'}), 403
        old_values = {c.name: getattr(client, c.name) for c in ClientProfile.__table__.columns
                      if c.name not in ('id', 'user_id', 'created_at')}
        client.name = name
        client.tax_number = data.get('tax_number', '')
        client.profile_type = data.get('profile_type', 'kft')
        client.annual_revenue = int(data.get('annual_revenue', 0))
        client.employee_count = int(data.get('employee_count', 0))
        client.vat_quarterly = data.get('vat_quarterly', False)
        client.vat_exempt = data.get('vat_exempt', False)
        client.kiva_elective = data.get('kiva_elective', False)
        client.notes = data.get('notes', '')
    else:
        client = ClientProfile(
            user_id=current_user.id, name=name,
            tax_number=data.get('tax_number', ''),
            profile_type=data.get('profile_type', 'kft'),
            annual_revenue=int(data.get('annual_revenue', 0)),
            employee_count=int(data.get('employee_count', 0)),
            vat_quarterly=data.get('vat_quarterly', False),
            vat_exempt=data.get('vat_exempt', False),
            kiva_elective=data.get('kiva_elective', False),
            notes=data.get('notes', ''),
        )
        db.session.add(client)

    db.session.commit()

    # Audit trail
    action = 'profile_edit' if client_id else 'profile_create'
    audit = AuditTrail(
        user_id=current_user.id, action=action,
        entity_type='client_profile', entity_id=client.id,
        old_value=json.dumps(old_values, ensure_ascii=False) if old_values else '',
        new_value=json.dumps({'name': name, 'type': client.profile_type}, ensure_ascii=False),
        ip_address=request.remote_addr or '',
    )
    db.session.add(audit)

    # Check thresholds
    alerts = check_client_thresholds(client)
    alert_ids = []
    for a in alerts:
        existing = ThresholdAlert.query.filter_by(
            user_id=current_user.id, client_id=client.id,
            threshold_type=a['type'], dismissed=False,
        ).first()
        if not existing:
            alert = ThresholdAlert(
                user_id=current_user.id, client_id=client.id,
                threshold_type=a['type'], threshold_name=a['name'],
                current_value=a['current'], limit_value=a['limit'],
                direction=a['direction'], severity=a['severity'],
            )
            db.session.add(alert)
            db.session.commit()
            alert_ids.append(alert.id)

    db.session.commit()
    return jsonify({'ok': True, 'id': client.id, 'new_alerts': len(alert_ids)})


@bp.route('/api/delete/<int:client_id>', methods=['DELETE'])
@login_required
def api_delete(client_id):
    client = ClientProfile.query.get_or_404(client_id)
    if client.user_id != current_user.id:
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403
    client.is_active = False
    ThresholdAlert.query.filter_by(client_id=client_id).update({'dismissed': True})
    db.session.commit()
    return jsonify({'ok': True})


# ── Threshold alerts ──

@bp.route('/api/alerts')
@login_required
def api_alerts():
    alerts = ThresholdAlert.query.filter_by(user_id=current_user.id, dismissed=False)\
        .order_by(ThresholdAlert.created_at.desc()).limit(50).all()
    return jsonify([{
        'id': a.id,
        'client_name': a.client.name if a.client else 'N/A',
        'threshold_type': a.threshold_type,
        'threshold_name': a.threshold_name,
        'current_value': a.current_value,
        'limit_value': a.limit_value,
        'direction': a.direction,
        'severity': a.severity,
        'created_at': a.created_at.isoformat() if a.created_at else None,
    } for a in alerts])


@bp.route('/api/alerts/dismiss/<int:alert_id>', methods=['POST'])
@login_required
def api_dismiss(alert_id):
    alert = ThresholdAlert.query.get_or_404(alert_id)
    if alert.user_id != current_user.id:
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403
    alert.dismissed = True
    db.session.commit()
    return jsonify({'ok': True})


# ── Onboarding checklist ──

@bp.route('/onboarding')
@login_required
def onboarding_page():
    steps = OnboardingChecklist.query.filter_by(user_id=current_user.id)\
        .order_by(OnboardingChecklist.step_order).all()
    clients = ClientProfile.query.filter_by(user_id=current_user.id, is_active=True).all()
    return render_template('onboarding.html', steps=steps, clients=clients)


@bp.route('/api/onboarding/init/<int:client_id>', methods=['POST'])
@login_required
def api_onboarding_init(client_id):
    """Create default onboarding steps for a new client."""
    client = ClientProfile.query.get_or_404(client_id)
    if client.user_id != current_user.id:
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403

    default_steps = [
        {'name': 'Ügyfél adatok rögzítése', 'order': 1},
        {'name': 'Adókör megállapítása', 'order': 2},
        {'name': 'Adókód-mapping beállítása', 'order': 3},
        {'name': 'NAV regisztráció ellenőrzése', 'order': 4},
        {'name': 'Online Számla technikai felhasználó', 'order': 5},
        {'name': 'eÁFA M2M szerepkörök', 'order': 6},
        {'name': 'Teszt-beküldés', 'order': 7},
    ]

    created = 0
    for step in default_steps:
        existing = OnboardingChecklist.query.filter_by(
            user_id=current_user.id, client_id=client_id,
            step_name=step['name']
        ).first()
        if not existing:
            s = OnboardingChecklist(
                user_id=current_user.id, client_id=client_id,
                step_name=step['name'], step_order=step['order'],
            )
            db.session.add(s)
            created += 1

    db.session.commit()
    return jsonify({'ok': True, 'created': created})


@bp.route('/api/onboarding/update/<int:step_id>', methods=['POST'])
@login_required
def api_onboarding_update(step_id):
    step = OnboardingChecklist.query.get_or_404(step_id)
    if step.user_id != current_user.id:
        return jsonify({'error': 'Hozzáférés megtagadva'}), 403

    data = request.get_json()
    step.status = data.get('status', step.status)
    step.assigned_to = data.get('assigned_to', step.assigned_to)
    step.notes = data.get('notes', step.notes)
    if step.status == 'done' and not step.completed_at:
        step.completed_at = datetime.now(timezone.utc)

    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/api/onboarding/list')
@login_required
def api_onboarding_list():
    client_id = request.args.get('client_id', type=int)
    query = OnboardingChecklist.query.filter_by(user_id=current_user.id)
    if client_id:
        query = query.filter_by(client_id=client_id)
    steps = query.order_by(OnboardingChecklist.client_id, OnboardingChecklist.step_order).all()

    return jsonify([{
        'id': s.id,
        'client_name': s.client.name if s.client else 'N/A',
        'step_name': s.step_name,
        'step_order': s.step_order,
        'status': s.status,
        'assigned_to': s.assigned_to,
        'notes': s.notes,
        'completed_at': s.completed_at.isoformat() if s.completed_at else None,
    } for s in steps])