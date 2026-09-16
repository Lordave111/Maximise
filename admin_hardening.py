"""Production hardening for the Merco admin centre."""

from datetime import datetime

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from sqlalchemy import inspect, text, or

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
            query = query.filter(
                or_(User.username.ilike(term), User.email.ilike(term), User.id == int(search))
            )
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
    """Delete an account directly at database level without ORM cascades."""
    denied = _admin_only()
    if denied:
        return denied

    dialect = db.engine.dialect.name
    user_table = '`user`' if dialect == 'mysql' else '"user"'

    row = db.session.execute(
        text(f'SELECT id, username, role FROM {user_table} WHERE id = :uid'),
        {'uid': id},
    ).mappings().first()

    if not row:
        flash('User not found.')
        return redirect(url_for('admin_dashboard'))

    if int(row['id']) == int(current_user.id):
        flash('You cannot delete your own admin account.')
        return redirect(url_for('admin_dashboard'))

    if row['role'] == 'admin':
        flash('Admin accounts are protected from deletion in this panel.')
        return redirect(url_for('admin_dashboard'))

    username = row['username']
    engine = db.engine
    quote_name = engine.dialect.identifier_preparer.quote
    product_table = quote_name('product')
    user_table_quoted = quote_name('user')

    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        table_columns = {}

        for table in tables:
            try:
                table_columns[table] = {column['name'] for column in inspector.get_columns(table)}
            except Exception:
                table_columns[table] = set()

        with engine.begin() as connection:
            if dialect == 'mysql':
                connection.execute(text('SET FOREIGN_KEY_CHECKS=0'))

            try:
                product_ids = []
                product_columns = table_columns.get('product', set())

                if 'seller_id' in product_columns:
                    product_rows = connection.execute(
                        text(f'SELECT id FROM {product_table} WHERE seller_id = :uid'),
                        {'uid': id},
                    ).fetchall()
                    product_ids = [int(product_row[0]) for product_row in product_rows]

                if product_ids:
                    for table, columns in table_columns.items():
                        if table in {'user', 'product'} or 'product_id' not in columns:
                            continue

                        placeholders = ', '.join(
                            f':product_{index}' for index in range(len(product_ids))
                        )
                        params = {
                            f'product_{index}': value
                            for index, value in enumerate(product_ids)
                        }
                        quoted_table = quote_name(table)
                        connection.execute(
                            text(
                                f'DELETE FROM {quoted_table} '
                                f'WHERE product_id IN ({placeholders})'
                            ),
                            params,
                        )

                user_reference_columns = (
                    'user_id',
                    'buyer_id',
                    'seller_id',
                    'viewer_id',
                    'owner_id',
                    'follower_id',
                    'following_id',
                    'account_id',
                )

                for table, columns in table_columns.items():
                    if table == 'user' or not columns:
                        continue

                    matches = [
                        column
                        for column in user_reference_columns
                        if column in columns
                    ]
                    if not matches:
                        continue

                    quoted_table = quote_name(table)
                    conditions = ' OR '.join(
                        f'{quote_name(column)} = :uid'
                        for column in matches
                    )
                    connection.execute(
                        text(f'DELETE FROM {quoted_table} WHERE {conditions}'),
                        {'uid': id},
                    )

                if 'seller_id' in product_columns:
                    connection.execute(
                        text(f'DELETE FROM {product_table} WHERE seller_id = :uid'),
                        {'uid': id},
                    )

                connection.execute(
                    text(f'DELETE FROM {user_table_quoted} WHERE id = :uid'),
                    {'uid': id},
                )
            finally:
                if dialect == 'mysql':
                    connection.execute(text('SET FOREIGN_KEY_CHECKS=1'))

        flash(f'{username} was permanently deleted.')
    except Exception:
        db.session.rollback()
        app.logger.exception(
            'Direct database admin user deletion failed for user %s',
            id,
        )
        flash('The user could not be deleted. The database was left unchanged.')

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
                    text(
                        f'ALTER TABLE {quoted} '
                        f'ADD COLUMN suspended_until {definition}'
                    )
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
    from flask_login import current_user as _current_user

    if not _current_user.is_authenticated or _current_user.role == 'admin':
        return None
    if not _is_suspended(_current_user):
        return None

    logout_user()
    flash('Your Merco account is currently suspended. Please contact the administrator.')
    return redirect(url_for('login'))


app.before_request(block_suspended_accounts)
