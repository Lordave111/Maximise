import os
import re
from urllib.parse import quote
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy import inspect, text

app = Flask(__name__)

# Production secrets/config must come from Render environment variables.
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    if os.environ.get('RENDER'):
        raise RuntimeError('SECRET_KEY is required on Render. Add it in the Render Environment settings.')
    secret_key = 'dev-only-secret-change-me'
app.config['SECRET_KEY'] = secret_key

# Support Render Postgres, the existing Aiven MySQL database, and local SQLite.
database_url = os.environ.get('DATABASE_URL')
if not database_url:
    if os.environ.get('RENDER'):
        raise RuntimeError('DATABASE_URL is required on Render. Add your database connection string in the Render Environment settings.')
    os.makedirs(os.path.join(os.getcwd(), 'instance'), exist_ok=True)
    database_url = 'sqlite:///instance/maximise.db'
else:
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql+psycopg2://', 1)
    elif database_url.startswith('postgresql://'):
        database_url = database_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    elif database_url.startswith('mysql://'):
        database_url = database_url.replace('mysql://', 'mysql+pymysql://', 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='buyer', nullable=False)
    whatsapp_number = db.Column(db.String(30))
    seller_slug = db.Column(db.String(120), unique=True)
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


def unique_seller_slug(username, user_id=None):
    base = slugify(username)
    slug = base
    counter = 2
    while True:
        query = User.query.filter_by(seller_slug=slug)
        if user_id:
            query = query.filter(User.id != user_id)
        if not query.first():
            return slug
        slug = f'{base}-{counter}'
        counter += 1


def migrate_schema():
    """Add columns needed by older installations without hardcoding a DB dialect."""
    inspector = inspect(db.engine)
    table_names = inspector.get_table_names()
    preparer = db.engine.dialect.identifier_preparer

    if 'user' in table_names:
        columns = {c['name'] for c in inspector.get_columns('user')}
        if 'seller_slug' not in columns:
            table = preparer.quote('user')
            column = preparer.quote('seller_slug')
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} VARCHAR(120) NULL'))

    if 'product' in table_names:
        columns = {c['name'] for c in inspector.get_columns('product')}
        if 'created_at' not in columns:
            table = preparer.quote('product')
            column = preparer.quote('created_at')
            with db.engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} TIMESTAMP NULL'))


def initialize_database():
    try:
        with app.app_context():
            db.create_all()
            migrate_schema()
        app.logger.info('Database initialization completed.')
    except Exception:
        app.logger.exception('Database initialization failed. Check DATABASE_URL and database availability.')


initialize_database()


@app.context_processor
def inject_globals():
    return {'market_categories': Category.query.order_by(Category.name.asc()).all()}


@app.route('/health')
def health():
    """Render health endpoint. It checks that the application can reach its database."""
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify(status='ok', database='ok'), 200
    except Exception:
        app.logger.exception('Health check database connection failed.')
        return jsonify(status='degraded', database='error'), 503


@app.route('/')
def home():
    return redirect(url_for('market'))


@app.route('/market')
def market():
    search = request.args.get('search', '').strip()
    category_id = request.args.get('category', type=int)
    query = Product.query.filter_by(is_sold_out=False).order_by(Product.created_at.desc(), Product.id.desc())
    if search:
        query = query.filter(Product.name.ilike(f'%{search}%'))
    if category_id:
        query = query.filter_by(category_id=category_id)
    products = query.all()
    return render_template(
        'market.html',
        products=products,
        categories=Category.query.order_by(Category.name.asc()).all(),
        search=search,
        selected_category=category_id,
    )


@app.route('/login', methods=['GET', 'POST'])
def login():
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


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        raw_password = request.form.get('password', '')
        if not username or not email or len(raw_password) < 6:
            flash('Enter your name, email and a password of at least 6 characters.')
            return render_template('register.html')
        if User.query.filter_by(email=email).first():
            flash('An account with that email already exists.')
            return redirect(url_for('login'))
        user = User(username=username, email=email, password=generate_password_hash(raw_password), role='buyer')
        db.session.add(user)
        db.session.commit()
        flash('Account created. You can become a seller anytime from Settings.')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin_dashboard'))
    if current_user.role == 'seller':
        return redirect(url_for('seller_dashboard'))
    return render_template(
        'buyer_dashboard.html',
        recent=Product.query.filter_by(is_sold_out=False).order_by(Product.created_at.desc()).limit(8).all(),
    )


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'become_seller' and current_user.role == 'buyer':
            current_user.role = 'seller'
            current_user.seller_slug = unique_seller_slug(
                request.form.get('seller_name') or current_user.username,
                current_user.id,
            )
            current_user.username = (request.form.get('seller_name') or current_user.username).strip()[:100]
            current_user.whatsapp_number = request.form.get('whatsapp', '').strip()[:30]
            db.session.commit()
            flash('Seller mode activated. Your storefront is now live.')
        elif action == 'profile':
            current_user.username = request.form.get('username', current_user.username).strip()[:100]
            current_user.whatsapp_number = request.form.get('whatsapp', current_user.whatsapp_number or '').strip()[:30]
            db.session.commit()
            flash('Settings saved.')
        return redirect(url_for('settings'))
    return render_template('settings.html')


@app.route('/seller/<seller_slug>')
def seller_page(seller_slug):
    seller = User.query.filter_by(seller_slug=seller_slug, role='seller').first_or_404()
    products = Product.query.filter_by(seller_id=seller.id, is_sold_out=False).order_by(Product.created_at.desc(), Product.id.desc()).all()
    return render_template('seller_page.html', seller=seller, products=products)


@app.route('/product/<int:id>')
def product_detail(id):
    product = Product.query.get_or_404(id)
    screenshots = [s for s in (product.screenshots or '').split(',') if s]
    return render_template('product_detail.html', product=product, screenshots=screenshots)


@app.route('/buy/<int:id>')
@login_required
def buy_product(id):
    product = Product.query.get_or_404(id)
    if product.is_sold_out:
        flash('This product is sold out.')
        return redirect(url_for('product_detail', id=id))
    if not product.seller.whatsapp_number:
        flash('The seller has not added a WhatsApp number yet.')
        return redirect(url_for('product_detail', id=id))
    message = quote(f"Hi, I'm interested in {product.name} on Maximise.")
    return redirect(f'https://wa.me/{product.seller.whatsapp_number}?text={message}')


@app.route('/seller')
@login_required
def seller_dashboard():
    if current_user.role != 'seller':
        flash('Seller mode is available from Settings.')
        return redirect(url_for('settings'))
    products = Product.query.filter_by(seller_id=current_user.id).order_by(Product.id.desc()).all()
    return render_template('seller_dashboard.html', products=products)


@app.route('/seller/add', methods=['GET', 'POST'])
@login_required
def add_product():
    if current_user.role != 'seller':
        flash('Become a seller from Settings before uploading products.')
        return redirect(url_for('settings'))
    categories = Category.query.order_by(Category.name.asc()).all()
    if request.method == 'POST':
        cover_file = request.files.get('cover_image')
        if not cover_file or not cover_file.filename:
            flash('Please choose a cover image.')
            return render_template('add_product.html', categories=categories)

        cover_filename = secure_filename(cover_file.filename)
        cover_file.save(os.path.join(app.config['UPLOAD_FOLDER'], cover_filename))
        screenshot_urls = []
        for file in request.files.getlist('screenshots'):
            if file and file.filename:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                screenshot_urls.append(url_for('static', filename=f'uploads/{filename}'))

        try:
            price = float(request.form.get('price', 0))
        except (TypeError, ValueError):
            flash('Enter a valid product price.')
            return render_template('add_product.html', categories=categories)

        product = Product(
            name=request.form.get('name', '').strip(),
            price=price,
            description=request.form.get('description', '').strip(),
            category_id=request.form.get('category', type=int),
            seller_id=current_user.id,
            cover_image=url_for('static', filename=f'uploads/{cover_filename}'),
            screenshots=','.join(screenshot_urls),
        )
        current_user.whatsapp_number = request.form.get('whatsapp', current_user.whatsapp_number or '').strip()[:30]
        db.session.add(product)
        db.session.commit()
        flash('Product published to the marketplace.')
        return redirect(url_for('seller_dashboard'))
    return render_template('add_product.html', categories=categories)


@app.route('/seller/product/<int:id>/delete', methods=['POST'])
@login_required
def seller_delete_product(id):
    product = Product.query.get_or_404(id)
    if current_user.role != 'seller' or product.seller_id != current_user.id:
        flash('Access denied.')
        return redirect(url_for('dashboard'))
    db.session.delete(product)
    db.session.commit()
    flash('Product removed.')
    return redirect(url_for('seller_dashboard'))


@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    sellers = User.query.filter_by(role='seller').order_by(User.id.desc()).all()
    buyers = User.query.filter_by(role='buyer').order_by(User.id.desc()).all()
    products = Product.query.order_by(Product.id.desc()).all()
    return render_template('admin_dashboard.html', sellers=sellers, buyers=buyers, products=products)


@app.route('/admin/product/<int:id>/delete', methods=['POST'])
def admin_delete_product(id):
    if not current_user.is_authenticated or current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted by admin.')
    return redirect(url_for('admin_dashboard'))


@app.route('/admin/user/<int:id>/delete', methods=['POST'])
def admin_delete_user(id):
    if not current_user.is_authenticated or current_user.role != 'admin':
        flash('Access denied.')
        return redirect(url_for('market'))
    user = User.query.get_or_404(id)
    if user.id == current_user.id or user.role == 'admin':
        flash('Admin accounts cannot be deleted here.')
        return redirect(url_for('admin_dashboard'))
    db.session.delete(user)
    db.session.commit()
    flash('User and their seller listings were deleted.')
    return redirect(url_for('admin_dashboard'))


@app.route('/init-db')
def init_db():
    try:
        db.create_all()
        migrate_schema()
        return 'Database ready.'
    except Exception:
        app.logger.exception('Database initialization failed.')
        return 'Database initialization failed. Check the Render logs and DATABASE_URL.', 500


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
