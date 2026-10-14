from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from sur_en_precios.domain.models_public import (
    ArticleCard,
    ArticleMetric,
    Price,
    Store,
)
from sur_en_precios.domain.models_user import (
    Basket,
    User,
)


class ScraperPort(ABC):
    """Port for fetching daily SEPA datasets asynchronously."""

    @abstractmethod
    async def fetch_daily_dataset(self, target_dir: Path) -> Path:
        """Downloads the daily dataset archive into target_dir using pathlib.Path."""
        ...

    @abstractmethod
    async def fetch_webpage(self, url: Optional[str] = None) -> str:
        """Fetches the webpage HTML content asynchronously."""
        ...

    @abstractmethod
    async def download_file(
        self, file_url: str, target_dir: Path, filename: Optional[str] = None
    ) -> Path:
        """Downloads a specific remote file into target_dir."""
        ...

    @abstractmethod
    async def discover_dataset_archives(
        self, url: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Discovers dataset archive resources available on the portal webpage."""
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

    @abstractmethod
    def store_archive(self, source_archive: Path, target_date: date) -> Path:
        """Stores or copies archive to raw/<target_date>/sepa_<target_date>.zip."""
        ...


class SepaDatasetPort(ABC):
    """Port for inspecting and extracting SEPA archive components."""

    @abstractmethod
    def infer_data_date(self, archive_path: Path) -> date:
        """Infers the price date (YYYY-MM-DD) from archive contents or name."""
        ...

    @abstractmethod
    def list_chain_archives(self, raw_date_dir: Path) -> List[Path]:
        """Lists all inner chain archive files or directories within a raw date folder."""
        ...

    @abstractmethod
    def extract_member(
        self, chain_archive: Path, member_name: str, dest_dir: Path
    ) -> Path:
        """Extracts a specific CSV member from a chain archive into dest_dir."""
        ...


class CatalogRepositoryPort(ABC):
    """Port for article and store catalog operations."""

    @abstractmethod
    def save_articles(self, articles: List[ArticleCard]) -> None: ...

    @abstractmethod
    def save_stores(self, stores: List[Store]) -> None: ...

    @abstractmethod
    def search_articles(
        self, query: str, limit: int = 50, mode: str = "fuzzy"
    ) -> List[ArticleCard]: ...

    @abstractmethod
    def get_article_by_ean(self, ean: str) -> Optional[ArticleCard]: ...

    @abstractmethod
    def get_stores_by_city(self, city: str) -> List[Store]: ...


class PriceRepositoryPort(ABC):
    """Port for daily prices and statistical metrics queries."""

    @abstractmethod
    def save_prices(self, prices: List[Price]) -> None: ...

    @abstractmethod
    def save_metrics(self, metrics: List[ArticleMetric]) -> None: ...

    @abstractmethod
    def delete_prices_for_date(self, price_date: date) -> int: ...

    @abstractmethod
    def delete_metrics_for_date(self, metric_date: date) -> int: ...

    @abstractmethod
    def get_prices_for_basket(
        self, city: str, price_date: date, eans: List[str]
    ) -> List[Price]: ...

    @abstractmethod
    def get_reference_prices(
        self, city: str, price_date: date, eans: List[str]
    ) -> Dict[str, int]: ...


class UserRepositoryPort(ABC):
    """Port for user accounts and basket management."""

    @abstractmethod
    def create_user(self, email: str, password_hash: str) -> User: ...

    @abstractmethod
    def get_user_by_email(self, email: str) -> Optional[User]: ...

    @abstractmethod
    def save_basket(self, basket: Basket) -> Basket: ...

    @abstractmethod
    def get_user_baskets(self, user_id: int) -> List[Basket]: ...

    @abstractmethod
    def get_basket_by_uuid(self, uuid_str: str) -> Optional[Basket]: ...

    @abstractmethod
    def delete_basket(self, basket_id: int, user_id: int) -> bool: ...
