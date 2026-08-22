"""Merco Web Push notifications for installed PWA users.

Browser push is optional: if VAPID keys are not configured, Merco keeps its
normal in-app notification centre and simply skips phone push delivery.
"""
from datetime import datetime, timedelta
import json
import os

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import event

from app import app, db
import social

try:
    from pywebpush import webpush, WebPushException
except Exception:  # pragma: no cover
    webpush = None
    WebPushException = Exception


class PushSubscription(db.Model):
    __tablename__ = 'push_subscription'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    endpoint = db.Column(db.String(2000), nullable=False, unique=True)
    p256dh = db.Column(db.String(500), nullable=False)
    auth = db.Column(db.String(500), nullable=False)
    user_agent = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, server_default=db.func.now(), index=True)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())


class PushJob(db.Model):
    __tablename__ = 'push_job'
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, db.ForeignKey('notification.id'), nullable=False, unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    available_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    sent_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, server_default=db.func.now(), index=True)


with app.app_context():
    db.create_all()


@event.listens_for(social.Notification, 'after_insert')
def queue_phone_push(mapper, connection, target):
    connection.execute(PushJob.__table__.insert().values(
        notification_id=target.id,
        user_id=target.user_id,
        status='pending',
        attempts=0,
        available_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    ))


def _vapid_ready():
    return bool(
        webpush
        and os.environ.get('VAPID_PUBLIC_KEY', '').strip()
        and os.environ.get('VAPID_PRIVATE_KEY', '').strip()
        and os.environ.get('VAPID_CLAIMS_EMAIL', '').strip()
    )


def _send(subscription, notification):
    payload = json.dumps({
        'title': notification.title,
        'body': notification.message,
        'url': notification.link or '/notifications',
        'tag': f'merco-{notification.id}',
    })
    vapid_claims = {'sub': os.environ['VAPID_CLAIMS_EMAIL'].strip()}
    try:
        webpush(
            subscription_info={
                'endpoint': subscription.endpoint,
                'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth},
            },
            data=payload,
            vapid_private_key=os.environ['VAPID_PRIVATE_KEY'].strip(),
            vapid_claims=vapid_claims,
        )
        return True
    except WebPushException as exc:
        response = getattr(exc, 'response', None)
        status = getattr(response, 'status_code', None)
        if status in (404, 410):
            db.session.delete(subscription)
            db.session.commit()
            return True
        raise


def process_push_queue(limit=10):
    if not _vapid_ready():
        return 0, 0
    sent = failed = 0
    jobs = (PushJob.query.filter(PushJob.status == 'pending', PushJob.available_at <= datetime.utcnow())
            .order_by(PushJob.id.asc()).limit(max(1, min(int(limit), 25))).all())
    for job in jobs:
        notification = db.session.get(social.Notification, job.notification_id)
        subscriptions = PushSubscription.query.filter_by(user_id=job.user_id).all()
        if not notification or not subscriptions:
            job.status = 'sent'
            job.sent_at = datetime.utcnow()
            db.session.commit()
            continue
        job.status = 'sending'
        job.attempts += 1
        db.session.commit()
        try:
            for subscription in list(subscriptions):
                _send(subscription, notification)
            job.status = 'sent'
            job.sent_at = datetime.utcnow()
            job.last_error = None
            sent += 1
        except Exception as exc:
            job.status = 'pending' if job.attempts < 4 else 'failed'
            job.available_at = datetime.utcnow() + timedelta(minutes=min(30, 2 ** job.attempts))
            job.last_error = str(exc)[:500]
            failed += 1
        db.session.commit()
    return sent, failed


@app.get('/push/config')
def push_config():
    return jsonify({
        'enabled': _vapid_ready(),
        'public_key': os.environ.get('VAPID_PUBLIC_KEY', '').strip(),
    })


@app.post('/push/subscribe')
@login_required
def push_subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = str(data.get('endpoint') or '').strip()
    keys = data.get('keys') or {}
    p256dh = str(keys.get('p256dh') or '').strip()
    auth = str(keys.get('auth') or '').strip()
    if not endpoint or not p256dh or not auth:
        return jsonify({'ok': False, 'error': 'Invalid push subscription.'}), 400
    row = PushSubscription.query.filter_by(endpoint=endpoint).first()
    if row:
        row.user_id = current_user.id
        row.p256dh = p256dh
        row.auth = auth
        row.user_agent = request.headers.get('User-Agent', '')[:500]
    else:
        db.session.add(PushSubscription(
            user_id=current_user.id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=request.headers.get('User-Agent', '')[:500],
        ))
    db.session.commit()
    return jsonify({'ok': True})


@app.delete('/push/subscribe')
@login_required
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = str(data.get('endpoint') or '').strip()
    if endpoint:
        PushSubscription.query.filter_by(endpoint=endpoint, user_id=current_user.id).delete(synchronize_session=False)
        db.session.commit()
    return jsonify({'ok': True})


@app.after_request
def process_push_after_request(response):
    if request.path not in ('/push/subscribe', '/push/unsubscribe') and response.status_code < 500:
        try:
            process_push_queue(limit=10)
        except Exception:
            app.logger.exception('Push notification queue processing failed')
    return response
