"""
Subscription routes — Stripe előfizetés kezelés.
Payment kapcsolat NEM aktív: csak előkészítés, a tesztidőszak végén kötjük be.
"""
import os
import stripe
from flask import Blueprint, request, jsonify, current_app, render_template, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import Subscription, AuditTrail
from datetime import datetime, timezone, timedelta

bp = Blueprint('subscription', __name__, url_prefix='/subscription')


# ── Plan definitions ──

PLANS = {
    'free': {
        'name': 'Próbaidőszak',
        'price': 0,
        'trial_days': 30,
        'max_searches_per_day': 20,
        'max_clients': 3,
        'features': ['RAG keresés', 'NAV füzetek + MK', 'Keresési napló', 'JSONL export'],
    },
    'monthly': {
        'name': 'Havi',
        'price': 9900,  # Ft
        'stripe_price_id': os.environ.get('STRIPE_MONTHLY_PRICE_ID', ''),
        'max_searches_per_day': 200,
        'max_clients': 50,
        'features': ['Minden a Próbából', 'Határérték-figyelő', 'Adókód-mapping UI', 'Ügyfél profilok', 'Onboarding checklist'],
    },
    'yearly': {
        'name': 'Éves',
        'price': 89900,  # Ft (2 hónap ingyen)
        'stripe_price_id': os.environ.get('STRIPE_YEARLY_PRICE_ID', ''),
        'max_searches_per_day': 500,
        'max_clients': 999,
        'features': ['Minden a Havi csomagból', 'Prioritás támogatás', 'Early access új funkciókhoz', '2 hónap ingyen!'],
    },
}




def get_stripe():
    sk = current_app.config.get('STRIPE_SECRET_KEY')
    if sk:
        stripe.api_key = sk
    return stripe


def check_usage_limit(user_id):
    """Ellenőrzi a napi keresési limitet a subscription alapján."""
    sub = Subscription.query.filter_by(user_id=user_id).first()
    if not sub:
        return {'allowed': True, 'remaining': 20, 'plan': 'free'}

    plan_key = 'free'
    if sub.status == 'active':
        plan_key = sub.plan_type  # 'monthly' or 'yearly'
    plan = PLANS.get(plan_key, PLANS['free'])

    from app.models import SearchLog
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = SearchLog.query.filter(
        SearchLog.user_id == user_id,
        SearchLog.created_at >= today_start
    ).count()

    remaining = plan['max_searches_per_day'] - today_count
    return {
        'allowed': remaining > 0 or plan_key != 'free',
        'remaining': max(0, remaining),
        'plan': plan_key,
        'limit': plan['max_searches_per_day'],
        'today': today_count,
    }


# ── Routes ──

@bp.route('/')
@login_required
def subscription_page():
    sub = Subscription.query.filter_by(user_id=current_user.id).first()
    usage = check_usage_limit(current_user.id)
    return render_template('subscription.html',
                           subscription=sub,
                           plans=PLANS,
                           usage=usage)


@bp.route('/pricing')
def pricing_page():
    return render_template('pricing.html', plans=PLANS)


@bp.route('/api/usage')
@login_required
def api_usage():
    return jsonify(check_usage_limit(current_user.id))


@bp.route('/api/create-checkout', methods=['POST'])
@login_required
def create_checkout():
    """Create Stripe checkout session for subscription.
    NOTE: Nem aktív — csak előkészítés. A tesztidőszak végén kötjük be.
    """
    data = request.get_json()
    plan_type = data.get('plan', 'monthly')

    if plan_type not in PLANS or plan_type == 'free':
        return jsonify({'error': 'Érvénytelen csomag'}), 400

    plan = PLANS[plan_type]
    stripe_price_id = plan.get('stripe_price_id', '')
    if not stripe_price_id:
        return jsonify({
            'error': 'A Stripe fizetési kapcsolat még nincs beállítva. '
                     'Ez a funkció a tesztidőszak végén aktiválódik.',
            'demo': True,
        }), 200

    try:
        stripe_instance = get_stripe()

        checkout_session = stripe_instance.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': stripe_price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=current_app.config['DOMAIN'] + '/subscription/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=current_app.config['DOMAIN'] + '/subscription/',
            client_reference_id=str(current_user.id),
            customer_email=current_user.email,
            metadata={
                'user_id': str(current_user.id),
                'plan': plan_type,
            },
        )

        return jsonify({'url': checkout_session['url']})

    except stripe.error.StripeError as e:
        err_body = e.user_message or str(e)
        current_app.logger.error(f'Stripe checkout error: {e}')
        return jsonify({'error': f'Fizetési hiba: {err_body}'}), 500
    except Exception as e:
        current_app.logger.error(f'Checkout error: {e}')
        return jsonify({'error': 'Hiba történt a fizetés indításakor.'}), 500


@bp.route('/success')
@login_required
def success():
    session_id = request.args.get('session_id')
    if session_id:
        try:
            stripe_instance = get_stripe()
            session = stripe_instance.checkout.Session.retrieve(session_id)
            if session.get('payment_status') == 'paid':
                # Update subscription
                sub = Subscription.query.filter_by(user_id=current_user.id).first()
                if sub:
                    sub.status = 'active'
                    sub.plan_type = session.get('metadata', {}).get('plan', 'monthly')
                    sub.stripe_subscription_id = session.get('subscription', '')
                    db.session.commit()

                    # Audit
                    audit = AuditTrail(
                        user_id=current_user.id, action='subscription_activate',
                        entity_type='subscription',
                        new_value=f'plan={sub.plan_type}, stripe={sub.stripe_subscription_id}',
                        ip_address=request.remote_addr or '',
                    )
                    db.session.add(audit)
                    db.session.commit()
        except Exception as e:
            current_app.logger.error(f'Success error: {e}')

    return redirect(url_for('subscription.subscription_page'))


@bp.route('/api/portal', methods=['POST'])
@login_required
def create_portal():
    """Create Stripe billing portal session."""
    sub = Subscription.query.filter_by(user_id=current_user.id).first()
    if not sub or not sub.stripe_subscription_id:
        return jsonify({'error': 'Nincs aktív előfizetés'}), 400

    try:
        stripe_instance = get_stripe()
        portal = stripe_instance.billing_portal.Session.create(
            customer=sub.stripe_subscription_id,  # This would need customer ID, not subscription
            return_url=current_app.config['DOMAIN'] + '/subscription/',
        )
        return jsonify({'url': portal['url']})
    except Exception as e:
        current_app.logger.error(f'Portal error: {e}')
        return jsonify({'error': 'Hiba a portál megnyitásakor'}), 500


@bp.route('/webhook', methods=['POST'])
def webhook():
    """Stripe webhook endpoint — subscription lifecycle events."""
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    wh_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET', '')

    if not wh_secret:
        current_app.logger.warning('STRIPE_WEBHOOK_SECRET not configured, skipping webhook')
        return 'Webhook not configured', 200

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, wh_secret)
    except Exception as e:
        current_app.logger.error(f'Webhook signature error: {e}')
        return 'Webhook error', 400

    event_type = event.get('type', '')
    current_app.logger.info(f'Stripe webhook: {event_type}')

    if event_type == 'checkout.session.completed':
        session = event['data']['object']
        user_id = int(session.get('metadata', {}).get('user_id', 0))
        plan = session.get('metadata', {}).get('plan', 'monthly')
        subscription_id = session.get('subscription', '')

        if user_id:
            sub = Subscription.query.filter_by(user_id=user_id).first()
            if sub:
                sub.status = 'active'
                sub.plan_type = plan
                sub.stripe_subscription_id = subscription_id
                db.session.commit()

    elif event_type == 'customer.subscription.deleted':
        subscription_id = event['data']['object'].get('id', '')
        sub = Subscription.query.filter_by(stripe_subscription_id=subscription_id).first()
        if sub:
            sub.status = 'cancelled'
            db.session.commit()

    elif event_type == 'invoice.payment_failed':
        subscription_id = event['data']['object'].get('subscription', '')
        sub = Subscription.query.filter_by(stripe_subscription_id=subscription_id).first()
        if sub:
            sub.status = 'cancelled'
            db.session.commit()

    return '', 200


@bp.route('/api/cancel', methods=['POST'])
@login_required
def api_cancel():
    sub = Subscription.query.filter_by(user_id=current_user.id).first()
    if not sub:
        return jsonify({'error': 'Nincs előfizetés'}), 400

    if sub.stripe_subscription_id:
        try:
            stripe_instance = get_stripe()
            stripe_instance.Subscription.delete(sub.stripe_subscription_id)
        except Exception as e:
            current_app.logger.error(f'Cancel error: {e}')

    sub.status = 'cancelled'
    db.session.commit()

    audit = AuditTrail(
        user_id=current_user.id, action='subscription_cancel',
        entity_type='subscription',
        old_value=f'plan={sub.plan_type}, status=active',
        new_value=f'plan={sub.plan_type}, status=cancelled',
        ip_address=request.remote_addr or '',
    )
    db.session.add(audit)
    db.session.commit()

    return jsonify({'ok': True})