# Merco EmailJS setup

Merco sends transactional mail through the EmailJS REST API from the Flask backend. EmailJS documents the REST endpoint as `POST https://api.emailjs.com/api/v1.0/email/send` with `service_id`, `template_id`, `user_id` (public key), `template_params`, and optional `accessToken`. The public key is safe to expose, but keep the private key server-side.

## Render environment variables

Set these on the Merco Render web service:

- `EMAILJS_SERVICE_ID` — EmailJS service ID.
- `EMAILJS_TEMPLATE_ID` — the designed Merco transactional template ID.
- `EMAILJS_VERIFICATION_TEMPLATE_ID` — optional; use this if verification has its own template. Otherwise the default template is used.
- `EMAILJS_PRODUCT_TEMPLATE_ID` — optional; use this if product-live emails have their own template. Otherwise the default template is used.
- `EMAILJS_PUBLIC_KEY` — EmailJS public key.
- `EMAILJS_PRIVATE_KEY` — optional private key/access token. Keep this secret.
- `MERCO_PUBLIC_URL` — public Merco URL, for example the Render URL.

Do not put the private key in HTML or browser JavaScript.

## EmailJS template

Create an EmailJS template and paste `docs/emailjs/merco-transactional-template.html` into its HTML content editor. Configure **To Email** as `{{to_email}}` and **Subject** as `{{subject}}`.

The template uses these variables:

`to_email`, `subject`, `name`, `preheader`, `message`, `action_url`, `action_text`, `brand_name`, `website_url`.

## Verification email

After registration, Merco generates a signed verification URL and sends it through the EmailJS verification template. The link expires after 24 hours. Seller Mode remains locked until the account is verified.

## Recommended EmailJS service

EmailJS recommends transactional email services for production/high-volume mail and personal providers mainly for development or low volume.
