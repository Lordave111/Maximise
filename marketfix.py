from flask import render_template, request
import threading

from app import app, Product, Category, User
import bootstrap


def responsive_market():
    search = request.args.get('search', '').strip()
    category_id = request.args.get('category', type=int)
    page = max(request.args.get('page', 1, type=int), 1)
    requested_size = request.args.get('page_size', type=int)
    page_size = requested_size if requested_size in (8, 12, 16) else 12

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


# Replace only the original marketplace view while keeping its existing
# endpoint name and all existing links/forms intact.
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


# seller_page in app.py predates the contact-aware storefront template. Keep
# the same endpoint but supply the contact object the template expects.
app.view_functions['seller_page'] = fixed_seller_page


# email_notifications registers a synchronous after_request sender. That made
# unrelated pages wait on the mail provider. Remove that hook and process the
# queue in one background worker instead.
try:
    import email_notifications

    for _after_fn in list(app.after_request_funcs.get(None, [])):
        if getattr(_after_fn, '__name__', '') == 'process_one_email_after_request':
            app.after_request_funcs[None].remove(_after_fn)

    _EMAIL_WORKER_LOCK = threading.Lock()

    def _process_email_queue_background():
        if not _EMAIL_WORKER_LOCK.acquire(blocking=False):
            return
        try:
            email_notifications.process_email_queue(limit=3)
        except Exception:
            app.logger.exception('Background email queue processing failed')
        finally:
            _EMAIL_WORKER_LOCK.release()

    def _email_worker_loop():
        stop = threading.Event()
        app.extensions['merco_email_worker_stop'] = stop
        while not stop.wait(15):
            _process_email_queue_background()

    if not app.extensions.get('merco_email_worker_started'):
        app.extensions['merco_email_worker_started'] = True
        threading.Thread(target=_email_worker_loop, name='merco-email-worker', daemon=True).start()
except Exception:
    app.logger.exception('Could not start background email worker')