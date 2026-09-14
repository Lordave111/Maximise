"""Production email presentation and SMTP diagnostics for Merco."""
import html
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flask import abort, flash, render_template, request
from flask_login import current_user, login_required

import email_notifications
from email_notifications import app


def _escape(value):
    return html.escape(str(value or ""), quote=True)


def premium_html(message, action_url='', action_text='Open Merco', name=''):
    """Responsive, branded HTML template used for every Merco email."""
    paragraphs = []
    for line in str(message or '').split('\n'):
        line = line.strip()
        if line:
            paragraphs.append(f'<p>{_escape(line)}</p>')
    button = ''
    if action_url:
        button = f'''<a class="button" href="{_escape(action_url)}">{_escape(action_text or 'Open Merco')}</a>'''
    return f'''<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Merco</title></head>
<body style="margin:0;background:#070b09;color:#e9f1ec;font-family:Arial,Helvetica,sans-serif;">
  <div style="width:100%;padding:38px 12px;box-sizing:border-box;background:#070b09;">
    <div style="max-width:620px;margin:0 auto;background:#0d1511;border:1px solid #21352a;border-radius:18px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,.28);">
      <div style="padding:28px 30px;border-bottom:1px solid #21352a;background:linear-gradient(135deg,#101b15,#0b120f);">
        <div style="font-size:25px;font-weight:800;letter-spacing:4px;color:#00e887;">MERCO</div>
        <div style="margin-top:7px;font-size:12px;letter-spacing:1.6px;color:#91a69b;text-transform:uppercase;">Marketplace made simple</div>
      </div>
      <div style="padding:32px 30px;">
        <div style="font-size:14px;color:#91a69b;margin-bottom:8px;">Hello {_escape(name or 'there')},</div>
        <div style="font-size:22px;font-weight:700;color:#f4f8f5;margin-bottom:20px;">A secure update from Merco</div>
        <div style="font-size:15px;line-height:1.75;color:#c8d4cd;">{''.join(paragraphs)}</div>
        {button if button else ''}
        <div style="margin-top:30px;padding:16px;border-radius:12px;background:#101b15;border:1px solid #203429;color:#84988d;font-size:12px;line-height:1.6;">
          If you did not request this email, you can safely ignore it. Never share your Merco password or verification links.
        </div>
      </div>
      <div style="padding:20px 30px;border-top:1px solid #21352a;color:#71857a;font-size:11px;line-height:1.6;">
        Merco · <a href="https://maximise.onrender.com" style="color:#00e887;text-decoration:none;">maximise.onrender.com</a><br>
        This is an automated message. Please do not reply directly to this email.
      </div>
    </div>
  </div>
</body>
</html>'''.replace('</head>', '<style>.button{display:inline-block;margin-top:24px;padding:13px 20px;background:#00e887;color:#04110a!important;text-decoration:none!important;border-radius:10px;font-weight:800;}</style></head>')


# Replace the generic HTML renderer without changing the queue API.
email_notifications._html_message = premium_html


def diagnose_smtp(to_email):
    """Perform a real SMTP login/send from the Render process and return safe diagnostics."""
    password = os.environ.get('SMTP_PASSWORD', '')
    if not password:
        return {'ok': False, 'stage': 'configuration', 'message': 'SMTP_PASSWORD is missing in Render.'}
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', to_email or ''):
        return {'ok': False, 'stage': 'validation', 'message': 'Enter a valid recipient email address.'}

    msg = MIMEMultipart('alternative')
    msg['Subject'] = 'Merco SMTP test — delivery check'
    msg['From'] = f'{email_notifications.SMTP_FROM_NAME} <{email_notifications.SMTP_FROM_EMAIL}>'
    msg['To'] = to_email
    body = ('This is a live SMTP test from your Merco production server.\n\n'
            'If you received this message, Gmail SMTP authentication and outbound email delivery are working correctly.')
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    msg.attach(MIMEText(premium_html(body, 'https://maximise.onrender.com', 'Open Merco', 'Merco user'), 'html', 'utf-8'))
    try:
        with smtplib.SMTP_SSL(email_notifications.SMTP_HOST, email_notifications.SMTP_PORT, timeout=15) as server:
            server.login(email_notifications.SMTP_USER, password)
            server.sendmail(email_notifications.SMTP_FROM_EMAIL, [to_email], msg.as_string())
        app.logger.info('SMTP diagnostic succeeded for %s', to_email)
        return {'ok': True, 'stage': 'delivery', 'message': f'Test email was accepted by Gmail for delivery to {to_email}.'}
    except smtplib.SMTPAuthenticationError as exc:
        app.logger.error('SMTP diagnostic authentication failed: %s', exc)
        return {'ok': False, 'stage': 'authentication', 'message': f'Gmail rejected the SMTP login ({exc.smtp_code}). Check that SMTP_PASSWORD is a current Google App Password for {email_notifications.SMTP_USER}.'}
    except smtplib.SMTPException as exc:
        app.logger.error('SMTP diagnostic failed: %s', exc)
        return {'ok': False, 'stage': 'smtp', 'message': f'Gmail SMTP returned an error: {exc}'}
    except OSError as exc:
        app.logger.error('SMTP diagnostic connection failed: %s', exc)
        return {'ok': False, 'stage': 'connection', 'message': f'Render could not connect to Gmail SMTP: {exc}'}


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
