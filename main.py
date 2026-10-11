import os
from flask import Flask
from dotenv import load_dotenv
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from flask import render_template, request, redirect, url_for, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.security import generate_password_hash, check_password_hash
import stripe

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")


class Base(DeclarativeBase):
    pass


app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///store.db"
db = SQLAlchemy(model_class=Base)
db.init_app(app)


class User(UserMixin, db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password: Mapped[str] = mapped_column(String(255))  # hashed, never plain text
    cart_items = relationship("CartItem", back_populates="user")


class Product(db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(500))
    price_cents: Mapped[int] = mapped_column(Integer)
    image: Mapped[str] = mapped_column(String(200))  # filename in static/images


class CartItem(db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    product_id: Mapped[int] = mapped_column(ForeignKey("product.id"))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    user = relationship("User", back_populates="cart_items")
    product = relationship("Product")


class Order(db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    stripe_session_id: Mapped[str] = mapped_column(String(200), unique=True)
    total_cents: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    items = relationship("OrderItem", back_populates="order")


class OrderItem(db.Model):
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("order.id"))
    name: Mapped[str] = mapped_column(String(100))
    unit_price_cents: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    order = relationship("Order", back_populates="items")


with app.app_context():
    db.create_all()


@app.template_filter("money")
def money(cents):
    return f"€{cents / 100:,.2f}"


@app.route("/")
def home():
    products = db.session.execute(db.select(Product)).scalars().all()
    return render_template("index.html", products=products)

csrf = CSRFProtect(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        if db.session.execute(db.select(User).where(User.email == email)).scalar():
            flash("That email is already registered. Log in instead.")
            return redirect(url_for("login"))
        user = User(
            email=email,
            name=request.form["name"].strip(),
            password=generate_password_hash(request.form["password"], method="pbkdf2:sha256", salt_length=8),
        )
        db.session.add(user)
        db.session.commit()
        login_user(user)
        return redirect(url_for("home"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        user = db.session.execute(db.select(User).where(User.email == email)).scalar()
        if user and check_password_hash(user.password, request.form["password"]):
            login_user(user)
            return redirect(url_for("home"))
        flash("Invalid email or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("home"))


@app.context_processor
def cart_count():
    if current_user.is_authenticated:
        total = sum(item.quantity for item in current_user.cart_items)
        return {"cart_count": total}
    return {"cart_count": 0}


@app.route("/cart/add/<int:product_id>", methods=["POST"])
@login_required
def add_to_cart(product_id):
    product = db.get_or_404(Product, product_id)
    item = db.session.execute(
        db.select(CartItem).where(
            CartItem.user_id == current_user.id,
            CartItem.product_id == product.id,
        )
    ).scalar()
    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(user_id=current_user.id, product_id=product.id))
    db.session.commit()
    flash(f"Added {product.name} to your cart.")
    return redirect(request.referrer or url_for("home"))


@app.route("/cart")
@login_required
def cart():
    items = current_user.cart_items
    total = sum(i.product.price_cents * i.quantity for i in items)
    return render_template("cart.html", items=items, total=total)


@app.route("/cart/update/<int:item_id>", methods=["POST"])
@login_required
def update_cart(item_id):
    item = db.get_or_404(CartItem, item_id)
    if item.user_id != current_user.id:
        return "Forbidden", 403
    qty = int(request.form["quantity"])
    if qty < 1:
        db.session.delete(item)
    else:
        item.quantity = min(qty, 99)
    db.session.commit()
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:item_id>", methods=["POST"])
@login_required
def remove_from_cart(item_id):
    item = db.get_or_404(CartItem, item_id)
    if item.user_id != current_user.id:
        return "Forbidden", 403
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("cart"))




@app.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    items = current_user.cart_items
    if not items:
        flash("Your cart is empty.")
        return redirect(url_for("cart"))

    line_items = [
        {
            "price_data": {
                "currency": "eur",
                "unit_amount": i.product.price_cents,  # from the DB, never from the browser
                "product_data": {"name": i.product.name},
            },
            "quantity": i.quantity,
        }
        for i in items
    ]

    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=line_items,
        client_reference_id=str(current_user.id),
        customer_email=current_user.email,
        success_url=url_for("success", _external=True) + "?session_id={CHECKOUT_SESSION_ID}",
        cancel_url=url_for("cancel", _external=True),
    )
    return redirect(session.url, code=303)


@app.route("/success")
@login_required
def success():
    return render_template("success.html")


@app.route("/cancel")
@login_required
def cancel():
    return render_template("cancel.html")

@app.route("/webhook", methods=["POST"])
@csrf.exempt  # Stripe can't send a CSRF token; the signature check protects this route instead
def webhook():
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, os.getenv("STRIPE_WEBHOOK_SECRET")
        )
    except (ValueError, stripe.SignatureVerificationError):
        return "Invalid request", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        if session["payment_status"] == "paid":
            user_id = int(session["client_reference_id"])
            already = db.session.execute(
                db.select(Order).where(Order.stripe_session_id == session["id"])
            ).scalar()
            if not already:  # Stripe can resend events; don't create duplicates
                cart_items = db.session.execute(
                    db.select(CartItem).where(CartItem.user_id == user_id)
                ).scalars().all()
                order = Order(
                    user_id=user_id,
                    stripe_session_id=session["id"],
                    total_cents=session["amount_total"],
                )
                for i in cart_items:
                    order.items.append(OrderItem(
                        name=i.product.name,
                        unit_price_cents=i.product.price_cents,
                        quantity=i.quantity,
                    ))
                    db.session.delete(i)
                db.session.add(order)
                db.session.commit()

    return "", 200


@app.route("/orders")
@login_required
def orders():
    user_orders = db.session.execute(
        db.select(Order)
        .where(Order.user_id == current_user.id)
        .order_by(Order.created_at.desc())
    ).scalars().all()
    return render_template("orders.html", orders=user_orders)



if __name__ == "__main__":
    app.run(debug=True, port=5001)