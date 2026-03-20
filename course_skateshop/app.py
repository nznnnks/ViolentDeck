from decimal import Decimal, InvalidOperation
import random
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

from flask import Flask, flash, redirect, render_template, request, session, url_for
from sqlalchemy import (
    Boolean,
    DateTime,
    Numeric,
    String,
    Text,
    create_engine,
    func,
    inspect,
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


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_slug: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)


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


def build_redirect_after_login(user: User):
    return redirect(url_for("admin_dashboard" if user.role == "admin" else "shop"))


def get_category_by_slug(slug: str) -> dict | None:
    return next((category for category in PRODUCT_CARDS if category["slug"] == slug), None)


def get_image_source(image_value: str) -> str:
    if image_value.startswith(("http://", "https://", "/")):
        return image_value
    return url_for("static", filename=image_value)


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


def init_db() -> None:
    Base.metadata.create_all(engine)
    ensure_user_table_columns()
    ensure_seed_user(DEFAULT_USER)
    ensure_seed_user(ADMIN_USER)

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
    return render_template("home.html", user=user_to_dict(user), products=PRODUCT_CARDS)


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


@app.route("/profile")
def profile():
    user = get_authenticated_user()
    if user is None:
        return redirect(url_for("auth_page"))
    return render_template("profile.html", user=user_to_dict(user))


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
        category_counts = []
        for category in PRODUCT_CARDS:
            count = db_session.scalar(select(func.count(Product.id)).where(Product.category_slug == category["slug"])) or 0
            category_counts.append({"title": category["title"], "count": count})

    return render_template("admin_dashboard.html", user=user_to_dict(admin_user), users_count=users_count, products_count=products_count, category_counts=category_counts)


@app.route("/admin/users")
def admin_users():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = parse_page_arg()
    with SessionLocal() as db_session:
        statement = select(User).order_by(User.id.desc())
        users, page, total_pages, total = paginate_statement(db_session, statement, page)

    return render_template("admin_users.html", user=user_to_dict(admin_user), users=users, page=page, total_pages=total_pages, total=total)


@app.post("/admin/users/<int:user_id>/update")
def admin_update_user(user_id: int):
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = request.form.get("page", "1")
    username = request.form.get("username", "").strip().lower()
    email = request.form.get("email", "").strip().lower()
    role = normalize_role(request.form.get("role"))
    is_verified = request.form.get("is_verified") == "on"
    new_password = request.form.get("new_password", "")

    if not username or not email:
        flash("Логин и почта обязательны.")
        return redirect(url_for("admin_users", page=page))
    if new_password and len(new_password) < 6:
        flash("Новый пароль должен быть не короче 6 символов.")
        return redirect(url_for("admin_users", page=page))

    with SessionLocal() as db_session:
        target_user = db_session.scalar(select(User).where(User.id == user_id))
        if target_user is None:
            flash("Пользователь не найден.")
            return redirect(url_for("admin_users", page=page))
        username_owner = db_session.scalar(select(User.id).where(User.username == username, User.id != user_id))
        if username_owner is not None:
            flash("Логин уже занят другим пользователем.")
            return redirect(url_for("admin_users", page=page))
        email_owner = db_session.scalar(select(User.id).where(User.email == email, User.id != user_id))
        if email_owner is not None:
            flash("Почта уже занята другим пользователем.")
            return redirect(url_for("admin_users", page=page))

        target_user.username = username
        target_user.email = email
        target_user.role = role
        target_user.is_verified = is_verified
        if not is_verified:
            target_user.verification_code = None
            target_user.verification_expires_at = None
        if new_password:
            target_user.password_hash = generate_password_hash(new_password)
        db_session.commit()
        if admin_user.id == target_user.id:
            session["user"] = target_user.username
            updated_role = target_user.role
        else:
            updated_role = admin_user.role

    flash("Данные пользователя обновлены.")
    if admin_user.id == user_id and updated_role != "admin":
        return redirect(url_for("shop"))
    return redirect(url_for("admin_users", page=page))

@app.route("/admin/products")
def admin_products():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    page = parse_page_arg()
    category_filter = request.args.get("category", "all")

    with SessionLocal() as db_session:
        statement = select(Product).order_by(Product.created_at.desc(), Product.id.desc())
        if category_filter != "all":
            statement = statement.where(Product.category_slug == category_filter)
        products, page, total_pages, total = paginate_statement(db_session, statement, page)

    return render_template("admin_products.html", user=user_to_dict(admin_user), categories=PRODUCT_CARDS, products=products, page=page, total_pages=total_pages, total=total, selected_category=category_filter, get_image_source=get_image_source)


@app.post("/admin/products/create")
def admin_create_product():
    admin_user = get_admin_user()
    if admin_user is None:
        return redirect(url_for("auth_page"))

    category_slug = request.form.get("category_slug", "")
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    image_url = request.form.get("image_url", "").strip()
    price_raw = request.form.get("price", "").strip()

    category = get_category_by_slug(category_slug)
    if category is None:
        flash("Выберите корректную категорию.")
        return redirect(url_for("admin_products"))
    if not name or not description or not price_raw:
        flash("Заполните название, описание и цену товара.")
        return redirect(url_for("admin_products", category=category_slug))

    try:
        price = Decimal(price_raw)
    except InvalidOperation:
        flash("Цена должна быть числом.")
        return redirect(url_for("admin_products", category=category_slug))

    if price <= 0:
        flash("Цена должна быть больше нуля.")
        return redirect(url_for("admin_products", category=category_slug))

    with SessionLocal() as db_session:
        db_session.add(Product(category_slug=category_slug, name=name, description=description, image_url=image_url or category["image"], price=price.quantize(Decimal("0.01"))))
        db_session.commit()

    flash("Товар добавлен.")
    return redirect(url_for("admin_products", category=category_slug))


@app.route("/logout")
def logout():
    session.pop("user", None)
    clear_pending_verification()
    clear_pending_password_reset()
    clear_pending_forgot_password()
    return redirect(url_for("auth_page"))


init_db()


if __name__ == "__main__":
    app.run(debug=True)
