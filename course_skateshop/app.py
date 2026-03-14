import os

from flask import Flask, flash, redirect, render_template, request, session, url_for
from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash


app = Flask(__name__)
app.secret_key = os.environ.get("VIOLENTDECK_SECRET", "violentdeck-secret-key")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5432/course_skateshop",
)
engine = create_engine(DATABASE_URL, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)


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


def init_db() -> None:
    Base.metadata.create_all(engine)

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
                )
            )
            db_session.commit()


def get_user_by_username(username: str | None) -> User | None:
    if not username:
        return None

    with SessionLocal() as db_session:
        return db_session.scalar(select(User).where(User.username == username))


def is_authenticated() -> bool:
    return get_user_by_username(session.get("user")) is not None


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
            )
        )
        db_session.commit()

    flash("Регистрация прошла успешно. Теперь войдите в аккаунт.")
    return redirect(url_for("auth_page"))


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("login_username", "").strip().lower()
    password = request.form.get("login_password", "")

    user = get_user_by_username(username)
    if user and check_password_hash(user.password_hash, password):
        session["user"] = username
        return redirect(url_for("shop"))

    flash("Неверный логин или пароль.")
    return redirect(url_for("auth_page"))


@app.route("/shop")
def shop():
    user = get_user_by_username(session.get("user"))
    if user is None:
        session.pop("user", None)
        flash("Сначала авторизуйтесь.")
        return redirect(url_for("auth_page"))

    return render_template(
        "home.html",
        user={"username": user.username, "email": user.email},
        products=PRODUCT_CARDS,
    )


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("auth_page"))


init_db()


if __name__ == "__main__":
    app.run(debug=True)
