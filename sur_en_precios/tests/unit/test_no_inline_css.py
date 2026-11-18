"""Regression tests enforcing zero inline CSS and visual-editor readiness of style.css."""

from __future__ import annotations

import base64
import re
from pathlib import Path

from sur_en_precios.tools.create_admin import create_admin_user
from sur_en_precios.web.control_app.app import create_control_app
from sur_en_precios.web.public_app import create_public_app
from sur_en_precios.web.public_app.maintenance import (
    clear_maintenance_mode,
    set_maintenance_mode,
)

WEB_ROOT = (
    Path(__file__).resolve().parents[2] / "src" / "sur_en_precios" / "web"
)
PUBLIC_APP_ROOT = WEB_ROOT / "public_app"
TEMPLATES_DIR = PUBLIC_APP_ROOT / "templates"
STYLE_CSS_PATH = PUBLIC_APP_ROOT / "static" / "css" / "style.css"
CHAKANA_SVG_PATH = PUBLIC_APP_ROOT / "static" / "img" / "chakana.svg"
CONTROL_APP_PATH = WEB_ROOT / "control_app" / "app.py"

STYLE_TAG_RE = re.compile(r"<style\b", re.IGNORECASE)
INLINE_STYLE_ATTR_RE = re.compile(r"\bstyle\s*=", re.IGNORECASE)
JS_STYLE_MUTATION_RE = re.compile(
    r"\.style\.|\.cssText\b|setAttribute\s*\(\s*['\"]style['\"]",
    re.IGNORECASE,
)


def _iter_website_source_files() -> list[Path]:
    """Returns all template, SVG, and control_app HTML-rendering source files."""
    files = sorted(TEMPLATES_DIR.rglob("*.html"))
    files.extend([CONTROL_APP_PATH, CHAKANA_SVG_PATH])
    return files


def test_no_inline_css_in_website_sources() -> None:
    """Every website template, inline script, SVG, and control app must be free of inline CSS."""
    source_files = _iter_website_source_files()
    assert len(source_files) >= 20

    for file_path in source_files:
        content = file_path.read_text(encoding="utf-8")
        assert not STYLE_TAG_RE.search(content), f"Found <style> tag in {file_path}"
        assert not INLINE_STYLE_ATTR_RE.search(content), (
            f"Found inline style= attribute in {file_path}"
        )
        assert not JS_STYLE_MUTATION_RE.search(content), (
            f"Found JS inline style mutation in {file_path}"
        )


def test_style_css_exists_and_is_visual_editor_ready() -> None:
    """Verifies style.css follows cascade layers, grouped tokens, and zero hardcoded colors outside tokens."""
    assert STYLE_CSS_PATH.is_file()
    css = STYLE_CSS_PATH.read_text(encoding="utf-8")

    # 1. Balanced braces and explicit cascade layer order
    assert css.count("{") == css.count("}")
    assert "@layer tokens, base, layout, components, pages, utilities;" in css
    assert "@layer tokens {" in css
    assert ":root {" in css

    # 2. Structured @group markers for offline visual editor discovery
    groups = re.findall(r"/\*\s*@group\s+([^*]+?)\s*\*/", css)
    assert len(groups) >= 10

    # 3. Every referenced CSS custom property is defined, and every defined token is used
    defined_vars = set(re.findall(r"(--[a-z0-9-]+)\s*:", css))
    used_vars = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", css))
    assert sorted(used_vars - defined_vars) == []
    assert sorted(defined_vars - used_vars) == []

    # 4. Zero hardcoded hex/rgb/hsl color literals outside @layer tokens
    tokens_end_idx = css.index("@layer base")
    non_token_css = re.sub(r"/\*.*?\*/", "", css[tokens_end_idx:], flags=re.DOTALL)
    assert re.findall(r"#[0-9a-fA-F]{3,8}\b", non_token_css) == []
    assert re.findall(r"\b(?:rgba?|hsla?)\(", non_token_css, flags=re.IGNORECASE) == []

    # 5. Base editable color tokens (before Derived Tints) use 6-digit hex (#rrggbb)
    tokens_section = css[:tokens_end_idx]
    derived_marker = "/* @group Colors: Derived Tints & Overlays */"
    assert derived_marker in tokens_section
    base_colors_section = tokens_section[: tokens_section.index(derived_marker)]
    base_color_decls = re.findall(
        r"(--color-[a-z0-9-]+)\s*:\s*([^;]+);", base_colors_section
    )
    assert len(base_color_decls) >= 25
    for token_name, token_val in base_color_decls:
        assert re.fullmatch(r"#[0-9a-fA-F]{6}", token_val.strip()), (
            f"Base color token {token_name} should use 6-digit hex for color-picker compatibility, got {token_val!r}"
        )


def test_rendered_public_pages_link_style_css_with_no_inline_css(
    tmp_path: Path,
) -> None:
    """All rendered public, auth, basket, optimize, admin, and maintenance pages link style.css cleanly."""
    workdir = tmp_path / "css_routes_workdir"
    app = create_public_app(workdir=workdir)
    app.config["TESTING"] = True
    app.config["CSRF_ENABLED"] = False
    client = app.test_client()

    # Static stylesheet served cleanly with text/css
    res_css = client.get("/static/css/style.css")
    assert res_css.status_code == 200
    assert "text/css" in res_css.content_type
    assert b"@layer tokens, base, layout, components, pages, utilities;" in res_css.data

    # Create a basket so editor page can also be rendered
    res_new = client.get("/baskets/new")
    assert res_new.status_code == 302
    editor_path = res_new.headers["Location"]

    public_routes = [
        "/",
        "/buscar",
        "/departments",
        "/help",
        "/auth/login",
        "/auth/register",
        "/baskets",
        editor_path,
        "/optimize",
    ]
    for route in public_routes:
        res = client.get(route)
        assert res.status_code == 200, f"Unexpected status {res.status_code} on {route}"
        html = res.get_data(as_text=True)
        assert 'href="/static/css/style.css"' in html, f"Missing style.css link on {route}"
        assert not STYLE_TAG_RE.search(html), f"Rendered <style> tag on {route}"
        assert not INLINE_STYLE_ATTR_RE.search(html), (
            f"Rendered inline style= attribute on {route}"
        )

    # Admin pages rendered cleanly without inline CSS
    create_admin_user(
        username="admin_css_check",
        password="AdminPassword123!",
        workdir_override=workdir,
    )
    app.config["TESTING"] = False
    res_login = client.post(
        "/auth/login",
        data={"username": "admin_css_check", "password": "AdminPassword123!"},
        follow_redirects=True,
    )
    assert res_login.status_code == 200

    for admin_route in ["/admin/dashboard", "/admin/users", "/admin/baskets", "/admin/system"]:
        res = client.get(admin_route)
        assert res.status_code == 200, f"Unexpected status {res.status_code} on {admin_route}"
        html = res.get_data(as_text=True)
        assert 'href="/static/css/style.css"' in html
        assert not STYLE_TAG_RE.search(html), f"Rendered <style> tag on {admin_route}"
        assert not INLINE_STYLE_ATTR_RE.search(html), (
            f"Rendered inline style= attribute on {admin_route}"
        )

    # Maintenance 503 page links style.css and /static/css/style.css remains accessible
    config = app.config["APP_CONFIG"]
    set_maintenance_mode(config, reason="CSS check")
    try:
        res_maint = client.get("/")
        assert res_maint.status_code == 503
        maint_html = res_maint.get_data(as_text=True)
        assert 'href="/static/css/style.css"' in maint_html
        assert not STYLE_TAG_RE.search(maint_html)
        assert not INLINE_STYLE_ATTR_RE.search(maint_html)

        res_maint_css = client.get("/static/css/style.css")
        assert res_maint_css.status_code == 200
    finally:
        clear_maintenance_mode(config)


def test_control_app_links_shared_style_css_without_inline_css(tmp_path: Path) -> None:
    """Control app dashboard also serves and links the single style.css without inline CSS."""
    workdir = tmp_path / "control_css_workdir"
    app = create_control_app(workdir=workdir)
    client = app.test_client()

    res_css = client.get("/static/css/style.css")
    assert res_css.status_code == 200
    assert "text/css" in res_css.content_type

    credentials = base64.b64encode(b"admin:sur_precios_2026").decode("utf-8")
    res_dash = client.get("/", headers={"Authorization": f"Basic {credentials}"})
    assert res_dash.status_code == 200
    html = res_dash.get_data(as_text=True)
    assert 'href="/static/css/style.css"' in html
    assert not STYLE_TAG_RE.search(html)
    assert not INLINE_STYLE_ATTR_RE.search(html)
