"""Final seller verification route override.

Seller verification is intentionally simple: the secure signed link is the
verification action. We only check that the saved seller contact values exist
and that the Nigerian phone number has the expected length/shape. No OTP,
WhatsApp API, email delivery, or manual approval is involved.
"""

from flask import flash, redirect, url_for
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired

from sitefix import app
import app as app_module
import seller_verification_fix as seller_fix


def _seller_store_url(slug):
    if not slug:
        raise ValueError('Seller store was not created correctly.')
    # app.py's real public storefront endpoint is seller_page.
    return url_for('seller_page', seller_slug=slug, _external=True)


def _settings_or_login():
    return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))


def _phone_exists_and_has_valid_length(value):
    normalized = seller_fix._normalize_phone(value)
    if not normalized:
        return None
    # Nigerian mobile numbers are +234 followed by 10 digits.
    if len(normalized) != 14:
        return None
    return normalized


def verify_seller(token):
    try:
        data = seller_fix._load_token(token)
        if data.get('purpose') not in ('seller-link', 'seller-whatsapp'):
            raise BadSignature()

        user_id = int(data['id'])
        user = app_module.User.query.filter_by(id=user_id).first()
        if not user:
            raise BadSignature()

        # If a previous request already completed, open the store instead of
        # sending the user back to Settings.
        if user.role == 'seller' and user.seller_verified:
            return seller_fix._verification_progress_html(
                user.username or 'Seller',
                _seller_store_url(user.seller_slug),
            )

        if user.role != 'buyer' or user.seller_verification_status != 'pending':
            flash('This seller verification link is no longer valid. Start Seller Mode again to create a new link.')
            return _settings_or_login()

        seller_name = (user.pending_seller_name or user.username or 'Merco Seller').strip()[:100]
        if not seller_name:
            raise ValueError('A seller/store name is required.')

        # The contact details must exist. The phone is only checked for valid
        # Nigerian mobile shape/length; no code is sent and no external service
        # is called to verify ownership.
        public_email = (user.pending_seller_email or user.email or '').strip()
        phone = _phone_exists_and_has_valid_length(user.pending_seller_phone)
        whatsapp = _phone_exists_and_has_valid_length(user.pending_seller_whatsapp)
        if not public_email or not phone or not whatsapp:
            raise ValueError('Your saved email and phone details are incomplete or invalid. Please restart Seller Mode.')

        slug = app_module.unique_seller_slug(seller_name, user.id)
        user.role = 'seller'
        user.username = seller_name
        user.seller_slug = slug
        user.whatsapp_number = whatsapp
        user.seller_verified = True
        user.seller_verification_status = 'verified'
        user.pending_seller_name = None
        user.pending_seller_email = None
        user.pending_seller_phone = None
        user.pending_seller_whatsapp = None
        app_module.db.session.commit()

        seller_url = _seller_store_url(slug)
        app.logger.info('SELLER_VERIFICATION_SUCCESS user_id=%s slug=%s', user.id, slug)
        return seller_fix._verification_progress_html(seller_name, seller_url)

    except SignatureExpired:
        app_module.db.session.rollback()
        flash('That seller verification link has expired. Start Seller Mode again to create a new 5-minute link.')
        return _settings_or_login()
    except (BadSignature, ValueError, TypeError, KeyError):
        app_module.db.session.rollback()
        flash('That seller verification link is invalid or the saved phone details are incomplete. Start Seller Mode again to create a new link.')
        return _settings_or_login()
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Final seller verification route failed')
        return _settings_or_login()


def _replace_or_add_rule(rule_path, endpoint, view_func):
    """Make sure an existing URL path actually dispatches to our final handler."""
    matching = [rule for rule in app.url_map.iter_rules() if rule.rule == rule_path]
    if matching:
        for rule in matching:
            app.view_functions[rule.endpoint] = view_func
        return
    app.add_url_rule(rule_path, endpoint=endpoint, view_func=view_func)


_replace_or_add_rule('/verify-seller/<token>', 'verify_seller_final', verify_seller)
app.view_functions['verify_seller_whatsapp'] = verify_seller
if 'verify_seller_final' not in app.view_functions:
    app.view_functions['verify_seller_final'] = verify_seller

if not any(rule.rule == '/verify-seller-final/<token>' for rule in app.url_map.iter_rules()):
    app.add_url_rule('/verify-seller-final/<token>', endpoint='verify_seller_final_url', view_func=verify_seller)
