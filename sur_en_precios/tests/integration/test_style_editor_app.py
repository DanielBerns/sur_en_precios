"""Integration tests for the standalone style.css visual color palette editor web application."""

from __future__ import annotations

import shutil
from pathlib import Path

from sur_en_precios.web.style_editor.app import create_style_editor_app
from sur_en_precios.web.style_editor.token_service import (
    DEFAULT_STYLE_CSS_PATH,
    parse_style_css_palette,
)


def test_style_editor_workspace_and_kitchen_sink_render(tmp_path: Path) -> None:
    """Verifies main editor UI, Kitchen Sink showcase, and static assets serve cleanly."""
    workdir = tmp_path / "editor_workdir"
    temp_css = tmp_path / "style.css"
    shutil.copy2(DEFAULT_STYLE_CSS_PATH, temp_css)

    app = create_style_editor_app(workdir=workdir, style_css_path=temp_css)
    client = app.test_client()

    # 1. Main visual editor page
    res_index = client.get("/")
    assert res_index.status_code == 200
    html = res_index.get_data(as_text=True)
    assert "Editor Visual de Paleta" in html
    assert "--color-bg" in html
    assert "--color-accent" in html
    assert "--color-reserved-surface" in html
    assert "Patagonia Nocturna" in html
    assert "Patagonia Diurna" in html

    # 2. Kitchen Sink preview canvas
    res_ks = client.get("/preview/kitchen-sink")
    assert res_ks.status_code == 200
    ks_html = res_ks.get_data(as_text=True)
    assert 'href="/static/css/style.css"' in ks_html
    assert "Kitchen Sink" in ks_html
    assert "data-tokens=" in ks_html

    # 3. Static stylesheets
    res_ed_css = client.get("/editor-static/editor.css")
    assert res_ed_css.status_code == 200
    assert "text/css" in res_ed_css.content_type

    res_ed_js = client.get("/editor-static/editor.js")
    assert res_ed_js.status_code == 200

    res_target_css = client.get("/static/css/style.css")
    assert res_target_css.status_code == 200
    assert "no-store" in res_target_css.headers.get("Cache-Control", "")


def test_embedded_same_origin_public_app_preview_routes(tmp_path: Path) -> None:
    """Verifies mounted /preview/app/* routes render public, basket, auth, and admin pages with demo data."""
    workdir = tmp_path / "preview_routes_workdir"
    temp_css = tmp_path / "style.css"
    shutil.copy2(DEFAULT_STYLE_CSS_PATH, temp_css)

    app = create_style_editor_app(workdir=workdir, style_css_path=temp_css)
    client = app.test_client()
    preview_env = app.config["PREVIEW_ENV"]

    for route_info in preview_env.get_preview_routes():
        url = route_info["url"]
        res = client.get(url)
        assert res.status_code == 200, f"Preview route {url} failed with {res.status_code}"
        body = res.get_data(as_text=True)
        assert "style.css" in body


def test_style_editor_rest_api_endpoints(tmp_path: Path) -> None:
    """Verifies GET/POST palette validation, disk save, presets CRUD, import, and export endpoints."""
    workdir = tmp_path / "api_workdir"
    temp_css = tmp_path / "style.css"
    shutil.copy2(DEFAULT_STYLE_CSS_PATH, temp_css)

    app = create_style_editor_app(workdir=workdir, style_css_path=temp_css)
    client = app.test_client()

    # 1. GET /api/palette
    res_get = client.get("/api/palette")
    assert res_get.status_code == 200
    data = res_get.get_json()
    tokens = dict(data["palette"]["values"])
    assert len(tokens) == 41

    # 2. POST /api/palette/validate
    tokens["--color-accent"] = "#00e5ff"
    res_val = client.post(
        "/api/palette/validate",
        json={"tokens": tokens, "color_scheme": "auto"},
    )
    assert res_val.status_code == 200
    assert res_val.get_json()["valid"] is True

    # Invalid token rejected with 400
    bad_tokens = dict(tokens)
    bad_tokens["--color-accent"] = "not-a-hex"
    res_bad = client.post("/api/palette/validate", json={"tokens": bad_tokens})
    assert res_bad.status_code == 400
    assert res_bad.get_json()["valid"] is False

    # 3. POST /api/palette/save-css writes directly to temp_css and creates backup
    res_save = client.post(
        "/api/palette/save-css",
        json={"tokens": tokens, "color_scheme": "dark"},
    )
    assert res_save.status_code == 200
    saved_state = parse_style_css_palette(temp_css)
    assert saved_state.values["--color-accent"] == "#00e5ff"

    # 4. POST /api/presets and DELETE /api/presets/<slug>
    res_preset = client.post(
        "/api/presets",
        json={
            "name": "Tema Red Local",
            "description": "Creado en test de integración",
            "tokens": tokens,
            "color_scheme": "dark",
        },
    )
    assert res_preset.status_code == 201
    slug = res_preset.get_json()["preset"]["slug"]
    assert slug == "tema_red_local"

    res_list = client.get("/api/presets")
    assert res_list.status_code == 200
    all_slugs = [p["slug"] for p in res_list.get_json()["presets"]]
    assert "tema_red_local" in all_slugs

    res_del = client.delete(f"/api/presets/{slug}")
    assert res_del.status_code == 200

    # 5. POST /api/palette/parse-import
    res_imp = client.post(
        "/api/palette/parse-import",
        json={"content": "--color-bg: '#101828'\n--color-accent: '#38bdf8'\n"},
    )
    assert res_imp.status_code == 200
    imp_data = res_imp.get_json()
    assert imp_data["tokens"]["--color-bg"] == "#101828"
    assert imp_data["tokens"]["--color-accent"] == "#38bdf8"

    # 6. POST /api/export/style.css and POST /api/export/palette.yaml
    res_exp_css = client.post(
        "/api/export/style.css",
        json={"tokens": tokens, "color_scheme": "dark"},
    )
    assert res_exp_css.status_code == 200
    assert "--color-accent: #00e5ff;" in res_exp_css.get_data(as_text=True)

    res_exp_yaml = client.post(
        "/api/export/palette.yaml",
        json={"tokens": tokens, "color_scheme": "dark"},
    )
    assert res_exp_yaml.status_code == 200
    assert "#00e5ff" in res_exp_yaml.get_data(as_text=True)
