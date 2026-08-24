"""Production wrapper for Merco.

Loads the hardened application and provides defensive production overrides for
Seller Mode and Settings so failures never turn the page into a blank/500
response.
"""

from flask import flash, redirect, render_template, request, url_for
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


def _production_settings():
    """Stable Settings view with the seller contact object always available.

    The original settings template expects ``contact``. The older route did
    not pass it on GET, which could make Settings/Seller activation appear as
    a blank page depending on the Jinja undefined configuration.
    """
    if request.method == 'POST':
        action = request.form.get('action', '').strip()

        if action == 'preferences':
            language = request.form.get('language', 'auto').strip().lower()
            currency = request.form.get('currency', 'NGN').strip().upper()
            if language != 'auto' and language not in app_module.SUPPORTED_LANGUAGES:
                language = 'auto'
            if currency not in app_module.SUPPORTED_CURRENCIES:
                currency = 'NGN'
            current_user.preferred_language = language
            current_user.preferred_currency = currency
            current_user.email_notifications = request.form.get('email_notifications') == '1'
            app_module.db.session.commit()
            flash('Language, currency and email preferences saved.')
            return redirect(url_for('settings'))

        if action == 'profile':
            current_user.username = request.form.get('username', current_user.username).strip()[:100]
            current_user.whatsapp_number = request.form.get(
                'whatsapp', current_user.whatsapp_number or ''
            ).strip()[:30]
            public_email = request.form.get('contact_email', current_user.email).strip()[:160]
            phone = request.form.get('phone_number', '').strip()[:40]
            try:
                bootstrap.save_contact(current_user, public_email, phone, require_phone=False)
                app_module.db.session.commit()
                flash('Profile and seller contact details saved.')
            except Exception as exc:
                app_module.db.session.rollback()
                flash(str(exc))
            return redirect(url_for('settings'))

        # Seller activation is intercepted by safe_seller_activation below.
        if action == 'become_seller':
            return _activate_seller()

        flash('Nothing to update.')
        return redirect(url_for('settings'))

    try:
        contact = bootstrap.get_contact(current_user)
    except Exception:
        app.logger.exception('Could not load seller contact for settings')
        contact = None

    return render_template('settings.html', contact=contact)


# Replace the fragile original Settings view with the production-safe one while
# keeping the public endpoint name ``settings`` unchanged.
app.view_functions['settings'] = _production_settings


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
import push_notifications  # noqa: E402,F401

application = app
