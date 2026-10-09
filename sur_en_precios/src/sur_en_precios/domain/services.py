import math
import statistics
from datetime import date
from typing import Dict, List, Optional, Tuple

from sur_en_precios.domain.models import (
    BasketOptimizationResult,
    DailyPrice,
    DailyProductMetrics,
    ItemBestPrice,
    ListItem,
    Product,
    Store,
    StoreBasketTotal,
    StoreItemPrice,
)


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
        ref_price_7d_ago: Optional[int] = None,
        ref_price_30d_ago: Optional[int] = None,
        ref_price_90d_ago: Optional[int] = None,
    ) -> DailyProductMetrics:
        """Computes daily price metrics for a product in a city."""
        if not prices:
            return DailyProductMetrics(metric_date=metric_date, ean=ean, city=city)

        sorted_prices = sorted(prices)
        min_p = sorted_prices[0]
        max_p = sorted_prices[-1]
        median_p = round(statistics.median(sorted_prices))
        ref_p = cls.calculate_reference_price(sorted_prices)

        # Price dispersion: stddev / mean
        dispersion = None
        if len(sorted_prices) > 1:
            mean_val = statistics.mean(sorted_prices)
            if mean_val > 0:
                dispersion = round(statistics.stdev(sorted_prices) / mean_val, 4)

        # Percentage changes based on Reference Price
        pct_7d = None
        if ref_p is not None and ref_price_7d_ago and ref_price_7d_ago > 0:
            pct_7d = round(((ref_p - ref_price_7d_ago) / ref_price_7d_ago) * 100.0, 2)

        pct_30d = None
        if ref_p is not None and ref_price_30d_ago and ref_price_30d_ago > 0:
            pct_30d = round(
                ((ref_p - ref_price_30d_ago) / ref_price_30d_ago) * 100.0, 2
            )

        pct_90d = None
        if ref_p is not None and ref_price_90d_ago and ref_price_90d_ago > 0:
            pct_90d = round(
                ((ref_p - ref_price_90d_ago) / ref_price_90d_ago) * 100.0, 2
            )

        return DailyProductMetrics(
            metric_date=metric_date,
            ean=ean,
            city=city,
            min_price=min_p,
            max_price=max_p,
            median_price=median_p,
            reference_price=ref_p,
            price_dispersion=dispersion,
            pct_change_7d=pct_7d,
            pct_change_30d=pct_30d,
            pct_change_90d=pct_90d,
        )


class BasketOptimizerService:
    """Domain service for optimizing multi-product shopping baskets across stores."""

    @staticmethod
    def optimize_basket(
        city: str,
        calc_date: date,
        requested_items: List[ListItem],
        products_map: Dict[str, Product],
        stores: List[Store],
        prices: List[DailyPrice],
        reference_prices: Dict[str, int],
    ) -> BasketOptimizationResult:
        """Optimizes a shopping basket across city stores for a target date."""
        # Index prices: (store_id, ean) -> price
        price_lookup: Dict[Tuple[str, str], int] = {}
        # Track city-wide min and max prices per product
        product_min_price: Dict[str, int] = {}
        product_max_price: Dict[str, int] = {}

        for p in prices:
            price_lookup[(p.store_id, p.ean)] = p.price

            if p.ean not in product_min_price or p.price < product_min_price[p.ean]:
                product_min_price[p.ean] = p.price
            if p.ean not in product_max_price or p.price > product_max_price[p.ean]:
                product_max_price[p.ean] = p.price

        total_requested_count = len(requested_items)

        complete_stores: List[StoreBasketTotal] = []
        partial_stores: List[StoreBasketTotal] = []

        # Evaluate each store
        for store in stores:
            store_item_prices: Dict[str, StoreItemPrice] = {}
            total_basket_price = 0
            matched_count = 0

            for item in requested_items:
                ean = item.ean
                item_price = price_lookup.get((store.id, ean))

                if item_price is not None:
                    matched_count += 1
                    total_basket_price += item_price * item.quantity

                    is_lowest = item_price == product_min_price.get(ean)
                    is_highest = item_price == product_max_price.get(ean)
                    ref_p = reference_prices.get(ean)
                    is_above_ref = (item_price > ref_p) if ref_p is not None else False

                    store_item_prices[ean] = StoreItemPrice(
                        ean=ean,
                        price=item_price,
                        is_lowest=is_lowest,
                        is_highest=is_highest,
                        is_above_reference=is_above_ref,
                    )

            if matched_count > 0:
                is_complete = matched_count == total_requested_count
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

        # Compute item-by-item optimal (cheapest store per item)
        item_by_item_optimal: List[ItemBestPrice] = []
        store_map = {s.id: s for s in stores}

        for item in requested_items:
            ean = item.ean
            product = products_map.get(ean, Product(ean=ean, name=f"Product {ean}"))
            cheapest_store_id: Optional[str] = None
            cheapest_price: Optional[int] = None

            for store in stores:
                price = price_lookup.get((store.id, ean))
                if price is not None:
                    if cheapest_price is None or price < cheapest_price:
                        cheapest_price = price
                        cheapest_store_id = store.id

            if cheapest_store_id and cheapest_price is not None:
                item_by_item_optimal.append(
                    ItemBestPrice(
                        product=product,
                        cheapest_store=store_map[cheapest_store_id],
                        price=cheapest_price,
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
        )
