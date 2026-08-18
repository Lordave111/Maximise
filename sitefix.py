"""Production hardening layer for Maximise.

Render starts this module. It loads the payment-aware Flask routes, then uses
persistent database-backed image storage so seller uploads survive restarts and
redeploys on an ephemeral web service.
"""

import base64
import io
import uuid

from flask import Response, abort
from PIL import Image, ImageOps
from sqlalchemy import inspect, text
from sqlalchemy.dialects.mysql import LONGTEXT

from app import app, db
import bootstrap


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


def persistent_save_image(file):
    if not file or not file.filename:
        return None

    original = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if original not in {'png', 'jpg', 'jpeg', 'webp', 'gif'}:
        raise ValueError('Only PNG, JPG, JPEG, WEBP and GIF images are allowed.')

    try:
        image = Image.open(file.stream)
        image = ImageOps.exif_transpose(image)
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (0, 0, 0))
            background.paste(image, mask=image.getchannel('A'))
            image = background
        else:
            image = image.convert('RGB')

        output = io.BytesIO()
        image.save(output, format='WEBP', quality=82, method=6)
        encoded = base64.b64encode(output.getvalue()).decode('ascii')
    except Exception as exc:
        raise ValueError('That image could not be processed. Please choose another image.') from exc

    asset = UploadedAsset(media_key=uuid.uuid4().hex, mime_type='image/webp', data=encoded)
    db.session.add(asset)
    db.session.flush()
    return f'/media/{asset.media_key}'


# Both payment-aware and legacy upload handlers resolve save_image at runtime.
bootstrap.save_image = persistent_save_image
import app as app_module
app_module.save_image = persistent_save_image


@app.get('/media/<media_key>')
def media_asset(media_key):
    asset = UploadedAsset.query.filter_by(media_key=media_key).first()
    if not asset:
        abort(404)
    try:
        payload = base64.b64decode(asset.data)
    except Exception:
        abort(404)
    return Response(payload, mimetype=asset.mime_type, headers={
        'Cache-Control': 'public, max-age=31536000, immutable'
    })


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
