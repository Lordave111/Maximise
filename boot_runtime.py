"""Safe production entrypoint for Merco."""

import builtins
import os
import threading
import time

from flask import jsonify, session
from flask_login import login_required

builtins.login_required = login_required

from merco_runtime import app  # noqa: E402

MERCO_RAILWAY_URL = 'https://maximise-production.up.railway.app'
os.environ['MERCO_PUBLIC_URL'] = MERCO_RAILWAY_URL
app.config['MERCO_PUBLIC_URL'] = MERCO_RAILWAY_URL

# Seller Mode uses a short-lived signed link. No WhatsApp Cloud API is required.
# Import the seller fix only after the canonical public URL is configured.
import seller_verification_fix  # noqa: E402,F401
import seller_store_verification_route  # noqa: E402,F401

# Database-backed integrations must initialize inside an application context.
with app.app_context():
    import email_notifications  # noqa: E402,F401
    import email_api  # noqa: E402,F401
    import email_overrides  # noqa: E402,F401

import notifications  # noqa: E402,F401
import push_notifications  # noqa: E402,F401
import adminfix  # noqa: E402,F401
import paystack_redirectfix  # noqa: E402,F401
import swfix  # noqa: E402,F401

try:
    with app.app_context():
        stale_jobs = email_notifications.EmailJob.query.filter(
            email_notifications.EmailJob.event_type == 'verification',
            email_notifications.EmailJob.status.in_(['pending', 'sending'])
        ).all()
        for stale_job in stale_jobs:
            stale_job.status = 'cancelled'
        if stale_jobs:
            email_notifications.db.session.commit()
except Exception:
    app.logger.exception('Could not clear stale verification email jobs during startup.')

_original_resend_verification = app.view_functions.get('resend_verification')
if _original_resend_verification:
    def _railway_resend_verification():
        response = _original_resend_verification()
        flashes = session.get('_flashes', [])
        session['_flashes'] = [
            (category, str(message).replace('Render', 'Railway'))
            for category, message in flashes
        ]
        return response
    app.view_functions['resend_verification'] = _railway_resend_verification


@app.get('/health')
def merco_health():
    return jsonify({'status': 'ok', 'service': 'merco'}), 200


def _email_worker():
    """Run the email queue with a dedicated Flask application context."""
    while True:
        try:
            with app.app_context():
                email_notifications.process_email_queue(limit=3)
        except Exception:
            app.logger.exception('Background email worker failed.')
        time.sleep(15)


def _push_worker():
    """Run the push queue with a dedicated Flask application context."""
    while True:
        try:
            with app.app_context():
                push_notifications.process_push_queue(limit=20)
        except Exception:
            app.logger.exception('Background push worker failed.')
        time.sleep(5)


if not app.extensions.get('merco_email_worker_started'):
    app.extensions['merco_email_worker_started'] = True
    threading.Thread(target=_email_worker, name='merco-email-worker', daemon=True).start()

if not app.extensions.get('merco_push_worker_started'):
    app.extensions['merco_push_worker_started'] = True
    threading.Thread(target=_push_worker, name='merco-push-worker', daemon=True).start()

application = app
