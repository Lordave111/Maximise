"""Reliable EmailJS delivery adapter and navigation API for Merco."""
import os
import requests

from flask import jsonify
from flask_login import current_user

import app as app_module
from app import app


def send_merco_email(user, subject, message, action_url='', action_text='Open Merco', template_id=None):
    service_id = os.environ.get('EMAILJS_SERVICE_ID', '').strip()
    public_key = os.environ.get('EMAILJS_PUBLIC_KEY', '').strip()
    private_key = (os.environ.get('EMAILJS_PRIVATE_KEY', '').strip()
                   or os.environ.get('EMAILJS_ACCESS_TOKEN', '').strip())
    template = (template_id or os.environ.get('EMAILJS_TEMPLATE_ID', '')).strip()

    if not service_id or not public_key or not template:
        app.logger.error('EmailJS configuration incomplete: service=%s public=%s template=%s', bool(service_id), bool(public_key), bool(template))
        return False

    payload = {
        'service_id': service_id,
        'template_id': template,
        'user_id': public_key,
        'template_params': {
            'to_email': user.email,
            'email': user.email,
            'subject': subject,
            'name': getattr(user, 'username', '') or '',
            'preheader': 'A secure update from Merco',
            'message': message,
            'action_url': action_url,
            'action_text': action_text,
            'brand_name': 'Merco',
            'website_url': os.environ.get('MERCO_PUBLIC_URL', '').strip(),
        },
    }
    if private_key:
        payload['accessToken'] = private_key

    try:
        response = requests.post(
            'https://api.emailjs.com/api/v1.0/email/send',
            json=payload,
            headers={'Accept': 'application/json', 'Content-Type': 'application/json'},
            timeout=20,
        )
        body = response.text[:1000]
        if response.ok:
            app.logger.info('EmailJS delivered email to %s (HTTP %s)', user.email, response.status_code)
            return True
        app.logger.error('EmailJS rejected email to %s: HTTP %s: %s', user.email, response.status_code, body)
        return False
    except requests.RequestException as exc:
        app.logger.error('EmailJS network error for %s: %s', user.email, exc)
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
