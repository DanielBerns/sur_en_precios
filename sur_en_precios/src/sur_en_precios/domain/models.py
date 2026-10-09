from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Product:
    ean: str
    name: str
    brand: Optional[str] = None
    category: Optional[str] = None


@dataclass(frozen=True)
class Store:
    id: str
    chain_name: str
    store_name: str
    city: str
    address: Optional[str] = None
    latitude: Optional[float] = (
        None  # Optional: coordinates may be missing in SEPA dataset
    )
    longitude: Optional[float] = (
        None  # Optional: coordinates may be missing in SEPA dataset
    )


@dataclass(frozen=True)
class DailyPrice:
    price_date: date
    ean: str
    store_id: str
    price: int  # Integer Pesos Argentinos (ARS)


@dataclass(frozen=True)
class DailyProductMetrics:
    metric_date: date
    ean: str
    city: str
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    median_price: Optional[int] = None
    reference_price: Optional[int] = (
        None  # Geometric mean of prices (expressed in integer ARS)
    )
    price_dispersion: Optional[float] = None
    pct_change_7d: Optional[float] = None
    pct_change_30d: Optional[float] = None
    pct_change_90d: Optional[float] = None


@dataclass(frozen=True)
class ListItem:
    ean: str
    quantity: int = 1


@dataclass
class ShoppingList:
    id: Optional[int]
    user_id: int
    name: str
    items: List[ListItem] = field(default_factory=list)
    created_at: Optional[datetime] = None


@dataclass
class User:
    id: Optional[int]
    email: str
    password_hash: str
    created_at: Optional[datetime] = None


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
    product: Product
    cheapest_store: Store
    price: int


@dataclass
class BasketOptimizationResult:
    city: str
    calculation_date: date
    requested_items: List[ListItem]
    best_single_store: Optional[StoreBasketTotal]
    item_by_item_optimal: List[ItemBestPrice]
    complete_stores: List[StoreBasketTotal]
    partial_stores: List[StoreBasketTotal]
    reference_prices: Dict[str, int]  # Dict of ean -> reference_price
