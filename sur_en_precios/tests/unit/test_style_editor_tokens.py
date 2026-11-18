"""Unit tests for style_editor token parsing, WCAG contrast, surgical serialization, and presets."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest

from sur_en_precios.tools.run_style_editor import build_parser
from sur_en_precios.web.style_editor.preset_service import (
    delete_user_preset,
    get_preset,
    list_presets,
    save_user_preset,
)
from sur_en_precios.web.style_editor.token_service import (
    DEFAULT_STYLE_CSS_PATH,
    DERIVED_GROUP_MARKER,
    PaletteValidationError,
    apply_palette_to_css_text,
    compute_contrast_ratio,
    compute_relative_luminance,
    infer_color_scheme,
    parse_style_css_palette,
    save_palette_to_style_css,
    validate_palette_values,
)

STYLE_EDITOR_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sur_en_precios"
    / "web"
    / "style_editor"
)


def test_parse_style_css_palette_extracts_all_41_base_tokens() -> None:
    """Verifies parse_style_css_palette discovers 5 @group sections and 41 base hex tokens."""
    state = parse_style_css_palette(DEFAULT_STYLE_CSS_PATH)

    assert state.color_scheme == "dark"
    assert len(state.groups) == 5
    group_ids = [g.id for g in state.groups]
    assert group_ids == [
        "Colors: Surfaces & Backgrounds",
        "Colors: Borders",
        "Colors: Text",
        "Colors: Brand & Semantic Status",
        "Colors: Institutional Reserved Spaces",
    ]

    assert len(state.values) == 41
    for token_name, hex_val in state.values.items():
        assert token_name.startswith("--color-")
        assert re.fullmatch(r"^#[0-9a-f]{6}$", hex_val)

    # Derived dependents and CSS selectors should be populated for bidirectional inspection
    accent_token = next(
        t for g in state.groups for t in g.tokens if t.name == "--color-accent"
    )
    assert "--color-accent-soft" in accent_token.derived_dependents
    assert len(accent_token.selectors) > 0
    assert len(state.contrast_checks) == 10


def test_wcag_luminance_contrast_and_color_scheme_inference() -> None:
    """Verifies WCAG 2.1 relative luminance, contrast ratio math, and auto color-scheme."""
    assert compute_relative_luminance("#000000") == pytest.approx(0.0)
    assert compute_relative_luminance("#ffffff") == pytest.approx(1.0)
    assert compute_contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert compute_contrast_ratio("#0b132b", "#edf2f4") > 14.0

    assert infer_color_scheme({"--color-bg": "#0b132b"}) == "dark"
    assert infer_color_scheme({"--color-bg": "#f1f5f9"}) == "light"


def test_validate_palette_values_enforces_strict_hex_and_token_set() -> None:
    """Rejects missing tokens, unknown tokens, 3-digit hex, or non-hex strings."""
    state = parse_style_css_palette(DEFAULT_STYLE_CSS_PATH)
    expected = set(state.values.keys())

    # Valid
    normalized, scheme = validate_palette_values(
        state.values, expected, color_scheme="auto"
    )
    assert len(normalized) == 41
    assert scheme == "dark"

    # Invalid hex format
    bad_hex = dict(state.values)
    bad_hex["--color-accent"] = "#48c"
    with pytest.raises(PaletteValidationError, match="6-digit hex"):
        validate_palette_values(bad_hex, expected)

    # Unknown token
    extra_tok = dict(state.values)
    extra_tok["--color-nonexistent"] = "#112233"
    with pytest.raises(PaletteValidationError, match="Unknown color tokens"):
        validate_palette_values(extra_tok, expected)

    # Missing token
    missing_tok = dict(state.values)
    missing_tok.pop("--color-bg")
    with pytest.raises(PaletteValidationError, match="Missing required base color tokens"):
        validate_palette_values(missing_tok, expected)


def test_surgical_save_preserves_all_style_css_invariants(tmp_path: Path) -> None:
    """Verifies saving an edited palette updates style.css cleanly, writes a backup, and passes all CSS invariants."""
    temp_css = tmp_path / "style.css"
    backup_dir = tmp_path / "backups"
    shutil.copy2(DEFAULT_STYLE_CSS_PATH, temp_css)

    state = parse_style_css_palette(temp_css)
    expected = set(state.values.keys())

    light_preset = get_preset("patagonia_diurna", expected)
    in_memory_css = apply_palette_to_css_text(
        temp_css.read_text(encoding="utf-8"),
        light_preset.tokens,
        color_scheme="auto",
    )
    assert "color-scheme: light;" in in_memory_css

    updated_state = save_palette_to_style_css(
        values=light_preset.tokens,
        style_css_path=temp_css,
        color_scheme="auto",
        backup_dir=backup_dir,
    )

    assert updated_state.color_scheme == "light"
    assert updated_state.values["--color-bg"] == "#f1f5f9"
    assert updated_state.values["--color-accent"] == "#0369a1"

    # Backup file must exist
    backups = list(backup_dir.glob("backup_*.yaml"))
    assert len(backups) == 1

    # Verify all test_no_inline_css.py invariants on the modified style.css
    css_text = temp_css.read_text(encoding="utf-8")
    assert css_text.count("{") == css_text.count("}")
    assert "@layer tokens, base, layout, components, pages, utilities;" in css_text
    assert DERIVED_GROUP_MARKER in css_text

    defined_vars = set(re.findall(r"(--[a-z0-9-]+)\s*:", css_text))
    used_vars = set(re.findall(r"var\(\s*(--[a-z0-9-]+)", css_text))
    assert sorted(used_vars - defined_vars) == []
    assert sorted(defined_vars - used_vars) == []


def test_builtin_and_user_presets_lifecycle(tmp_path: Path) -> None:
    """Verifies all 4 built-in presets load cleanly and user presets support full CRUD."""
    state = parse_style_css_palette(DEFAULT_STYLE_CSS_PATH)
    expected = set(state.values.keys())
    user_dir = tmp_path / "user_palettes"

    presets = list_presets(expected, user_palettes_dir=user_dir)
    builtin_slugs = {p.slug for p in presets if p.builtin}
    assert {
        "patagonia_nocturna",
        "patagonia_diurna",
        "alto_contraste",
        "estepa_calida",
    }.issubset(builtin_slugs)

    custom_tokens = dict(state.values)
    custom_tokens["--color-accent"] = "#12ab34"

    saved = save_user_preset(
        name="Mi Paleta Austral",
        tokens=custom_tokens,
        expected_token_names=expected,
        user_palettes_dir=user_dir,
        description="Prueba unitaria",
    )
    assert saved.slug == "mi_paleta_austral"
    assert not saved.builtin
    assert saved.tokens["--color-accent"] == "#12ab34"

    fetched = get_preset("mi_paleta_austral", expected, user_palettes_dir=user_dir)
    assert fetched.name == "Mi Paleta Austral"

    assert delete_user_preset("mi_paleta_austral", user_palettes_dir=user_dir) is True
    assert delete_user_preset("mi_paleta_austral", user_palettes_dir=user_dir) is False


def test_style_editor_sources_have_zero_inline_css() -> None:
    """Verifies editor.html, kitchen_sink.html, and editor.js contain zero inline CSS tags, attributes, or .style. mutations."""
    files = [
        STYLE_EDITOR_ROOT / "templates" / "editor.html",
        STYLE_EDITOR_ROOT / "templates" / "kitchen_sink.html",
        STYLE_EDITOR_ROOT / "static" / "editor.js",
    ]
    style_tag_re = re.compile(r"<style\b", re.IGNORECASE)
    inline_style_attr_re = re.compile(r"\bstyle\s*=", re.IGNORECASE)
    js_style_mutation_re = re.compile(
        r"\.style\.|\.cssText\b|setAttribute\s*\(\s*['\"]style['\"]",
        re.IGNORECASE,
    )

    for file_path in files:
        content = file_path.read_text(encoding="utf-8")
        assert not style_tag_re.search(content), f"Found <style> tag in {file_path}"
        assert not inline_style_attr_re.search(content), (
            f"Found inline style= attribute in {file_path}"
        )
        assert not js_style_mutation_re.search(content), (
            f"Found JS inline style mutation in {file_path}"
        )


def test_cli_parser_defaults() -> None:
    """Verifies CLI parser defaults to LAN binding 0.0.0.0:5002."""
    parser = build_parser()
    args = parser.parse_args([])
    assert args.host == "0.0.0.0"
    assert args.port == 5002
    assert args.debug is False
