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
    return _flask_login_user(user, remember=True, duration=duration or app.config['REMEMBER_COOKIE_DURATION'], force=force, fresh=fresh)


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
    social_module = __import__('social')
    follow_model = social_module.SellerFollow
    notification_model = social_module.Notification

    deleted_products = [obj for obj in session.deleted if isinstance(obj, Product)]
    for product in deleted_products:
        session.query(placement_model).filter_by(product_id=product.id).delete(synchronize_session=False)
        session.query(payment_model).filter_by(product_id=product.id).update({payment_model.product_id: None}, synchronize_session=False)

    user_model = __import__('app', fromlist=['User']).User
    deleted_users = [obj for obj in session.deleted if isinstance(obj, user_model)]
    for user in deleted_users:
        session.query(follow_model).filter((follow_model.buyer_id == user.id) | (follow_model.seller_id == user.id)).delete(synchronize_session=False)
        session.query(notification_model).filter_by(user_id=user.id).delete(synchronize_session=False)
        session.query(contact_model).filter_by(seller_id=user.id).delete(synchronize_session=False)


def _decode_data_url(value):
    if not value:
        return None, None
    try:
        header, payload = value.split(',', 1)
        mime = header.split(';', 1)[0].split(':', 1)[-1].strip() or 'image/webp'
        return mime, base64.b64decode(payload, validate=True)
    except Exception:
        return None, None


def _store_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    raw = file_storage.read()
    if not raw:
        return None
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Image is too large. Please choose an image under 8 MB.')
    try:
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            quality = 84
            while True:
                output = io.BytesIO()
                image.save(output, format='WEBP', quality=quality, method=6)
                if output.tell() <= 1024 * 1024 or quality <= 50:
                    break
                quality -= 7
            encoded = base64.b64encode(output.getvalue()).decode('ascii')
    except Exception as exc:
        raise ValueError('The uploaded image could not be processed. Please use a JPG or PNG image.') from exc
    asset = UploadedAsset(media_key=uuid.uuid4().hex, mime_type='image/webp', data=encoded)
    db.session.add(asset)
    db.session.flush()
    return asset.media_key


def _store_images(files):
    keys = []
    for file_storage in files or []:
        key = _store_image(file_storage)
        if key:
            keys.append(key)
    return keys


def _media_response(media_key):
    asset = UploadedAsset.query.filter_by(media_key=media_key).first_or_404()
    try:
        payload = base64.b64decode(asset.data, validate=True)
    except Exception:
        abort(404)
    return Response(payload, mimetype=asset.mime_type, headers={'Cache-Control': 'public, max-age=31536000, immutable'})


@app.get('/media/<media_key>')
def media(media_key):
    return _media_response(media_key)


@app.get('/uploads/<path:filename>')
def legacy_upload(filename):
    # Keep old templates/links working where a legacy file exists.
    return send_from_directory('static/uploads', filename)


# IMPORTANT: Render starts `sitefix:app`, so modules that register routes must
# be imported here. Importing only bootstrap leaves /seller/followers and
# /seller/insights unregistered, which produces a 404 even though their route
# functions exist in the source tree.
import social  # noqa: E402,F401
import seller_features  # noqa: E402,F401
