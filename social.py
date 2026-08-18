from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import event, select

from app import app, db, Product, User, unique_seller_slug
from bootstrap import SellerContact, ListingPlacement


class SellerFollow(db.Model):
    __tablename__ = 'seller_follow'
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    __table_args__ = (db.UniqueConstraint('buyer_id', 'seller_id', name='uq_seller_follow'),)


class Notification(db.Model):
    __tablename__ = 'notification'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    title = db.Column(db.String(180), nullable=False)
    message = db.Column(db.String(500), nullable=False)
    link = db.Column(db.String(500), nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now(), index=True)


class ProductView(db.Model):
    __tablename__ = 'product_view'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    viewed_at = db.Column(db.DateTime, server_default=db.func.now(), index=True)
    __table_args__ = (db.Index('ix_product_view_product_viewer', 'product_id', 'viewer_id'),)


with app.app_context():
    db.create_all()


@event.listens_for(Product, 'after_insert')
def notify_followers_after_product_insert(mapper, connection, target):
    rows = connection.execute(select(SellerFollow.buyer_id).where(SellerFollow.seller_id == target.seller_id)).all()
    if not rows:
        return
    seller = connection.execute(select(User.username).where(User.id == target.seller_id)).scalar_one_or_none() or 'A seller'
    link = f'/product/{target.id}'
    values = [{'user_id': row[0], 'title': f'{seller} posted a new product', 'message': f'{target.name} is now available on Maximise.', 'link': link, 'created_at': datetime.utcnow()} for row in rows]
    connection.execute(Notification.__table__.insert(), values)


@app.before_request
def record_product_view():
    if request.method != 'GET':
        return
    path = request.path.rstrip('/')
    if not path.startswith('/product/'):
        return
    try:
        product_id = int(path.rsplit('/', 1)[-1])
    except (TypeError, ValueError):
        return
    product = db.session.get(Product, product_id)
    if not product or (current_user.is_authenticated and current_user.id == product.seller_id):
        return
    now = datetime.utcnow()
    if current_user.is_authenticated:
        recent = ProductView.query.filter(ProductView.product_id == product_id, ProductView.viewer_id == current_user.id, ProductView.viewed_at >= now - timedelta(days=1)).first()
        if recent:
            return
        db.session.add(ProductView(product_id=product_id, viewer_id=current_user.id))
    else:
        db.session.add(ProductView(product_id=product_id, viewer_id=None))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


@app.context_processor
def inject_social_globals():
    unread = 0
    following_count = 0
    if current_user.is_authenticated:
        try:
            unread = Notification.query.filter_by(user_id=current_user.id, read_at=None).count()
            following_count = SellerFollow.query.filter_by(buyer_id=current_user.id).count()
        except Exception:
            db.session.rollback()
    return {'unread_notifications': unread, 'following_count': following_count, 'is_following_seller': lambda seller_id: is_following(current_user.id, seller_id) if current_user.is_authenticated else False}


def is_following(buyer_id, seller_id):
    return SellerFollow.query.filter_by(buyer_id=buyer_id, seller_id=seller_id).first() is not None


@app.post('/follow-seller/<seller_slug>')
@login_required
def follow_seller(seller_slug):
    seller = User.query.filter_by(seller_slug=seller_slug, role='seller').first_or_404()
    if seller.id == current_user.id:
        flash('You cannot follow your own store.')
        return redirect(request.referrer or url_for('seller_page', seller_slug=seller_slug))
    existing = SellerFollow.query.filter_by(buyer_id=current_user.id, seller_id=seller.id).first()
    if existing:
        db.session.delete(existing)
        flash(f'You unfollowed {seller.username}.')
    else:
        db.session.add(SellerFollow(buyer_id=current_user.id, seller_id=seller.id))
        db.session.add(Notification(user_id=seller.id, title='New follower', message=f'{current_user.username} is now following your store.', link=url_for('seller_page', seller_slug=seller.seller_slug)))
        flash(f'You are now following {seller.username}.')
    db.session.commit()
    return redirect(request.referrer or url_for('seller_page', seller_slug=seller_slug))


@app.get('/notifications')
@login_required
def notifications():
    items = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(80).all()
    return render_template('notifications.html', notifications=items)


@app.post('/notifications/<int:id>/read')
@login_required
def notification_read(id):
    item = Notification.query.filter_by(id=id, user_id=current_user.id).first_or_404()
    item.read_at = datetime.utcnow()
    db.session.commit()
    return redirect(item.link or url_for('notifications'))


@app.post('/notifications/read-all')
@login_required
def notifications_read_all():
    Notification.query.filter_by(user_id=current_user.id, read_at=None).update({'read_at': datetime.utcnow()}, synchronize_session=False)
    db.session.commit()
    return redirect(url_for('notifications'))


@app.get('/following')
@login_required
def following():
    rows = SellerFollow.query.filter_by(buyer_id=current_user.id).order_by(SellerFollow.created_at.desc()).all()
    sellers = []
    for row in rows:
        seller = User.query.get(row.seller_id)
        if seller and seller.role == 'seller':
            sellers.append(seller)
    return render_template('following.html', sellers=sellers)


@app.get('/seller/insights')
@login_required
def seller_insights():
    if current_user.role != 'seller':
        flash('Seller access required.')
        return redirect(url_for('market'))
    products = Product.query.filter_by(seller_id=current_user.id).order_by(Product.created_at.desc(), Product.id.desc()).all()
    follower_rows = SellerFollow.query.filter_by(seller_id=current_user.id).order_by(SellerFollow.created_at.desc()).all()
    follower_ids = [row.buyer_id for row in follower_rows]
    followers = User.query.filter(User.id.in_(follower_ids)).all() if follower_ids else []
    follower_map = {user.id: user for user in followers}
    followers = [follower_map[row.buyer_id] for row in follower_rows if row.buyer_id in follower_map]
    analytics = []
    for product in products:
        total_views = ProductView.query.filter_by(product_id=product.id).count()
        unique_logged_in = db.session.query(ProductView.viewer_id).filter(ProductView.product_id == product.id, ProductView.viewer_id.isnot(None)).distinct().count()
        anonymous_views = ProductView.query.filter_by(product_id=product.id, viewer_id=None).count()
        recent_views = ProductView.query.filter(ProductView.product_id == product.id, ProductView.viewed_at >= datetime.utcnow() - timedelta(days=7)).count()
        viewer_rows = ProductView.query.filter(ProductView.product_id == product.id, ProductView.viewer_id.isnot(None)).order_by(ProductView.viewed_at.desc()).limit(20).all()
        viewer_ids = list(dict.fromkeys(row.viewer_id for row in viewer_rows if row.viewer_id))
        viewer_users = User.query.filter(User.id.in_(viewer_ids)).all() if viewer_ids else []
        viewer_map = {user.id: user for user in viewer_users}
        viewers = [(viewer_map[row.viewer_id], row.viewed_at) for row in viewer_rows if row.viewer_id in viewer_map]
        analytics.append({'product': product, 'views': total_views, 'unique_viewers': unique_logged_in, 'anonymous_views': anonymous_views, 'recent_views': recent_views, 'viewers': viewers})
    total_views = sum(item['views'] for item in analytics)
    return render_template('seller_insights.html', analytics=analytics, followers=followers, total_views=total_views, follower_count=len(followers))


@app.get('/admin/control')
@login_required
def admin_control():
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    sellers = User.query.filter_by(role='seller').order_by(User.id.desc()).all()
    buyers = User.query.filter_by(role='buyer').order_by(User.id.desc()).all()
    products = Product.query.order_by(Product.created_at.desc(), Product.id.desc()).all()
    follows = SellerFollow.query.count()
    unread = Notification.query.filter(Notification.read_at.is_(None)).count()
    placements = ListingPlacement.query.order_by(ListingPlacement.expires_at.desc()).limit(30).all()
    return render_template('admin_control.html', sellers=sellers, buyers=buyers, products=products, follows=follows, unread_notifications=unread, placements=placements)


@app.post('/admin/product/<int:id>/toggle')
@login_required
def admin_toggle_product(id):
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    product = Product.query.get_or_404(id)
    product.is_sold_out = not bool(product.is_sold_out)
    db.session.commit()
    flash(f'{product.name} is now {"hidden" if product.is_sold_out else "visible"} in the market.')
    return redirect(request.referrer or url_for('admin_control'))


@app.post('/admin/user/<int:id>/role')
@login_required
def admin_change_role(id):
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    user = User.query.get_or_404(id)
    if user.role == 'admin' or user.id == current_user.id:
        flash('Admin accounts cannot be changed here.')
        return redirect(url_for('admin_control'))
    target = request.form.get('role', 'buyer')
    if target not in ('buyer', 'seller'):
        flash('Invalid role.')
        return redirect(url_for('admin_control'))
    user.role = target
    if target == 'seller':
        user.seller_slug = unique_seller_slug(user.username, user.id)
        contact = SellerContact.query.filter_by(seller_id=user.id).first()
        if not contact:
            db.session.add(SellerContact(seller_id=user.id, public_email=user.email, phone_number='', free_listing_used=False))
    db.session.commit()
    flash(f'{user.username} is now a {target}.')
    return redirect(url_for('admin_control'))


@app.post('/admin/announce')
@login_required
def admin_announce():
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    title = request.form.get('title', '').strip()[:180]
    message = request.form.get('message', '').strip()[:500]
    if not title or not message:
        flash('Add both a title and message.')
        return redirect(url_for('admin_control'))
    users = User.query.filter(User.id != current_user.id).all()
    db.session.bulk_save_objects([Notification(user_id=u.id, title=title, message=message, link='/market') for u in users])
    db.session.commit()
    flash(f'Announcement delivered to {len(users)} users.')
    return redirect(url_for('admin_control'))


import seller_features  # noqa: E402,F401
