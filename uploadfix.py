"""Production seller upload route.

The old listing flow lived inside a before_request hook and depended on the
legacy save_image() filesystem helper.  This module provides a real Flask
route and stores uploaded images through sitefix's persistent DB-backed media
storage, while keeping the existing Paystack/listing lifecycle.
"""

import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from werkzeug.exceptions import RequestEntityTooLarge

from app import app, db, Product, Category
import bootstrap
import sitefix

# Multiple images are uploaded in one multipart request. Keep a reasonable
# request ceiling, while sitefix._store_image still enforces 8 MB per image.
app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024


@app.errorhandler(RequestEntityTooLarge)
def upload_too_large(error):
    if request.path == '/seller/add':
        flash('The upload is too large. Keep each image under 8 MB and try again.')
        return redirect(url_for('add_product'))
    return error


def _render_form(contact, first_listing_free, categories=None):
    return render_template(
        'add_product.html',
        categories=categories or Category.query.order_by(Category.name.asc()).all(),
        first_listing_free=first_listing_free,
        contact=contact,
    )


# app.py already contains the legacy /seller/add rule with endpoint
# ``add_product``. Register this replacement under a temporary unique endpoint
# so Flask does not raise an AssertionError while importing the production
# wrapper. We then replace the endpoint's view function below, preserving all
# existing url_for('add_product') calls and templates.
@app.route('/seller/add', methods=['GET', 'POST'], endpoint='production_add_product')
@login_required
def add_product():
    if current_user.role != 'seller':
        flash('Become a seller from Settings before uploading products.')
        return redirect(url_for('settings'))

    categories = Category.query.order_by(Category.name.asc()).all()
    contact = bootstrap.get_contact(current_user)
    free_used = bool(contact.free_listing_used) or bool(
        Product.query.filter_by(seller_id=current_user.id).first()
    )

    if request.method == 'GET':
        return _render_form(contact, not free_used, categories)

    stored_keys = []
    try:
        name = (request.form.get('name') or '').strip()[:200]
        price = Decimal(request.form.get('price', '0'))
        category_id = request.form.get('category', type=int)
        description = (request.form.get('description') or '').strip()
        whatsapp = (request.form.get('whatsapp') or '').strip()[:30]
        email = (request.form.get('contact_email') or contact.public_email or '').strip()[:160]
        phone = (request.form.get('phone_number') or contact.phone_number or '').strip()[:40]
        duration = int(request.form.get('duration', '12'))

        if not name or price < 0:
            raise ValueError('Enter a valid product name and price.')
        if duration not in (12, 24):
            raise ValueError('Choose either 12 hours or 24 hours.')
        if not category_id or not Category.query.get(category_id):
            raise ValueError('Choose a valid product category.')
        if not email or '@' not in email:
            raise ValueError('Add a valid public email.')
        if not phone:
            raise ValueError('Add a phone number so buyers can call you.')
        if not whatsapp:
            raise ValueError('Add a WhatsApp number so buyers can message you.')

        cover_file = request.files.get('cover_image')
        screenshot_files = [f for f in request.files.getlist('screenshots') if f and f.filename]
        if not cover_file or not cover_file.filename:
            raise ValueError('Please choose a cover image.')
        if not screenshot_files:
            raise ValueError('Please add at least one additional product image.')

        # Persist contact information in the same transaction as the listing.
        contact = bootstrap.save_contact(current_user, email, phone, require_phone=True)
        current_user.whatsapp_number = whatsapp

        # sitefix converts and stores images in uploaded_asset, so Railway/Render
        # restarts do not lose seller media.
        cover = sitefix._store_image(cover_file)
        if not cover:
            raise ValueError('The cover image could not be processed.')
        stored_keys.append(cover)

        screenshots = []
        for image_file in screenshot_files:
            key = sitefix._store_image(image_file)
            if not key:
                raise ValueError('One of the additional images could not be processed.')
            stored_keys.append(key)
            screenshots.append(key)

        screenshot_text = ','.join(screenshots)

        if not free_used:
            product = Product(
                name=name,
                price=float(price),
                description=description,
                category_id=category_id,
                seller_id=current_user.id,
                cover_image=cover,
                screenshots=screenshot_text,
            )
            db.session.add(product)
            db.session.flush()

            free_payment = bootstrap.ListingPayment(
                reference=f'FREE-LIST-{uuid.uuid4().hex}',
                seller_id=current_user.id,
                product_id=product.id,
                name=name,
                price=float(price),
                description=description,
                category_id=category_id,
                cover_image=cover,
                screenshots=screenshot_text,
                duration_hours=24,
                fee_percent=0,
                amount_kobo=0,
                status='free',
                paid_at=bootstrap.datetime.utcnow(),
            )
            db.session.add(free_payment)
            db.session.flush()
            bootstrap.create_placement(product, current_user.id, 24, 0, 0, free_payment.id, True)
            contact.free_listing_used = True
            db.session.commit()
            flash('Your first listing is live — complimentary for 24 hours.')
            return redirect(url_for('seller_dashboard'))

        fee_percent, fee_amount = bootstrap.listing_fee(price, duration)
        amount_kobo = int((fee_amount * 100).to_integral_value(rounding=ROUND_HALF_UP))
        if amount_kobo <= 0:
            raise ValueError('This listing fee is too small to process. Increase the product price.')

        payment = bootstrap.ListingPayment(
            reference=f'MAX-LIST-{uuid.uuid4().hex}',
            seller_id=current_user.id,
            name=name,
            price=float(price),
            description=description,
            category_id=category_id,
            cover_image=cover,
            screenshots=screenshot_text,
            duration_hours=duration,
            fee_percent=fee_percent,
            amount_kobo=amount_kobo,
            status='pending',
        )
        db.session.add(payment)
        db.session.commit()

        try:
            checkout_url = bootstrap.initialize_paystack_payment(payment, email)
        except Exception:
            db.session.delete(payment)
            db.session.commit()
            app.logger.exception('Paystack initialization failed for seller upload')
            raise ValueError('Payment could not be started. Check PAYSTACK_SECRET_KEY and try again.')

        return redirect(checkout_url)

    except (InvalidOperation, ValueError) as exc:
        db.session.rollback()
        app.logger.warning('Seller upload rejected: %s', exc)
        flash(str(exc))
        return _render_form(contact, not free_used, categories)
    except Exception:
        db.session.rollback()
        app.logger.exception('Seller product upload failed')
        flash('The product could not be uploaded. Please check the images and try again.')
        return _render_form(contact, not free_used, categories)


# Replace the legacy endpoint's dispatch target without trying to register the
# same endpoint twice. The URL rule already exists in app.py, and Flask keeps
# url_for('add_product') working while dispatching that rule to this production
# implementation.
app.view_functions['add_product'] = add_product
