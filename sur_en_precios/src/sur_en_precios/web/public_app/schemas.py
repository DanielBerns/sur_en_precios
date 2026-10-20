import datetime as dt
import math
import re
from typing import Any, Dict, Generator, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class Pagination:
    """Helper class for paginating collections in Flask/Jinja templates."""

    def __init__(
        self,
        page: int,
        per_page: int,
        total_items: int,
        items: Optional[List[Any]] = None,
    ):
        self.per_page = max(1, per_page)
        self.total_items = max(0, total_items)
        self.total_pages = max(1, math.ceil(self.total_items / self.per_page))
        self.page = min(max(1, page), self.total_pages) if self.total_items > 0 else 1
        self.items = items if items is not None else []

    @property
    def has_prev(self) -> bool:
        return self.page > 1

    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @property
    def prev_num(self) -> int:
        return self.page - 1

    @property
    def next_num(self) -> int:
        return self.page + 1

    @property
    def start_item(self) -> int:
        if self.total_items == 0:
            return 0
        return (self.page - 1) * self.per_page + 1

    @property
    def end_item(self) -> int:
        return min(self.page * self.per_page, self.total_items)

    def iter_pages(
        self,
        left_edge: int = 2,
        left_current: int = 2,
        right_current: int = 2,
        right_edge: int = 2,
    ) -> Generator[Optional[int], None, None]:
        """Yields page numbers for pagination controls, inserting None for gaps."""
        last = 0
        for num in range(1, self.total_pages + 1):
            if (
                num <= left_edge
                or (
                    num >= self.page - left_current and num <= self.page + right_current
                )
                or num > self.total_pages - right_edge
            ):
                if last and num - last > 1:
                    yield None
                yield num
                last = num


class ArticleSearchQuery(BaseModel):
    """Query parameters for article text search."""

    q: str = ""
    mode: Literal["fuzzy", "exact"] = "fuzzy"
    limit: int = Field(default=20, ge=1, le=100)
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)


class CategoryArticlesQuery(BaseModel):
    """Query parameters for category article listing."""

    limit: int = Field(default=150, ge=1, le=500)


class ArticlePriceStatsQuery(BaseModel):
    """Query parameters for article price statistics."""

    city: Optional[str] = None
    date: Optional[dt.date] = None

    @classmethod
    def from_request(
        cls, city: Optional[str], date_str: Optional[str]
    ) -> "ArticlePriceStatsQuery":
        target_date: Optional[dt.date] = None
        if date_str and date_str.strip():
            try:
                target_date = dt.date.fromisoformat(date_str.strip())
            except ValueError:
                target_date = None
        return cls(city=city, date=target_date)


class ArticleSearchResultSchema(BaseModel):
    """JSON response schema for an article in search or category list."""

    ean: str
    name: str
    brand: str = ""
    category: str = ""


class StorePriceItemSchema(BaseModel):
    """JSON response schema for a price offered by a specific store."""

    chain_name: str
    branch_name: Optional[str] = None
    city: Optional[str] = None
    price: int
    unit_price: Optional[float] = None
    unit: Optional[str] = None
    date: Optional[str] = None


class ArticlePriceStatsResponseSchema(BaseModel):
    """JSON response schema for article price statistics."""

    ean: str
    name: Optional[str] = None
    clean_description: Optional[str] = None
    brand_name: Optional[str] = None
    package: Optional[str] = None
    category_name: Optional[str] = None
    date: Optional[str] = None
    city: Optional[str] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    reference_price: Optional[int] = None
    price_dispersion: Optional[float] = None
    cheapest_store: Optional[str] = None
    most_expensive_store: Optional[str] = None
    stores_count: int = 0
    store_prices: List[StorePriceItemSchema] = []


class BasketCreateForm(BaseModel):
    """Form schema for creating a new basket from POST /baskets/create."""

    name: str = "Canasta de Compras"
    eans: str = ""

    @field_validator("name", mode="before")
    @classmethod
    def clean_name(cls, v: Any) -> str:
        s = str(v).strip() if v is not None else ""
        return s or "Canasta de Compras"

    @property
    def ean_list(self) -> List[str]:
        return [e.strip() for e in self.eans.split(",") if e.strip()]


class BasketItemUpdateSchema(BaseModel):
    """Schema representing one item's parameters within an edited basket."""

    ean: str
    quantity: int = Field(default=1, ge=1)
    selected: bool = True
    numerator: int = Field(default=1, ge=1)
    denominator: int = Field(default=1, ge=1)


class BasketSaveForm(BaseModel):
    """Form schema for saving updates to a basket."""

    action: str = "save"
    name: str = ""
    is_public: bool = False
    eans: str = ""
    items: List[BasketItemUpdateSchema] = []

    @classmethod
    def from_form(
        cls, form_data: Dict[str, Any], default_name: str = "Canasta de Compras"
    ) -> "BasketSaveForm":
        action = form_data.get("action", "save")
        raw_name = form_data.get("name", "")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        name = name or default_name
        is_public = form_data.get("is_public") == "1"
        eans_raw = form_data.get("eans", "")
        ean_list = [e.strip() for e in eans_raw.split(",") if e.strip()]

        items: List[BasketItemUpdateSchema] = []
        for ean in ean_list:
            qty_raw = form_data.get(f"item_quantity_{ean}", "1")
            sel_raw = form_data.get(f"item_selected_{ean}")
            num_raw = form_data.get(f"item_numerator_{ean}", "1")
            den_raw = form_data.get(f"item_denominator_{ean}", "1")

            try:
                qty = max(1, int(qty_raw))
            except (ValueError, TypeError):
                qty = 1

            try:
                num = max(1, int(num_raw))
            except (ValueError, TypeError):
                num = 1

            try:
                den = int(den_raw)
                if den <= 0:
                    den = 1
            except (ValueError, TypeError):
                den = 1

            selected = sel_raw == "1"
            items.append(
                BasketItemUpdateSchema(
                    ean=ean,
                    quantity=qty,
                    selected=selected,
                    numerator=num,
                    denominator=den,
                )
            )

        return cls(
            action=action,
            name=name,
            is_public=is_public,
            eans=eans_raw,
            items=items,
        )


class OptimizeQuerySchema(BaseModel):
    """Query schema for basket price optimization calculation."""

    city: Optional[str] = None
    date: Optional[str] = None
    eans: str = ""
    list_id: Optional[str] = None
    public_uuid: Optional[str] = None

    @property
    def ean_list(self) -> List[str]:
        if not self.eans.strip():
            return []
        return [e.strip() for e in re.split(r"[\s,]+", self.eans) if e.strip()]
