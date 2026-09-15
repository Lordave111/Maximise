"""Expose the root service worker required by the Web Push API."""

from flask import Response

from sitefix import app


@app.get('/sw.js', endpoint='service_worker')
def service_worker():
    # Service workers must be served from the root scope. Keep the actual
    # worker source in static/sw.js, but expose it at /sw.js so browsers can
    # register it for the entire Merco origin.
    with open(app.static_folder + '/sw.js', 'r', encoding='utf-8') as handle:
        source = handle.read()
    return Response(source, mimetype='application/javascript', headers={
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Service-Worker-Allowed': '/',
    })
