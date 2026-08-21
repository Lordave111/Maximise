import os
import re
import uuid
import smtplib
from email.message import EmailMessage
from urllib.parse import quote, parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or os.urandom(32)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.environ.get('UPLOAD_FOLDER', os.path.join(os.getcwd(), 'static', 'uploads'))


def get_database_url():
    value = (os.environ.get('DATABASE_URL') or '').strip()
    # Render users sometimes paste a quoted connection string. Remove only one
    # matching pair so the actual SQLAlchemy URL is never polluted by quotes.
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1].strip()
    if not value:
        return 'sqlite:///maximise.db'
    if value.startswith('postgres://'):
        return value.replace('postgres://', 'postgresql+psycopg://', 1)
    if value.startswith('postgresql://') and '+psycopg' not in value:
        return value.replace('postgresql://', 'postgresql+psycopg://', 1)
    if value.startswith('mysql://'):
        value = value.replace('mysql://', 'mysql+pymysql://', 1)
    if value.startswith('mysql+pymysql://'):
        # Aiven commonly supplies ssl-mode=REQUIRED. That parameter is a MySQL
        # CLI option and is not accepted by PyMySQL's connect(). Remove all
        # common spellings from the URL and enable TLS through connect_args.
        parsed = urlsplit(value)
        query = []
        for key, val in parse_qsl(parsed.query, keep_blank_values=True):
            normalized = key.lower().replace('_', '-')
            if normalized in {'ssl-mode', 'sslmode'}:
                continue
            query.append((key, val))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return value


DATABASE_URL = get_database_url()
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
engine_options = {'pool_pre_ping': True, 'pool_recycle': 280}
if DATABASE_URL.startswith('mysql+pymysql://'):
    engine_options['connect_args'] = {'ssl': {}}
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please sign in to continue.'

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
DEFAULT_CATEGORIES = ['Electronics', 'Fashion', 'Home & Living', 'Beauty', 'Phones & Accessories', 'Computers', 'Gaming', 'Vehicles', 'Books', 'Services', 'Other']


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='buyer', nullable=False)
    whatsapp_number = db.Column(db.String(30))
    seller_slug = db.Column(db.String(120), unique=True)
    preferred_language = db.Column(db.String(10), default='auto', nullable=False)
    preferred_currency = db.Column(db.String(3), default='NGN', nullable=False)
    email_verified = db.Column(db.Boolean, default=False, nullable=False)
    email_notifications = db.Column(db.Boolean, default=True, nullable=False)
    products = db.relationship('Product', backref='seller', lazy=True, cascade='all, delete-orphan')


class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    products = db.relationship('Product', backref='category', lazy=True)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    price = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text)
    cover_image = db.Column(db.String(300))
    screenshots = db.Column(db.Text)
    is_sold_out = db.Column(db.Boolean, default=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'))
    created_at = db.Column(db.DateTime, server_default=db.func.now())


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def slugify(value):
    value = re.sub(r'[^a-zA-Z0-9]+', '-', value.strip().lower()).strip('-')
    return value or 'seller'


def unique_seller_slug(name, user_id=None):
    base = slugify(name)
    slug, number = base, 2
    while True:
        query = User.query.filter_by(seller_slug=slug)
        if user_id:
            query = query.filter(User.id != user_id)
        if not query.first():
            return slug
        slug = f'{base}-{number}'
        number += 1


def migrate_schema():
    inspector = inspect(db.engine)
    tables = inspector.get_table_names()
    dialect = db.engine.dialect.name
    quote_name = db.engine.dialect.identifier_preparer.quote
    with db.engine.begin() as conn:
        if 'user' in tables and 'seller_slug' not in {c['name'] for c in inspector.get_columns('user')}:
            conn.execute(text(f'ALTER TABLE {quote_name("user")} ADD COLUMN seller_slug VARCHAR(120)'))
        if 'product' in tables and 'created_at' not in {c['name'] for c in inspector.get_columns('product')}:
            column_type = 'TIMESTAMP' if dialect == 'postgresql' else 'DATETIME'
            conn.execute(text(f'ALTER TABLE {quote_name("product")} ADD COLUMN created_at {column_type}'))
        if 'user' in tables:
            user_columns = {c['name'] for c in inspector.get_columns('user')}
            if 'preferred_language' not in user_columns:
                conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN preferred_language VARCHAR(10) NOT NULL DEFAULT 'auto'"))
            if 'preferred_currency' not in user_columns:
                conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN preferred_currency VARCHAR(3) NOT NULL DEFAULT 'NGN'"))
            if 'email_verified' not in user_columns:
                conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT FALSE"))
                conn.execute(text(f"UPDATE {quote_name('user')} SET email_verified = TRUE"))
            if 'email_notifications' not in user_columns:
                conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN email_notifications BOOLEAN NOT NULL DEFAULT TRUE"))


SUPPORTED_LANGUAGES = {
    'en': 'English', 'fr': 'Français', 'es': 'Español', 'pt': 'Português',
    'ar': 'العربية', 'ha': 'Hausa', 'yo': 'Yorùbá'
}
SUPPORTED_CURRENCIES = {
    'NGN': '₦ Nigerian Naira', 'USD': '$ US Dollar', 'GBP': '£ British Pound',
    'EUR': '€ Euro', 'GHS': '₵ Ghanaian Cedi', 'KES': 'KSh Kenyan Shilling', 'ZAR': 'R South African Rand'
}

def _serializer():
    return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='maximise-email-verification')

def make_verification_token(user):
    return _serializer().dumps({'id': user.id, 'email': user.email})

def send_email(to_email, subject, text_body, html_body=None):
    host = os.environ.get('SMTP_HOST', '').strip()
    port = int(os.environ.get('SMTP_PORT', '587') or 587)
    username = os.environ.get('SMTP_USERNAME', '').strip()
    password = os.environ.get('SMTP_PASSWORD', '')
    sender = os.environ.get('MAIL_FROM', username).strip()
    if not host or not sender:
        app.logger.warning('SMTP is not configured; email not sent to %s', to_email)
        return False
    message = EmailMessage()
    message['From'] = sender
    message['To'] = to_email
    message['Subject'] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype='html')
    try:
        with smtplib.SMTP(host, port, timeout=15) as smtp:
            if os.environ.get('SMTP_TLS', '1').lower() not in {'0', 'false', 'no'}:
                smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(message)
        return True
    except Exception:
        app.logger.exception('SMTP delivery failed for %s', to_email)
        return False

def send_verification_email(user):
    token = make_verification_token(user)
    link = url_for('verify_email', token=token, _external=True)
    return send_email(
        user.email, 'Verify your Merco email',
        f'Hi {user.username},\n\nVerify your email to unlock Seller Mode on Merco:\n{link}\n\nThis link expires in 24 hours.',
        f'<div style="font-family:Arial,sans-serif"><h2>Verify your Merco email</h2><p>Hi {user.username},</p><p>Verify your email to unlock Seller Mode.</p><p><a href="{link}" style="display:inline-block;padding:12px 18px;background:#d4af62;color:#080705;text-decoration:none;border-radius:10px;font-weight:700">Verify email</a></p><p>This link expires in 24 hours.</p></div>'
    )

def initialize_database():
    db.create_all()
    migrate_schema()
    changed = False
    for name in DEFAULT_CATEGORIES:
        if not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name))
            changed = True
    if changed:
        db.session.commit()


try:
    with app.app_context():
        initialize_database()
except Exception:
    app.logger.exception('Database initialization deferred. Check DATABASE_URL and database availability.')


@app.context_processor
def inject_globals():
    try:
        categories = Category.query.order_by(Category.name.asc()).all()
    except Exception:
        categories = []
    return {'market_categories': categories, 'supported_languages': SUPPORTED_LANGUAGES, 'supported_currencies': SUPPORTED_CURRENCIES}


@app.get('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'ok', 'service': 'maximise', 'database': 'ok'}), 200
    except Exception:
        db.session.rollback()
        return jsonify({'status': 'degraded', 'service': 'maximise', 'database': 'unavailable'}), 503


@app.get('/')
def home():
    return redirect(url_for('market'))


@app.get('/market')
def market():
    search = request.args.get('search', '').strip()
    category_id = request.args.get('category', type=int)
    query = Product.query.filter_by(is_sold_out=False).order_by(Product.created_at.desc(), Product.id.desc())
    if search:
        term = f'%{search}%'
        query = query.filter(Product.name.ilike(term) | Product.description.ilike(term))
    if category_id:
        query = query.filter_by(category_id=category_id)
    return render_template('market.html', products=query.all(), categories=Category.query.order_by(Category.name.asc()).all(), search=search, selected_category=category_id)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        user = User.query.filter_by(email=email).first()
        admin_email = os.environ.get('ADMIN_EMAIL', '').strip().lower()
        admin_password = os.environ.get('ADMIN_PASSWORD', '')
        if admin_email and admin_password and email == admin_email and password == admin_password:
            if not user:
                user = User(username='Admin', email=email, password=generate_password_hash(password), role='admin')
                db.session.add(user)
                db.session.commit()
            elif user.role != 'admin':
                user.role = 'admin'
                db.session.commit()
            login_user(user)
            return redirect(url_for('dashboard'))
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.')
    return render_template('login.html')


@app.get('/verify-email/<token>')
def verify_email(token):
    try:
        data = _serializer().loads(token, max_age=86400)
        user = User.query.filter_by(id=int(data['id']), email=data['email']).first_or_404()
    except (BadSignature, SignatureExpired, ValueError, TypeError):
        flash('That verification link is invalid or has expired. Please request a new one.')
        return redirect(url_for('login'))
    user.email_verified = True
    db.session.commit()
    flash('Email verified successfully. You can now open a seller store.')
    return redirect(url_for('login'))

@app.get('/verify-email')
@login_required
def verify_email_notice():
    if current_user.email_verified:
        return redirect(url_for('settings'))
    return render_template('verify_email.html')

@app.post('/verify-email/resend')
@login_required
def resend_verification():
    if current_user.email_verified:
        flash('Your email is already verified.')
    elif send_verification_email(current_user):
        flash('A new verification email has been sent.')
    else:
        flash('Email delivery is not configured. Please contact the site administrator.')
    return redirect(url_for('verify_email_notice'))

@app.get('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()[:100]
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        if not username or not email or len(password) < 6:
            flash('Enter your name, email and a password of at least 6 characters.')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.')
            return redirect(url_for('login'))
        user = User(username=username, email=email, password=generate_password_hash(password), role='buyer', email_verified=False)
        db.session.add(user)
        db.session.commit()
        sent = send_verification_email(user)
        flash('Account created. Check your email to verify it before opening a seller store.' if sent else 'Account created, but email delivery is not configured yet. Ask the administrator to configure SMTP verification.')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.get('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    if current_user.role == 'seller':
        if not current_user.seller_slug:
            current_user.seller_slug = unique_seller_slug(current_user.username, current_user.id)
            db.session.commit()
        return redirect(url_for('seller_dashboard'))
    recent = Product.query.filter_by(is_sold_out=False).order_by(Product.created_at.desc(), Product.id.desc()).limit(8).all()
    return render_template('buyer_dashboard.html', recent=recent)


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'preferences':
            language = request.form.get('language', 'auto').strip().lower()
            currency = request.form.get('currency', 'NGN').strip().upper()
            if language != 'auto' and language not in SUPPORTED_LANGUAGES: language = 'auto'
            if currency not in SUPPORTED_CURRENCIES: currency = 'NGN'
            current_user.preferred_language = language
            current_user.preferred_currency = currency
            current_user.email_notifications = request.form.get('email_notifications') == '1'
            db.session.commit()
            flash('Language, currency and email preferences saved.')
            return redirect(url_for('settings'))
        if action == 'become_seller' and current_user.role == 'buyer':
            if not current_user.email_verified:
                send_verification_email(current_user)
                flash('Verify your email before opening your seller store. A fresh verification link has been sent if SMTP is configured.')
                return redirect(url_for('settings'))
            seller_name = (request.form.get('seller_name') or current_user.username).strip()[:100]
            whatsapp = request.form.get('whatsapp', '').strip()[:30]
            if not whatsapp:
                flash('Add a WhatsApp number so buyers can contact you.')
                return redirect(url_for('settings'))
            current_user.role = 'seller'
            current_user.username = seller_name
            current_user.seller_slug = unique_seller_slug(seller_name, current_user.id)
            current_user.whatsapp_number = whatsapp
            db.session.commit()
            flash('Seller mode activated. Your storefront is now live.')
        elif action == 'profile':
            current_user.username = request.form.get('username', current_user.username).strip()[:100]
            current_user.whatsapp_number = request.form.get('whatsapp', current_user.whatsapp_number or '').strip()[:30]
            db.session.commit()
            flash('Settings saved.')
        return redirect(url_for('settings'))
    return render_template('settings.html')


@app.get('/seller/<seller_slug>')
def seller_page(seller_slug):
    seller = User.query.filter_by(seller_slug=seller_slug, role='seller').first_or_404()
    products = Product.query.filter_by(seller_id=seller.id, is_sold_out=False).order_by(Product.created_at.desc(), Product.id.desc()).all()
    return render_template('seller_page.html', seller=seller, products=products)


@app.get('/product/<int:id>')
def product_detail(id):
    product = Product.query.get_or_404(id)
    screenshots = [s for s in (product.screenshots or '').split(',') if s]
    return render_template('product_detail.html', product=product, screenshots=screenshots)


@app.get('/buy/<int:id>')
@login_required
def buy_product(id):
    product = Product.query.get_or_404(id)
    if product.is_sold_out:
        flash('This product is sold out.')
        return redirect(url_for('product_detail', id=id))
    if not product.seller.whatsapp_number:
        flash('The seller has not added a WhatsApp number yet.')
        return redirect(url_for('product_detail', id=id))
    message = quote(f"Hi, I'm interested in {product.name} on Merco.")
    return redirect(f'https://wa.me/{product.seller.whatsapp_number}?text={message}')


@app.get('/seller')
@login_required
def seller_dashboard():
    if current_user.role == 'seller' and not current_user.email_verified:
        return redirect(url_for('verify_email_notice'))
    if current_user.role != 'seller':
        flash('Seller mode is available from Settings.')
        return redirect(url_for('settings'))
    if not current_user.seller_slug:
        current_user.seller_slug = unique_seller_slug(current_user.username, current_user.id)
        db.session.commit()
    products = Product.query.filter_by(seller_id=current_user.id).order_by(Product.created_at.desc(), Product.id.desc()).all()
    return render_template('seller_dashboard.html', products=products)


def save_image(file):
    if not file or not file.filename:
        return None
    original = secure_filename(file.filename)
    extension = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError('Only PNG, JPG, JPEG, WEBP and GIF images are allowed.')
    filename = f'{uuid.uuid4().hex}.{extension}'
    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
    return url_for('static', filename=f'uploads/{filename}')


def delete_product_files(product):
    prefix = url_for('static', filename='uploads/')
    urls = [product.cover_image] + [x for x in (product.screenshots or '').split(',') if x]
    for value in urls:
        if value and value.startswith(prefix):
            path = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(value[len(prefix):]))
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except OSError:
                app.logger.warning('Could not remove uploaded file: %s', path)


@app.route('/seller/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if current_user.role != 'seller':
        flash('Become a seller from Settings before uploading products.')
        return redirect(url_for('settings'))
    categories = Category.query.order_by(Category.name.asc()).all()
    if request.method == 'POST':
        try:
            name = request.form.get('name', '').strip()[:200]
            price = float(request.form.get('price', 0))
            if not name or price < 0:
                raise ValueError('Enter a valid product name and price.')
            cover = save_image(request.files.get('cover_image'))
            if not cover:
                raise ValueError('Please choose a cover image.')
            screenshots = [saved for file in request.files.getlist('screenshots') if (saved := save_image(file))]
            current_user.whatsapp_number = request.form.get('whatsapp', current_user.whatsapp_number or '').strip()[:30]
            db.session.add(Product(name=name, price=price, description=request.form.get('description', '').strip(), category_id=request.form.get('category', type=int), seller_id=current_user.id, cover_image=cover, screenshots=','.join(screenshots)))
            db.session.commit()
            if current_user.email_notifications:
                send_email(current_user.email, 'Your Merco product is live', f'Your product {name} has been published to the marketplace.', f'<p>Your product <strong>{name}</strong> is now live on Merco.</p>')
            flash('Product published to the marketplace. A confirmation email was sent if notifications are enabled.')
            return redirect(url_for('seller_dashboard'))
        except ValueError as exc:
            flash(str(exc))
        except Exception:
            db.session.rollback()
            app.logger.exception('Product upload failed')
            flash('The product could not be published. Please try again.')
    return render_template('add_product.html', categories=categories)


@app.post('/seller/product/<int:id>/delete')
@login_required
def seller_delete_product(id):
    product = Product.query.get_or_404(id)
    if current_user.role != 'seller' or product.seller_id != current_user.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    delete_product_files(product)
    db.session.delete(product)
    db.session.commit()
    flash('Product removed.')
    return redirect(url_for('seller_dashboard'))


@app.get('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    sellers = User.query.filter_by(role='seller').order_by(User.id.desc()).all()
    buyers = User.query.filter_by(role='buyer').order_by(User.id.desc()).all()
    products = Product.query.order_by(Product.created_at.desc(), Product.id.desc()).all()
    return render_template('admin_dashboard.html', sellers=sellers, buyers=buyers, products=products)


@app.post('/admin/product/<int:id>/delete')
@login_required
def admin_delete_product(id):
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    product = Product.query.get_or_404(id)
    delete_product_files(product)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted by admin.')
    return redirect(url_for('admin_dashboard'))


@app.post('/admin/user/<int:id>/delete')
@login_required
def admin_delete_user(id):
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    user = User.query.get_or_404(id)
    if user.id == current_user.id or user.role == 'admin':
        flash('Admin accounts cannot be deleted here.')
        return redirect(url_for('admin_dashboard'))
    for product in list(user.products):
        delete_product_files(product)
    db.session.delete(user)
    db.session.commit()
    flash('User and their seller listings were deleted.')
    return redirect(url_for('admin_dashboard'))


@app.errorhandler(413)
def too_large(_error):
    flash('That upload is too large. Maximum file size is 8 MB.')
    return redirect(request.referrer or url_for('market'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=os.environ.get('FLASK_DEBUG') == '1')