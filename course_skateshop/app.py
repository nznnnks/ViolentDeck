from decimal import Decimal, InvalidOperation
import json
import random
import re
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from uuid import uuid4

from flask import Flask, Response, flash, redirect, render_template, request, session, url_for
from sqlalchemy import (
    Boolean,
    DateTime,
    Numeric,
    String,
    Text,
    create_engine,
    func,
    inspect,
    or_,
    select,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

import settings


app = Flask(__name__)
app.secret_key = settings.SECRET_KEY

engine = create_engine(settings.DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
PAGE_SIZE = 10
ORDER_STATUSES = [
    ("new", "Новый"),
    ("processing", "В обработке"),
    ("shipped", "Отправлен"),
    ("done", "Завершён"),
    ("cancelled", "Отменён"),
]
PAYMENT_METHODS = [
    ("cash", "Наличными при получении"),
    ("card", "Картой при получении"),
]


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="customer")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_reset_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    accent: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    image: Mapped[str] = mapped_column(String(500), nullable=False)
    empty_title: Mapped[str] = mapped_column(String(255), nullable=False)
    empty_description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_slug: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(nullable=False, index=True)
    checkout_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    product_id: Mapped[int] = mapped_column(nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(nullable=False, default=1)
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    shipping_address: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False, default="cash")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False, default="anonymous")
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    status_code: Mapped[int] = mapped_column(nullable=False, default=200)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)


DEFAULT_USER = {
    "username": "violent",
    "password": "deck123",
    "email": "team@violentdeck.test",
    "role": "customer",
}

ADMIN_USER = {
    "username": "admin",
    "password": "admin123",
    "email": "admin@violentdeck.test",
    "role": "admin",
}

PRODUCT_CARDS = [
    {
        "slug": "skateboards",
        "title": "Скейтборды",
        "description": "Стабильные деки, качественные подвески и колёса для любых трюков.",
        "accent": "скейты",
        "image": "images/skate.png",
        "empty_title": "Товары скоро появятся",
        "empty_description": "Мы уже готовим каталог скейтбордов. Загляните сюда позже.",
    },
    {
        "slug": "clothing",
        "title": "Одежда",
        "description": "Свободные худи, футболки и шорты из прочных материалов streetwear-класса.",
        "accent": "одежда",
        "image": "images/clothing.png",
        "empty_title": "Коллекция в подготовке",
        "empty_description": "Одежда для каталога скоро появится на этой странице.",
    },
    {
        "slug": "accessories",
        "title": "Аксессуары",
        "description": "Подшипники, сменные колёса, инструменты и элементы защиты.",
        "accent": "аксессуары",
        "image": "images/accessories.png",
        "empty_title": "Раздел заполняется",
        "empty_description": "Скоро здесь появятся аксессуары для вашего сетапа.",
    },
]


def parse_page_arg(param_name: str = "page") -> int:
    raw_value = request.args.get(param_name, "1")
    try:
        return max(1, int(raw_value))
    except ValueError:
        return 1


def paginate_statement(db_session, statement, page: int):
    total = db_session.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), total_pages)
    items = list(db_session.scalars(statement.limit(PAGE_SIZE).offset((page - 1) * PAGE_SIZE)))
    return items, page, total_pages, total


def paginate_list(items: list, page: int):
    total = len(items)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(1, page), total_pages)
    start_index = (page - 1) * PAGE_SIZE
    end_index = start_index + PAGE_SIZE
    return items[start_index:end_index], page, total_pages, total


def user_to_dict(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_verified": user.is_verified,
    }


def normalize_role(role: str | None) -> str:
    return "admin" if role == "admin" else "customer"


def normalize_slug(raw_value: str) -> str:
    slug = re.sub(r"[^\w]+", "-", raw_value.strip().lower(), flags=re.UNICODE)
    return slug.strip("-")


def normalize_order_status(status: str | None) -> str:
    allowed_statuses = {value for value, _ in ORDER_STATUSES}
    return status if status in allowed_statuses else "new"


def normalize_payment_method(payment_method: str | None) -> str:
    allowed_methods = {value for value, _ in PAYMENT_METHODS}
    return payment_method if payment_method in allowed_methods else "cash"


def get_payment_method_label(payment_method: str) -> str:
    return next((label for value, label in PAYMENT_METHODS if value == payment_method), "Наличными при получении")


def build_redirect_after_login(user: User):
    return redirect(url_for("admin_dashboard" if user.role == "admin" else "shop"))


def get_categories() -> list[Category]:
    with SessionLocal() as db_session:
        return list(db_session.scalars(select(Category).order_by(Category.created_at.asc(), Category.id.asc())))


def get_category_by_slug(slug: str) -> Category | None:
    with SessionLocal() as db_session:
        return db_session.scalar(select(Category).where(Category.slug == slug))


def get_image_source(image_value: str) -> str:
    if image_value.startswith(("http://", "https://", "/")):
        return image_value
    return url_for("static", filename=image_value)


def make_json_download(filename: str, payload: list[dict]) -> Response:
    return Response(
        json.dumps(payload, ensure_ascii=False, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def load_json_upload() -> list[dict] | None:
    upload = request.files.get("file")
    if upload is None or not upload.filename:
        flash("Выберите JSON-файл для импорта.")
        return None

    try:
        payload = json.load(upload.stream)
    except Exception:
        flash("Не удалось прочитать JSON-файл.")
        return None

    if not isinstance(payload, list):
        flash("JSON должен содержать список объектов.")
        return None
    return payload


def parse_datetime_value(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None


def build_request_details() -> str:
    if request.method == "GET":
        return ""

    safe_fields = []
    for key, value in request.form.items():
        if any(secret_key in key.lower() for secret_key in ("password", "code", "token")):
            continue
        safe_fields.append(f"{key}={value}")
    return ", ".join(safe_fields)


def ensure_category_for_import(db_session, category_slug: str) -> Category:
    category = db_session.scalar(select(Category).where(Category.slug == category_slug))
    if category is not None:
        return category

    title = category_slug.replace("-", " ").strip().title() or "Категория"
    category = Category(
        slug=category_slug,
        title=title,
        description=f"Импортированная категория {title}.",
        accent=title,
        image="images/skate.png",
        empty_title="Товары скоро появятся",
        empty_description=f"Мы уже готовим каталог для категории {title}.",
    )
    db_session.add(category)
    db_session.flush()
    return category


def get_cart() -> dict[str, int]:
    raw_cart = session.get("cart", {})
    normalized_cart: dict[str, int] = {}
    if not isinstance(raw_cart, dict):
        return normalized_cart

    for product_id, quantity in raw_cart.items():
        try:
            normalized_quantity = max(1, int(quantity))
        except (TypeError, ValueError):
            continue
        normalized_cart[str(product_id)] = normalized_quantity
    return normalized_cart


def save_cart(cart: dict[str, int]) -> None:
    session["cart"] = cart
    session.modified = True


def clear_cart() -> None:
    session.pop("cart", None)


def get_cart_count() -> int:
    return sum(get_cart().values())


def get_checkout_id(order: Order) -> str:
    return order.checkout_id or f"legacy-{order.id}"


def build_grouped_orders(
    orders: list[Order],
    products_by_id: dict[int, Product],
    users_by_id: dict[int, User] | None = None,
) -> list[dict]:
    grouped_orders: dict[str, dict] = {}

    for order in orders:
        checkout_id = get_checkout_id(order)
        product = products_by_id.get(order.product_id)
        order_group = grouped_orders.get(checkout_id)

        if order_group is None:
            user = users_by_id.get(order.user_id) if users_by_id is not None else None
            order_group = {
                "id": order.id,
                "checkout_id": checkout_id,
                "status": order.status,
                "shipping_address": order.shipping_address,
                "payment_method": order.payment_method,
                "payment_method_label": get_payment_method_label(order.payment_method),
                "created_at": order.created_at,
                "total_price": Decimal("0.00"),
                "total_quantity": 0,
                "items_count": 0,
                "username": user.username if user is not None else "Пользователь удалён",
                "email": user.email if user is not None else "",
                "line_items": [],
                "categories": set(),
                "first_product_image_url": product.image_url if product is not None else "",
            }
            grouped_orders[checkout_id] = order_group

        order_group["id"] = min(order_group["id"], order.id)
        order_group["created_at"] = min(order_group["created_at"], order.created_at)
        order_group["total_price"] += Decimal(order.total_price)
        order_group["total_quantity"] += order.quantity
        order_group["items_count"] += 1

        if product is not None:
            order_group["categories"].add(product.category_slug)
            if not order_group["first_product_image_url"]:
                order_group["first_product_image_url"] = product.image_url

        order_group["line_items"].append(
            {
                "order_row_id": order.id,
                "product_id": order.product_id,
                "product_name": product.name if product is not None else "Товар удалён",
                "product_image_url": product.image_url if product is not None else "",
                "category_slug": product.category_slug if product is not None else "",
                "quantity": order.quantity,
                "total_price": order.total_price,
            }
        )

    grouped_list = list(grouped_orders.values())
    for order_group in grouped_list:
        order_group["line_items"].sort(key=lambda item: item["order_row_id"])
        order_group["categories"] = ", ".join(sorted({category for category in order_group["categories"] if category})) or "—"

    grouped_list.sort(key=lambda item: (item["created_at"], item["id"]), reverse=True)
    return grouped_list


def serialize_order(order: Order, product: Product | None) -> dict:
    return {
        "id": order.id,
        "checkout_id": get_checkout_id(order),
        "quantity": order.quantity,
        "status": order.status,
        "total_price": order.total_price,
        "shipping_address": order.shipping_address,
        "payment_method": order.payment_method,
        "payment_method_label": get_payment_method_label(order.payment_method),
        "created_at": order.created_at,
        "product_name": product.name if product is not None else "Товар удалён",
        "product_image_url": product.image_url if product is not None else "",
        "product_category_slug": product.category_slug if product is not None else "",
    }


def serialize_admin_order(order: Order, user: User | None, product: Product | None) -> dict:
    return {
        "id": order.id,
        "checkout_id": get_checkout_id(order),
        "quantity": order.quantity,
        "status": order.status,
        "total_price": order.total_price,
        "shipping_address": order.shipping_address,
        "payment_method": order.payment_method,
        "payment_method_label": get_payment_method_label(order.payment_method),
        "created_at": order.created_at,
        "username": user.username if user is not None else "Пользователь удалён",
        "email": user.email if user is not None else "",
        "product_name": product.name if product is not None else "Товар удалён",
        "category_slug": product.category_slug if product is not None else "",
    }


def generate_code() -> str:
    return f"{random.randint(0, 999999):06d}"


def send_email(recipient_email: str, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.EMAIL_HOST_USER
    message["To"] = recipient_email
    message.set_content(body)

    if settings.EMAIL_USE_SSL:
        with smtplib.SMTP_SSL(settings.EMAIL_HOST, settings.EMAIL_PORT) as smtp:
            smtp.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT) as smtp:
        smtp.starttls()
        smtp.login(settings.EMAIL_HOST_USER, settings.EMAIL_HOST_PASSWORD)
        smtp.send_message(message)


def send_verification_email(recipient_email: str, code: str) -> None:
    send_email(recipient_email, "Код подтверждения ViolentDeck", "Здравствуйте!\n\nВаш код подтверждения для регистрации в ViolentDeck: " + code + f"\nКод действует {settings.VERIFICATION_CODE_TTL_MINUTES} минут.\n")


def send_password_reset_email(recipient_email: str, code: str) -> None:
    send_email(recipient_email, "Код смены пароля ViolentDeck", "Здравствуйте!\n\nВаш код для смены пароля в ViolentDeck: " + code + f"\nКод действует {settings.VERIFICATION_CODE_TTL_MINUTES} минут.\n")


def ensure_user_table_columns() -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    alter_statements = []

    if "role" not in existing_columns:
        alter_statements.append("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) NOT NULL DEFAULT 'customer'")
    if "is_verified" not in existing_columns:
        alter_statements.append("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE")
    if "verification_code" not in existing_columns:
        alter_statements.append("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR(6)")
    if "verification_expires_at" not in existing_columns:
        alter_statements.append("ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_expires_at TIMESTAMP")
    if "password_reset_code" not in existing_columns:
        alter_statements.append("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_code VARCHAR(6)")
    if "password_reset_expires_at" not in existing_columns:
        alter_statements.append("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMP")

    if not alter_statements:
        return

    with engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))


def ensure_order_table_columns() -> None:
    inspector = inspect(engine)
    if not inspector.has_table("orders"):
        return

    existing_columns = {column["name"] for column in inspector.get_columns("orders")}
    alter_statements = []

    if "shipping_address" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS shipping_address TEXT NOT NULL DEFAULT ''"
        )
    if "payment_method" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(30) NOT NULL DEFAULT 'cash'"
        )
    if "checkout_id" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS checkout_id VARCHAR(32) NOT NULL DEFAULT ''"
        )

    if not alter_statements:
        with engine.begin() as connection:
            connection.execute(text("UPDATE orders SET checkout_id = CONCAT('legacy-', id) WHERE checkout_id IS NULL OR checkout_id = ''"))
        return

    with engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))
        connection.execute(text("UPDATE orders SET checkout_id = CONCAT('legacy-', id) WHERE checkout_id IS NULL OR checkout_id = ''"))


def backfill_historical_checkout_ids() -> None:
    with SessionLocal() as db_session:
        orders = list(
            db_session.scalars(
                select(Order).order_by(Order.user_id.asc(), Order.created_at.asc(), Order.id.asc())
            )
        )
        if not orders:
            return

        current_group: list[Order] = []

        def flush_group() -> None:
            if len(current_group) < 2:
                return
            checkout_id = uuid4().hex
            for grouped_order in current_group:
                grouped_order.checkout_id = checkout_id

        for order in orders:
            if not current_group:
                current_group = [order]
                continue

            previous_order = current_group[-1]
            same_customer = order.user_id == previous_order.user_id
            same_address = order.shipping_address == previous_order.shipping_address
            same_payment = order.payment_method == previous_order.payment_method
            same_status = order.status == previous_order.status
            close_in_time = abs((order.created_at - previous_order.created_at).total_seconds()) <= 5
            current_is_legacy = order.checkout_id.startswith("legacy-")
            previous_is_legacy = previous_order.checkout_id.startswith("legacy-")

            if same_customer and same_address and same_payment and same_status and close_in_time and current_is_legacy and previous_is_legacy:
                current_group.append(order)
                continue

            flush_group()
            current_group = [order]

        flush_group()
        db_session.commit()


def ensure_seed_user(seed_user: dict) -> None:
    with SessionLocal() as db_session:
        user = db_session.scalar(select(User).where(User.username == seed_user["username"]))
        if user is None:
            db_session.add(User(username=seed_user["username"], email=seed_user["email"], password_hash=generate_password_hash(seed_user["password"]), role=seed_user["role"], is_verified=True))
            db_session.commit()
            return

        user.email = seed_user["email"]
        user.role = seed_user["role"]
        user.is_verified = True
        user.verification_code = None
        user.verification_expires_at = None
        user.password_reset_code = None
        user.password_reset_expires_at = None
        db_session.commit()


def ensure_seed_categories() -> None:
    with SessionLocal() as db_session:
        for category_data in PRODUCT_CARDS:
            category = db_session.scalar(select(Category).where(Category.slug == category_data["slug"]))
            if category is None:
                db_session.add(
                    Category(
                        slug=category_data["slug"],
                        title=category_data["title"],
                        description=category_data["description"],
                        accent=category_data["accent"],
                        image=category_data["image"],
                        empty_title=category_data["empty_title"],
                        empty_description=category_data["empty_description"],
                    )
                )
                continue

            category.title = category_data["title"]
            category.description = category_data["description"]
            category.accent = category_data["accent"]
            category.image = category_data["image"]
            category.empty_title = category_data["empty_title"]
            category.empty_description = category_data["empty_description"]

        db_session.commit()


def init_db() -> None:
    Base.metadata.create_all(engine)
    ensure_user_table_columns()
    ensure_order_table_columns()
    backfill_historical_checkout_ids()
    ensure_seed_categories()
    ensure_seed_user(DEFAULT_USER)
    ensure_seed_user(ADMIN_USER)


@app.after_request
def persist_action_log(response):
    if request.path.startswith("/static/"):
        return response
    if request.endpoint in {None, "persist_action_log"}:
        return response
    if request.method == "OPTIONS":
        return response

    username = session.get("user") or "anonymous"
    details = build_request_details()

    try:
        with SessionLocal() as db_session:
            db_session.add(
                ActionLog(
                    username=username,
                    method=request.method,
                    path=request.path,
                    endpoint=request.endpoint or "",
                    status_code=response.status_code,
                    details=details,
                )
            )
            db_session.commit()
    except Exception:
        pass

    return response

def get_user_by_username(username: str | None) -> User | None:
    if not username:
        return None
    with SessionLocal() as db_session:
        return db_session.scalar(select(User).where(User.username == username))


def get_user_by_email(email: str | None) -> User | None:
    if not email:
        return None
    with SessionLocal() as db_session:
        return db_session.scalar(select(User).where(User.email == email))


def get_authenticated_user() -> User | None:
    user = get_user_by_username(session.get("user"))
    if user is None or not user.is_verified:
        session.pop("user", None)
        return None
    return user


def get_admin_user() -> User | None:
    user = get_authenticated_user()
    if user is None or user.role != "admin":
        return None
    return user


def save_pending_verification(username: str) -> None:
    session["pending_verification_username"] = username


def clear_pending_verification() -> None:
    session.pop("pending_verification_username", None)


def get_pending_user() -> User | None:
    return get_user_by_username(session.get("pending_verification_username"))


def save_pending_password_reset(username: str) -> None:
    session["pending_password_reset_username"] = username


def clear_pending_password_reset() -> None:
    session.pop("pending_password_reset_username", None)


def get_pending_password_reset_user() -> User | None:
    return get_user_by_username(session.get("pending_password_reset_username"))


def save_pending_forgot_password(username: str) -> None:
    session["pending_forgot_password_username"] = username


def clear_pending_forgot_password() -> None:
    session.pop("pending_forgot_password_username", None)


def get_pending_forgot_password_user() -> User | None:
    return get_user_by_username(session.get("pending_forgot_password_username"))


def issue_new_verification_code(user: User) -> None:
    code = generate_code()
    expires_at = datetime.utcnow() + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES)
    with SessionLocal() as db_session:
        db_user = db_session.scalar(select(User).where(User.id == user.id))
        if db_user is None:
            raise ValueError("Пользователь не найден.")
        db_user.verification_code = code
        db_user.verification_expires_at = expires_at
        db_session.commit()
    send_verification_email(user.email, code)


def issue_password_reset_code(user: User) -> None:
    code = generate_code()
    expires_at = datetime.utcnow() + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES)
    with SessionLocal() as db_session:
        db_user = db_session.scalar(select(User).where(User.id == user.id))
        if db_user is None:
            raise ValueError("Пользователь не найден.")
        db_user.password_reset_code = code
        db_user.password_reset_expires_at = expires_at
        db_session.commit()
    send_password_reset_email(user.email, code)


@app.context_processor
def inject_cart_state():
    return {"cart_count": get_cart_count()}


@app.route("/", methods=["GET"])
def auth_page():
    user = get_authenticated_user()
    if user is not None:
        return build_redirect_after_login(user)
    return render_template("auth.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("register_username", "").strip().lower()
    password = request.form.get("register_password", "")
    email = request.form.get("register_email", "").strip().lower()

    if not username or not password or not email:
        flash("Заполните все поля регистрации.")
        return redirect(url_for("register"))
    if len(password) < 6:
        flash("Пароль должен быть не короче 6 символов.")
        return redirect(url_for("register"))

    verification_code = generate_code()
    verification_expires_at = datetime.utcnow() + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES)

    with SessionLocal() as db_session:
        if db_session.scalar(select(User.id).where(User.username == username)):
            flash("Пользователь с таким логином уже зарегистрирован.")
            return redirect(url_for("register"))
        if db_session.scalar(select(User.id).where(User.email == email)):
            flash("Пользователь с такой почтой уже зарегистрирован.")
            return redirect(url_for("register"))
        db_session.add(User(username=username, email=email, password_hash=generate_password_hash(password), role="customer", is_verified=False, verification_code=verification_code, verification_expires_at=verification_expires_at))
        db_session.commit()

    try:
        send_verification_email(email, verification_code)
    except Exception:
        with SessionLocal() as db_session:
            created_user = db_session.scalar(select(User).where(User.username == username))
            if created_user is not None and not created_user.is_verified:
                db_session.delete(created_user)
                db_session.commit()
        flash("Не удалось отправить код на почту. Проверьте настройки почты и попробуйте снова.")
        return redirect(url_for("register"))

    save_pending_verification(username)
    return redirect(url_for("verify_registration"))


@app.route("/verify", methods=["GET", "POST"])
def verify_registration():
    user = get_pending_user()
    if user is None:
        flash("Сначала зарегистрируйтесь.")
        return redirect(url_for("register"))

    if request.method == "GET":
        return render_template("verify.html", email=user.email, username=user.username)

    code = request.form.get("verification_code", "").strip()
    if not code:
        flash("Введите код подтверждения.")
        return redirect(url_for("verify_registration"))

    with SessionLocal() as db_session:
        db_user = db_session.scalar(select(User).where(User.id == user.id))
        if db_user is None:
            clear_pending_verification()
            flash("Пользователь не найден.")
            return redirect(url_for("register"))
        if db_user.verification_code != code:
            flash("Неверный код подтверждения.")
            return redirect(url_for("verify_registration"))
        if db_user.verification_expires_at is None or db_user.verification_expires_at < datetime.utcnow():
            flash("Срок действия кода истёк. Отправьте код заново.")
            return redirect(url_for("verify_registration"))
        db_user.is_verified = True
        db_user.verification_code = None
        db_user.verification_expires_at = None
        db_session.commit()
        verified_username = db_user.username

    clear_pending_verification()
    session["user"] = verified_username
    return redirect(url_for("shop"))


@app.post("/verify/resend")
def resend_verification_code():
    user = get_pending_user()
    if user is None:
        flash("Сначала зарегистрируйтесь.")
        return redirect(url_for("register"))
    try:
        issue_new_verification_code(user)
    except Exception:
        flash("Не удалось отправить новый код. Попробуйте позже.")
        return redirect(url_for("verify_registration"))
    flash("Новый код отправлен на почту.")
    return redirect(url_for("verify_registration"))


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("login_username", "").strip().lower()
    password = request.form.get("login_password", "")

    user = get_user_by_username(username)
    if user and check_password_hash(user.password_hash, password):
        if not user.is_verified:
            save_pending_verification(username)
            return redirect(url_for("verify_registration"))
        session["user"] = username
        return build_redirect_after_login(user)

    flash("Неверный логин или пароль.")
    return redirect(url_for("auth_page"))


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "GET":
        return render_template("forgot_password.html")

    email = request.form.get("email", "").strip().lower()
    if not email:
        flash("Введите почту.")
        return redirect(url_for("forgot_password"))

    user = get_user_by_email(email)
    if user is None:
        flash("Аккаунт с такой почтой не найден.")
        return redirect(url_for("forgot_password"))

    try:
        issue_password_reset_code(user)
    except Exception:
        flash("Не удалось отправить код для восстановления пароля. Попробуйте позже.")
        return redirect(url_for("forgot_password"))

    save_pending_forgot_password(user.username)
    return redirect(url_for("forgot_password_verify"))


@app.route("/forgot-password/verify", methods=["GET", "POST"])
def forgot_password_verify():
    user = get_pending_forgot_password_user()
    if user is None:
        flash("Сначала введите почту для восстановления пароля.")
        return redirect(url_for("forgot_password"))

    if request.method == "GET":
        return render_template("forgot_password_verify.html", user=user_to_dict(user))

    code = request.form.get("reset_code", "").strip()
    new_password = request.form.get("new_password", "")

    if not code or not new_password:
        flash("Введите код и новый пароль.")
        return redirect(url_for("forgot_password_verify"))
    if len(new_password) < 6:
        flash("Пароль должен быть не короче 6 символов.")
        return redirect(url_for("forgot_password_verify"))

    with SessionLocal() as db_session:
        db_user = db_session.scalar(select(User).where(User.id == user.id))
        if db_user is None:
            clear_pending_forgot_password()
            flash("Пользователь не найден.")
            return redirect(url_for("forgot_password"))
        if db_user.password_reset_code != code:
            flash("Неверный код для восстановления пароля.")
            return redirect(url_for("forgot_password_verify"))
        if db_user.password_reset_expires_at is None or db_user.password_reset_expires_at < datetime.utcnow():
            flash("Срок действия кода истёк. Запросите новый код.")
            return redirect(url_for("forgot_password_verify"))
        db_user.password_hash = generate_password_hash(new_password)
        db_user.password_reset_code = None
        db_user.password_reset_expires_at = None
        db_session.commit()

    clear_pending_forgot_password()
    flash("Пароль изменён. Теперь войдите в аккаунт.")
    return redirect(url_for("auth_page"))


@app.post("/forgot-password/resend")
def forgot_password_resend():
    user = get_pending_forgot_password_user()
    if user is None:
        flash("Сначала введите почту для восстановления пароля.")
        return redirect(url_for("forgot_password"))
    try:
        issue_password_reset_code(user)
    except Exception:
        flash("Не удалось отправить новый код для восстановления пароля.")
        return redirect(url_for("forgot_password_verify"))
    flash("Новый код отправлен на почту.")
    return redirect(url_for("forgot_password_verify"))

@app.route("/shop")
def shop():
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))
    return render_template("home.html", user=user_to_dict(user), products=get_categories(), get_image_source=get_image_source)


@app.route("/shop/category/<slug>")
def category_page(slug: str):
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))

    category = get_category_by_slug(slug)
    if category is None:
        flash("Категория не найдена.")
        return redirect(url_for("shop"))

    page = parse_page_arg()
    with SessionLocal() as db_session:
        statement = select(Product).where(Product.category_slug == slug).order_by(Product.created_at.desc(), Product.id.desc())
        products, page, total_pages, total = paginate_statement(db_session, statement, page)

    return render_template("category.html", user=user_to_dict(user), category=category, products=products, page=page, total_pages=total_pages, total=total, get_image_source=get_image_source)


@app.post("/cart/add")
def add_to_cart():
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))
    if user.role == "admin":
        flash("Корзина доступна только пользователям.")
        return redirect(url_for("shop"))

    product_id_raw = request.form.get("product_id", "").strip()
    category_slug = request.form.get("category_slug", "").strip()
    page_raw = request.form.get("page", "1").strip()
    quantity_raw = request.form.get("quantity", "1").strip()

    try:
        product_id = int(product_id_raw)
    except ValueError:
        flash("Не удалось добавить товар: товар не найден.")
        return redirect(url_for("shop"))

    try:
        page = max(1, int(page_raw))
    except ValueError:
        page = 1

    try:
        quantity = max(1, int(quantity_raw))
    except ValueError:
        quantity = 1

    with SessionLocal() as db_session:
        product = db_session.scalar(select(Product).where(Product.id == product_id))
        if product is None:
            flash("Не удалось добавить товар: товар не найден.")
            return redirect(url_for("shop"))

    cart = get_cart()
    cart_key = str(product_id)
    cart[cart_key] = cart.get(cart_key, 0) + quantity
    save_cart(cart)

    flash("Товар добавлен в корзину.")
    if category_slug:
        return redirect(url_for("category_page", slug=category_slug, page=page))
    return redirect(url_for("cart_page"))


@app.route("/cart")
def cart_page():
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))
    if user.role == "admin":
        return redirect(url_for("shop"))

    cart = get_cart()
    product_ids = []
    for product_id in cart.keys():
        try:
            product_ids.append(int(product_id))
        except ValueError:
            continue

    with SessionLocal() as db_session:
        products = list(db_session.scalars(select(Product).where(Product.id.in_(product_ids)))) if product_ids else []

    products_by_id = {product.id: product for product in products}
    cart_items = []
    cart_total = Decimal("0.00")
    for product_id, quantity in cart.items():
        try:
            product = products_by_id.get(int(product_id))
        except ValueError:
            product = None
        if product is None:
            continue
        item_total = product.price * quantity
        cart_total += item_total
        cart_items.append(
            {
                "product_id": product.id,
                "name": product.name,
                "price": product.price,
                "quantity": quantity,
                "item_total": item_total,
                "image_url": product.image_url,
                "category_slug": product.category_slug,
            }
        )

    return render_template(
        "cart.html",
        user=user_to_dict(user),
        cart_items=cart_items,
        cart_total=cart_total,
        get_image_source=get_image_source,
    )


@app.post("/cart/update")
def update_cart_item():
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))

    product_id = request.form.get("product_id", "").strip()
    quantity_raw = request.form.get("quantity", "1").strip()
    cart = get_cart()

    if product_id not in cart:
        return redirect(url_for("cart_page"))

    try:
        quantity = int(quantity_raw)
    except ValueError:
        quantity = cart[product_id]

    if quantity <= 0:
        cart.pop(product_id, None)
    else:
        cart[product_id] = quantity

    save_cart(cart)
    return redirect(url_for("cart_page"))


@app.post("/cart/remove")
def remove_from_cart():
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))

    product_id = request.form.get("product_id", "").strip()
    cart = get_cart()
    cart.pop(product_id, None)
    save_cart(cart)
    flash("Товар удалён из корзины.")
    return redirect(url_for("cart_page"))


@app.post("/orders/create")
def create_order():
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))
    if user.role == "admin":
        flash("Оформление заказов доступно только пользователям.")
        return redirect(url_for("shop"))

    shipping_address = request.form.get("shipping_address", "").strip()
    payment_method = normalize_payment_method(request.form.get("payment_method"))
    if not shipping_address:
        flash("Укажите адрес доставки.")
        return redirect(url_for("cart_page"))

    cart = get_cart()
    if not cart:
        flash("Корзина пуста.")
        return redirect(url_for("cart_page"))

    product_ids = []
    for product_id in cart.keys():
        try:
            product_ids.append(int(product_id))
        except ValueError:
            continue

    with SessionLocal() as db_session:
        products = list(db_session.scalars(select(Product).where(Product.id.in_(product_ids)))) if product_ids else []
        products_by_id = {product.id: product for product in products}
        created_orders = 0
        checkout_id = uuid4().hex

        for product_id, quantity in cart.items():
            try:
                product = products_by_id.get(int(product_id))
            except ValueError:
                product = None
            if product is None:
                continue

            db_session.add(
                Order(
                    user_id=user.id,
                    checkout_id=checkout_id,
                    product_id=product.id,
                    quantity=quantity,
                    total_price=product.price * quantity,
                    shipping_address=shipping_address,
                    payment_method=payment_method,
                    status="new",
                )
            )
            created_orders += 1

        db_session.commit()

    if created_orders == 0:
        flash("Не удалось оформить заказ: корзина пуста или товары недоступны.")
        return redirect(url_for("cart_page"))

    clear_cart()
    flash("Заказ успешно оформлен.")
    return redirect(url_for("profile"))


@app.route("/profile")
def profile():
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))

    with SessionLocal() as db_session:
        orders = list(
            db_session.scalars(
                select(Order)
                .where(Order.user_id == user.id)
                .order_by(Order.created_at.desc(), Order.id.desc())
            )
        )
        product_ids = [order.product_id for order in orders]
        products = list(db_session.scalars(select(Product).where(Product.id.in_(product_ids)))) if product_ids else []

    products_by_id = {product.id: product for product in products}
    orders_data = build_grouped_orders(orders, products_by_id)[:10]
    return render_template("profile.html", user=user_to_dict(user), orders=orders_data, get_image_source=get_image_source)


@app.route("/orders/<int:order_id>")
def order_detail(order_id: int):
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))
    if user.role == "admin":
        return redirect(url_for("admin_orders"))

    with SessionLocal() as db_session:
        anchor_order = db_session.scalar(select(Order).where(Order.id == order_id, Order.user_id == user.id))
        if anchor_order is None:
            flash("Заказ не найден.")
            return redirect(url_for("profile"))

        checkout_id = get_checkout_id(anchor_order)
        order_rows = list(
            db_session.scalars(
                select(Order)
                .where(Order.user_id == user.id, Order.checkout_id == checkout_id)
                .order_by(Order.id.asc())
            )
        )
        if not order_rows:
            order_rows = [anchor_order]
        product_ids = [order.product_id for order in order_rows]
        products = list(db_session.scalars(select(Product).where(Product.id.in_(product_ids)))) if product_ids else []

    products_by_id = {product.id: product for product in products}
    grouped_orders = build_grouped_orders(order_rows, products_by_id)
    order_data = grouped_orders[0] if grouped_orders else build_grouped_orders([anchor_order], products_by_id)[0]
    return render_template(
        "order_detail.html",
        user=user_to_dict(user),
        order=order_data,
        get_image_source=get_image_source,
    )


@app.post("/profile/password/send-code")
def send_password_reset_code_route():
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))
    try:
        issue_password_reset_code(user)
    except Exception:
        flash("Не удалось отправить код для смены пароля. Попробуйте позже.")
        return redirect(url_for("profile"))
    save_pending_password_reset(user.username)
    flash("Код для смены пароля отправлен на почту.")
    return redirect(url_for("verify_password_reset"))


@app.route("/profile/password/verify", methods=["GET", "POST"])
def verify_password_reset():
    current_user = get_authenticated_user()
    pending_user = get_pending_password_reset_user()
    if current_user is None:
        clear_pending_password_reset()
        return redirect(url_for("auth_page"))
    if pending_user is None or pending_user.username != current_user.username:
        flash("Сначала запросите код для смены пароля.")
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template("password_reset_verify.html", user=user_to_dict(current_user))

    code = request.form.get("reset_code", "").strip()
    new_password = request.form.get("new_password", "")
    if not code or not new_password:
        flash("Введите код и новый пароль.")
        return redirect(url_for("verify_password_reset"))
    if len(new_password) < 6:
        flash("Пароль должен быть не короче 6 символов.")
        return redirect(url_for("verify_password_reset"))

    with SessionLocal() as db_session:
        db_user = db_session.scalar(select(User).where(User.id == current_user.id))
        if db_user is None or not db_user.is_verified:
            session.pop("user", None)
            clear_pending_password_reset()
            return redirect(url_for("auth_page"))
        if db_user.password_reset_code != code:
            flash("Неверный код для смены пароля.")
            return redirect(url_for("verify_password_reset"))
        if db_user.password_reset_expires_at is None or db_user.password_reset_expires_at < datetime.utcnow():
            flash("Срок действия кода истёк. Запросите новый код.")
            return redirect(url_for("verify_password_reset"))
        db_user.password_hash = generate_password_hash(new_password)
        db_user.password_reset_code = None
        db_user.password_reset_expires_at = None
        db_session.commit()

    clear_pending_password_reset()
    flash("Пароль успешно изменён.")
    return redirect(url_for("profile"))


@app.post("/profile/password/resend")
def resend_password_reset_code():
    current_user = get_authenticated_user()
    pending_user = get_pending_password_reset_user()
    if current_user is None:
        clear_pending_password_reset()
        return redirect(url_for("auth_page"))
    if pending_user is None or pending_user.username != current_user.username:
        flash("Сначала запросите код для смены пароля.")
        return redirect(url_for("profile"))
    try:
        issue_password_reset_code(current_user)
    except Exception:
        flash("Не удалось отправить новый код для смены пароля.")
        return redirect(url_for("verify_password_reset"))
    flash("Новый код для смены пароля отправлен на почту.")
    return redirect(url_for("verify_password_reset"))


@app.route("/admin")
def admin_dashboard():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    with SessionLocal() as db_session:
        users_count = db_session.scalar(select(func.count(User.id))) or 0
        products_count = db_session.scalar(select(func.count(Product.id))) or 0
        categories = list(db_session.scalars(select(Category).order_by(Category.created_at.asc(), Category.id.asc())))
        category_counts = []
        for category in categories:
            count = db_session.scalar(select(func.count(Product.id)).where(Product.category_slug == category.slug)) or 0
            category_counts.append({"title": category.title, "count": count})

    return render_template("admin_dashboard.html", user=user_to_dict(admin_user), users_count=users_count, products_count=products_count, category_counts=category_counts)


@app.get("/admin/logs/export")
def admin_export_logs():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    time_from = datetime.utcnow() - timedelta(minutes=10)
    with SessionLocal() as db_session:
        logs = list(
            db_session.scalars(
                select(ActionLog)
                .where(ActionLog.created_at >= time_from)
                .order_by(ActionLog.created_at.desc(), ActionLog.id.desc())
            )
        )

    lines = []
    for log in logs:
        base_line = f"[{log.created_at.strftime('%Y-%m-%d %H:%M:%S')}] {log.username} {log.method} {log.path} endpoint={log.endpoint} status={log.status_code}"
        if log.details:
            base_line += f" details={log.details}"
        lines.append(base_line)

    content = "\n".join(lines) if lines else "За последние 10 минут действий не найдено."
    return Response(
        content,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="app-actions-last-10-minutes.log"'},
    )


@app.route("/admin/users")
def admin_users():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = parse_page_arg()
    search_query = request.args.get("q", "").strip().lower()
    role_filter = request.args.get("role", "all").strip().lower()
    verified_filter = request.args.get("verified", "all").strip().lower()
    if role_filter not in {"all", "customer", "admin"}:
        role_filter = "all"
    if verified_filter not in {"all", "verified", "unverified"}:
        verified_filter = "all"

    with SessionLocal() as db_session:
        statement = select(User)
        if search_query:
            pattern = f"%{search_query}%"
            statement = statement.where(or_(User.username.ilike(pattern), User.email.ilike(pattern)))
        if role_filter != "all":
            statement = statement.where(User.role == role_filter)
        if verified_filter == "verified":
            statement = statement.where(User.is_verified.is_(True))
        elif verified_filter == "unverified":
            statement = statement.where(User.is_verified.is_(False))
        statement = statement.order_by(User.id.desc())
        users, page, total_pages, total = paginate_statement(db_session, statement, page)

    return render_template(
        "admin_users.html",
        user=user_to_dict(admin_user),
        users=users,
        page=page,
        total_pages=total_pages,
        total=total,
        search_query=search_query,
        selected_role=role_filter,
        selected_verified=verified_filter,
    )


@app.post("/admin/users/create")
def admin_create_user():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role = normalize_role(request.form.get("role"))
    is_verified = request.form.get("is_verified") == "on"

    if not username or not email or not password:
        flash("Логин, почта и пароль обязательны.")
        return redirect(url_for("admin_users"))
    if len(password) < 6:
        flash("Пароль должен быть не короче 6 символов.")
        return redirect(url_for("admin_users"))

    with SessionLocal() as db_session:
        username_owner = db_session.scalar(select(User.id).where(User.username == username))
        if username_owner is not None:
            flash("Логин уже занят другим пользователем.")
            return redirect(url_for("admin_users"))
        email_owner = db_session.scalar(select(User.id).where(User.email == email))
        if email_owner is not None:
            flash("Почта уже занята другим пользователем.")
            return redirect(url_for("admin_users"))

        db_session.add(
            User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                role=role,
                is_verified=is_verified,
                verification_code=None,
                verification_expires_at=None,
                password_reset_code=None,
                password_reset_expires_at=None,
            )
        )
        db_session.commit()

    flash("Пользователь добавлен.")
    return redirect(url_for("admin_users"))


@app.post("/admin/users/<int:user_id>/update")
def admin_update_user(user_id: int):
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = request.form.get("page", "1")
    search_query = request.form.get("q", "").strip().lower()
    role_filter = request.form.get("role_filter", "all").strip().lower()
    verified_filter = request.form.get("verified_filter", "all").strip().lower()
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower()
    role = normalize_role(request.form.get("role"))
    is_verified = request.form.get("is_verified") == "on"

    if not username or not email:
        flash("Логин и почта обязательны.")
        return redirect(url_for("admin_users", page=page, q=search_query, role=role_filter, verified=verified_filter))

    with SessionLocal() as db_session:
        target_user = db_session.scalar(select(User).where(User.id == user_id))
        if target_user is None:
            flash("Пользователь не найден.")
            return redirect(url_for("admin_users", page=page, q=search_query, role=role_filter, verified=verified_filter))
        username_owner = db_session.scalar(select(User.id).where(User.username == username, User.id != user_id))
        if username_owner is not None:
            flash("Логин уже занят другим пользователем.")
            return redirect(url_for("admin_users", page=page, q=search_query, role=role_filter, verified=verified_filter))
        email_owner = db_session.scalar(select(User.id).where(User.email == email, User.id != user_id))
        if email_owner is not None:
            flash("Почта уже занята другим пользователем.")
            return redirect(url_for("admin_users", page=page, q=search_query, role=role_filter, verified=verified_filter))

        target_user.username = username
        target_user.email = email
        target_user.role = role
        target_user.is_verified = is_verified
        if not is_verified:
            target_user.verification_code = None
            target_user.verification_expires_at = None
        db_session.commit()
        if admin_user.id == target_user.id:
            session["user"] = target_user.username
            updated_role = target_user.role
        else:
            updated_role = admin_user.role

    flash("Данные пользователя обновлены.")
    if admin_user.id == user_id and updated_role != "admin":
        return redirect(url_for("shop"))
    return redirect(url_for("admin_users", page=page, q=search_query, role=role_filter, verified=verified_filter))


@app.post("/admin/users/<int:user_id>/delete")
def admin_delete_user(user_id: int):
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = request.form.get("page", "1")
    search_query = request.form.get("q", "").strip().lower()
    role_filter = request.form.get("role_filter", "all").strip().lower()
    verified_filter = request.form.get("verified_filter", "all").strip().lower()

    if admin_user.id == user_id:
        flash("Нельзя удалить текущего администратора.")
        return redirect(url_for("admin_users", page=page, q=search_query, role=role_filter, verified=verified_filter))

    with SessionLocal() as db_session:
        target_user = db_session.scalar(select(User).where(User.id == user_id))
        if target_user is None:
            flash("Пользователь не найден.")
            return redirect(url_for("admin_users", page=page, q=search_query, role=role_filter, verified=verified_filter))

        if target_user.role == "admin":
            admins_count = db_session.scalar(select(func.count(User.id)).where(User.role == "admin")) or 0
            if admins_count <= 1:
                flash("Нельзя удалить последнего администратора.")
                return redirect(url_for("admin_users", page=page, q=search_query, role=role_filter, verified=verified_filter))

        db_session.delete(target_user)
        db_session.commit()

    flash("Пользователь удалён.")
    return redirect(url_for("admin_users", page=page, q=search_query, role=role_filter, verified=verified_filter))


@app.get("/admin/users/export")
def admin_export_users():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    with SessionLocal() as db_session:
        users = list(db_session.scalars(select(User).order_by(User.id.asc())))

    payload = [
        {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "password_hash": user.password_hash,
            "role": user.role,
            "is_verified": user.is_verified,
        }
        for user in users
    ]
    return make_json_download("users-export.json", payload)


@app.post("/admin/users/import")
def admin_import_users():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    payload = load_json_upload()
    if payload is None:
        return redirect(url_for("admin_users"))

    imported_count = 0
    with SessionLocal() as db_session:
        for item in payload:
            if not isinstance(item, dict):
                continue

            username = str(item.get("username", "")).strip().lower()
            email = str(item.get("email", "")).strip().lower()
            password_hash = str(item.get("password_hash", "")).strip()
            if not username or not email or not password_hash:
                continue

            user = db_session.scalar(select(User).where(User.username == username))
            if user is None:
                user = db_session.scalar(select(User).where(User.email == email))

            if user is None:
                user = User(
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    role=normalize_role(item.get("role")),
                    is_verified=bool(item.get("is_verified", False)),
                )
                db_session.add(user)
            else:
                user.username = username
                user.email = email
                user.password_hash = password_hash
                user.role = normalize_role(item.get("role"))
                user.is_verified = bool(item.get("is_verified", False))
                if not user.is_verified:
                    user.verification_code = None
                    user.verification_expires_at = None

            imported_count += 1

        db_session.commit()

    flash(f"Импортировано пользователей: {imported_count}.")
    return redirect(url_for("admin_users"))


@app.route("/admin/products")
def admin_products():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = parse_page_arg()
    category_filter = request.args.get("category", "all").strip().lower()
    search_query = request.args.get("q", "").strip()

    with SessionLocal() as db_session:
        categories = list(db_session.scalars(select(Category).order_by(Category.created_at.asc(), Category.id.asc())))
        category_slugs = {category.slug for category in categories}
        if category_filter != "all" and category_filter not in category_slugs:
            category_filter = "all"
        statement = select(Product)
        if category_filter != "all":
            statement = statement.where(Product.category_slug == category_filter)
        if search_query:
            pattern = f"%{search_query}%"
            statement = statement.where(or_(Product.name.ilike(pattern), Product.description.ilike(pattern)))
        statement = statement.order_by(Product.created_at.desc(), Product.id.desc())
        products, page, total_pages, total = paginate_statement(db_session, statement, page)

    return render_template(
        "admin_products.html",
        user=user_to_dict(admin_user),
        categories=categories,
        products=products,
        page=page,
        total_pages=total_pages,
        total=total,
        selected_category=category_filter,
        search_query=search_query,
        get_image_source=get_image_source,
    )


@app.route("/admin/orders")
def admin_orders():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = parse_page_arg()
    search_query = request.args.get("q", "").strip().lower()
    status_filter = request.args.get("status", "all").strip().lower()
    payment_filter = request.args.get("payment", "all").strip().lower()
    allowed_statuses = {value for value, _ in ORDER_STATUSES}
    allowed_payments = {value for value, _ in PAYMENT_METHODS}
    if status_filter not in {"all", *allowed_statuses}:
        status_filter = "all"
    if payment_filter not in {"all", *allowed_payments}:
        payment_filter = "all"

    with SessionLocal() as db_session:
        statement = select(Order)
        if status_filter != "all":
            statement = statement.where(Order.status == status_filter)
        if payment_filter != "all":
            statement = statement.where(Order.payment_method == payment_filter)
        if search_query:
            pattern = f"%{search_query}%"
            user_ids_subquery = select(User.id).where(or_(User.username.ilike(pattern), User.email.ilike(pattern)))
            product_ids_subquery = select(Product.id).where(Product.name.ilike(pattern))
            conditions = [
                Order.shipping_address.ilike(pattern),
                Order.user_id.in_(user_ids_subquery),
                Order.product_id.in_(product_ids_subquery),
            ]
            if search_query.isdigit():
                conditions.append(Order.id == int(search_query))
            statement = statement.where(or_(*conditions))
        statement = statement.order_by(Order.created_at.desc(), Order.id.desc())
        matched_orders = list(db_session.scalars(statement))
        checkout_ids = [get_checkout_id(order) for order in matched_orders]
        if checkout_ids:
            orders = list(
                db_session.scalars(
                    select(Order)
                    .where(Order.checkout_id.in_(checkout_ids))
                    .order_by(Order.created_at.desc(), Order.id.desc())
                )
            )
        else:
            orders = []

        user_ids = [order.user_id for order in orders]
        product_ids = [order.product_id for order in orders]
        users = list(db_session.scalars(select(User).where(User.id.in_(user_ids)))) if user_ids else []
        products = list(db_session.scalars(select(Product).where(Product.id.in_(product_ids)))) if product_ids else []

    users_by_id = {user.id: user for user in users}
    products_by_id = {product.id: product for product in products}
    orders_data = build_grouped_orders(orders, products_by_id, users_by_id)
    orders_data, page, total_pages, total = paginate_list(orders_data, page)

    return render_template(
        "admin_orders.html",
        user=user_to_dict(admin_user),
        orders=orders_data,
        order_statuses=ORDER_STATUSES,
        payment_methods=PAYMENT_METHODS,
        page=page,
        total_pages=total_pages,
        total=total,
        search_query=search_query,
        selected_status=status_filter,
        selected_payment=payment_filter,
    )


@app.get("/admin/orders/export")
def admin_export_orders():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    with SessionLocal() as db_session:
        orders = list(db_session.scalars(select(Order).order_by(Order.id.asc())))
        users = {user.id: user for user in db_session.scalars(select(User))}

    payload = [
        {
            "id": order.id,
            "checkout_id": order.checkout_id,
            "user_id": order.user_id,
            "username": users.get(order.user_id).username if users.get(order.user_id) is not None else "",
            "product_id": order.product_id,
            "quantity": order.quantity,
            "total_price": str(order.total_price),
            "shipping_address": order.shipping_address,
            "payment_method": order.payment_method,
            "status": order.status,
            "created_at": order.created_at.isoformat(),
        }
        for order in orders
    ]
    return make_json_download("orders-export.json", payload)


@app.post("/admin/orders/import")
def admin_import_orders():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    payload = load_json_upload()
    if payload is None:
        return redirect(url_for("admin_orders"))

    imported_count = 0
    with SessionLocal() as db_session:
        for item in payload:
            if not isinstance(item, dict):
                continue

            quantity = item.get("quantity")
            product_id = item.get("product_id")
            shipping_address = str(item.get("shipping_address", "")).strip()
            total_price_raw = str(item.get("total_price", "")).strip()
            if not shipping_address:
                continue

            try:
                quantity = int(quantity)
                product_id = int(product_id)
                total_price = Decimal(total_price_raw)
            except (TypeError, ValueError, InvalidOperation):
                continue

            if quantity <= 0:
                continue

            user = None
            username = str(item.get("username", "")).strip().lower()
            user_id = item.get("user_id")
            if username:
                user = db_session.scalar(select(User).where(User.username == username))
            if user is None and user_id is not None:
                try:
                    user = db_session.scalar(select(User).where(User.id == int(user_id)))
                except (TypeError, ValueError):
                    user = None

            product = db_session.scalar(select(Product).where(Product.id == product_id))
            if user is None or product is None:
                continue

            order = None
            raw_id = item.get("id")
            if raw_id is not None:
                try:
                    order = db_session.scalar(select(Order).where(Order.id == int(raw_id)))
                except (TypeError, ValueError):
                    order = None

            created_at = parse_datetime_value(item.get("created_at"))
            checkout_id = str(item.get("checkout_id", "")).strip() or uuid4().hex
            payment_method = normalize_payment_method(item.get("payment_method"))
            status = normalize_order_status(item.get("status"))

            if order is None:
                order = Order(
                    user_id=user.id,
                    checkout_id=checkout_id,
                    product_id=product.id,
                    quantity=quantity,
                    total_price=total_price.quantize(Decimal("0.01")),
                    shipping_address=shipping_address,
                    payment_method=payment_method,
                    status=status,
                )
                if created_at is not None:
                    order.created_at = created_at
                db_session.add(order)
            else:
                order.user_id = user.id
                order.checkout_id = checkout_id
                order.product_id = product.id
                order.quantity = quantity
                order.total_price = total_price.quantize(Decimal("0.01"))
                order.shipping_address = shipping_address
                order.payment_method = payment_method
                order.status = status
                if created_at is not None:
                    order.created_at = created_at

            imported_count += 1

        db_session.commit()

    flash(f"Импортировано заказов: {imported_count}.")
    return redirect(url_for("admin_orders"))


@app.post("/admin/orders/<int:order_id>/update")
def admin_update_order(order_id: int):
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = request.form.get("page", "1")
    search_query = request.form.get("q", "").strip().lower()
    status_filter = request.form.get("status_filter", "all").strip().lower()
    payment_filter = request.form.get("payment_filter", "all").strip().lower()
    shipping_address = request.form.get("shipping_address", "").strip()
    status = normalize_order_status(request.form.get("status"))
    payment_method = normalize_payment_method(request.form.get("payment_method"))
    if not shipping_address:
        flash("Укажите адрес доставки.")
        return redirect(url_for("admin_orders", page=page, q=search_query, status=status_filter, payment=payment_filter))

    with SessionLocal() as db_session:
        anchor_order = db_session.scalar(select(Order).where(Order.id == order_id))
        if anchor_order is None:
            flash("Заказ не найден.")
            return redirect(url_for("admin_orders", page=page, q=search_query, status=status_filter, payment=payment_filter))
        checkout_id = get_checkout_id(anchor_order)
        orders = list(db_session.scalars(select(Order).where(Order.checkout_id == checkout_id)))
        if not orders:
            orders = [anchor_order]

        for order in orders:
            order.shipping_address = shipping_address
            order.payment_method = payment_method
            order.status = status
        db_session.commit()

    flash("Заказ обновлён.")
    return redirect(url_for("admin_orders", page=page, q=search_query, status=status_filter, payment=payment_filter))


@app.post("/admin/orders/<int:order_id>/delete")
def admin_delete_order(order_id: int):
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = request.form.get("page", "1")
    search_query = request.form.get("q", "").strip().lower()
    status_filter = request.form.get("status_filter", "all").strip().lower()
    payment_filter = request.form.get("payment_filter", "all").strip().lower()
    with SessionLocal() as db_session:
        anchor_order = db_session.scalar(select(Order).where(Order.id == order_id))
        if anchor_order is None:
            flash("Заказ не найден.")
            return redirect(url_for("admin_orders", page=page, q=search_query, status=status_filter, payment=payment_filter))
        checkout_id = get_checkout_id(anchor_order)
        orders = list(db_session.scalars(select(Order).where(Order.checkout_id == checkout_id)))
        if not orders:
            orders = [anchor_order]
        for order in orders:
            db_session.delete(order)
        db_session.commit()

    flash("Заказ удалён.")
    return redirect(url_for("admin_orders", page=page, q=search_query, status=status_filter, payment=payment_filter))


@app.post("/admin/products/create")
def admin_create_product():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    category_slug = request.form.get("category_slug", "")
    search_query = request.form.get("q", "").strip()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    image_url = request.form.get("image_url", "").strip()
    price_raw = request.form.get("price", "").strip()

    with SessionLocal() as db_session:
        category = db_session.scalar(select(Category).where(Category.slug == category_slug))
        if category is None:
            flash("Выберите корректную категорию.")
            return redirect(url_for("admin_products", q=search_query))
        if not name or not description or not price_raw:
            flash("Заполните название, описание и цену товара.")
            return redirect(url_for("admin_products", category=category_slug, q=search_query))

        try:
            price = Decimal(price_raw)
        except InvalidOperation:
            flash("Цена должна быть числом.")
            return redirect(url_for("admin_products", category=category_slug, q=search_query))

        if price <= 0:
            flash("Цена должна быть больше нуля.")
            return redirect(url_for("admin_products", category=category_slug, q=search_query))

        db_session.add(Product(category_slug=category_slug, name=name, description=description, image_url=image_url or category.image, price=price.quantize(Decimal("0.01"))))
        db_session.commit()

    flash("Товар добавлен.")
    return redirect(url_for("admin_products", category=category_slug, q=search_query))


@app.post("/admin/products/<int:product_id>/update")
def admin_update_product(product_id: int):
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = request.form.get("page", "1")
    category_filter = request.form.get("category_filter", "all").strip().lower()
    search_query = request.form.get("q", "").strip()
    category_slug = request.form.get("category_slug", "").strip()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    image_url = request.form.get("image_url", "").strip()
    price_raw = request.form.get("price", "").strip()

    with SessionLocal() as db_session:
        product = db_session.scalar(select(Product).where(Product.id == product_id))
        if product is None:
            flash("Товар не найден.")
            return redirect(url_for("admin_products", page=page, category=category_filter, q=search_query))

        category = db_session.scalar(select(Category).where(Category.slug == category_slug))
        if category is None:
            flash("Выберите корректную категорию.")
            return redirect(url_for("admin_products", page=page, category=category_filter, q=search_query))
        if not name or not description or not price_raw:
            flash("Заполните название, описание и цену товара.")
            return redirect(url_for("admin_products", page=page, category=category_filter, q=search_query))

        try:
            price = Decimal(price_raw)
        except InvalidOperation:
            flash("Цена должна быть числом.")
            return redirect(url_for("admin_products", page=page, category=category_filter, q=search_query))

        if price <= 0:
            flash("Цена должна быть больше нуля.")
            return redirect(url_for("admin_products", page=page, category=category_filter, q=search_query))

        product.category_slug = category_slug
        product.name = name
        product.description = description
        product.image_url = image_url or category.image
        product.price = price.quantize(Decimal("0.01"))
        db_session.commit()

    flash("Товар обновлён.")
    return redirect(url_for("admin_products", page=page, category=category_filter, q=search_query))


@app.post("/admin/categories/create")
def admin_create_category():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    title = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    image = request.form.get("image", "").strip()

    slug = normalize_slug(title)
    if not slug or not title or not description:
        flash("Укажите название и описание категории.")
        return redirect(url_for("admin_products"))

    if not image:
        image = "images/skate.png"
    accent = title
    empty_title = "Товары скоро появятся"
    empty_description = f"Мы уже готовим каталог для категории {title}."

    with SessionLocal() as db_session:
        existing_category = db_session.scalar(select(Category).where(Category.slug == slug))
        if existing_category is not None:
            flash("Категория с таким slug уже существует.")
            return redirect(url_for("admin_products"))

        db_session.add(
            Category(
                slug=slug,
                title=title,
                description=description,
                accent=accent,
                image=image,
                empty_title=empty_title,
                empty_description=empty_description,
            )
        )
        db_session.commit()

    flash("Категория добавлена.")
    return redirect(url_for("admin_products", category=slug))


@app.get("/admin/products/export")
def admin_export_products():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    with SessionLocal() as db_session:
        products = list(db_session.scalars(select(Product).order_by(Product.id.asc())))

    payload = [
        {
            "id": product.id,
            "category_slug": product.category_slug,
            "name": product.name,
            "description": product.description,
            "image_url": product.image_url,
            "price": str(product.price),
            "created_at": product.created_at.isoformat(),
        }
        for product in products
    ]
    return make_json_download("products-export.json", payload)


@app.post("/admin/products/import")
def admin_import_products():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    payload = load_json_upload()
    if payload is None:
        return redirect(url_for("admin_products"))

    imported_count = 0
    with SessionLocal() as db_session:
        for item in payload:
            if not isinstance(item, dict):
                continue

            category_slug = str(item.get("category_slug", "")).strip().lower()
            name = str(item.get("name", "")).strip()
            description = str(item.get("description", "")).strip()
            image_url = str(item.get("image_url", "")).strip()
            price_raw = str(item.get("price", "")).strip()
            if not category_slug or not name or not description or not price_raw:
                continue

            try:
                price = Decimal(price_raw)
            except InvalidOperation:
                continue

            if price <= 0:
                continue

            category = ensure_category_for_import(db_session, category_slug)
            product = None
            raw_id = item.get("id")
            if raw_id is not None:
                try:
                    product = db_session.scalar(select(Product).where(Product.id == int(raw_id)))
                except (TypeError, ValueError):
                    product = None
            if product is None:
                product = db_session.scalar(select(Product).where(Product.name == name, Product.category_slug == category.slug))

            created_at = parse_datetime_value(item.get("created_at"))
            if product is None:
                product = Product(
                    category_slug=category.slug,
                    name=name,
                    description=description,
                    image_url=image_url or category.image,
                    price=price.quantize(Decimal("0.01")),
                )
                if created_at is not None:
                    product.created_at = created_at
                db_session.add(product)
            else:
                product.category_slug = category.slug
                product.name = name
                product.description = description
                product.image_url = image_url or category.image
                product.price = price.quantize(Decimal("0.01"))
                if created_at is not None:
                    product.created_at = created_at

            imported_count += 1

        db_session.commit()

    flash(f"Импортировано товаров: {imported_count}.")
    return redirect(url_for("admin_products"))


@app.post("/admin/products/<int:product_id>/delete")
def admin_delete_product(product_id: int):
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = request.form.get("page", "1")
    category_filter = request.form.get("category_filter", "all").strip().lower()
    search_query = request.form.get("q", "").strip()

    with SessionLocal() as db_session:
        product = db_session.scalar(select(Product).where(Product.id == product_id))
        if product is None:
            flash("Товар не найден.")
            return redirect(url_for("admin_products", page=page, category=category_filter, q=search_query))

        db_session.delete(product)
        db_session.commit()

    flash("Товар удалён.")
    return redirect(url_for("admin_products", page=page, category=category_filter, q=search_query))


@app.route("/logout")
def logout():
    session.pop("user", None)
    clear_pending_verification()
    clear_pending_password_reset()
    clear_pending_forgot_password()
    clear_cart()
    return redirect(url_for("auth_page"))


init_db()


if __name__ == "__main__":
    app.run(debug=True)
