"""Safe Render entrypoint for Merco.

The legacy app module references @login_required during import but its import
list omitted the decorator. Seed the symbol before loading merco_runtime so
both the legacy runtime and the production fixes can initialize normally.
"""

import builtins
import threading
import time

from flask_login import login_required

builtins.login_required = login_required

from merco_runtime import app  # noqa: E402

# Load the SMTP email integration after the application and production routes
# are initialized. This installs the verification/transactional email hooks.
import email_notifications  # noqa: E402,F401
import email_overrides  # noqa: E402,F401


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
