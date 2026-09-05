"""Production wrapper for Merco."""

import time
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for, jsonify
from flask_login import current_user, login_required
from sqlalchemy import text

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
            flash('Verify your email before opening your seller store. ' + ('A fresh verification email has been sent.' if sent else 'Please verify your email first.'))
            return redirect(url_for('settings'))
        seller_name = (request.form.get('seller_name') or current_user.username).strip()[:100]
        public_email = (request.form.get('contact_email') or current_user.email).strip()[:160]
        phone = (request.form.get('phone_number') or '').strip()[:40]
        whatsapp = (request.form.get('whatsapp') or '').strip()[:30]
        if not seller_name or not public_email or '@' not in public_email or not phone or not whatsapp:
            raise ValueError('Seller name, public email, phone and WhatsApp are required.')
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


@app.before_request
def safe_seller_activation():
    if request.path == '/settings' and request.method == 'POST' and request.form.get('action') == 'become_seller':
        return _activate_seller()
    return None


import email_notifications  # noqa: E402,F401


_DEMO_SEED_READY = False
_DEMO_SEED_READY_AT = 0.0
_DEMO_LOCK_NAME = 'merco_demo_catalog_seed_v1'


def _acquire_demo_seed_lock():
    """Serialize demo seeding across Gunicorn workers/processes."""
    dialect = app_module.db.engine.dialect.name
    if dialect == 'mysql':
        value = app_module.db.session.execute(
            text('SELECT GET_LOCK(:lock_name, 90)'),
            {'lock_name': _DEMO_LOCK_NAME},
        ).scalar()
        return value == 1, 'mysql'
    if dialect == 'postgresql':
        app_module.db.session.execute(text('SELECT pg_advisory_lock(284731)'))
        return True, 'postgresql'
    return True, 'none'


def _release_demo_seed_lock(lock_kind):
    try:
        if lock_kind == 'mysql':
            app_module.db.session.execute(
                text('SELECT RELEASE_LOCK(:lock_name)'),
                {'lock_name': _DEMO_LOCK_NAME},
            )
        elif lock_kind == 'postgresql':
            app_module.db.session.execute(text('SELECT pg_advisory_unlock(284731)'))
        app_module.db.session.commit()
    except Exception:
        app.logger.exception('Could not release demo seed lock.')
        app_module.db.session.rollback()


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
                    placement = bootstrap.ListingPlacement(
                        product_id=product.id, seller_id=seller.id, duration_hours=87600,
                        fee_percent=0, amount_kobo=0, is_free=True,
                        starts_at=now, expires_at=horizon,
                    )
                    app_module.db.session.add(placement)
                    repaired += 1
                else:
                    changed = False
                    if placement.seller_id != seller.id:
                        placement.seller_id = seller.id; changed = True
                    if placement.is_free is not True:
                        placement.is_free = True; changed = True
                    if placement.fee_percent != 0:
                        placement.fee_percent = 0; changed = True
                    if placement.amount_kobo != 0:
                        placement.amount_kobo = 0; changed = True
                    if not placement.expires_at or placement.expires_at <= now:
                        placement.starts_at = now; placement.expires_at = horizon
                        placement.duration_hours = 87600; changed = True
                    if changed:
                        repaired += 1
        if repaired:
            app_module.db.session.commit()
        return repaired
    except Exception:
        app.logger.exception('Permanent demo listing repair failed.')
        raise


def _seed_and_repair_demo_data():
    """Create/repair demo data with a DB advisory lock and cached success."""
    global _DEMO_SEED_READY, _DEMO_SEED_READY_AT

    if _DEMO_SEED_READY and time.time() - _DEMO_SEED_READY_AT < 300:
        return {'sellers': 50, 'products': 150, 'live_products': 150, 'created': 0, 'repaired': 0, 'cached': True}

    lock_kind = None
    try:
        with app.app_context():
            lock_acquired, lock_kind = _acquire_demo_seed_lock()
            if not lock_acquired:
                app_module.db.session.rollback()
                return {
                    'sellers': 0, 'products': 0, 'live_products': 0,
                    'created': 0, 'repaired': 0,
                    'error': 'Could not acquire the demo catalog database lock.',
                }
            try:
                # Run schema setup only after the lock is held, preventing two
                # workers from altering/creating the same tables concurrently.
                app_module.initialize_database()
                import demo_seed
                created = demo_seed.seed_demo_data()
                repaired = _ensure_demo_listings_live()
                demo_sellers = app_module.User.query.filter(
                    app_module.User.role == 'seller',
                    app_module.User.seller_slug.like('merco-demo-store-%'),
                ).count()
                demo_products = app_module.Product.query.join(
                    app_module.User, app_module.Product.seller_id == app_module.User.id
                ).filter(
                    app_module.User.role == 'seller',
                    app_module.User.seller_slug.like('merco-demo-store-%'),
                ).count()
                live_products = app_module.Product.query.join(
                    app_module.User, app_module.Product.seller_id == app_module.User.id
                ).filter(
                    app_module.User.role == 'seller',
                    app_module.User.seller_slug.like('merco-demo-store-%'),
                    app_module.Product.is_sold_out.is_(False),
                ).count()
                status = {
                    'sellers': demo_sellers, 'products': demo_products,
                    'live_products': live_products, 'created': created,
                    'repaired': repaired,
                }
                if demo_sellers >= 50 and demo_products >= 150 and live_products >= 150:
                    _DEMO_SEED_READY = True
                    _DEMO_SEED_READY_AT = time.time()
                app.logger.info('DEMO_SEED_STATUS %s', status)
                return status
            finally:
                _release_demo_seed_lock(lock_kind)
    except Exception as exc:
        app.logger.exception('Demo account/catalog guard failed.')
        try:
            app_module.db.session.rollback()
        except Exception:
            pass
        return {
            'sellers': 0, 'products': 0, 'live_products': 0,
            'created': 0, 'repaired': 0, 'error': str(exc),
        }


def _repair_demo_market_on_request():
    if request.path in ('/market', '/health', '/login'):
        _seed_and_repair_demo_data()
    return None


app.before_request(_repair_demo_market_on_request)


def _demo_health():
    try:
        db = app_module.db
        db.session.execute(text('SELECT 1'))
        status = _seed_and_repair_demo_data()
        response = {
            'status': 'ok' if 'error' not in status else 'degraded',
            'service': 'merco',
            'database': 'ok',
            'demo_sellers': status.get('sellers', 0),
            'demo_products': status.get('products', 0),
            'demo_live_products': status.get('live_products', 0),
            'demo_seed_error': bool(status.get('error')),
        }
        if status.get('error'):
            response['demo_seed_error_type'] = status['error'].__class__.__name__
            response['demo_seed_error_message'] = str(status['error'])[:180]
        return jsonify(response), 200
    except Exception:
        app_module.db.session.rollback()
        return jsonify({'status': 'degraded', 'service': 'merco', 'database': 'unavailable'}), 503


app.view_functions['health'] = _demo_health


# Seed once during startup; the advisory lock prevents concurrent workers from
# fighting over the same MySQL rows. Relevant requests can repair a reset DB.
_seed_and_repair_demo_data()

application = app
