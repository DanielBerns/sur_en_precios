import logging

from flask import Blueprint, jsonify, request

from sur_en_precios.web.public_app.database import (
    get_catalog_repository,
    get_price_repository,
    get_public_session,
)
from sur_en_precios.web.public_app.schemas import (
    ArticlePriceStatsQuery,
    ArticlePriceStatsResponseSchema,
    ArticleSearchQuery,
    ArticleSearchResultSchema,
    CategoryArticlesQuery,
    StorePriceItemSchema,
)

logger = logging.getLogger("sur_en_precios.public_app.api")

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/articles/search")
def api_search_articles():
    try:
        query = ArticleSearchQuery(
            q=request.args.get("q", ""),
            mode=request.args.get("mode", "fuzzy"),
            limit=request.args.get("limit", 20, type=int),
        )
    except Exception:
        query = ArticleSearchQuery(
            q=request.args.get("q", ""),
            mode="fuzzy",
            limit=20,
        )

    try:
        with get_public_session() as session:
            cat_repo = get_catalog_repository(session)
            results = cat_repo.search_articles(
                query.q, limit=query.limit, mode=query.mode
            )
            payload = [
                ArticleSearchResultSchema(
                    ean=r.ean,
                    name=r.name,
                    brand=getattr(r, "brand_name", None) or "",
                    category=getattr(r, "category_name", None) or "",
                ).model_dump()
                for r in results
            ]
            return jsonify(payload)
    except Exception as exc:
        logger.error(
            "API article search error (q=%r, mode=%s): %s",
            query.q,
            query.mode,
            exc,
        )
        return jsonify([]), 500


@api_bp.route("/categories/<slug>/articles")
def api_category_articles(slug: str):
    try:
        query = CategoryArticlesQuery(limit=request.args.get("limit", 150, type=int))
    except Exception:
        query = CategoryArticlesQuery(limit=150)

    try:
        with get_public_session() as session:
            cat_repo = get_catalog_repository(session)
            articles = cat_repo.get_articles_by_subcategory(slug, limit=query.limit)
            payload = [
                ArticleSearchResultSchema(
                    ean=r.ean,
                    name=r.name,
                    brand=getattr(r, "brand_name", None) or "",
                    category=getattr(r, "category_name", None) or "",
                ).model_dump()
                for r in articles
            ]
            return jsonify(payload)
    except Exception as exc:
        logger.error("API category articles error (slug=%s): %s", slug, exc)
        return jsonify([]), 500


@api_bp.route("/articles/<ean>/price-stats")
def api_article_price_stats(ean: str):
    query = ArticlePriceStatsQuery.from_request(
        city=request.args.get("city"),
        date_str=request.args.get("date"),
    )

    try:
        with get_public_session() as session:
            price_repo = get_price_repository(session)
            stats = price_repo.get_article_price_stats(
                ean=ean, city=query.city, price_date=query.date
            )
            if not stats:
                return jsonify({"error": "Artículo no encontrado"}), 404

            store_prices = [
                StorePriceItemSchema(
                    chain_name=st.chain_name,
                    branch_name=st.branch_name,
                    city=st.city,
                    price=st.price,
                    unit_price=st.unit_price,
                    unit=st.unit,
                    date=st.date.isoformat() if st.date else None,
                )
                for st in stats.store_prices
            ]

            response = ArticlePriceStatsResponseSchema(
                ean=stats.ean,
                name=stats.name,
                clean_description=stats.clean_description,
                brand_name=stats.brand_name,
                package=stats.package,
                category_name=stats.category_name,
                date=stats.date.isoformat() if stats.date else None,
                city=stats.city,
                min_price=stats.min_price,
                max_price=stats.max_price,
                reference_price=stats.reference_price,
                price_dispersion=stats.price_dispersion,
                cheapest_store=stats.cheapest_store,
                most_expensive_store=stats.most_expensive_store,
                stores_count=stats.stores_count,
                store_prices=store_prices,
            )

            return jsonify(response.model_dump())
    except Exception as exc:
        logger.error("API article price stats error (ean=%s): %s", ean, exc)
        return jsonify({"error": "Error interno del servidor"}), 500
