"""Self-contained preview environment and fallback demo data seeder for public_app routes."""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Any

from flask import Flask, Response, request, session
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sur_en_precios.config import read_config
from sur_en_precios.domain.models_public import (
    Article,
    Brand,
    Category,
    DailyPrice,
    DailyProductMetric,
    PointOfSale,
    PublicBase,
    UnreviewedArticle,
)
from sur_en_precios.domain.models_user import Basket, BasketItem, User
from sur_en_precios.web.public_app import create_public_app
from sur_en_precios.web.public_app.database import ensure_public_session_factory

logger = logging.getLogger(__name__)

__all__ = [
    "PREVIEW_SAMPLE_EAN",
    "PreviewEnvironment",
    "build_preview_public_app",
]

PREVIEW_SAMPLE_EAN = "7793704000016"


class PreviewEnvironment:
    """Holds references to the mounted preview public_app and seeded preview identifiers."""

    def __init__(
        self,
        app: Flask,
        admin_user_id: int,
        sample_basket_id: int,
        sample_basket_uuid: str,
        sample_ean: str,
        sample_department_slug: str,
    ) -> None:
        self.app = app
        self.admin_user_id = admin_user_id
        self.sample_basket_id = sample_basket_id
        self.sample_basket_uuid = sample_basket_uuid
        self.sample_ean = sample_ean
        self.sample_department_slug = sample_department_slug

    def get_preview_routes(self) -> list[dict[str, str]]:
        """Returns the curated list of previewable public_app routes for the editor toolbar."""
        return [
            {
                "id": "kitchen-sink",
                "label": "🎨 Kitchen Sink (Todos los Componentes UI)",
                "url": "/preview/kitchen-sink",
            },
            {
                "id": "landing",
                "label": "🏠 Inicio / Portada e Institucional",
                "url": "/preview/app/",
            },
            {
                "id": "search",
                "label": "🔍 Buscador de Productos (con Resultados)",
                "url": "/preview/app/buscar?q=a",
            },
            {
                "id": "article-detail",
                "label": "📦 Detalle de Artículo y Precios por Comercio",
                "url": f"/preview/app/article/{self.sample_ean}",
            },
            {
                "id": "departments",
                "label": "🗂️ Categorías y Rubros",
                "url": "/preview/app/departments",
            },
            {
                "id": "department-view",
                "label": "🛒 Vista de Rubro (Almacén)",
                "url": f"/preview/app/department/{self.sample_department_slug}",
            },
            {
                "id": "baskets",
                "label": "🧺 Mis Canastas",
                "url": "/preview/app/baskets",
            },
            {
                "id": "basket-editor",
                "label": "✏️ Editor de Canasta y Reporte de Precios",
                "url": f"/preview/app/baskets/{self.sample_basket_id}/edit",
            },
            {
                "id": "optimize",
                "label": "⚡ Optimizador de Precios",
                "url": "/preview/app/optimize",
            },
            {
                "id": "help",
                "label": "❓ Guía y Ayuda",
                "url": "/preview/app/help",
            },
            {
                "id": "login",
                "label": "🔐 Iniciar Sesión",
                "url": "/preview/app/auth/login",
            },
            {
                "id": "register",
                "label": "📝 Registro de Usuario",
                "url": "/preview/app/auth/register",
            },
            {
                "id": "admin-dashboard",
                "label": "🛠️ Panel Admin — Resumen",
                "url": "/preview/app/admin/dashboard",
            },
            {
                "id": "admin-users",
                "label": "👥 Panel Admin — Usuarios",
                "url": "/preview/app/admin/users",
            },
            {
                "id": "admin-baskets",
                "label": "📋 Panel Admin — Canastas",
                "url": "/preview/app/admin/baskets",
            },
            {
                "id": "admin-system",
                "label": "⚙️ Panel Admin — Sistema y Sincronización",
                "url": "/preview/app/admin/system",
            },
        ]


def _seed_fallback_public_data(session: Session) -> tuple[str, str]:
    """Seeds lightweight Patagonian supermarket demo data if public.sqlite is empty."""
    existing_article = session.scalars(select(Article).limit(1)).first()
    existing_cat = session.scalars(
        select(Category).where(Category.level == 1).limit(1)
    ).first()
    if existing_article is not None and existing_cat is not None:
        return existing_article.ean, existing_cat.slug

    today = dt.date.today()

    cat_almacen = Category(
        name="Almacén",
        slug="almacen",
        level=1,
        description="Productos secos, infusiones, aceites y despensa general.",
    )
    cat_lacteos = Category(
        name="Lácteos y Frescos",
        slug="lacteos-y-frescos",
        level=1,
        description="Leches, yogures, mantecas y quesos refrigerados.",
    )
    cat_bebidas = Category(
        name="Bebidas",
        slug="bebidas",
        level=1,
        description="Aguas, jugos, gaseosas y bodega.",
    )
    cat_limpieza = Category(
        name="Limpieza del Hogar",
        slug="limpieza-del-hogar",
        level=1,
        description="Detergentes, lavandinas, jabones y desinfectantes.",
    )
    session.add_all([cat_almacen, cat_lacteos, cat_bebidas, cat_limpieza])
    session.flush()

    sub_yerba = Category(
        name="Yerba Mate",
        slug="yerba-mate",
        level=2,
        parent_id=cat_almacen.id,
        description="Yerba mate tradicional, suave y compuesta.",
    )
    sub_aceites = Category(
        name="Aceites y Vinagres",
        slug="aceites-y-vinagres",
        level=2,
        parent_id=cat_almacen.id,
        description="Aceites de girasol, oliva y mezcla.",
    )
    sub_leche = Category(
        name="Leche Fluida",
        slug="leche-fluida",
        level=2,
        parent_id=cat_lacteos.id,
        description="Leche entera y descremada larga vida.",
    )
    session.add_all([sub_yerba, sub_aceites, sub_leche])
    session.flush()

    brand_playadito = Brand(name="Playadito", slug="playadito")
    brand_natura = Brand(name="Natura", slug="natura")
    brand_serenisima = Brand(name="La Serenísima", slug="la-serenisima")
    brand_lucchetti = Brand(name="Lucchetti", slug="lucchetti")
    session.add_all([brand_playadito, brand_natura, brand_serenisima, brand_lucchetti])
    session.flush()

    articles_data: list[dict[str, Any]] = [
        {
            "ean": PREVIEW_SAMPLE_EAN,
            "name": "Yerba Mate Playadito Con Palo 1 Kg",
            "clean_description": "Yerba Mate Playadito Con Palo 1 Kg",
            "brand": brand_playadito,
            "brand_name": "Playadito",
            "package": "1 kg",
            "package_amount": 1.0,
            "package_unit": "kg",
            "category": sub_yerba,
            "prices": [3950, 4200, 4490, 4850],
        },
        {
            "ean": "7790272000105",
            "name": "Aceite de Girasol Natura 1.5 L",
            "clean_description": "Aceite de Girasol Natura 1.5 L",
            "brand": brand_natura,
            "brand_name": "Natura",
            "package": "1.5 l",
            "package_amount": 1.5,
            "package_unit": "l",
            "category": sub_aceites,
            "prices": [2890, 3100, 3250, 3590],
        },
        {
            "ean": "7790742000018",
            "name": "Leche Entera UAT La Serenísima 1 L",
            "clean_description": "Leche Entera UAT La Serenísima 1 L",
            "brand": brand_serenisima,
            "brand_name": "La Serenísima",
            "package": "1 l",
            "package_amount": 1.0,
            "package_unit": "l",
            "category": sub_leche,
            "prices": [1450, 1520, 1600, 1790],
        },
        {
            "ean": "7790070411713",
            "name": "Fideos Tallarín Lucchetti 500 G",
            "clean_description": "Fideos Tallarín Lucchetti 500 G",
            "brand": brand_lucchetti,
            "brand_name": "Lucchetti",
            "package": "500 g",
            "package_amount": 0.5,
            "package_unit": "kg",
            "category": cat_almacen,
            "prices": [1120, 1250, 1340, 1480],
        },
    ]

    stores_data = [
        PointOfSale(
            code="POS-CR-LAANONIMA-01",
            sepa_id="10-1-101",
            comercio_id=10,
            bandera_id=1,
            sucursal_id=101,
            business_name="S.A. Importadora y Exportadora de la Patagonia",
            holding_group="La Anónima",
            brand_name="La Anónima",
            store_format="Hipermercado",
            branch_name="Sucursal Km 3",
            address="Av. Tehuelches 120",
            city="Comodoro Rivadavia",
            province="Chubut",
            province_code="AR-U",
        ),
        PointOfSale(
            code="POS-CR-CARREFOUR-02",
            sepa_id="11-1-202",
            comercio_id=11,
            bandera_id=1,
            sucursal_id=202,
            business_name="INC S.A.",
            holding_group="Carrefour",
            brand_name="Carrefour Market",
            store_format="Supermercado",
            branch_name="Centro Rivadavia",
            address="San Martín 850",
            city="Comodoro Rivadavia",
            province="Chubut",
            province_code="AR-U",
        ),
        PointOfSale(
            code="POS-CR-CHANGOMAS-03",
            sepa_id="12-1-303",
            comercio_id=12,
            bandera_id=1,
            sucursal_id=303,
            business_name="Dorinka S.R.L.",
            holding_group="GDN Argentina",
            brand_name="Híper ChangoMâs",
            store_format="Hipermercado",
            branch_name="Av. Yrigoyen Sur",
            address="Av. Hipólito Yrigoyen 2550",
            city="Comodoro Rivadavia",
            province="Chubut",
            province_code="AR-U",
        ),
        PointOfSale(
            code="POS-TW-LAANONIMA-04",
            sepa_id="10-1-404",
            comercio_id=10,
            bandera_id=1,
            sucursal_id=404,
            business_name="S.A. Importadora y Exportadora de la Patagonia",
            holding_group="La Anónima",
            brand_name="La Anónima",
            store_format="Supermercado",
            branch_name="Trelew Centro",
            address="Colombia 250",
            city="Trelew",
            province="Chubut",
            province_code="AR-U",
        ),
    ]
    session.add_all(stores_data)
    session.flush()

    for item in articles_data:
        art = Article(
            ean=item["ean"],
            name=item["name"],
            clean_description=item["clean_description"],
            brand=item["brand"],
            brand_name=item["brand_name"],
            package=item["package"],
            package_amount=item["package_amount"],
            package_unit=item["package_unit"],
            category=item["category"],
            is_reviewed=True,
        )
        session.add(art)
        session.flush()

        prices_list: list[int] = item["prices"]
        for store_obj, price_val in zip(stores_data, prices_list):
            unit_p = round(price_val / float(item["package_amount"]), 2)
            session.add(
                DailyPrice(
                    date=today,
                    ean=art.ean,
                    store_code=store_obj.code,
                    price=price_val,
                    unit_price=unit_p,
                )
            )

        min_p = min(prices_list)
        max_p = max(prices_list)
        med_p = int(sorted(prices_list)[len(prices_list) // 2])
        disp = round((max_p - min_p) / med_p, 4)

        for city_name in ("Comodoro Rivadavia", "Trelew"):
            session.add(
                DailyProductMetric(
                    date=today,
                    ean=art.ean,
                    city=city_name,
                    min_price=min_p,
                    max_price=max_p,
                    median_price=med_p,
                    geo_mean_price=med_p,
                    price_dispersion=disp,
                    pct_change_7d=1.8,
                    pct_change_30d=4.5,
                    pct_change_90d=12.4,
                )
            )

    existing_unreviewed = session.scalar(
        select(func.count()).select_from(UnreviewedArticle)
    )
    if not existing_unreviewed:
        session.add(
            UnreviewedArticle(
                ean="7798999001122",
                raw_description="DULCE REGIONAL CALAFATE ARTESANAL FRASCO 450GR",
                suggested_brand="Patagonia Dulce",
                suggested_package="450 g",
                suggested_category_id=cat_almacen.id,
                reason="Artículo regional de demostración para vista previa",
            )
        )

    session.commit()
    return PREVIEW_SAMPLE_EAN, cat_almacen.slug


def _seed_preview_user_and_basket(user_session: Session, sample_ean: str) -> tuple[int, int, str]:
    """Ensures a preview admin user and a populated sample basket exist in user_data.sqlite."""
    admin_user = user_session.scalars(
        select(User).where(User.username == "admin_preview")
    ).first()
    if admin_user is None:
        admin_user = User(
            username="admin_preview",
            password_hash="preview_only_non_login_hash",
            is_admin=True,
            is_active=True,
        )
        user_session.add(admin_user)
        user_session.flush()

    basket = user_session.scalars(
        select(Basket).where(Basket.user_id == admin_user.id).limit(1)
    ).first()
    if basket is None:
        basket = Basket(
            user_id=admin_user.id,
            name="Canasta Familiar Patagónica (Vista Previa)",
            is_public=True,
            items=[
                BasketItem(ean=sample_ean, quantity=2, selected=True, numerator=2, denominator=1),
                BasketItem(ean="7790272000105", quantity=1, selected=True, numerator=1, denominator=1),
                BasketItem(ean="7790742000018", quantity=4, selected=True, numerator=4, denominator=1),
                BasketItem(ean="7790070411713", quantity=3, selected=True, numerator=3, denominator=1),
            ],
        )
        user_session.add(basket)
        user_session.flush()

    user_session.commit()
    return int(admin_user.id), int(basket.id), str(basket.uuid)


def build_preview_public_app(
    workdir: Path | None = None,
    style_css_path: Path | None = None,
) -> PreviewEnvironment:
    """Creates and seeds a preview instance of public_app with auto-authenticated admin session."""
    config = read_config(workdir_override=workdir, should_create_override=True)
    public_app = create_public_app(workdir=config.workdir)

    public_factory = ensure_public_session_factory(public_app)
    public_engine = public_app.extensions.get("public_engine")
    if public_engine is not None:
        try:
            PublicBase.metadata.create_all(public_engine)
        except Exception as exc:
            logger.debug("Public DB readonly or already initialized: %s", exc)

    sample_ean = PREVIEW_SAMPLE_EAN
    sample_dept_slug = "almacen"
    try:
        with public_factory() as p_session:
            sample_ean, sample_dept_slug = _seed_fallback_public_data(p_session)
    except Exception as exc:
        logger.warning("Could not seed fallback public preview data: %s", exc)

    user_factory = public_app.extensions["user_session_factory"]
    with user_factory() as u_session:
        admin_user_id, basket_id, basket_uuid = _seed_preview_user_and_basket(
            u_session, sample_ean
        )

    @public_app.before_request
    def _configure_preview_request() -> Response | None:
        # Always serve the active target style_css_path with no-store caching
        if style_css_path is not None and request.path.endswith("/static/css/style.css"):
            css_bytes = style_css_path.read_bytes()
            return Response(
                css_bytes,
                status=200,
                mimetype="text/css",
                headers={"Cache-Control": "no-store, max-age=0"},
            )

        # On /auth/login and /auth/register, keep user logged out so auth forms render instead of redirecting
        if request.path.startswith("/auth/"):
            session.pop("user_id", None)
            session.pop("username", None)
            session.pop("is_admin", None)
        else:
            session["user_id"] = admin_user_id
            session["username"] = "admin_preview"
            session["is_admin"] = True
        return None

    return PreviewEnvironment(
        app=public_app,
        admin_user_id=admin_user_id,
        sample_basket_id=basket_id,
        sample_basket_uuid=basket_uuid,
        sample_ean=sample_ean,
        sample_department_slug=sample_dept_slug,
    )
