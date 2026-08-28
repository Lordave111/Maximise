"""Reliable Mailjet delivery adapter and navigation API for Merco."""
import os
import html
import requests

from flask import jsonify
from flask_login import current_user

import app as app_module
from app import app


MAILJET_SEND_URL = 'https://api.mailjet.com/v3.1/send'


def _mailjet_config():
    return {
        'api_key': (os.environ.get('MAILJET_API_KEY', '').strip()
                    or os.environ.get('MJ_APIKEY_PUBLIC', '').strip()),
        'secret_key': (os.environ.get('MAILJET_SECRET_KEY', '').strip()
                       or os.environ.get('MJ_APIKEY_PRIVATE', '').strip()),
        'from_email': (os.environ.get('MAILJET_FROM_EMAIL', '').strip()
                       or os.environ.get('MAIL_FROM_EMAIL', '').strip()),
        'from_name': (os.environ.get('MAILJET_FROM_NAME', '').strip()
                      or os.environ.get('MAIL_FROM_NAME', '').strip()
                      or 'Merco'),
    }


def _email_html(name, subject, message, action_url='', action_text='Open Merco'):
    safe_name = html.escape(name or 'there')
    safe_subject = html.escape(subject or 'Merco notification')
    paragraphs = ''.join(
        f'<p style="margin:0 0 14px;line-height:1.7;color:#514a3b;font-size:15px;">{html.escape(part)}</p>'
        for part in (message or '').split('\n') if part.strip()
    )
    button = ''
    if action_url:
        button = (
            f'<a href="{html.escape(action_url, quote=True)}" '
            'style="display:inline-block;padding:13px 22px;border-radius:12px;'
            'background:#d6a72f;color:#17130a;text-decoration:none;font-weight:700;">'
            f'{html.escape(action_text or "Open Merco")}</a>'
        )
    return f'''<!doctype html>
<html><body style="margin:0;background:#f4f0e7;font-family:Arial,Helvetica,sans-serif;color:#17130a;">
  <div style="max-width:620px;margin:28px auto;padding:18px;">
    <div style="background:#17130a;border:1px solid #c99a2e;border-radius:22px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,.16);">
      <div style="padding:24px 26px;background:linear-gradient(135deg,#17130a,#2a210f);">
        <div style="font-size:26px;font-weight:800;letter-spacing:.08em;color:#f4c94f;">MERCO</div>
        <div style="margin-top:5px;color:#d9cfba;font-size:12px;letter-spacing:.12em;text-transform:uppercase;">The open marketplace</div>
      </div>
      <div style="padding:28px;background:#fffdf8;">
        <div style="font-size:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#b18320;margin-bottom:8px;">{safe_subject}</div>
        <h1 style="margin:0 0 18px;font-size:25px;color:#17130a;">Hi {safe_name},</h1>
        {paragraphs}
        <div style="margin-top:24px;">{button}</div>
      </div>
      <div style="padding:18px 26px;color:#bfb39d;font-size:12px;text-align:center;">
        You're receiving this because of activity on your Merco account.
      </div>
    </div>
  </div>
</body></html>'''


def send_merco_email(user, subject, message, action_url='', action_text='Open Merco', template_id=None):
    cfg = _mailjet_config()
    if not cfg['api_key'] or not cfg['secret_key'] or not cfg['from_email']:
        app.logger.error(
            'Mailjet configuration incomplete: api_key=%s secret_key=%s from_email=%s',
            bool(cfg['api_key']), bool(cfg['secret_key']), bool(cfg['from_email'])
        )
        return False

    recipient = (getattr(user, 'email', '') or '').strip()
    if not recipient:
        app.logger.error('Mailjet skipped email because recipient is empty')
        return False

    name = getattr(user, 'username', '') or 'there'
    text_body = f'Hi {name},\n\n{message}'
    html_body = _email_html(name, subject, message, action_url, action_text)
    payload = {
        'Messages': [{
            'From': {'Email': cfg['from_email'], 'Name': cfg['from_name']},
            'To': [{'Email': recipient, 'Name': name}],
            'Subject': subject or 'Merco notification',
            'TextPart': text_body,
            'HTMLPart': html_body,
        }]
    }

    try:
        response = requests.post(
            MAILJET_SEND_URL,
            auth=(cfg['api_key'], cfg['secret_key']),
            json=payload,
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            timeout=20,
        )
        body = response.text[:1500]
        if response.ok:
            app.logger.info('Mailjet delivered email to %s (HTTP %s)', recipient, response.status_code)
            return True
        app.logger.error('Mailjet rejected email to %s: HTTP %s: %s', recipient, response.status_code, body)
        return False
    except requests.RequestException as exc:
        app.logger.error('Mailjet network error for %s: %s', recipient, exc)
        return False


@app.get('/api/navigation')
def navigation_api():
    if not current_user.is_authenticated:
        return jsonify({'authenticated': False, 'role': None, 'items': []})
    common = [
        {'label': 'Marketplace', 'icon': 'ri-store-2-line', 'url': '/market'},
        {'label': 'Dashboard', 'icon': 'ri-dashboard-3-line', 'url': '/dashboard'},
        {'label': 'Notifications', 'icon': 'ri-notification-3-line', 'url': '/notifications'},
        {'label': 'Settings', 'icon': 'ri-settings-4-line', 'url': '/settings'},
    ]
    if current_user.role == 'buyer':
        role_items = [
            {'label': 'For You', 'icon': 'ri-sparkling-line', 'url': '/for-you'},
            {'label': 'Following', 'icon': 'ri-user-heart-line', 'url': '/following'},
        ]
    elif current_user.role == 'seller':
        role_items = [
            {'label': 'Upload Product', 'icon': 'ri-add-box-line', 'url': '/seller/add'},
            {'label': 'Followers', 'icon': 'ri-group-line', 'url': '/seller/followers'},
            {'label': 'Analytics', 'icon': 'ri-bar-chart-box-line', 'url': '/seller/insights'},
        ]
    else:
        role_items = [
            {'label': 'Admin Control', 'icon': 'ri-shield-star-line', 'url': '/admin/control'},
        ]
    return jsonify({'authenticated': True, 'role': current_user.role, 'items': common[:2] + role_items + common[2:]})


# Replace the module-level function used by verification and queued email jobs.
app_module.send_merco_email = send_merco_email

# Load the push module and immediately override its subscription endpoint.
try:
    import push_delivery_fix  # noqa: E402,F401
except Exception:
    app.logger.exception('Push delivery override could not be loaded')
