"""Safe production entrypoint for Merco."""

import builtins
import threading
import time

from flask import jsonify
from flask_login import login_required

builtins.login_required = login_required

from merco_runtime import app  # noqa: E402

# Load production integrations after the application and marketplace routes.
import email_notifications  # noqa: E402,F401
import notifications  # noqa: E402,F401
import push_notifications  # noqa: E402,F401
import email_overrides  # noqa: E402,F401
import adminfix  # noqa: E402,F401
import paystack_redirectfix  # noqa: E402,F401


@app.get('/health')
def merco_health():
    """Lightweight Railway health endpoint that does not depend on the database."""
    return jsonify({'status': 'ok', 'service': 'merco'}), 200


def _email_worker():
    """Drain queued emails without slowing down normal web requests."""
    while True:
        try:
            email_notifications.process_email_queue(limit=3)
        except Exception:
            app.logger.exception('Background email worker failed.')
        time.sleep(15)


def _push_worker():
    """Deliver queued browser push notifications in the background."""
    while True:
        try:
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
