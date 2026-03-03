import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# -------- CONFIG ----------
app = Flask(__name__)
app.config['SECRET_KEY'] = 'supersecretkey'
app.config['SQLALCHEMY_DATABASE_URI'] = "mysql+pymysql://avnadmin:AVNS_kGEUKEqpS9e5vSecN8T@mysql-2f4aa36-nwahiridaviduche-cede.c.aivencloud.com:11573/defaultdb?ssl=true"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), "static/uploads")
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# -------- MODELS ----------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20), default='buyer')  # buyer/seller/admin
    whatsapp_number = db.Column(db.String(20))
    products = db.relationship("Product", backref="seller", lazy=True)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True)
    products = db.relationship("Product", backref="category", lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200))
    price = db.Column(db.Float)
    description = db.Column(db.Text)
    cover_image = db.Column(db.String(300))
    screenshots = db.Column(db.Text)  # Comma separated URLs
    is_sold_out = db.Column(db.Boolean, default=False)
    seller_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("category.id"))

# -------- LOGIN ----------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# -------- ROUTES ----------
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        email = request.form["email"]
        password = request.form["password"]

        user = User.query.filter_by(email=email).first()
        # Check hardcoded admin
        if email=="nwahiridaviduche@gmail.com" and password=="22david":
            # Check if admin exists in DB
            user = User.query.filter_by(email=email).first()
            if not user:
                user = User(username="Admin", email=email,
                            password=generate_password_hash(password), role="admin")
                db.session.add(user)
                db.session.commit()
            login_user(user)
            return redirect(url_for("admin_dashboard"))

        if user and check_password_hash(user.password, password):
            login_user(user)
            if user.role=="admin":
                return redirect(url_for("admin_dashboard"))
            elif user.role=="seller":
                return redirect(url_for("seller_dashboard"))
            else:
                return redirect(url_for("home"))
        flash("Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        username = request.form["username"]
        email = request.form["email"]
        password = generate_password_hash(request.form["password"])
        role = request.form.get("role","buyer")
        if User.query.filter_by(email=email).first():
            flash("Email exists")
            return redirect(url_for("register"))
        user = User(username=username,email=email,password=password,role=role)
        db.session.add(user)
        db.session.commit()
        flash("Registered")
        return redirect(url_for("login"))
    return render_template("register.html")

# -------- HOME ----------
@app.route("/")
def home():
    search = request.args.get("search")
    category_id = request.args.get("category")
    query = Product.query.filter_by(is_sold_out=False)
    if search:
        query = query.filter(Product.name.contains(search))
    if category_id:
        query = query.filter_by(category_id=category_id)
    products = query.all()
    categories = Category.query.all()
    return render_template("home.html", products=products, categories=categories)

# -------- PRODUCT DETAIL ----------
@app.route("/product/<int:id>")
def product_detail(id):
    product = Product.query.get_or_404(id)
    screenshots = product.screenshots.split(",") if product.screenshots else []
    return render_template("product_detail.html", product=product, screenshots=screenshots)

@app.route("/buy/<int:id>")
def buy_product(id):
    product = Product.query.get_or_404(id)
    phone = product.seller.whatsapp_number
    message = f"I'm interested in {product.name}"
    return redirect(f"https://wa.me/{phone}?text={message}")

# -------- SELLER DASHBOARD ----------
@app.route("/seller")
@login_required
def seller_dashboard():
    if current_user.role != "seller":
        flash("Access denied")
        return redirect(url_for("home"))
    products = Product.query.filter_by(seller_id=current_user.id).all()
    return render_template("seller_dashboard.html", products=products)

@app.route("/seller/add", methods=["GET","POST"])
@login_required
def add_product():
    if current_user.role != "seller":
        flash("Access denied")
        return redirect(url_for("home"))
    categories = Category.query.all()
    if request.method=="POST":
        name = request.form["name"]
        price = request.form["price"]
        description = request.form["description"]
        category_id = request.form["category"]
        whatsapp = request.form["whatsapp"]

        cover_file = request.files["cover_image"]
        cover_filename = secure_filename(cover_file.filename)
        cover_file.save(os.path.join(app.config['UPLOAD_FOLDER'], cover_filename))

        screenshot_files = request.files.getlist("screenshots")
        screenshot_filenames = []
        for file in screenshot_files:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            screenshot_filenames.append(url_for('static', filename=f"uploads/{filename}"))

        product = Product(
            name=name, price=price, description=description,
            category_id=category_id, seller_id=current_user.id,
            cover_image=url_for('static', filename=f"uploads/{cover_filename}"),
            screenshots=",".join(screenshot_filenames)
        )
        current_user.whatsapp_number = whatsapp
        db.session.add(product)
        db.session.commit()
        return redirect(url_for("seller_dashboard"))
    return render_template("add_product.html", categories=categories)

# Edit/Delete routes similar (can be added)

# -------- ADMIN DASHBOARD ----------
@app.route("/admin/dashboard")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        flash("Access denied")
        return redirect(url_for("home"))
    categories = Category.query.all()
    products = Product.query.all()
    users = User.query.all()
    return render_template("admin_dashboard.html", categories=categories, products=products, users=users)

# -------- RUN ----------
if __name__=="__main__":
    app.run(debug=True)
