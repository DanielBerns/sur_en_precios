import datetime as dt
from pathlib import Path

from flask import url_for

from sur_en_precios.web.public_app import create_public_app
from sur_en_precios.web.public_app.database import (
    get_or_create_demo_user,
    get_user_repository,
    get_user_session,
)
from sur_en_precios.web.public_app.schemas import (
    ArticlePriceStatsQuery,
    ArticlePriceStatsResponseSchema,
    ArticleSearchQuery,
    ArticleSearchResultSchema,
    BasketCreateForm,
    BasketSaveForm,
    CategoryArticlesQuery,
    OptimizeQuerySchema,
)


def test_pydantic_schemas_validation():
    # 1. ArticleSearchQuery
    search_q = ArticleSearchQuery(q="leche", mode="exact", limit=10)
    assert search_q.q == "leche"
    assert search_q.mode == "exact"
    assert search_q.limit == 10

    # 2. CategoryArticlesQuery
    cat_q = CategoryArticlesQuery(limit=50)
    assert cat_q.limit == 50

    # 3. ArticlePriceStatsQuery
    stats_q = ArticlePriceStatsQuery.from_request(
        city="Bahía Blanca", date_str="2026-10-20"
    )
    assert stats_q.city == "Bahía Blanca"
    assert stats_q.date == dt.date(2026, 10, 20)

    # Invalid date string handled gracefully
    stats_invalid = ArticlePriceStatsQuery.from_request(
        city=None, date_str="not-a-date"
    )
    assert stats_invalid.date is None

    # 4. ArticleSearchResultSchema
    art_result = ArticleSearchResultSchema(
        ean="77912345", name="Yogur", brand="La Serenísima"
    )
    dumped = art_result.model_dump()
    assert dumped["ean"] == "77912345"
    assert dumped["brand"] == "La Serenísima"

    # 5. ArticlePriceStatsResponseSchema
    stats_resp = ArticlePriceStatsResponseSchema(
        ean="77912345",
        name="Yogur Frutilla",
        min_price=1000,
        max_price=1200,
        reference_price=1100,
        price_dispersion=0.09,
        stores_count=2,
    )
    dumped_stats = stats_resp.model_dump()
    assert dumped_stats["min_price"] == 1000
    assert dumped_stats["stores_count"] == 2

    # 6. BasketCreateForm
    create_form = BasketCreateForm(
        name="  Mi Canasta  ", eans="779001, 779002 , , 779003"
    )
    assert create_form.name == "Mi Canasta"
    assert create_form.ean_list == ["779001", "779002", "779003"]

    # 7. BasketSaveForm.from_form
    raw_form = {
        "action": "optimize",
        "name": "Canasta Actualizada",
        "is_public": "1",
        "eans": "779001,779002",
        "item_quantity_779001": "3",
        "item_selected_779001": "1",
        "item_numerator_779001": "1",
        "item_denominator_779001": "2",
        "item_quantity_779002": "-1",  # should be clamped to 1
        "item_numerator_779002": "abc",  # fallback to 1
        "item_denominator_779002": "0",  # invalid denominator clamped to 1
    }
    save_form = BasketSaveForm.from_form(raw_form)
    assert save_form.action == "optimize"
    assert save_form.is_public is True
    assert len(save_form.items) == 2
    assert save_form.items[0].quantity == 3
    assert save_form.items[0].numerator == 1
    assert save_form.items[0].denominator == 2
    assert save_form.items[0].selected is True
    assert save_form.items[1].quantity == 1
    assert save_form.items[1].numerator == 1
    assert save_form.items[1].denominator == 1
    assert save_form.items[1].selected is False

    # 8. OptimizeQuerySchema
    opt_q = OptimizeQuerySchema(
        city="Bahía Blanca",
        date="2026-10-20",
        eans="779001 779002, 779003",
        list_id="10",
        public_uuid="uuid-xyz",
    )
    assert opt_q.ean_list == ["779001", "779002", "779003"]


def test_endpoint_aliases_and_url_for_resolution(tmp_path: Path):
    """Verifies that both blueprint endpoints (e.g. 'catalog.index') and legacy aliases ('index') work with url_for."""
    workdir = tmp_path / "url_workdir"
    app = create_public_app(workdir=workdir)

    with app.test_request_context():
        # Catalog
        assert url_for("catalog.index") == "/"
        assert url_for("index") == "/"
        assert url_for("catalog.departments") == "/departments"
        assert url_for("departments") == "/departments"
        assert (
            url_for("catalog.department_view", slug="almacen") == "/department/almacen"
        )
        assert url_for("department_view", slug="almacen") == "/department/almacen"

        # Baskets
        assert url_for("baskets.baskets") == "/baskets"
        assert url_for("baskets") == "/baskets"
        assert url_for("baskets.new_basket") == "/baskets/new"
        assert url_for("new_basket") == "/baskets/new"
        assert url_for("baskets.edit_basket", basket_id=42) == "/baskets/42/edit"
        assert url_for("edit_basket", basket_id=42) == "/baskets/42/edit"

        # Optimize
        assert url_for("optimize.optimize") == "/optimize"
        assert url_for("optimize") == "/optimize"

        # API
        assert url_for("api.api_search_articles") == "/api/articles/search"
        assert url_for("api_search_articles") == "/api/articles/search"


def test_database_helpers_and_sessions(tmp_path: Path):
    """Verifies session context managers and demo user creation."""
    workdir = tmp_path / "db_helper_workdir"
    app = create_public_app(workdir=workdir)

    with app.app_context():
        with get_user_session() as session:
            repo = get_user_repository(session)
            user1 = get_or_create_demo_user(repo)
            assert user1.email == "demo@surenprecios.ar"
            user2 = get_or_create_demo_user(repo)
            assert user1.id == user2.id


def test_api_search_articles_pagination(tmp_path: Path):
    """Verifies that api_search_articles supports paginated and unpaginated responses."""
    workdir = tmp_path / "search_pagination_workdir"
    app = create_public_app(workdir=workdir)
    client = app.test_client()

    # 1. Unpaginated request returns list
    res_list = client.get("/api/articles/search?q=test")
    assert res_list.status_code == 200
    assert isinstance(res_list.get_json(), list)
    assert "X-Total-Count" in res_list.headers

    # 2. Paginated request returns dict with metadata
    res_pag = client.get("/api/articles/search?q=test&page=1&per_page=10&paginated=1")
    assert res_pag.status_code == 200
    data = res_pag.get_json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "per_page" in data
    assert "total_pages" in data
    assert res_pag.headers.get("X-Page") == "1"
    assert res_pag.headers.get("X-Per-Page") == "10"
