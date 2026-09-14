"""External Web Push notifications for Merco."""
import json
import os
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import event
from sitefix import app, db

try:
    from pywebpush import webpush, WebPushException
except Exception:
    webpush = None
    WebPushException = Exception


class PushSubscription(db.Model):
    __tablename__ = 'push_subscription'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    endpoint = db.Column(db.String(2000), nullable=False, unique=True)
    p256dh = db.Column(db.String(500), nullable=False)
    auth = db.Column(db.String(500), nullable=False)
    user_agent = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class PushJob(db.Model):
    __tablename__ = 'push_job'
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)


with app.app_context():
    db.create_all()


def vapid_public_key():
    return (os.environ.get('VAPID_PUBLIC_KEY') or '').strip()


def push_configured():
    return bool(webpush and vapid_public_key() and os.environ.get('VAPID_PRIVATE_KEY') and os.environ.get('VAPID_CLAIMS_EMAIL'))


def send_push(subscription, title, message, url='/market', kind='general'):
    if not push_configured():
        return False
    payload = json.dumps({'title': str(title)[:180], 'body': str(message)[:1000], 'url': url or '/market', 'kind': kind or 'general', 'icon': '/static/icons/icon-192.svg', 'badge': '/static/icons/icon-192.svg'})
    info = {'endpoint': subscription.endpoint, 'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth}}
    try:
        webpush(subscription_info=info, data=payload, vapid_private_key=os.environ['VAPID_PRIVATE_KEY'], vapid_claims={'sub': os.environ['VAPID_CLAIMS_EMAIL']})
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if status in (404, 410):
            try:
                db.session.delete(subscription)
                db.session.commit()
            except Exception:
                db.session.rollback()
        app.logger.warning('Web Push delivery failed: %s', exc)
        return False
    except Exception:
        app.logger.exception('Unexpected Web Push delivery failure')
        return False


def send_push_to_user(user_id, title, message, url='/market', kind='general'):
    sent = 0
    for subscription in PushSubscription.query.filter_by(user_id=user_id).all():
        if send_push(subscription, title, message, url, kind):
            sent += 1
    return sent


# Queue each persistent in-site notification for external delivery. The queue is
# inserted in the same DB transaction, so events cannot be lost between layers.
try:
    from notifications import Notification

    @event.listens_for(Notification, 'after_insert')
    def queue_notification_push(mapper, connection, target):
        connection.execute(PushJob.__table__.insert().values(notification_id=target.id, status='pending', attempts=0, created_at=datetime.utcnow()))
except Exception:
    pass


def process_push_queue(limit=20):
    if not push_configured():
        return 0
    from notifications import Notification
    jobs = PushJob.query.filter_by(status='pending').order_by(PushJob.created_at.asc()).limit(limit).all()
    processed = 0
    for job in jobs:
        job.status = 'processing'
        job.attempts += 1
        db.session.commit()
        notification = db.session.get(Notification, job.notification_id)
        if not notification:
            job.status = 'sent'
            job.processed_at = datetime.utcnow()
            db.session.commit()
            continue
        send_push_to_user(notification.user_id, notification.title, notification.message, notification.action_url or '/market', notification.kind)
        job.status = 'sent'
        job.processed_at = datetime.utcnow()
        db.session.commit()
        processed += 1
    return processed


@app.get('/api/push/public-key')
def push_public_key_api():
    return jsonify({'ok': True, 'configured': push_configured(), 'publicKey': vapid_public_key()})


@app.get('/api/push/status')
@login_required
def push_status():
    return jsonify({'ok': True, 'configured': push_configured(), 'subscriptions': PushSubscription.query.filter_by(user_id=current_user.id).count()})


@app.post('/api/push/subscribe')
@login_required
def push_subscribe():
    if not push_configured():
        return jsonify({'ok': False, 'error': 'Push notifications are not configured on the server yet.'}), 503
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
        db.session.add(PushSubscription(user_id=current_user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=request.headers.get('User-Agent', '')[:500]))
    db.session.commit()
    return jsonify({'ok': True})


@app.post('/api/push/unsubscribe')
@login_required
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = str(data.get('endpoint') or '').strip()
    query = PushSubscription.query.filter_by(user_id=current_user.id)
    if endpoint:
        query = query.filter_by(endpoint=endpoint)
    deleted = query.delete(synchronize_session=False)
    db.session.commit()
    return jsonify({'ok': True, 'deleted': deleted})
