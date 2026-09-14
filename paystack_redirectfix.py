"""Production Paystack callback redirect.

After a successful listing payment, sellers should land on their public
storefront rather than the seller dashboard.
"""

from flask import flash, redirect, request, url_for
from flask_login import current_user, login_required

from sitefix import app, db
import bootstrap


def _seller_store_url():
    slug = (getattr(current_user, 'seller_slug', None) or '').strip()
    if slug:
        return f'/seller/{slug}'
    return url_for('seller_dashboard')


@app.get('/payments/paystack/callback', endpoint='paystack_callback_storefront')
@login_required
def paystack_callback_storefront():
    reference = (request.args.get('reference') or request.args.get('trxref') or '').strip()
    payment = bootstrap.ListingPayment.query.filter_by(
        reference=reference, seller_id=current_user.id
    ).first()
    if not payment:
        flash('We could not find that listing payment.')
        return redirect(url_for('seller_dashboard'))

    if payment.status == 'paid' and payment.product_id:
        flash('Payment confirmed. Your listing is live.')
        return redirect(_seller_store_url())

    try:
        transaction = bootstrap.verify_with_paystack(reference)
        if bootstrap.complete_verified_payment(payment, transaction):
            flash('Payment confirmed. Your listing is now live.')
            return redirect(_seller_store_url())
        payment.status = 'failed'
        db.session.commit()
        flash('Payment was not confirmed, so the listing was not published.')
    except Exception:
        db.session.rollback()
        app.logger.exception('Paystack storefront callback verification failed')
        flash('We could not verify the payment yet. If you were charged, please contact support.')

    return redirect(url_for('seller_dashboard'))


# Replace the legacy callback endpoint with this production-safe callback.
app.view_functions['paystack_callback'] = paystack_callback_storefront
