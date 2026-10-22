"""Security utilities, decorators, and CSRF protection for public_app."""

import secrets
from functools import wraps
from typing import Any, Callable

from flask import abort, current_app, flash, redirect, request, session, url_for
from flask_babel import gettext as _


class CurrentUser:
    """Convenience wrapper for user session data accessible in templates."""

    def __init__(self, session_dict: Any):
        self._session = session_dict

    @property
    def id(self) -> int | None:
        val = self._session.get("user_id")
        return int(val) if val is not None else None

    @property
    def username(self) -> str | None:
        val = self._session.get("username")
        return str(val) if val is not None else None

    @property
    def is_admin(self) -> bool:
        return bool(self._session.get("is_admin", False))

    @property
    def is_authenticated(self) -> bool:
        return bool(self._session.get("user_id"))


def get_current_user() -> CurrentUser:
    """Returns CurrentUser instance bound to the active request session."""
    return CurrentUser(session)


def generate_csrf_token() -> str:
    """Generates or retrieves CSRF token stored in current session."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return str(session["_csrf_token"])


def validate_csrf() -> bool:
    """Validates submitted CSRF token against session."""
    if not current_app.config.get("CSRF_ENABLED", True) or current_app.config.get(
        "TESTING"
    ):
        return True
    session_token = session.get("_csrf_token")
    if not session_token:
        return False

    submitted_token = request.form.get("csrf_token") or request.headers.get(
        "X-CSRFToken"
    )
    if not submitted_token or not secrets.compare_digest(
        submitted_token, session_token
    ):
        return False
    return True


def csrf_protect(f: Callable) -> Callable:
    """Decorator requiring valid CSRF token on POST/PUT/DELETE requests."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if not validate_csrf():
                abort(400, description="Token CSRF inválido o expirado.")
        return f(*args, **kwargs)

    return decorated


def login_required(f: Callable) -> Callable:
    """Decorator ensuring that only authenticated users can access the route."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not session.get("user_id") and not current_app.config.get("TESTING"):
            flash(_("Por favor, inicia sesión para acceder."), "warning")
            return redirect(url_for("auth.login", next=request.full_path))
        return f(*args, **kwargs)

    return decorated


def admin_required(f: Callable) -> Callable:
    """Decorator ensuring that only the administrator can access the route."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        if not session.get("user_id"):
            flash(
                _("Se requiere iniciar sesión como administrador."),
                "error",
            )
            return redirect(url_for("auth.login", next=request.full_path))

        if not session.get("is_admin"):
            flash(
                _("Acceso denegado. No tienes permisos de administrador."),
                "error",
            )
            return redirect(url_for("catalog.index"))

        return f(*args, **kwargs)

    return decorated


def sync_api_required(f: Callable) -> Callable:
    """Decorator requiring valid Bearer API token for UNPSJB automated catalog synchronization."""

    @wraps(f)
    def decorated(*args: Any, **kwargs: Any) -> Any:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            abort(
                401,
                description="Se requiere encabezado Authorization: Bearer <TOKEN> válido.",
            )

        submitted_token = auth_header.split(" ", 1)[1].strip()
        config = current_app.config.get("APP_CONFIG")
        if not config:
            abort(500, description="Error de configuración del servidor.")

        expected_token = config.get_sync_settings().api_token
        if not expected_token or not secrets.compare_digest(
            submitted_token, expected_token
        ):
            abort(403, description="Token de sincronización inválido o no autorizado.")

        return f(*args, **kwargs)

    return decorated
