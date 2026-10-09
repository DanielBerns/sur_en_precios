import logging
from datetime import date
from pathlib import Path

import duckdb
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.models_public import PublicBase
from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
)
from sur_en_precios.domain.models import DailyPrice, DailyProductMetrics, Product, Store
from sur_en_precios.domain.services import PriceMetricsCalculator


class ProcessAndPublishRegionUseCase:
    """ETL Use Case: Processes raw daily SEPA CSVs, computes Reference Price metrics, and builds public.sqlite."""

    def __init__(
        self, target_region: str = "AR-B", logger: logging.Logger | None = None
    ):
        self._target_region = target_region
        self._logger = logger or logging.getLogger("sur_en_precios")

    def execute(
        self, extracted_dir: Path, output_db_path: Path, process_date: date
    ) -> None:
        """Executes ETL data processing using DuckDB vector operations and SQLAlchemy 2.0 ORM."""
        self._logger.info(
            "Starting regional data processing ETL...",
            extra={
                "region": self._target_region,
                "date": str(process_date),
                "db_path": str(output_db_path),
            },
        )

        sucursales_csv = extracted_dir / "sucursales.csv"
        productos_csv = extracted_dir / "productos.csv"

        if not sucursales_csv.exists() or not productos_csv.exists():
            raise FileNotFoundError(
                f"Missing required SEPA CSV files in {extracted_dir}. (Expected sucursales.csv and productos.csv)"
            )

        output_db_path.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{output_db_path}")
        PublicBase.metadata.create_all(engine)

        con = duckdb.connect()

        # Load Stores filtered by target region
        stores_rows = con.execute(
            f"""
            SELECT 
                CAST(id_sucursal AS VARCHAR) AS id,
                COALESCE(sucursales_nombre, 'Sucursal') AS store_name,
                'Supermercado' AS chain_name,
                COALESCE(sucursales_localidad, 'General') AS city,
                sucursales_calle AS address,
                TRY_CAST(sucursales_latitud AS DOUBLE) AS latitude,
                TRY_CAST(sucursales_longitud AS DOUBLE) AS longitude
            FROM read_csv('{sucursales_csv}', delim='|', header=True, ignore_errors=True)
            WHERE sucursales_provincia = '{self._target_region}'
            """
        ).fetchall()

        # Load Products & Prices with integer Pesos rounding
        prices_rows = con.execute(
            f"""
            SELECT 
                CAST(id_producto AS VARCHAR) AS ean,
                productos_descripcion AS name,
                productos_marca AS brand,
                'Almacén' AS category,
                CAST(id_sucursal AS VARCHAR) AS store_id,
                ROUND(TRY_CAST(productos_precio_lista AS DOUBLE)) AS price
            FROM read_csv('{productos_csv}', delim='|', header=True, ignore_errors=True)
            WHERE TRY_CAST(productos_precio_lista AS DOUBLE) IS NOT NULL
              AND TRY_CAST(productos_precio_lista AS DOUBLE) > 0
            """
        ).fetchall()

        with Session(engine) as session:
            cat_repo = SqlAlchemyCatalogRepository(session)
            price_repo = SqlAlchemyPriceRepository(session)

            # Insert Stores
            store_entities: list[Store] = []
            for row in stores_rows:
                s_id, s_name, c_name, city, addr, lat, lon = row
                store_entities.append(
                    Store(
                        id=str(s_id),
                        chain_name=str(c_name),
                        store_name=str(s_name),
                        city=str(city),
                        address=str(addr) if addr else None,
                        latitude=float(lat) if lat is not None else None,
                        longitude=float(lon) if lon is not None else None,
                    )
                )
            cat_repo.save_stores(store_entities)

            # Insert Products & Prices
            product_entities: list[Product] = []
            price_entities: list[DailyPrice] = []
            distinct_products: dict[str, Product] = {}

            # Group prices by (ean, city) to compute Reference Price
            city_prices_map: dict[tuple[str, str], list[int]] = {}
            store_city_map = {s.id: s.city for s in store_entities}

            for row in prices_rows:
                ean, p_name, brand, category, store_id, price_val = row
                ean = str(ean)
                store_id = str(store_id)
                price_int = int(price_val)

                if ean not in distinct_products:
                    p = Product(
                        ean=ean,
                        name=str(p_name),
                        brand=str(brand) if brand else None,
                        category=str(category) if category else None,
                    )
                    distinct_products[ean] = p
                    product_entities.append(p)

                price_entities.append(
                    DailyPrice(
                        price_date=process_date,
                        ean=ean,
                        store_id=store_id,
                        price=price_int,
                    )
                )

                city = store_city_map.get(store_id, "General")
                key = (ean, city)
                if key not in city_prices_map:
                    city_prices_map[key] = []
                city_prices_map[key].append(price_int)

            cat_repo.save_products(product_entities)
            price_repo.save_prices(price_entities)

            # Compute and save Reference Price Metrics
            metric_entities: list[DailyProductMetrics] = []
            for (ean, city), p_list in city_prices_map.items():
                m = PriceMetricsCalculator.calculate_metrics(
                    metric_date=process_date,
                    ean=ean,
                    city=city,
                    prices=p_list,
                )
                metric_entities.append(m)

            price_repo.save_metrics(metric_entities)

            # Create SQLite FTS5 Full-Text Search Table
            session.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
                        ean UNINDEXED,
                        name,
                        brand,
                        category,
                        content='products',
                        content_rowid='rowid'
                    );
                    """
                )
            )
            session.execute(
                text(
                    """
                    INSERT INTO products_fts(products_fts) VALUES('rebuild');
                    """
                )
            )
            session.commit()

        self._logger.info(
            "ETL processing completed successfully.",
            extra={
                "stores_count": len(store_entities),
                "products_count": len(product_entities),
                "prices_count": len(price_entities),
            },
        )
