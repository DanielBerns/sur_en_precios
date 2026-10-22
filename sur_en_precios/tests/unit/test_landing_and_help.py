"""Unit tests for the landing page, institutional information, help page, and static assets."""

from pathlib import Path

from flask import url_for

from sur_en_precios.web.public_app import create_public_app


def test_landing_page_institutional_content(tmp_path: Path):
    workdir = tmp_path / "landing_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # 1. Chakana icon and favicon
    assert "chakana.svg" in html
    assert "favicon.ico" in html
    assert 'rel="icon" type="image/svg+xml"' in html

    # 2. Required institutional information
    assert "Universidad Nacional de la Patagonia San Juan Bosco" in html
    assert "Facultad de Ciencias Económicas" in html
    assert "Observatorio de Economía de los Recursos Naturales de la Patagonia" in html

    # 3. Reserved space for partner entities
    assert "Facultad de Ingeniería" in html
    assert (
        "Grupo de Investigación en Procesamiento de la Información y Sensores" in html
    )
    assert "Facultad de Humanidades y Ciencias Sociales" in html
    assert "Espacio Reservado" in html

    # 4. Spanish UI check
    assert "Sur en Precios" in html
    assert "Buscar Productos" in html
    assert "Mis Canastas" in html
    assert "Optimizar Precios" in html
    assert "Categorías" in html
    assert "Ayuda" in html
    assert "Marco Institucional" in html


def test_landing_page_aliases(tmp_path: Path):
    workdir = tmp_path / "aliases_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    res_inicio = client.get("/inicio")
    assert res_inicio.status_code == 200
    assert "Universidad Nacional de la Patagonia San Juan Bosco" in res_inicio.get_data(
        as_text=True
    )

    res_landing = client.get("/landing")
    assert res_landing.status_code == 200
    assert (
        "Observatorio de Economía de los Recursos Naturales de la Patagonia"
        in res_landing.get_data(as_text=True)
    )


def test_help_page(tmp_path: Path):
    workdir = tmp_path / "help_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    for path in ["/help", "/ayuda"]:
        response = client.get(path)
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert "Centro de Ayuda y Guía de Uso" in html
        assert "Cómo Buscar Productos" in html
        assert "Estadísticas y Precios de Referencia" in html
        assert "media geométrica" in html.lower()
        assert "Gestión de Canastas de Compra" in html
        assert "Optimizador de Precios" in html
        assert "Preguntas Frecuentes" in html
        assert "Contacto Institucional y Soporte" in html
        assert "chakana.svg" in html


def test_static_assets_serving(tmp_path: Path):
    workdir = tmp_path / "static_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    # Favicon route
    res_favicon = client.get("/favicon.ico")
    assert res_favicon.status_code == 200

    # Static chakana svg
    res_svg = client.get("/static/img/chakana.svg")
    assert res_svg.status_code == 200
    assert "image/svg+xml" in res_svg.content_type
    assert b"<svg" in res_svg.data

    # Static favicon.ico
    res_ico = client.get("/static/img/favicon.ico")
    assert res_ico.status_code == 200


def test_search_view_and_url_for_resolution(tmp_path: Path):
    workdir = tmp_path / "routes_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    client = app.test_client()

    with app.test_request_context():
        assert url_for("catalog.index") == "/"
        assert url_for("catalog.landing") in ("/inicio", "/landing")
        assert url_for("catalog.search_view") in ("/buscar", "/productos")
        assert url_for("catalog.help") in ("/help", "/ayuda")

    res_buscar = client.get("/buscar")
    assert res_buscar.status_code == 200
    assert "Buscador de Productos" in res_buscar.get_data(as_text=True)
