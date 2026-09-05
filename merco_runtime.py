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
    """Make every seeded demo product permanently live.

    Demo inventory is fixture data, not paid inventory. It must never expire or
    become sold out, and it must have a ListingPlacement so every marketplace
    layer sees it as published.
    """
    if os.environ.get('MERCO_SEED_DEMO_DATA', '').strip() != '1':
        return 0
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
                products = app_module.Product.query.filter_by(seller_id=seller.id).all()
                for product in products:
                    if product.is_sold_out:
                        product.is_sold_out = False
                        repaired += 1
                    placement = bootstrap.ListingPlacement.query.filter_by(product_id=product.id).first()
                    if not placement:
                        placement = bootstrap.ListingPlacement(
                            product_id=product.id,
                            seller_id=seller.id,
                            duration_hours=87600,
                            fee_percent=0,
                            amount_kobo=0,
                            is_free=True,
                            starts_at=now,
                            expires_at=horizon,
                        )
                        app_module.db.session.add(placement)
                        repaired += 1
                    else:
                        changed = False
                        if placement.seller_id != seller.id:
                            placement.seller_id = seller.id
                            changed = True
                        if placement.is_free is not True:
                            placement.is_free = True
                            changed = True
                        if placement.fee_percent != 0:
                            placement.fee_percent = 0
                            changed = True
                        if placement.amount_kobo != 0:
                            placement.amount_kobo = 0
                            changed = True
                        if not placement.expires_at or placement.expires_at <= now:
                            placement.starts_at = now
                            placement.expires_at = horizon
                            placement.duration_hours = 87600
                            changed = True
                        if changed:
                            repaired += 1
            if repaired:
                app_module.db.session.commit()
            return repaired
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Permanent demo listing repair failed.')
        return 0


def _repair_demo_market_on_request():
    """Guarantee demo inventory exists before the public market is rendered."""
    if request.path not in ('/market', '/health'):
        return None
    if os.environ.get('MERCO_SEED_DEMO_DATA', '').strip() != '1':
        return None
    try:
        import demo_seed
        demo_seed.seed_demo_data()
        repaired = _ensure_demo_listings_live()
        if repaired:
            app.logger.info('Permanent demo catalog repair changed %s records.', repaired)
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception('Permanent demo catalog repair failed.')
    return None


# Register this AFTER the production modules so it is the final guard before
# /market or Render's /health request reaches its view function.
app.before_request(_repair_demo_market_on_request)


# Seed immediately at process startup as well.
if os.environ.get('MERCO_SEED_DEMO_DATA', '').strip() == '1':
    try:
        import demo_seed
        created = demo_seed.seed_demo_data()
        app.logger.info('Demo marketplace seed complete; created %s sellers.', created)
        repaired = _ensure_demo_listings_live()
        app.logger.info('Permanent demo marketplace repair complete; changed %s records.', repaired)
    except Exception:
        app.logger.exception('Demo marketplace seed/repair failed; application startup will continue.')

application = app
