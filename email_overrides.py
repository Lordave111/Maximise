"""Branded transactional email presentation and delivery diagnostics for Merco."""
import html
import re

from flask import abort, flash, render_template, request
from flask_login import current_user, login_required

import email_notifications
from email_notifications import app


RAILWAY_URL = 'https://maximise-production.up.railway.app'


def _escape(value):
    return html.escape(str(value or ''), quote=True)


def _email_theme(subject):
    """Return a polished title, eyebrow and intro for the email event."""
    text = (subject or '').lower()
    if 'verify' in text:
        return 'Verify your email', 'ACCOUNT SECURITY', 'Confirm your email to finish setting up Merco.'
    if 'welcome' in text:
        return 'Welcome to Merco', 'WELCOME ABOARD', 'Your account is ready. Discover, buy and sell with confidence.'
    if 'seller mode' in text:
        return 'Seller Mode is live', 'SELLER ACCOUNT', 'Your storefront is ready for business.'
    if 'listing is live' in text or 'payment' in text:
        return 'Your listing is live', 'PAYMENT CONFIRMED', 'Your Merco seller activity has been successfully processed.'
    if 'new follower' in text:
        return 'You have a new follower', 'SOCIAL UPDATE', 'Someone is now following your Merco storefront.'
    if 'posted a new product' in text:
        return 'A seller you follow posted', 'NEW PRODUCT', 'There is something new waiting for you on Merco.'
    if 'test' in text:
        return 'Email delivery is connected', 'SYSTEM TEST', 'This confirms that Merco can send transactional email through the configured provider.'
    return 'A new update from Merco', 'MERCO UPDATE', 'Here is an update from your Merco account.'


def premium_html(message, action_url='', action_text='Open Merco', name='', subject=''):
    """Build a responsive branded HTML email that works across major clients."""
    title, eyebrow, intro = _email_theme(subject)
    paragraphs = []
    for line in str(message or '').split('\n'):
        line = line.strip()
        if line:
            paragraphs.append(f'<p style="margin:0 0 14px">{_escape(line)}</p>')

    button = ''
    if action_url:
        button = (
            f'<a href="{_escape(action_url)}" '
            'style="display:inline-block;padding:14px 22px;background:#00e887;'
            'color:#04110a!important;text-decoration:none!important;border-radius:10px;'
            'font-size:14px;font-weight:800;line-height:1">'
            f'{_escape(action_text or "Open Merco")}</a>'
        )

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark">
<title>{_escape(title)}</title>
</head>
<body style="margin:0;padding:0;background:#050a08;color:#e9f1ec;font-family:Arial,Helvetica,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:#050a08;">
<tr><td align="center" style="padding:32px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:620px;background:#0b1510;border:1px solid #1e3829;border-radius:18px;overflow:hidden;">
<tr><td style="padding:26px 30px;background:#07100b;border-bottom:1px solid #1e3829;">
<div style="font-size:24px;font-weight:900;letter-spacing:5px;color:#00e887;">MERCO</div>
<div style="margin-top:7px;font-size:11px;font-weight:700;letter-spacing:2px;color:#82978b;text-transform:uppercase;">Marketplace made simple</div>
</td></tr>
<tr><td style="padding:34px 30px;">
<div style="font-size:11px;font-weight:800;letter-spacing:1.8px;color:#00e887;text-transform:uppercase;">{_escape(eyebrow)}</div>
<h1 style="margin:9px 0 10px;font-size:27px;line-height:1.2;color:#f6faf7;">{_escape(title)}</h1>
<p style="margin:0 0 26px;font-size:14px;line-height:1.6;color:#91a69b;">{_escape(intro)}</p>
<div style="margin-bottom:24px;font-size:14px;color:#91a69b;">Hello {_escape(name or 'there')},</div>
<div style="font-size:15px;line-height:1.75;color:#cad6cf;">{''.join(paragraphs)}</div>
{f'<div style="margin-top:26px">{button}</div>' if button else ''}
<div style="margin-top:30px;padding:15px 16px;background:#0f1d15;border:1px solid #1d3427;border-radius:12px;font-size:12px;line-height:1.6;color:#84988d;">
For your security, never share your Merco password or verification links. If you did not expect this message, you can safely ignore it.
</div>
</td></tr>
<tr><td style="padding:20px 30px;border-top:1px solid #1e3829;color:#71857a;font-size:11px;line-height:1.7;">
Merco · <a href="{RAILWAY_URL}" style="color:#00e887;text-decoration:none;">Open Merco</a><br>
This is an automated transactional email. Please do not reply directly to this message.
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>'''


# The Resend transport calls this renderer when it needs HTML without a subject.
def _html_message_with_subject(message, action_url='', action_text='Open Merco', name='', subject=''):
    return premium_html(message, action_url, action_text, name, subject)


email_notifications._html_message = _html_message_with_subject

# Make the subject available to the renderer while preserving the existing queue API.
_original_send_smtp = email_notifications.send_smtp


def _branded_send(to_email, subject, message, *, name='', action_url='', action_text='Open Merco', html_body=None):
    branded_body = html_body or premium_html(message, action_url, action_text, name, subject)
    return _original_send_smtp(
        to_email,
        subject,
        message,
        name=name,
        action_url=action_url,
        action_text=action_text,
        html_body=branded_body,
    )


email_notifications.send_smtp = _branded_send


def diagnose_email(to_email):
    """Send a real delivery test through the currently configured Merco transport."""
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', to_email or ''):
        return {'ok': False, 'stage': 'validation', 'message': 'Enter a valid recipient email address.'}
    try:
        body = (
            'This is a live delivery test from Merco.\n\n'
            'If you received this message, the Merco transactional email connection is working.'
        )
        ok = email_notifications.send_smtp(
            to_email,
            'Merco email delivery test',
            body,
            name='Merco user',
            action_url=RAILWAY_URL,
            action_text='Open Merco',
        )
        if ok:
            return {'ok': True, 'stage': 'delivery', 'message': f'Test email was accepted for delivery to {to_email}.'}
        return {'ok': False, 'stage': 'delivery', 'message': 'The email provider rejected or could not deliver the test message. Check the Railway Resend variables and provider logs.'}
    except Exception as exc:
        app.logger.exception('Email delivery diagnostic failed')
        return {'ok': False, 'stage': 'delivery', 'message': f'Email test failed: {type(exc).__name__}.'}


@app.route('/admin/email-test', methods=['GET', 'POST'])
@login_required
def admin_email_test():
    if current_user.role != 'admin':
        abort(403)
    result = None
    recipient = (request.form.get('recipient') or current_user.email or '').strip().lower()
    if request.method == 'POST':
        result = diagnose_email(recipient)
        flash(result['message'])
    return render_template('admin_email_test.html', result=result, recipient=recipient)
