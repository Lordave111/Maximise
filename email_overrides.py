"""Production email presentation and SMTP diagnostics for Merco."""
import html
import re

from flask import abort, flash, render_template, request
from flask_login import current_user, login_required

import email_notifications
from email_notifications import app


RAILWAY_URL = 'https://maximise-production.up.railway.app'


def _escape(value):
    return html.escape(str(value or ''), quote=True)


def premium_html(message, action_url='', action_text='Open Merco', name=''):
    """Responsive branded HTML template used for every Merco email."""
    paragraphs = []
    for line in str(message or '').split('\n'):
        line = line.strip()
        if line:
            paragraphs.append(f'<p>{_escape(line)}</p>')
    button = ''
    if action_url:
        button = f'<a class="button" href="{_escape(action_url)}">{_escape(action_text or "Open Merco")}</a>'
    return f'''<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Merco</title>
<style>.button{{display:inline-block;margin-top:24px;padding:13px 20px;background:#00e887;color:#04110a!important;text-decoration:none!important;border-radius:10px;font-weight:800;}}</style>
</head>
<body style="margin:0;background:#070b09;color:#e9f1ec;font-family:Arial,Helvetica,sans-serif;">
<div style="width:100%;padding:38px 12px;box-sizing:border-box;background:#070b09;">
<div style="max-width:620px;margin:0 auto;background:#0d1511;border:1px solid #21352a;border-radius:18px;overflow:hidden;">
<div style="padding:28px 30px;border-bottom:1px solid #21352a;background:linear-gradient(135deg,#101b15,#0b120f);">
<div style="font-size:25px;font-weight:800;letter-spacing:4px;color:#00e887;">MERCO</div>
<div style="margin-top:7px;font-size:12px;letter-spacing:1.6px;color:#91a69b;text-transform:uppercase;">Marketplace made simple</div>
</div>
<div style="padding:32px 30px;">
<div style="font-size:14px;color:#91a69b;margin-bottom:8px;">Hello {_escape(name or 'there')},</div>
<div style="font-size:22px;font-weight:700;color:#f4f8f5;margin-bottom:20px;">A secure update from Merco</div>
<div style="font-size:15px;line-height:1.75;color:#c8d4cd;">{''.join(paragraphs)}</div>
{button}
<div style="margin-top:30px;padding:16px;border-radius:12px;background:#101b15;border:1px solid #203429;color:#84988d;font-size:12px;line-height:1.6;">If you did not request this email, you can safely ignore it. Never share your Merco password or verification links.</div>
</div>
<div style="padding:20px 30px;border-top:1px solid #21352a;color:#71857a;font-size:11px;line-height:1.6;">Merco · <a href="{RAILWAY_URL}" style="color:#00e887;text-decoration:none;">Open Merco</a><br>This is an automated message. Please do not reply directly to this email.</div>
</div></div></body></html>'''


# Replace the generic HTML renderer without changing the queue API.
email_notifications._html_message = premium_html


def diagnose_smtp(to_email):
    """Run a real delivery test through the exact SMTP implementation used by Merco."""
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', to_email or ''):
        return {'ok': False, 'stage': 'validation', 'message': 'Enter a valid recipient email address.'}
    cfg = email_notifications._smtp_config()
    if not cfg['password']:
        return {'ok': False, 'stage': 'configuration', 'message': 'SMTP password is missing. Add a Gmail App Password to SMTP_PASSWORD (or GMAIL_APP_PASSWORD) in Railway Variables.'}
    try:
        body = ('This is a live SMTP test from Merco.\n\n'
                'If you received this message, Gmail SMTP authentication and outbound email delivery are working correctly.')
        ok = email_notifications.send_smtp(
            to_email,
            'Merco SMTP test — delivery check',
            body,
            name='Merco user',
            action_url=RAILWAY_URL,
            action_text='Open Merco',
        )
        if ok:
            return {'ok': True, 'stage': 'delivery', 'message': f'Test email was accepted for delivery to {to_email}.'}
        return {'ok': False, 'stage': 'smtp', 'message': 'SMTP could not deliver the test email. Check the Railway SMTP variables and Gmail App Password.'}
    except Exception as exc:
        app.logger.exception('SMTP diagnostic failed')
        return {'ok': False, 'stage': 'smtp', 'message': f'SMTP test failed: {type(exc).__name__}.'}


@app.route('/admin/email-test', methods=['GET', 'POST'])
@login_required
def admin_email_test():
    if current_user.role != 'admin':
        abort(403)
    result = None
    recipient = (request.form.get('recipient') or current_user.email or '').strip().lower()
    if request.method == 'POST':
        result = diagnose_smtp(recipient)
        flash(result['message'])
    return render_template('admin_email_test.html', result=result, recipient=recipient)
