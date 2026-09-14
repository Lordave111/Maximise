from flask import render_template, request

from app import app, Product, Category, User
import bootstrap


def responsive_market():
    search = request.args.get('search', '').strip()
    category_id = request.args.get('category', type=int)
    page = max(request.args.get('page', 1, type=int), 1)

    # Server-side pagination: only 12 products are sent to the browser per page.
    # The full catalogue is never rendered into the page at once.
    page_size = 12

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
    pagination = query.paginate(page=page, per_page=page_size, error_out=False)

    return render_template(
        'market.html',
        products=pagination.items,
        pagination=pagination,
        total_products=total,
        categories=Category.query.order_by(Category.name.asc()).all(),
        search=search,
        selected_category=category_id,
        page_size=page_size,
    )


app.view_functions['market'] = responsive_market


def fixed_seller_page(seller_slug):
    seller = User.query.filter_by(seller_slug=seller_slug, role='seller').first_or_404()
    products = Product.query.filter_by(
        seller_id=seller.id, is_sold_out=False
    ).order_by(Product.created_at.desc(), Product.id.desc()).all()
    return render_template(
        'seller_page.html',
        seller=seller,
        products=products,
        contact=bootstrap.get_contact(seller),
    )


app.view_functions['seller_page'] = fixed_seller_page

# Email queue processing is owned by merco_runtime.py. Do not start another
# worker here: two workers can race over the same pending SMTP jobs.
