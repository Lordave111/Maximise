"""HTTPS email transport for Railway deployments.

Railway disables outbound SMTP on Free/Trial/Hobby plans. This module keeps
Merco's existing email queue and switches delivery to Resend's HTTPS API when
RESEND_API_KEY is configured. SMTP remains available as a fallback for plans
where outbound SMTP is enabled.
"""
import os

import requests

import email_notifications


RESEND_API_URL = "https://api.resend.com/emails"
RESEND_API_KEY = (os.environ.get("RESEND_API_KEY") or "").strip()
RESEND_FROM_EMAIL = (
    os.environ.get("RESEND_FROM_EMAIL")
    or os.environ.get("SMTP_FROM_EMAIL")
    or "onboarding@resend.dev"
).strip()
RESEND_FROM_NAME = (
    os.environ.get("RESEND_FROM_NAME")
    or os.environ.get("SMTP_FROM_NAME")
    or "Merco"
).strip()


def _resend_send(to_email, subject, message, *, name="", action_url="", action_text="Open Merco", html_body=None):
    if not RESEND_API_KEY:
        return email_notifications._smtp_send_original(
            to_email,
            subject,
            message,
            name=name,
            action_url=action_url,
            action_text=action_text,
            html_body=html_body,
        )

    if not to_email or "@" not in to_email:
        email_notifications.app.logger.error("Email API refused invalid recipient: %s", to_email)
        return False

    body_html = html_body or email_notifications._html_message(
        message, action_url, action_text, name
    )
    payload = {
        "from": f"{RESEND_FROM_NAME} <{RESEND_FROM_EMAIL}>",
        "to": [to_email],
        "subject": subject[:180],
        "html": body_html,
        "text": message[:10000],
    }

    try:
        response = requests.post(
            RESEND_API_URL,
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=20,
        )
        if 200 <= response.status_code < 300:
            data = response.json() if response.content else {}
            email_notifications.app.logger.info(
                "Email API delivered email to %s (id=%s)",
                to_email,
                data.get("id", "unknown"),
            )
            return True

        # Do not log the API key. Resend's response normally contains a useful
        # validation/authentication message, so keep that in the deployment log.
        detail = response.text[:500]
        email_notifications.app.logger.error(
            "Email API rejected message to %s with HTTP %s: %s",
            to_email,
            response.status_code,
            detail,
        )
        return False
    except requests.RequestException as exc:
        email_notifications.app.logger.error(
            "Email API request failed for %s: %s", to_email, exc
        )
        return False


# Preserve the original SMTP transport so it can still be used if no API key
# is configured or if the project is moved to Railway Pro.
email_notifications._smtp_send_original = email_notifications.send_smtp
email_notifications.send_smtp = _resend_send
