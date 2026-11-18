"""CSS token parser, validator, WCAG contrast calculator, and surgical serializer for style.css."""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_STYLE_CSS_PATH",
    "DERIVED_GROUP_MARKER",
    "HEX_COLOR_RE",
    "TOKEN_METADATA",
    "GROUP_LABELS",
    "CONTRAST_PAIRS",
    "ColorToken",
    "TokenGroup",
    "ContrastCheckResult",
    "PaletteState",
    "PaletteValidationError",
    "compute_relative_luminance",
    "compute_contrast_ratio",
    "infer_color_scheme",
    "evaluate_palette_contrast",
    "parse_style_css_palette",
    "validate_palette_values",
    "apply_palette_to_css_text",
    "save_palette_to_style_css",
]

DEFAULT_STYLE_CSS_PATH = (
    Path(__file__).resolve().parents[1]
    / "public_app"
    / "static"
    / "css"
    / "style.css"
)

DERIVED_GROUP_MARKER = "/* @group Colors: Derived Tints & Overlays */"
HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
GROUP_COMMENT_RE = re.compile(r"/\*\s*@group\s+([^*]+?)\s*\*/")
TOKEN_DECL_RE = re.compile(r"(--color-[a-z0-9-]+)\s*:\s*([^;]+);")
ANY_VAR_DECL_RE = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);")
VAR_REF_RE = re.compile(r"var\(\s*(--[a-z0-9-]+)")
COLOR_SCHEME_RE = re.compile(r"(color-scheme\s*:\s*)(dark|light)(\s*;)")

GROUP_LABELS: dict[str, dict[str, str]] = {
    "Colors: Surfaces & Backgrounds": {
        "title": "Superficies y Fondos",
        "description": "Fondos de página, tarjetas, cabeceras, formularios y gradientes de portada.",
    },
    "Colors: Borders": {
        "title": "Bordes y Divisores",
        "description": "Contornos de tarjetas, tablas, campos de entrada y separadores estructurales.",
    },
    "Colors: Text": {
        "title": "Tipografía y Texto",
        "description": "Jerarquía de lectura: texto principal, títulos destacados, metadatos y texto sobre acentos.",
    },
    "Colors: Brand & Semantic Status": {
        "title": "Marca y Estados Semánticos",
        "description": "Acentos interactivos, precios mínimos/máximos, alertas, resplandor Chakana y sombras.",
    },
    "Colors: Institutional Reserved Spaces": {
        "title": "Espacios Institucionales (UNPSJB)",
        "description": "Paleta distintiva para tarjetas y emblemas de facultades y grupos de investigación.",
    },
}

TOKEN_METADATA: dict[str, dict[str, str]] = {
    "--color-bg": {
        "label": "Fondo Principal",
        "description": "Fondo base del documento (body) y base de velos translúcidos.",
    },
    "--color-surface": {
        "label": "Superficie de Tarjetas",
        "description": "Fondo principal de tarjetas (.card), paneles y contenedores.",
    },
    "--color-surface-subtle": {
        "label": "Superficie Sutil",
        "description": "Fondo de filas alternas, cabeceras de tabla y bloques secundarios.",
    },
    "--color-surface-elevated": {
        "label": "Superficie Elevada",
        "description": "Fondo de diálogos modales, paneles destacados y barras flotantes.",
    },
    "--color-surface-deep": {
        "label": "Superficie Profunda",
        "description": "Fondo de bloques profundos, pozos de código y métricas internas.",
    },
    "--color-surface-hover": {
        "label": "Superficie en Hover",
        "description": "Color de superficie al pasar el cursor sobre filas o tarjetas interactivas.",
    },
    "--color-surface-header": {
        "label": "Fondo de Cabecera",
        "description": "Barra superior de navegación principal (.site-header).",
    },
    "--color-surface-footer": {
        "label": "Fondo de Pie de Página",
        "description": "Sección inferior institucional (.site-footer).",
    },
    "--color-surface-input": {
        "label": "Fondo de Controles",
        "description": "Campos de texto, buscadores, selectores y áreas de entrada.",
    },
    "--color-hero-bg-start": {
        "label": "Gradiente Hero (Inicio)",
        "description": "Color inicial del gradiente en el bloque principal de bienvenida.",
    },
    "--color-hero-bg-end": {
        "label": "Gradiente Hero (Fin)",
        "description": "Color final del gradiente en el bloque principal de bienvenida.",
    },
    "--color-border": {
        "label": "Borde General",
        "description": "Contorno estándar de tarjetas, botones secundarios e inputs.",
    },
    "--color-border-hover": {
        "label": "Borde en Hover",
        "description": "Contorno resaltado al enfocar o pasar el cursor sobre tarjetas.",
    },
    "--color-border-subtle": {
        "label": "Borde Sutil",
        "description": "Líneas de celdas de tabla y separadores internos suaves.",
    },
    "--color-border-footer": {
        "label": "Borde de Pie de Página",
        "description": "Línea divisoria superior e interna del pie de página.",
    },
    "--color-border-divider": {
        "label": "Divisor Interno",
        "description": "Separadores discretos entre secciones de contenido.",
    },
    "--color-border-disabled": {
        "label": "Borde Deshabilitado",
        "description": "Contorno para elementos inactivos o sin disponibilidad.",
    },
    "--color-border-muted": {
        "label": "Borde Atenuado",
        "description": "Bordes punteados o de espacios vacíos / placeholders.",
    },
    "--color-text": {
        "label": "Texto Principal",
        "description": "Color predeterminado de párrafos y contenido general.",
    },
    "--color-text-strong": {
        "label": "Texto Destacado",
        "description": "Títulos principales, valores numéricos fuertes y nombres de productos.",
    },
    "--color-text-muted": {
        "label": "Texto Secundario",
        "description": "Subtítulos, descripciones auxiliares y etiquetas de formulario.",
    },
    "--color-text-subtle": {
        "label": "Texto Sutil",
        "description": "Notas al pie, marcas de tiempo y ayudas contextuales.",
    },
    "--color-text-on-accent": {
        "label": "Texto sobre Acento",
        "description": "Texto dentro de botones primarios, insignias activas y llamadas a la acción.",
    },
    "--color-text-on-danger": {
        "label": "Texto sobre Peligro",
        "description": "Texto dentro de botones de eliminación y alertas críticas.",
    },
    "--color-accent": {
        "label": "Acento Primario",
        "description": "Color insignia para botones principales, enlaces activos y foco.",
    },
    "--color-accent-hover": {
        "label": "Acento Primario (Hover)",
        "description": "Variante del acento primario al pasar el cursor.",
    },
    "--color-accent-secondary": {
        "label": "Acento Secundario",
        "description": "Tono complementario brillante para destacados y gradientes de marca.",
    },
    "--color-success": {
        "label": "Éxito / Precio Mínimo",
        "description": "Indicador de mejor precio, ahorro potencial y operaciones exitosas.",
    },
    "--color-success-hover": {
        "label": "Éxito (Hover)",
        "description": "Variante al pasar el cursor sobre botones de confirmación/éxito.",
    },
    "--color-warning": {
        "label": "Advertencia / Referencia",
        "description": "Avisos preventivos, precio medio de referencia e insignias de atención.",
    },
    "--color-danger": {
        "label": "Peligro / Precio Máximo",
        "description": "Alertas de error, acciones destructivas e indicador de precio más caro.",
    },
    "--color-logo-glow": {
        "label": "Resplandor de Logo",
        "description": "Halo luminoso proyectado detrás del emblema Chakana.",
    },
    "--color-shadow": {
        "label": "Base de Sombras",
        "description": "Color base mezclado en todas las sombras de elevación (--shadow-*).",
    },
    "--color-reserved-surface": {
        "label": "Superficie Institucional",
        "description": "Color base para fondos translúcidos de espacios reservados UNPSJB.",
    },
    "--color-reserved-border": {
        "label": "Borde Institucional",
        "description": "Contorno de tarjetas de espacios reservados institucionales.",
    },
    "--color-reserved-border-hover": {
        "label": "Borde Institucional (Hover)",
        "description": "Contorno activo al pasar el cursor sobre bloques institucionales.",
    },
    "--color-reserved-badge-border": {
        "label": "Borde Insignia Institucional",
        "description": "Contorno de píldoras e insignias en tarjetas institucionales.",
    },
    "--color-reserved-accent": {
        "label": "Acento Institucional",
        "description": "Color de énfasis e iconos dentro de espacios reservados.",
    },
    "--color-reserved-heading": {
        "label": "Título Institucional",
        "description": "Encabezados de tarjetas de facultades y grupos de investigación.",
    },
    "--color-reserved-text": {
        "label": "Texto Institucional",
        "description": "Cuerpo de texto en bloques institucionales reservados.",
    },
    "--color-reserved-meta": {
        "label": "Metadatos Institucionales",
        "description": "Etiquetas y notas secundarias en tarjetas institucionales.",
    },
}

CONTRAST_PAIRS: list[dict[str, Any]] = [
    {
        "id": "text-on-bg",
        "label": "Texto principal sobre Fondo",
        "fg": "--color-text",
        "bg": "--color-bg",
        "min_ratio": 4.5,
    },
    {
        "id": "text-on-surface",
        "label": "Texto principal sobre Tarjeta",
        "fg": "--color-text",
        "bg": "--color-surface",
        "min_ratio": 4.5,
    },
    {
        "id": "strong-on-surface",
        "label": "Texto destacado sobre Tarjeta",
        "fg": "--color-text-strong",
        "bg": "--color-surface",
        "min_ratio": 4.5,
    },
    {
        "id": "strong-on-input",
        "label": "Texto destacado sobre Input",
        "fg": "--color-text-strong",
        "bg": "--color-surface-input",
        "min_ratio": 4.5,
    },
    {
        "id": "muted-on-bg",
        "label": "Texto secundario sobre Fondo",
        "fg": "--color-text-muted",
        "bg": "--color-bg",
        "min_ratio": 4.5,
    },
    {
        "id": "muted-on-surface",
        "label": "Texto secundario sobre Tarjeta",
        "fg": "--color-text-muted",
        "bg": "--color-surface",
        "min_ratio": 4.5,
    },
    {
        "id": "accent-on-surface",
        "label": "Acento primario sobre Tarjeta",
        "fg": "--color-accent",
        "bg": "--color-surface",
        "min_ratio": 3.0,
    },
    {
        "id": "on-accent-btn",
        "label": "Texto sobre Botón Acento",
        "fg": "--color-text-on-accent",
        "bg": "--color-accent",
        "min_ratio": 4.5,
    },
    {
        "id": "on-danger-btn",
        "label": "Texto sobre Botón Peligro",
        "fg": "--color-text-on-danger",
        "bg": "--color-danger",
        "min_ratio": 4.5,
    },
    {
        "id": "reserved-text-on-bg",
        "label": "Texto Institucional sobre Fondo",
        "fg": "--color-reserved-text",
        "bg": "--color-bg",
        "min_ratio": 4.5,
    },
]


class PaletteValidationError(ValueError):
    """Raised when a color palette fails validation against style.css invariants."""


@dataclass(frozen=True, slots=True)
class ColorToken:
    """Single editable 6-digit hex color token in :root."""

    name: str
    value: str
    group: str
    label: str
    description: str
    derived_dependents: list[str] = field(default_factory=list)
    selectors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "group": self.group,
            "label": self.label,
            "description": self.description,
            "derived_dependents": self.derived_dependents,
            "selectors": self.selectors,
        }


@dataclass(frozen=True, slots=True)
class TokenGroup:
    """Logical @group section of base color tokens."""

    id: str
    title: str
    description: str
    tokens: list[ColorToken]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "tokens": [t.to_dict() for t in self.tokens],
        }


@dataclass(frozen=True, slots=True)
class ContrastCheckResult:
    """WCAG 2.1 contrast evaluation for a foreground/background token pair."""

    id: str
    label: str
    fg_token: str
    bg_token: str
    fg_hex: str
    bg_hex: str
    ratio: float
    min_ratio: float
    passes_aa: bool
    passes_aaa: bool
    level: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "fg_token": self.fg_token,
            "bg_token": self.bg_token,
            "fg_hex": self.fg_hex,
            "bg_hex": self.bg_hex,
            "ratio": round(self.ratio, 2),
            "min_ratio": self.min_ratio,
            "passes_aa": self.passes_aa,
            "passes_aaa": self.passes_aaa,
            "level": self.level,
        }


@dataclass(frozen=True, slots=True)
class PaletteState:
    """Complete parsed representation of the editable color palette in style.css."""

    color_scheme: str
    groups: list[TokenGroup]
    values: dict[str, str]
    derived_tokens: dict[str, str]
    contrast_checks: list[ContrastCheckResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "color_scheme": self.color_scheme,
            "groups": [g.to_dict() for g in self.groups],
            "values": dict(self.values),
            "derived_tokens": dict(self.derived_tokens),
            "contrast_checks": [c.to_dict() for c in self.contrast_checks],
        }


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Converts a 6-digit hex color (#rrggbb) into an (R, G, B) integer tuple."""
    cleaned = hex_color.strip()
    if not HEX_COLOR_RE.fullmatch(cleaned):
        raise PaletteValidationError(
            f"Expected 6-digit hex color (#rrggbb), got {hex_color!r}"
        )
    return (
        int(cleaned[1:3], 16),
        int(cleaned[3:5], 16),
        int(cleaned[5:7], 16),
    )


def compute_relative_luminance(hex_color: str) -> float:
    """Computes WCAG 2.1 relative luminance in [0.0, 1.0] for a #rrggbb hex string."""
    r_int, g_int, b_int = _hex_to_rgb(hex_color)
    channels: list[float] = []
    for channel_255 in (r_int, g_int, b_int):
        s_rgb = channel_255 / 255.0
        if s_rgb <= 0.04045:
            channels.append(s_rgb / 12.92)
        else:
            channels.append(((s_rgb + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def compute_contrast_ratio(hex_a: str, hex_b: str) -> float:
    """Computes WCAG 2.1 contrast ratio in [1.0, 21.0] between two #rrggbb colors."""
    lum_a = compute_relative_luminance(hex_a)
    lum_b = compute_relative_luminance(hex_b)
    lighter = max(lum_a, lum_b)
    darker = min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


def infer_color_scheme(values: dict[str, str]) -> str:
    """Infers 'dark' or 'light' color-scheme from the relative luminance of --color-bg."""
    bg_hex = values.get("--color-bg", "#0b132b")
    luminance = compute_relative_luminance(bg_hex)
    return "light" if luminance > 0.35 else "dark"


def evaluate_palette_contrast(values: dict[str, str]) -> list[ContrastCheckResult]:
    """Evaluates WCAG contrast ratios across all key foreground/background token pairs."""
    results: list[ContrastCheckResult] = []
    for pair in CONTRAST_PAIRS:
        fg_token = str(pair["fg"])
        bg_token = str(pair["bg"])
        if fg_token not in values or bg_token not in values:
            continue
        fg_hex = values[fg_token]
        bg_hex = values[bg_token]
        min_ratio = float(pair["min_ratio"])
        ratio = compute_contrast_ratio(fg_hex, bg_hex)
        passes_aa = ratio >= min_ratio
        aaa_threshold = 7.0 if min_ratio >= 4.5 else 4.5
        passes_aaa = ratio >= aaa_threshold
        if passes_aaa:
            level = "AAA"
        elif passes_aa:
            level = "AA"
        else:
            level = "FAIL"
        results.append(
            ContrastCheckResult(
                id=str(pair["id"]),
                label=str(pair["label"]),
                fg_token=fg_token,
                bg_token=bg_token,
                fg_hex=fg_hex,
                bg_hex=bg_hex,
                ratio=ratio,
                min_ratio=min_ratio,
                passes_aa=passes_aa,
                passes_aaa=passes_aaa,
                level=level,
            )
        )
    return results


def _extract_selector_map(
    css_text: str,
    base_token_names: set[str],
    derived_dependents_map: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Maps each base color token to the CSS selectors in style.css that use it (directly or via derived tokens)."""
    if "@layer base" not in css_text:
        return {name: [] for name in base_token_names}

    non_token_css = re.sub(
        r"/\*.*?\*/", "", css_text[css_text.index("@layer base") :], flags=re.DOTALL
    )

    # Reverse map: any derived/shadow token -> list of base tokens it depends on
    var_to_base_tokens: dict[str, set[str]] = {
        name: {name} for name in base_token_names
    }
    for base_name, dependents in derived_dependents_map.items():
        for dep in dependents:
            var_to_base_tokens.setdefault(dep, set()).add(base_name)

    token_selectors: dict[str, list[str]] = {name: [] for name in base_token_names}
    rule_re = re.compile(r"([^{};]+)\{([^{}]*)\}")

    for match in rule_re.finditer(non_token_css):
        raw_selector = " ".join(match.group(1).strip().split())
        body = match.group(2)
        if (
            not raw_selector
            or raw_selector.startswith("@")
            or raw_selector in ("from", "to")
        ):
            continue
        # Clean pseudo-elements/states slightly so querySelectorAll in preview can match the base element too
        referenced_vars = set(VAR_REF_RE.findall(body))
        if not referenced_vars:
            continue

        affected_bases: set[str] = set()
        for ref_var in referenced_vars:
            if ref_var in var_to_base_tokens:
                affected_bases.update(var_to_base_tokens[ref_var])

        for base_token in affected_bases:
            if (
                raw_selector not in token_selectors[base_token]
                and len(token_selectors[base_token]) < 24
            ):
                token_selectors[base_token].append(raw_selector)

    return token_selectors


def parse_style_css_palette(
    style_css_path: Path | None = None,
) -> PaletteState:
    """Parses style.css and extracts the 5 base @group color sections and all 41 base #rrggbb tokens."""
    target_path = (style_css_path or DEFAULT_STYLE_CSS_PATH).expanduser().resolve()
    if not target_path.is_file():
        raise FileNotFoundError(f"style.css not found at {target_path}")

    css_text = target_path.read_text(encoding="utf-8")
    if "@layer base" not in css_text or DERIVED_GROUP_MARKER not in css_text:
        raise PaletteValidationError(
            f"style.css at {target_path} is missing expected @layer tokens or {DERIVED_GROUP_MARKER} markers."
        )

    tokens_end_idx = css_text.index("@layer base")
    tokens_section = css_text[:tokens_end_idx]
    derived_idx = tokens_section.index(DERIVED_GROUP_MARKER)
    base_colors_section = tokens_section[:derived_idx]
    remaining_tokens_section = tokens_section[derived_idx:]

    scheme_match = COLOR_SCHEME_RE.search(base_colors_section)
    color_scheme = scheme_match.group(2) if scheme_match else "dark"

    # Parse derived tokens and shadow tokens that depend on base color tokens
    derived_tokens: dict[str, str] = {}
    derived_dependents_map: dict[str, list[str]] = {}

    for var_name, var_expr in ANY_VAR_DECL_RE.findall(remaining_tokens_section):
        cleaned_expr = " ".join(var_expr.strip().split())
        referenced = VAR_REF_RE.findall(cleaned_expr)
        if var_name.startswith("--color-") or var_name.startswith("--shadow-"):
            if referenced:
                derived_tokens[var_name] = cleaned_expr
                for ref in referenced:
                    if ref.startswith("--color-"):
                        derived_dependents_map.setdefault(ref, [])
                        if var_name not in derived_dependents_map[ref]:
                            derived_dependents_map[ref].append(var_name)

    # Split base_colors_section by @group comments
    group_matches = list(GROUP_COMMENT_RE.finditer(base_colors_section))
    if not group_matches:
        raise PaletteValidationError("No @group sections found in base colors section.")

    raw_group_entries: list[tuple[str, list[tuple[str, str]]]] = []
    values: dict[str, str] = {}

    for idx, g_match in enumerate(group_matches):
        group_id = g_match.group(1).strip()
        chunk_start = g_match.end()
        chunk_end = (
            group_matches[idx + 1].start()
            if idx + 1 < len(group_matches)
            else len(base_colors_section)
        )
        chunk = base_colors_section[chunk_start:chunk_end]
        decls = TOKEN_DECL_RE.findall(chunk)
        token_pairs: list[tuple[str, str]] = []
        for token_name, raw_val in decls:
            hex_val = raw_val.strip().lower()
            if not HEX_COLOR_RE.fullmatch(hex_val):
                raise PaletteValidationError(
                    f"Base color token {token_name} in style.css has invalid 6-digit hex value: {raw_val!r}"
                )
            token_pairs.append((token_name, hex_val))
            values[token_name] = hex_val
        raw_group_entries.append((group_id, token_pairs))

    selector_map = _extract_selector_map(
        css_text, set(values.keys()), derived_dependents_map
    )

    groups: list[TokenGroup] = []
    for group_id, token_pairs in raw_group_entries:
        group_meta = GROUP_LABELS.get(
            group_id,
            {"title": group_id, "description": ""},
        )
        group_tokens: list[ColorToken] = []
        for token_name, hex_val in token_pairs:
            t_meta = TOKEN_METADATA.get(
                token_name,
                {
                    "label": token_name.removeprefix("--color-")
                    .replace("-", " ")
                    .title(),
                    "description": "",
                },
            )
            group_tokens.append(
                ColorToken(
                    name=token_name,
                    value=hex_val,
                    group=group_id,
                    label=t_meta["label"],
                    description=t_meta["description"],
                    derived_dependents=derived_dependents_map.get(token_name, []),
                    selectors=selector_map.get(token_name, []),
                )
            )
        groups.append(
            TokenGroup(
                id=group_id,
                title=group_meta["title"],
                description=group_meta["description"],
                tokens=group_tokens,
            )
        )

    contrast_checks = evaluate_palette_contrast(values)
    return PaletteState(
        color_scheme=color_scheme,
        groups=groups,
        values=values,
        derived_tokens=derived_tokens,
        contrast_checks=contrast_checks,
    )


def validate_palette_values(
    candidate_values: dict[str, Any],
    expected_token_names: set[str],
    color_scheme: str | None = None,
) -> tuple[dict[str, str], str]:
    """Validates a candidate dictionary of token values and returns normalized lowercase #rrggbb values and color_scheme."""
    if not isinstance(candidate_values, dict):
        raise PaletteValidationError("Palette values must be a mapping of token names to #rrggbb strings.")

    unknown = sorted(set(candidate_values.keys()) - expected_token_names)
    if unknown:
        raise PaletteValidationError(
            f"Unknown color tokens not present in style.css base palette: {', '.join(unknown)}"
        )

    missing = sorted(expected_token_names - set(candidate_values.keys()))
    if missing:
        raise PaletteValidationError(
            f"Missing required base color tokens: {', '.join(missing)}"
        )

    normalized: dict[str, str] = {}
    for name in sorted(expected_token_names):
        raw_val = candidate_values.get(name)
        if not isinstance(raw_val, str):
            raise PaletteValidationError(
                f"Token {name} value must be a string, got {type(raw_val).__name__}"
            )
        cleaned = raw_val.strip().lower()
        if not HEX_COLOR_RE.fullmatch(cleaned):
            raise PaletteValidationError(
                f"Token {name} must be a 6-digit hex color (#rrggbb), got {raw_val!r}"
            )
        normalized[name] = cleaned

    if color_scheme is None or color_scheme == "auto":
        resolved_scheme = infer_color_scheme(normalized)
    elif color_scheme in ("dark", "light"):
        resolved_scheme = color_scheme
    else:
        raise PaletteValidationError(
            f"Invalid color_scheme {color_scheme!r}. Expected 'dark', 'light', or 'auto'."
        )

    return normalized, resolved_scheme


def apply_palette_to_css_text(
    css_text: str,
    values: dict[str, str],
    color_scheme: str | None = None,
) -> str:
    """Surgically updates only the 41 base color tokens and color-scheme inside @layer tokens of style.css."""
    if "@layer base" not in css_text or DERIVED_GROUP_MARKER not in css_text:
        raise PaletteValidationError(
            "Target CSS text is missing @layer base or Derived Tints marker."
        )

    tokens_end_idx = css_text.index("@layer base")
    tokens_section = css_text[:tokens_end_idx]
    derived_idx = tokens_section.index(DERIVED_GROUP_MARKER)
    base_colors_section = tokens_section[:derived_idx]
    rest_of_css = css_text[derived_idx:]

    existing_decls = dict(TOKEN_DECL_RE.findall(base_colors_section))
    expected_names = set(existing_decls.keys())

    normalized_values, resolved_scheme = validate_palette_values(
        values,
        expected_names,
        color_scheme=color_scheme,
    )

    def _replace_token(match: re.Match[str]) -> str:
        t_name = match.group(1)
        if t_name in normalized_values:
            return f"{t_name}: {normalized_values[t_name]};"
        return match.group(0)

    updated_base = TOKEN_DECL_RE.sub(_replace_token, base_colors_section)
    updated_base = COLOR_SCHEME_RE.sub(
        rf"\g<1>{resolved_scheme}\g<3>",
        updated_base,
        count=1,
    )

    updated_css = updated_base + rest_of_css

    # Post-update invariant check matching tests/unit/test_no_inline_css.py
    if updated_css.count("{") != updated_css.count("}"):
        raise PaletteValidationError("Braces became unbalanced after applying palette.")
    if "@layer tokens, base, layout, components, pages, utilities;" not in updated_css:
        raise PaletteValidationError("Cascade layer order declaration missing.")

    return updated_css


def save_palette_to_style_css(
    values: dict[str, Any],
    style_css_path: Path | None = None,
    color_scheme: str | None = None,
    backup_dir: Path | None = None,
) -> PaletteState:
    """Validates and atomically writes the updated color palette to style.css, creating a backup snapshot first."""
    target_path = (style_css_path or DEFAULT_STYLE_CSS_PATH).expanduser().resolve()
    if not target_path.is_file():
        raise FileNotFoundError(f"style.css not found at {target_path}")

    current_state = parse_style_css_palette(target_path)
    original_css = target_path.read_text(encoding="utf-8")

    updated_css = apply_palette_to_css_text(
        original_css,
        values,
        color_scheme=color_scheme,
    )

    if backup_dir is not None:
        resolved_backup_dir = Path(backup_dir).expanduser().resolve()
        resolved_backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_file = resolved_backup_dir / f"backup_{timestamp}.yaml"
        backup_payload = {
            "name": f"Backup ({timestamp} UTC)",
            "description": "Respaldo automático previo a guardar cambios en style.css",
            "color_scheme": current_state.color_scheme,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "tokens": current_state.values,
        }
        with open(backup_file, "w", encoding="utf-8") as f:
            yaml.safe_dump(backup_payload, f, sort_keys=False, allow_unicode=True)
        logger.info("Saved automatic palette backup to %s", backup_file)

    temp_css_path = target_path.with_suffix(".css.tmp")
    temp_css_path.write_text(updated_css, encoding="utf-8")
    temp_css_path.replace(target_path)
    logger.info("Atomically updated palette in %s", target_path)

    return parse_style_css_palette(target_path)
