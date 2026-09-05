"""Production wrapper for Merco."""

import os
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


def _ensure_demo_listings_live():
    now = datetime.utcnow()
    horizon = now + timedelta(days=3650)
    repaired = 0
    try:
        with app.app_context():
            demo_sellers = app_module.User.query.filter(
                app_module.User.role == 'seller',
                app_module.User.seller_slug.like('merco-demo-store-%'),
            ).all()
            for seller in demo_sellers:
                for product in app_module.Product.query.filter_by(seller_id=seller.id).all():
                    product.is_sold_out = False
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
        return 0


def _seed_and_repair_demo_data():
    """Create/repair demo data and return non-sensitive counts for diagnostics."""
    try:
        with app.app_context():
            # Make schema creation/migrations deterministic before seeding.
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
            app.logger.info('DEMO_SEED_STATUS %s', status)
            return status
    except Exception as exc:
        app.logger.exception('Demo account/catalog guard failed.')
        return {'sellers': 0, 'products': 0, 'live_products': 0, 'created': 0, 'repaired': 0, 'error': str(exc)}


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
        return jsonify(response), 200
    except Exception:
        app_module.db.session.rollback()
        return jsonify({'status': 'degraded', 'service': 'merco', 'database': 'unavailable'}), 503


app.view_functions['health'] = _demo_health


# Seed during startup as well as on the relevant public requests. This makes
# the production fixture independent of Render Blueprint variable syncing.
_seed_and_repair_demo_data()

application = app
