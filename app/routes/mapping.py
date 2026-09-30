from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import TaxMapping, AuditTrail, ClientProfile, ThresholdAlert, OnboardingChecklist
from app.rag.thresholds import DEFAULT_TAX_MAP, check_client_thresholds
from datetime import datetime, timezone
import json

bp = Blueprint('mapping', __name__, url_prefix='/mapping')


@bp.route('/')
@login_required
def mapping_page():
    mappings = TaxMapping.query.filter_by(user_id=current_user.id, is_active=True)\
        .order_by(TaxMapping.client_name, TaxMapping.internal_code).all()
    clients = ClientProfile.query.filter_by(user_id=current_user.id, is_active=True).all()
    return render_template('mapping.html', mappings=mappings, clients=clients, defaults=DEFAULT_TAX_MAP)


@bp.route('/api/list')
@login_required
def api_list():
    client = request.args.get('client', 'default')
    mappings = TaxMapping.query.filter_by(
        user_id=current_user.id, client_name=client
    ).order_by(TaxMapping.internal_code).all() if client else TaxMapping.query.filter_by(user_id=current_user.id).all()

    return jsonify([{
        'id': m.id,
        'internal_code': m.internal_code,
        'nav_code': m.nav_code,
        'description': m.description,
        'vat_rate': m.vat_rate,
        'reverse_charge': m.reverse_charge,
        'approved_by': m.approved_by,
        'source': m.source,
        'client_name': m.client_name,
    } for m in mappings])


@bp.route('/api/suggest', methods=['POST'])
@login_required
def api_suggest():
    """AI adókód javaslat — a RAG-et használja a NAV füzetek alapján."""
    data = request.get_json()
    internal_code = data.get('internal_code', '').strip()
    description = data.get('description', '').strip()

    # AI-based suggestion using RAG context
    from app.agents.accountant import AccountantAgent
    agent = AccountantAgent()
    prompt = (
        f"Az alábbi belső könyvelési kategóriához keresek NAV adókódot.\n"
        f"Belső kód: {internal_code}\n"
        f"Leírás: {description}\n\n"
        f"A lehetséges NAV adókódok a következők (NAV eÁFA sztenderd):\n"
        f"AAM = Általános adókulcsos (27% / 5% / 18%)\n"
        f"EAM = EU-s termékértékesítés / szolgáltatás (0%, fordított adózás)\n"
        f"TAM = Harmadik ország (0%)\n"
        f"FAD = Fordított adózás\n"
        f"ADM = Adómentes (pl. pénzügyi)\n"
        f"KBA = Különbözet szerinti áfa (használt cikk)\n\n"
        f"Válasz formátuma:\n"
        f"nav_code: [kód]\n"
        f"vat_rate: [%]\n"
        f"reverse_charge: [igen/nem]\n"
        f"indoklás: [röviden]"
    )

    suggestion_text, _ = agent.generate(
        [{'role': 'user', 'content': prompt}]
    )

    return jsonify({
        'suggestion': suggestion_text,
        'internal_code': internal_code,
    })


@bp.route('/api/save', methods=['POST'])
@login_required
def api_save():
    data = request.get_json()
    internal_code = data.get('internal_code', '').strip()
    nav_code = data.get('nav_code', '').strip().upper()
    vat_rate = data.get('vat_rate', '27%')
    reverse_charge = data.get('reverse_charge', False)
    description = data.get('description', '')
    client_name = data.get('client_name', 'default')
    source = data.get('source', 'ai_suggestion')
    reason = data.get('reason', '')

    if not internal_code or not nav_code:
        return jsonify({'error': 'Hiányzó adatok'}), 400

    # Check existing
    existing = TaxMapping.query.filter_by(
        user_id=current_user.id, client_name=client_name, internal_code=internal_code
    ).first()

    old_value = ''
    if existing:
        old_value = json.dumps({
            'nav_code': existing.nav_code, 'vat_rate': existing.vat_rate,
            'reverse_charge': existing.reverse_charge, 'approved_by': existing.approved_by,
        })
        existing.nav_code = nav_code
        existing.vat_rate = vat_rate
        existing.reverse_charge = bool(reverse_charge)
        existing.description = description
        existing.approved_by = 'human'
        existing.approved_at = datetime.now(timezone.utc)
        existing.source = source
        existing.updated_at = datetime.now(timezone.utc)
    else:
        mapping = TaxMapping(
            user_id=current_user.id, client_name=client_name,
            internal_code=internal_code, nav_code=nav_code,
            vat_rate=vat_rate, reverse_charge=bool(reverse_charge),
            description=description, source=source, approved_by='human',
        )
        db.session.add(mapping)

    db.session.commit()

    # Audit trail
    new_value = json.dumps({
        'nav_code': nav_code, 'vat_rate': vat_rate,
        'reverse_charge': bool(reverse_charge), 'approved_by': 'human',
    })
    audit = AuditTrail(
        user_id=current_user.id, action='mapping_change',
        entity_type='tax_mapping', entity_id=existing.id if existing else 0,
        old_value=old_value, new_value=new_value,
        reason=reason,
        ip_address=request.remote_addr or '',
    )
    db.session.add(audit)
    db.session.commit()

    return jsonify({'ok': True})


@bp.route('/api/audit')
@login_required
def api_audit():
    limit = request.args.get('limit', 100, type=int)
    entity_type = request.args.get('entity_type', '')
    query = AuditTrail.query.filter_by(user_id=current_user.id)
    if entity_type:
        query = query.filter_by(entity_type=entity_type)
    logs = query.order_by(AuditTrail.created_at.desc()).limit(limit).all()

    return jsonify([{
        'id': a.id,
        'action': a.action,
        'entity_type': a.entity_type,
        'old_value': a.old_value,
        'new_value': a.new_value,
        'reason': a.reason,
        'created_at': a.created_at.isoformat() if a.created_at else None,
    } for a in logs])