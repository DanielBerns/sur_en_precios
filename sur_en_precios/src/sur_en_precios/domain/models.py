from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

from sur_en_precios.domain.models_public import ArticleCard, Store
from sur_en_precios.domain.models_user import BasketItem


@dataclass
class StoreItemPrice:
    ean: str
    price: int
    is_lowest: bool = False
    is_highest: bool = False
    is_above_reference: bool = False


@dataclass
class StoreBasketTotal:
    store: Store
    total_price: int
    matched_items_count: int
    requested_items_count: int
    is_complete: bool
    item_prices: Dict[str, StoreItemPrice] = field(default_factory=dict)


@dataclass
class ItemBestPrice:
    product: ArticleCard
    cheapest_store: Store
    price: int


@dataclass
class BasketOptimizationResult:
    city: str
    calculation_date: date
    requested_items: List[BasketItem]
    best_single_store: Optional[StoreBasketTotal]
    item_by_item_optimal: List[ItemBestPrice]
    complete_stores: List[StoreBasketTotal]
    partial_stores: List[StoreBasketTotal]
    reference_prices: Dict[str, int]  # Dict of ean -> reference_price
