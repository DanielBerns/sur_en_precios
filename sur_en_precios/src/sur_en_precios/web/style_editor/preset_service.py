"""Palette preset storage and discovery service for built-in and user-defined YAML presets."""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sur_en_precios.web.style_editor.token_service import (
    PaletteValidationError,
    validate_palette_values,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_BUILTIN_PALETTES_DIR",
    "PalettePreset",
    "slugify_preset_name",
    "list_presets",
    "get_preset",
    "save_user_preset",
    "delete_user_preset",
]

DEFAULT_BUILTIN_PALETTES_DIR = (
    Path(__file__).resolve().parents[4] / "data" / "palettes"
)

SLUG_CLEAN_RE = re.compile(r"[^a-z0-9_]+")


@dataclass(frozen=True, slots=True)
class PalettePreset:
    """Represents a named color palette preset (either built-in or user-saved)."""

    slug: str
    name: str
    description: str
    color_scheme: str
    builtin: bool
    tokens: dict[str, str]
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "color_scheme": self.color_scheme,
            "builtin": self.builtin,
            "tokens": dict(self.tokens),
            "created_at": self.created_at,
        }


def slugify_preset_name(name: str) -> str:
    """Converts a human-readable preset name into a safe filesystem slug."""
    lower = name.strip().lower()
    translations = str.maketrans("áéíóúüñ -", "aeiouun__")
    ascii_str = lower.translate(translations)
    cleaned = SLUG_CLEAN_RE.sub("_", ascii_str).strip("_")
    if not cleaned:
        raise PaletteValidationError(f"Invalid preset name: {name!r}")
    return cleaned[:64]


def _load_preset_file(
    file_path: Path,
    expected_token_names: set[str],
    default_builtin: bool,
) -> PalettePreset:
    """Loads and validates a single YAML preset file."""
    with open(file_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    if not isinstance(raw, dict):
        raise PaletteValidationError(f"Invalid preset YAML structure in {file_path}")

    slug = str(raw.get("slug") or file_path.stem).strip()
    name = str(raw.get("name") or slug).strip()
    description = str(raw.get("description") or "").strip()
    raw_tokens = raw.get("tokens")
    if not isinstance(raw_tokens, dict):
        raise PaletteValidationError(f"Preset {file_path} is missing 'tokens' dictionary.")

    normalized_tokens, resolved_scheme = validate_palette_values(
        raw_tokens,
        expected_token_names,
        color_scheme=raw.get("color_scheme"),
    )

    return PalettePreset(
        slug=slug,
        name=name,
        description=description,
        color_scheme=resolved_scheme,
        builtin=bool(raw.get("builtin", default_builtin)),
        tokens=normalized_tokens,
        created_at=str(raw["created_at"]) if raw.get("created_at") else None,
    )


def list_presets(
    expected_token_names: set[str],
    user_palettes_dir: Path | None = None,
    builtin_palettes_dir: Path | None = None,
) -> list[PalettePreset]:
    """Lists all built-in starter presets and user-defined presets."""
    b_dir = (builtin_palettes_dir or DEFAULT_BUILTIN_PALETTES_DIR).expanduser().resolve()
    presets_by_slug: dict[str, PalettePreset] = {}

    if b_dir.is_dir():
        for yaml_path in sorted(b_dir.glob("*.yaml")):
            try:
                preset = _load_preset_file(
                    yaml_path,
                    expected_token_names,
                    default_builtin=True,
                )
                presets_by_slug[preset.slug] = preset
            except Exception as exc:
                logger.warning("Skipping invalid built-in preset %s: %s", yaml_path, exc)

    if user_palettes_dir is not None:
        u_dir = Path(user_palettes_dir).expanduser().resolve()
        if u_dir.is_dir():
            for yaml_path in sorted(u_dir.glob("*.yaml")):
                try:
                    preset = _load_preset_file(
                        yaml_path,
                        expected_token_names,
                        default_builtin=False,
                    )
                    # Do not let user files overwrite built-in slugs
                    if preset.slug in presets_by_slug and presets_by_slug[preset.slug].builtin:
                        custom_slug = f"user_{preset.slug}"
                        preset = PalettePreset(
                            slug=custom_slug,
                            name=preset.name,
                            description=preset.description,
                            color_scheme=preset.color_scheme,
                            builtin=False,
                            tokens=preset.tokens,
                            created_at=preset.created_at,
                        )
                    presets_by_slug[preset.slug] = preset
                except Exception as exc:
                    logger.warning("Skipping invalid user preset %s: %s", yaml_path, exc)

    # Order: patagonia_nocturna first, then other built-ins, then user presets
    def _sort_key(p: PalettePreset) -> tuple[int, str]:
        if p.slug == "patagonia_nocturna":
            return (0, p.name)
        if p.builtin:
            return (1, p.name)
        return (2, p.name)

    return sorted(presets_by_slug.values(), key=_sort_key)


def get_preset(
    slug: str,
    expected_token_names: set[str],
    user_palettes_dir: Path | None = None,
    builtin_palettes_dir: Path | None = None,
) -> PalettePreset:
    """Retrieves a specific preset by slug."""
    for preset in list_presets(
        expected_token_names=expected_token_names,
        user_palettes_dir=user_palettes_dir,
        builtin_palettes_dir=builtin_palettes_dir,
    ):
        if preset.slug == slug:
            return preset
    raise KeyError(f"Palette preset {slug!r} not found.")


def save_user_preset(
    name: str,
    tokens: dict[str, Any],
    expected_token_names: set[str],
    user_palettes_dir: Path,
    description: str = "",
    color_scheme: str | None = None,
    builtin_palettes_dir: Path | None = None,
) -> PalettePreset:
    """Validates and saves a custom user palette preset as a YAML file in user_palettes_dir."""
    cleaned_name = name.strip()
    if not cleaned_name:
        raise PaletteValidationError("Preset name cannot be empty.")

    slug = slugify_preset_name(cleaned_name)

    b_dir = (builtin_palettes_dir or DEFAULT_BUILTIN_PALETTES_DIR).expanduser().resolve()
    if (b_dir / f"{slug}.yaml").exists():
        slug = f"custom_{slug}"

    normalized_tokens, resolved_scheme = validate_palette_values(
        tokens,
        expected_token_names,
        color_scheme=color_scheme,
    )

    u_dir = Path(user_palettes_dir).expanduser().resolve()
    u_dir.mkdir(parents=True, exist_ok=True)
    target_file = u_dir / f"{slug}.yaml"
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()

    payload = {
        "slug": slug,
        "name": cleaned_name,
        "description": description.strip(),
        "color_scheme": resolved_scheme,
        "builtin": False,
        "created_at": created_at,
        "tokens": normalized_tokens,
    }

    temp_file = target_file.with_suffix(".yaml.tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
    temp_file.replace(target_file)
    logger.info("Saved user palette preset '%s' to %s", slug, target_file)

    return PalettePreset(
        slug=slug,
        name=cleaned_name,
        description=description.strip(),
        color_scheme=resolved_scheme,
        builtin=False,
        tokens=normalized_tokens,
        created_at=created_at,
    )


def delete_user_preset(
    slug: str,
    user_palettes_dir: Path,
) -> bool:
    """Deletes a custom user preset YAML file from user_palettes_dir."""
    safe_slug = slugify_preset_name(slug)
    u_dir = Path(user_palettes_dir).expanduser().resolve()
    target_file = u_dir / f"{safe_slug}.yaml"
    if not target_file.is_file():
        return False
    target_file.unlink()
    logger.info("Deleted user palette preset '%s' from %s", safe_slug, target_file)
    return True
