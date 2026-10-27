"""File-system adapter that loads benchmark baskets downloaded from PythonAnywhere.

Baskets are the YAML files produced by the public web portal's "Exportar"
action (``BasketYamlService.export_to_yaml``). Drop them into the configured
baskets directory (default ``<workdir>/data/baskets``).

Basket identity: the basket ``uuid`` from the YAML is used as the stable key
when present (so renaming the file does not break the time series); otherwise
the slugified file name is used.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

import yaml

from sur_en_precios.domain.evolution import EvolutionBasketItem, EvolutionBasketSpec
from sur_en_precios.domain.services import BasketYamlService, YamlValidationError

logger = logging.getLogger(__name__)

__all__ = ["BasketLoadResult", "load_basket_file", "load_baskets_from_directory"]

BASKET_SUFFIXES = (".yaml", ".yml")
_MAX_KEY_LEN = 64


@dataclass(frozen=True)
class BasketLoadResult:
    """Outcome of loading one basket file (either a spec or an error)."""

    path: Path
    spec: Optional[EvolutionBasketSpec] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.spec is not None


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    return slug[:_MAX_KEY_LEN] or "basket"


def _extract_uuid(raw: Any) -> Optional[str]:
    if not isinstance(raw, dict):
        return None
    basket = raw.get("basket")
    if not isinstance(basket, dict):
        return None
    value = str(basket.get("uuid") or "").strip()
    return value[:_MAX_KEY_LEN] or None


def load_basket_file(path: Path) -> EvolutionBasketSpec:
    """Parses and validates a single basket YAML file.

    Raises:
        YamlValidationError: invalid YAML syntax or basket schema.
        ValueError: basket has no selected items.
        OSError / UnicodeDecodeError: file cannot be read.
    """
    resolved = Path(path).expanduser().resolve()
    content = resolved.read_text(encoding="utf-8")
    parsed = BasketYamlService.import_from_yaml(content)
    for warning in parsed.warnings:
        logger.warning(
            "Basket file warning", extra={"file": resolved.name, "detail": warning}
        )

    items = tuple(
        EvolutionBasketItem(
            ean=it.ean,
            quantity=it.quantity,
            numerator=it.numerator,
            denominator=it.denominator,
            name=it.name,
        )
        for it in parsed.items
        if it.selected
    )
    if not items:
        raise ValueError("La canasta no tiene artículos seleccionados.")

    key = _extract_uuid(yaml.safe_load(content)) or _slugify(resolved.stem)
    return EvolutionBasketSpec(
        key=key,
        name=parsed.name,
        items=items,
        source_file=resolved.name,
    )


def load_baskets_from_directory(directory: Path) -> List[BasketLoadResult]:
    """Loads every ``*.yaml`` / ``*.yml`` basket in ``directory`` (sorted by name).

    A broken file does not prevent the others from loading: its error is
    reported in the corresponding :class:`BasketLoadResult`. Two files that
    resolve to the same basket key are reported as an error for the second.
    """
    resolved = Path(directory).expanduser().resolve()
    if not resolved.is_dir():
        logger.warning("Baskets directory not found", extra={"path": str(resolved)})
        return []

    files = sorted(
        p
        for p in resolved.iterdir()
        if p.is_file() and p.suffix.lower() in BASKET_SUFFIXES
    )
    results: List[BasketLoadResult] = []
    seen_keys: dict[str, str] = {}
    for file_path in files:
        try:
            spec = load_basket_file(file_path)
        except (YamlValidationError, ValueError, OSError, UnicodeDecodeError) as exc:
            logger.error(
                "Invalid basket file",
                extra={"file": file_path.name, "error": str(exc)},
            )
            results.append(BasketLoadResult(path=file_path, error=str(exc)))
            continue

        if spec.key in seen_keys:
            msg = (
                f"Canasta duplicada: '{file_path.name}' tiene la misma clave "
                f"({spec.key}) que '{seen_keys[spec.key]}'."
            )
            logger.error("Duplicated basket key", extra={"file": file_path.name})
            results.append(BasketLoadResult(path=file_path, error=msg))
            continue

        seen_keys[spec.key] = file_path.name
        results.append(BasketLoadResult(path=file_path, spec=spec))
    return results
