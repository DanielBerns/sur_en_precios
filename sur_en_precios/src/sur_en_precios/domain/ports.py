from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from sur_en_precios.domain.models import (
    DailyPrice,
    DailyProductMetrics,
    Product,
    ShoppingList,
    Store,
    User,
)


class ScraperPort(ABC):
    """Port for fetching daily SEPA datasets asynchronously."""

    @abstractmethod
    async def fetch_daily_dataset(self, target_dir: Path) -> Path:
        """Downloads the daily dataset archive into target_dir using pathlib.Path."""
        ...


class RawStoragePort(ABC):
    """Port for managing landed raw daily archive files."""

    @abstractmethod
    def save_raw_archive(self, content: bytes, filename: str) -> Path:
        """Saves raw byte stream using pathlib.Path."""
        ...

    @abstractmethod
    def extract_archive(self, archive_path: Path) -> List[Path]:
        """Extracts archive into daily working folder."""
        ...


class CatalogRepositoryPort(ABC):
    """Port for product and store catalog operations."""

    @abstractmethod
    def save_products(self, products: List[Product]) -> None: ...

    @abstractmethod
    def save_stores(self, stores: List[Store]) -> None: ...

    @abstractmethod
    def search_products(self, query: str, limit: int = 50) -> List[Product]: ...

    @abstractmethod
    def get_product_by_ean(self, ean: str) -> Optional[Product]: ...

    @abstractmethod
    def get_stores_by_city(self, city: str) -> List[Store]: ...


class PriceRepositoryPort(ABC):
    """Port for daily prices and statistical metrics queries."""

    @abstractmethod
    def save_prices(self, prices: List[DailyPrice]) -> None: ...

    @abstractmethod
    def save_metrics(self, metrics: List[DailyProductMetrics]) -> None: ...

    @abstractmethod
    def get_prices_for_basket(
        self, city: str, price_date: date, eans: List[str]
    ) -> List[DailyPrice]: ...

    @abstractmethod
    def get_reference_prices(
        self, city: str, price_date: date, eans: List[str]
    ) -> Dict[str, int]: ...


class UserRepositoryPort(ABC):
    """Port for user accounts and shopping list management."""

    @abstractmethod
    def create_user(self, email: str, password_hash: str) -> User: ...

    @abstractmethod
    def get_user_by_email(self, email: str) -> Optional[User]: ...

    @abstractmethod
    def save_shopping_list(self, shopping_list: ShoppingList) -> ShoppingList: ...

    @abstractmethod
    def get_user_shopping_lists(self, user_id: int) -> List[ShoppingList]: ...

    @abstractmethod
    def delete_shopping_list(self, list_id: int, user_id: int) -> bool: ...
