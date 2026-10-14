import base64
import io
from pathlib import Path

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
