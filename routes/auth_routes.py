"""Authentication routes for login, registration, and logout."""

from flask import render_template, redirect, url_for, session, request, flash
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, User, UserProfile


def register_auth_routes(app):
    """Register authentication routes on the Flask app."""

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()

            if not username or not password:
                flash("Please enter username and password.", "error")
                return render_template("login.html", page_title="Login")

            try:
                user = User.query.filter_by(username=username).first()

                if not user:
                    flash("User not found.", "error")
                    return render_template("login.html", page_title="Login")

                if not check_password_hash(user.password_hash, password):
                    flash("Incorrect password.", "error")
                    return render_template("login.html", page_title="Login")

                session["user_id"] = user.id
                session["username"] = user.username
                session.pop("active_character_id", None)

                return redirect(url_for("index"))

            except Exception as e:
                db.session.rollback()
                flash(f"Database error: {str(e)}", "error")
                return render_template("login.html", page_title="Login")

        return render_template("login.html", page_title="Login")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "").strip()

            if not username or not email or not password:
                flash("Please fill in all fields.", "error")
                return render_template("register.html", page_title="Register")

            existing_username = User.query.filter_by(username=username).first()
            if existing_username:
                flash("This username is already taken.", "error")
                return render_template("register.html", page_title="Register")

            existing_email = User.query.filter_by(email=email).first()
            if existing_email:
                flash("This email is already in use.", "error")
                return render_template("register.html", page_title="Register")

            try:
                password_hash = generate_password_hash(password)

                new_user = User(
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    is_active=True
                )
                db.session.add(new_user)
                db.session.commit()

                new_profile = UserProfile(
                    user_id=new_user.id,
                    display_name=username,
                    bio="New adventurer"
                )
                db.session.add(new_profile)
                db.session.commit()

                flash("Registration successful. You can now log in.", "success")
                return redirect(url_for("login"))

            except Exception as e:
                db.session.rollback()
                flash(f"Database error: {str(e)}", "error")
                return render_template("register.html", page_title="Register")

        return render_template("register.html", page_title="Register")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))
