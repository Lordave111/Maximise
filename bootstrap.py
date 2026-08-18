import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import requests
from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text

from app import app, db, Product, Category, User, save_image

PAYSTACK_SECRET_KEY = os.environ.get('PAYSTACK_SECRET_KEY', '').strip()
PAYSTACK_BASE = 'https://api.paystack.co'


def add_column_if_missing(table, column, definition):
    inspector = inspect(db.engine)
    if table not in inspector.get_table_names():
        return
    columns = {item['name'] for item in inspector.get_columns(table)}
    if column not in columns:
        quoted_table = db.engine.dialect.identifier_preparer.quote(table)
        with db.engine.begin() as conn:
            conn.execute(text(f'ALTER TABLE {quoted_table} ADD COLUMN {column} {definition}'))


class SellerContact(db.Model):
    __tablename__ = 'seller_contact'
    id = db.Column(db.Integer, primary_key=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True, nullable=False)
    public_email = db.Column(db.String(160), nullable=False)
    phone_number = db.Column(db.String(40), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())
    seller = db.relationship('User', backref=db.backref('seller_contact', uselist=False))


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


class ListingPlacement(db.Model):
    __tablename__ = 'listing_placement'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), unique=True, nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    payment_id = db.Column(db.Integer, db.ForeignKey('listing_payment.id'), nullable=True)
    duration_hours = db.Column(db.Integer, nullable=False)
    fee_percent = db.Column(db.Float, default=0, nullable=False)
    amount_kobo = db.Column(db.Integer, default=0, nullable=False)
    is_free = db.Column(db.Boolean, default=False, nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    product = db.relationship('Product', backref=db.backref('listing_placement', uselist=False))


with app.app_context():
    add_column_if_missing('user', 'contact_email', 'VARCHAR(160)')
    add_column_if_missing('user', 'phone_number', 'VARCHAR(40)')
    add_column_if_missing('user', 'free_listing_used', 'BOOLEAN DEFAULT FALSE')
    db.create_all()
    # Existing sellers with products have already used the first complimentary slot.
    if 'free_listing_used' in {c['name'] for c in inspect(db.engine).get_columns('user')}:
        for seller in User.query.filter_by(role='seller').all():
            if not getattr(seller, 'free_listing_used', False) and Product.query.filter_by(seller_id=seller.id).first():
                seller.free_listing_used = True
        db.session.commit()


def get_contact(user):
    contact = SellerContact.query.filter_by(seller_id=user.id).first()
    if contact:
        return contact
    email = getattr(user, 'contact_email', None) or user.email
    phone = getattr(user, 'phone_number', None) or ''
    return SellerContact(public_email=email, phone_number=phone, seller_id=user.id)


def save_contact(user, email, phone):
    email = (email or user.email).strip()[:160]
    phone = (phone or '').strip()[:40]
    if not email or '@' not in email:
        raise ValueError('Add a valid public email.')
    if not phone:
        raise ValueError('Add a phone number so buyers can call you.')
    contact = SellerContact.query.filter_by(seller_id=user.id).first()
    if not contact:
        contact = SellerContact(seller_id=user.id, public_email=email, phone_number=phone)
        db.session.add(contact)
    else:
        contact.public_email = email
        contact.phone_number = phone
    # Keep these values available to existing account/admin code too.
    if hasattr(user, 'contact_email'):
        user.contact_email = email
    if hasattr(user, 'phone_number'):
        user.phone_number = phone
    return contact


def expire_listings():
    now = datetime.utcnow()
    placements = ListingPlacement.query.filter(
        ListingPlacement.expires_at <= now,
        ListingPlacement.product_id.isnot(None),
    ).all()
    changed = False
    for placement in placements:
        product = Product.query.get(placement.product_id)
        if product and not product.is_sold_out:
            product.is_sold_out = True
            changed = True
    if changed:
        db.session.commit()


def listing_fee(price, hours):
    rate = Decimal('0.10') if hours == 12 else Decimal('0.28')
    amount = (Decimal(str(price)) * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return float(rate * 100), amount


def create_placement(product, seller_id, duration_hours, fee_percent=0, amount_kobo=0, payment_id=None, is_free=False):
    starts = datetime.utcnow()
    placement = ListingPlacement(
        product_id=product.id,
        seller_id=seller_id,
        payment_id=payment_id,
        duration_hours=duration_hours,
        fee_percent=fee_percent,
        amount_kobo=amount_kobo,
        is_free=is_free,
        starts_at=starts,
        expires_at=starts + timedelta(hours=duration_hours),
    )
    db.session.add(placement)
    return placement


def create_product_from_payment(payment):
    if payment.product_id:
        return Product.query.get(payment.product_id)
    product = Product(
        name=payment.name,
        price=payment.price,
        description=payment.description,
        category_id=payment.category_id,
        seller_id=payment.seller_id,
        cover_image=payment.cover_image,
        screenshots=payment.screenshots,
    )
    db.session.add(product)
    db.session.flush()
    create_placement(product, payment.seller_id, payment.duration_hours, payment.fee_percent, payment.amount_kobo, payment.id, False)
    payment.product_id = product.id
    payment.status = 'paid'
    payment.paid_at = datetime.utcnow()
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
    return payload.get('data') if payload.get('status') else None


def initialize_paystack_payment(payment, email):
    if not PAYSTACK_SECRET_KEY:
        raise RuntimeError('PAYSTACK_SECRET_KEY is not configured on the server.')
    response = requests.post(
        f'{PAYSTACK_BASE}/transaction/initialize',
        headers={'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}', 'Content-Type': 'application/json'},
        json={
            'email': email,
            'amount': str(payment.amount_kobo),
            'currency': 'NGN',
            'reference': payment.reference,
            'callback_url': url_for('paystack_callback', _external=True),
            'metadata': json.dumps({
                'listing_payment_id': payment.id,
                'seller_id': payment.seller_id,
                'duration_hours': payment.duration_hours,
                'cancel_action': url_for('add_product', _external=True),
            }),
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
    if int(transaction.get('amount') or 0) != payment.amount_kobo:
        return False
    if (transaction.get('currency') or '').upper() != 'NGN':
        return False
    create_product_from_payment(payment)
    return True


def render_storefront(slug):
    seller = User.query.filter_by(seller_slug=slug, role='seller').first_or_404()
    products = Product.query.filter_by(seller_id=seller.id, is_sold_out=False).order_by(Product.created_at.desc(), Product.id.desc()).all()
    contact = get_contact(seller)
    return render_template('seller_page.html', seller=seller, products=products, contact=contact)


def render_product_page(product_id):
    product = Product.query.get_or_404(product_id)
    screenshots = [s for s in (product.screenshots or '').split(',') if s]
    contact = get_contact(product.seller)
    placement = ListingPlacement.query.filter_by(product_id=product.id).first()
    return render_template('product_detail.html', product=product, screenshots=screenshots, contact=contact, placement=placement)


@app.before_request
def marketplace_payment_layer():
    try:
        expire_listings()
    except Exception:
        db.session.rollback()
        app.logger.exception('Listing expiry check failed')

    # Use the payment-aware settings view while preserving the existing POST route logic.
    if request.path == '/settings':
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if request.method == 'GET':
            return render_template('settings.html', contact=get_contact(current_user))
        try:
            save_contact(
                current_user,
                request.form.get('contact_email', current_user.email),
                request.form.get('phone_number', ''),
            )
            db.session.commit()
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc))
            return render_template('settings.html', contact=get_contact(current_user))

    if request.path.startswith('/seller/') and request.path != '/seller/add' and request.path != '/seller/payments':
        slug = request.path.split('/seller/', 1)[1].strip('/')
        if slug:
            return render_storefront(slug)

    if request.path.startswith('/product/'):
        try:
            product_id = int(request.path.rsplit('/', 1)[-1])
            return render_product_page(product_id)
        except ValueError:
            pass

    if request.path == '/seller/add':
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if current_user.role != 'seller':
            flash('Become a seller from Settings before uploading products.')
            return redirect(url_for('settings'))
        categories = Category.query.order_by(Category.name.asc()).all()
        free_used = bool(getattr(current_user, 'free_listing_used', False))
        if not free_used and Product.query.filter_by(seller_id=current_user.id).first():
            free_used = True
            current_user.free_listing_used = True
            db.session.commit()
        contact = get_contact(current_user)
        if request.method == 'GET':
            return render_template('add_product.html', categories=categories, first_listing_free=not free_used, contact=contact)

        try:
            name = request.form.get('name', '').strip()[:200]
            price = Decimal(request.form.get('price', '0'))
            category_id = request.form.get('category', type=int)
            description = request.form.get('description', '').strip()
            whatsapp = request.form.get('whatsapp', '').strip()[:30]
            email = request.form.get('contact_email', contact.public_email).strip()[:160]
            phone = request.form.get('phone_number', contact.phone_number).strip()[:40]
            duration = int(request.form.get('duration', '24'))
            if not name or price < 0:
                raise ValueError('Enter a valid product name and price.')
            if duration not in (12, 24):
                raise ValueError('Choose either 12 hours or 24 hours.')
            if not category_id:
                raise ValueError('Choose a product category.')
            if not email or '@' not in email:
                raise ValueError('Add a valid public email.')
            if not phone:
                raise ValueError('Add a phone number so buyers can call you.')
            if not whatsapp:
                raise ValueError('Add a WhatsApp number so buyers can message you.')

            save_contact(current_user, email, phone)
            current_user.whatsapp_number = whatsapp
            cover = save_image(request.files.get('cover_image'))
            if not cover:
                raise ValueError('Please choose a cover image.')
            screenshots = [saved for file in request.files.getlist('screenshots') if (saved := save_image(file))]

            if not free_used:
                product = Product(name=name, price=float(price), description=description, category_id=category_id, seller_id=current_user.id, cover_image=cover, screenshots=','.join(screenshots))
                db.session.add(product)
                db.session.flush()
                create_placement(product, current_user.id, 24, 0, 0, None, True)
                current_user.free_listing_used = True
                db.session.commit()
                flash('Your first listing is live — complimentary for 24 hours.')
                return redirect(url_for('seller_dashboard'))

            fee_percent, fee_amount = listing_fee(price, duration)
            amount_kobo = int((fee_amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
            if amount_kobo <= 0:
                raise ValueError('This listing fee is too small to process. Increase the product price.')
            payment = ListingPayment(
                reference=f'MAX-LIST-{uuid.uuid4().hex}', seller_id=current_user.id, name=name, price=float(price), description=description,
                category_id=category_id, cover_image=cover, screenshots=','.join(screenshots), duration_hours=duration,
                fee_percent=fee_percent, amount_kobo=amount_kobo, status='pending',
            )
            db.session.add(payment)
            db.session.commit()
            try:
                checkout_url = initialize_paystack_payment(payment, email)
            except Exception:
                db.session.delete(payment)
                db.session.commit()
                app.logger.exception('Paystack initialization failed')
                raise ValueError('Payment could not be started. Check PAYSTACK_SECRET_KEY and try again.')
            return redirect(checkout_url)
        except (InvalidOperation, ValueError) as exc:
            db.session.rollback()
            flash(str(exc))
            return render_template('add_product.html', categories=categories, first_listing_free=not free_used, contact=contact)
        except Exception:
            db.session.rollback()
            app.logger.exception('Payment-aware product upload failed')
            flash('The listing could not be prepared. Please try again.')
            return render_template('add_product.html', categories=categories, first_listing_free=not free_used, contact=contact)


@app.get('/payments/paystack/callback')
@login_required
def paystack_callback():
    reference = (request.args.get('reference') or request.args.get('trxref') or '').strip()
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
    payment = ListingPayment.query.filter_by(reference=data.get('reference')).first()
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


application = app
