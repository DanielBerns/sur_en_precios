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
    unit_price: Optional[float] = None
    unit: Optional[str] = None


@dataclass
class StoreBasketTotal:
    store: Store
    total_price: int
    matched_items_count: int
    requested_items_count: int
    is_complete: bool
    item_prices: Dict[str, StoreItemPrice] = field(default_factory=dict)


@dataclass
class ItemSubstitution:
    original_ean: str
    product: ArticleCard
    cheapest_store: Store
    price: int
    unit_price: Optional[float] = None
    unit: Optional[str] = None
    savings_amount: int = 0
    savings_percent: float = 0.0


@dataclass
class ItemBestPrice:
    product: ArticleCard
    cheapest_store: Store
    price: int
    unit_price: Optional[float] = None
    unit: Optional[str] = None
    substitution: Optional[ItemSubstitution] = None
    min_price: Optional[int] = None
    reference_price: Optional[int] = None
    max_price: Optional[int] = None
    price_dispersion: Optional[float] = None
    quantity: int = 1
    numerator: int = 1
    denominator: int = 1


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
    suggested_substitutions: List[ItemSubstitution] = field(default_factory=list)
    multi_store_total_price: int = 0


@dataclass
class StorePriceDetail:
    chain_name: str
    branch_name: str
    city: str
    price: int
    unit_price: Optional[float] = None
    unit: Optional[str] = None
    date: Optional[date] = None


@dataclass
class ArticlePriceStats:
    ean: str
    name: str
    clean_description: str
    brand_name: Optional[str] = None
    package: Optional[str] = None
    category_name: Optional[str] = None
    date: Optional[date] = None
    city: Optional[str] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    reference_price: Optional[int] = None
    price_dispersion: Optional[float] = None
    cheapest_store: Optional[str] = None
    most_expensive_store: Optional[str] = None
    stores_count: int = 0
    store_prices: List[StorePriceDetail] = field(default_factory=list)
