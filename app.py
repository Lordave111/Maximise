import os
import re
import uuid
import json
import requests
from urllib.parse import quote, parse_qsl, urlencode, urlsplit, urlunsplit

from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, current_user, UserMixin, login_required
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
    id = db.Column(db.Integer, primary_key=True); username = db.Column(db.String(100), nullable=False); email = db.Column(db.String(100), unique=True, nullable=False); password = db.Column(db.String(200), nullable=False); role = db.Column(db.String(20), default='buyer', nullable=False); whatsapp_number = db.Column(db.String(30)); seller_slug = db.Column(db.String(120), unique=True); preferred_language = db.Column(db.String(10), default='auto', nullable=False); preferred_currency = db.Column(db.String(3), default='NGN', nullable=False); email_verified = db.Column(db.Boolean, default=False, nullable=False); email_notifications = db.Column(db.Boolean, default=True, nullable=False); seller_verified = db.Column(db.Boolean, default=False, nullable=False); seller_verification_status = db.Column(db.String(20), default='none', nullable=False); pending_seller_name = db.Column(db.String(100)); pending_seller_email = db.Column(db.String(160)); pending_seller_phone = db.Column(db.String(40)); pending_seller_whatsapp = db.Column(db.String(30)); products = db.relationship('Product', backref='seller', lazy=True, cascade='all, delete-orphan')
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
            if 'seller_verified' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN seller_verified BOOLEAN NOT NULL DEFAULT FALSE"))
            if 'seller_verification_status' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN seller_verification_status VARCHAR(20) NOT NULL DEFAULT 'none'"))
            if 'pending_seller_name' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN pending_seller_name VARCHAR(100)"))
            if 'pending_seller_email' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN pending_seller_email VARCHAR(160)"))
            if 'pending_seller_phone' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN pending_seller_phone VARCHAR(40)"))
            if 'pending_seller_whatsapp' not in cols: conn.execute(text(f"ALTER TABLE {quote_name('user')} ADD COLUMN pending_seller_whatsapp VARCHAR(30)"))
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