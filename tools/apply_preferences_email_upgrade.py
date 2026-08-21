from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app = ROOT / 'app.py'
base = ROOT / 'templates' / 'base.html'
s = app.read_text(encoding='utf-8')

# Imports
s = s.replace('import uuid\n', 'import uuid\nimport smtplib\nfrom email.message import EmailMessage\n')
s = s.replace('from werkzeug.utils import secure_filename\n', 'from werkzeug.utils import secure_filename\nfrom itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired\n')

# User preferences and email verification state.
needle = "    seller_slug = db.Column(db.String(120), unique=True)\n"
if 'preferred_language' not in s:
    s = s.replace(needle, needle + "    preferred_language = db.Column(db.String(10), default='auto', nullable=False)\n    preferred_currency = db.Column(db.String(3), default='NGN', nullable=False)\n    email_verified = db.Column(db.Boolean, default=False, nullable=False)\n    email_notifications = db.Column(db.Boolean, default=True, nullable=False)\n")

# Schema migration for existing databases.
marker = "        if 'product' in tables and 'created_at' not in {c['name'] for c in inspector.get_columns('product')}:\n            column_type = 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME'\n            conn.execute(text(f'ALTER TABLE {quote_name(\"product\")} ADD COLUMN created_at {column_type}'))\n"
if 'preferred_currency' not in s[s.find('def migrate_schema'):s.find('def initialize_database')]:
    extra = marker + "        if 'user' in tables:\n            user_columns = {c['name'] for c in inspector.get_columns('user')}\n            if 'preferred_language' not in user_columns:\n                conn.execute(text(f\"ALTER TABLE {quote_name('user')} ADD COLUMN preferred_language VARCHAR(10) NOT NULL DEFAULT 'auto'\"))\n            if 'preferred_currency' not in user_columns:\n                conn.execute(text(f\"ALTER TABLE {quote_name('user')} ADD COLUMN preferred_currency VARCHAR(3) NOT NULL DEFAULT 'NGN'\"))\n            if 'email_verified' not in user_columns:\n                conn.execute(text(f\"ALTER TABLE {quote_name('user')} ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT FALSE\"))\n                conn.execute(text(f\"UPDATE {quote_name('user')} SET email_verified = TRUE\"))\n            if 'email_notifications' not in user_columns:\n                conn.execute(text(f\"ALTER TABLE {quote_name('user')} ADD COLUMN email_notifications BOOLEAN NOT NULL DEFAULT TRUE\"))\n"
    s = s.replace(marker, extra)

# Mail helpers.
anchor = "def initialize_database():\n"
helpers = '''SUPPORTED_LANGUAGES = {\n    'en': 'English', 'fr': 'Français', 'es': 'Español', 'pt': 'Português',\n    'ar': 'العربية', 'ha': 'Hausa', 'yo': 'Yorùbá'\n}\nSUPPORTED_CURRENCIES = {\n    'NGN': '₦ Nigerian Naira', 'USD': '$ US Dollar', 'GBP': '£ British Pound',\n    'EUR': '€ Euro', 'GHS': '₵ Ghanaian Cedi', 'KES': 'KSh Kenyan Shilling', 'ZAR': 'R South African Rand'\n}\n\ndef _serializer():\n    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='maximise-email-verification')\n\ndef make_verification_token(user):\n    return _serializer().dumps({'id': user.id, 'email': user.email})\n\ndef send_email(to_email, subject, text_body, html_body=None):\n    host = os.environ.get('SMTP_HOST', '').strip()\n    port = int(os.environ.get('SMTP_PORT', '587') or 587)\n    username = os.environ.get('SMTP_USERNAME', '').strip()\n    password = os.environ.get('SMTP_PASSWORD', '')\n    sender = os.environ.get('MAIL_FROM', username).strip()\n    if not host or not sender:\n        app.logger.warning('SMTP is not configured; email not sent to %s', to_email)\n        return False\n    message = EmailMessage()\n    message['From'] = sender\n    message['To'] = to_email\n    message['Subject'] = subject\n    message.set_content(text_body)\n    if html_body:\n        message.add_alternative(html_body, subtype='html')\n    try:\n        with smtplib.SMTP(host, port, timeout=15) as smtp:\n            if os.environ.get('SMTP_TLS', '1').lower() not in {'0', 'false', 'no'}:\n                smtp.starttls()\n            if username and password:\n                smtp.login(username, password)\n            smtp.send_message(message)\n        return True\n    except Exception:\n        app.logger.exception('SMTP delivery failed for %s', to_email)\n        return False\n\ndef send_verification_email(user):\n    token = make_verification_token(user)\n    link = url_for('verify_email', token=token, _external=True)\n    return send_email(\n        user.email, 'Verify your Maximise email',\n        f'Hi {user.username},\\n\\nVerify your email to unlock Seller Mode on Maximise:\\n{link}\\n\\nThis link expires in 24 hours.',\n        f'<div style="font-family:Arial,sans-serif"><h2>Verify your Maximise email</h2><p>Hi {user.username},</p><p>Verify your email to unlock Seller Mode.</p><p><a href="{link}" style="display:inline-block;padding:12px 18px;background:#d4af62;color:#080705;text-decoration:none;border-radius:10px;font-weight:700">Verify email</a></p><p>This link expires in 24 hours.</p></div>'\n    )\n\n'''
if 'SUPPORTED_LANGUAGES' not in s:
    s = s.replace(anchor, helpers + anchor)

# Registration sends verification mail; seller mode remains locked until verified.
old = "        db.session.add(User(username=username, email=email, password=generate_password_hash(password), role='buyer'))\n        db.session.commit()\n        flash('Account created. You can become a seller anytime from Settings.')\n        return redirect(url_for('login'))\n"
new = "        user = User(username=username, email=email, password=generate_password_hash(password), role='buyer', email_verified=False)\n        db.session.add(user)\n        db.session.commit()\n        sent = send_verification_email(user)\n        flash('Account created. Check your email to verify it before opening a seller store.' if sent else 'Account created, but email delivery is not configured yet. Ask the administrator to configure SMTP verification.')\n        return redirect(url_for('login'))\n"
s = s.replace(old, new)

old = "        if action == 'become_seller' and current_user.role == 'buyer':\n            seller_name = (request.form.get('seller_name') or current_user.username).strip()[:100]\n"
new = "        if action == 'become_seller' and current_user.role == 'buyer':\n            if not current_user.email_verified:\n                send_verification_email(current_user)\n                flash('Verify your email before opening your seller store. A fresh verification link has been sent if SMTP is configured.')\n                return redirect(url_for('settings'))\n            seller_name = (request.form.get('seller_name') or current_user.username).strip()[:100]\n"
s = s.replace(old, new)

# Preferences action in existing settings route.
old = "    if request.method == 'POST':\n        action = request.form.get('action')\n        if action == 'become_seller'"
new = "    if request.method == 'POST':\n        action = request.form.get('action')\n        if action == 'preferences':\n            language = request.form.get('language', 'auto').strip().lower()\n            currency = request.form.get('currency', 'NGN').strip().upper()\n            if language != 'auto' and language not in SUPPORTED_LANGUAGES: language = 'auto'\n            if currency not in SUPPORTED_CURRENCIES: currency = 'NGN'\n            current_user.preferred_language = language\n            current_user.preferred_currency = currency\n            current_user.email_notifications = request.form.get('email_notifications') == '1'\n            db.session.commit()\n            flash('Language, currency and email preferences saved.')\n            return redirect(url_for('settings'))\n        if action == 'become_seller'"
s = s.replace(old, new)

# Expose preference lists to templates.
s = s.replace("    return {'market_categories': categories}\n", "    return {'market_categories': categories, 'supported_languages': SUPPORTED_LANGUAGES, 'supported_currencies': SUPPORTED_CURRENCIES}\n", 1)

# Verification routes.
route_anchor = "@app.get('/logout')\n"
routes = '''@app.get('/verify-email/<token>')\ndef verify_email(token):\n    try:\n        data = _serializer().loads(token, max_age=86400)\n        user = User.query.filter_by(id=int(data['id']), email=data['email']).first_or_404()\n    except (BadSignature, SignatureExpired, ValueError, TypeError):\n        flash('That verification link is invalid or has expired. Please request a new one.')\n        return redirect(url_for('login'))\n    user.email_verified = True\n    db.session.commit()\n    flash('Email verified successfully. You can now open a seller store.')\n    return redirect(url_for('login'))\n\n@app.get('/verify-email')\n@login_required\ndef verify_email_notice():\n    if current_user.email_verified:\n        return redirect(url_for('settings'))\n    return render_template('verify_email.html')\n\n@app.post('/verify-email/resend')\n@login_required\ndef resend_verification():\n    if current_user.email_verified:\n        flash('Your email is already verified.')\n    elif send_verification_email(current_user):\n        flash('A new verification email has been sent.')\n    else:\n        flash('Email delivery is not configured. Please contact the site administrator.')\n    return redirect(url_for('verify_email_notice'))\n\n'''
if "@app.get('/verify-email/<token>')" not in s:
    s = s.replace(route_anchor, routes + route_anchor)

# Unverified sellers cannot access their seller dashboard.
s = s.replace("def seller_dashboard():\n    if current_user.role != 'seller':\n", "def seller_dashboard():\n    if current_user.role == 'seller' and not current_user.email_verified:\n        return redirect(url_for('verify_email_notice'))\n    if current_user.role != 'seller':\n")

# Confirmation email after successful seller listing.
old = "            db.session.commit()\n            flash('Product published to the marketplace.')\n            return redirect(url_for('seller_dashboard'))\n"
new = "            db.session.commit()\n            if current_user.email_notifications:\n                send_email(current_user.email, 'Your Maximise product is live', f'Your product {name} has been published to the marketplace.', f'<p>Your product <strong>{name}</strong> is now live on Maximise.</p>')\n            flash('Product published to the marketplace. A confirmation email was sent if notifications are enabled.')\n            return redirect(url_for('seller_dashboard'))\n"
s = s.replace(old, new)

app.write_text(s, encoding='utf-8')

# Load client-side language/currency controls on every page.
b = base.read_text(encoding='utf-8')
if 'preferences.js' not in b:
    b = b.replace('{% block scripts %}{% endblock %}', '<script src="{{ url_for(\'static\', filename=\'preferences.js\') }}"></script>\n{% block scripts %}{% endblock %}')
base.write_text(b, encoding='utf-8')
print('Applied preferences + email verification upgrade')
