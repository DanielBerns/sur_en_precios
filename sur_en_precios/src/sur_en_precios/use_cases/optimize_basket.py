from datetime import date
from typing import Dict, List

from sur_en_precios.domain.models import BasketOptimizationResult
from sur_en_precios.domain.models_public import ArticleCard
from sur_en_precios.domain.models_user import BasketItem
from sur_en_precios.domain.ports import CatalogRepositoryPort, PriceRepositoryPort
from sur_en_precios.domain.services import BasketOptimizerService


class OptimizeBasketUseCase:
    """Use Case for executing basket optimization across stores in a city."""

    def __init__(
        self, catalog_repo: CatalogRepositoryPort, price_repo: PriceRepositoryPort
    ):
        self._catalog_repo = catalog_repo
        self._price_repo = price_repo

    def execute(
        self, city: str, target_date: date, requested_items: List[BasketItem]
    ) -> BasketOptimizationResult:
        """Executes basket optimization logic for requested items."""
        eans = [item.ean for item in requested_items]

        # Fetch stores in city
        stores = self._catalog_repo.get_stores_by_city(city)

        # Fetch catalog articles
        products_map: Dict[str, ArticleCard] = {}
        for ean in eans:
            p = self._catalog_repo.get_article_by_ean(ean)
            if p:
                products_map[ean] = p

        # Fetch prices and reference prices
        prices = self._price_repo.get_prices_for_basket(city, target_date, eans)
        reference_prices = self._price_repo.get_reference_prices(
            city, target_date, eans
        )

        return BasketOptimizerService.optimize_basket(
            city=city,
            calc_date=target_date,
            requested_items=requested_items,
            products_map=products_map,
            stores=stores,
            prices=prices,
            reference_prices=reference_prices,
        )
