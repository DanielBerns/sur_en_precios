import logging
import os
from pathlib import Path

from flask import Flask, abort, request
from flask_babel import Babel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sur_en_precios.config import read_config
from sur_en_precios.domain.models_public import PublicBase
from sur_en_precios.web.public_app.blueprints import (
    admin_bp,
    api_bp,
    auth_bp,
    baskets_bp,
    catalog_bp,
    optimize_bp,
)
from sur_en_precios.web.public_app.database import init_user_db
from sur_en_precios.web.public_app.security import (
    generate_csrf_token,
    get_current_user,
    validate_csrf,
)

logger = logging.getLogger("sur_en_precios.public_app")


def get_locale() -> str:
    """Returns application default locale for Babel internationalization."""
    return "es_AR"


def _register_endpoint_aliases(app: Flask) -> None:
    """Register top-level endpoint aliases for backwards compatibility with url_for."""
    for rule in list(app.url_map.iter_rules()):
        if "." in rule.endpoint:
            short_name = rule.endpoint.split(".", 1)[1]
            if short_name not in app.view_functions:
                app.view_functions[short_name] = app.view_functions[rule.endpoint]
            if short_name not in app.url_map._rules_by_endpoint:
                app.add_url_rule(
                    rule.rule,
                    endpoint=short_name,
                    view_func=app.view_functions[rule.endpoint],
                    methods=rule.methods,
                )


def create_public_app(workdir: Path | None = None) -> Flask:
    """Factory creating Flask public web application configured with Blueprints and SQLAlchemy."""
    config = read_config(workdir_override=workdir, should_create_override=True)
    public_db_path = config.get_public_db_path()
    user_db_path = config.get_user_db_path()

    public_engine = create_engine(f"sqlite:///{public_db_path}")
    PublicBase.metadata.create_all(public_engine)

    user_engine = create_engine(f"sqlite:///{user_db_path}")
    init_user_db(user_engine)

    public_session_factory = sessionmaker(
        bind=public_engine, autoflush=False, expire_on_commit=False
    )
    user_session_factory = sessionmaker(
        bind=user_engine, autoflush=False, expire_on_commit=False
    )

    templates_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(templates_dir))

    # Production-ready session hardening
    app.secret_key = os.environ.get(
        "SECRET_KEY", "sur_precios_public_secret_key_production_2026"
    )
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get(
        "PYTHONANYWHERE_SITE"
    ):
        app.config["SESSION_COOKIE_SECURE"] = True

    app.config["BABEL_DEFAULT_LOCALE"] = "es_AR"
    app.config["APP_CONFIG"] = config
    app.config["PUBLIC_ENGINE"] = public_engine
    app.config["USER_ENGINE"] = user_engine

    app.extensions["public_engine"] = public_engine
    app.extensions["user_engine"] = user_engine
    app.extensions["public_session_factory"] = public_session_factory
    app.extensions["user_session_factory"] = user_session_factory

    Babel(app, locale_selector=get_locale)

    @app.before_request
    def enforce_csrf_protection():
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            if not validate_csrf():
                abort(400, description="Token CSRF inválido o expirado.")

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
        return response

    @app.context_processor
    def inject_security_context():
        return {
            "current_user": get_current_user(),
            "csrf_token": generate_csrf_token,
        }

    @app.template_filter("format_currency")
    def format_currency(value: int | None) -> str:
        if value is None:
            return "-"
        formatted = f"{value:,}".replace(",", ".")
        return f"${formatted} ARS"

    # Register modular blueprints
    app.register_blueprint(catalog_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(baskets_bp)
    app.register_blueprint(optimize_bp)
    app.register_blueprint(api_bp)

    # Register top-level endpoint aliases for backwards-compatibility
    _register_endpoint_aliases(app)

    return app


def create_app() -> Flask:
    """Factory returning the Flask WSGI application instance (e.g., for PythonAnywhere)."""
    return create_public_app()


def main():
    import sys

    try:
        config = read_config()
        public_app = create_public_app()
        public_app.run(port=5000, debug=config.settings.app.debug)
    except Exception as exc:
        logger.error("Public server error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
