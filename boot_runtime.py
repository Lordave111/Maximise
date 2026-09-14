"""Safe production entrypoint for Merco."""

import builtins
import threading
import time

from flask_login import login_required

builtins.login_required = login_required

from merco_runtime import app  # noqa: E402

# Load production integrations after the application and marketplace routes.
import email_notifications  # noqa: E402,F401
import email_overrides  # noqa: E402,F401
import adminfix  # noqa: E402,F401


def _email_worker():
    """Drain queued emails without slowing down normal web requests."""
    while True:
        try:
            email_notifications.process_email_queue(limit=3)
        except Exception:
            app.logger.exception('Background email worker failed.')
        time.sleep(15)


if not app.extensions.get('merco_email_worker_started'):
    app.extensions['merco_email_worker_started'] = True
    threading.Thread(target=_email_worker, name='merco-email-worker', daemon=True).start()

application = app
