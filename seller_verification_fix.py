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
    return _seller_serializer().dumps({'id': int(user.id), 'whatsapp': whatsapp, 'purpose': 'seller-whatsapp'})


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
        message = ('Hello Merco Customer Care, I want to open a seller store.\n\n'
                   f'Name: {seller_name}\nWhatsApp: {whatsapp}\n\n'
                   'My secure seller verification link is below. I will open it within 5 minutes to activate Seller Mode automatically.\n\n'
                   f'Verification link: {verification_link}')
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
    safe_name = (name or 'Seller').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Seller Verified · Merco</title>
<style>
:root{{--bg:#050a08;--panel:#0b1712;--panel2:#0f2018;--green:#00ff88;--text:#e7f5ef;--muted:#91aaa0;--line:rgba(0,255,136,.16)}}
*{{box-sizing:border-box}} body{{margin:0;min-height:100vh;background:radial-gradient(circle at 50% 0%,rgba(0,255,136,.12),transparent 36%),var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;display:grid;place-items:center;padding:24px;overflow-x:hidden}}
body:before{{content:"";position:fixed;inset:0;pointer-events:none;background-image:linear-gradient(rgba(255,255,255,.018) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.018) 1px,transparent 1px);background-size:36px 36px;mask-image:linear-gradient(to bottom,#000,transparent 80%)}}
.shell{{width:min(100%,560px);position:relative}} .brand{{display:flex;align-items:center;justify-content:center;gap:10px;margin-bottom:18px;font-weight:800;letter-spacing:.08em;font-size:18px}} .brand-mark{{width:38px;height:38px;border:1px solid rgba(0,255,136,.5);border-radius:12px;display:grid;place-items:center;color:var(--green);font-size:20px;font-weight:900;box-shadow:0 0 28px rgba(0,255,136,.12)}}
.card{{position:relative;background:linear-gradient(145deg,rgba(15,32,24,.96),rgba(7,15,11,.98));border:1px solid var(--line);border-radius:28px;padding:38px 34px;box-shadow:0 28px 80px rgba(0,0,0,.45),0 0 55px rgba(0,255,136,.07);text-align:center;overflow:hidden}} .card:after{{content:"";position:absolute;top:-90px;right:-80px;width:220px;height:220px;background:rgba(0,255,136,.08);filter:blur(45px);border-radius:50%}}
.icon{{width:82px;height:82px;margin:0 auto 22px;border-radius:24px;background:rgba(0,255,136,.1);border:1px solid rgba(0,255,136,.28);display:grid;place-items:center;color:var(--green);font-size:42px;font-weight:700;box-shadow:0 0 45px rgba(0,255,136,.12)}}
.badge{{display:inline-flex;align-items:center;gap:7px;padding:7px 11px;border-radius:999px;background:rgba(0,255,136,.08);border:1px solid rgba(0,255,136,.2);color:var(--green);font-size:11px;font-weight:800;letter-spacing:.12em}} h1{{font-size:clamp(28px,7vw,42px);line-height:1.08;margin:16px 0 12px;letter-spacing:-.035em}} .lead{{color:var(--muted);line-height:1.7;font-size:15px;margin:0 auto;max-width:440px}}
.steps{{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin:28px 0;text-align:left}} .step{{padding:14px 11px;border:1px solid rgba(255,255,255,.07);border-radius:15px;background:rgba(255,255,255,.025)}} .step b{{display:block;color:var(--green);font-size:12px;margin-bottom:5px}} .step span{{color:#b5c9c1;font-size:11px;line-height:1.35}}
.cta{{display:flex;align-items:center;justify-content:center;gap:9px;width:100%;padding:15px 20px;border-radius:14px;background:var(--green);color:#031008;text-decoration:none;font-weight:850;box-shadow:0 10px 28px rgba(0,255,136,.16);transition:transform .18s,box-shadow .18s}} .cta:hover{{transform:translateY(-2px);box-shadow:0 14px 34px rgba(0,255,136,.24)}} .sub{{display:block;margin-top:14px;color:#708980;text-decoration:none;font-size:13px}} .secure{{margin-top:24px;padding-top:20px;border-top:1px solid rgba(255,255,255,.07);color:#708980;font-size:11px;line-height:1.55}} .secure strong{{color:#a9c1b8}} @media(max-width:480px){{body{{padding:14px}}.card{{padding:30px 20px;border-radius:23px}}.steps{{gap:6px}}.step{{padding:11px 8px}}}}
</style></head>
<body><div class="shell"><div class="brand"><span class="brand-mark">M</span><span>MERCO</span></div>
<main class="card"><div class="icon">✓</div><div class="badge">● SELLER VERIFIED</div><h1>Your store is live.</h1><p class="lead">Welcome, <strong>{safe_name}</strong>. Your Seller Mode has been activated successfully and your Merco storefront is ready.</p>
<div class="steps"><div class="step"><b>01 · VERIFIED</b><span>Your seller account is confirmed.</span></div><div class="step"><b>02 · ACTIVE</b><span>Your storefront is now available.</span></div><div class="step"><b>03 · READY</b><span>Log in to manage your store.</span></div></div>
<a class="cta" href="/login">Continue to Merco <span>→</span></a><a class="sub" href="/">Back to home</a><div class="secure"><strong>Secure verification</strong><br>Your signed verification link was valid for 5 minutes and could only activate the matching seller request.</div>
</main></div></body></html>'''


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
