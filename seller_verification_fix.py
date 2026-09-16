"""Simple seller verification for Merco.

Seller Mode no longer requires WhatsApp Cloud API, email verification, or
customer-care API messaging. The seller request generates a signed link that
is valid for five minutes. Opening the link directly activates the account.
"""
import hashlib
import html
import os
from urllib.parse import quote

from flask import flash, redirect, request, url_for
from flask_login import current_user
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import text

import merco_runtime
from sitefix import app
import app as app_module
import bootstrap

SELLER_VERIFICATION_MAX_AGE = 300
SELLER_TOKEN_SALT = "merco-seller-whatsapp-v3"


def _seller_serializer():
    configured = (os.environ.get("SECRET_KEY") or "").strip()
    if configured:
        key = configured
    else:
        database_url = (os.environ.get("DATABASE_URL") or "").strip()
        seed = database_url or "merco-local-seller-verification"
        key = hashlib.sha256(("merco-local-seller-key-v3:" + seed).encode("utf-8")).hexdigest()
    return URLSafeTimedSerializer(key, salt=SELLER_TOKEN_SALT)


def _token(user):
    return _seller_serializer().dumps({
        "id": int(user.id),
        "whatsapp": "".join(ch for ch in (user.pending_seller_whatsapp or "") if ch.isdigit()),
        "purpose": "seller-whatsapp",
    })


def _verification_url(user):
    base = (os.environ.get("MERCO_PUBLIC_URL") or "https://maximise-production.up.railway.app").rstrip("/")
    return f"{base}/verify-seller-whatsapp/{_token(user)}"


def _link_page(link, seller_name):
    safe_link = html.escape(link, quote=True)
    safe_name = html.escape(seller_name or "Seller")
    return f'''<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Verify Seller · Merco</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#050a08;color:#e0f2f1;font-family:Arial,sans-serif}}main{{width:min(92%,520px);box-sizing:border-box;padding:28px;border:1px solid rgba(0,255,136,.25);border-radius:22px;background:#0a1912;text-align:center}}a.btn,button{{display:inline-block;border:0;border-radius:12px;padding:14px 20px;background:#00ff88;color:#04100a;font-weight:700;text-decoration:none;cursor:pointer}}.link{{margin:18px 0;padding:12px;border-radius:10px;background:#06110b;color:#9ee8c5;word-break:break-all;font-size:13px;text-align:left}}p{{color:#a8c0ba;line-height:1.6}}</style></head>
<body><main><div style="font-size:48px;color:#00ff88">✓</div><h1>Verify your seller account</h1>
<p>Hi {safe_name}. Your secure verification link is ready. Open it within <b>5 minutes</b> to activate Seller Mode and your store.</p>
<p class="link">{safe_link}</p>
<a class="btn" href="{safe_link}">Verify &amp; Open My Store</a>
<p style="font-size:12px;margin-top:18px">No WhatsApp API and no email verification are required for Seller Mode.</p>
</main></body></html>'''


def _activate_seller_fixed():
    if not current_user.is_authenticated:
        return redirect(url_for("login"))
    if current_user.role != "buyer":
        return redirect(url_for("dashboard"))
    try:
        seller_name = (request.form.get("seller_name") or current_user.username or "Merco Seller").strip()[:100]
        public_email = (request.form.get("contact_email") or current_user.email or "").strip()[:160]
        phone = (request.form.get("phone_number") or "").strip()[:40]
        whatsapp = "".join(ch for ch in (request.form.get("whatsapp") or "").strip() if ch.isdigit())[:30]
        if not seller_name or not public_email or "@" not in public_email or not phone or not whatsapp:
            raise ValueError("Seller name, public email, phone and WhatsApp are required.")

        bootstrap.save_contact(current_user, public_email, phone, require_phone=True)
        current_user.pending_seller_name = seller_name
        current_user.pending_seller_email = public_email
        current_user.pending_seller_phone = phone
        current_user.pending_seller_whatsapp = whatsapp
        current_user.seller_verification_status = "pending"
        current_user.seller_verified = False
        app_module.db.session.commit()

        return _link_page(_verification_url(current_user), seller_name)
    except ValueError as exc:
        app_module.db.session.rollback()
        flash(str(exc))
        return redirect(url_for("settings"))
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception("Seller verification request failed")
        flash("Seller verification could not be started. Please try again.")
        return redirect(url_for("settings"))


def _load_token(token):
    try:
        return _seller_serializer().loads(token, max_age=SELLER_VERIFICATION_MAX_AGE)
    except SignatureExpired:
        raise
    except BadSignature as stable_error:
        # Accept links from the immediately preceding implementation while
        # they are still within their original five-minute lifetime.
        try:
            return app_module._serializer().loads(token, max_age=SELLER_VERIFICATION_MAX_AGE)
        except Exception:
            raise stable_error


def _success_page(name):
    safe_name = html.escape(name or "Seller")
    return f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Seller verified · Merco</title>
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#050a08;color:#e0f2f1;font-family:Arial,sans-serif}}main{{max-width:520px;margin:24px;padding:32px;border:1px solid rgba(0,255,136,.28);border-radius:22px;background:#0a1912;text-align:center}}a{{display:inline-block;margin-top:12px;padding:13px 20px;border-radius:12px;background:#00ff88;color:#04100a;text-decoration:none;font-weight:700}}</style></head><body><main><div style="font-size:54px;color:#00ff88">✓</div><h1>Seller verified</h1><p>Welcome, {safe_name}. Your seller account is active and your store is ready.</p><a href="/login">Log in to your store</a></main></body></html>'''


def _verify_seller_whatsapp_fixed(token):
    """Activate Seller Mode directly from the signed five-minute link.

    A direct SQL UPDATE is intentionally used here. Updating User through the
    ORM fires account-lifecycle notification listeners, which can fail when a
    legacy notification/push table is being repaired. Seller verification must
    not depend on notifications being configured correctly.
    """
    try:
        data = _load_token(token)
        if data.get("purpose") != "seller-whatsapp":
            raise BadSignature()

        user_id = int(data["id"])
        token_whatsapp = "".join(ch for ch in str(data.get("whatsapp") or "") if ch.isdigit())
        if not token_whatsapp:
            raise BadSignature()

        user = app_module.User.query.filter_by(id=user_id).first()
        if not user:
            raise BadSignature()

        stored_whatsapp = "".join(ch for ch in (user.pending_seller_whatsapp or "") if ch.isdigit())
        if user.role == "seller" and bool(user.seller_verified):
            return _success_page(user.username or "Seller")

        if user.role != "buyer" or user.seller_verification_status != "pending" or stored_whatsapp != token_whatsapp:
            return _success_page(user.username or "Seller") if user.role == "seller" and bool(user.seller_verified) else (
                "<html><body style='font-family:Arial;background:#050a08;color:#e0f2f1;padding:40px;text-align:center'><h1>Link no longer valid</h1><p>Please start Seller Mode again to get a new 5-minute link.</p><a href='/login' style='color:#00ff88'>Log in</a></body></html>"
            )

        seller_name = (user.pending_seller_name or user.username or "Merco Seller").strip()[:100]
        slug_base = app_module.slugify(seller_name) or "seller"
        seller_slug = f"{slug_base}-{user.id}"[:120]

        # Bypass ORM lifecycle events so a notification/push schema problem can
        # never roll back the actual seller activation.
        table = app_module.db.engine.dialect.identifier_preparer.quote("user")
        statement = text(f"""
            UPDATE {table}
            SET role=:role,
                username=:username,
                seller_slug=:seller_slug,
                whatsapp_number=:whatsapp_number,
                seller_verified=:seller_verified,
                seller_verification_status=:seller_verification_status,
                pending_seller_name=NULL,
                pending_seller_email=NULL,
                pending_seller_phone=NULL,
                pending_seller_whatsapp=NULL
            WHERE id=:id AND role='buyer' AND seller_verification_status='pending'
        """)
        result = app_module.db.session.execute(statement, {
            "role": "seller",
            "username": seller_name,
            "seller_slug": seller_slug,
            "whatsapp_number": user.pending_seller_whatsapp,
            "seller_verified": True,
            "seller_verification_status": "verified",
            "id": user.id,
        })
        if result.rowcount != 1:
            raise RuntimeError("Seller account could not be activated.")
        app_module.db.session.commit()
        app.logger.info("Seller verification completed directly for user_id=%s", user.id)
        return _success_page(seller_name)

    except SignatureExpired:
        app_module.db.session.rollback()
        return "<html><body style='font-family:Arial;background:#050a08;color:#e0f2f1;padding:40px;text-align:center'><h1>Verification link expired</h1><p>Start Seller Mode again to generate a new 5-minute link.</p><a href='/login' style='color:#00ff88'>Log in</a></body></html>", 410
    except (BadSignature, ValueError, TypeError, KeyError):
        app_module.db.session.rollback()
        return "<html><body style='font-family:Arial;background:#050a08;color:#e0f2f1;padding:40px;text-align:center'><h1>Invalid verification link</h1><p>Start Seller Mode again to generate a new link.</p><a href='/login' style='color:#00ff88'>Log in</a></body></html>", 400
    except Exception:
        app_module.db.session.rollback()
        app.logger.exception("Seller verification failed")
        return "<html><body style='font-family:Arial;background:#050a08;color:#e0f2f1;padding:40px;text-align:center'><h1>Verification failed</h1><p>Please generate a new Seller Mode link and try again.</p><a href='/login' style='color:#00ff88'>Log in</a></body></html>", 500


merco_runtime._activate_seller = _activate_seller_fixed
app.view_functions["verify_seller_whatsapp"] = _verify_seller_whatsapp_fixed
app.view_functions["activate_seller_production"] = _activate_seller_fixed
