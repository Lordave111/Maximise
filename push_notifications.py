"""External Web Push notifications for Merco.

Requires VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_CLAIMS_EMAIL in the environment.
"""
import json
import os
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user, login_required
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


with app.app_context():
    db.create_all()


def vapid_public_key():
    return (os.environ.get('VAPID_PUBLIC_KEY') or '').strip()


def push_configured():
    return bool(webpush and vapid_public_key() and os.environ.get('VAPID_PRIVATE_KEY') and os.environ.get('VAPID_CLAIMS_EMAIL'))


def send_push(subscription, title, message, url='/market', kind='general'):
    if not push_configured():
        return False
    payload = json.dumps({
        'title': str(title)[:180],
        'body': str(message)[:1000],
        'url': url or '/market',
        'kind': kind or 'general',
        'icon': '/static/icons/icon-192.svg',
        'badge': '/static/icons/icon-192.svg'
    })
    info = {'endpoint': subscription.endpoint, 'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth}}
    try:
        webpush(
            subscription_info=info,
            data=payload,
            vapid_private_key=os.environ['VAPID_PRIVATE_KEY'],
            vapid_claims={'sub': os.environ['VAPID_CLAIMS_EMAIL']},
        )
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
    subscriptions = PushSubscription.query.filter_by(user_id=user_id).all()
    sent = 0
    for subscription in subscriptions:
        if send_push(subscription, title, message, url, kind):
            sent += 1
    return sent


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
        row = PushSubscription(user_id=current_user.id, endpoint=endpoint, p256dh=p256dh, auth=auth, user_agent=request.headers.get('User-Agent', '')[:500])
        db.session.add(row)
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


def send_push_for_notification(row):
    """Best-effort external counterpart of an in-site Notification row."""
    if not row or not row.user_id:
        return 0
    return send_push_to_user(row.user_id, row.title, row.message, row.action_url or '/market', row.kind)
