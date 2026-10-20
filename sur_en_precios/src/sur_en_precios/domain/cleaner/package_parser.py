"""Package parsing and standardization utilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from sur_en_precios.domain.cleaner.text_utils import normalize_nfc

UNIT_CANONICAL_MAP = {
    "cc": "ml",
    "cm3": "ml",
    "ml": "ml",
    "lt": "L",
    "l": "L",
    "litro": "L",
    "litros": "L",
    "gr": "g",
    "g": "g",
    "grs": "g",
    "gramos": "g",
    "kg": "kg",
    "k": "kg",
    "kgs": "kg",
    "kilos": "kg",
    "un": "u",
    "u": "u",
    "und": "u",
    "unid": "u",
    "unidades": "u",
    "mt": "m",
    "m": "m",
    "mts": "m",
    "metros": "m",
}


@dataclass(frozen=True)
class PackageInfo:
    """Structured representation of an article's package."""

    raw: str
    amount: Optional[float]
    unit: Optional[str]
    display: Optional[str]

    @property
    def is_valid(self) -> bool:
        return self.amount is not None and self.unit is not None


def parse_package(pkg_str: str | None) -> PackageInfo:
    """Parse a package string into amount, standardized unit, and clean display format.

    Examples:
        '500.0 ml' -> PackageInfo(amount=500.0, unit='ml', display='500 ml')
        '1.5 lt'   -> PackageInfo(amount=1.5, unit='L', display='1.5 L')
        '75.0 gr'  -> PackageInfo(amount=75.0, unit='g', display='75 g')
    """
    if not pkg_str:
        return PackageInfo(raw="", amount=None, unit=None, display=None)

    raw = normalize_nfc(pkg_str).strip()
    match = re.match(r"^([\d\.]+)\s*([a-zA-Z]+)$", raw)
    if not match:
        return PackageInfo(raw=raw, amount=None, unit=None, display=raw or None)

    try:
        amount = float(match.group(1))
    except ValueError:
        return PackageInfo(raw=raw, amount=None, unit=None, display=raw)

    raw_unit = match.group(2).lower()
    unit = UNIT_CANONICAL_MAP.get(raw_unit, raw_unit)

    # Format amount cleanly (e.g. 500 instead of 500.0, 1.5 instead of 1.50)
    amt_str = f"{int(amount)}" if amount.is_integer() else f"{amount:g}"
    display = f"{amt_str} {unit}"

    return PackageInfo(raw=raw, amount=amount, unit=unit, display=display)


def build_package_patterns(amount: float | None, unit: str | None) -> List[re.Pattern]:
    """Build regex patterns that match the package within a raw description text.

    Matches patterns like '500 ml', '500ml', '500 cc', '1.5 lt', '1,5lt', 'x 500 g', etc.
    """
    if amount is None or not unit:
        return []

    val_float = amount
    val_int = int(val_float) if val_float.is_integer() else None

    val_strs = [str(val_float)]
    if val_int is not None:
        val_strs.append(str(val_int))
    else:
        val_strs.append(str(val_float).replace(".", ","))

    # Unit variations in descriptions
    u_lower = unit.lower()
    unit_variants = [u_lower]
    if u_lower in ("ml", "cc"):
        unit_variants.extend(["ml", "cc", "cm3", "ml.", "cc."])
    elif u_lower in ("l", "lt"):
        unit_variants.extend(["lt", "l", "lts", "lt.", "l.", "litro", "litros"])
    elif u_lower in ("g", "gr"):
        unit_variants.extend(["gr", "g", "grs", "gr.", "g.", "gramos"])
    elif u_lower == "kg":
        unit_variants.extend(["kg", "k", "kgs", "kg.", "kilos", "kilo"])
    elif u_lower in ("u", "un"):
        unit_variants.extend(
            ["un", "u", "und", "unid", "un.", "u.", "unidades", "unidad"]
        )
    elif u_lower in ("m", "mt"):
        unit_variants.extend(["mt", "m", "mts", "mt.", "m.", "metros", "metro"])

    patterns: List[re.Pattern] = []
    for vs in val_strs:
        vs_esc = re.escape(vs)
        for uv in set(unit_variants):
            uv_esc = re.escape(uv)
            # e.g. 500 ml, 500ml, x500 ml, x 500ml
            pat = rf"(?:\bx\s*)?{vs_esc}\s*{uv_esc}\b"
            patterns.append(re.compile(pat, re.IGNORECASE))

    return patterns
