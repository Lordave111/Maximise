"""Persistent in-site notifications for Merco."""
from datetime import datetime
from flask import jsonify, render_template, redirect, url_for
from flask_login import current_user, login_required
from sqlalchemy import select, event, text, inspect
from sqlalchemy.orm.attributes import get_history

from sitefix import app, db
from app import User, Product
import social
import bootstrap


class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    kind = db.Column(db.String(40), nullable=False, default='general')
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.String(1000), nullable=False)
    action_url = db.Column(db.String(600), nullable=True)
    action_text = db.Column(db.String(100), nullable=True)
    is_read = db.Column(db.Boolean, nullable=False, default=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class PushJob(db.Model):
    __tablename__ = 'push_job'
    id = db.Column(db.Integer, primary_key=True)
    notification_id = db.Column(db.Integer, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    processed_at = db.Column(db.DateTime, nullable=True)


# create_all() only creates missing tables; it does not add columns to an
# existing Railway/MySQL table. Older Merco databases can therefore be missing
# newer notification fields (for example `kind`). Repair those columns safely
# at startup before any notification query/insert runs.
def _repair_notification_schema():
    try:
        db.create_all()
        inspector = inspect(db.engine)

        if 'notification' in inspector.get_table_names():
            existing = {col['name'] for col in inspector.get_columns('notification')}
            additions = {
                'kind': "VARCHAR(40) NOT NULL DEFAULT 'general'",
                'title': "VARCHAR(180) NOT NULL DEFAULT ''",
                'message': "VARCHAR(1000) NOT NULL DEFAULT ''",
                'action_url': "VARCHAR(600) NULL",
                'action_text': "VARCHAR(100) NULL",
                'is_read': "BOOLEAN NOT NULL DEFAULT FALSE",
                'created_at': "DATETIME NULL",
            }
            for name, definition in additions.items():
                if name not in existing:
                    db.session.execute(text(f"ALTER TABLE notification ADD COLUMN {name} {definition}"))
            # Backfill nullable legacy timestamps before making them useful to
            # ordering code. Leave the column nullable for old rows.
            if 'created_at' not in existing:
                db.session.execute(text("UPDATE notification SET created_at = UTC_TIMESTAMP() WHERE created_at IS NULL"))
            db.session.commit()

        # Keep the push queue compatible with the same legacy database.
        inspector = inspect(db.engine)
        if 'push_job' in inspector.get_table_names():
            existing = {col['name'] for col in inspector.get_columns('push_job')}
            additions = {
                'notification_id': "INTEGER NOT NULL DEFAULT 0",
                'status': "VARCHAR(20) NOT NULL DEFAULT 'pending'",
                'attempts': "INTEGER NOT NULL DEFAULT 0",
                'created_at': "DATETIME NULL",
                'processed_at': "DATETIME NULL",
            }
            for name, definition in additions.items():
                if name not in existing:
                    db.session.execute(text(f"ALTER TABLE push_job ADD COLUMN {name} {definition}"))
            if 'created_at' not in existing:
                db.session.execute(text("UPDATE push_job SET created_at = UTC_TIMESTAMP() WHERE created_at IS NULL"))
            db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('Notification database schema repair failed')


with app.app_context():
    _repair_notification_schema()


def create_notification(user_id, kind, title, message, action_url='', action_text='Open'):
    if not user_id:
        return None
    row = Notification(user_id=user_id, kind=kind, title=title[:180], message=message[:1000], action_url=(action_url or '')[:600], action_text=(action_text or 'Open')[:100])
    db.session.add(row)
    return row


def create_notification_connection(connection, user_id, kind, title, message, action_url='', action_text='Open'):
    if not user_id:
        return
    result = connection.execute(Notification.__table__.insert().values(
        user_id=user_id, kind=kind, title=title[:180], message=message[:1000],
        action_url=(action_url or '')[:600], action_text=(action_text or 'Open')[:100],
        is_read=False, created_at=datetime.utcnow()
    ))
    notification_id = result.inserted_primary_key[0] if result.inserted_primary_key else None
    if notification_id:
        connection.execute(PushJob.__table__.insert().values(notification_id=notification_id, status='pending', attempts=0, created_at=datetime.utcnow()))


@app.get('/api/notifications')
@login_required
def notifications_api():
    rows = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(30).all()
    unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({'ok': True, 'unread': unread, 'notifications': [
        {'id': n.id, 'kind': n.kind, 'title': n.title, 'message': n.message,
         'action_url': n.action_url or '', 'action_text': n.action_text or 'Open',
         'is_read': bool(n.is_read), 'created_at': n.created_at.isoformat() if n.created_at else ''}
        for n in rows
    ]})


@app.post('/api/notifications/<int:notification_id>/read')
@login_required
def notification_read(notification_id):
    row = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    row.is_read = True
    db.session.commit()
    return jsonify({'ok': True})


@app.post('/api/notifications/read-all')
@login_required
def notifications_read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True}, synchronize_session=False)
    db.session.commit()
    return jsonify({'ok': True})


@app.get('/notifications')
@login_required
def notifications_page():
    rows = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(100).all()
    return render_template('notifications.html', notifications=rows)


@app.get('/notifications/open/<int:notification_id>')
@login_required
def open_notification(notification_id):
    row = Notification.query.filter_by(id=notification_id, user_id=current_user.id).first_or_404()
    row.is_read = True
    db.session.commit()
    return redirect(row.action_url or url_for('notifications_page'))


@event.listens_for(Product, 'after_insert')
def notify_followers_new_product(mapper, connection, target):
    followers = connection.execute(select(social.SellerFollow.buyer_id).where(social.SellerFollow.seller_id == target.seller_id)).all()
    seller = connection.execute(select(User.username).where(User.id == target.seller_id)).scalar_one_or_none() or 'A seller'
    link = f'/product/{target.id}'
    for row in followers:
        create_notification_connection(connection, row[0], 'new_product', f'{seller} posted a new product', f'{seller} just posted {target.name} on Merco.', link, 'View product')


@event.listens_for(social.SellerFollow, 'after_insert')
def notify_new_follower(mapper, connection, target):
    buyer = connection.execute(select(User.username).where(User.id == target.buyer_id)).scalar_one_or_none() or 'A buyer'
    seller = connection.execute(select(User.username, User.seller_slug).where(User.id == target.seller_id)).first()
    if seller:
        name, slug = seller
        link = f'/seller/{slug}' if slug else '/seller'
        create_notification_connection(connection, target.seller_id, 'new_follower', 'You have a new follower', f'{buyer} is now following your store.', link, 'View store')


@event.listens_for(bootstrap.ListingPayment, 'after_update')
def notify_payment_success(mapper, connection, target):
    history = get_history(target, 'status')
    if not history.has_changes() or target.status != 'paid':
        return
    create_notification_connection(connection, target.seller_id, 'payment_success', 'Your listing is live', f'Payment confirmed. {target.name} is now published for {target.duration_hours} hours.', '/seller', 'Open seller dashboard')


@event.listens_for(User, 'after_update')
def notify_account_lifecycle(mapper, connection, target):
    role_history = get_history(target, 'role')
    verified_history = get_history(target, 'email_verified')
    if role_history.has_changes() and target.role == 'seller' and role_history.deleted and role_history.deleted[0] == 'buyer':
        slug = target.seller_slug or ''
        create_notification_connection(connection, target.id, 'seller_activated', 'Seller Mode is live', 'Your seller storefront is now active and ready for listings.', f'/seller/{slug}' if slug else '/seller', 'Open my store')
    if verified_history.has_changes() and bool(target.email_verified) and verified_history.deleted and not bool(verified_history.deleted[0]):
        create_notification_connection(connection, target.id, 'welcome', 'Welcome to Merco', 'Your email is verified and your account is ready.', '/market', 'Explore Merco')
