"""Seller store management routes for Merco.

Keeps seller inventory management separate from the core app so the existing
listing/payment layer is left untouched. Sellers can edit listing details,
mark products sold out/live, delete listings, and open their public store.
"""
from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from sitefix import app
import app as app_module


def _seller_dashboard():
    return redirect(url_for('seller_dashboard'))


@app.route('/seller/product/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def seller_edit_product(id):
    if current_user.role != 'seller':
        flash('Seller access required.')
        return redirect(url_for('dashboard'))

    product = app_module.Product.query.filter_by(id=id, seller_id=current_user.id).first_or_404()
    categories = app_module.Category.query.order_by(app_module.Category.name.asc()).all()

    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()[:200]
            price_raw = request.form.get('price', '0').strip()
            description = request.form.get('description', '').strip()
            category_id = request.form.get('category_id', type=int)

            from decimal import Decimal, InvalidOperation
            price = Decimal(price_raw)
            if not name:
                raise ValueError('Enter a product name.')
            if price < 0:
                raise ValueError('Price cannot be negative.')
            if not category_id or not app_module.Category.query.get(category_id):
                raise ValueError('Choose a valid category.')

            product.name = name
            product.price = float(price)
            product.description = description
            product.category_id = category_id
            app_module.db.session.commit()
            flash('Product updated successfully. Your existing listing payment and placement remain unchanged.')
            return _seller_dashboard()
        except (InvalidOperation, ValueError) as exc:
            app_module.db.session.rollback()
            flash(str(exc))
        except Exception:
            app_module.db.session.rollback()
            app.logger.exception('Seller product edit failed')
            flash('The product could not be updated. Please try again.')

    return render_template('seller_edit_product.html', product=product, categories=categories)


@app.post('/seller/product/<int:id>/toggle')
@login_required
def seller_toggle_product(id):
    if current_user.role != 'seller':
        flash('Seller access required.')
        return redirect(url_for('dashboard'))

    product = app_module.Product.query.filter_by(id=id, seller_id=current_user.id).first_or_404()
    product.is_sold_out = not product.is_sold_out
    app_module.db.session.commit()
    flash('Product marked as sold out.' if product.is_sold_out else 'Product is live again.')
    return _seller_dashboard()


# Make the edit/toggle routes visible to Flask even when this module is loaded
# after the original app routes.
app.view_functions['seller_edit_product'] = seller_edit_product
app.view_functions['seller_toggle_product'] = seller_toggle_product
