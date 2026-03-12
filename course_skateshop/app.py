from flask import Flask, render_template, request, redirect, url_for, session, flash
import os

app = Flask(__name__)
app.secret_key = os.environ.get("VIOLENTDECK_SECRET", "violentdeck-secret-key")

DEFAULT_USER = {
    "username": "violent",
    "password": "deck123",
    "email": "team@violentdeck.test"
}
registered_users = {DEFAULT_USER["username"]: DEFAULT_USER}

PRODUCT_CARDS = [
    {
        "title": "Скейтборды",
        "description": "Стабильные деки, качественные подвески и колеса для любых трюков.",
        "accent": "скейты",
        "image": "images/skate.png"
    },
    {
        "title": "Одежда",
        "description": "Свободные худи, футболки и шорты из прочных материалов streetwear-класса.",
        "accent": "одежда",
        "image": "images/clothing.png"
    },
    {
        "title": "Аксессуары",
        "description": "Подшипники, сменные колеса, инструменты и элементы защиты.",
        "accent": "аксессуары",
        "image": "images/accessories.png"
    }
]


def _is_authenticated() -> bool:
    return session.get("user") in registered_users


@app.route("/", methods=["GET"])
def auth_page():
    return render_template("auth.html", registered_users=registered_users, default_user=DEFAULT_USER)


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")
    username = request.form.get("register_username", "").strip().lower()
    password = request.form.get("register_password", "")
    email = request.form.get("register_email", "").strip()

    if not username or not password or not email:
        flash("Заполните все поля регистрации.")
        return redirect(url_for("auth_page"))

    if username in registered_users:
        flash("Пользователь с таким именем уже зарегистрирован.")
        return redirect(url_for("auth_page"))

    registered_users[username] = {
        "username": username,
        "password": password,
        "email": email
    }
    flash("Регистрация прошла успешно. Теперь войдите в свой аккаунт.")
    return redirect(url_for("auth_page"))


@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("login_username", "").strip().lower()
    password = request.form.get("login_password", "")

    user = registered_users.get(username)
    if user and user["password"] == password:
        session["user"] = username
        flash("Вы успешно вошли.")
        return redirect(url_for("shop"))

    flash("Неверное имя пользователя или пароль.")
    return redirect(url_for("auth_page"))


@app.route("/shop")
def shop():
    if not _is_authenticated():
        flash("Сначала авторизуйтесь.")
        return redirect(url_for("auth_page"))

    return render_template("home.html", user=registered_users[session["user"]], products=PRODUCT_CARDS)


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Вы вышли из аккаунта.")
    return redirect(url_for("auth_page"))


if __name__ == "__main__":
    app.run(debug=True)
