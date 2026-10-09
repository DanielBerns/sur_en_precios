import base64
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
