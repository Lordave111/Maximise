"""Following, seller insights and product-view features.

Marketplace alerts are intentionally email-only. There is no in-site or
phone notification UI or delivery layer here.
"""
from datetime import datetime, timedelta

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import app, db, Product, User
import bootstrap


class SellerFollow(db.Model):
    __tablename__ = 'seller_follow'
    id = db.Column(db.Integer, primary_key=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, server_default=db.func.now())
    __table_args__ = (db.UniqueConstraint('buyer_id', 'seller_id', name='uq_seller_follow'),)


class ProductView(db.Model):
    __tablename__ = 'product_view'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False, index=True)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    viewed_at = db.Column(db.DateTime, server_default=db.func.now(), index=True)
    __table_args__ = (db.Index('ix_product_view_product_viewer', 'product_id', 'viewer_id'),)


with app.app_context():
    db.create_all()


@app.before_request
def record_product_view():
    if request.method != 'GET' or not request.path.rstrip('/').startswith('/product/'):
        return
    try:
        product_id = int(request.path.rsplit('/', 1)[-1])
    except (TypeError, ValueError):
        return
    product = db.session.get(Product, product_id)
    if not product or (current_user.is_authenticated and current_user.id == product.seller_id):
        return
    now = datetime.utcnow()
    if current_user.is_authenticated:
        recent = ProductView.query.filter(
            ProductView.product_id == product_id,
            ProductView.viewer_id == current_user.id,
            ProductView.viewed_at >= now - timedelta(days=1),
        ).first()
        if recent:
            return
        db.session.add(ProductView(product_id=product_id, viewer_id=current_user.id))
    else:
        db.session.add(ProductView(product_id=product_id, viewer_id=None))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()


def is_following(buyer_id, seller_id):
    return SellerFollow.query.filter_by(buyer_id=buyer_id, seller_id=seller_id).first() is not None


@app.context_processor
def inject_social_globals():
    following_count = 0
    if current_user.is_authenticated:
        try:
            following_count = SellerFollow.query.filter_by(buyer_id=current_user.id).count()
        except Exception:
            db.session.rollback()
    return {
        'following_count': following_count,
        'is_following_seller': lambda seller_id: is_following(current_user.id, seller_id) if current_user.is_authenticated else False,
    }


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
        db.session.commit()
        flash(f'You unfollowed {seller.username}.')
    else:
        db.session.add(SellerFollow(buyer_id=current_user.id, seller_id=seller.id))
        db.session.commit()
        flash(f'You are now following {seller.username}. New product updates will be sent by email.')
    return redirect(request.referrer or url_for('seller_page', seller_slug=seller_slug))


@app.get('/following')
@login_required
def following():
    rows = SellerFollow.query.filter_by(buyer_id=current_user.id).order_by(SellerFollow.created_at.desc()).all()
    sellers = [seller for row in rows if (seller := db.session.get(User, row.seller_id)) and seller.role == 'seller']
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
    return render_template('seller_insights.html', analytics=analytics, followers=followers, total_views=sum(item['views'] for item in analytics), follower_count=len(followers))


@app.get('/seller/followers/<int:buyer_id>')
@login_required
def seller_follower_detail(buyer_id):
    if current_user.role != 'seller':
        flash('Seller access required.')
        return redirect(url_for('market'))
    follow = SellerFollow.query.filter_by(seller_id=current_user.id, buyer_id=buyer_id).first_or_404()
    buyer = db.session.get(User, buyer_id)
    viewed = ProductView.query.filter_by(viewer_id=buyer.id).order_by(ProductView.viewed_at.desc()).limit(20).all()
    viewed_product_ids = [row.product_id for row in viewed]
    products = Product.query.filter(Product.id.in_(viewed_product_ids), Product.seller_id == current_user.id).all() if viewed_product_ids else []
    product_map = {p.id: p for p in products}
    seller_views = [(product_map[row.product_id], row.viewed_at) for row in viewed if row.product_id in product_map]
    return render_template('seller_follower_detail.html', follower=buyer, followed_at=follow.created_at, seller_views=seller_views)


@app.get('/for-you')
@login_required
def for_you():
    if current_user.role != 'buyer':
        return redirect(url_for('dashboard'))
    followed_ids = [row.seller_id for row in SellerFollow.query.filter_by(buyer_id=current_user.id).all()]
    followed_products = Product.query.filter(Product.seller_id.in_(followed_ids), Product.is_sold_out.is_(False)).order_by(Product.created_at.desc(), Product.id.desc()).limit(12).all() if followed_ids else []
    excluded = {p.id for p in followed_products}
    fresh = Product.query.filter(Product.is_sold_out.is_(False), ~Product.id.in_(excluded) if excluded else True).order_by(Product.created_at.desc(), Product.id.desc()).limit(12).all()
    return render_template('for_you.html', followed_products=followed_products, fresh=fresh, following_count=len(followed_ids))


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
    placements = bootstrap.ListingPlacement.query.order_by(bootstrap.ListingPlacement.expires_at.desc()).limit(30).all()
    return render_template('admin_control.html', sellers=sellers, buyers=buyers, products=products, follows=follows, placements=placements)


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
    try:
        import email_notifications
        users = User.query.filter(User.id != current_user.id, User.email_notifications.is_(True)).all()
        for user in users:
            email_notifications.queue_email(user.id, 'admin_announcement', title, message, '/market', 'Open Merco')
        db.session.commit()
        flash(f'Email announcement queued for {len(users)} users.')
    except Exception:
        db.session.rollback()
        app.logger.exception('Admin announcement email queue failed')
        flash('The announcement could not be queued.')
    return redirect(url_for('admin_control'))
