import logging
from typing import Literal

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_babel import gettext as _
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from sur_en_precios.domain.cleaner.text_utils import strip_accents
from sur_en_precios.domain.models_public import Category
from sur_en_precios.web.public_app.database import (
    get_catalog_repository,
    get_price_repository,
    get_public_session,
    get_user_repository,
    get_user_session,
)
from sur_en_precios.web.public_app.schemas import (
    ArticlePriceStatsQuery,
    ArticleSearchQuery,
    Pagination,
)

logger = logging.getLogger("sur_en_precios.public_app.catalog")

catalog_bp = Blueprint("catalog", __name__)


def _resolve_search_cities(cat_repo, req_city: str | None) -> tuple[list[str], str]:
    """Returns available region cities and the canonical selected city ('' for all cities)."""
    config = current_app.config["APP_CONFIG"]
    cities = list(cat_repo.get_cities_for_region(config.get_region()))
    if not req_city:
        return cities, ""

    req_lower = req_city.lower()
    matching_city = next((c for c in cities if c.lower() == req_lower), None)
    if matching_city:
        return cities, matching_city

    req_unaccent = strip_accents(req_lower)
    matching_unaccent = next(
        (c for c in cities if strip_accents(c.lower()) == req_unaccent),
        None,
    )
    if matching_unaccent:
        return cities, matching_unaccent

    cities.append(req_city)
    return cities, req_city


def _parse_search_params() -> ArticleSearchQuery:
    """Parses and clamps search query parameters from the current Flask request."""
    query_param = request.args.get("q", "")
    mode_param = request.args.get("mode", "fuzzy")
    city_param = request.args.get("city")
    page_param = request.args.get("page", 1)
    per_page_param = request.args.get("per_page", 20)

    try:
        page = max(1, int(page_param))
    except (ValueError, TypeError):
        page = 1

    try:
        per_page = max(1, min(500, int(per_page_param)))
    except (ValueError, TypeError):
        per_page = 20

    mode: Literal["fuzzy", "exact"] = "exact" if mode_param == "exact" else "fuzzy"
    return ArticleSearchQuery(
        q=query_param,
        mode=mode,
        city=city_param,
        page=page,
        per_page=per_page,
    )


@catalog_bp.route("/")
def index():
    params = _parse_search_params()
    if params.q:
        products = []
        total_count = 0
        cities: list[str] = []
        selected_city = params.city or ""
        try:
            with get_public_session() as pub_session:
                cat_repo = get_catalog_repository(pub_session)
                cities, selected_city = _resolve_search_cities(cat_repo, params.city)
                products, total_count = cat_repo.search_articles_paginated(
                    query=params.q,
                    page=params.page,
                    per_page=params.per_page,
                    mode=params.mode,
                    city=selected_city or None,
                )
        except Exception as exc:
            logger.error("Error searching in index: %s", exc)
            flash(_("Ocurrió un error al realizar la búsqueda."), "error")

        pagination = Pagination(
            page=params.page,
            per_page=params.per_page,
            total_items=total_count,
            items=products,
        )
        return render_template(
            "catalog/index.html",
            query=params.q,
            mode=params.mode,
            cities=cities,
            selected_city=selected_city,
            products=products,
            pagination=pagination,
        )

    # When no query is provided, render the rich institutional landing page
    departments = []
    cities = []
    selected_city = params.city or ""
    try:
        with get_public_session() as pub_session:
            cat_repo = get_catalog_repository(pub_session)
            departments = cat_repo.get_departments()
            cities, selected_city = _resolve_search_cities(cat_repo, params.city)
    except Exception as exc:
        logger.debug("Could not load landing page catalog metadata: %s", exc)

    return render_template(
        "catalog/landing.html",
        departments=departments,
        cities=cities,
        selected_city=selected_city,
    )


@catalog_bp.route("/inicio")
@catalog_bp.route("/landing")
def landing():
    params = _parse_search_params()
    departments = []
    cities: list[str] = []
    selected_city = params.city or ""
    try:
        with get_public_session() as pub_session:
            cat_repo = get_catalog_repository(pub_session)
            departments = cat_repo.get_departments()
            cities, selected_city = _resolve_search_cities(cat_repo, params.city)
    except Exception as exc:
        logger.debug("Could not load landing page catalog metadata: %s", exc)

    return render_template(
        "catalog/landing.html",
        departments=departments,
        cities=cities,
        selected_city=selected_city,
    )


@catalog_bp.route("/buscar")
@catalog_bp.route("/productos")
def search_view():
    params = _parse_search_params()
    products = []
    total_count = 0
    cities: list[str] = []
    selected_city = params.city or ""
    try:
        with get_public_session() as pub_session:
            cat_repo = get_catalog_repository(pub_session)
            cities, selected_city = _resolve_search_cities(cat_repo, params.city)
            if params.q:
                products, total_count = cat_repo.search_articles_paginated(
                    query=params.q,
                    page=params.page,
                    per_page=params.per_page,
                    mode=params.mode,
                    city=selected_city or None,
                )
    except Exception as exc:
        logger.error("Error searching: %s", exc)
        flash(_("Ocurrió un error al realizar la búsqueda."), "error")

    pagination = Pagination(
        page=params.page,
        per_page=params.per_page,
        total_items=total_count,
        items=products,
    )
    return render_template(
        "catalog/index.html",
        query=params.q,
        mode=params.mode,
        cities=cities,
        selected_city=selected_city,
        products=products,
        pagination=pagination,
    )


@catalog_bp.route("/help")
@catalog_bp.route("/ayuda")
def help():
    return render_template("catalog/help.html")


@catalog_bp.route("/departments")
def departments():
    try:
        with get_public_session() as session:
            cat_repo = get_catalog_repository(session)
            depts = cat_repo.get_departments()
            return render_template("catalog/departments.html", departments=depts)
    except Exception as exc:
        logger.error("Error loading departments: %s", exc)
        flash(_("Error al cargar las categorías."), "error")
        return render_template("catalog/departments.html", departments=[])


@catalog_bp.route("/department/<slug>")
def department_view(slug: str):
    try:
        with get_public_session() as session:
            cat_repo = get_catalog_repository(session)
            dept = (
                session.execute(
                    select(Category).where(Category.slug == slug, Category.level == 1)
                )
                .scalars()
                .first()
            )
            if not dept:
                flash(_("Departamento no encontrado."), "error")
                return redirect(url_for("catalog.departments"))
            subcategories = cat_repo.get_subcategories(slug)
            return render_template(
                "catalog/department_view.html",
                department=dept,
                subcategories=subcategories,
            )
    except Exception as exc:
        logger.error("Error loading department %s: %s", slug, exc)
        flash(_("Error al cargar el departamento."), "error")
        return redirect(url_for("catalog.departments"))


@catalog_bp.route("/subcategory/<slug>")
def subcategory_view(slug: str):
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        with get_public_session() as session:
            cat_repo = get_catalog_repository(session)
            sub = (
                session.execute(
                    select(Category)
                    .where(Category.slug == slug, Category.level == 2)
                    .options(joinedload(Category.parent))
                )
                .scalars()
                .first()
            )
            if not sub:
                flash(_("Subcategoría no encontrada."), "error")
                return redirect(url_for("catalog.departments"))
            articles, total_count = cat_repo.get_articles_by_subcategory_paginated(
                slug, page=page, per_page=50
            )
            pagination = Pagination(
                page=page,
                per_page=50,
                total_items=total_count,
                items=articles,
            )
            back_url = (
                url_for("catalog.department_view", slug=sub.parent.slug)
                if sub.parent
                else url_for("catalog.departments")
            )
            back_label = sub.parent.name if sub.parent else _("Categorías")
            return render_template(
                "catalog/articles_list.html",
                title=f"{sub.name}",
                subtitle=f"{sub.parent.name if sub.parent else ''} — {total_count} artículos disponibles",
                articles=articles,
                pagination=pagination,
                back_url=back_url,
                back_label=back_label,
            )
    except Exception as exc:
        logger.error("Error loading subcategory %s: %s", slug, exc)
        flash(_("Error al cargar la subcategoría."), "error")
        return redirect(url_for("catalog.departments"))


@catalog_bp.route("/tag/<name>")
def tag_view(name: str):
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (ValueError, TypeError):
        page = 1

    try:
        with get_public_session() as session:
            cat_repo = get_catalog_repository(session)
            articles, total_count = cat_repo.get_articles_by_tag_paginated(
                name, page=page, per_page=50
            )
            pagination = Pagination(
                page=page,
                per_page=50,
                total_items=total_count,
                items=articles,
            )
            return render_template(
                "catalog/articles_list.html",
                title=f"Etiqueta #{name}",
                subtitle=f"{total_count} artículos asociados",
                articles=articles,
                pagination=pagination,
                back_url=url_for("catalog.index"),
                back_label=_("Buscar Productos"),
            )
    except Exception as exc:
        logger.error("Error loading tag %s: %s", name, exc)
        flash(_("Error al cargar los artículos por etiqueta."), "error")
        return redirect(url_for("catalog.index"))


@catalog_bp.route("/article/<ean>")
def article_detail(ean: str):
    query = ArticlePriceStatsQuery.from_request(
        city=request.args.get("city"), date_str=request.args.get("date")
    )
    try:
        user_baskets = []
        user_id = session.get("user_id")
        if user_id:
            try:
                with get_user_session() as u_session:
                    user_repo = get_user_repository(u_session)
                    user_baskets = user_repo.get_user_baskets(user_id=user_id)
            except Exception as e:
                logger.error("Error fetching user baskets for article detail: %s", e)

        with get_public_session() as pub_session:
            price_repo = get_price_repository(pub_session)
            stats = price_repo.get_article_price_stats(
                ean=ean, city=query.city, price_date=query.date
            )
            if not stats:
                flash(_("Artículo no encontrado."), "error")
                return redirect(url_for("catalog.index"))

            return render_template(
                "catalog/article_detail.html",
                stats=stats,
                user_baskets=user_baskets,
            )
    except Exception as exc:
        logger.error("Error loading article detail for ean %s: %s", ean, exc)
        flash(_("Error al cargar los datos del artículo."), "error")
        return redirect(url_for("catalog.index"))
