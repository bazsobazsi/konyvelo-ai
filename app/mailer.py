"""
Egyszerű e-mail küldő — SMTP, opcionális.
Ha SMTP nincs beállítva, a tartalmat a logba írja (fejlesztés).
"""
import smtplib
import logging
from email.message import EmailMessage
from flask import current_app

logger = logging.getLogger(__name__)


def is_configured():
    return bool(current_app.config.get('SMTP_HOST'))


def send_email(to_email, subject, body_text, body_html=None):
    """Send email. Returns (ok: bool, info: str)."""
    cfg = current_app.config

    if not is_configured():
        logger.warning(
            'SMTP nincs beállítva — e-mail NEM lett elküldve.\n'
            f'  Címzett: {to_email}\n  Tárgy: {subject}\n  Tartalom:\n{body_text}'
        )
        return False, 'smtp_not_configured'

    host = cfg['SMTP_HOST']
    port = cfg['SMTP_PORT']
    user = cfg['SMTP_USER']
    password = cfg['SMTP_PASSWORD']
    sender = cfg['SMTP_FROM'] or user
    use_tls = cfg['SMTP_USE_TLS']
    from_name = cfg['MAIL_FROM_NAME']

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f'{from_name} <{sender}>'
    msg['To'] = to_email
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype='html')

    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=15)
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                server.starttls()
        if user and password:
            server.login(user, password)
        server.send_message(msg)
        server.quit()
        logger.info(f'E-mail elküldve: {to_email} — {subject}')
        return True, 'sent'
    except Exception as e:
        logger.error(f'E-mail küldés hiba ({to_email}): {e}', exc_info=True)
        return False, str(e)


def send_password_reset(to_email, name, reset_url, expiry_minutes):
    subject = 'KönyvelőAI — Jelszó emlékeztető'
    body = f"""Kedves {name}!

Jelszó-emlékeztetőt kértél a KönyvelőAI fiókodhoz.

A jelszó visszaállításához kattints az alábbi linkre:
{reset_url}

A link {expiry_minutes} percig érvényes, és csak egyszer használható.

Ha nem te kérted, hagyd figyelmen kívül ezt az e-mailt — a jelszavad nem változik.

Üdvözlettel,
KönyvelőAI
"""
    html = f"""<html><body style="font-family:Arial,sans-serif;color:#222;line-height:1.6">
<p>Kedves {name}!</p>
<p>Jelszó-emlékeztetőt kértél a <strong>KönyvelőAI</strong> fiókodhoz.</p>
<p><a href="{reset_url}" style="background:#6366f1;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:600">Jelszó visszaállítása</a></p>
<p style="font-size:13px;color:#666">A link {expiry_minutes} percig érvényes, és csak egyszer használható.<br>
Ha nem te kérted, hagyd figyelmen kívül ezt az e-mailt.</p>
<p style="font-size:12px;color:#999">KönyvelőAI</p>
</body></html>"""
    return send_email(to_email, subject, body, html)