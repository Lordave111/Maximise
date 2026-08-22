"""Production wrapper for Merco.

Loads the hardened application and provides a dedicated, defensive Seller Mode
activation endpoint so failures never turn the Settings page into a blank/500
response.
"""

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from sitefix import app
import app as app_module
import bootstrap


def _activate_seller():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    if current_user.role != 'buyer':
        return redirect(url_for('dashboard'))

    try:
        if not current_user.email_verified:
            sent = app_module.send_verification_email(current_user)
            flash('Verify your email before opening your seller store. ' + ('A fresh verification email has been sent.' if sent else 'Please verify your email first.'))
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

        bootstrap.save_contact(current_user, public_email, phone, require_phone=True)
        current_user.role = 'seller'
        current_user.username = seller_name
        current_user.seller_slug = app_module.unique_seller_slug(seller_name, current_user.id)
        current_user.whatsapp_number = whatsapp
        app_module.db.session.commit()

        flash('Seller Mode activated successfully. Your storefront is now live.')
        return redirect(url_for('seller_dashboard'))
    except ValueError as exc:
        app_module.db.session.rollback()
        flash(str(exc))
        return redirect(url_for('settings'))
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Seller activation failed')
        flash('Seller Mode could not be activated. No account changes were saved. Please try again.')
        return redirect(url_for('settings'))


@app.route('/activate-seller', methods=['POST'], endpoint='activate_seller_production')
@login_required
def activate_seller_production():
    return _activate_seller()


@app.before_request
def safe_seller_activation():
    # Backward compatibility for older Settings forms still posting here.
    if request.path != '/settings' or request.method != 'POST':
        return None
    if request.form.get('action') != 'become_seller':
        return None
    return _activate_seller()


# Load queued EmailJS lifecycle notifications after all marketplace feature
# modules have registered their models and routes.
import email_notifications  # noqa: E402,F401

application = app
