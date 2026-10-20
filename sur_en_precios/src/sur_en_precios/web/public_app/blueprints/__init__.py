from sur_en_precios.web.public_app.blueprints.admin import admin_bp
from sur_en_precios.web.public_app.blueprints.api import api_bp
from sur_en_precios.web.public_app.blueprints.auth import auth_bp
from sur_en_precios.web.public_app.blueprints.baskets import baskets_bp
from sur_en_precios.web.public_app.blueprints.catalog import catalog_bp
from sur_en_precios.web.public_app.blueprints.optimize import optimize_bp

__all__ = [
    "admin_bp",
    "api_bp",
    "auth_bp",
    "baskets_bp",
    "catalog_bp",
    "optimize_bp",
]
