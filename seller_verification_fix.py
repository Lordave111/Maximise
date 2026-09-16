"""Simple seller verification for Merco.

Seller Mode uses one signed verification link. No WhatsApp API, WhatsApp chat,
email delivery, or manual approval is required. The link opens a real
verification screen, validates the saved contact details, activates the seller,
and then opens the newly-created storefront.
"""
import hashlib
import html
import os
import re

from flask import flash, redirect, request, url_for
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

import merco_runtime
from sitefix import app
import app as app_module
import bootstrap

SELLER_VERIFICATION_MAX_AGE = 300
SELLER_TOKEN_SALT = "merco-seller-link-v3"
EMAIL_RE = re.compile(r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$")


def _seller_serializer():
    configured = (os.environ.get("SECRET_KEY") or "").strip()
    if configured:
        key = configured
    else:
        database_url = (os.environ.get("DATABASE_URL") or "").strip()
        seed = database_url or "merco-local-seller-verification"
        key = hashlib.sha256(("merco-seller-key-v2:" + seed).encode("utf-8")).hexdigest()
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
    return _seller_serializer().dumps({'id': int(user.id), 'purpose': 'seller-link'})


def _verification_url(user):
    base = (os.environ.get('MERCO_PUBLIC_URL') or 'https://maximise-production.up.railway.app').rstrip('/')
    return f"{base}/verify-seller/{_token(user)}"


def _verification_ready_html(name, verification_link):
    safe_name = html.escape(name or 'Seller')
    safe_link = html.escape(verification_link, quote=True)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Verify your store · Merco</title><style>
:root{{--bg:#050a08;--panel:#0b1712;--green:#00ff88;--text:#e7f5ef;--muted:#8ea79d;--line:rgba(0,255,136,.16)}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;padding:22px;background:radial-gradient(circle at 50% 0%,rgba(0,255,136,.13),transparent 38%),var(--bg);color:var(--text);font-family:Inter,system-ui,-apple-system,"Segoe UI",sans-serif;display:grid;place-items:center}}.wrap{{width:min(100%,570px)}}.brand{{text-align:center;margin-bottom:18px;font-weight:900;letter-spacing:.12em;color:var(--green)}}.card{{background:linear-gradient(145deg,rgba(14,31,23,.98),rgba(7,14,10,.99));border:1px solid var(--line);border-radius:28px;padding:34px;box-shadow:0 30px 90px rgba(0,0,0,.48)}}.top{{text-align:center}}.icon{{width:76px;height:76px;margin:0 auto 18px;border-radius:23px;display:grid;place-items:center;background:rgba(0,255,136,.1);border:1px solid rgba(0,255,136,.28);color:var(--green);font-size:38px}}.eyebrow{{font-size:11px;font-weight:900;letter-spacing:.14em;color:var(--green)}}h1{{font-size:clamp(28px,7vw,40px);line-height:1.08;margin:12px 0}}.lead{{margin:0;color:var(--muted);line-height:1.65}}.timer{{margin:24px 0 18px;padding:13px 15px;border-radius:15px;background:rgba(255,190,70,.07);border:1px solid rgba(255,190,70,.18);color:#d9c9a5;font-size:13px;text-align:center}}.linkbox{{display:flex;gap:9px;margin-top:18px}}.linkbox input{{min-width:0;flex:1;padding:14px;border-radius:13px;border:1px solid rgba(255,255,255,.1);background:#07100b;color:#cfe5dc;font-size:12px;outline:none}}button,.cta{{border:0;border-radius:13px;padding:14px 18px;background:var(--green);color:#031008;font-weight:900;cursor:pointer;text-decoration:none}}.cta{{display:block;text-align:center;margin-top:14px}}.note{{margin-top:22px;text-align:center;color:#718a81;font-size:11px;line-height:1.55}}@media(max-width:480px){{.card{{padding:25px 18px}}.linkbox{{flex-direction:column}}button{{width:100%}}}}</style></head><body><div class="wrap"><div class="brand">M · MERCO</div><main class="card"><div class="top"><div class="icon">✓</div><div class="eyebrow">SELLER MODE</div><h1>Verify &amp; create your store</h1><p class="lead">Hi <strong>{safe_name}</strong>. Your seller details are ready. Open the secure link below to verify the saved email and phone details and create your new storefront.</p></div><div class="timer">⏱ <strong>This link expires in 5 minutes.</strong></div><div class="linkbox"><input id="verification-link" value="{safe_link}" readonly><button type="button" onclick="copyLink()">Copy link</button></div><a class="cta" href="{safe_link}">Start Verification &amp; Create Store →</a><p class="note">Merco checks the saved contact details and seller request. No WhatsApp API, email delivery, or admin approval is used.</p></main></div><script>function copyLink(){{const x=document.getElementById('verification-link');x.select();navigator.clipboard?.writeText(x.value);}}</script></body></html>'''


def _verification_progress_html(name, seller_url):
    safe_name = html.escape(name or 'Seller')
    safe_url = html.escape(seller_url, quote=True)
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="2;url={safe_url}"><title>Store created · Merco</title><style>
:root{{--bg:#050a08;--green:#00ff88;--text:#e7f5ef;--muted:#91aaa0}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;padding:24px;background:radial-gradient(circle at 50% 0%,rgba(0,255,136,.13),transparent 38%),var(--bg);color:var(--text);font-family:Inter,system-ui,sans-serif;display:grid;place-items:center}}.card{{width:min(100%,560px);padding:40px 30px;text-align:center;background:linear-gradient(145deg,#0e2017,#070f0b);border:1px solid rgba(0,255,136,.18);border-radius:28px;box-shadow:0 30px 90px rgba(0,0,0,.5)}}.logo{{font-weight:900;letter-spacing:.12em;color:var(--green);margin-bottom:28px}}.icon{{width:84px;height:84px;margin:auto;border-radius:25px;display:grid;place-items:center;background:rgba(0,255,136,.1);border:1px solid rgba(0,255,136,.3);color:var(--green);font-size:45px}}.badge{{display:inline-block;margin-top:20px;padding:7px 12px;border-radius:999px;color:var(--green);background:rgba(0,255,136,.08);font-size:11px;font-weight:900;letter-spacing:.12em}}h1{{font-size:clamp(30px,8vw,42px);margin:15px 0 8px}}p{{color:var(--muted);line-height:1.7}}.bar{{height:5px;margin:25px 0;background:rgba(255,255,255,.06);border-radius:99px;overflow:hidden}}.bar i{{display:block;width:100%;height:100%;background:var(--green);animation:load 2s linear}}@keyframes load{{from{{width:0}}to{{width:100%}}}}.cta{{display:block;margin-top:20px;padding:14px;border-radius:14px;background:var(--green);color:#031008;text-decoration:none;font-weight:900}}</style></head><body><main class="card"><div class="logo">M · MERCO</div><div class="icon">✓</div><div class="badge">SELLER VERIFIED</div><h1>Store created.</h1><p>Welcome, <strong>{safe_name}</strong>. Your email and phone details have been checked and your brand-new Merco storefront is now ready.</p><div class="bar"><i></i></div><p>Opening your new store…</p><a class="cta" href="{safe_url}">Open My New Store →</a></main></body></html>'''


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
        if not seller_name:
            raise ValueError('Please enter a seller/store name.')
        if not public_email:
            raise ValueError('Please enter a valid email address, for example name@gmail.com.')
        if not phone:
            raise ValueError('Please enter a valid Nigerian phone number, for example 08012345678 or +2348012345678.')
        if not whatsapp:
            raise ValueError('Please enter a valid Nigerian WhatsApp number, for example 08012345678 or +2348012345678.')
        bootstrap.save_contact(current_user, public_email, phone, require_phone=True)
        current_user.pending_seller_name = seller_name
        current_user.pending_seller_email = public_email
        current_user.pending_seller_phone = phone
        current_user.pending_seller_whatsapp = whatsapp
        current_user.seller_verification_status = 'pending'
        current_user.seller_verified = False
        app_module.db.session.commit()
        return _verification_ready_html(seller_name, _verification_url(current_user))
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


def _verify_seller_fixed(token):
    try:
        data = _load_token(token)
        if data.get('purpose') not in ('seller-link', 'seller-whatsapp'):
            raise BadSignature()
        user_id = int(data['id'])
        user = app_module.User.query.filter_by(id=user_id).first()
        if not user:
            raise BadSignature()
        if user.role == 'seller' and user.seller_verified:
            seller_url = url_for('seller_page', seller_slug=user.seller_slug, _external=True)
            return _verification_progress_html(user.username or 'Seller', seller_url)
        if user.role != 'buyer' or user.seller_verification_status != 'pending':
            flash('This seller verification link is no longer valid. Start Seller Mode again to create a new link.')
            return redirect(url_for('settings') if current_user.is_authenticated else url_for('login'))

        seller_name = (user.pending_seller_name or user.username or 'Merco Seller').strip()[:100]
        public_email = _valid_email(user.pending_seller_email)
        phone = _normalize_phone(user.pending_seller_phone)
        whatsapp = _normalize_phone(user.pending_seller_whatsapp)
        if not public_email or not phone or not whatsapp:
            raise ValueError('The saved seller contact details are no longer valid. Please restart Seller Mode.')

        # This is the actual verification checkpoint: the signed link proves the
        # seller request is the one being completed, while these checks confirm
        # the saved email/phone values still pass Merco's validation rules.
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
        app.logger.info('Seller verification completed for user_id=%s', user.id)
        seller_url = url_for('seller_page', seller_slug=slug, _external=True)
        return _verification_progress_html(seller_name, seller_url)
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


# Keep the old URL working for links already generated, but all new links use
# the clean /verify-seller/<token> path.
app.view_functions['verify_seller_whatsapp'] = _verify_seller_fixed
app.add_url_rule('/verify-seller/<token>', endpoint='verify_seller', view_func=_verify_seller_fixed)
app.view_functions['activate_seller_production'] = _activate_seller_fixed
merco_runtime._activate_seller = _activate_seller_fixed
