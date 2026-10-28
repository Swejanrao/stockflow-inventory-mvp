from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import Flask, flash, redirect, render_template, request, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import UniqueConstraint, func, or_, select
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# The local SQLite file lives in the instance folder. Create the folder before DB setup.
import os
os.makedirs(app.instance_path, exist_ok=True)
if app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///stockflow.db":
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
        app.instance_path, "stockflow.db"
    ).replace("\\", "/")

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to continue."
login_manager.login_message_category = "info"
csrf = CSRFProtect(app)


class Organization(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    default_low_stock_threshold = db.Column(db.Integer, nullable=False, default=5)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    users = db.relationship("User", back_populates="organization", cascade="all, delete-orphan")
    products = db.relationship("Product", back_populates="organization", cascade="all, delete-orphan")


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    organization = db.relationship("Organization", back_populates="users")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    __table_args__ = (UniqueConstraint("organization_id", "sku", name="uq_org_sku"),)
    id = db.Column(db.Integer, primary_key=True)
    organization_id = db.Column(db.Integer, db.ForeignKey("organization.id"), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    sku = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=True)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    cost_price = db.Column(db.Numeric(12, 2), nullable=True)
    selling_price = db.Column(db.Numeric(12, 2), nullable=True)
    low_stock_threshold = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
    organization = db.relationship("Organization", back_populates="products")

    @property
    def effective_threshold(self):
        if self.low_stock_threshold is not None:
            return self.low_stock_threshold
        return self.organization.default_low_stock_threshold

    @property
    def is_low_stock(self):
        return self.quantity <= self.effective_threshold


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None


def parse_money(raw_value, field_name):
    raw_value = (raw_value or "").strip()
    if not raw_value:
        return None
    try:
        value = Decimal(raw_value)
        if not value.is_finite() or value < 0 or value > Decimal("9999999999.99"):
            raise InvalidOperation
        return value.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name} must be a valid non-negative price.")


def parse_integer(raw_value, field_name, optional=False):
    raw_value = (raw_value or "").strip()
    if optional and not raw_value:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be a whole number.")
    if value < 0:
        raise ValueError(f"{field_name} cannot be negative.")
    if value > 2_000_000_000:
        raise ValueError(f"{field_name} is too large.")
    return value


def get_owned_product(product_id):
    # Always scope product lookup to the signed-in user's organization.
    return db.session.scalar(
        select(Product).where(
            Product.id == product_id,
            Product.organization_id == current_user.organization_id,
        )
    )


def product_form_values(product=None):
    """Validate and return product form data; raises ValueError for friendly messages."""
    name = (request.form.get("name") or "").strip()
    sku = (request.form.get("sku") or "").strip()
    description = (request.form.get("description") or "").strip() or None
    if not name:
        raise ValueError("Product name is required.")
    if len(name) > 150:
        raise ValueError("Product name must be 150 characters or fewer.")
    if not sku:
        raise ValueError("SKU is required.")
    if len(sku) > 80:
        raise ValueError("SKU must be 80 characters or fewer.")
    quantity = parse_integer(request.form.get("quantity"), "Quantity")
    threshold = parse_integer(request.form.get("low_stock_threshold"), "Low-stock threshold", optional=True)
    cost_price = parse_money(request.form.get("cost_price"), "Cost price")
    selling_price = parse_money(request.form.get("selling_price"), "Selling price")
    duplicate_query = select(Product).where(
        Product.organization_id == current_user.organization_id,
        func.lower(Product.sku) == sku.lower(),
    )
    if product is not None:
        duplicate_query = duplicate_query.where(Product.id != product.id)
    if db.session.scalar(duplicate_query):
        raise ValueError("That SKU already exists in your organization. Please use a unique SKU.")
    return {
        "name": name,
        "sku": sku,
        "description": description,
        "quantity": quantity,
        "cost_price": cost_price,
        "selling_price": selling_price,
        "low_stock_threshold": threshold,
    }


@app.route("/")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm_password = request.form.get("confirm_password") or ""
        organization_name = (request.form.get("organization_name") or "").strip()
        if not email or "@" not in email or len(email) > 255:
            flash("Enter a valid email address.", "danger")
        elif len(password) < 8:
            flash("Password must be at least 8 characters long.", "danger")
        elif password != confirm_password:
            flash("Passwords do not match.", "danger")
        elif not organization_name or len(organization_name) > 120:
            flash("Organization name is required (maximum 120 characters).", "danger")
        elif db.session.scalar(select(User).where(User.email == email)):
            flash("An account with this email already exists. Please log in.", "warning")
        else:
            organization = Organization(name=organization_name, default_low_stock_threshold=5)
            user = User(email=email, organization=organization)
            user.set_password(password)
            db.session.add(organization)
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Your StockFlow account is ready. Welcome!", "success")
            return redirect(url_for("dashboard"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = db.session.scalar(select(User).where(User.email == email))
        if user and user.check_password(password):
            login_user(user)
            flash("You are logged in.", "success")
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "danger")
    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    base_query = select(Product).where(Product.organization_id == current_user.organization_id)
    products = db.session.scalars(base_query.order_by(Product.name.asc())).all()
    total_products = len(products)
    total_quantity = sum(product.quantity for product in products)
    low_stock_products = [product for product in products if product.is_low_stock]
    return render_template(
        "dashboard.html",
        total_products=total_products,
        total_quantity=total_quantity,
        low_stock_products=low_stock_products,
    )


@app.route("/products")
@login_required
def products():
    search = (request.args.get("q") or "").strip()
    query = select(Product).where(Product.organization_id == current_user.organization_id)
    if search:
        pattern = f"%{search}%"
        query = query.where(or_(Product.name.ilike(pattern), Product.sku.ilike(pattern)))
    product_list = db.session.scalars(query.order_by(Product.created_at.desc())).all()
    return render_template("products.html", products=product_list, search=search)


@app.route("/products/new", methods=["GET", "POST"])
@login_required
def create_product():
    if request.method == "POST":
        try:
            values = product_form_values()
            product = Product(organization_id=current_user.organization_id, **values)
            db.session.add(product)
            db.session.commit()
            flash("Product created successfully.", "success")
            return redirect(url_for("products"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
        except Exception:
            db.session.rollback()
            flash("Could not save the product. Check that the SKU is unique and try again.", "danger")
    return render_template("product_form.html", product=None, page_title="Add product")


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    product = get_owned_product(product_id)
    if product is None:
        flash("Product not found.", "warning")
        return redirect(url_for("products"))
    if request.method == "POST":
        try:
            values = product_form_values(product)
            for key, value in values.items():
                setattr(product, key, value)
            db.session.commit()
            flash("Product updated successfully.", "success")
            return redirect(url_for("products"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
            product = get_owned_product(product_id)
        except Exception:
            db.session.rollback()
            flash("Could not update the product. Check that the SKU is unique and try again.", "danger")
            product = get_owned_product(product_id)
    return render_template("product_form.html", product=product, page_title="Edit product")


@app.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product(product_id):
    product = get_owned_product(product_id)
    if product is None:
        flash("Product not found.", "warning")
    else:
        db.session.delete(product)
        db.session.commit()
        flash("Product deleted.", "success")
    return redirect(url_for("products"))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    organization = db.session.get(Organization, current_user.organization_id)
    if request.method == "POST":
        try:
            threshold = parse_integer(request.form.get("default_low_stock_threshold"), "Default low-stock threshold")
            if threshold > 1_000_000:
                raise ValueError("Threshold must be 1,000,000 or less.")
            organization.default_low_stock_threshold = threshold
            db.session.commit()
            flash("Settings saved.", "success")
            return redirect(url_for("settings"))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), "danger")
            organization = db.session.get(Organization, current_user.organization_id)
    return render_template("settings.html", organization=organization)


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", message="The page or product you requested was not found."), 404


@app.errorhandler(500)
def server_error(_error):
    db.session.rollback()
    return render_template("error.html", message="Something went wrong. Please try again."), 500


with app.app_context():
    db.create_all()


if __name__ == "__main__":
    app.run(debug=True)
