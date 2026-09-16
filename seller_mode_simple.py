"""Simple Seller Mode: instant seller access with direct dashboard navigation."""

from flask import redirect, url_for, request, flash
from flask_login import current_user, login_required

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


def simple_settings():
    """Keep the real Settings page intact while handling Seller Mode activation."""
    if request.method == 'POST' and request.form.get('action') == 'become_seller' and current_user.role == 'buyer':
        seller_name = (request.form.get('seller_name') or current_user.username).strip()[:100]
        whatsapp = request.form.get('whatsapp', '').strip()[:30]
        if not seller_name:
            flash('Enter a store name.')
            return redirect(url_for('settings'))
        if not whatsapp:
            flash('Add a WhatsApp number so buyers can contact you.')

            return redirect(url_for('settings'))

        try:
            slug = app_module.unique_seller_slug(seller_name, current_user.id)
            current_user.username = seller_name
            current_user.role = 'seller'
            current_user.seller_slug = slug
            current_user.whatsapp_number = whatsapp
            current_user.seller_verified = True
            current_user.seller_verification_status = 'none'
            current_user.pending_seller_name = None
            current_user.pending_seller_email = None
            current_user.pending_seller_phone = None
            current_user.pending_seller_whatsapp = None
            app_module.db.session.commit()
            return redirect(url_for('seller_dashboard'))
        except Exception:
            app_module.db.session.rollback()
            app.logger.exception('Instant Seller Mode activation failed')
            flash('Could not create your seller store. Please try again.')
            return redirect(url_for('settings'))

    # All normal Settings GET/POST requests are handled by the original
    # settings endpoint, including profile and preference updates.
    original = app.view_functions.get('settings_original')
    if original:
        return original()
    return redirect(url_for('dashboard'))


_original_settings = app.view_functions.get('settings')
if _original_settings:
    app.view_functions['settings_original'] = _original_settings
app.view_functions['settings'] = simple_settings
