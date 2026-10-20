"""Authentication Blueprint for Sur en Precios."""

import logging
from datetime import datetime, timezone

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _

from sur_en_precios.domain.services import AuthService
from sur_en_precios.web.public_app.database import (
    get_user_repository,
    get_user_session,
)

logger = logging.getLogger("sur_en_precios.public_app.auth")

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    """Handles new user registration following strict best practices with zero recovery."""
    if session.get("user_id"):
        return redirect(url_for("catalog.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        disclaimer_ack = request.form.get("disclaimer_ack")

        if not disclaimer_ack:
            flash(
                _(
                    "Debe aceptar la condición de no recuperación de usuario y contraseña para continuar."
                ),
                "error",
            )
            return render_template("auth/register.html", username=username)

        if password != confirm_password:
            flash(_("Las contraseñas no coinciden."), "error")
            return render_template("auth/register.html", username=username)

        val_user, err_user = AuthService.validate_username(username)
        if not val_user:
            flash(_(err_user), "error")
            return render_template("auth/register.html", username=username)

        val_pass, err_pass = AuthService.validate_password(password)
        if not val_pass:
            flash(_(err_pass), "error")
            return render_template("auth/register.html", username=username)

        try:
            with get_user_session() as u_session:
                user_repo = get_user_repository(u_session)
                existing = user_repo.get_user_by_username(username)
                if existing:
                    flash(
                        _("El nombre de usuario ya se encuentra registrado."),
                        "error",
                    )
                    return render_template("auth/register.html", username=username)

                pwd_hash = AuthService.hash_password(password)
                new_user = user_repo.create_user(
                    username=username, password_hash=pwd_hash, is_admin=False
                )

                # Initialize authenticated session
                session.clear()
                session["user_id"] = new_user.id
                session["username"] = new_user.username
                session["is_admin"] = new_user.is_admin

                flash(
                    _("¡Cuenta creada exitosamente! Bienvenido a Sur en Precios."),
                    "success",
                )
                return redirect(url_for("baskets.baskets"))
        except Exception as exc:
            logger.error("Error creating user %s: %s", username, exc)
            flash(
                _("Ocurrió un error al crear la cuenta. Intente nuevamente."),
                "error",
            )
            return render_template("auth/register.html", username=username)

    return render_template("auth/register.html", username="")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Handles user login with constant-time check to prevent timing attacks."""
    if session.get("user_id"):
        return redirect(url_for("catalog.index"))

    next_url = request.args.get("next") or request.form.get("next")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        with get_user_session() as u_session:
            user_repo = get_user_repository(u_session)
            user = user_repo.get_user_by_username(username)

            if user and AuthService.verify_password(password, user.password_hash):
                session.clear()
                session["user_id"] = user.id
                session["username"] = user.username
                session["is_admin"] = user.is_admin
                user.last_login_at = datetime.now(timezone.utc)
                u_session.commit()

                flash(_("¡Bienvenido/a, %(name)s!", name=user.username), "success")
                if (
                    next_url
                    and next_url.startswith("/")
                    and not next_url.startswith("//")
                ):
                    return redirect(next_url)
                return redirect(url_for("baskets.baskets"))

            # Timing-attack mitigation
            AuthService.dummy_verify()
            flash(_("Nombre de usuario o contraseña incorrectos."), "error")

    return render_template("auth/login.html", username="", next_url=next_url)


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    """Logs the user out and clears the session."""
    session.clear()
    flash(_("Has cerrado sesión correctamente."), "info")
    return redirect(url_for("catalog.index"))
