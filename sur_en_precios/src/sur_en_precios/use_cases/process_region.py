import logging
import shutil
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import duckdb
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from sur_en_precios.adapters.database.models_public import PublicBase
from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
)
from sur_en_precios.adapters.sepa_archive import SepaArchiveError, ZipSepaDatasetAdapter
from sur_en_precios.domain.models import (
    DailyPrice,
    DailyProductMetrics,
    Product,
    Store,
)
from sur_en_precios.domain.ports import SepaDatasetPort
from sur_en_precios.domain.services import PriceMetricsCalculator


class ProcessAndPublishRegionUseCase:
    """ETL Use Case: Processes raw daily SEPA CSVs per chain archive, computes Reference Price metrics, and updates public.sqlite."""

    def __init__(
        self,
        target_region: str = "AR-B",
        sepa_dataset_adapter: Optional[SepaDatasetPort] = None,
        batch_size: int = 10_000,
        temp_dir: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._target_region = target_region
        self._sepa_dataset = sepa_dataset_adapter or ZipSepaDatasetAdapter()
        self._batch_size = batch_size
        self._temp_dir = temp_dir
        self._logger = logger or logging.getLogger("sur_en_precios")

    def execute(
        self, raw_date_dir: Path, output_db_path: Path, process_date: date
    ) -> None:
        """Executes ETL data processing using DuckDB vector operations and SQLAlchemy 2.0 ORM."""
        self._logger.info(
            "Starting regional data processing ETL...",
            extra={
                "region": self._target_region,
                "date": str(process_date),
                "raw_dir": str(raw_date_dir),
                "db_path": str(output_db_path),
            },
        )

        chain_archives = self._sepa_dataset.list_chain_archives(raw_date_dir)
        if not chain_archives:
            raise FileNotFoundError(
                f"No SEPA chain archives or CSV files found in {raw_date_dir}"
            )

        output_db_path.parent.mkdir(parents=True, exist_ok=True)
        if output_db_path.exists():
            output_db_path.unlink()
        engine = create_engine(f"sqlite:///{output_db_path}")
        PublicBase.metadata.create_all(engine)

        work_temp_base = (self._temp_dir or (output_db_path.parent / "tmp")).resolve()
        work_temp_base.mkdir(parents=True, exist_ok=True)

        con = duckdb.connect()

        all_stores: List[Store] = []
        all_products_dict: Dict[str, Product] = {}
        all_prices: List[DailyPrice] = []
        store_city_map: Dict[str, str] = {}
        city_prices_map: Dict[Tuple[str, str], List[int]] = {}

        processed_chains_count = 0

        for idx, chain_archive in enumerate(chain_archives):
            chain_temp = work_temp_base / f"chain_{idx}"
            if chain_temp.exists():
                shutil.rmtree(chain_temp)
            chain_temp.mkdir(parents=True, exist_ok=True)

            try:
                # 1. Extract sucursales.csv and optionally comercio.csv
                sucursales_csv = self._sepa_dataset.extract_member(
                    chain_archive, "sucursales.csv", chain_temp
                )

                has_comercio = False
                try:
                    comercio_csv = self._sepa_dataset.extract_member(
                        chain_archive, "comercio.csv", chain_temp
                    )
                    has_comercio = comercio_csv.exists()
                except (FileNotFoundError, SepaArchiveError):
                    has_comercio = False

                # 2. Query stores filtered by region
                region_filter = (
                    ""
                    if self._target_region.upper() == "ALL"
                    else f"WHERE sucursales_provincia = '{self._target_region}'"
                )

                if has_comercio:
                    store_query = f"""
                    SELECT 
                        s.id_comercio,
                        s.id_bandera,
                        s.id_sucursal,
                        concat(CAST(s.id_comercio AS VARCHAR), '-', CAST(s.id_bandera AS VARCHAR), '-', CAST(s.id_sucursal AS VARCHAR)) AS composite_id,
                        COALESCE(c.comercio_bandera_nombre, 'Supermercado') AS chain_name,
                        COALESCE(s.sucursales_nombre, 'Sucursal') AS store_name,
                        COALESCE(s.sucursales_localidad, 'General') AS city,
                        concat_ws(' ', s.sucursales_calle, s.sucursales_numero) AS address,
                        TRY_CAST(s.sucursales_latitud AS DOUBLE) AS latitude,
                        TRY_CAST(s.sucursales_longitud AS DOUBLE) AS longitude
                    FROM read_csv('{sucursales_csv}', delim='|', header=True, all_varchar=True, ignore_errors=True) s
                    LEFT JOIN read_csv('{comercio_csv}', delim='|', header=True, all_varchar=True, ignore_errors=True) c
                      ON CAST(s.id_comercio AS VARCHAR) = CAST(c.id_comercio AS VARCHAR)
                     AND CAST(s.id_bandera AS VARCHAR) = CAST(c.id_bandera AS VARCHAR)
                    {region_filter}
                    """
                else:
                    store_query = f"""
                    SELECT 
                        id_comercio,
                        id_bandera,
                        id_sucursal,
                        concat(CAST(id_comercio AS VARCHAR), '-', CAST(id_bandera AS VARCHAR), '-', CAST(id_sucursal AS VARCHAR)) AS composite_id,
                        'Supermercado' AS chain_name,
                        COALESCE(sucursales_nombre, 'Sucursal') AS store_name,
                        COALESCE(sucursales_localidad, 'General') AS city,
                        concat_ws(' ', sucursales_calle, sucursales_numero) AS address,
                        TRY_CAST(sucursales_latitud AS DOUBLE) AS latitude,
                        TRY_CAST(sucursales_longitud AS DOUBLE) AS longitude
                    FROM read_csv('{sucursales_csv}', delim='|', header=True, all_varchar=True, ignore_errors=True)
                    {region_filter}
                    """

                stores_rows = con.execute(store_query).fetchall()

                if not stores_rows:
                    # No stores in this region for this chain, skip products
                    continue

                processed_chains_count += 1
                chain_stores: List[Store] = []
                for s_row in stores_rows:
                    (
                        _,
                        _,
                        _,
                        comp_id,
                        c_name,
                        s_name,
                        city,
                        addr,
                        lat,
                        lon,
                    ) = s_row
                    comp_id_str = str(comp_id)
                    city_str = str(city) if city else "General"
                    store_obj = Store(
                        id=comp_id_str,
                        chain_name=str(c_name),
                        store_name=str(s_name),
                        city=city_str,
                        address=str(addr) if addr else None,
                        latitude=float(lat) if lat is not None else None,
                        longitude=float(lon) if lon is not None else None,
                    )
                    chain_stores.append(store_obj)
                    store_city_map[comp_id_str] = city_str

                all_stores.extend(chain_stores)

                # Register temp table of chain stores in DuckDB for filtering prices
                con.execute("DROP TABLE IF EXISTS current_chain_stores;")
                con.execute(
                    """
                    CREATE TEMP TABLE current_chain_stores (
                        id_comercio VARCHAR,
                        id_bandera VARCHAR,
                        id_sucursal VARCHAR,
                        composite_id VARCHAR
                    );
                    """
                )
                for s_row in stores_rows:
                    ic, ib, isuc, comp_id = s_row[0], s_row[1], s_row[2], s_row[3]
                    con.execute(
                        f"INSERT INTO current_chain_stores VALUES ('{ic}', '{ib}', '{isuc}', '{comp_id}');"
                    )

                # 3. Extract productos.csv and join with chain stores
                productos_csv = self._sepa_dataset.extract_member(
                    chain_archive, "productos.csv", chain_temp
                )

                price_query = f"""
                SELECT 
                    CAST(p.id_producto AS VARCHAR) AS ean,
                    p.productos_descripcion AS name,
                    p.productos_marca AS brand,
                    'Almacén' AS category,
                    cs.composite_id AS store_id,
                    ROUND(TRY_CAST(p.productos_precio_lista AS DOUBLE)) AS price
                FROM read_csv('{productos_csv}', delim='|', header=True, all_varchar=True, ignore_errors=True) p
                INNER JOIN current_chain_stores cs
                   ON CAST(p.id_comercio AS VARCHAR) = cs.id_comercio
                  AND CAST(p.id_bandera AS VARCHAR) = cs.id_bandera
                  AND CAST(p.id_sucursal AS VARCHAR) = cs.id_sucursal
                WHERE TRY_CAST(p.productos_precio_lista AS DOUBLE) IS NOT NULL
                  AND TRY_CAST(p.productos_precio_lista AS DOUBLE) > 0
                """
                prices_rows = con.execute(price_query).fetchall()

                seen_chain_prices: Set[Tuple[str, str]] = set()

                for p_row in prices_rows:
                    ean, name, brand, category, store_id, price_val = p_row
                    ean_str = str(ean)
                    store_id_str = str(store_id)
                    price_int = int(price_val)

                    # Deduplicate prices within same chain run
                    price_key = (ean_str, store_id_str)
                    if price_key in seen_chain_prices:
                        continue
                    seen_chain_prices.add(price_key)

                    if ean_str not in all_products_dict:
                        all_products_dict[ean_str] = Product(
                            ean=ean_str,
                            name=str(name) if name else f"Producto {ean_str}",
                            brand=str(brand) if brand else None,
                            category=str(category) if category else "Almacén",
                        )

                    all_prices.append(
                        DailyPrice(
                            price_date=process_date,
                            ean=ean_str,
                            store_id=store_id_str,
                            price=price_int,
                        )
                    )

                    city = store_city_map.get(store_id_str, "General")
                    metric_key = (ean_str, city)
                    if metric_key not in city_prices_map:
                        city_prices_map[metric_key] = []
                    city_prices_map[metric_key].append(price_int)

                self._logger.info(
                    f"Processed chain archive: {chain_archive.name}",
                    extra={
                        "chain_archive": chain_archive.name,
                        "stores_found": len(chain_stores),
                        "prices_found": len(seen_chain_prices),
                    },
                )

            except (SepaArchiveError, FileNotFoundError) as exc:
                self._logger.warning(
                    f"Skipping chain archive due to extraction error: {chain_archive}. Error: {exc}"
                )
            finally:
                if chain_temp.exists():
                    shutil.rmtree(chain_temp, ignore_errors=True)

        # 4. Save into Database using SQLAlchemy repositories
        all_products = list(all_products_dict.values())

        with Session(engine) as session:
            cat_repo = SqlAlchemyCatalogRepository(session)
            price_repo = SqlAlchemyPriceRepository(session)

            # Idempotent cleanup for process_date
            price_repo.delete_prices_for_date(process_date)
            price_repo.delete_metrics_for_date(process_date)

            cat_repo.save_stores(all_stores, batch_size=self._batch_size)
            cat_repo.save_products(all_products, batch_size=self._batch_size)
            price_repo.save_prices(all_prices, batch_size=self._batch_size)

            # Compute and save Reference Price Metrics
            metric_entities: List[DailyProductMetrics] = []
            for (ean, city), p_list in city_prices_map.items():
                m = PriceMetricsCalculator.calculate_metrics(
                    metric_date=process_date,
                    ean=ean,
                    city=city,
                    prices=p_list,
                )
                metric_entities.append(m)

            price_repo.save_metrics(metric_entities, batch_size=self._batch_size)

            # Rebuild FTS5 table
            session.execute(
                text(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
                        ean UNINDEXED,
                        name,
                        brand,
                        category
                    );
                    """
                )
            )
            session.execute(text("DELETE FROM products_fts;"))
            for p in all_products:
                session.execute(
                    text(
                        """
                        INSERT INTO products_fts(ean, name, brand, category)
                        VALUES (:ean, :name, :brand, :category);
                        """
                    ),
                    {
                        "ean": p.ean,
                        "name": p.name,
                        "brand": p.brand or "",
                        "category": p.category or "",
                    },
                )
            session.commit()

        self._logger.info(
            "ETL processing completed successfully.",
            extra={
                "region": self._target_region,
                "date": str(process_date),
                "chains_count": processed_chains_count,
                "stores_count": len(all_stores),
                "products_count": len(all_products),
                "prices_count": len(all_prices),
                "metrics_count": len(metric_entities),
            },
        )
