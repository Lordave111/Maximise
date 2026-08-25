"""Production override for the Web Push subscription endpoint.

The existing queue is retained, but subscription now performs an immediate
end-to-end push test so users know whether VAPID delivery actually works.
"""
from datetime import datetime

from flask import jsonify, request
from flask_login import current_user, login_required

from app import app, db
import social
import push_notifications as push


@login_required
def push_subscribe_fixed():
    data = request.get_json(silent=True) or {}
    endpoint = str(data.get('endpoint') or '').strip()
    keys = data.get('keys') or {}
    p256dh = str(keys.get('p256dh') or '').strip()
    auth = str(keys.get('auth') or '').strip()

    if not endpoint or not p256dh or not auth:
        return jsonify({'ok': False, 'error': 'Invalid push subscription.'}), 400
    if len(endpoint) > 700:
        return jsonify({'ok': False, 'error': 'Push endpoint is unexpectedly long.'}), 400
    if not push._vapid_ready():
        return jsonify({'ok': False, 'error': 'Phone alerts are not configured on the server. Add VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY and VAPID_CLAIMS_EMAIL in Render.'}), 503

    row = push.PushSubscription.query.filter_by(endpoint=endpoint).first()
    if row:
        row.user_id = current_user.id
        row.p256dh = p256dh
        row.auth = auth
        row.user_agent = request.headers.get('User-Agent', '')[:500]
    else:
        row = push.PushSubscription(
            user_id=current_user.id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=request.headers.get('User-Agent', '')[:500],
        )
        db.session.add(row)
    db.session.commit()

    # A real test notification makes the setup self-verifying. It also creates
    # the corresponding in-site notification for the Notifications page.
    test = social.Notification(
        user_id=current_user.id,
        title='Phone alerts enabled',
        message='Merco can now send important marketplace updates to this device.',
        link='/notifications',
        created_at=datetime.utcnow(),
    )
    db.session.add(test)
    db.session.commit()

    try:
        push._send(row, test)
    except Exception as exc:
        app.logger.exception('Initial Web Push delivery failed')
        return jsonify({'ok': False, 'error': f'Device saved, but VAPID delivery failed: {str(exc)[:240]}'}), 502

    return jsonify({'ok': True, 'test_notification_sent': True})


# Keep the existing URL/endpoint name while replacing only the implementation.
app.view_functions['push_subscribe'] = push_subscribe_fixed
