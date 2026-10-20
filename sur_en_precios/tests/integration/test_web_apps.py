import base64
import io
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from sur_en_precios.domain.models_public import (
    Article,
    Category,
    DailyPrice,
    DailyProductMetric,
    PointOfSale,
    PublicBase,
    Tag,
)
from sur_en_precios.web.control_app.app import create_control_app
from sur_en_precios.web.public_app.app import create_public_app


def test_control_app_endpoints(tmp_path: Path) -> None:
    workdir = tmp_path / "control_workdir"
    app = create_control_app(workdir=workdir)
    client = app.test_client()

    # Unauthorized access -> 401
    res = client.get("/")
    assert res.status_code == 401

    # Authorized access -> 200
    credentials = base64.b64encode(b"admin:sur_precios_2026").decode("utf-8")
    headers = {"Authorization": f"Basic {credentials}"}
    res_auth = client.get("/", headers=headers)
    assert res_auth.status_code == 200
    assert "Panel de Control" in res_auth.get_data(as_text=True)

    # Log API endpoint
    post_res = client.post(
        "/api/logs/scraper",
        json={
            "job_name": "test_harvester",
            "status": "SUCCESS",
            "file_size_bytes": 1024,
            "duration_ms": 150,
        },
    )
    assert post_res.status_code == 201


def test_public_app_endpoints(tmp_path: Path) -> None:
    workdir = tmp_path / "public_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    # Index page
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert "Buscar Productos" in res_index.get_data(as_text=True)

    # Baskets page
    res_baskets = client.get("/baskets")
    assert res_baskets.status_code == 200
    assert "Mis Canastas" in res_baskets.get_data(as_text=True)

    # Create Basket
    res_create = client.post(
        "/baskets/create", data={"name": "Test Basket", "eans": "779001, 779002"}
    )
    assert res_create.status_code == 302  # Redirects to /baskets

    # Optimize page
    res_opt = client.get("/optimize?city=Bahía+Blanca&date=2026-10-09&eans=779001")
    assert res_opt.status_code == 200
    assert "Optimización de Canasta" in res_opt.get_data(as_text=True)


def test_basket_editor_and_public_sharing(tmp_path: Path) -> None:
    workdir = tmp_path / "editor_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    # 1. New basket creation redirects to editor
    res_new = client.get("/baskets/new")
    assert res_new.status_code == 302
    edit_url = res_new.headers["Location"]
    assert "/edit" in edit_url

    # 2. Load editor page
    res_edit = client.get(edit_url)
    assert res_edit.status_code == 200
    edit_html = res_edit.get_data(as_text=True)
    assert "Nombre de la Canasta" in edit_html
    assert "Canasta Pública" in edit_html
    assert "Buscador de Artículos" in edit_html
    assert "Agregar todos los artículos encontrados" in edit_html
    assert "btn_add_all_found" in edit_html
    assert "addAllFoundArticles" in edit_html

    # Extract basket_id
    basket_id = int(edit_url.split("/baskets/")[1].split("/edit")[0])

    # 3. Test API article search
    res_search = client.get("/api/articles/search?q=aceite&mode=fuzzy")
    assert res_search.status_code == 200
    assert isinstance(res_search.get_json(), list)

    # 4. Save basket changes (toggle is_public=True, items with numerator/denominator and selection)
    save_data = {
        "name": "Canasta Familiar Bahía",
        "is_public": "1",
        "eans": "779001,779002",
        "item_selected_779001": "1",
        "item_quantity_779001": "2",
        "item_numerator_779001": "1",
        "item_denominator_779001": "2",
        # item 779002 has selected=False (unselected)
        "item_quantity_779002": "1",
        "item_numerator_779002": "3",
        "item_denominator_779002": "4",
    }
    res_save = client.post(f"/baskets/{basket_id}/save", data=save_data)
    assert res_save.status_code == 302

    # Reload editor and verify saved properties
    res_saved_edit = client.get(f"/baskets/{basket_id}/edit")
    assert res_saved_edit.status_code == 200
    saved_html = res_saved_edit.get_data(as_text=True)
    assert "Canasta Familiar Bahía" in saved_html
    assert "UUID para Compartir" in saved_html
    assert "Copiar UUID" in saved_html
    assert "Copiar Enlace" in saved_html

    # 5. Export YAML
    res_export = client.get(f"/baskets/{basket_id}/export")
    assert res_export.status_code == 200
    assert "application/x-yaml" in res_export.headers.get("Content-Type", "")
    yaml_data = res_export.get_data(as_text=True)
    assert "Canasta Familiar Bahía" in yaml_data
    assert "numerator: 1" in yaml_data
    assert "denominator: 2" in yaml_data

    # Extract UUID from exported YAML
    import yaml

    parsed_yaml = yaml.safe_load(yaml_data)
    basket_uuid = parsed_yaml["basket"]["uuid"]
    assert basket_uuid is not None

    # 6. Out-of-band UUID sharing view
    res_public = client.get(f"/baskets/public/{basket_uuid}")
    assert res_public.status_code == 200
    public_html = res_public.get_data(as_text=True)
    assert "Canasta Compartida: Canasta Familiar Bahía" in public_html
    assert "Canasta Pública" in public_html
    assert basket_uuid in public_html
    assert "Guardar en Mis Canastas" in public_html

    # Open public basket via UUID form lookup
    res_open = client.get(f"/baskets/open?uuid={basket_uuid}")
    assert res_open.status_code == 302
    assert basket_uuid in res_open.headers["Location"]

    # Clone public basket
    res_clone = client.post(f"/baskets/public/{basket_uuid}/clone")
    assert res_clone.status_code == 302
    assert "/edit" in res_clone.headers["Location"]

    # Test Private Basket 404 access
    res_save_priv = client.post(
        f"/baskets/{basket_id}/save",
        data={"name": "Canasta Privada", "is_public": "0", "eans": "779001"},
    )
    assert res_save_priv.status_code == 302
    res_priv_view = client.get(f"/baskets/public/{basket_uuid}")
    assert res_priv_view.status_code == 404

    # 7. YAML upload / import
    valid_yaml = b"""
basket:
  name: "Canasta Importada"
  is_public: true
  items:
    - ean: "779001"
      quantity: 5
      selected: true
      numerator: 1
      denominator: 1
"""
    res_import = client.post(
        "/baskets/import",
        data={"yaml_file": (io.BytesIO(valid_yaml), "canasta.yaml")},
        content_type="multipart/form-data",
    )
    assert res_import.status_code == 302
    assert "/edit" in res_import.headers["Location"]

    # 8. YAML upload error checking (zero denominator fails fast without traceback)
    invalid_yaml = b"""
basket:
  name: "Canasta Erronea"
  items:
    - ean: "779001"
      denominator: 0
"""
    res_err_import = client.post(
        "/baskets/import",
        data={"yaml_file": (io.BytesIO(invalid_yaml), "invalid.yaml")},
        content_type="multipart/form-data",
    )
    assert res_err_import.status_code == 302
    assert "/baskets" in res_err_import.headers["Location"]

    # 9. Delete basket
    res_delete = client.post(f"/baskets/{basket_id}/delete")
    assert res_delete.status_code == 302
    assert "/baskets" in res_delete.headers["Location"]


def test_public_app_handles_legacy_user_db_migration(tmp_path: Path) -> None:
    """Verifies that an older user_data.sqlite without 'selected' column is migrated without errors."""
    import sqlite3

    workdir = tmp_path / "legacy_workdir"
    workdir.mkdir()
    data_dir = workdir / "data"
    data_dir.mkdir()

    config_file = workdir / "config.yaml"
    config_file.write_text(
        "app:\n"
        "  region: AR-B\n"
        "database:\n"
        "  public_db_filename: public.sqlite\n"
        "  user_db_filename: user_data.sqlite\n",
        encoding="utf-8",
    )

    user_db = data_dir / "user_data.sqlite"
    conn = sqlite3.connect(str(user_db))
    # Create legacy schema without selected, numerator, denominator columns
    conn.executescript("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email VARCHAR(255) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at DATETIME
        );
        CREATE TABLE baskets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid VARCHAR(36) NOT NULL UNIQUE,
            user_id INTEGER NOT NULL,
            name VARCHAR(120) NOT NULL,
            is_public BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE basket_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            basket_id INTEGER NOT NULL,
            ean VARCHAR(32) NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY(basket_id) REFERENCES baskets(id)
        );
        INSERT INTO users (id, email, password_hash) VALUES (1, 'demo@surenprecios.ar', 'hashed');
        INSERT INTO baskets (id, uuid, user_id, name, is_public) VALUES (1, 'test-uuid-1234', 1, 'Canasta Vieja', 0);
        INSERT INTO basket_items (id, basket_id, ean, quantity) VALUES (1, 1, '779001', 2);
    """)
    conn.commit()
    conn.close()

    # Now create public app pointing to this workdir
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    # GET /baskets must succeed without 'OperationalError: no such column: basket_items_1.selected'
    res = client.get("/baskets")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Canasta Vieja" in html

    # Verify column 'selected' was automatically migrated
    conn = sqlite3.connect(str(user_db))
    cols = {
        row[1] for row in conn.execute("PRAGMA table_info(basket_items)").fetchall()
    }
    conn.close()
    assert "selected" in cols
    assert "numerator" in cols
    assert "denominator" in cols


def test_optimize_renders_complete_stores_without_formatting_error(
    tmp_path: Path, monkeypatch
) -> None:
    """Verifies that rendering complete_stores with 100% badge does not crash with ValueError incomplete format."""
    from datetime import date

    from sur_en_precios.domain.models import BasketOptimizationResult, StoreBasketTotal
    from sur_en_precios.domain.models_public import Branch, Flag, Store
    from sur_en_precios.use_cases.optimize_basket import OptimizeBasketUseCase

    workdir = tmp_path / "optimize_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    fake_store = Store(
        code="c1", flag=Flag(flag="Carrefour"), branch=Branch(branch="Centro")
    )
    fake_total = StoreBasketTotal(
        store=fake_store,
        total_price=1500,
        matched_items_count=1,
        requested_items_count=1,
        is_complete=True,
    )
    fake_result = BasketOptimizationResult(
        city="Bahía Blanca",
        calculation_date=date(2026, 10, 9),
        requested_items=[],
        best_single_store=fake_total,
        item_by_item_optimal=[],
        complete_stores=[fake_total],
        partial_stores=[],
        reference_prices={},
    )

    monkeypatch.setattr(
        OptimizeBasketUseCase, "execute", lambda self, *args, **kwargs: fake_result
    )

    res = client.get("/optimize?city=Bahía+Blanca&date=2026-10-09&eans=779001")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "Disponibilidad 100%" in html
    assert "Carrefour — Centro" in html


def test_taxonomy_navigation_routes(tmp_path: Path) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from sur_en_precios.domain.models_public import Article, Category, PublicBase

    workdir = tmp_path / "taxonomy_workdir"
    app = create_public_app(workdir=workdir)
    client = app.test_client()

    public_db_path = workdir / "data" / "public.sqlite"
    public_db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{public_db_path}")
    PublicBase.metadata.create_all(engine)

    with Session(engine) as session:
        dept = Category(name="Almacén", slug="almacen", level=1)
        session.add(dept)
        session.flush()

        sub = Category(name="Aceites", slug="aceites", level=2, parent_id=dept.id)
        tag = Tag(name="sin-tacc", slug="sin-tacc")
        session.add_all([sub, tag])
        session.flush()

        article = Article(
            ean="779001",
            name="Aceite de Girasol 900ml",
            brand_name="Natura",
            package="Botella 900ml",
            package_amount=900.0,
            package_unit="ml",
            category_id=sub.id,
        )
        article.tags.append(tag)
        session.add(article)
        session.commit()

    # 1. /departments
    res_dept = client.get("/departments")
    assert res_dept.status_code == 200
    assert "Explorar por Categoría" in res_dept.get_data(as_text=True)
    assert "Almacén" in res_dept.get_data(as_text=True)

    # 2. /department/almacen
    res_sub = client.get("/department/almacen")
    assert res_sub.status_code == 200
    assert "Aceites" in res_sub.get_data(as_text=True)

    # 3. /subcategory/aceites
    res_art = client.get("/subcategory/aceites")
    assert res_art.status_code == 200
    assert "Aceite de Girasol" in res_art.get_data(as_text=True)
    assert "#sin-tacc" in res_art.get_data(as_text=True)

    # 4. /tag/sin-tacc
    res_tag = client.get("/tag/sin-tacc")
    assert res_tag.status_code == 200
    assert "Etiqueta #sin-tacc" in res_tag.get_data(as_text=True)
    assert "Aceite de Girasol" in res_tag.get_data(as_text=True)


def test_article_price_stats_and_detail_view(tmp_path: Path) -> None:
    workdir = tmp_path / "stats_workdir"
    data_dir = workdir / "data"
    data_dir.mkdir(parents=True)

    app = create_public_app(workdir=workdir)
    client = app.test_client()

    public_db_path = data_dir / "public.sqlite"
    engine = create_engine(f"sqlite:///{public_db_path}")
    PublicBase.metadata.create_all(engine)

    today = date(2026, 10, 9)
    with Session(engine) as session:
        dept = Category(name="Almacén", slug="almacen", level=1)
        session.add(dept)
        session.flush()

        sub = Category(name="Aceites", slug="aceites", level=2, parent_id=dept.id)
        session.add(sub)
        session.flush()

        article = Article(
            ean="779001",
            name="Aceite de Oliva Extra 500ml",
            clean_description="Aceite de Oliva Extra",
            brand_name="Cocinero",
            package="500 ml",
            package_amount=500.0,
            package_unit="ml",
            category_id=sub.id,
        )
        pos = PointOfSale(
            code="pos1",
            brand_name="Carrefour",
            branch_name="Sucursal 1",
            city="Bahía Blanca",
            province="Buenos Aires",
            province_code="AR-B",
        )
        price = DailyPrice(
            date=today,
            ean="779001",
            store_code="pos1",
            price=1500,
            unit_price=3.0,
        )
        metric = DailyProductMetric(
            date=today,
            ean="779001",
            city="Bahía Blanca",
            min_price=1400,
            max_price=1600,
            median_price=1500,
            price_dispersion=0.065,
        )
        session.add_all([article, pos, price, metric])
        session.commit()

    # 1. Test search page results contain clickable EAN link and modal dialog
    res_search = client.get("/?q=oliva")
    assert res_search.status_code == 200
    search_html = res_search.get_data(as_text=True)
    assert (
        "openPriceStatsModal(event, &#39;779001&#39;)" in search_html
        or "openPriceStatsModal(event, '779001')" in search_html
    )
    assert 'href="/article/779001"' in search_html
    assert 'id="price_stats_dialog"' in search_html

    # 2. Test category subcategory page contains clickable EAN link
    res_subcat = client.get("/subcategory/aceites")
    assert res_subcat.status_code == 200
    subcat_html = res_subcat.get_data(as_text=True)
    assert (
        "openPriceStatsModal(event, &#39;779001&#39;)" in subcat_html
        or "openPriceStatsModal(event, '779001')" in subcat_html
    )
    assert 'href="/article/779001"' in subcat_html

    # 3. Test API endpoint /api/articles/779001/price-stats
    res_api = client.get("/api/articles/779001/price-stats")
    assert res_api.status_code == 200
    data = res_api.get_json()
    assert data["ean"] == "779001"
    assert data["name"] == "Aceite de Oliva Extra 500ml"
    assert data["brand_name"] == "Cocinero"
    assert data["min_price"] == 1400
    assert data["max_price"] == 1600
    assert data["reference_price"] == 1500
    assert data["price_dispersion"] == 0.065
    assert data["stores_count"] == 1
    assert data["store_prices"][0]["chain_name"] == "Carrefour"
    assert data["store_prices"][0]["price"] == 1500

    # 4. Test API 404 for non-existent article
    res_api_404 = client.get("/api/articles/000000/price-stats")
    assert res_api_404.status_code == 404
    assert "error" in res_api_404.get_json()

    # 5. Test standalone article detail view /article/779001
    res_detail = client.get("/article/779001")
    assert res_detail.status_code == 200
    detail_html = res_detail.get_data(as_text=True)
    assert "Aceite de Oliva Extra 500ml" in detail_html
    assert "Cocinero" in detail_html
    assert "Precio Mínimo" in detail_html
    assert "$1.400 ARS" in detail_html
    assert "Precio de Referencia" in detail_html
    assert "$1.500 ARS" in detail_html
    assert "Precio Máximo" in detail_html
    assert "$1.600 ARS" in detail_html
    assert "Carrefour" in detail_html
    assert "Sucursal 1" in detail_html

    # 6. Test article detail view redirect for non-existent EAN
    res_detail_404 = client.get("/article/000000")
    assert res_detail_404.status_code == 302
    assert res_detail_404.headers["Location"] == "/"
