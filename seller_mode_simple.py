"""Seller Mode route helpers.

The canonical Settings handler lives in merco_runtime.py. This module only
provides the seller entry route so it cannot override or break Settings.
"""

from flask import redirect, url_for, flash
from flask_login import login_required

from sitefix import app
import app as app_module


@app.get('/seller/open/<seller_slug>')
@login_required
def seller_open(seller_slug):
    seller = app_module.User.query.filter_by(
        seller_slug=seller_slug, role='seller'
    ).first()
    if not seller:
        flash('Store not found.')
        return redirect(url_for('settings'))
    return redirect(url_for('seller_dashboard'))
