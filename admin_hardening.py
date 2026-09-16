"""Production hardening for the Merco admin centre."""

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import inspect, text, or_

from sitefix import app, db
import app as app_module

User = app_module.User
Product = app_module.Product


def _admin_only():
    if not current_user.is_authenticated or current_user.role != 'admin':
        flash('Admin access required.')
        return redirect(url_for('dashboard'))
    return None


def _admin_dashboard_hardened():
    denied = _admin_only()
    if denied:
        return denied

    search = request.args.get('user_search', '').strip()
    all_users = User.query.order_by(User.id.desc()).all()
    query = User.query
    if search:
        term = f'%{search}%'
        if search.isdigit():
            query = query.filter(or_(User.username.ilike(term), User.email.ilike(term), User.id == int(search)))
        else:
            query = query.filter(or_(User.username.ilike(term), User.email.ilike(term)))
    users = query.order_by(User.id.desc()).all()

    sellers = [u for u in users if u.role == 'seller']
    buyers = [u for u in users if u.role == 'buyer']
    products = Product.query.order_by(Product.id.desc()).all()
    suspended_count = sum(1 for u in all_users if getattr(u, 'suspended_until', None))

    return render_template(
        'admin_dashboard.html',
        users=users,
        sellers=sellers,
        buyers=buyers,
        products=products,
        suspended_count=suspended_count,
        user_search=search,
    )


@app.post('/admin/user/<int:id>/delete', endpoint='admin_delete_user_hardened')
@login_required
def admin_delete_user_hardened(id):
    denied = _admin_only()
    if denied:
        return denied

    user = User.query.get_or_404(id)
    if user.id == current_user.id:
        flash('You cannot delete your own admin account.')
        return redirect(url_for('admin_dashboard'))
    if user.role == 'admin':
        flash('Admin accounts are protected from deletion in this panel.')
        return redirect(url_for('admin_dashboard'))

    try:
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        preparer = db.engine.dialect.identifier_preparer
        products = list(user.products)
        product_ids = [p.id for p in products]

        delete_files = getattr(app_module, 'delete_product_files', None)
        if delete_files:
            for product in products:
                try:
                    delete_files(product)
                except Exception:
                    app.logger.exception('Could not remove files for product %s', product.id)

        # Clean product-dependent records before removing the seller's products.
        for table in tables:
            if table in {'user', 'product'} or not product_ids:
                continue
            try:
                columns = {c['name'] for c in inspector.get_columns(table)}
            except Exception:
                continue
            if 'product_id' in columns:
                quoted = preparer.quote(table)
                for product_id in product_ids:
                    db.session.execute(text(f'DELETE FROM {quoted} WHERE product_id = :pid'), {'pid': product_id})

        # Clean every common user relationship, including push_job and followers.
        user_reference_columns = (
            'user_id', 'buyer_id', 'seller_id', 'viewer_id',
            'owner_id', 'follower_id', 'following_id'
        )
        for table in tables:
            if table == 'user':
                continue
            try:
                columns = {c['name'] for c in inspector.get_columns(table)}
            except Exception:
                continue
            matches = [column for column in user_reference_columns if column in columns]
            if not matches:
                continue
            quoted = preparer.quote(table)
            conditions = ' OR '.join(f'{preparer.quote(column)} = :uid' for column in matches)
            db.session.execute(text(f'DELETE FROM {quoted} WHERE {conditions}'), {'uid': user.id})

        # Legacy MySQL foreign keys can exist outside the ORM model. Disable
        # them only for the final deletion after dependent rows were cleaned.
        mysql = db.engine.dialect.name == 'mysql'
        if mysql:
            db.session.execute(text('SET FOREIGN_KEY_CHECKS=0'))
        try:
            db.session.delete(user)
            db.session.commit()
        finally:
            if mysql:
                db.session.execute(text('SET FOREIGN_KEY_CHECKS=1'))
                db.session.commit()

        flash(f'{user.username} was permanently deleted.')
    except Exception:
        db.session.rollback()
        try:
            if db.engine.dialect.name == 'mysql':
                db.session.execute(text('SET FOREIGN_KEY_CHECKS=1'))
                db.session.commit()
        except Exception:
            db.session.rollback()
        app.logger.exception('Hardened admin user deletion failed')
        flash('The user could not be deleted. No account changes were saved.')

    return redirect(url_for('admin_dashboard'))


# Make the existing admin template action use the hardened route.
app.view_functions['admin_delete_user_safe'] = admin_delete_user_hardened
app.view_functions['admin_delete_user_hardened'] = admin_delete_user_hardened
app.view_functions['admin_dashboard'] = _admin_dashboard_hardened
