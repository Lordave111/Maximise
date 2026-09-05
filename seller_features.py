"""Seller lifecycle features: listing expiry and paid reactivation."""
from datetime import datetime
import uuid
from decimal import Decimal

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import app, db, Product
import bootstrap
import social

_ORIGINAL_COMPLETE = bootstrap.complete_verified_payment


def expire_listings_with_notifications():
    """Expire listings and send seller expiry email without creating app alerts."""
    now = datetime.utcnow()
    placements = bootstrap.ListingPlacement.query.filter(bootstrap.ListingPlacement.expires_at <= now).all()
    changed = False
    for placement in placements:
        product = Product.query.get(placement.product_id)
        if not product or product.is_sold_out:
            continue
        product.is_sold_out = True
        changed = True
        try:
            import email_notifications
            email_notifications.queue_email(
                placement.seller_id,
                'listing_expired',
                f'Your Merco listing expired: {product.name}',
                f'Your listing "{product.name}" has expired and is no longer visible in the marketplace. Reactivate it whenever you are ready.',
                url_for('reactivate_product', product_id=product.id, _external=True),
                'Reactivate listing',
            )
        except Exception:
            app.logger.exception('Listing expiry email queue failed')
    if changed:
        db.session.commit()


bootstrap.expire_listings = expire_listings_with_notifications


def complete_verified_payment_with_reactivation(payment, transaction):
    if not transaction or transaction.get('status') != 'success':
        return False
    if int(transaction.get('amount') or 0) != payment.amount_kobo or (transaction.get('currency') or '').upper() != 'NGN':
        return False
    if payment.product_id:
        product = Product.query.get(payment.product_id)
        if not product:
            return False
        old = bootstrap.ListingPlacement.query.filter_by(product_id=product.id).first()
        if old:
            db.session.delete(old)
            db.session.flush()
        product.is_sold_out = False
        bootstrap.create_placement(product, payment.seller_id, payment.duration_hours, payment.fee_percent,
                                   payment.amount_kobo, payment.id, False)
        payment.status = 'paid'
        payment.paid_at = datetime.utcnow()
        db.session.commit()
        return True
    return _ORIGINAL_COMPLETE(payment, transaction)


bootstrap.complete_verified_payment = complete_verified_payment_with_reactivation


@app.route('/seller/product/<int:product_id>/reactivate', methods=['GET', 'POST'])
@login_required
def reactivate_product(product_id):
    product = Product.query.get_or_404(product_id)
    if product.seller_id != current_user.id or current_user.role != 'seller':
        flash('You can only reactivate your own listings.')
        return redirect(url_for('seller_dashboard'))
    placement = bootstrap.ListingPlacement.query.filter_by(product_id=product.id).first()
    if placement and placement.expires_at > datetime.utcnow() and not product.is_sold_out:
        flash('This listing is already active.')
        return redirect(url_for('seller_dashboard'))
    if request.method == 'GET':
        return render_template('reactivate_product.html', product=product)
    try:
        duration = int(request.form.get('duration', '24'))
        if duration not in (12, 24):
            raise ValueError('Choose either 12 hours or 24 hours.')
        fee_percent, fee_amount = bootstrap.listing_fee(Decimal(str(product.price)), duration)
        amount_kobo = int((fee_amount * 100).to_integral_value())
        if amount_kobo <= 0:
            raise ValueError('The listing fee is too small to process.')
        payment = bootstrap.ListingPayment(
            reference=f'MAX-REACT-{uuid.uuid4().hex}', seller_id=current_user.id, product_id=product.id,
            name=product.name, price=float(product.price), description=product.description,
            category_id=product.category_id, cover_image=product.cover_image,
            screenshots=product.screenshots, duration_hours=duration, fee_percent=fee_percent,
            amount_kobo=amount_kobo, status='pending')
        db.session.add(payment)
        db.session.commit()
        try:
            checkout_url = bootstrap.initialize_paystack_payment(payment, current_user.email)
        except Exception:
            db.session.delete(payment)
            db.session.commit()
            app.logger.exception('Paystack reactivation initialization failed')
            raise ValueError('Payment could not be started. Please try again.')
        return redirect(checkout_url)
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc))
        return redirect(url_for('reactivate_product', product_id=product.id))


@app.get('/seller/followers')
@login_required
def seller_followers_page():
    if current_user.role != 'seller':
        flash('Seller access only.')
        return redirect(url_for('market'))
    rows = social.SellerFollow.query.filter_by(seller_id=current_user.id).order_by(social.SellerFollow.created_at.desc()).all()
    follower_ids = [row.buyer_id for row in rows]
    users = social.User.query.filter(social.User.id.in_(follower_ids)).all() if follower_ids else []
    by_id = {user.id: user for user in users}
    followers = [(by_id[row.buyer_id], row.created_at) for row in rows if row.buyer_id in by_id]
    return render_template('seller_followers.html', followers=followers)
