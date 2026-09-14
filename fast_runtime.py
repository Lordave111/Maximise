"""Fast production entrypoint for Merco.

Loads the existing runtime configuration, then removes the legacy request-time
Demo catalogue repair hook. Demo data must never block normal page requests.
"""

from flask import jsonify
from sqlalchemy import text

import merco_runtime
from merco_runtime import app
import app as app_module


# merco_runtime keeps the old repair function for manual maintenance, but it
# must not run when somebody opens /market. Removing it here makes the deployed
# web process fast without changing the database contents.
for _before_fn in list(app.before_request_funcs.get(None, [])):
    if getattr(_before_fn, '__name__', '') == '_repair_demo_market_on_request':
        app.before_request_funcs[None].remove(_before_fn)


@app.get('/fast-health')
def fast_health():
    try:
        app_module.db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'ok', 'service': 'merco', 'database': 'ok'}), 200
    except Exception:
        app_module.db.session.rollback()
        return jsonify({'status': 'degraded', 'service': 'merco', 'database': 'unavailable'}), 503


# Keep the original health endpoint lightweight too. It must never seed or
# repair hundreds of catalogue records during a health check.
app.view_functions['health'] = fast_health

application = app
