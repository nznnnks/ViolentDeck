import random
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage

from flask import Flask, flash, redirect, render_template, request, session, url_for
from sqlalchemy import Boolean, DateTime, String, create_engine, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash

import settings


app = Flask(__name__)
app.secret_key = settings.SECRET_KEY

engine = create_engine(settings.DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verification_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    verification_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    password_reset_code: Mapped[str | None] = mapped_column(String(6), nullable=True)
    password_reset_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


DEFAULT_USER = {
    "username": "violent",
    "password": "deck123",
    "email": "team@violentdeck.test",
}

PRODUCT_CARDS = [
    {
        "title": "Скейтборды",
        "description": "Стабильные деки, качественные подвески и колеса для любых трюков.",
        "accent": "скейты",
        "image": "images/skate.png",
    },
    {
        "title": "Одежда",
        "description": "Свободные худи, футболки и шорты из прочных материалов streetwear-класса.",
        "accent": "одежда",
        "image": "images/clothing.png",
    },
    {
        "title": "Аксессуары",
        "description": "Подшипники, сменные колеса, инструменты и элементы защиты.",
        "accent": "аксессуары",
        "image": "images/accessories.png",
    },
]


def generate_verification_code() -> str:
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
    send_email(
        recipient_email=recipient_email,
        subject="Код подтверждения ViolentDeck",
        body=(
            "Здравствуйте!\n\n"
            f"Ваш код подтверждения для регистрации в ViolentDeck: {code}\n"
            f"Код действует {settings.VERIFICATION_CODE_TTL_MINUTES} минут.\n"
        ),
    )


def send_password_reset_email(recipient_email: str, code: str) -> None:
    send_email(
        recipient_email=recipient_email,
        subject="Код смены пароля ViolentDeck",
        body=(
            "Здравствуйте!\n\n"
            f"Ваш код для смены пароля в ViolentDeck: {code}\n"
            f"Код действует {settings.VERIFICATION_CODE_TTL_MINUTES} минут.\n"
        ),
    )


def ensure_user_table_columns() -> None:
    inspector = inspect(engine)
    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    alter_statements = []

    if "is_verified" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_verified BOOLEAN NOT NULL DEFAULT FALSE"
        )
    if "verification_code" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_code VARCHAR(6)"
        )
    if "verification_expires_at" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_expires_at TIMESTAMP"
        )
    if "password_reset_code" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_code VARCHAR(6)"
        )
    if "password_reset_expires_at" not in existing_columns:
        alter_statements.append(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS password_reset_expires_at TIMESTAMP"
        )

    if not alter_statements:
        return

    with engine.begin() as connection:
        for statement in alter_statements:
            connection.execute(text(statement))


def init_db() -> None:
    Base.metadata.create_all(engine)
    ensure_user_table_columns()

    with SessionLocal() as db_session:
        default_user = db_session.scalar(
            select(User).where(User.username == DEFAULT_USER["username"])
        )
        if default_user is None:
            db_session.add(
                User(
                    username=DEFAULT_USER["username"],
                    email=DEFAULT_USER["email"],
                    password_hash=generate_password_hash(DEFAULT_USER["password"]),
                    is_verified=True,
                )
            )
            db_session.commit()
            return

        if not default_user.is_verified:
            default_user.is_verified = True
            default_user.verification_code = None
            default_user.verification_expires_at = None
            default_user.password_reset_code = None
            default_user.password_reset_expires_at = None
            db_session.commit()


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


def is_authenticated() -> bool:
    user = get_user_by_username(session.get("user"))
    return user is not None and user.is_verified


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


def issue_new_verification_code(user: User) -> str:
    code = generate_verification_code()
    expires_at = datetime.utcnow() + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES)

    with SessionLocal() as db_session:
        db_user = db_session.scalar(select(User).where(User.id == user.id))
        if db_user is None:
            raise ValueError("Пользователь не найден.")
        db_user.verification_code = code
        db_user.verification_expires_at = expires_at
        db_session.commit()

    send_verification_email(user.email, code)
    return code


def issue_password_reset_code(user: User) -> str:
    code = generate_verification_code()
    expires_at = datetime.utcnow() + timedelta(minutes=settings.VERIFICATION_CODE_TTL_MINUTES)

    with SessionLocal() as db_session:
        db_user = db_session.scalar(select(User).where(User.id == user.id))
        if db_user is None:
            raise ValueError("Пользователь не найден.")
        db_user.password_reset_code = code
        db_user.password_reset_expires_at = expires_at
        db_session.commit()

    send_password_reset_email(user.email, code)
    return code


@app.route("/", methods=["GET"])
def auth_page():
    if is_authenticated():
        return redirect(url_for("shop"))
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

    verification_code = generate_verification_code()
    verification_expires_at = datetime.utcnow() + timedelta(
        minutes=settings.VERIFICATION_CODE_TTL_MINUTES
    )

    with SessionLocal() as db_session:
        if db_session.scalar(select(User.id).where(User.username == username)):
            flash("Пользователь с таким логином уже зарегистрирован.")
            return redirect(url_for("register"))

        if db_session.scalar(select(User.id).where(User.email == email)):
            flash("Пользователь с такой почтой уже зарегистрирован.")
            return redirect(url_for("register"))

        db_session.add(
            User(
                username=username,
                email=email,
                password_hash=generate_password_hash(password),
                is_verified=False,
                verification_code=verification_code,
                verification_expires_at=verification_expires_at,
            )
        )
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

        if (
            db_user.verification_expires_at is None
            or db_user.verification_expires_at < datetime.utcnow()
        ):
            flash("Срок действия кода истёк. Отправьте код заново.")
            return redirect(url_for("verify_registration"))

        db_user.is_verified = True
        db_user.verification_code = None
        db_user.verification_expires_at = None
        db_session.commit()

    clear_pending_verification()
    session["user"] = db_user.username
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
        return redirect(url_for("shop"))

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
        return render_template(
            "forgot_password_verify.html",
            user={"username": user.username, "email": user.email},
        )

    code = request.form.get("reset_code", "").strip()
    new_password = request.form.get("new_password", "")

    if not code or not new_password:
        flash("Введите код и новый пароль.")
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

        if (
            db_user.password_reset_expires_at is None
            or db_user.password_reset_expires_at < datetime.utcnow()
        ):
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
    user = get_user_by_username(session.get("user"))
    if user is None or not user.is_verified:
        session.pop("user", None)
        return redirect(url_for("auth_page"))

    return render_template(
        "home.html",
        user={"username": user.username, "email": user.email},
        products=PRODUCT_CARDS,
    )


@app.route("/profile")
def profile():
    user = get_user_by_username(session.get("user"))
    if user is None or not user.is_verified:
        session.pop("user", None)
        return redirect(url_for("auth_page"))

    return render_template(
        "profile.html",
        user={"username": user.username, "email": user.email},
    )


@app.post("/profile/password/send-code")
def send_password_reset_code_route():
    user = get_user_by_username(session.get("user"))
    if user is None or not user.is_verified:
        session.pop("user", None)
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
    current_user = get_user_by_username(session.get("user"))
    pending_user = get_pending_password_reset_user()
    if current_user is None or not current_user.is_verified:
        session.pop("user", None)
        clear_pending_password_reset()
        return redirect(url_for("auth_page"))
    if pending_user is None or pending_user.username != current_user.username:
        flash("Сначала запросите код для смены пароля.")
        return redirect(url_for("profile"))

    if request.method == "GET":
        return render_template(
            "password_reset_verify.html",
            user={"username": current_user.username, "email": current_user.email},
        )

    code = request.form.get("reset_code", "").strip()
    new_password = request.form.get("new_password", "")

    if not code or not new_password:
        flash("Введите код и новый пароль.")
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

        if (
            db_user.password_reset_expires_at is None
            or db_user.password_reset_expires_at < datetime.utcnow()
        ):
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
    current_user = get_user_by_username(session.get("user"))
    pending_user = get_pending_password_reset_user()
    if current_user is None or not current_user.is_verified:
        session.pop("user", None)
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
