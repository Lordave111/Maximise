"""Production seller verification hardening for Merco.

This module patches the existing seller-verification flow without replacing the
main application. It fixes the successful-verification redirect and can send
the five-minute verification link automatically through WhatsApp Cloud API
when the required Railway variables are configured. A click-to-chat fallback
is retained when the API is not configured.
"""

import os
from urllib.parse import quote

import requests
from flask import flash, redirect, request, url_for
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired

import merco_runtime
from sitefix import app
import app as app_module
import bootstrap

SELLER_VERIFICATION_MAX_AGE = 300


def _token(user):
    return app_module._serializer().dumps({
        'id': user.id,
        'whatsapp': user.pending_seller_whatsapp,
        'purpose': 'seller-whatsapp',
    })


def _verification_url(user):
    base = (os.environ.get('MERCO_PUBLIC_URL') or 'https://maximise-production.up.railway.app').rstrip('/')
    return f"{base}/verify-seller-whatsapp/{_token(user)}"


def _send_whatsapp_template(recipient, seller_name, verification_link):
    """Send the verification link with WhatsApp Cloud API when configured."""
    token = (os.environ.get('WHATSAPP_ACCESS_TOKEN') or '').strip()
    phone_id = (os.environ.get('WHATSAPP_PHONE_NUMBER_ID') or '').strip()
    template_name = (os.environ.get('WHATSAPP_VERIFICATION_TEMPLATE') or 'seller_verification').strip()
    language = (os.environ.get('WHATSAPP_TEMPLATE_LANGUAGE') or 'en_US').strip()
    if not token or not phone_id:
        return False

    api_version = (os.environ.get('WHATSAPP_GRAPH_API_VERSION') or 'v23.0').strip()
    endpoint = f'https://graph.facebook.com/{api_version}/{phone_id}/messages'
    payload = {
        'messaging_product': 'whatsapp',
        'to': recipient,
        'type': 'template',
        'template': {
            'name': template_name,
            'language': {'code': language},
            'components': [
                {
                    'type': 'body',
                    'parameters': [
                        {'type': 'text', 'text': seller_name[:100]},
                        {'type': 'text', 'text': '5 minutes'},
                    ],
                },
                {
                    'type': 'button',
                    'sub_type': 'url',
                    'index': '0',
                    'parameters': [
                        {'type': 'text', 'text': verification_link.rsplit('/', 1)[-1]},
                    ],
                },
            ],
        },
    }
    try:
        response = requests.post(
            endpoint,
            headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
            json=payload,
            timeout=20,
        )
        if 200 <= response.status_code < 300:
            app.logger.info('WhatsApp seller verification sent to %s', recipient)
            return True
        app.logger.error('WhatsApp verification rejected: HTTP %s: %s', response.status_code, response.text[:1000])
    except requests.RequestException:
        app.logger.exception('WhatsApp verification API request failed')
    return False


def _activate_seller_fixed():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    if current_user.role != 'buyer':
        return redirect(url_for('dashboard'))
    try:
        seller_name = (request.form.get('seller_name') or current_user.username).strip()[:100]
        public_email = (request.form.get('contact_email') or current_user.email).strip()[:160]
        phone = (request.form.get('phone_number') or '').strip()[:40]
        whatsapp = ''.join(ch for ch in (request.form.get('whatsapp') or '').strip() if ch.isdigit())[:30]
        if not seller_name or not public_email or '@' not in public_email or not phone or not whatsapp:
            raise ValueError('Seller name, public email, phone and WhatsApp are required.')

        admin_whatsapp = ''.join(ch for ch in os.environ.get('MERCO_VERIFICATION_WHATSAPP', '').strip() if ch.isdigit())
        if not admin_whatsapp:
            raise ValueError('Seller verification is temporarily unavailable. Please contact Merco support.')

        bootstrap.save_contact(current_user, public_email, phone, require_phone=True)
        current_user.pending_seller_name = seller_name
        current_user.pending_seller_email = public_email
        current_user.pending_seller_phone = phone
        current_user.pending_seller_whatsapp = whatsapp
        current_user.seller_verification_status = 'pending'
        current_user.seller_verified = False
        app_module.db.session.commit()

        verification_link = _verification_url(current_user)
        # Prefer automatic delivery to the seller's WhatsApp. The customer-care
        # number remains the configured support identity for fallback chat.
        sent = _send_whatsapp_template(whatsapp, seller_name, verification_link)
        if sent:
            flash('Customer Care has sent your WhatsApp verification link. Open it within 5 minutes to activate your store.')
            return redirect(url_for('settings'))

        message = (
            'Hello Merco Customer Care, I want to open a seller store.\n\n'
            f'Name: {seller_name}\n'
            f'WhatsApp: {whatsapp}\n\n'
            'Please send/confirm my Merco seller verification link. The link is valid for 5 minutes.\n'
            f'Verification link: {verification_link}'
        )
        wa_url = f'https://wa.me/{admin_whatsapp}?text={quote(message)}'
        flash('WhatsApp automatic delivery is not configured yet, so Merco opened Customer Care for verification.')
        return redirect(wa_url)
    except ValueError as exc:
        app_module.db.session.rollback()
        flash(str(exc))
        return redirect(url_for('settings'))
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Seller verification request failed')
        flash('Seller verification could not be started. Please try again.')
        return redirect(url_for('settings'))


def _verify_seller_whatsapp_fixed(token):
    try:
        data = app_module._serializer().loads(token, max_age=SELLER_VERIFICATION_MAX_AGE)
        if data.get('purpose') != 'seller-whatsapp':
            raise BadSignature()
        user_id = int(data['id'])
        token_whatsapp = str(data.get('whatsapp') or '').strip()
        user = app_module.User.query.filter_by(id=user_id).first()
        if not user:
            raise BadSignature()
        if (
            user.role != 'buyer'
            or user.seller_verification_status != 'pending'
            or not user.pending_seller_whatsapp
            or ''.join(ch for ch in user.pending_seller_whatsapp if ch.isdigit()) != token_whatsapp
        ):
            flash('This seller verification link is no longer valid. Start Seller Mode again to get a new link.')
            return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))

        user.role = 'seller'
        user.username = user.pending_seller_name or user.username
        user.seller_slug = app_module.unique_seller_slug(user.username, user.id)
        user.whatsapp_number = user.pending_seller_whatsapp
        user.seller_verified = True
        user.seller_verification_status = 'verified'
        user.pending_seller_name = None
        user.pending_seller_email = None
        user.pending_seller_phone = None
        user.pending_seller_whatsapp = None
        app_module.db.session.commit()

        # Do not redirect to the old nonexistent seller_page endpoint; that was
        # the source of the Internal Server Error after a valid verification.
        if current_user.is_authenticated and current_user.id == user.id:
            flash('Your seller account is verified and your store is now active.')
            return redirect(url_for('seller_dashboard'))
        return redirect(url_for('login'))
    except (BadSignature, SignatureExpired, ValueError, TypeError, KeyError):
        flash('That seller verification link is invalid or has expired. Start Seller Mode again to get a new link.')
        return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Seller WhatsApp verification failed')
        flash('Seller verification could not be completed. Please request a new link.')
        return redirect(url_for('login'))


# Patch the existing production wrapper's functions and Flask endpoint in place.
merco_runtime._activate_seller = _activate_seller_fixed
app.view_functions['verify_seller_whatsapp'] = _verify_seller_whatsapp_fixed
app.view_functions['activate_seller_production'] = _activate_seller_fixed
