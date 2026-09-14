from flask import render_template, request, abort

from app import app, Product, Category, User
import bootstrap


PAGE_SIZE = 12


def _market_context():
    search = request.args.get('search', '').strip()
    category_id = request.args.get('category', type=int)
    page = max(request.args.get('page', 1, type=int), 1)

    query = Product.query.filter_by(is_sold_out=False).order_by(
        Product.created_at.desc(), Product.id.desc()
    )
    if search:
        query = query.filter(
            Product.name.ilike(f'%{search}%') |
            Product.description.ilike(f'%{search}%')
        )
    if category_id:
        query = query.filter_by(category_id=category_id)

    total = query.count()
    pagination = query.paginate(page=page, per_page=PAGE_SIZE, error_out=False)
    return dict(
        products=pagination.items,
        pagination=pagination,
        total_products=total,
        categories=Category.query.order_by(Category.name.asc()).all(),
        search=search,
        selected_category=category_id,
        page_size=PAGE_SIZE,
    )


def responsive_market():
    # Explicitly return only one page of products. This replaces the original
    # route even if app.py is imported directly rather than through a named
    # route wrapper.
    return render_template('market.html', **_market_context())


app.view_functions['market'] = responsive_market


# Hard guarantee: if Flask's original market endpoint is ever re-registered by
# another feature module, this request handler still prevents all 150 listings
# from being rendered into a single response.
@app.before_request
def force_market_pagination():
    if request.path != '/market':
        return None
    return render_template('market.html', **_market_context())


def _seller_store_response(seller_slug):
    seller = User.query.filter_by(seller_slug=seller_slug, role='seller').first()
    if not seller:
        abort(404)

    products = Product.query.filter_by(
        seller_id=seller.id, is_sold_out=False
    ).order_by(Product.created_at.desc(), Product.id.desc()).all()

    try:
        contact = bootstrap.get_contact(seller)
    except Exception:
        app.logger.exception('Seller contact lookup failed for seller %s', seller.id)
        contact = type('SellerContactFallback', (), {
            'public_email': seller.email or '',
            'phone_number': '',
        })()

    return render_template(
        'seller_page.html',
        seller=seller,
        products=products,
        contact=contact,
    )


def fixed_seller_page(seller_slug):
    return _seller_store_response(seller_slug)


app.view_functions['seller_page'] = fixed_seller_page


# Also expose a clean canonical store URL. Existing /seller/<slug> links remain
# valid, while /store/<slug> avoids conflicts with authenticated seller tools.
@app.get('/store/<seller_slug>', endpoint='public_store')
def public_store(seller_slug):
    return _seller_store_response(seller_slug)


# Email queue processing is owned by merco_runtime.py. No SMTP work is done in
# marketplace/store requests.
