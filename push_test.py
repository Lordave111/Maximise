"""Small diagnostic endpoint for Merco Web Push.

It sends one real push immediately after a device subscribes, so users do not
have to wait for the notification queue to discover a newly created alert.
"""
from flask import jsonify
from flask_login import current_user, login_required

from app import app, db
from push_notifications import PushSubscription, _send, _vapid_ready


@app.post('/push/test')
@login_required
def push_test():
    if not _vapid_ready():
        return jsonify({
            'ok': False,
            'error': 'Phone alerts are not configured on the server. Add VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_CLAIMS_EMAIL in Render.'
        }), 503

    subscriptions = PushSubscription.query.filter_by(user_id=current_user.id).all()
    if not subscriptions:
        return jsonify({'ok': False, 'error': 'This device is not subscribed yet.'}), 400

    class TestNotification:
        id = f'test-{current_user.id}'
        title = 'Merco notifications enabled'
        message = 'Phone alerts are working on this device.'
        link = '/notifications'

    errors = []
    sent = 0
    for subscription in list(subscriptions):
        try:
            _send(subscription, TestNotification())
            sent += 1
        except Exception as exc:
            errors.append(str(exc)[:500])

    if sent:
        return jsonify({'ok': True, 'message': 'Test notification sent to this device.'})

    db.session.rollback()
    return jsonify({'ok': False, 'error': errors[0] if errors else 'Push delivery failed.'}), 502
