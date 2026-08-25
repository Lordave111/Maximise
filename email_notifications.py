"""Merco transactional + marketplace email queue.

EmailJS remains the delivery provider. This module keeps email sending out of
critical database operations by queueing messages and processing them safely.
"""
from datetime import datetime, timedelta
import os
import time

from flask import jsonify, request
from sqlalchemy import select, event
from sqlalchemy.orm.attributes import get_history

from app import app, db, User, Product
import bootstrap
import social
import email_delivery_fix  # noqa: E402,F401


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


def queue_email(user_id, event_type, subject, message, action_url='', action_text='Open Merco', *, transactional=False):
    user = db.session.get(User, user_id)
    if not user or not user.email:
        return None
    if not transactional and not bool(user.email_notifications):
        return None
    job = EmailJob(user_id=user.id, event_type=event_type, subject=subject[:180],
                   message=message[:2000], action_url=action_url[:600] if action_url else '',
                   action_text=(action_text or 'Open Merco')[:120])
    db.session.add(job)
    return job


def queue_email_connection(connection, user_id, event_type, subject, message, action_url='', action_text='Open Merco', *, transactional=False):
    row = connection.execute(select(User.email, User.email_notifications).where(User.id == user_id)).first()
    if not row or not row.email or (not transactional and not bool(row.email_notifications)):
        return
    connection.execute(EmailJob.__table__.insert().values(
        user_id=user_id, event_type=event_type, subject=subject[:180], message=message[:2000],
        action_url=(action_url or '')[:600], action_text=(action_text or 'Open Merco')[:120],
        status='pending', attempts=0, available_at=datetime.utcnow(), created_at=datetime.utcnow()
    ))


def process_email_queue(limit=1):
    sent = failed = 0
    with app.app_context():
        jobs = (EmailJob.query.filter(EmailJob.status == 'pending', EmailJob.available_at <= datetime.utcnow())
                .order_by(EmailJob.id.asc()).limit(max(1, min(int(limit), 10))).all())
        for index, job in enumerate(jobs):
            user = db.session.get(User, job.user_id)
            if not user or not user.email:
                job.status = 'cancelled'
                db.session.commit()
                continue
            if job.event_type not in {'verification', 'welcome', 'seller_activated', 'payment_success'} and not bool(user.email_notifications):
                job.status = 'cancelled'
                db.session.commit()
                continue
            job.status = 'sending'
            job.attempts += 1
            db.session.commit()
            try:
                import app as app_module
                ok = app_module.send_merco_email(
                    user, job.subject, job.message, action_url=job.action_url or '',
                    action_text=job.action_text or 'Open Merco',
                    template_id=os.environ.get('EMAILJS_NOTIFICATION_TEMPLATE_ID') or os.environ.get('EMAILJS_TEMPLATE_ID')
                )
                if ok:
                    job.status = 'sent'
                    job.sent_at = datetime.utcnow()
                    job.last_error = None
                    sent += 1
                else:
                    raise RuntimeError('EmailJS rejected or skipped the message')
            except Exception as exc:
                job.status = 'pending' if job.attempts < 4 else 'failed'
                job.available_at = datetime.utcnow() + timedelta(minutes=min(30, 2 ** job.attempts))
                job.last_error = str(exc)[:500]
                failed += 1
            db.session.commit()
            if index < len(jobs) - 1:
                time.sleep(1.05)
    return sent, failed


@event.listens_for(Product, 'after_insert')
def queue_new_product_emails(mapper, connection, target):
    followers = connection.execute(select(social.SellerFollow.buyer_id).where(social.SellerFollow.seller_id == target.seller_id)).all()
    seller_name = connection.execute(select(User.username).where(User.id == target.seller_id)).scalar_one_or_none() or 'A seller'
    link = f'/product/{target.id}'
    for row in followers:
        queue_email_connection(connection, row[0], 'new_product', f'{seller_name} posted a new product',
                               f'{seller_name} just posted {target.name} on Merco. Take a look while it is fresh.', link, 'View product')


@event.listens_for(social.SellerFollow, 'after_insert')
def queue_new_follower_email(mapper, connection, target):
    buyer_name = connection.execute(select(User.username).where(User.id == target.buyer_id)).scalar_one_or_none() or 'A buyer'
    seller_name = connection.execute(select(User.username).where(User.id == target.seller_id)).scalar_one_or_none() or 'your store'
    seller = connection.execute(select(User.seller_slug).where(User.id == target.seller_id)).scalar_one_or_none()
    link = f'/seller/{seller}' if seller else '/seller'
    queue_email_connection(connection, target.seller_id, 'new_follower', 'You have a new Merco follower',
                           f'{buyer_name} is now following {seller_name}. Open your seller dashboard to see your followers.', link, 'View my followers')


@event.listens_for(bootstrap.ListingPayment, 'after_update')
def queue_payment_success_email(mapper, connection, target):
    history = get_history(target, 'status')
    if not history.has_changes() or target.status != 'paid':
        return
    product_name = target.name or 'your listing'
    queue_email_connection(connection, target.seller_id, 'payment_success', 'Your Merco listing is live',
                           f'Payment confirmed. {product_name} has been published/reactivated successfully for {target.duration_hours} hours.',
                           '/seller', 'Open seller dashboard', transactional=True)


@event.listens_for(User, 'after_update')
def queue_account_lifecycle_emails(mapper, connection, target):
    role_history = get_history(target, 'role')
    verified_history = get_history(target, 'email_verified')
    if role_history.has_changes() and target.role == 'seller' and role_history.deleted and role_history.deleted[0] == 'buyer':
        link = f'/seller/{target.seller_slug}' if target.seller_slug else '/seller'
        queue_email_connection(connection, target.id, 'seller_activated', 'Seller Mode is live on Merco',
                               f'Your seller account is now active, {target.username}. Your storefront is ready for listings.', link, 'Open my store', transactional=True)
    if verified_history.has_changes() and bool(target.email_verified) and verified_history.deleted and not bool(verified_history.deleted[0]):
        queue_email_connection(connection, target.id, 'welcome', 'Welcome to Merco',
                               f'Welcome to Merco, {target.username}. Your email is verified and your account is ready. Explore the marketplace or open Seller Mode from Settings.', '/market', 'Explore Merco', transactional=True)


@app.before_request
def expire_and_queue_listing_alerts():
    try:
        before = {n.id for n in social.Notification.query.filter_by(title='Listing expired').all()}
        seller_features = __import__('seller_features')
        seller_features.expire_listings_with_notifications()
        fresh = social.Notification.query.filter(social.Notification.title == 'Listing expired', ~social.Notification.id.in_(before) if before else True).all()
        for notification in fresh:
            queue_email(notification.user_id, 'listing_expired', notification.title, notification.message,
                        notification.link or '/seller', 'Reactivate listing')
        if fresh:
            db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('Listing expiry/email check failed')


@app.post('/tasks/process-emails')
def process_email_task():
    expected = os.environ.get('CRON_SECRET', '').strip()
    supplied = request.headers.get('X-Cron-Secret', '') or request.args.get('secret', '')
    if not expected or supplied != expected:
        return jsonify({'ok': False}), 401
    sent, failed = process_email_queue(limit=5)
    return jsonify({'ok': True, 'sent': sent, 'failed': failed}), 200


@app.after_request
def process_one_email_after_request(response):
    if request.path != '/tasks/process-emails' and response.status_code < 500:
        try:
            process_email_queue(limit=1)
        except Exception:
            app.logger.exception('Email queue processing failed')
    return response
