"""Production wrapper for Merco."""

import os
import time
import threading
from datetime import datetime, timedelta
from urllib.parse import quote

from flask import flash, redirect, render_template, request, url_for, jsonify
from flask_login import current_user, login_required
from sqlalchemy import text
from itsdangerous import BadSignature, SignatureExpired

from sitefix import app
import app as app_module
import bootstrap
import uploadfix  # noqa: E402,F401 - real seller upload route


def _verification_token(user):
    return app_module._serializer().dumps({'id': user.id, 'email': user.email, 'purpose': 'seller-whatsapp'})


def _verification_url(user):
    return url_for('verify_seller_whatsapp', token=_verification_token(user), _external=True)


def _activate_seller():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    if current_user.role != 'buyer':
        return redirect(url_for('dashboard'))
    try:
        seller_name = (request.form.get('seller_name') or current_user.username).strip()[:100]
        public_email = (request.form.get('contact_email') or current_user.email).strip()[:160]
        phone = (request.form.get('phone_number') or '').strip()[:40]
        whatsapp = (request.form.get('whatsapp') or '').strip()[:30]
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
        message = (
            f"Hello Merco Support, I want to open a seller store.\n\n"
            f"Name: {seller_name}\n"
            f"Merco account: {current_user.email}\n"
            f"WhatsApp: {whatsapp}\n\n"
            f"Please verify my WhatsApp/account and approve my Seller Mode.\n"
            f"Admin verification link: {verification_link}"
        )
        wa_url = f'https://wa.me/{admin_whatsapp}?text={quote(message)}'
        return redirect(wa_url)
    except ValueError as exc:
        app_module.db.session.rollback()
        flash(str(exc))
        return redirect(url_for('settings'))
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Seller verification request failed')
        flash('Seller verification could not be started. No account changes were saved. Please try again.')
        return redirect(url_for('settings'))


def _verify_seller_whatsapp(token):
    if not current_user.is_authenticated or current_user.role != 'admin':
        flash('Please sign in as a Merco admin to approve seller verification.')
        return redirect(url_for('login'))
    try:
        data = app_module._serializer().loads(token, max_age=86400)
        if data.get('purpose') != 'seller-whatsapp':
            raise BadSignature()
        user = app_module.User.query.filter_by(id=int(data['id']), email=data['email']).first_or_404()
        if user.seller_verification_status != 'pending' or not user.pending_seller_whatsapp:
            flash('This seller verification request is no longer pending.')
            return redirect(url_for('admin_dashboard'))
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
        flash(f'{user.username} has been verified and Seller Mode is now active.')
        return redirect(url_for('admin_dashboard'))
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        flash('That seller verification link is invalid or has expired.')
        return redirect(url_for('admin_dashboard'))


app.add_url_rule('/verify-seller-whatsapp/<token>', endpoint='verify_seller_whatsapp', view_func=_verify_seller_whatsapp)


def _production_settings():
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
            current_user.whatsapp_number = request.form.get('whatsapp', current_user.whatsapp_number or '').strip()[:30]
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


app.view_functions['settings'] = _production_settings


@app.route('/activate-seller', methods=['POST'], endpoint='activate_seller_production')
@login_required
def activate_seller_production():
    return _activate_seller()


app.before_request_funcs.setdefault(None, [])


def safe_seller_activation():
    if request.path == '/settings' and request.method == 'POST' and request.form.get('action') == 'become_seller':
        return _activate_seller()
    return None


app.before_request(safe_seller_activation)


import email_notifications  # noqa: E402,F401

_EMAIL_WORKER_STOP = threading.Event()
_EMAIL_WORKER_LOCK = threading.Lock()


def _process_queued_emails_background():
    if not _EMAIL_WORKER_LOCK.acquire(blocking=False):
        return
    try:
        email_notifications.process_email_queue(limit=3)
    except Exception:
        app.logger.exception('Background email queue processing failed')
    finally:
        _EMAIL_WORKER_LOCK.release()


def _email_worker_loop():
    while not _EMAIL_WORKER_STOP.wait(15):
        _process_queued_emails_background()


if not app.extensions.get('merco_email_worker_started'):
    app.extensions['merco_email_worker_started'] = True
    _EMAIL_WORKER_THREAD = threading.Thread(target=_email_worker_loop, name='merco-email-worker', daemon=True)
    _EMAIL_WORKER_THREAD.start()


_DEMO_SEED_READY = False
_DEMO_SEED_READY_AT = 0.0
_DEMO_SEED_LOCK = threading.Lock()


def _ensure_demo_listings_live():
    now = datetime.utcnow()
    horizon = now + timedelta(days=3650)
    repaired = 0
    try:
        demo_sellers = app_module.User.query.filter(
            app_module.User.role == 'seller',
            app_module.User.seller_slug.like('merco-demo-store-%'),
        ).all()
        for seller in demo_sellers:
            for product in app_module.Product.query.filter_by(seller_id=seller.id).all():
                if product.is_sold_out:
                    product.is_sold_out = False
                    repaired += 1
                placement = bootstrap.ListingPlacement.query.filter_by(product_id=product.id).first()
                if not placement:
                    placement = bootstrap.ListingPlacement(product_id=product.id, seller_id=seller.id, duration_hours=87600, fee_percent=0, amount_kobo=0, is_free=True, starts_at=now, expires_at=horizon)
                    app_module.db.session.add(placement); repaired += 1
                else:
                    changed = False
                    if placement.seller_id != seller.id: placement.seller_id = seller.id; changed = True
                    if placement.is_free is not True: placement.is_free = True; changed = True
                    if placement.fee_percent != 0: placement.fee_percent = 0; changed = True
                    if placement.amount_kobo != 0: placement.amount_kobo = 0; changed = True
                    if not placement.expires_at or placement.expires_at <= now:
                        placement.starts_at = now; placement.expires_at = horizon; placement.duration_hours = 87600; changed = True
                    if changed: repaired += 1
        if repaired: app_module.db.session.commit()
        return repaired
    except Exception:
        app.logger.exception('Permanent demo listing repair failed.')
        raise


def _seed_and_repair_demo_data():
    global _DEMO_SEED_READY, _DEMO_SEED_READY_AT
    if _DEMO_SEED_READY and time.time() - _DEMO_SEED_READY_AT < 300:
        return {'sellers': 50, 'products': 150, 'live_products': 150, 'created': 0, 'repaired': 0, 'cached': True}
    with _DEMO_SEED_LOCK:
        if _DEMO_SEED_READY and time.time() - _DEMO_SEED_READY_AT < 300:
            return {'sellers': 50, 'products': 150, 'live_products': 150, 'created': 0, 'repaired': 0, 'cached': True}
        try:
            with app.app_context():
                import demo_seed
                created = demo_seed.seed_demo_data(); repaired = _ensure_demo_listings_live()
                demo_sellers = app_module.User.query.filter(app_module.User.role == 'seller', app_module.User.seller_slug.like('merco-demo-store-%')).count()
                demo_products = app_module.Product.query.join(app_module.User, app_module.Product.seller_id == app_module.User.id).filter(app_module.User.role == 'seller', app_module.User.seller_slug.like('merco-demo-store-%')).count()
                live_products = app_module.Product.query.join(app_module.User, app_module.Product.seller_id == app_module.User.id).filter(app_module.User.role == 'seller', app_module.User.seller_slug.like('merco-demo-store-%'), app_module.Product.is_sold_out.is_(False)).count()
                status = {'sellers': demo_sellers, 'products': demo_products, 'live_products': live_products, 'created': created, 'repaired': repaired}
                _DEMO_SEED_READY = demo_sellers >= 50 and demo_products >= 150; _DEMO_SEED_READY_AT = time.time() if _DEMO_SEED_READY else 0.0
                app.logger.info('DEMO_SEED_STATUS %s', status); return status
        except Exception as exc:
            app.logger.exception('Demo account/catalog guard failed.')
            try: app_module.db.session.rollback()
            except Exception: pass
            return {'sellers': 0, 'products': 0, 'live_products': 0, 'created': 0, 'repaired': 0, 'error': str(exc)}


@app.post('/tasks/seed-demo')
def seed_demo_task():
    expected = app_module.os.environ.get('CRON_SECRET', '').strip(); supplied = request.headers.get('X-Cron-Secret', '') or request.args.get('secret', '')
    if not expected or supplied != expected: return jsonify({'ok': False}), 401
    return jsonify(_seed_and_repair_demo_data()), 200


def _demo_health():
    try:
        app_module.db.session.execute(text('SELECT 1')); return jsonify({'status': 'ok', 'service': 'merco', 'database': 'ok'}), 200
    except Exception:
        try: app_module.db.session.rollback()
        except Exception: pass
        return jsonify({'status': 'degraded', 'service': 'merco', 'database': 'unavailable'}), 503


app.view_functions['health'] = _demo_health
import marketfix  # noqa: E402,F401
import email_overrides  # noqa: E402,F401
application = app
