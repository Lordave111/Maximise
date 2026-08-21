"""Small production wrapper for Render.

Loads the hardened Merco app and safely handles Seller Mode activation before
Flask reaches the older settings handler. This keeps a database/contact error
from becoming an unhelpful 500 page.
"""

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from sitefix import app
import app as app_module
import bootstrap


@app.before_request
def safe_seller_activation():
    if request.path != '/settings' or request.method != 'POST':
        return None
    if request.form.get('action') != 'become_seller':
        return None
    if not current_user.is_authenticated:
        return None
    if current_user.role != 'buyer':
        return None

    try:
        if not current_user.email_verified:
            sent = app_module.send_verification_email(current_user)
            flash(
                'Verify your email before opening your seller store. '
                + ('A fresh verification email has been sent.' if sent else 'Please verify your email first.')
            )
            return redirect(url_for('settings'))

        seller_name = (request.form.get('seller_name') or current_user.username).strip()[:100]
        public_email = (request.form.get('contact_email') or current_user.email).strip()[:160]
        phone = (request.form.get('phone_number') or '').strip()[:40]
        whatsapp = (request.form.get('whatsapp') or '').strip()[:30]

        if not seller_name:
            raise ValueError('Enter a seller or store name.')
        if not public_email or '@' not in public_email:
            raise ValueError('Enter a valid public email.')
        if not phone:
            raise ValueError('Add a phone number so buyers can call you.')
        if not whatsapp:
            raise ValueError('Add a WhatsApp number so buyers can contact you.')

        # SellerContact is the canonical public-contact record used by the
        # storefront. save_contact creates it when an older account has none.
        bootstrap.save_contact(current_user, public_email, phone, require_phone=True)
        current_user.role = 'seller'
        current_user.username = seller_name
        current_user.seller_slug = app_module.unique_seller_slug(seller_name, current_user.id)
        current_user.whatsapp_number = whatsapp
        db = app_module.db
        db.session.commit()

        flash('Seller mode activated. Your storefront is now live.')
        return redirect(url_for('seller_dashboard'))
    except ValueError as exc:
        app_module.db.session.rollback()
        flash(str(exc))
        return redirect(url_for('settings'))
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Seller activation failed')
        flash('We could not activate Seller Mode right now. Your account was not changed. Please try again.')
        return redirect(url_for('settings'))


# Keep the normal WSGI object name expected by Render.
application = app
