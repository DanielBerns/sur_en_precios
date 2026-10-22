import json
import logging
import math
import re
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import bcrypt
import yaml

from sur_en_precios.domain.models import (
    BasketOptimizationResult,
    ItemBestPrice,
    ItemSubstitution,
    StoreBasketTotal,
    StoreItemPrice,
)
from sur_en_precios.domain.models_public import (
    ArticleCard,
    ArticleDescription,
    ArticleMetric,
    ArticleNumber,
    City,
    Price,
    Store,
    Timestamp,
)
from sur_en_precios.domain.models_user import Basket, BasketItem

logger = logging.getLogger("sur_en_precios.services")


def calculate_unit_price(
    price: int, pkg_amount: Optional[float], pkg_unit: Optional[str]
) -> Tuple[Optional[float], Optional[str]]:
    """Calculates normalized unit price (ARS per kg, liter or unit) and returns (unit_price, base_unit)."""
    if not pkg_amount or pkg_amount <= 0 or not pkg_unit:
        return None, None

    unit = str(pkg_unit).lower().strip()
    if unit in ("ml", "cc"):
        base_amt = pkg_amount / 1000.0
        return round(price / base_amt, 2), "L"
    elif unit in ("g", "gr"):
        base_amt = pkg_amount / 1000.0
        return round(price / base_amt, 2), "kg"
    elif unit in ("l", "lt"):
        return round(price / pkg_amount, 2), "L"
    elif unit in ("kg",):
        return round(price / pkg_amount, 2), "kg"
    elif unit in ("u", "un"):
        return round(price / pkg_amount, 2), "u"
    return None, None


class PriceMetricsCalculator:
    """Calculates statistical price metrics including Reference Price (Geometric Mean)."""

    @staticmethod
    def calculate_reference_price(prices: List[int]) -> Optional[int]:
        """Calculates the Reference Price (Geometric Mean) rounded to integer Pesos Argentinos."""
        if not prices:
            return None
        valid_prices = [p for p in prices if p > 0]
        if not valid_prices:
            return None

        # Geometric Mean: exp( sum(ln(P_i)) / n )
        log_sum = sum(math.log(p) for p in valid_prices)
        geo_mean = math.exp(log_sum / len(valid_prices))
        return round(geo_mean)

    @classmethod
    def calculate_metrics(
        cls,
        metric_date: date,
        ean: str,
        city: str,
        prices: List[int],
    ) -> ArticleMetric:
        """Computes daily price metrics for a product in a city."""
        timestamp = Timestamp(value=metric_date)
        article_number = ArticleNumber(ean=ean)
        city_entity = City(name=city)

        if not prices:
            return ArticleMetric(
                timestamp=timestamp,
                article_number=article_number,
                city=city_entity,
            )

        sorted_prices = sorted(prices)
        min_p = sorted_prices[0]
        max_p = sorted_prices[-1]
        ref_p = cls.calculate_reference_price(sorted_prices)

        # Price dispersion: stddev / mean
        dispersion = None
        if len(sorted_prices) > 1:
            mean_val = statistics.mean(sorted_prices)
            if mean_val > 0:
                dispersion = round(statistics.stdev(sorted_prices) / mean_val, 4)

        return ArticleMetric(
            timestamp=timestamp,
            article_number=article_number,
            city=city_entity,
            min_price=min_p,
            max_price=max_p,
            reference_price=ref_p,
            price_dispersion=dispersion,
        )


class BasketOptimizerService:
    """Domain service for optimizing multi-product shopping baskets across stores."""

    @staticmethod
    def optimize_basket(
        city: str,
        calc_date: date,
        requested_items: List[BasketItem],
        products_map: Dict[str, Any],
        stores: List[Store],
        prices: List[Price],
        reference_prices: Dict[str, int],
        substitute_candidates_map: Optional[Dict[str, List[Any]]] = None,
        substitute_prices: Optional[List[Price]] = None,
    ) -> BasketOptimizationResult:
        """Optimizes a shopping basket across city stores for a target date."""
        # Filter active (selected) items; None defaults to True
        active_items = [
            item
            for item in requested_items
            if getattr(item, "selected", True) is not False
        ]
        total_requested_count = len(active_items)

        # Combine prices with substitute_prices if present
        all_prices_list = list(prices)
        if substitute_prices:
            all_prices_list.extend(substitute_prices)

        # Index prices: (store_identifier, ean) -> price
        price_lookup: Dict[Tuple[str, str], int] = {}
        unit_price_lookup: Dict[
            Tuple[str, str], Tuple[Optional[float], Optional[str]]
        ] = {}

        # Track city-wide min and max prices per product
        product_min_price: Dict[str, int] = {}
        product_max_price: Dict[str, int] = {}

        for p in all_prices_list:
            p_ean = str(getattr(p, "ean", "") or "")
            amt_val = getattr(p, "price", None)
            if amt_val is None:
                amt_val = getattr(p, "amount", 0)
            amt: int = int(amt_val) if amt_val is not None else 0

            # Determine unit price and unit
            u_price = getattr(p, "unit_price", None)
            base_unit: Optional[str] = None
            prod = products_map.get(p_ean)
            if prod:
                calc_u_price, calc_base_unit = calculate_unit_price(
                    amt,
                    getattr(prod, "package_amount", None),
                    getattr(prod, "package_unit", None),
                )
                if u_price is None:
                    u_price = calc_u_price
                base_unit = calc_base_unit

            s_id = getattr(p, "store_id", None)
            if s_id is not None:
                price_lookup[(str(s_id), p_ean)] = amt
                unit_price_lookup[(str(s_id), p_ean)] = (u_price, base_unit)
            s_code = getattr(p, "store_code", None)
            if s_code:
                price_lookup[(str(s_code), p_ean)] = amt
                unit_price_lookup[(str(s_code), p_ean)] = (u_price, base_unit)
            if hasattr(p, "store") and p.store:
                if getattr(p.store, "code", None):
                    price_lookup[(str(p.store.code), p_ean)] = amt
                    unit_price_lookup[(str(p.store.code), p_ean)] = (u_price, base_unit)
                if getattr(p.store, "id", None) is not None:
                    price_lookup[(str(p.store.id), p_ean)] = amt
                    unit_price_lookup[(str(p.store.id), p_ean)] = (u_price, base_unit)

            if p_ean not in product_min_price or amt < product_min_price[p_ean]:
                product_min_price[p_ean] = amt
            if p_ean not in product_max_price or amt > product_max_price[p_ean]:
                product_max_price[p_ean] = amt

        complete_stores: List[StoreBasketTotal] = []
        partial_stores: List[StoreBasketTotal] = []

        def get_store_price(st: Any, ean: str) -> Optional[int]:
            st_code = getattr(st, "code", None)
            if st_code and (str(st_code), ean) in price_lookup:
                return price_lookup[(str(st_code), ean)]
            st_id = getattr(st, "id", None)
            if st_id is not None and (str(st_id), ean) in price_lookup:
                return price_lookup[(str(st_id), ean)]
            return None

        def get_store_unit_price(
            st: Any, ean: str
        ) -> Tuple[Optional[float], Optional[str]]:
            st_code = getattr(st, "code", None)
            if st_code and (str(st_code), ean) in unit_price_lookup:
                return unit_price_lookup[(str(st_code), ean)]
            st_id = getattr(st, "id", None)
            if st_id is not None and (str(st_id), ean) in unit_price_lookup:
                return unit_price_lookup[(str(st_id), ean)]
            return None, None

        # Evaluate each store
        for store in stores:
            store_item_prices: Dict[str, StoreItemPrice] = {}
            total_basket_price = 0
            matched_count = 0

            for item in active_items:
                ean = item.ean
                item_price = get_store_price(store, ean)

                if item_price is not None:
                    matched_count += 1
                    num = getattr(item, "numerator", 1) or 1
                    den = getattr(item, "denominator", 1) or 1
                    if den == 0:
                        logger.error(
                            "Denominator for item %s is 0, defaulting to 1", ean
                        )
                        den = 1
                    effective_item_price = round(item_price * item.quantity * num / den)
                    total_basket_price += effective_item_price

                    is_lowest = item_price == product_min_price.get(ean)
                    is_highest = item_price == product_max_price.get(ean)
                    ref_p = reference_prices.get(ean)
                    is_above_ref = (item_price > ref_p) if ref_p is not None else False
                    u_price, base_unit = get_store_unit_price(store, ean)

                    store_item_prices[ean] = StoreItemPrice(
                        ean=ean,
                        price=item_price,
                        is_lowest=is_lowest,
                        is_highest=is_highest,
                        is_above_reference=is_above_ref,
                        unit_price=u_price,
                        unit=base_unit,
                    )

            if matched_count > 0:
                is_complete = (matched_count == total_requested_count) and (
                    total_requested_count > 0
                )
                basket_total = StoreBasketTotal(
                    store=store,
                    total_price=total_basket_price,
                    matched_items_count=matched_count,
                    requested_items_count=total_requested_count,
                    is_complete=is_complete,
                    item_prices=store_item_prices,
                )

                if is_complete:
                    complete_stores.append(basket_total)
                else:
                    partial_stores.append(basket_total)

        # Sort complete stores by total price ascending
        complete_stores.sort(key=lambda s: s.total_price)
        # Sort partial stores by matched items descending, then total price ascending
        partial_stores.sort(key=lambda s: (-s.matched_items_count, s.total_price))

        best_single = complete_stores[0] if complete_stores else None

        # Compute item-by-item optimal (cheapest store per active item)
        item_by_item_optimal: List[ItemBestPrice] = []
        suggested_substitutions: List[ItemSubstitution] = []
        multi_store_total: int = 0

        for item in active_items:
            ean = item.ean
            product = products_map.get(ean)
            if product is None:
                product = ArticleCard(
                    article_number=ArticleNumber(ean=ean),
                    description=ArticleDescription(content=f"Producto {ean}"),
                )
            cheapest_store: Optional[Store] = None
            cheapest_price: Optional[int] = None
            cheapest_unit_price: Optional[float] = None
            cheapest_base_unit: Optional[str] = None

            for store in stores:
                price = get_store_price(store, ean)
                if price is not None:
                    if cheapest_price is None or price < cheapest_price:
                        cheapest_price = price
                        cheapest_store = store
                        u_p, u_u = get_store_unit_price(store, ean)
                        cheapest_unit_price = u_p
                        cheapest_base_unit = u_u

            # Check for candidate substitutions if available
            best_sub: Optional[ItemSubstitution] = None
            if (
                substitute_candidates_map
                and ean in substitute_candidates_map
                and cheapest_price is not None
            ):
                candidates = substitute_candidates_map[ean]
                for cand in candidates:
                    cand_ean = getattr(cand, "ean", str(cand))
                    cand_cheapest_store: Optional[Store] = None
                    cand_cheapest_price: Optional[int] = None
                    cand_unit_price: Optional[float] = None
                    cand_base_unit: Optional[str] = None

                    for store in stores:
                        cp = get_store_price(store, cand_ean)
                        if cp is not None:
                            if cand_cheapest_price is None or cp < cand_cheapest_price:
                                cand_cheapest_price = cp
                                cand_cheapest_store = store
                                cu_p, cu_u = get_store_unit_price(store, cand_ean)
                                cand_unit_price = cu_p
                                cand_base_unit = cu_u

                    if cand_cheapest_store and cand_cheapest_price is not None:
                        # Recommend if cheaper
                        if cand_cheapest_price < cheapest_price:
                            savings = cheapest_price - cand_cheapest_price
                            savings_pct = round((savings / cheapest_price) * 100, 1)
                            if best_sub is None or savings > best_sub.savings_amount:
                                best_sub = ItemSubstitution(
                                    original_ean=ean,
                                    product=cand,
                                    cheapest_store=cand_cheapest_store,
                                    price=cand_cheapest_price,
                                    unit_price=cand_unit_price,
                                    unit=cand_base_unit,
                                    savings_amount=savings,
                                    savings_percent=savings_pct,
                                )

            if best_sub:
                suggested_substitutions.append(best_sub)

            if cheapest_store is not None and cheapest_price is not None:
                min_p = product_min_price.get(ean)
                max_p = product_max_price.get(ean)
                ref_p = reference_prices.get(ean)
                dispersion = None
                if min_p is not None and max_p is not None and min_p > 0:
                    dispersion = round(((max_p - min_p) / min_p) * 100, 1)

                num = getattr(item, "numerator", 1) or 1
                den = getattr(item, "denominator", 1) or 1
                if den == 0:
                    den = 1
                effective_price = round(cheapest_price * item.quantity * num / den)
                multi_store_total += effective_price

                item_by_item_optimal.append(
                    ItemBestPrice(
                        product=product,
                        cheapest_store=cheapest_store,
                        price=cheapest_price,
                        unit_price=cheapest_unit_price,
                        unit=cheapest_base_unit,
                        substitution=best_sub,
                        min_price=min_p,
                        reference_price=ref_p,
                        max_price=max_p,
                        price_dispersion=dispersion,
                        quantity=item.quantity,
                        numerator=num,
                        denominator=den,
                    )
                )

        return BasketOptimizationResult(
            city=city,
            calculation_date=calc_date,
            requested_items=requested_items,
            best_single_store=best_single,
            item_by_item_optimal=item_by_item_optimal,
            complete_stores=complete_stores,
            partial_stores=partial_stores,
            reference_prices=reference_prices,
            suggested_substitutions=suggested_substitutions,
            multi_store_total_price=multi_store_total,
        )


def levenshtein_distance(s1: str, s2: str) -> int:
    """Computes the Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)

    if len(s1) > len(s2):
        s1, s2 = s2, s1

    previous_row = list(range(len(s1) + 1))
    for i, c2 in enumerate(s2):
        current_row = [i + 1] * (len(s1) + 1)
        for j, c1 in enumerate(s1):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row[j + 1] = min(insertions, deletions, substitutions)
        previous_row = current_row

    return previous_row[-1]


def fuzzy_similarity_ratio(query: str, target: str) -> float:
    """Computes a normalized similarity score in [0.0, 1.0] between query and target."""
    q = query.strip().lower()
    t = target.strip().lower()
    if not q or not t:
        return 0.0
    if q == t:
        return 1.0
    if q in t:
        return max(0.7, len(q) / len(t))

    dist = levenshtein_distance(q, t)
    max_len = max(len(q), len(t))
    if max_len == 0:
        return 1.0
    return max(0.0, 1.0 - (dist / max_len))


class YamlValidationError(Exception):
    """Raised when uploaded or imported YAML fails syntax or business validation."""

    pass


@dataclass
class ParsedBasketItem:
    ean: str
    quantity: int = 1
    selected: bool = True
    numerator: int = 1
    denominator: int = 1
    name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None


@dataclass
class ParsedBasket:
    name: str
    is_public: bool
    items: List[ParsedBasketItem]
    warnings: List[str]


class BasketYamlService:
    """Service for exporting and importing baskets in YAML format with extensive error checking."""

    @staticmethod
    def export_to_yaml(
        basket: Basket,
        articles_metadata: Optional[Dict[str, ArticleCard]] = None,
    ) -> str:
        """Serializes a Basket entity to standard YAML."""
        articles_metadata = articles_metadata or {}
        items_payload = []
        for item in basket.items:
            art = articles_metadata.get(item.ean)
            item_dict: Dict[str, Any] = {
                "ean": str(item.ean),
                "quantity": int(getattr(item, "quantity", 1)),
                "selected": bool(getattr(item, "selected", True)),
                "numerator": int(getattr(item, "numerator", 1)),
                "denominator": int(getattr(item, "denominator", 1)),
            }
            if art:
                if hasattr(art, "name") and art.name:
                    item_dict["name"] = art.name
                if hasattr(art, "brand_name") and art.brand_name:
                    item_dict["brand"] = art.brand_name
                if hasattr(art, "category_name") and art.category_name:
                    item_dict["category"] = art.category_name
            items_payload.append(item_dict)

        payload = {
            "version": "1.0",
            "basket": {
                "name": str(basket.name),
                "uuid": str(basket.uuid) if getattr(basket, "uuid", None) else "",
                "is_public": bool(getattr(basket, "is_public", False)),
                "created_at": (
                    basket.created_at.isoformat()
                    if getattr(basket, "created_at", None)
                    else ""
                ),
                "items": items_payload,
            },
        }
        header = "# Sur en Precios — Canasta de Compras\n"
        return header + yaml.dump(payload, allow_unicode=True, sort_keys=False)

    @classmethod
    def import_from_yaml(
        cls,
        yaml_content: str,
        catalog_eans: Optional[set[str]] = None,
    ) -> ParsedBasket:
        """
        Parses and validates an uploaded YAML basket string.
        Fails fast with detailed error messages on invalid syntax or schema violations.
        """
        warnings: List[str] = []
        if not yaml_content or not yaml_content.strip():
            logger.error("YAML import error: content is empty")
            raise YamlValidationError("El archivo YAML está vacío.")

        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as exc:
            logger.error("YAML syntax error: %s", exc)
            problem = getattr(exc, "problem", str(exc))
            mark = getattr(exc, "problem_mark", None)
            if mark:
                raise YamlValidationError(
                    f"Error de sintaxis YAML en línea {mark.line + 1}, columna {mark.column + 1}: {problem}"
                )
            raise YamlValidationError(f"Error de sintaxis YAML: {problem}")

        if not isinstance(data, dict):
            logger.error("YAML structure error: root is not a dictionary")
            raise YamlValidationError(
                "Estructura inválida: El archivo YAML debe ser un objeto/mapeo."
            )

        basket_data = data.get("basket")
        if not basket_data or not isinstance(basket_data, dict):
            logger.error("YAML structure error: missing 'basket' mapping")
            raise YamlValidationError(
                "Estructura inválida: Falta la sección principal 'basket'."
            )

        name = str(basket_data.get("name", "")).strip()
        if not name:
            logger.error("YAML validation error: basket name is empty")
            raise YamlValidationError(
                "El nombre de la canasta ('name') es obligatorio y no puede estar vacío."
            )
        if len(name) > 120:
            logger.error("YAML validation error: basket name exceeds 120 chars")
            raise YamlValidationError(
                "El nombre de la canasta no puede exceder los 120 caracteres."
            )

        is_public = bool(basket_data.get("is_public", False))

        raw_items = basket_data.get("items")
        if not raw_items or not isinstance(raw_items, list):
            logger.error("YAML validation error: 'items' missing or empty")
            raise YamlValidationError(
                "La canasta debe contener una lista no vacía de artículos en 'items'."
            )

        parsed_items: List[ParsedBasketItem] = []
        seen_eans: set[str] = set()

        for idx, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                logger.error("YAML item %d is not a dict", idx)
                raise YamlValidationError(
                    f"El artículo #{idx} no tiene un formato válido (debe ser un objeto)."
                )

            ean_raw = item.get("ean")
            if ean_raw is None:
                logger.error("YAML item %d missing ean", idx)
                raise YamlValidationError(
                    f"El artículo #{idx} no tiene el código 'ean'."
                )

            ean = str(ean_raw).strip()
            if not ean.isdigit() or not (6 <= len(ean) <= 14):
                logger.error("YAML item %d invalid ean: %s", idx, ean)
                raise YamlValidationError(
                    f"El artículo #{idx} tiene un código EAN inválido ('{ean}'). Debe contener entre 6 y 14 dígitos."
                )

            if ean in seen_eans:
                warnings.append(
                    f"El código EAN {ean} apareció duplicado en el archivo. Se consolidó su cantidad."
                )
                existing_item = next(it for it in parsed_items if it.ean == ean)
                qty_raw = item.get("quantity", 1)
                try:
                    qty = int(qty_raw)
                    if qty > 0:
                        existing_item.quantity += qty
                except (ValueError, TypeError):
                    pass
                continue

            seen_eans.add(ean)

            try:
                quantity = int(item.get("quantity", 1))
                if quantity <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                logger.error("YAML item %d invalid quantity", idx)
                raise YamlValidationError(
                    f"El artículo #{idx} (EAN {ean}) tiene una cantidad inválida. Debe ser un entero mayor o igual a 1."
                )

            selected = bool(item.get("selected", True))

            try:
                numerator = int(item.get("numerator", 1))
                if numerator <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                logger.error("YAML item %d invalid numerator", idx)
                raise YamlValidationError(
                    f"El artículo #{idx} (EAN {ean}) tiene un 'numerator' inválido. Debe ser un entero mayor o igual a 1."
                )

            try:
                denominator = int(item.get("denominator", 1))
                if denominator <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                logger.error("YAML item %d invalid denominator (zero or negative)", idx)
                raise YamlValidationError(
                    f"El artículo #{idx} (EAN {ean}) tiene un 'denominator' inválido. No puede ser cero ni negativo."
                )

            item_name = str(item.get("name", "")).strip() or None
            item_brand = str(item.get("brand", "")).strip() or None
            item_cat = str(item.get("category", "")).strip() or None

            if catalog_eans is not None and ean not in catalog_eans:
                warnings.append(
                    f"El artículo con EAN {ean} ({item_name or 'Sin descripción'}) no se encuentra en el catálogo regional actual."
                )

            parsed_items.append(
                ParsedBasketItem(
                    ean=ean,
                    quantity=quantity,
                    selected=selected,
                    numerator=numerator,
                    denominator=denominator,
                    name=item_name,
                    brand=item_brand,
                    category=item_cat,
                )
            )

        if not parsed_items:
            raise YamlValidationError(
                "No se encontraron artículos válidos para importar en la canasta."
            )

        return ParsedBasket(
            name=name,
            is_public=is_public,
            items=parsed_items,
            warnings=warnings,
        )


def _format_store_dict(st: Any) -> Optional[Dict[str, Any]]:
    """Helper to convert Store or PointOfSale instance to a standardized dictionary."""
    if not st:
        return None
    code = getattr(st, "code", None) or getattr(st, "id", "")
    chain = getattr(st, "chain_name", None) or getattr(st, "brand_name", "") or ""
    store = getattr(st, "store_name", None) or getattr(st, "branch_name", "") or ""
    city = getattr(st, "city", None)
    if hasattr(city, "name"):
        city = city.name
    elif not city and hasattr(st, "place") and st.place and hasattr(st.place, "city"):
        city = getattr(st.place.city, "name", str(st.place.city))
    return {
        "store_code": str(code),
        "chain_name": str(chain),
        "branch_name": str(store),
        "address": getattr(st, "address", None),
        "city": str(city) if city else None,
    }


class BasketPriceReportService:
    """Service for generating comprehensive price reports for baskets in JSON format."""

    @classmethod
    def build_report_dict(
        cls,
        result: BasketOptimizationResult,
        basket: Optional[Basket] = None,
        unpriced_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Builds a structured dictionary containing full price optimization and basket metrics."""
        unpriced_items = unpriced_items or []

        # Determine basket info
        basket_info: Dict[str, Any] = {
            "id": getattr(basket, "id", None),
            "uuid": getattr(basket, "uuid", None),
            "name": getattr(basket, "name", "Canasta de Compras"),
            "is_public": bool(getattr(basket, "is_public", False)),
        }

        # Summary calculation
        best_single = None
        if result.best_single_store:
            st = result.best_single_store.store
            st_dict = _format_store_dict(st) or {}
            best_single = {
                **st_dict,
                "total_price": result.best_single_store.total_price,
                "matched_items_count": result.best_single_store.matched_items_count,
                "requested_items_count": result.best_single_store.requested_items_count,
                "is_complete": result.best_single_store.is_complete,
            }

        savings = 0
        savings_pct = 0.0
        if (
            result.best_single_store
            and result.best_single_store.total_price > result.multi_store_total_price
        ):
            savings = (
                result.best_single_store.total_price - result.multi_store_total_price
            )
            if result.best_single_store.total_price > 0:
                savings_pct = round(
                    (savings / result.best_single_store.total_price) * 100, 2
                )

        summary = {
            "total_requested_items": len(result.requested_items),
            "priced_items_count": len(result.item_by_item_optimal),
            "unpriced_items_count": len(unpriced_items),
            "best_single_store": best_single,
            "multi_store_optimal_total": result.multi_store_total_price,
            "potential_savings": savings,
            "potential_savings_percent": savings_pct,
        }

        # Build articles list
        articles_list: List[Dict[str, Any]] = []
        for opt in result.item_by_item_optimal:
            product = opt.product
            cheapest_st = opt.cheapest_store
            weight = (
                round(opt.quantity * (opt.numerator / opt.denominator), 2)
                if opt.denominator
                else float(opt.quantity)
            )
            weighted_subtotal = (
                round(opt.price * opt.quantity * (opt.numerator / opt.denominator))
                if opt.denominator
                else (opt.price * opt.quantity)
            )

            cheapest_store_dict = _format_store_dict(cheapest_st)

            articles_list.append(
                {
                    "ean": getattr(product, "ean", ""),
                    "name": getattr(product, "name", ""),
                    "brand": getattr(product, "brand_name", "") or "",
                    "category": getattr(product, "category_name", "") or "",
                    "package": getattr(product, "package", "") or "",
                    "quantity": opt.quantity,
                    "numerator": opt.numerator,
                    "denominator": opt.denominator,
                    "weight": weight,
                    "cheapest_store": cheapest_store_dict,
                    "min_price": opt.price,
                    "reference_price": opt.reference_price,
                    "max_price": opt.max_price,
                    "price_dispersion_pct": opt.price_dispersion,
                    "unit_price": opt.unit_price,
                    "unit": opt.unit,
                    "weighted_subtotal": weighted_subtotal,
                }
            )

        # Build complete and partial stores lists
        complete_stores: List[Dict[str, Any]] = []
        for st_total in result.complete_stores:
            st = st_total.store
            st_dict = _format_store_dict(st) or {}
            complete_stores.append(
                {
                    **st_dict,
                    "total_price": st_total.total_price,
                    "coverage_percent": 100.0,
                    "matched_items": st_total.matched_items_count,
                    "item_prices": {
                        ean: {
                            "price": item_p.price,
                            "unit_price": item_p.unit_price,
                            "unit": item_p.unit,
                            "is_lowest": item_p.is_lowest,
                            "is_highest": item_p.is_highest,
                            "is_above_reference": item_p.is_above_reference,
                        }
                        for ean, item_p in st_total.item_prices.items()
                    },
                }
            )

        partial_stores: List[Dict[str, Any]] = []
        for st_total in result.partial_stores:
            st = st_total.store
            st_dict = _format_store_dict(st) or {}
            coverage = (
                round(
                    (st_total.matched_items_count / st_total.requested_items_count)
                    * 100,
                    1,
                )
                if st_total.requested_items_count
                else 0.0
            )
            partial_stores.append(
                {
                    **st_dict,
                    "subtotal_price": st_total.total_price,
                    "coverage_percent": coverage,
                    "matched_items": st_total.matched_items_count,
                    "total_requested_items": st_total.requested_items_count,
                    "item_prices": {
                        ean: {
                            "price": item_p.price,
                            "unit_price": item_p.unit_price,
                            "unit": item_p.unit,
                            "is_lowest": item_p.is_lowest,
                            "is_highest": item_p.is_highest,
                            "is_above_reference": item_p.is_above_reference,
                        }
                        for ean, item_p in st_total.item_prices.items()
                    },
                }
            )

        # Build substitutions
        substitutions: List[Dict[str, Any]] = []
        for sub in getattr(result, "suggested_substitutions", []):
            st = sub.cheapest_store
            substitutions.append(
                {
                    "original_ean": sub.original_ean,
                    "substitute_ean": getattr(sub.product, "ean", ""),
                    "substitute_name": getattr(sub.product, "name", ""),
                    "substitute_brand": getattr(sub.product, "brand_name", "") or "",
                    "cheapest_store": _format_store_dict(st),
                    "price": sub.price,
                    "unit_price": sub.unit_price,
                    "unit": sub.unit,
                    "savings_amount": sub.savings_amount,
                    "savings_percent": sub.savings_percent,
                }
            )

        report = {
            "report_type": "basket_prices_report",
            "version": "1.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "basket": basket_info,
            "parameters": {
                "city": result.city,
                "date": (
                    result.calculation_date.isoformat()
                    if isinstance(result.calculation_date, (date, datetime))
                    else str(result.calculation_date)
                ),
            },
            "summary": summary,
            "articles": articles_list,
            "unpriced_articles": unpriced_items,
            "complete_stores": complete_stores,
            "partial_stores": partial_stores,
            "suggested_substitutions": substitutions,
        }
        return report

    @classmethod
    def export_to_json(
        cls,
        result: BasketOptimizationResult,
        basket: Optional[Basket] = None,
        unpriced_items: Optional[List[Dict[str, Any]]] = None,
        indent: int = 2,
    ) -> str:
        """Serializes price report dictionary into formatted JSON string."""
        data = cls.build_report_dict(
            result, basket=basket, unpriced_items=unpriced_items
        )
        return json.dumps(data, ensure_ascii=False, indent=indent)


COMMON_PASSWORDS_BLACKLIST = {
    "1234567890",
    "password123",
    "admin12345",
    "qwerty1234",
    "supersecret",
    "sur_en_precios",
    "argentina2026",
    "contraseña123",
    "123456789012",
}

DUMMY_BCRYPT_HASH = "$2b$12$e8x/yX3yX3yX3yX3yX3yXeK6c459o96wE2ZJpPq7OqG7fP1lE7rTe"


class AuthService:
    """Domain service enforcing strict OWASP security standards for user credentials."""

    @staticmethod
    def validate_username(username: str) -> tuple[bool, str]:
        """Validates username formatting: 3-30 chars, alphanumeric, underscores, dots, hyphens."""
        if not username:
            return False, "El nombre de usuario no puede estar vacío."
        clean_user = username.strip().lower()
        if len(clean_user) < 3:
            return False, "El nombre de usuario debe tener al menos 3 caracteres."
        if len(clean_user) > 30:
            return False, "El nombre de usuario no puede superar los 30 caracteres."
        if not re.match(r"^[a-zA-Z0-9_.-]+$", clean_user):
            return (
                False,
                "El nombre de usuario solo puede contener letras, números, puntos, guiones o guiones bajos.",
            )
        if clean_user.isdigit():
            return (
                False,
                "El nombre de usuario no puede estar compuesto únicamente por dígitos.",
            )
        return True, ""

    @staticmethod
    def validate_password(password: str) -> tuple[bool, str]:
        """Validates password strength following strict OWASP best practices.

        Rules:
          - Minimum 10 characters.
          - Maximum 128 characters (mitigates bcrypt DoS).
          - At least one letter and one number or special character.
          - Not present in common password blacklist.
        """
        if not password:
            return False, "La contraseña no puede estar vacía."
        if len(password) < 10:
            return False, "La contraseña debe tener al menos 10 caracteres."
        if len(password) > 128:
            return False, "La contraseña no puede superar los 128 caracteres."
        if password.lower() in COMMON_PASSWORDS_BLACKLIST:
            return (
                False,
                "La contraseña elegida es demasiado común o insegura. Elija una más robusta.",
            )
        has_letter = any(c.isalpha() for c in password)
        has_digit_or_symbol = any(not c.isalpha() for c in password)
        if not (has_letter and has_digit_or_symbol):
            return (
                False,
                "La contraseña debe combinar letras con números o símbolos especiales.",
            )
        return True, ""

    @staticmethod
    def hash_password(password: str) -> str:
        """Hashes password with bcrypt and work factor 12."""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(12)).decode(
            "utf-8"
        )

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verifies password using constant-time comparison."""
        if not password or not password_hash:
            return False
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"), password_hash.encode("utf-8")
            )
        except Exception:
            return False

    @staticmethod
    def dummy_verify() -> None:
        """Executes a constant-time check to prevent timing attacks when user does not exist."""
        try:
            bcrypt.checkpw(
                b"dummy_timing_protection_pass", DUMMY_BCRYPT_HASH.encode("utf-8")
            )
        except Exception:
            pass
