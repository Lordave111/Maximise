"""Reliable EmailJS delivery adapter for Merco.

The original implementation used urllib and logged every HTTP/network problem
as the same generic "delivery failed" message. This adapter keeps the existing
EmailJS REST contract, uses the already-installed requests package, and logs
EmailJS's actual response body so configuration/provider errors are visible in
Render logs.
"""
import os
import requests

from app import app


def send_merco_email(user, subject, message, action_url='', action_text='Open Merco', template_id=None):
    service_id = os.environ.get('EMAILJS_SERVICE_ID', '').strip()
    public_key = os.environ.get('EMAILJS_PUBLIC_KEY', '').strip()
    private_key = (os.environ.get('EMAILJS_PRIVATE_KEY', '').strip()
                   or os.environ.get('EMAILJS_ACCESS_TOKEN', '').strip())
    template = (template_id or os.environ.get('EMAILJS_TEMPLATE_ID', '')).strip()

    if not service_id or not public_key or not template:
        app.logger.error(
            'EmailJS configuration incomplete: service=%s public=%s template=%s',
            bool(service_id), bool(public_key), bool(template)
        )
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
        app.logger.error(
            'EmailJS rejected email to %s: HTTP %s: %s',
            user.email, response.status_code, body
        )
        return False
    except requests.RequestException as exc:
        app.logger.error('EmailJS network error for %s: %s', user.email, exc)
        return False


# The rest of the application already calls app.send_merco_email indirectly.
# Replace only that delivery function; no routes or templates are changed.
app.send_merco_email = send_merco_email
