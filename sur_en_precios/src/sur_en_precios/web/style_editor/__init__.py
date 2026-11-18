"""Standalone local-network visual color palette editor package for style.css."""

from sur_en_precios.web.style_editor.app import create_style_editor_app
from sur_en_precios.web.style_editor.preset_service import (
    PalettePreset,
    delete_user_preset,
    get_preset,
    list_presets,
    save_user_preset,
)
from sur_en_precios.web.style_editor.token_service import (
    ColorToken,
    ContrastCheckResult,
    PaletteState,
    PaletteValidationError,
    TokenGroup,
    apply_palette_to_css_text,
    compute_contrast_ratio,
    compute_relative_luminance,
    evaluate_palette_contrast,
    infer_color_scheme,
    parse_style_css_palette,
    save_palette_to_style_css,
    validate_palette_values,
)

__all__ = [
    "ColorToken",
    "ContrastCheckResult",
    "PalettePreset",
    "PaletteState",
    "PaletteValidationError",
    "TokenGroup",
    "apply_palette_to_css_text",
    "compute_contrast_ratio",
    "compute_relative_luminance",
    "create_style_editor_app",
    "delete_user_preset",
    "evaluate_palette_contrast",
    "get_preset",
    "infer_color_scheme",
    "list_presets",
    "parse_style_css_palette",
    "save_palette_to_style_css",
    "save_user_preset",
    "validate_palette_values",
]
