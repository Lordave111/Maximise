"""Production wrapper for Merco.

Loads the hardened application and provides defensive production overrides for
Seller Mode and Settings so failures never turn the page into a blank/500
response.
"""

import os
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

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
        if not seller_name:
            raise ValueError('Enter a seller or store name.')
        if not public_email or '@' not in public_email:
            raise ValueError('Enter a valid public email.')
        if not phone:
            raise ValueError('Add a phone number so buyers can call you.')
        if not whatsapp:
            raise ValueError('Add a WhatsApp number so buyers can contact you.')
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
    """Stable Settings view with the seller contact object always available."""
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
    if request.path != '/settings' or request.method != 'POST':
        return None
    if request.form.get('action') != 'become_seller':
        return None
    return _activate_seller()


# Load email-only lifecycle features after the marketplace feature modules.
import email_notifications  # noqa: E402,F401


def _ensure_demo_listings_live():
    """Repair demo listings so seeded products also have active placements.

    Demo products are database rows, but the marketplace's live-listing layer
    uses ListingPlacement records. Earlier demo seeding created the products
    without placements, which made seller dashboards report zero live items.
    This startup repair is idempotent and also refreshes expired demo placements.
    """
    now = datetime.utcnow()
    horizon = now + timedelta(days=365)
    try:
        with app.app_context():
            demo_sellers = app_module.User.query.filter(
                app_module.User.role == 'seller',
                app_module.User.seller_slug.like('merco-demo-store-%'),
            ).all()
            repaired = 0
            for seller in demo_sellers:
                products = app_module.Product.query.filter_by(seller_id=seller.id).all()
                for product in products:
                    product.is_sold_out = False
                    placement = bootstrap.ListingPlacement.query.filter_by(product_id=product.id).first()
                    if not placement:
                        placement = bootstrap.ListingPlacement(
                            product_id=product.id,
                            seller_id=seller.id,
                            duration_hours=24,
                            fee_percent=0,
                            amount_kobo=0,
                            is_free=True,
                            starts_at=now,
                            expires_at=horizon,
                        )
                        app_module.db.session.add(placement)
                        repaired += 1
                    elif placement.expires_at <= now or placement.seller_id != seller.id:
                        placement.seller_id = seller.id
                        placement.duration_hours = 24
                        placement.fee_percent = 0
                        placement.amount_kobo = 0
                        placement.is_free = True
                        placement.starts_at = now
                        placement.expires_at = horizon
                        repaired += 1
            if repaired:
                app_module.db.session.commit()
                app.logger.info('Demo listing repair complete; activated %s listings.', repaired)
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Demo listing repair failed; application startup will continue.')


def _repair_demo_market_on_request():
    """Last-mile guard for the public market page.

    Render can keep an existing service environment even when a Blueprint
    environment change has not been synchronized. If the public market ever
    reaches a state with no live demo products, repair/seed the demo catalog
    during the request instead of showing a misleading ``0 live items`` page.
    This only runs when MERCO_SEED_DEMO_DATA is explicitly enabled.
    """
    if request.path != '/market':
        return None
    if os.environ.get('MERCO_SEED_DEMO_DATA', '').strip() != '1':
        return None
    try:
        live_demo_count = app_module.db.session.query(app_module.Product.id).join(
            app_module.User, app_module.Product.seller_id == app_module.User.id
        ).filter(
            app_module.User.seller_slug.like('merco-demo-store-%'),
            app_module.User.role == 'seller',
            app_module.Product.is_sold_out.is_(False),
        ).count()
        if live_demo_count:
            return None

        import demo_seed
        demo_seed.seed_demo_data()
        _ensure_demo_listings_live()
        app.logger.info('Public market guard repaired the demo catalog.')
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Public market demo repair failed.')
    return None


app.before_request(_repair_demo_market_on_request)


# Seed the public demo marketplace once per deploy/process start when enabled.
if os.environ.get('MERCO_SEED_DEMO_DATA', '').strip() == '1':
    try:
        import demo_seed
        created = demo_seed.seed_demo_data()
        app.logger.info('Demo marketplace seed complete; created %s sellers.', created)
        _ensure_demo_listings_live()
    except Exception:
        app.logger.exception('Demo marketplace seed failed; application startup will continue.')

application = app
