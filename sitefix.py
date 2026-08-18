"""Production hardening layer for Maximise.

Render starts this module. It loads the payment-aware Flask routes, then uses
persistent database-backed image storage so seller uploads survive restarts and
redeploys on an ephemeral web service.
"""

import base64
import io
import uuid
from datetime import timedelta

from flask import Response, abort, send_from_directory
from flask_login import login_user as _flask_login_user
from PIL import Image, ImageOps
from sqlalchemy import event, inspect, text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Session

from app import app, db, Product
import bootstrap

# Keep users signed in across browser/app restarts. Render supplies SECRET_KEY
# as a persistent environment variable, so remember cookies remain valid across
# normal deployments.
app.config.update(
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE='Lax',
    REMEMBER_COOKIE_DURATION=timedelta(days=30),
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SECURE=True,
    REMEMBER_COOKIE_SAMESITE='Lax',
)

import app as app_module


def remembered_login_user(user, remember=None, duration=None, force=False, fresh=True):
    return _flask_login_user(
        user,
        remember=True,
        duration=duration or app.config['REMEMBER_COOKIE_DURATION'],
        force=force,
        fresh=fresh,
    )


app_module.login_user = remembered_login_user


class UploadedAsset(db.Model):
    __tablename__ = 'uploaded_asset'
    id = db.Column(db.Integer, primary_key=True)
    media_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    mime_type = db.Column(db.String(80), nullable=False, default='image/webp')
    data = db.Column(db.Text().with_variant(LONGTEXT(), 'mysql'), nullable=False)
    created_at = db.Column(db.DateTime, server_default=db.func.now())


with app.app_context():
    db.create_all()
    inspector = inspect(db.engine)
    if 'seller_contact' in inspector.get_table_names():
        columns = {c['name'] for c in inspector.get_columns('seller_contact')}
        if 'free_listing_used' not in columns:
            dialect = db.engine.dialect.name
            definition = 'BOOLEAN DEFAULT FALSE' if dialect != 'sqlite' else 'INTEGER DEFAULT 0'
            quoted = db.engine.dialect.identifier_preparer.quote('seller_contact')
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {quoted} ADD COLUMN free_listing_used {definition}'))


@event.listens_for(Session, 'before_flush')
def protect_marketplace_deletes(session, flush_context, instances):
    placement_model = bootstrap.ListingPlacement
    payment_model = bootstrap.ListingPayment
    contact_model = bootstrap.SellerContact

    deleted_products = [obj for obj in session.deleted if isinstance(obj, Product)]
    for product in deleted_products:
        session.query(placement_model).filter_by(product_id=product.id).delete(synchronize_session=False)
        session.query(payment_model).filter_by(product_id=product.id).update(
            {payment_model.product_id: None}, synchronize_session=False
        )

    user_model = __import__('app', fromlist=['User']).User
    deleted_users = [obj for obj in session.deleted if isinstance(obj, user_model)]
    for user in deleted_users:
        session.query(placement_model).filter_by(seller_id=user.id).delete(synchronize_session=False)
        session.query(payment_model).filter_by(seller_id=user.id).delete(synchronize_session=False)
        session.query(contact_model).filter_by(seller_id=user.id).delete(synchronize_session=False)


def persistent_save_image(file):
    if not file or not file.filename:
        return None

    extension = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if extension not in {'png', 'jpg', 'jpeg', 'webp', 'gif'}:
        raise ValueError('Only PNG, JPG, JPEG, WEBP and GIF images are allowed.')

    try:
        image = Image.open(file.stream)
        image.verify()
        file.stream.seek(0)
        image = Image.open(file.stream)
        image = ImageOps.exif_transpose(image)
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (0, 0, 0))
            background.paste(image, mask=image.getchannel('A'))
            image = background
        else:
            image = image.convert('RGB')

        encoded = None
        for quality in (78, 68, 58, 48):
            output = io.BytesIO()
            image.save(output, format='WEBP', quality=quality, method=6)
            payload = output.getvalue()
            if len(payload) <= 1024 * 1024:
                encoded = base64.b64encode(payload).decode('ascii')
                break
        if encoded is None:
            raise ValueError('That image is too large after compression. Please choose a smaller image.')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('That image could not be processed. Please choose another image.') from exc

    try:
        asset = UploadedAsset(media_key=uuid.uuid4().hex, mime_type='image/webp', data=encoded)
        db.session.add(asset)
        db.session.flush()
        return f'/media/{asset.media_key}'
    except Exception as exc:
        db.session.rollback()
        raise ValueError('The image could not be saved. Please try again with a smaller image.') from exc


bootstrap.save_image = persistent_save_image
app_module.save_image = persistent_save_image


@app.get('/media/<media_key>')
def media_asset(media_key):
    asset = UploadedAsset.query.filter_by(media_key=media_key).first()
    if not asset:
        abort(404)
    try:
        payload = base64.b64decode(asset.data, validate=True)
    except Exception:
        abort(404)
    return Response(payload, mimetype=asset.mime_type, headers={
        'Cache-Control': 'public, max-age=31536000, immutable'
    })


@app.get('/sw.js')
def service_worker():
    """Serve the worker from / so it can control the whole Maximise origin."""
    return send_from_directory(app.static_folder, 'sw.js', mimetype='application/javascript',
                               max_age=0, conditional=False)


# Social/follow/notification features are loaded after the payment layer so
# their models and routes share the same production database and Flask app.
import social  # noqa: E402,F401


@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    app.logger.exception('Unhandled Maximise server error: %s', error)
    return (
        '<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Maximise · Something went wrong</title><style>'
        'body{margin:0;background:#050505;color:#f5f0e6;font:16px system-ui,sans-serif;display:grid;place-items:center;min-height:100vh}'
        '.box{max-width:620px;padding:42px;border:1px solid rgba(212,175,55,.25);border-radius:24px;background:rgba(255,255,255,.04);text-align:center}'
        'h1{color:#d4af37}p{color:#aaa;line-height:1.7}a{color:#d4af37}'
        '</style></head><body><div class="box"><h1>Maximise is recovering</h1>'
        '<p>Something went wrong while loading this page. Your account and marketplace data are safe. Please refresh and try again.</p>'
        '<a href="/market">Return to Market</a></div></body></html>', 500
    )


application = app
