"""Seller verification without a WhatsApp API.

Generates a signed five-minute verification link and opens normal WhatsApp
click-to-chat with Merco Customer Care. Opening the link verifies the matching
buyer automatically.
"""
import os
from urllib.parse import quote
from flask import flash, redirect, request, url_for
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired
import merco_runtime
from sitefix import app
import app as app_module
import bootstrap

SELLER_VERIFICATION_MAX_AGE = 300

def _token(user):
    return app_module._serializer().dumps({'id': user.id, 'whatsapp': user.pending_seller_whatsapp, 'purpose': 'seller-whatsapp'})

def _verification_url(user):
    base = (os.environ.get('MERCO_PUBLIC_URL') or 'https://maximise-production.up.railway.app').rstrip('/')
    return f"{base}/verify-seller-whatsapp/{_token(user)}"

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
        customer_care = ''.join(ch for ch in os.environ.get('MERCO_VERIFICATION_WHATSAPP', '').strip() if ch.isdigit())
        if not customer_care:
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
        message = ('Hello Merco Customer Care, I want to open a seller store.\n\n'
                   f'Name: {seller_name}\nWhatsApp: {whatsapp}\n\n'
                   'My secure seller verification link is below. I will open it within 5 minutes to activate Seller Mode automatically.\n\n'
                   f'Verification link: {verification_link}')
        wa_url = f'https://wa.me/{customer_care}?text={quote(message)}'
        flash('WhatsApp is ready with your secure verification link. Send the message, then open the link within 5 minutes to activate your store.')
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
        stored_whatsapp = ''.join(ch for ch in (user.pending_seller_whatsapp or '') if ch.isdigit())
        if user.role != 'buyer' or user.seller_verification_status != 'pending' or not stored_whatsapp or stored_whatsapp != token_whatsapp:
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
        if current_user.is_authenticated and current_user.id == user.id:
            flash('Your seller account is verified and your store is now active.')
            return redirect(url_for('seller_dashboard'))
        return redirect(url_for('login'))
    except (BadSignature, SignatureExpired, ValueError, TypeError, KeyError):
        flash('That seller verification link is invalid or has expired. Start Seller Mode again to get a new link.')
        return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Seller verification failed')
        flash('Seller verification could not be completed. Please request a new link.')
        return redirect(url_for('login'))

merco_runtime._activate_seller = _activate_seller_fixed
app.view_functions['verify_seller_whatsapp'] = _verify_seller_whatsapp_fixed
app.view_functions['activate_seller_production'] = _activate_seller_fixed
