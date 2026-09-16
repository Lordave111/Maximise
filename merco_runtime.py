"""Production wrapper for Merco."""

import os
import time
import threading
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, jsonify, url_for
from flask_login import current_user, login_required
from sqlalchemy import text

from sitefix import app
import app as app_module
import bootstrap
import uploadfix  # noqa: E402,F401

# Harden browser/session defaults for the production HTTPS deployment.
app.config.setdefault('SESSION_COOKIE_HTTPONLY', True)
app.config.setdefault('SESSION_COOKIE_SAMESITE', 'Lax')
app.config['SESSION_COOKIE_SECURE'] = True

@app.after_request
def _security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('Cache-Control', 'no-cache')
    return response


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
            # Seller Mode is instant. No WhatsApp redirect, verification token,
            # OTP, admin approval, or external verification is involved.
            if current_user.role == 'seller':
                if not current_user.seller_slug:
                    current_user.seller_slug = app_module.unique_seller_slug(current_user.username, current_user.id)
                current_user.seller_verified = True
                current_user.seller_verification_status = 'none'
                app_module.db.session.commit()
                return redirect(url_for('seller_open', seller_slug=current_user.seller_slug))

            seller_name = (request.form.get('seller_name') or current_user.username).strip()[:100]
            whatsapp = request.form.get('whatsapp', '').strip()[:30]
            public_email = (request.form.get('contact_email') or current_user.email).strip()[:160]
            phone = request.form.get('phone_number', '').strip()[:40]
            if not seller_name:
                flash('Enter a store name.')
                return redirect(url_for('settings'))
            if not whatsapp:
                flash('Add a WhatsApp number so buyers can contact you.')
                return redirect(url_for('settings'))
            if not public_email or '@' not in public_email:
                flash('Enter a valid contact email.')
                return redirect(url_for('settings'))
            try:
                bootstrap.save_contact(current_user, public_email, phone, require_phone=False)
                current_user.username = seller_name
                current_user.role = 'seller'
                current_user.seller_slug = app_module.unique_seller_slug(seller_name, current_user.id)
                current_user.whatsapp_number = whatsapp
                current_user.seller_verified = True
                current_user.seller_verification_status = 'none'
                current_user.pending_seller_name = None
                current_user.pending_seller_email = None
                current_user.pending_seller_phone = None
                current_user.pending_seller_whatsapp = None
                app_module.db.session.commit()
                return redirect(url_for('seller_open', seller_slug=current_user.seller_slug))
            except Exception as exc:
                app_module.db.session.rollback()
                app.logger.exception('Instant Seller Mode activation failed')
                flash(f'Could not create your store: {exc}')
                return redirect(url_for('settings'))

        flash('Nothing to update.')
        return redirect(url_for('settings'))

    try:
        contact = bootstrap.get_contact(current_user)
    except Exception:
        app.logger.exception('Could not load seller contact for settings')
        contact = None
    return render_template('settings.html', contact=contact)


# Keep the production settings handler while preserving the rest of the app.
app.view_functions['settings'] = _production_settings


@app.route('/activate-seller', methods=['POST'], endpoint='activate_seller_production')
@login_required
def activate_seller_production():
    return _production_settings()


# Legacy seller verification routes are intentionally not registered here.
# WhatsApp is a storefront contact method only, never a seller-creation step.


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
                    app_module.db.session.add(placement)
                    repaired += 1
                else:
                    changed = False
                    if placement.seller_id != seller.id: placement.seller_id = seller.id; changed = True
                    if placement.is_free is not True: placement.is_free = True; changed = True
                    if placement.fee_percent != 0: placement.fee_percent = 0; changed = True
                    if placement.amount_kobo != 0: placement.amount_kobo = 0; changed = True
                    if not placement.expires_at or placement.expires_at <= now:
                        placement.starts_at = now; placement.expires_at = horizon; placement.duration_hours = 87600; changed = True
                    if changed: repaired += 1
        if repaired:
            app_module.db.session.commit()
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
                created = demo_seed.seed_demo_data()
                repaired = _ensure_demo_listings_live()
                demo_sellers = app_module.User.query.filter(app_module.User.role == 'seller', app_module.User.seller_slug.like('merco-demo-store-%')).count()
                demo_products = app_module.Product.query.join(app_module.User, app_module.Product.seller_id == app_module.User.id).filter(app_module.User.role == 'seller', app_module.User.seller_slug.like('merco-demo-store-%')).count()
                live_products = app_module.Product.query.join(app_module.User, app_module.Product.seller_id == app_module.User.id).filter(app_module.User.role == 'seller', app_module.User.seller_slug.like('merco-demo-store-%'), app_module.Product.is_sold_out.is_(False)).count()
                status = {'sellers': demo_sellers, 'products': demo_products, 'live_products': live_products, 'created': created, 'repaired': repaired}
                _DEMO_SEED_READY = demo_sellers >= 50 and demo_products >= 150
                _DEMO_SEED_READY_AT = time.time() if _DEMO_SEED_READY else 0.0
                app.logger.info('DEMO_SEED_STATUS %s', status)
                return status
        except Exception as exc:
            app.logger.exception('Demo account/catalog guard failed.')
            try: app_module.db.session.rollback()
            except Exception: pass
            return {'sellers': 0, 'products': 0, 'live_products': 0, 'created': 0, 'repaired': 0, 'error': str(exc)}


@app.post('/tasks/seed-demo')
def seed_demo_task():
    expected = app_module.os.environ.get('CRON_SECRET', '').strip()
    supplied = request.headers.get('X-Cron-Secret', '') or request.args.get('secret', '')
    if not expected or supplied != expected:
        return jsonify({'ok': False}), 401
    return jsonify(_seed_and_repair_demo_data()), 200


def _demo_health():
    try:
        app_module.db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'ok', 'service': 'merco', 'database': 'ok'}), 200
    except Exception:
        try: app_module.db.session.rollback()
        except Exception: pass
        return jsonify({'status': 'degraded', 'service': 'merco', 'database': 'unavailable'}), 503


app.view_functions['health'] = _demo_health
import marketfix  # noqa: E402,F401
import email_overrides  # noqa: E402,F401
application = app
