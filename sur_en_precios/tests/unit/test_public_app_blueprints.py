import datetime as dt
import json
from pathlib import Path

from flask import url_for
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.domain.models_public import (
    Article,
    DailyPrice,
    PointOfSale,
)
from sur_en_precios.domain.models_user import Basket, BasketItem
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
        assert (
            url_for("baskets.export_basket_prices_json", basket_id=42)
            == "/baskets/42/export-prices-json"
        )
        assert (
            url_for("export_basket_prices_json", basket_id=42)
            == "/baskets/42/export-prices-json"
        )
        assert (
            url_for("baskets.export_public_basket_prices_json", uuid_str="abc-123")
            == "/baskets/public/abc-123/export-prices-json"
        )
        assert (
            url_for("export_public_basket_prices_json", uuid_str="abc-123")
            == "/baskets/public/abc-123/export-prices-json"
        )

        # Optimize
        assert url_for("optimize.optimize") == "/optimize"
        assert url_for("optimize") == "/optimize"
        assert url_for("optimize.export_optimize_json") == "/optimize/export-json"
        assert url_for("export_optimize_json") == "/optimize/export-json"

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


def test_export_basket_prices_json_endpoint(tmp_path: Path):
    """Verifies that export_basket_prices_json generates a downloadable JSON price report."""
    workdir = tmp_path / "export_json_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True

    config = app.config["APP_CONFIG"]
    public_engine = create_engine(f"sqlite:///{config.get_public_db_path()}")
    user_engine = create_engine(f"sqlite:///{config.get_user_db_path()}")

    target_date = dt.date(2026, 10, 20)

    with Session(public_engine) as pub_session:
        pos = PointOfSale(
            code="POS-01",
            brand_name="Supermercado Sur",
            branch_name="Sucursal Central",
            city="Comodoro Rivadavia",
            address="San Martin 500",
        )
        art = Article(
            ean="7790001",
            name="Leche Entera 1L",
            clean_description="Leche Entera 1L",
            brand_name="La Serenísima",
            package="1 L",
            package_amount=1.0,
            package_unit="L",
        )
        dp = DailyPrice(
            date=target_date,
            ean="7790001",
            store_code="POS-01",
            price=1500,
            unit_price=1500.0,
        )
        pub_session.add_all([pos, art, dp])
        pub_session.commit()

    with Session(user_engine) as u_session:
        user_repo = get_user_repository(u_session)
        demo_user = get_or_create_demo_user(user_repo)
        demo_user_id = demo_user.id
        basket = Basket(
            user_id=demo_user_id,
            name="Canasta Familiar",
            is_public=False,
            items=[
                BasketItem(
                    ean="7790001",
                    quantity=2,
                    selected=True,
                    numerator=1,
                    denominator=1,
                )
            ],
        )
        saved_basket = user_repo.save_basket(basket)
        basket_id = saved_basket.id

    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user_id"] = demo_user_id

    # Test GET export-prices-json
    res = client.get(
        f"/baskets/{basket_id}/export-prices-json?city=Comodoro Rivadavia&date=2026-10-20"
    )
    assert res.status_code == 200
    assert "application/json" in res.content_type
    cd = res.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert ".json" in cd

    data = json.loads(res.get_data(as_text=True))
    assert data["report_type"] == "basket_prices_report"
    assert data["version"] == "1.0"
    assert data["basket"]["id"] == basket_id
    assert data["basket"]["name"] == "Canasta Familiar"
    assert data["parameters"]["city"] == "Comodoro Rivadavia"
    assert data["parameters"]["date"] == "2026-10-20"
    assert data["summary"]["priced_items_count"] == 1
    assert data["summary"]["multi_store_optimal_total"] == 3000
    assert len(data["articles"]) == 1
    assert data["articles"][0]["ean"] == "7790001"
    assert data["articles"][0]["min_price"] == 1500
    assert data["articles"][0]["weighted_subtotal"] == 3000


def test_export_public_basket_prices_json_endpoint(tmp_path: Path):
    """Verifies that public baskets can be exported as JSON prices reports without login."""
    workdir = tmp_path / "public_export_json_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True

    config = app.config["APP_CONFIG"]
    public_engine = create_engine(f"sqlite:///{config.get_public_db_path()}")
    user_engine = create_engine(f"sqlite:///{config.get_user_db_path()}")

    target_date = dt.date(2026, 10, 20)

    with Session(public_engine) as pub_session:
        pos = PointOfSale(
            code="POS-PUB",
            brand_name="Super Barato",
            branch_name="Centro",
            city="Comodoro Rivadavia",
        )
        art = Article(
            ean="7790002",
            name="Arroz 1kg",
            clean_description="Arroz 1kg",
            brand_name="Gallo",
            package="1 kg",
            package_amount=1.0,
            package_unit="kg",
        )
        dp = DailyPrice(
            date=target_date,
            ean="7790002",
            store_code="POS-PUB",
            price=1200,
            unit_price=1200.0,
        )
        pub_session.add_all([pos, art, dp])
        pub_session.commit()

    with Session(user_engine) as u_session:
        user_repo = get_user_repository(u_session)
        demo_user = get_or_create_demo_user(user_repo)
        pub_basket = Basket(
            user_id=demo_user.id,
            name="Canasta Compartida",
            uuid="pub-1234-uuid-test",
            is_public=True,
            items=[
                BasketItem(
                    ean="7790002",
                    quantity=1,
                    selected=True,
                    numerator=1,
                    denominator=1,
                )
            ],
        )
        priv_basket = Basket(
            user_id=demo_user.id,
            name="Canasta Privada",
            uuid="priv-5678-uuid-test",
            is_public=False,
            items=[
                BasketItem(
                    ean="7790002",
                    quantity=1,
                    selected=True,
                    numerator=1,
                    denominator=1,
                )
            ],
        )
        user_repo.save_basket(pub_basket)
        user_repo.save_basket(priv_basket)

    client = app.test_client()

    # 1. Anonymous access to public basket prices JSON
    res_pub = client.get(
        "/baskets/public/pub-1234-uuid-test/export-prices-json?city=Comodoro Rivadavia&date=2026-10-20"
    )
    assert res_pub.status_code == 200
    assert "application/json" in res_pub.content_type
    assert ".json" in res_pub.headers.get("Content-Disposition", "")
    data_pub = json.loads(res_pub.get_data(as_text=True))
    assert data_pub["basket"]["uuid"] == "pub-1234-uuid-test"
    assert data_pub["summary"]["priced_items_count"] == 1

    # 2. Anonymous access to private basket -> 404
    res_priv = client.get("/baskets/public/priv-5678-uuid-test/export-prices-json")
    assert res_priv.status_code == 404


def test_optimize_export_json_endpoints(tmp_path: Path):
    """Verifies that /optimize supports downloading JSON price reports via format=json and export-json."""
    workdir = tmp_path / "optimize_export_json_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True

    config = app.config["APP_CONFIG"]
    public_engine = create_engine(f"sqlite:///{config.get_public_db_path()}")

    target_date = dt.date(2026, 10, 20)

    with Session(public_engine) as pub_session:
        pos = PointOfSale(
            code="POS-OPT",
            brand_name="Super Optimo",
            branch_name="Sucursal 1",
            city="Comodoro Rivadavia",
        )
        art = Article(
            ean="7799991",
            name="Yerba Mate 1kg",
            clean_description="Yerba Mate 1kg",
            brand_name="Playadito",
        )
        dp = DailyPrice(
            date=target_date,
            ean="7799991",
            store_code="POS-OPT",
            price=2500,
            unit_price=2500.0,
        )
        pub_session.add_all([pos, art, dp])
        pub_session.commit()

    client = app.test_client()

    # 1. /optimize?format=json
    res_fmt = client.get(
        "/optimize?city=Comodoro Rivadavia&date=2026-10-20&eans=7799991&format=json"
    )
    assert res_fmt.status_code == 200
    assert "application/json" in res_fmt.content_type
    assert ".json" in res_fmt.headers.get("Content-Disposition", "")
    data_fmt = json.loads(res_fmt.get_data(as_text=True))
    assert data_fmt["report_type"] == "basket_prices_report"
    assert data_fmt["parameters"]["city"] == "Comodoro Rivadavia"
    assert data_fmt["summary"]["priced_items_count"] == 1
    assert data_fmt["articles"][0]["ean"] == "7799991"
    assert data_fmt["articles"][0]["min_price"] == 2500

    # 2. /optimize/export-json
    res_route = client.get(
        "/optimize/export-json?city=Comodoro Rivadavia&date=2026-10-20&eans=7799991"
    )
    assert res_route.status_code == 200
    assert "application/json" in res_route.content_type
    data_route = json.loads(res_route.get_data(as_text=True))
    assert data_route["summary"]["multi_store_optimal_total"] == 2500

    # 3. Empty request with format=json returns 400
    res_empty = client.get("/optimize?format=json")
    assert res_empty.status_code == 400
    assert "error" in json.loads(res_empty.get_data(as_text=True))


def test_optimize_dropdown_displays_priced_chubut_cities(tmp_path: Path):
    """Regression test: /optimize city selector shows priced AR-U cities instead of unpriced AR-B rows."""
    workdir = tmp_path / "optimize_chubut_workdir"
    workdir.mkdir()
    # Simulate a legacy PythonAnywhere config.yaml that still had AR-B
    (workdir / "config.yaml").write_text("app:\n  region: AR-B\n", encoding="utf-8")

    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True

    config = app.config["APP_CONFIG"]
    public_engine = create_engine(f"sqlite:///{config.get_public_db_path()}")
    target_date = dt.date(2026, 10, 24)

    with Session(public_engine) as pub_session:
        unpriced_arb = PointOfSale(
            code="(10-1-1)(carrefour)",
            brand_name="Carrefour",
            branch_name="25 De Mayo",
            city="25 De Mayo",
            province="Buenos Aires",
            province_code="AR-B",
        )
        priced_comodoro = PointOfSale(
            code="9-2-101",
            brand_name="La Anónima",
            branch_name="Centro",
            city="Comodoro Rivadavia",
            province="Chubut",
            province_code="AR-U",
        )
        priced_trelew = PointOfSale(
            code="9-2-102",
            brand_name="Cooperativa Obrera",
            branch_name="Trelew",
            city="Trelew",
            province="Chubut",
            province_code="AR-U",
        )
        art = Article(
            ean="7790895000430",
            name="Gaseosa Coca-Cola 1.5L",
            clean_description="Gaseosa Coca-Cola 1.5L",
            brand_name="Coca-Cola",
        )
        dp1 = DailyPrice(
            date=target_date,
            ean="7790895000430",
            store_code="9-2-101",
            price=2500,
        )
        dp2 = DailyPrice(
            date=target_date,
            ean="7790895000430",
            store_code="9-2-102",
            price=2450,
        )
        pub_session.add_all(
            [unpriced_arb, priced_comodoro, priced_trelew, art, dp1, dp2]
        )
        pub_session.commit()

    client = app.test_client()
    res = client.get("/optimize")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Comodoro Rivadavia" in html
    assert "Trelew" in html
    assert "25 De Mayo" not in html
