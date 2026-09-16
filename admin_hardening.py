"""Production hardening for the Merco admin centre."""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
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
    """Delete a user and that user's products directly in the database."""
    denied = _admin_only()
    if denied:
        return denied

    if id == current_user.id:
        flash('You cannot delete your own admin account.')
        return redirect(url_for('admin_dashboard'))

    engine = db.engine
    dialect = engine.dialect.name
    user_table = '`user`' if dialect == 'mysql' else '"user"'
    product_table = '`product`' if dialect == 'mysql' else '"product"'

    try:
        with engine.begin() as connection:
            if dialect == 'mysql':
                connection.execute(text('SET FOREIGN_KEY_CHECKS=0'))

            try:
                row = connection.execute(
                    text(f'SELECT username, role FROM {user_table} WHERE id = :id'),
                    {'id': id},
                ).mappings().first()

                if not row:
                    flash('User not found.')
                    return redirect(url_for('admin_dashboard'))

                if row['role'] == 'admin':
                    flash('Admin accounts are protected from deletion.')
                    return redirect(url_for('admin_dashboard'))

                connection.execute(
                    text(f'DELETE FROM {product_table} WHERE seller_id = :id'),
                    {'id': id},
                )
                connection.execute(
                    text(f'DELETE FROM {user_table} WHERE id = :id'),
                    {'id': id},
                )
                username = row['username']
            finally:
                if dialect == 'mysql':
                    connection.execute(text('SET FOREIGN_KEY_CHECKS=1'))

        db.session.expire_all()
        flash(f'{username} and their products were permanently deleted.')
    except Exception:
        db.session.rollback()
        app.logger.exception('Admin deletion failed for user %s', id)
        flash('Could not delete the user from the database.')

    return redirect(url_for('admin_dashboard'))


app.view_functions['admin_delete_user_safe'] = admin_delete_user_hardened
app.view_functions['admin_delete_user_hardened'] = admin_delete_user_hardened
app.view_functions['admin_dashboard'] = _admin_dashboard_hardened


def _ensure_suspension_column():
    """Add the suspension timestamp to existing production databases safely."""
    with app.app_context():
        inspector = inspect(db.engine)
        if 'user' not in inspector.get_table_names():
            return

        columns = {column['name'] for column in inspector.get_columns('user')}
        if 'suspended_until' not in columns:
            quoted = db.engine.dialect.identifier_preparer.quote('user')
            dialect_name = db.engine.dialect.name
            definition = 'DATETIME NULL' if dialect_name == 'mysql' else 'TIMESTAMP NULL'
            with db.engine.begin() as connection:
                connection.execute(
                    text(f'ALTER TABLE {quoted} ADD COLUMN suspended_until {definition}')
                )


_ensure_suspension_column()

if not hasattr(User, 'suspended_until'):
    User.suspended_until = db.Column(db.DateTime, nullable=True)


def _is_suspended(user):
    until = getattr(user, 'suspended_until', None)
    if not until:
        return False

    if until <= datetime.utcnow():
        user.suspended_until = None
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
        return False

    return True


def block_suspended_accounts():
    """Prevent suspended buyers/sellers from using the marketplace."""
    if not current_user.is_authenticated or current_user.role == 'admin':
        return None
    if not _is_suspended(current_user):
        return None

    logout_user()
    flash('Your Merco account is currently suspended. Please contact the administrator.')
    return redirect(url_for('login'))


app.before_request(block_suspended_accounts)
