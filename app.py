import os
import re
import uuid
import json
import requests
from urllib.parse import quote, parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, current_user, UserMixin
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
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}: value = value[1:-1].strip()
    if not value: return 'sqlite:///maximise.db'
    if value.startswith('postgres://'): return value.replace('postgres://', 'postgresql+psycopg://', 1)
    if value.startswith('postgresql://') and '+psycopg' not in value: return value.replace('postgresql://', 'postgresql+psycopg://', 1)
    if value.startswith('mysql://'): value = value.replace('mysql://', 'mysql+pymysql://', 1)
    if value.startswith('mysql+pymysql://'):
        parsed = urlsplit(value); query = []
        for key, val in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower().replace('_', '-') in {'ssl-mode', 'sslmode'}: continue
            query.append((key, val))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))
    return value

DATABASE_URL = get_database_url()
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
engine_options = {'pool_pre_ping': True, 'pool_recycle': 280}
if DATABASE_URL.startswith('mysql+pymysql://'): engine_options['connect_args'] = {'ssl': {}}
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
db = SQLAlchemy(app)
login_manager = LoginManager(app); login_manager.login_view = 'login'; login_manager.login_message = 'Please sign in to continue.'
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
DEFAULT_CATEGORIES = ['Electronics', 'Fashion', 'Home & Living', 'Beauty', 'Phones & Accessories', 'Computers', 'Gaming', 'Vehicles', 'Books', 'Services', 'Other']

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True); username = db.Column(db.String(100), nullable=False); email = db.Column(db.String(100), unique=True, nullable=False); password = db.Column(db.String(200), nullable=False); role = db.Column(db.String(20), default='buyer', nullable=False); whatsapp_number = db.Column(db.String(30)); seller_slug = db.Column(db.String(120), unique=True); preferred_language = db.Column(db.String(10), default='auto', nullable=False); preferred_currency = db.Column(db.String(3), default='NGN', nullable=False); email_verified = db.Column(db.Boolean, default=False, nullable=False); email_notifications = db.Column(db.Boolean, default=True, nullable=False); products = db.relationship('Product', backref='seller', lazy=True, cascade='all, delete-orphan')
class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True); name = db.Column(db.String(100), unique=True, nullable=False); products = db.relationship('Product', backref='category', lazy=True)
class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True); name = db.Column(db.String(200), nullable=False); price = db.Column(db.Float, nullable=False); description = db.Column(db.Text); cover_image = db.Column(db.String(300)); screenshots = db.Column(db.Text); is_sold_out = db.Column(db.Boolean, default=False); seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False); category_id = db.Column(db.Integer, db.ForeignKey('category.id')); created_at = db.Column(db.DateTime, server_default=db.func.now())
@login_manager.user_loader
def load_user(user_id): return db.session.get(User, int(user_id))
def slugify(value): return re.sub(r'[^a-zA-Z0-9]+', '-', value.strip().lower()).strip('-') or 'seller'
def unique_seller_slug(name, user_id=None):
    base=slugify(name); slug=base; number=2
    while True:
        query=User.query.filter_by(seller_slug=slug)
        if user_id: query=query.filter(User.id != user_id)
        if not query.first(): return slug
        slug=f'{base}-{number}'; number+=1

def migrate_schema():
    inspector=inspect(db.engine); tables=inspector.get_table_names(); dialect=db.engine.dialect.name; quote_name=db.engine.dialect.identifier_preparer.quote
    with db.engine.begin() as conn:
        if 'user' in tables and 'seller_slug' not in {c['name'] for c in inspector.get_columns('user')}: conn.execute(text(f'ALTER TABLE {quote_name("user")} ADD COLUMN seller_slug VARCHAR(120)'))
        if 'product' in tables and 'created_at' not in {c['name'] for c in inspector.get_columns('product')}: conn.execute(text(f'ALTER TABLE {quote_name("product")} ADD COLUMN created_at {"TIMESTAMP" if dialect == "postgresql" else "DATETIME"}'))
        if 'user' in tables:
            cols={c['name'] for c in inspector.get_columns('user')}
            if 'preferred_language' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN preferred_language VARCHAR(10) NOT NULL DEFAULT 'auto'"))
            if 'preferred_currency' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN preferred_currency VARCHAR(3) NOT NULL DEFAULT 'NGN'"))
            if 'email_verified' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT FALSE")); conn.execute(text(f"UPDATE {quote_name('user')} SET email_verified = TRUE"))
            if 'email_notifications' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN email_notifications BOOLEAN NOT NULL DEFAULT TRUE"))
SUPPORTED_LANGUAGES={'en':'English','fr':'Français','es':'Español','pt':'Português','ar':'العربية','ha':'Hausa','yo':'Yorùbá'}
SUPPORTED_CURRENCIES={'NGN':'₦ Nigerian Naira','USD':'$ US Dollar','GBP':'£ British Pound','EUR':'€ Euro','GHS':'₵ Ghanaian Cedi','KES':'KSh Kenyan Shilling','ZAR':'R South African Shilling'}
def _serializer(): return URLSafeTimedSerializer(app.config['SECRET_KEY'], salt='maximise-email-verification')
def make_verification_token(user): return _serializer().dumps({'id':user.id,'email':user.email})
def _emailjs_config(template_id=None): return {'service_id':os.environ.get('EMAILJS_SERVICE_ID','').strip(),'public_key':os.environ.get('EMAILJS_PUBLIC_KEY','').strip(),'private_key':(os.environ.get('EMAILJS_PRIVATE_KEY','').strip() or os.environ.get('EMAILJS_ACCESS_TOKEN','').strip()),'template_id':(template_id or os.environ.get('EMAILJS_TEMPLATE_ID','')).strip()}
def _send_emailjs(to_email,subject,message,name='',action_url='',action_text='Open Merco',template_id=None):
    cfg=_emailjs_config(template_id)
    if not cfg['service_id'] or not cfg['public_key'] or not cfg['template_id']: app.logger.error('EmailJS configuration incomplete'); return False
    payload={'service_id':cfg['service_id'],'template_id':cfg['template_id'],'user_id':cfg['public_key'],'template_params':{'to_email':to_email,'email':to_email,'recipient_email':to_email,'subject':subject,'name':name or '','username':name or '','preheader':'A secure update from Merco','message':message,'action_url':action_url,'action_text':action_text,'brand_name':'Merco','website_url':os.environ.get('MERCO_PUBLIC_URL','').strip()}}
    if cfg['private_key']: payload['accessToken']=cfg['private_key']
    try:
        response=requests.post('https://api.emailjs.com/api/v1.0/email/send',json=payload,headers={'Accept':'application/json','Content-Type':'application/json'},timeout=20)
        if response.ok: return True
        app.logger.error('EmailJS rejected email to %s: HTTP %s: %s',to_email,response.status_code,response.text[:1500]); return False
    except requests.RequestException as exc: app.logger.error('EmailJS network error: %s',exc); return False
def send_email(to_email,subject,text_body,html_body=None,template_id=None,action_url='',action_text='Open Merco'): return _send_emailjs(to_email,subject,text_body,action_url=action_url,action_text=action_text,template_id=template_id)
def send_merco_email(user,subject,message,action_url='',action_text='Open Merco',template_id=None): return _send_emailjs(user.email,subject,message,name=getattr(user,'username',''),action_url=action_url,action_text=action_text,template_id=template_id)
def send_verification_email(user): return send_merco_email(user,'Verify your Merco email',f'Hi {user.username},\n\nYour Merco account is almost ready. Verify your email to unlock Seller Mode.\n\nThis verification link expires in 24 hours.',action_url=url_for('verify_email',token=make_verification_token(user),_external=True),action_text='Verify my email',template_id=os.environ.get('EMAILJS_VERIFICATION_TEMPLATE_ID') or os.environ.get('EMAILJS_TEMPLATE_ID'))
def initialize_database():
    db.create_all(); migrate_schema(); changed=False
    for name in DEFAULT_CATEGORIES:
        if not Category.query.filter_by(name=name).first(): db.session.add(Category(name=name)); changed=True
    if changed: db.session.commit()
try:
    with app.app_context(): initialize_database()
except Exception: app.logger.exception('Database initialization deferred.')
@app.context_processor
def inject_globals():
    try: categories=Category.query.order_by(Category.name.asc()).all()
    except Exception: categories=[]
    return {'market_categories':categories,'supported_languages':SUPPORTED_LANGUAGES,'supported_currencies':SUPPORTED_CURRENCIES}
@app.get('/health')
def health():
    try: db.session.execute(text('SELECT 1')); return jsonify({'status':'ok','service':'maximise','database':'ok'}),200
    except Exception: db.session.rollback(); return jsonify({'status':'degraded','service':'maximise','database':'unavailable'}),503
@app.get('/')
def home(): return redirect(url_for('market'))
@app.get('/market')
def market():
    search=request.args.get('search','').strip(); category_id=request.args.get('category',type=int); page=max(request.args.get('page',1,type=int),1)
    query=Product.query.filter_by(is_sold_out=False).order_by(Product.created_at.desc(),Product.id.desc())
    if search: query=query.filter(Product.name.ilike(f'%{search}%') | Product.description.ilike(f'%{search}%'))
    if category_id: query=query.filter_by(category_id=category_id)
    total=query.count(); pagination=query.paginate(page=page,per_page=12,error_out=False)
    return render_template('market.html',products=pagination.items,pagination=pagination,total_products=total,categories=Category.query.order_by(Category.name.asc()).all(),search=search,selected_category=category_id)
@app.route('/login',methods=['GET','POST'])
def login():
    if current_user.is_authenticated:return redirect(url_for('dashboard'))
    if request.method=='POST':
        email=request.form.get('email','').strip().lower(); password=request.form.get('password',''); user=User.query.filter_by(email=email).first(); admin_email=os.environ.get('ADMIN_EMAIL','').strip().lower(); admin_password=os.environ.get('ADMIN_PASSWORD','')
        if admin_email and admin_password and email==admin_email and password==admin_password:
            if not user: user=User(username='Admin',email=email,password=generate_password_hash(password),role='admin'); db.session.add(user); db.session.commit()
            elif user.role!='admin': user.role='admin'; db.session.commit()
            login_user(user); return redirect(url_for('dashboard'))
        if user and check_password_hash(user.password,password): login_user(user); return redirect(url_for('dashboard'))
        flash('Invalid email or password.')
    return render_template('login.html')
@app.get('/verify-email/<token>')
def verify_email(token):
    try: data=_serializer().loads(token,max_age=86400); user=User.query.filter_by(id=int(data['id']),email=data['email']).first_or_404()
    except (BadSignature,SignatureExpired,ValueError,TypeError): flash('That verification link is invalid or has expired. Please request a new one.'); return redirect(url_for('login'))
    user.email_verified=True; db.session.commit(); flash('Email verified successfully. You can now open a seller store.'); return redirect(url_for('login'))
@app.get('/verify-email')
@login_required
def verify_email_notice(): return redirect(url_for('settings')) if current_user.email_verified else render_template('verify_email.html')
@app.post('/verify-email/resend')
@login_required
def resend_verification():
    if current_user.email_verified: flash('Your email is already verified.')
    elif send_verification_email(current_user): flash('A new verification email has been sent.')
    else: flash('Email delivery failed. Check the EmailJS configuration in Render and the template recipient field.')
    return redirect(url_for('verify_email_notice'))
@app.get('/logout')
@login_required
def logout(): logout_user(); return redirect(url_for('login'))
@app.route('/register',methods=['GET','POST'])
def register():
    if current_user.is_authenticated:return redirect(url_for('dashboard'))
    if request.method=='POST':
        username=request.form.get('username','').strip()[:100]; email=request.form.get('email','').strip().lower(); password=request.form.get('password','')
        if not username or not email or len(password)<6: flash('Enter your name, email and a password of at least 6 characters.'); return render_template('register.html')
        if User.query.filter_by(email=email).first(): flash('An account with that email already exists.'); return redirect(url_for('login'))
        user=User(username=username,email=email,password=generate_password_hash(password),role='buyer',email_verified=False); db.session.add(user); db.session.commit(); sent=send_verification_email(user); flash('Account created. Check your email to verify it before opening a seller store.' if sent else 'Account created, but email delivery failed.'); return redirect(url_for('login'))
    return render_template('register.html')
@app.get('/dashboard')
@login_required
def dashboard():
    if current_user.role=='admin':return redirect(url_for('admin_dashboard'))
    if current_user.role=='seller':
        if not current_user.seller_slug: current_user.seller_slug=unique_seller_slug(current_user.username,current_user.id); db.session.commit()
        return redirect(url_for('seller_dashboard'))
    recent=Product.query.filter_by(is_sold_out=False).order_by(Product.created_at.desc(),Product.id.desc()).limit(8).all(); return render_template('buyer_dashboard.html',recent=recent)
@app.route('/settings',methods=['GET','POST'])
@login_required
def settings():
    if request.method=='POST':
        action=request.form.get('action')
        if action=='preferences':
            language=request.form.get('language','auto').strip().lower(); currency=request.form.get('currency','NGN').strip().upper(); language=language if language=='auto' or language in SUPPORTED_LANGUAGES else 'auto'; currency=currency if currency in SUPPORTED_CURRENCIES else 'NGN'; current_user.preferred_language=language; current_user.preferred_currency=currency; current_user.email_notifications=request.form.get('email_notifications')=='1'; db.session.commit(); flash('Language, currency and email preferences saved.')
        elif action=='become_seller' and current_user.role=='buyer':
            if not current_user.email_verified: send_verification_email(current_user); flash('Verify your email before opening your seller store.'); return redirect(url_for('settings'))
            seller_name=(request.form.get('seller_name') or current_user.username).strip()[:100]; whatsapp=request.form.get('whatsapp','').strip()[:30]
            if not whatsapp: flash('Add a WhatsApp number so buyers can contact you.'); return redirect(url_for('settings'))
            current_user.role='seller'; current_user.username=seller_name; current_user.seller_slug=unique_seller_slug(seller_name,current_user.id); current_user.whatsapp_number=whatsapp; db.session.commit(); flash('Seller mode activated. Your storefront is now live.')
        elif action=='profile': current_user.username=request.form.get('username',current_user.username).strip()[:100]; current_user.whatsapp_number=request.form.get('whatsapp',current_user.whatsapp_number or '').strip()[:30]; db.session.commit(); flash('Settings saved.')
        return redirect(url_for('settings'))
    return render_template('settings.html')
@app.get('/seller/<seller_slug>')
def seller_page(seller_slug):
    seller=User.query.filter_by(seller_slug=seller_slug,role='seller').first_or_404(); products=Product.query.filter_by(seller_id=seller.id,is_sold_out=False).order_by(Product.created_at.desc(),Product.id.desc()).all(); return render_template('seller_page.html',seller=seller,products=products)
@app.get('/product/<int:id>')
def product_detail(id):
    product=Product.query.get_or_404(id); screenshots=[s for s in (product.screenshots or '').split(',') if s]
    import bootstrap
    contact=bootstrap.get_contact(product.seller); placement=bootstrap.ListingPlacement.query.filter_by(product_id=product.id).first()
    return render_template('product_detail.html',product=product,screenshots=screenshots,contact=contact,placement=placement)
@app.get('/buy/<int:id>')
@login_required
def buy_product(id):
    product=Product.query.get_or_404(id)
    if product.is_sold_out: flash('This product is sold out.'); return redirect(url_for('product_detail',id=id))
    if not product.seller.whatsapp_number: flash('The seller has not added a WhatsApp number yet.'); return redirect(url_for('product_detail',id=id))
    return redirect(f'https://wa.me/{product.seller.whatsapp_number}?text={quote(f"Hi, I'm interested in {product.name} on Merco.")}')
def save_image(file):
    if not file or not file.filename:return None
    original=secure_filename(file.filename); extension=original.rsplit('.',1)[-1].lower() if '.' in original else ''
    if extension not in ALLOWED_IMAGE_EXTENSIONS: raise ValueError('Only PNG, JPG, JPEG, WEBP and GIF images are allowed.')
    filename=f'{uuid.uuid4().hex}.{extension}'; file.save(os.path.join(app.config['UPLOAD_FOLDER'],filename)); return url_for('static',filename=f'uploads/{filename}')

def delete_product_files(product):
    prefix=url_for('static',filename='uploads/'); urls=[product.cover_image]+[x for x in (product.screenshots or '').split(',') if x]
    for value in urls:
        if value and value.startswith(prefix):
            path=os.path.join(app.config['UPLOAD_FOLDER'],os.path.basename(value[len(prefix):]))
            try:
                if os.path.isfile(path): os.remove(path)
            except OSError: app.logger.warning('Could not remove uploaded file: %s',path)
@app.route('/seller/add',methods=['GET','POST'])
@login_required
def add_product():
    if current_user.role!='seller': flash('Become a seller from Settings before uploading products.'); return redirect(url_for('settings'))
    categories=Category.query.order_by(Category.name.asc()).all()
    if request.method=='POST':
        try:
            name=request.form.get('name','').strip()[:200]; price=float(request.form.get('price',0))
            if not name or price<0: raise ValueError('Enter a valid product name and price.')
            cover=save_image(request.files.get('cover_image'))
            shots=[save_image(request.files.get(k)) for k in ('screenshot_1','screenshot_2','screenshot_3')]
            shots=[s for s in shots if s]
            product=Product(name=name,price=price,description=request.form.get('description','').strip(),cover_image=cover,screenshots=','.join(shots),seller_id=current_user.id,category_id=request.form.get('category_id',type=int),is_sold_out=False); db.session.add(product); db.session.commit(); flash('Product published to your store.'); return redirect(url_for('seller_dashboard'))
        except Exception as exc: db.session.rollback(); flash(str(exc))
    return render_template('add_product.html',categories=categories)
@app.get('/seller')
@login_required
def seller_dashboard():
    if current_user.role!='seller': return redirect(url_for('settings'))
    products=Product.query.filter_by(seller_id=current_user.id).order_by(Product.created_at.desc(),Product.id.desc()).all(); return render_template('seller_dashboard.html',products=products)
@app.post('/seller/delete/<int:id>')
@login_required
def delete_product(id):
    product=Product.query.get_or_404(id)
    if product.seller_id!=current_user.id and current_user.role!='admin': flash('You cannot delete this product.'); return redirect(url_for('seller_dashboard'))
    delete_product_files(product); db.session.delete(product); db.session.commit(); flash('Product removed.'); return redirect(url_for('seller_dashboard'))
@app.get('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role!='admin': flash('Admin access required.'); return redirect(url_for('dashboard'))
    return render_template('admin_dashboard.html',products=Product.query.order_by(Product.id.desc()).all(),users=User.query.order_by(User.id.desc()).all())
@app.post('/admin/product/<int:id>/delete')
@login_required
def admin_delete_product(id):
    if current_user.role!='admin': flash('Admin access required.'); return redirect(url_for('dashboard'))
    product=Product.query.get_or_404(id); delete_product_files(product); db.session.delete(product); db.session.commit(); flash('Product deleted.'); return redirect(url_for('admin_dashboard'))
@app.post('/admin/user/<int:id>/delete')
@login_required
def admin_delete_user(id):
    if current_user.role!='admin': flash('Admin access required.'); return redirect(url_for('dashboard'))
    user=User.query.get_or_404(id)
    if user.id==current_user.id: flash('You cannot delete your own admin account.'); return redirect(url_for('admin_dashboard'))
    for product in list(user.products): delete_product_files(product)
    db.session.delete(user); db.session.commit(); flash('User deleted.'); return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=os.environ.get('FLASK_DEBUG')=='1')
