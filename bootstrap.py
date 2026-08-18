import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text

from app import app, db, Product, Category, save_image

PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '').strip()
PAYSTACK_BASE = 'https://api.paystack.co'

# Add the marketplace fields without replacing the existing database.
def add_column_if_missing(table, column, definition):
    inspector = inspect(db.engine)
    if table not in inspector.get_table_names():
        return
    columns = {item['name'] for item in inspector.get_columns(table)}
    if column not in columns:
        quoted_table = db.engine.dialect.identifier_preparer.quote(table)
        with db.engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE {quoted_table} ADD COLUMN {column} {definition}'))


# Dynamically extend the existing mapped models so old databases can migrate safely.
if not hasattr(Product, 'expires_at'):
    Product.expires_at = db.Column(db.DateTime, nullable=True)

from app import User

if not hasattr(User, 'contact_email'):
    User.contact_email = db.Column(db.String(160), nullable=True)
if not hasattr(User, 'phone_number'):
    User.phone_number = db.Column(db.String(40), nullable=True)
if not hasattr(User, 'free_listing_used'):
    User.free_listing_used = db.Column(db.Boolean, default=False, nullable=False)


class ListingPayment(db.Model):
    __tablename__ = 'listing_payment'

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(80), unique=True, nullable=False, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    cover_image = db.Column(db.String(300), nullable=False)
    screenshots = db.Column(db.Text)
    duration_hours = db.Column(db.Integer, nullable=False)
    fee_percent = db.Column(db.Float, nullable=False)
    amount_kobo = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='pending', nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    paid_at = db.Column(db.DateTime, nullable=True)

    seller = db.relationship('User', foreign_keys=[seller_id])


with app.app_context():
    add_column_if_missing('user', 'contact_email', 'VARCHAR(160)')
    add_column_if_missing('user', 'phone_number', 'VARCHAR(40)')
    add_column_if_missing('user', 'free_listing_used', 'BOOLEAN DEFAULT FALSE')
    add_column_if_missing('product', 'expires_at', 'DATETIME')
    db.create_all()
    # Sellers who already have listings have already consumed their first free listing.
    for seller in User.query.filter_by(role='seller').all():
        if not seller.free_listing_used and Product.query.filter_by(seller_id=seller.id).first():
            seller.free_listing_used = True
    db.session.commit()


def expire_listings():
    now = datetime.utcnow()
    expired = Product.query.filter(
        Product.expires_at.isnot(None),
        Product.expires_at <= now,
        Product.is_sold_out.is_(False),
    ).all()
    if expired:
        for product in expired:
            product.is_sold_out = True
        db.session.commit()


def listing_fee(price, hours):
    rate = Decimal('0.10') if hours == 12 else Decimal('0.28')
    amount = (Decimal(str(price)) * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return rate * 100, amount


def create_product_from_payment(payment):
    if payment.product_id:
        return Product.query.get(payment.product_id)
    expires_at = datetime.utcnow() + timedelta(hours=payment.duration_hours)
    product = Product(
        name=payment.name,
        price=payment.price,
        description=payment.description,
        category_id=payment.category_id,
        seller_id=payment.seller_id,
        cover_image=payment.cover_image,
        screenshots=payment.screenshots,
        expires_at=expires_at,
    )
    db.session.add(product)
    payment.status = 'paid'
    payment.paid_at = datetime.utcnow()
    db.session.flush()
    payment.product_id = product.id
    seller = User.query.get(payment.seller_id)
    if seller:
        seller.free_listing_used = True
    db.session.commit()
    return product


def verify_with_paystack(reference):
    if not PAYSTACK_SECRET_KEY:
        return None
    response = requests.get(
        f'{PAYSTACK_BASE}/transaction/verify/{reference}',
        headers={'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}'},
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get('status'):
        return None
    return payload.get('data') or {}


def initialize_paystack_payment(payment, email):
    if not PAYSTACK_SECRET_KEY:
        raise RuntimeError('PAYSTACK_SECRET_KEY is not configured on the server.')
    response = requests.post(
        f'{PAYSTACK_BASE}/transaction/initialize',
        headers={
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
            'Content-Type': 'application/json',
        },
        json={
            'email': email,
            'amount': str(payment.amount_kobo),
            'currency': 'NGN',
            'reference': payment.reference,
            'callback_url': url_for('paystack_callback', _external=True),
            'metadata': {
                'listing_payment_id': payment.id,
                'seller_id': payment.seller_id,
                'duration_hours': payment.duration_hours,
            },
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get('status') or not payload.get('data', {}).get('authorization_url'):
        raise RuntimeError(payload.get('message') or 'Paystack could not initialize the payment.')
    return payload['data']['authorization_url']


def complete_verified_payment(payment, transaction):
    if not transaction or transaction.get('status') != 'success':
        return False
    amount = int(transaction.get('amount') or 0)
    currency = (transaction.get('currency') or '').upper()
    if amount != payment.amount_kobo or currency != 'NGN':
        return False
    create_product_from_payment(payment)
    return True


@app.before_request
def marketplace_payment_layer():
    try:
        expire_listings()
    except Exception:
        db.session.rollback()
        app.logger.exception('Listing expiry check failed')

    # Keep seller contact details synchronized with the existing Settings route.
    if request.path == '/settings' and request.method == 'POST' and current_user.is_authenticated:
        current_user.contact_email = (request.form.get('contact_email') or current_user.email).strip()[:160]
        current_user.phone_number = (request.form.get('phone_number') or '').strip()[:40]
        if not current_user.contact_email:
            current_user.contact_email = current_user.email
        db.session.commit()

    # Replace only the old product-upload page with the payment-aware flow.
    if request.path == '/seller/add':
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if current_user.role != 'seller':
            flash('Become a seller from Settings before uploading products.')
            return redirect(url_for('settings'))

        categories = Category.query.order_by(Category.name.asc()).all()
        has_used_free = bool(current_user.free_listing_used)
        if not has_used_free and Product.query.filter_by(seller_id=current_user.id).first():
            has_used_free = True
            current_user.free_listing_used = True
            db.session.commit()

        if request.method == 'GET':
            return render_template(
                'add_product.html',
                categories=categories,
                first_listing_free=not has_used_free,
            )

        try:
            name = request.form.get('name', '').strip()[:200]
            price = Decimal(request.form.get('price', '0'))
            category_id = request.form.get('category', type=int)
            description = request.form.get('description', '').strip()
            whatsapp = request.form.get('whatsapp', '').strip()[:30]
            contact_email = request.form.get('contact_email', current_user.contact_email or current_user.email).strip()[:160]
            phone_number = request.form.get('phone_number', current_user.phone_number or '').strip()[:40]
            duration = int(request.form.get('duration', '24'))

            if not name or price < 0:
                raise ValueError('Enter a valid product name and price.')
            if duration not in (12, 24):
                raise ValueError('Choose either 12 hours or 24 hours.')
            if not category_id:
                raise ValueError('Choose a product category.')
            if not contact_email or '@' not in contact_email:
                raise ValueError('Add a valid buyer contact email.')
            if not phone_number:
                raise ValueError('Add a phone number so buyers can call you.')
            if not whatsapp:
                raise ValueError('Add a WhatsApp number so buyers can message you.')

            cover = save_image(request.files.get('cover_image'))
            if not cover:
                raise ValueError('Please choose a cover image.')
            screenshots = [
                saved for file in request.files.getlist('screenshots')
                if (saved := save_image(file))
            ]

            current_user.whatsapp_number = whatsapp
            current_user.contact_email = contact_email
            current_user.phone_number = phone_number

            # The first listing is always a 24-hour complimentary placement.
            if not has_used_free:
                product = Product(
                    name=name,
                    price=float(price),
                    description=description,
                    category_id=category_id,
                    seller_id=current_user.id,
                    cover_image=cover,
                    screenshots=','.join(screenshots),
                    expires_at=datetime.utcnow() + timedelta(hours=24),
                )
                db.session.add(product)
                current_user.free_listing_used = True
                db.session.commit()
                flash('Your first listing is live — complimentary for 24 hours.')
                return redirect(url_for('seller_dashboard'))

            fee_percent, fee_amount = listing_fee(price, duration)
            amount_kobo = int((fee_amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
            if amount_kobo <= 0:
                raise ValueError('This listing fee is too small to process. Increase the product price.')
            if amount_kobo > 10_000_000 * 100:
                raise ValueError('The listing fee is above the payment provider limit.')

            payment = ListingPayment(
                reference=f'MAX-LIST-{uuid.uuid4().hex}',
                seller_id=current_user.id,
                name=name,
                price=float(price),
                description=description,
                category_id=category_id,
                cover_image=cover,
                screenshots=','.join(screenshots),
                duration_hours=duration,
                fee_percent=float(fee_percent),
                amount_kobo=amount_kobo,
                status='pending',
            )
            db.session.add(payment)
            db.session.commit()
            try:
                checkout_url = initialize_paystack_payment(payment, contact_email)
            except Exception:
                db.session.delete(payment)
                db.session.commit()
                app.logger.exception('Paystack initialization failed')
                raise ValueError('Payment could not be started. Check the payment configuration and try again.')
            return redirect(checkout_url)
        except (InvalidOperation, ValueError) as exc:
            db.session.rollback()
            flash(str(exc))
            return render_template('add_product.html', categories=categories, first_listing_free=not has_used_free)
        except Exception:
            db.session.rollback()
            app.logger.exception('Payment-aware product upload failed')
            flash('The listing could not be prepared. Please try again.')
            return render_template('add_product.html', categories=categories, first_listing_free=not has_used_free)


@app.get('/payments/paystack/callback')
@login_required
def paystack_callback():
    reference = request.args.get('reference', '').strip()
    payment = ListingPayment.query.filter_by(reference=reference, seller_id=current_user.id).first()
    if not payment:
        flash('We could not find that listing payment.')
        return redirect(url_for('seller_dashboard'))
    if payment.status == 'paid' and payment.product_id:
        flash('Payment confirmed. Your listing is live.')
        return redirect(url_for('seller_dashboard'))
    try:
        transaction = verify_with_paystack(reference)
        if complete_verified_payment(payment, transaction):
            flash('Payment confirmed. Your listing is now live.')
        else:
            payment.status = 'failed'
            db.session.commit()
            flash('Payment was not confirmed, so the listing was not published.')
    except Exception:
        app.logger.exception('Paystack callback verification failed')
        flash('We could not verify the payment yet. If you were charged, please contact support.')
    return redirect(url_for('seller_dashboard'))


@app.post('/payments/paystack/webhook')
def paystack_webhook():
    if not PAYSTACK_SECRET_KEY:
        return jsonify({'ok': False}), 503
    signature = request.headers.get('x-paystack-signature', '')
    raw = request.get_data()
    expected = hmac.new(PAYSTACK_SECRET_KEY.encode(), raw, hashlib.sha512).hexdigest()
    if not signature or not hmac.compare_digest(signature, expected):
        return jsonify({'ok': False}), 401

    event = request.get_json(silent=True) or {}
    if event.get('event') != 'charge.success':
        return jsonify({'ok': True}), 200

    data = event.get('data') or {}
    reference = data.get('reference')
    payment = ListingPayment.query.filter_by(reference=reference).first()
    if not payment:
        return jsonify({'ok': True}), 200
    try:
        complete_verified_payment(payment, data)
    except Exception:
        db.session.rollback()
        app.logger.exception('Paystack webhook fulfillment failed')
        return jsonify({'ok': False}), 500
    return jsonify({'ok': True}), 200


@app.get('/seller/payments')
@login_required
def seller_payments():
    if current_user.role != 'seller':
        return redirect(url_for('settings'))
    payments = ListingPayment.query.filter_by(seller_id=current_user.id).order_by(ListingPayment.id.desc()).all()
    return render_template('seller_payments.html', payments=payments)


# Render should import this WSGI module so the payment layer is loaded.
application = app
