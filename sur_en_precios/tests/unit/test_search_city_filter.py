"""Unit and integration tests for city-filtered website and API search."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
)
from sur_en_precios.domain.models_public import (
    Article,
    DailyPrice,
    PointOfSale,
    PublicBase,
)
from sur_en_precios.web.public_app import create_public_app
from sur_en_precios.web.public_app.schemas import (
    ArticlePriceStatsQuery,
    ArticleSearchQuery,
)


def _seed_multi_city_catalog(engine) -> None:
    """Seeds articles, stores, and prices across Comodoro Rivadavia, Trelew, and Bahía Blanca."""
    PublicBase.metadata.create_all(engine)
    today = date(2026, 11, 18)

    with Session(engine) as session:
        stores = [
            PointOfSale(
                code="pos-cr-1",
                brand_name="La Anónima",
                branch_name="Centro CR",
                city="Comodoro Rivadavia",
                province="Chubut",
                province_code="AR-U",
            ),
            PointOfSale(
                code="pos-tw-1",
                brand_name="Carrefour",
                branch_name="Centro Trelew",
                city="Trelew",
                province="Chubut",
                province_code="AR-U",
            ),
            PointOfSale(
                code="pos-bb-1",
                brand_name="Cooperativa Obrera",
                branch_name="Centro Bahía",
                city="Bahía Blanca",
                province="Buenos Aires",
                province_code="AR-B",
            ),
        ]
        articles = [
            Article(
                ean="779000100001",
                name="Leche Entera Comodoro 1L",
                clean_description="Leche Entera Comodoro 1L",
                brand_name="La Serenísima",
            ),
            Article(
                ean="779000100002",
                name="Leche Entera Trelew 1L",
                clean_description="Leche Entera Trelew 1L",
                brand_name="La Serenísima",
            ),
            Article(
                ean="779000100003",
                name="Leche Entera Compartida 1L",
                clean_description="Leche Entera Compartida 1L",
                brand_name="Sancor",
            ),
            Article(
                ean="779000100004",
                name="Leche Entera Bahía 1L",
                clean_description="Leche Entera Bahía 1L",
                brand_name="Ilolay",
            ),
            Article(
                ean="779000100005",
                name="Leche Sin Precio Local 1L",
                clean_description="Leche Sin Precio Local 1L",
                brand_name="SinStock",
            ),
        ]
        prices = [
            DailyPrice(
                date=today,
                ean="779000100001",
                store_code="pos-cr-1",
                price=1500,
            ),
            DailyPrice(
                date=today,
                ean="779000100002",
                store_code="pos-tw-1",
                price=1450,
            ),
            DailyPrice(
                date=today,
                ean="779000100003",
                store_code="pos-cr-1",
                price=1600,
            ),
            DailyPrice(
                date=today,
                ean="779000100003",
                store_code="pos-tw-1",
                price=1550,
            ),
            DailyPrice(
                date=today,
                ean="779000100004",
                store_code="pos-bb-1",
                price=1300,
            ),
        ]
        session.add_all([*stores, *articles, *prices])
        session.commit()


def test_schema_city_normalization():
    assert ArticleSearchQuery(q="leche").city is None
    assert ArticleSearchQuery(q="leche", city="").city is None
    assert ArticleSearchQuery(q="leche", city="   ").city is None
    assert ArticleSearchQuery(q="leche", city="all").city is None
    assert ArticleSearchQuery(q="leche", city="ALL").city is None
    assert (
        ArticleSearchQuery(q="leche", city=" Comodoro Rivadavia ").city
        == "Comodoro Rivadavia"
    )

    assert ArticlePriceStatsQuery.from_request(city="", date_str=None).city is None
    assert ArticlePriceStatsQuery.from_request(city="all", date_str=None).city is None
    assert (
        ArticlePriceStatsQuery.from_request(city=" Trelew ", date_str=None).city
        == "Trelew"
    )


def test_repository_search_articles_city_filter():
    engine = create_engine("sqlite:///:memory:")
    _seed_multi_city_catalog(engine)

    with Session(engine) as session:
        cat_repo = SqlAlchemyCatalogRepository(session)
        price_repo = SqlAlchemyPriceRepository(session)

        # 1. All cities (None, "", "all") returns all 5 articles
        for city_val in (None, "", "all", "ALL"):
            items, total = cat_repo.search_articles_paginated(
                query="Leche", mode="fuzzy", city=city_val
            )
            assert total == 5
            assert len(items) == 5

        # 2. Specific city in fuzzy mode
        cr_items, cr_total = cat_repo.search_articles_paginated(
            query="Leche", mode="fuzzy", city="Comodoro Rivadavia"
        )
        assert cr_total == 2
        assert {a.ean for a in cr_items} == {"779000100001", "779000100003"}

        # 3. Specific city in exact mode
        tw_items, tw_total = cat_repo.search_articles_paginated(
            query="Leche", mode="exact", city="Trelew"
        )
        assert tw_total == 2
        assert {a.ean for a in tw_items} == {"779000100002", "779000100003"}

        # 4. Accent-insensitive and case-insensitive city match
        bb_items = cat_repo.search_articles("Leche", mode="fuzzy", city="bahia blanca")
        assert [a.ean for a in bb_items] == ["779000100004"]

        # 5. Direct numeric EAN search respects city filter
        ean_cr, ean_cr_total = cat_repo.search_articles_paginated(
            query="779000100001", mode="fuzzy", city="Comodoro Rivadavia"
        )
        assert ean_cr_total == 1
        assert [a.ean for a in ean_cr] == ["779000100001"]

        ean_tw, ean_tw_total = cat_repo.search_articles_paginated(
            query="779000100001", mode="fuzzy", city="Trelew"
        )
        assert ean_tw_total == 0
        assert ean_tw == []

        # 6. Unknown city returns empty cleanly
        unknown_items, unknown_total = cat_repo.search_articles_paginated(
            query="Leche", mode="fuzzy", city="Ciudad Inexistente"
        )
        assert unknown_total == 0
        assert unknown_items == []

        # 7. Price stats: multi-city all-cities vs single-city filter
        all_stats = price_repo.get_article_price_stats("779000100003")
        assert all_stats is not None
        assert all_stats.city is None
        assert all_stats.stores_count == 2
        assert all_stats.min_price == 1550
        assert all_stats.max_price == 1600

        tw_stats = price_repo.get_article_price_stats("779000100003", city="Trelew")
        assert tw_stats is not None
        assert tw_stats.city == "Trelew"
        assert tw_stats.stores_count == 1
        assert tw_stats.min_price == 1550
        assert tw_stats.max_price == 1550


def test_website_search_city_selector_and_pagination(tmp_path: Path):
    workdir = tmp_path / "city_search_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True

    config = app.config["APP_CONFIG"]
    public_engine = create_engine(f"sqlite:///{config.get_public_db_path()}")
    _seed_multi_city_catalog(public_engine)

    # Add extra Comodoro-only articles to test city-preserving pagination
    today = date(2026, 11, 18)
    with Session(public_engine) as session:
        extra_articles = [
            Article(
                ean=f"7799000{i:04d}",
                name=f"Arroz Patagónico {i:02d} 1kg",
                clean_description=f"Arroz Patagónico {i:02d} 1kg",
                brand_name="Gallo",
            )
            for i in range(1, 26)
        ]
        extra_prices = [
            DailyPrice(
                date=today,
                ean=f"7799000{i:04d}",
                store_code="pos-cr-1",
                price=2000 + i,
            )
            for i in range(1, 26)
        ]
        session.add_all([*extra_articles, *extra_prices])
        session.commit()

    client = app.test_client()

    # 1. Landing page renders city selector with "Todas las ciudades" + AR-U priced cities
    res_landing = client.get("/")
    assert res_landing.status_code == 200
    landing_html = res_landing.get_data(as_text=True)
    assert 'id="hero_search_city"' in landing_html
    assert 'name="city"' in landing_html
    assert "Todas las ciudades" in landing_html
    assert "Comodoro Rivadavia" in landing_html
    assert "Trelew" in landing_html

    # 2. Dedicated /buscar page renders city selector
    res_buscar = client.get("/buscar")
    assert res_buscar.status_code == 200
    buscar_html = res_buscar.get_data(as_text=True)
    assert 'id="search_city"' in buscar_html
    assert "Todas las ciudades" in buscar_html
    assert "Comodoro Rivadavia" in buscar_html
    assert "Trelew" in buscar_html

    # 3. Search with "all cities" (empty city param) returns all matching articles
    res_all = client.get("/?q=Leche&city=")
    assert res_all.status_code == 200
    html_all = res_all.get_data(as_text=True)
    assert "Leche Entera Comodoro 1L" in html_all
    assert "Leche Entera Trelew 1L" in html_all
    assert "Leche Entera Compartida 1L" in html_all
    assert "Todas las ciudades" in html_all

    # 4. Search scoped to Trelew only returns Trelew articles and propagates city to article links
    res_tw = client.get("/?q=Leche&city=Trelew")
    assert res_tw.status_code == 200
    html_tw = res_tw.get_data(as_text=True)
    assert "Leche Entera Trelew 1L" in html_tw
    assert "Leche Entera Compartida 1L" in html_tw
    assert "Leche Entera Comodoro 1L" not in html_tw
    assert "Leche Sin Precio Local 1L" not in html_tw
    assert 'value="Trelew" selected' in html_tw
    assert 'data-city="Trelew"' in html_tw
    assert "/article/779000100002?city=Trelew" in html_tw

    # 5. Pagination and per_page form preserve selected city
    res_pag = client.get("/?q=Arroz&city=Comodoro+Rivadavia&per_page=20&page=1")
    assert res_pag.status_code == 200
    html_pag = res_pag.get_data(as_text=True)
    assert "Mostrando 1-20 de 25 artículos encontrados" in html_pag
    assert '<input type="hidden" name="city" value="Comodoro Rivadavia">' in html_pag
    assert "city=Comodoro+Rivadavia" in html_pag
    assert "page=2" in html_pag

    # 6. Empty city-filtered search offers one-click fallback to all cities
    res_empty_tw = client.get("/?q=Arroz&city=Trelew")
    assert res_empty_tw.status_code == 200
    html_empty_tw = res_empty_tw.get_data(as_text=True)
    assert 'No se encontraron artículos para "Arroz" en Trelew.' in html_empty_tw
    assert "Buscar en todas las ciudades" in html_empty_tw

    # 7. API /api/articles/search supports city filtering (paginated and unpaginated)
    api_all = client.get("/api/articles/search?q=Leche")
    assert api_all.status_code == 200
    assert len(api_all.get_json()) == 5

    api_tw = client.get("/api/articles/search?q=Leche&city=Trelew")
    assert api_tw.status_code == 200
    tw_payload = api_tw.get_json()
    assert {item["ean"] for item in tw_payload} == {"779000100002", "779000100003"}

    api_cr_pag = client.get(
        "/api/articles/search?q=Leche&city=Comodoro+Rivadavia&page=1&per_page=10&paginated=1"
    )
    assert api_cr_pag.status_code == 200
    cr_pag_data = api_cr_pag.get_json()
    assert cr_pag_data["total"] == 2
    assert {item["ean"] for item in cr_pag_data["items"]} == {
        "779000100001",
        "779000100003",
    }

    # 8. Basket editor includes city selector with "Todas las ciudades" and region cities
    res_new = client.get("/baskets/new")
    assert res_new.status_code == 302
    res_editor = client.get(res_new.headers["Location"])
    assert res_editor.status_code == 200
    editor_html = res_editor.get_data(as_text=True)
    assert 'id="search_city"' in editor_html
    assert "Todas las ciudades" in editor_html
    assert "Comodoro Rivadavia" in editor_html
    assert "Trelew" in editor_html
