import os
from flask import Flask, render_template, redirect, url_for, request
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime

# ======================
# BASE SETUP
# ======================

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config["SECRET_KEY"] = "supersecretkey"
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(basedir,'store.db')}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Ensure uploads folder exists
UPLOAD_FOLDER = os.path.join(basedir, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# ======================
# MODELS
# ======================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    email = db.Column(db.String(120), unique=True)
    password_hash = db.Column(db.String(200))
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200))
    description = db.Column(db.Text)
    price = db.Column(db.Float)
    stock = db.Column(db.Integer)
    category = db.Column(db.String(100))
    image = db.Column(db.String(200))


class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    product_id = db.Column(db.Integer)
    quantity = db.Column(db.Integer, default=1)


class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    total = db.Column(db.Float)
    status = db.Column(db.String(50), default="Pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ======================
# SETUP FUNCTION
# ======================

def setup_demo_data():
    db.create_all()

    # Demo products if none exist
    if Product.query.count() == 0:
        demo_products = [
            {"name":"Purple Gaming Headset","description":"RGB wireless headset","price":25000,"stock":10,"category":"Electronics","image":"default.png"},
            {"name":"Pink Mechanical Keyboard","description":"Premium clicky keyboard","price":45000,"stock":8,"category":"Electronics","image":"default.png"},
            {"name":"Black Smart Watch","description":"Fitness smartwatch","price":60000,"stock":5,"category":"Wearables","image":"default.png"},
            {"name":"Purple Hoodie","description":"Premium cotton hoodie","price":20000,"stock":15,"category":"Fashion","image":"default.png"}
        ]
        for item in demo_products:
            db.session.add(Product(**item))

    # Admin account
    if not User.query.filter_by(email="admin@mail.com").first():
        admin = User(username="admin", email="admin@mail.com", is_admin=True)
        admin.set_password("admin123")
        db.session.add(admin)

    db.session.commit()


# ======================
# CALL SETUP AT STARTUP
# ======================

with app.app_context():
    setup_demo_data()


# ======================
# ROUTES (Home, Admin, CRUD, Cart, Auth)
# ======================

@app.route("/")
def home():
    search = request.args.get("search")
    category = request.args.get("category")
    products = Product.query
    if search:
        products = products.filter(Product.name.contains(search))
    if category:
        products = products.filter_by(category=category)
    return render_template("home.html", products=products.all())


@app.route("/admin")
@login_required
def admin():
    if not current_user.is_admin:
        return "Unauthorized"
    products = Product.query.all()
    orders = Order.query.all()
    return render_template("admin.html", products=products, orders=orders)


@app.route("/admin/add-product", methods=["POST"])
@login_required
def add_product():
    if not current_user.is_admin:
        return "Unauthorized"
    file = request.files["image"]
    filename = secure_filename(file.filename) if file else "default.png"
    if file:
        file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    product = Product(
        name=request.form["name"],
        description=request.form["description"],
        price=float(request.form["price"]),
        stock=int(request.form["stock"]),
        category=request.form["category"],
        image=filename
    )
    db.session.add(product)
    db.session.commit()
    return redirect(url_for("admin"))


@app.route("/admin/edit-product/<int:id>", methods=["GET","POST"])
@login_required
def edit_product(id):
    if not current_user.is_admin:
        return "Unauthorized"
    product = Product.query.get_or_404(id)
    if request.method=="POST":
        product.name = request.form["name"]
        product.description = request.form["description"]
        product.price = float(request.form["price"])
        product.stock = int(request.form["stock"])
        product.category = request.form["category"]
        file = request.files.get("image")
        if file and file.filename != "":
            if product.image != "default.png":
                old_path = os.path.join(app.config["UPLOAD_FOLDER"], product.image)
                if os.path.exists(old_path):
                    os.remove(old_path)
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
            product.image = filename
        db.session.commit()
        return redirect(url_for("admin"))
    return render_template("edit_product.html", product=product)


@app.route("/admin/delete-product/<int:id>", methods=["POST"])
@login_required
def delete_product(id):
    if not current_user.is_admin:
        return "Unauthorized"
    product = Product.query.get(id)
    if product:
        if product.image != "default.png":
            image_path = os.path.join(app.config["UPLOAD_FOLDER"], product.image)
            if os.path.exists(image_path):
                os.remove(image_path)
        db.session.delete(product)
        db.session.commit()
    return redirect(url_for("admin"))


@app.route("/add-to-cart/<int:id>")
@login_required
def add_to_cart(id):
    item = CartItem.query.filter_by(user_id=current_user.id, product_id=id).first()
    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(user_id=current_user.id, product_id=id, quantity=1))
    db.session.commit()
    return redirect(url_for("cart"))


@app.route("/cart")
@login_required
def cart():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = 0
    detailed = []
    for item in items:
        product = Product.query.get(item.product_id)
        subtotal = product.price * item.quantity
        total += subtotal
        detailed.append({"product": product, "quantity": item.quantity, "subtotal": subtotal})
    return render_template("cart.html", items=detailed, total=total)


@app.route("/checkout")
@login_required
def checkout():
    items = CartItem.query.filter_by(user_id=current_user.id).all()
    total = sum(Product.query.get(i.product_id).price * i.quantity for i in items)
    order = Order(user_id=current_user.id, total=total)
    db.session.add(order)
    for item in items:
        product = Product.query.get(item.product_id)
        product.stock -= item.quantity
        db.session.delete(item)
    db.session.commit()
    return render_template("checkout.html", total=total)


@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        user = User(username=request.form["username"], email=request.form["email"])
        user.set_password(request.form["password"])
        db.session.add(user)
        db.session.commit()
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        user = User.query.filter_by(email=request.form["email"]).first()
        if user and user.check_password(request.form["password"]):
            login_user(user)
            return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))


# ======================
# RUN
# ======================

if __name__=="__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
