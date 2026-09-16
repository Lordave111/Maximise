"""Seller verification without a WhatsApp API.

Normal WhatsApp only shares the short-lived verification link. The link itself
activates Seller Mode; no WhatsApp API or email verification is required.
"""
import hashlib
import os
import re
from urllib.parse import quote

from flask import flash, redirect, request, url_for
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import merco_runtime
from sitefix import app
import app as app_module
import bootstrap

SELLER_VERIFICATION_MAX_AGE = 300
SELLER_TOKEN_SALT = "merco-seller-whatsapp-v2"
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def _seller_serializer():
    configured = (os.environ.get("SECRET_KEY") or "").strip()
    if configured:
        key = configured
    else:
        database_url = (os.environ.get("DATABASE_URL") or "").strip()
        seed = database_url or "merco-local-seller-verification"
        key = hashlib.sha256(("merco-seller-key-v1:" + seed).encode("utf-8")).hexdigest()
    return URLSafeTimedSerializer(key, salt=SELLER_TOKEN_SALT)


def _normalize_phone(value):
    """Normalize common Nigerian phone formats and reject obviously fake input."""
    raw = (value or "").strip()
    digits = ''.join(ch for ch in raw if ch.isdigit())
    if raw.startswith('+'):
        normalized = '+' + digits
    elif digits.startswith('234'):
        normalized = '+' + digits
    elif digits.startswith('0') and len(digits) == 11:
        normalized = '+234' + digits[1:]
    else:
        normalized = '+' + digits if digits else ''

    # Nigeria mobile numbers are +234 followed by 10 digits, with mobile
    # prefixes beginning 70-90. Also reject repeated/single-digit placeholders.
    if not re.fullmatch(r'\+234[789]\d{9}', normalized):
        return None
    local = normalized[4:]
    if len(set(local)) == 1:
        return None
    return normalized


def _valid_email(value):
    email = (value or '').strip().lower()
    if len(email) > 160 or not EMAIL_RE.fullmatch(email):
        return None
    local, domain = email.rsplit('@', 1)
    if len(local) > 64 or domain.startswith('.') or domain.endswith('.') or '..' in domain:
        return None
    return email


def _token(user):
    whatsapp = _normalize_phone(user.pending_seller_whatsapp or '')
    return _seller_serializer().dumps({
        'id': int(user.id),
        'whatsapp': whatsapp,
        'purpose': 'seller-whatsapp',
    })


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
        public_email = _valid_email(request.form.get('contact_email') or current_user.email)
        phone = _normalize_phone(request.form.get('phone_number') or '')
        whatsapp = _normalize_phone(request.form.get('whatsapp') or '')
        customer_care = ''.join(ch for ch in os.environ.get('MERCO_VERIFICATION_WHATSAPP', '').strip() if ch.isdigit())
        if not seller_name:
            raise ValueError('Please enter a seller/store name.')
        if not public_email:
            raise ValueError('Please enter a valid email address, for example name@gmail.com.')
        if not phone:
            raise ValueError('Please enter a valid Nigerian phone number, for example 08012345678 or +2348012345678.')
        if not whatsapp:
            raise ValueError('Please enter a valid Nigerian WhatsApp number, for example 08012345678 or +2348012345678.')
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
        message = (
            'Hello Merco Customer Care, I want to open a seller store.\n\n'
            f'Name: {seller_name}\n'
            f'WhatsApp: {whatsapp}\n\n'
            'My secure seller verification link is below. I will open it within 5 minutes to activate Seller Mode automatically.\n\n'
            f'Verification link: {verification_link}'
        )
        wa_url = f'https://wa.me/{customer_care}?text={quote(message, safe="")}'
        flash('Details accepted. WhatsApp is ready with your secure 5-minute verification link.')
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


def _load_token(token):
    try:
        return _seller_serializer().loads(token, max_age=SELLER_VERIFICATION_MAX_AGE)
    except SignatureExpired:
        raise
    except BadSignature as stable_error:
        try:
            return app_module._serializer().loads(token, max_age=SELLER_VERIFICATION_MAX_AGE)
        except Exception:
            raise stable_error


def _seller_verification_success_html(name):
    safe_name = (name or 'Seller').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Seller verified · Merco</title></head>'
        '<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#050a08;color:#e0f2f1;font-family:Arial,sans-serif">'
        '<main style="max-width:520px;margin:24px;padding:32px;border:1px solid rgba(0,255,136,.28);border-radius:22px;background:#0a1912;text-align:center">'
        '<div style="font-size:54px;color:#00ff88">✓</div>'
        f'<h1 style="margin:10px 0">Seller verified</h1><p style="color:#a8c0ba;line-height:1.6">Welcome, {safe_name}. Your Merco seller account is now active and your store has been created successfully.</p>'
        '<a href="/login" style="display:inline-block;margin-top:12px;padding:13px 20px;border-radius:12px;background:#00ff88;color:#04100a;text-decoration:none;font-weight:700">Log in to your store</a>'
        '</main></body></html>'
    )


def _verify_seller_whatsapp_fixed(token):
    try:
        data = _load_token(token)
        if data.get('purpose') != 'seller-whatsapp':
            raise BadSignature()
        user_id = int(data['id'])
        token_whatsapp = _normalize_phone(str(data.get('whatsapp') or ''))
        if not token_whatsapp:
            raise BadSignature()
        user = app_module.User.query.filter_by(id=user_id).first()
        if not user:
            raise BadSignature()
        stored_whatsapp = _normalize_phone(user.pending_seller_whatsapp or '')
        if user.role == 'seller' and user.seller_verified:
            return _seller_verification_success_html(user.username or 'Seller')
        if user.role != 'buyer' or user.seller_verification_status != 'pending' or not stored_whatsapp or stored_whatsapp != token_whatsapp:
            flash('This seller verification link is no longer valid. Start Seller Mode again to get a new link.')
            return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))

        seller_name = (user.pending_seller_name or user.username or 'Merco Seller').strip()[:100]
        slug = app_module.unique_seller_slug(seller_name, user.id)
        user.role = 'seller'
        user.username = seller_name
        user.seller_slug = slug
        user.whatsapp_number = user.pending_seller_whatsapp
        user.seller_verified = True
        user.seller_verification_status = 'verified'
        user.pending_seller_name = None
        user.pending_seller_email = None
        user.pending_seller_phone = None
        user.pending_seller_whatsapp = None
        app_module.db.session.commit()
        app.logger.info('Seller verification completed for user_id=%s', user.id)
        return _seller_verification_success_html(seller_name)
    except SignatureExpired:
        app_module.db.session.rollback()
        flash('That seller verification link has expired. Start Seller Mode again to get a new 5-minute link.')
        return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))
    except (BadSignature, ValueError, TypeError, KeyError):
        app_module.db.session.rollback()
        flash('That seller verification link is invalid. Start Seller Mode again to get a new link.')
        return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Seller verification failed')
        flash('Seller verification could not be completed. Please try again with a newly generated link.')
        return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))


def _seller_verification_success():
    return _seller_verification_success_html('Seller'), 200

try:
    app.add_url_rule('/seller-verification-success', endpoint='seller_verification_success', view_func=_seller_verification_success)
except AssertionError:
    pass

merco_runtime._activate_seller = _activate_seller_fixed
app.view_functions['verify_seller_whatsapp'] = _verify_seller_whatsapp_fixed
app.view_functions['activate_seller_production'] = _activate_seller_fixed
