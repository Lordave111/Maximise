"""Reliable transactional and marketplace email delivery using Gmail SMTP."""
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import os
import smtplib
import time

from flask import jsonify, request, url_for
from sqlalchemy import select, event
from sqlalchemy.orm.attributes import get_history

from app import app, db, User, Product
import bootstrap
import social


class EmailJob(db.Model):
    __tablename__ = 'email_job'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    event_type = db.Column(db.String(60), nullable=False, index=True)
    subject = db.Column(db.String(180), nullable=False)
    message = db.Column(db.String(2000), nullable=False)
    action_url = db.Column(db.String(600), nullable=True)
    action_text = db.Column(db.String(120), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    last_error = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now(), index=True)


with app.app_context():
    db.create_all()


# Stable Gmail SMTP settings live in the backend. Only the secret App Password
# needs to be configured in Render.
SMTP_HOST = 'smtp.gmail.com'
SMTP_PORT = 465
SMTP_SECURE = True
SMTP_USER = 'nwahiridaviduche@gmail.com'
SMTP_FROM_EMAIL = 'nwahiridaviduche@gmail.com'
SMTP_FROM_NAME = 'Merco'
MERCO_PUBLIC_URL = 'https://maximise.onrender.com'


def _smtp_config():
    return {
        'host': SMTP_HOST,
        'port': SMTP_PORT,
        'secure': SMTP_SECURE,
        'user': SMTP_USER,
        'password': os.environ.get('SMTP_PASSWORD') or '',
        'from_email': SMTP_FROM_EMAIL,
        'from_name': SMTP_FROM_NAME,
        'public_url': MERCO_PUBLIC_URL,
    }


def _html_message(message, action_url='', action_text='Open Merco', name=''):
    paragraphs = ''.join(
        f'<p style="margin:0 0 14px">{html.escape(line)}</p>'
        for line in message.split('\n') if line.strip()
    )
    button = ''
    if action_url:
        safe_url = html.escape(action_url, quote=True)
        button = f'<p style="margin:24px 0"><a href="{safe_url}" style="display:inline-block;padding:12px 18px;background:#d4af37;color:#050505;text-decoration:none;border-radius:8px;font-weight:700">{html.escape(action_text)}</a></p>'
    return f'<!doctype html><html><body style="margin:0;background:#070707;color:#f5f1e8;font-family:Arial,sans-serif"><div style="max-width:620px;margin:0 auto;padding:40px 24px"><div style="font-size:13px;letter-spacing:3px;color:#d4af37;font-weight:700">MERCO</div><h1 style="font-size:25px;margin:12px 0 22px">{html.escape(name or "Hello")}</h1><div style="font-size:15px;line-height:1.7;color:#d8d3c8">{paragraphs}</div>{button}<div style="margin-top:30px;border-top:1px solid #2a2a2a;padding-top:16px;font-size:12px;color:#888">Merco marketplace · This is an automated email.</div></div></body></html>'


def send_smtp(to_email, subject, message, *, name='', action_url='', action_text='Open Merco', html_body=None):
    cfg = _smtp_config()
    if not cfg['password']:
        app.logger.error('SMTP_PASSWORD is not configured.')
        return False
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject[:180]
    msg['From'] = f'{cfg["from_name"]} <{cfg["from_email"]}>'
    msg['To'] = to_email
    msg.attach(MIMEText(message[:10000], 'plain', 'utf-8'))
    msg.attach(MIMEText(html_body or _html_message(message, action_url, action_text, name), 'html', 'utf-8'))
    try:
        with smtplib.SMTP_SSL(cfg['host'], cfg['port'], timeout=10) as server:
            server.login(cfg['user'], cfg['password'])
            server.sendmail(cfg['from_email'], [to_email], msg.as_string())
        app.logger.info('SMTP delivered email to %s', to_email)
        return True
    except (OSError, smtplib.SMTPException) as exc:
        app.logger.error('SMTP delivery failed for %s: %s', to_email, exc)
        return False


def _send_merco_email_smtp(user, subject, message, action_url='', action_text='Open Merco', template_id=None):
    return send_smtp(user.email, subject, message, name=getattr(user, 'username', ''), action_url=action_url, action_text=action_text)


def _send_email_smtp(to_email, subject, text_body, html_body=None, template_id=None, action_url='', action_text='Open Merco'):
    return send_smtp(to_email, subject, text_body, action_url=action_url, action_text=action_text, html_body=html_body)


app_module = __import__('app')
app_module.send_merco_email = _send_merco_email_smtp
app_module.send_email = _send_email_smtp


def _queue_verification_email(user):
    if not user or not user.email:
        return False
    try:
        token = app_module.make_verification_token(user)
        action_url = url_for('verify_email', token=token, _external=True)
        queue_email(user.id, 'verification', 'Verify your Merco email',
                    f'Hi {user.username},\n\nYour Merco account is almost ready. Verify your email to unlock Seller Mode.\n\nThis verification link expires in 24 hours.',
                    action_url, 'Verify my email', transactional=True)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        app.logger.exception('Could not queue verification email')
        return False


app_module.send_verification_email = _queue_verification_email
app_module.__dict__['send_verification_email'] = _queue_verification_email


def queue_email(user_id, event_type, subject, message, action_url='', action_text='Open Merco', *, transactional=False):
    user = db.session.get(User, user_id)
    if not user or not user.email or (not transactional and not bool(user.email_notifications)):
        return None
    job = EmailJob(user_id=user.id, event_type=event_type, subject=subject[:180], message=message[:2000], action_url=(action_url or '')[:600], action_text=(action_text or 'Open Merco')[:120])
    db.session.add(job)
    return job


def queue_email_connection(connection, user_id, event_type, subject, message, action_url='', action_text='Open Merco', *, transactional=False):
    row = connection.execute(select(User.email, User.email_notifications).where(User.id == user_id)).first()
    if not row or not row.email or (not transactional and not bool(row.email_notifications)):
        return
    connection.execute(EmailJob.__table__.insert().values(user_id=user_id, event_type=event_type, subject=subject[:180], message=message[:2000], action_url=(action_url or '')[:600], action_text=(action_text or 'Open Merco')[:120], status='pending', attempts=0, available_at=datetime.utcnow(), created_at=datetime.utcnow()))


def process_email_queue(limit=3):
    sent = failed = 0
    with app.app_context():
        jobs = (EmailJob.query.filter(EmailJob.status == 'pending', EmailJob.available_at <= datetime.utcnow()).order_by(EmailJob.id.asc()).limit(max(1, min(int(limit), 10))).all())
        for index, job in enumerate(jobs):
            user = db.session.get(User, job.user_id)
            if not user or not user.email:
                job.status = 'cancelled'; db.session.commit(); continue
            if job.event_type not in {'verification', 'welcome', 'seller_activated', 'payment_success'} and not bool(user.email_notifications):
                job.status = 'cancelled'; db.session.commit(); continue
            job.status = 'sending'; job.attempts += 1; db.session.commit()
            try:
                if not send_smtp(user.email, job.subject, job.message, name=user.username, action_url=job.action_url or '', action_text=job.action_text or 'Open Merco'):
                    raise RuntimeError('SMTP rejected the message')
                job.status = 'sent'; job.sent_at = datetime.utcnow(); job.last_error = None; sent += 1
            except Exception as exc:
                job.status = 'pending' if job.attempts < 4 else 'failed'; job.available_at = datetime.utcnow() + timedelta(minutes=min(30, 2 ** job.attempts)); job.last_error = str(exc)[:500]; failed += 1
            db.session.commit()
            if index < len(jobs) - 1: time.sleep(0.2)
    return sent, failed


@event.listens_for(Product, 'after_insert')
def queue_new_product_emails(mapper, connection, target):
    followers = connection.execute(select(social.SellerFollow.buyer_id).where(social.SellerFollow.seller_id == target.seller_id)).all()
    seller_name = connection.execute(select(User.username).where(User.id == target.seller_id)).scalar_one_or_none() or 'A seller'
    link = f'{MERCO_PUBLIC_URL}/product/{target.id}'
    for row in followers:
        queue_email_connection(connection, row[0], 'new_product', f'{seller_name} posted a new product', f'{seller_name} just posted {target.name} on Merco. Take a look while it is fresh.', link, 'View product')


@event.listens_for(social.SellerFollow, 'after_insert')
def queue_new_follower_email(mapper, connection, target):
    buyer_name = connection.execute(select(User.username).where(User.id == target.buyer_id)).scalar_one_or_none() or 'A buyer'
    seller_row = connection.execute(select(User.username, User.seller_slug).where(User.id == target.seller_id)).first()
    if not seller_row:
        return
    seller_name, slug = seller_row
    link = f'{MERCO_PUBLIC_URL}/seller/{slug}' if slug else f'{MERCO_PUBLIC_URL}/seller'
    queue_email_connection(connection, target.seller_id, 'new_follower', 'You have a new Merco follower', f'{buyer_name} is now following {seller_name}. Open your seller store to see your followers.', link, 'View my store')


@event.listens_for(bootstrap.ListingPayment, 'after_update')
def queue_payment_success_email(mapper, connection, target):
    history = get_history(target, 'status')
    if not history.has_changes() or target.status != 'paid':
        return
    queue_email_connection(connection, target.seller_id, 'payment_success', 'Your Merco listing is live', f'Payment confirmed. {target.name} has been published/reactivated successfully for {target.duration_hours} hours.', f'{MERCO_PUBLIC_URL}/seller', 'Open seller dashboard', transactional=True)


@event.listens_for(User, 'after_update')
def queue_account_lifecycle_emails(mapper, connection, target):
    role_history = get_history(target, 'role')
    verified_history = get_history(target, 'email_verified')
    if role_history.has_changes() and target.role == 'seller' and role_history.deleted and role_history.deleted[0] == 'buyer':
        link = f'{MERCO_PUBLIC_URL}/seller/{target.seller_slug}' if target.seller_slug else f'{MERCO_PUBLIC_URL}/seller'
        queue_email_connection(connection, target.id, 'seller_activated', 'Seller Mode is live on Merco', f'Your seller account is now active, {target.username}. Your storefront is ready for listings.', link, 'Open my store', transactional=True)
    if verified_history.has_changes() and bool(target.email_verified) and verified_history.deleted and not bool(verified_history.deleted[0]):
        queue_email_connection(connection, target.id, 'welcome', 'Welcome to Merco', f'Welcome to Merco, {target.username}. Your email is verified and your account is ready.', f'{MERCO_PUBLIC_URL}/market', 'Explore Merco', transactional=True)


@app.post('/tasks/process-emails')
def process_email_task():
    expected = os.environ.get('CRON_SECRET', '').strip()
    supplied = request.headers.get('X-Cron-Secret', '') or request.args.get('secret', '')
    if not expected or supplied != expected:
        return jsonify({'ok': False}), 401
    sent, failed = process_email_queue(limit=10)
    return jsonify({'ok': True, 'sent': sent, 'failed': failed}), 200
