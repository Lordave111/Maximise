"""Final seller verification route override.

Keeps verification independent of the user's browser session and opens the
actual public store route after activation. This exists as a small production
shim so older seller-verification code cannot send a successful verification
back to Settings because of a stale/nonexistent seller_page endpoint.
"""

from flask import flash, redirect, url_for
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired

from sitefix import app
import app as app_module
import seller_verification_fix as seller_fix


def _public_store_url(slug):
    return url_for('public_store', seller_slug=slug, _external=True)


def verify_seller(token):
    try:
        data = seller_fix._load_token(token)
        if data.get('purpose') not in ('seller-link', 'seller-whatsapp'):
            raise BadSignature()

        user_id = int(data['id'])
        user = app_module.User.query.filter_by(id=user_id).first()
        if not user:
            raise BadSignature()

        if user.role == 'seller' and user.seller_verified:
            return seller_fix._verification_progress_html(
                user.username or 'Seller',
                _public_store_url(user.seller_slug),
            )

        if user.role != 'buyer' or user.seller_verification_status != 'pending':
            flash('This seller verification link is no longer valid. Start Seller Mode again to create a new link.')
            return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))

        seller_name = (user.pending_seller_name or user.username or 'Merco Seller').strip()[:100]
        public_email = seller_fix._valid_email(user.pending_seller_email)
        phone = seller_fix._normalize_phone(user.pending_seller_phone)
        whatsapp = seller_fix._normalize_phone(user.pending_seller_whatsapp)

        if not public_email or not phone or not whatsapp:
            raise ValueError('The saved seller email or phone details are no longer valid. Please restart Seller Mode.')

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

        app.logger.info('SELLER_VERIFICATION_SUCCESS user_id=%s slug=%s', user.id, slug)
        return seller_fix._verification_progress_html(seller_name, _public_store_url(slug))

    except SignatureExpired:
        app_module.db.session.rollback()
        flash('That seller verification link has expired. Start Seller Mode again to create a new 5-minute link.')
        return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))
    except (BadSignature, ValueError, TypeError, KeyError):
        app_module.db.session.rollback()
        flash('That seller verification link is invalid. Start Seller Mode again to create a new link.')
        return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Final seller verification route failed')
        return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))


# New clean route and compatibility route both use this final handler.
app.add_url_rule('/verify-seller-final/<token>', endpoint='verify_seller_final', view_func=verify_seller)
app.add_url_rule('/verify-seller/<token>', endpoint='verify_seller_direct_final', view_func=verify_seller)
app.view_functions['verify_seller_whatsapp'] = verify_seller
