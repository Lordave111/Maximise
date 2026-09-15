"""Admin user-management layer for Merco.

Keeps the legacy app intact while adding DB-backed user management, editing,
account suspension and a responsive admin dashboard.
"""

from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, logout_user
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash

from sitefix import app, db
import app as app_module

User = app_module.User
Product = app_module.Product


def _ensure_suspension_column():
    """Add the suspension timestamp to existing production databases safely."""
    with app.app_context():
        inspector = inspect(db.engine)
        if 'user' not in inspector.get_table_names():
            return
        columns = {column['name'] for column in inspector.get_columns('user')}
        if 'suspended_until' not in columns:
            quoted = db.engine.dialect.identifier_preparer.quote('user')
            dialect = db.engine.dialect.name
            definition = 'DATETIME NULL' if dialect == 'mysql' else 'TIMESTAMP NULL'
            with db.engine.begin() as connection:
                connection.execute(text(f'ALTER TABLE {quoted} ADD COLUMN suspended_until {definition}'))


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


def _admin_only():
    if not current_user.is_authenticated or current_user.role != 'admin':
        flash('Admin access required.')
        return redirect(url_for('dashboard'))
    return None


@app.before_request
def block_suspended_accounts():
    """Prevent suspended buyers/sellers from using the marketplace."""
    if not current_user.is_authenticated or current_user.role == 'admin':
        return None
    if not _is_suspended(current_user):
        return None
    logout_user()
    flash('Your Merco account is currently suspended. Please contact the administrator.')
    return redirect(url_for('login'))


def _admin_dashboard():
    denied = _admin_only()
    if denied:
        return denied
    users = User.query.order_by(User.id.desc()).all()
    sellers = [user for user in users if user.role == 'seller']
    buyers = [user for user in users if user.role == 'buyer']
    products = Product.query.order_by(Product.id.desc()).all()
    suspended_count = sum(1 for user in users if _is_suspended(user))
    return render_template(
        'admin_dashboard.html',
        users=users,
        sellers=sellers,
        buyers=buyers,
        products=products,
        suspended_count=suspended_count,
    )


@app.route('/admin/user/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_edit_user(id):
    denied = _admin_only()
    if denied:
        return denied
    user = User.query.get_or_404(id)
    if request.method == 'POST':
        try:
            username = request.form.get('username', '').strip()[:100]
            email = request.form.get('email', '').strip().lower()[:100]
            role = request.form.get('role', user.role).strip().lower()
            whatsapp = request.form.get('whatsapp_number', '').strip()[:30]
            password = request.form.get('password', '')
            if not username or not email or '@' not in email:
                raise ValueError('Name and a valid email are required.')
            if role not in {'buyer', 'seller', 'admin'}:
                raise ValueError('Invalid user role.')
            duplicate = User.query.filter(User.email == email, User.id != user.id).first()
            if duplicate:
                raise ValueError('Another account already uses that email.')
            if user.id == current_user.id and role != 'admin':
                raise ValueError('You cannot remove admin access from your current account.')
            user.username = username
            user.email = email
            user.role = role
            user.whatsapp_number = whatsapp or None
            user.email_verified = request.form.get('email_verified') == '1'
            user.email_notifications = request.form.get('email_notifications') == '1'
            if password:
                if len(password) < 6:
                    raise ValueError('New passwords must contain at least 6 characters.')
                user.password = generate_password_hash(password)
            db.session.commit()
            flash(f'{user.username} was updated successfully.')
            return redirect(url_for('admin_dashboard'))
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc))
        except Exception:
            db.session.rollback()
            app.logger.exception('Admin user edit failed')
            flash('The user could not be updated. No changes were saved.')
    return render_template('admin_user_edit.html', user=user, suspended=_is_suspended(user))


@app.post('/admin/user/<int:id>/suspend')
@login_required
def admin_suspend_user(id):
    denied = _admin_only()
    if denied:
        return denied
    user = User.query.get_or_404(id)
    if user.id == current_user.id or user.role == 'admin':
        flash('Admin accounts cannot be suspended from this panel.')
        return redirect(url_for('admin_dashboard'))
    try:
        mode = request.form.get('duration', 'days').strip().lower()
        if mode == 'indefinite':
            user.suspended_until = datetime.utcnow() + timedelta(days=36500)
            message = f'{user.username} was suspended indefinitely.'
        else:
            days = int(request.form.get('days', '1'))
            if days < 1 or days > 3650:
                raise ValueError
            user.suspended_until = datetime.utcnow() + timedelta(days=days)
            message = f'{user.username} was suspended for {days} day(s).'
        db.session.commit()
        flash(message)
    except ValueError:
        db.session.rollback()
        flash('Choose a valid suspension period between 1 and 3650 days.')
    except Exception:
        db.session.rollback()
        app.logger.exception('Admin user suspension failed')
        flash('The account could not be suspended.')
    return redirect(url_for('admin_dashboard'))


@app.post('/admin/user/<int:id>/unsuspend')
@login_required
def admin_unsuspend_user(id):
    denied = _admin_only()
    if denied:
        return denied
    user = User.query.get_or_404(id)
    user.suspended_until = None
    try:
        db.session.commit()
        flash(f'{user.username} can access Merco again.')
    except Exception:
        db.session.rollback()
        flash('Could not remove the suspension.')
    return redirect(url_for('admin_dashboard'))


@app.post('/admin/user/<int:id>/delete')
@login_required
def admin_delete_user_safe(id):
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
        # Clean uploaded files first; the DB transaction below remains the
        # source of truth for the account deletion.
        delete_files = getattr(app_module, 'delete_product_files', None)
        for product in list(user.products):
            if delete_files:
                try:
                    delete_files(product)
                except Exception:
                    app.logger.exception('Could not remove files for product %s', product.id)

        # Several optional marketplace modules have user foreign keys without
        # ORM relationships. Delete those rows explicitly so MySQL/Postgres
        # foreign-key constraints cannot block account removal.
        related_tables = (
            'push_subscription', 'email_job', 'notification',
            'seller_follow', 'product_view', 'seller_contact',
            'listing_placement', 'listing_payment',
        )
        dialect = db.engine.dialect
        preparer = dialect.identifier_preparer
        user_table = preparer.quote('user')
        for table in related_tables:
            try:
                columns = {c['name'] for c in inspect(db.engine).get_columns(table)}
            except Exception:
                continue
            if 'user_id' in columns:
                db.session.execute(text(f'DELETE FROM {preparer.quote(table)} WHERE user_id = :uid'), {'uid': user.id})
            if table == 'seller_follow' and 'buyer_id' in columns:
                db.session.execute(text(f'DELETE FROM {preparer.quote(table)} WHERE buyer_id = :uid OR seller_id = :uid'), {'uid': user.id})
            elif table == 'product_view' and 'viewer_id' in columns:
                db.session.execute(text(f'DELETE FROM {preparer.quote(table)} WHERE viewer_id = :uid'), {'uid': user.id})
            elif table in {'seller_contact', 'listing_placement', 'listing_payment'} and 'seller_id' in columns:
                db.session.execute(text(f'DELETE FROM {preparer.quote(table)} WHERE seller_id = :uid'), {'uid': user.id})

        # Product rows are cascade/delete-orphan children of User.
        db.session.delete(user)
        db.session.commit()
        flash(f'{user.username} was permanently deleted.')
    except Exception:
        db.session.rollback()
        app.logger.exception('Admin user deletion failed')
        flash('The user could not be deleted. No account changes were saved.')
    return redirect(url_for('admin_dashboard'))


app.view_functions['admin_dashboard'] = _admin_dashboard
