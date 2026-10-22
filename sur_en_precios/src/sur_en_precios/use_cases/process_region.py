"""Regional ETL Use Case: Processes daily SEPA feeds and enriches public.sqlite."""

from __future__ import annotations

import csv
import logging
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, joinedload

from sur_en_precios.adapters.database.repositories import (
    SqlAlchemyCatalogRepository,
    SqlAlchemyPriceRepository,
)
from sur_en_precios.adapters.database.seeder import (
    DEFAULT_HERMES_DB_PATH,
    seed_master_catalog,
)
from sur_en_precios.adapters.sepa_archive import SepaArchiveError, ZipSepaDatasetAdapter
from sur_en_precios.domain.cleaner.article_cleaner import ArticleCleaner
from sur_en_precios.domain.models_public import (
    Article,
    Category,
    DailyPrice,
    DailyProductMetric,
    PointOfSale,
    PublicBase,
    UnreviewedArticle,
)
from sur_en_precios.domain.normalizers import (
    decode_region_code,
    normalize_branch_name,
    normalize_chain_name,
    normalize_city,
)
from sur_en_precios.domain.ports import SepaDatasetPort
from sur_en_precios.domain.services import PriceMetricsCalculator
from sur_en_precios.domain.taxonomy.classifier import TaxonomyClassifier


class ProcessAndPublishRegionUseCase:
    """ETL Use Case: Processes raw daily SEPA CSVs, computes Reference Price metrics, and updates public.sqlite."""

    def __init__(
        self,
        target_region: str = "AR-U",
        sepa_dataset_adapter: Optional[SepaDatasetPort] = None,
        batch_size: int = 10_000,
        temp_dir: Optional[Path] = None,
        logger: Optional[logging.Logger] = None,
        master_db_path: Optional[Path] = None,
        window_days: int = 7,
    ):
        self._target_region = target_region
        self._sepa_dataset = sepa_dataset_adapter or ZipSepaDatasetAdapter()
        self._batch_size = batch_size
        self._temp_dir = temp_dir
        self._logger = logger or logging.getLogger("sur_en_precios")
        self._master_db_path = master_db_path or DEFAULT_HERMES_DB_PATH
        self._article_cleaner = ArticleCleaner()
        self._taxonomy_classifier = TaxonomyClassifier()
        self._window_days = window_days

    def _calculate_unit_price(
        self, price: int, pkg_amount: Optional[float], pkg_unit: Optional[str]
    ) -> Optional[float]:
        """Calculates normalized unit price (ARS per kg or liter or unit)."""
        if not pkg_amount or pkg_amount <= 0 or not pkg_unit:
            return None

        unit = pkg_unit.lower()
        if unit in ("ml", "cc"):
            # Normalize to liters
            base_amt = pkg_amount / 1000.0
            return round(price / base_amt, 2)
        elif unit in ("g", "gr"):
            # Normalize to kilograms
            base_amt = pkg_amount / 1000.0
            return round(price / base_amt, 2)
        elif unit in ("l", "lt", "kg", "u", "un"):
            return round(price / pkg_amount, 2)
        return None

    def execute(
        self, raw_date_dir: Path, output_db_path: Path, process_date: date
    ) -> None:
        """Executes ETL data processing with hybrid master catalog lookup and novel product staging."""
        self._logger.info(
            "Starting regional data processing ETL...",
            extra={
                "region": self._target_region,
                "date": str(process_date),
                "raw_dir": str(raw_date_dir),
                "db_path": str(output_db_path),
            },
        )

        try:
            chain_archives = self._sepa_dataset.list_chain_archives(raw_date_dir)
            if not chain_archives:
                raise FileNotFoundError(
                    f"No SEPA chain archives or CSV files found in {raw_date_dir}"
                )

            output_db_path.parent.mkdir(parents=True, exist_ok=True)

            # 1. Hybrid Master Seeding: initialize public.sqlite if new
            engine = create_engine(f"sqlite:///{output_db_path}")
            PublicBase.metadata.create_all(engine)

            with Session(engine) as session:
                has_articles = session.scalar(select(Article.id).limit(1)) is not None
                if not has_articles and self._master_db_path.exists():
                    self._logger.info(
                        "Seeding master catalog from %s", self._master_db_path
                    )
                    seed_master_catalog(output_db_path, self._master_db_path)

            # Load in-memory caches of known articles and categories
            known_articles: Dict[
                str, Tuple[Optional[float], Optional[str], Optional[int]]
            ] = {}
            category_map: Dict[Tuple[str, str], int] = {}

            with Session(engine) as session:
                for a_ean, a_amt, a_unit, a_cat_id in session.execute(
                    select(
                        Article.ean,
                        Article.package_amount,
                        Article.package_unit,
                        Article.category_id,
                    )
                ).all():
                    known_articles[a_ean] = (a_amt, a_unit, a_cat_id)

                for cat in session.execute(
                    select(Category)
                    .where(Category.level == 2)
                    .options(joinedload(Category.parent))
                ).scalars():
                    parent_name = cat.parent.name if cat.parent else "Almacén"
                    category_map[(parent_name, cat.name)] = cat.id

            work_temp_base = (
                self._temp_dir or (output_db_path.parent / "tmp")
            ).resolve()
            work_temp_base.mkdir(parents=True, exist_ok=True)

            all_stores: List[PointOfSale] = []
            new_articles: List[Article] = []
            unreviewed_staging: List[UnreviewedArticle] = []
            all_prices: List[DailyPrice] = []
            store_city_map: Dict[str, str] = {}
            city_prices_map: Dict[Tuple[str, str], List[int]] = {}
            seen_store_codes: Set[str] = set()

            processed_chains_count = 0

            for idx, chain_archive in enumerate(chain_archives):
                chain_temp = work_temp_base / f"chain_{idx}"
                if chain_temp.exists():
                    shutil.rmtree(chain_temp, ignore_errors=True)
                chain_temp.mkdir(parents=True, exist_ok=True)

                try:
                    # 1. Extract sucursales.csv and optional comercio.csv
                    sucursales_csv = self._sepa_dataset.extract_member(
                        chain_archive, "sucursales.csv", chain_temp
                    )

                    comercio_map: Dict[Tuple[str, str], str] = {}
                    try:
                        comercio_csv = self._sepa_dataset.extract_member(
                            chain_archive, "comercio.csv", chain_temp
                        )
                        if comercio_csv.exists():
                            with open(
                                comercio_csv,
                                mode="r",
                                encoding="utf-8-sig",
                                errors="replace",
                            ) as f:
                                reader = csv.DictReader(f, delimiter="|")
                                for row in reader:
                                    ic = (row.get("id_comercio") or "").strip()
                                    ib = (row.get("id_bandera") or "").strip()
                                    bn = (
                                        row.get("comercio_bandera_nombre") or ""
                                    ).strip()
                                    if ic and ib:
                                        comercio_map[(ic, ib)] = bn
                    except (FileNotFoundError, SepaArchiveError):
                        pass

                    # 2. Parse stores filtered by region
                    chain_stores: List[PointOfSale] = []
                    valid_chain_store_ids: Set[Tuple[str, str, str]] = set()

                    with open(
                        sucursales_csv, mode="r", encoding="utf-8-sig", errors="replace"
                    ) as f:
                        reader = csv.DictReader(f, delimiter="|")
                        for row in reader:
                            prov = (
                                (row.get("sucursales_provincia") or "").strip().upper()
                            )
                            if (
                                self._target_region.upper() != "ALL"
                                and prov != self._target_region.upper()
                            ):
                                continue

                            ic = (row.get("id_comercio") or "").strip()
                            ib = (row.get("id_bandera") or "").strip()
                            isuc = (row.get("id_sucursal") or "").strip()
                            if not ic or not ib or not isuc:
                                continue

                            comp_id = f"{ic}-{ib}-{isuc}"
                            valid_chain_store_ids.add((ic, ib, isuc))

                            c_name = comercio_map.get((ic, ib)) or "Supermercado"
                            s_name = row.get("sucursales_nombre") or "Sucursal"
                            city = normalize_city(
                                row.get("sucursales_localidad") or "General"
                            )
                            calle = (row.get("sucursales_calle") or "").strip()
                            num = (row.get("sucursales_numero") or "").strip()
                            addr = f"{calle} {num}".strip() or None

                            try:
                                lat = (
                                    float(row.get("sucursales_latitud", ""))
                                    if row.get("sucursales_latitud")
                                    else None
                                )
                            except ValueError:
                                lat = None

                            try:
                                lon = (
                                    float(row.get("sucursales_longitud", ""))
                                    if row.get("sucursales_longitud")
                                    else None
                                )
                            except ValueError:
                                lon = None

                            reg_code = self._target_region.strip().upper()
                            reg_name = decode_region_code(reg_code)

                            store_obj = PointOfSale(
                                code=comp_id,
                                brand_name=normalize_chain_name(c_name),
                                branch_name=normalize_branch_name(s_name),
                                address=addr,
                                city=city,
                                province=reg_name,
                                province_code=reg_code,
                                latitude=lat,
                                longitude=lon,
                            )

                            if comp_id not in seen_store_codes:
                                seen_store_codes.add(comp_id)
                                chain_stores.append(store_obj)
                            store_city_map[comp_id] = city

                    if not chain_stores and not valid_chain_store_ids:
                        continue

                    processed_chains_count += 1
                    all_stores.extend(chain_stores)

                    # 3. Extract productos.csv
                    productos_csv = self._sepa_dataset.extract_member(
                        chain_archive, "productos.csv", chain_temp
                    )

                    seen_chain_prices: Set[Tuple[str, str]] = set()

                    with open(
                        productos_csv, mode="r", encoding="utf-8-sig", errors="replace"
                    ) as f:
                        reader = csv.DictReader(f, delimiter="|")
                        for row in reader:
                            ic = (row.get("id_comercio") or "").strip()
                            ib = (row.get("id_bandera") or "").strip()
                            isuc = (row.get("id_sucursal") or "").strip()
                            if (ic, ib, isuc) not in valid_chain_store_ids:
                                continue

                            raw_p = row.get("productos_precio_lista") or ""
                            try:
                                price_val = float(raw_p)
                                if price_val <= 0:
                                    continue
                                price_int = round(price_val)
                            except (ValueError, TypeError):
                                continue

                            ean_str = str(row.get("id_producto") or "").strip()
                            if not ean_str:
                                continue

                            store_id_str = f"{ic}-{ib}-{isuc}"

                            price_key = (ean_str, store_id_str)
                            if price_key in seen_chain_prices:
                                continue
                            seen_chain_prices.add(price_key)

                            # Check or clean article
                            clean_pkg_amt: Optional[float] = None
                            clean_pkg_unit: Optional[str] = None

                            if ean_str in known_articles:
                                clean_pkg_amt, clean_pkg_unit, _ = known_articles[
                                    ean_str
                                ]
                            else:
                                # Novel / unseen product: execute Cleaner & Classifier
                                raw_desc = row.get("productos_descripcion", "")
                                raw_brand = row.get("productos_marca", "")
                                raw_pkg = f"{row.get('productos_cantidad_presentacion', '')} {row.get('productos_unidad_medida_presentacion', '')}".strip()

                                cleaned = self._article_cleaner.process(
                                    ean=ean_str,
                                    raw_description=raw_desc,
                                    raw_brand=raw_brand,
                                    raw_package=raw_pkg,
                                )

                                classification = self._taxonomy_classifier.classify(
                                    cleaned
                                )
                                cat_id = category_map.get(
                                    (
                                        classification.department,
                                        classification.subcategory,
                                    )
                                )

                                is_unclassified = (
                                    classification.department == "Almacén"
                                    and classification.subcategory == "Almacén General"
                                )

                                article_obj = Article(
                                    ean=ean_str,
                                    name=cleaned.name,
                                    clean_description=cleaned.clean_description,
                                    raw_description=cleaned.raw_description,
                                    brand_name=cleaned.brand_name,
                                    package=cleaned.package,
                                    package_amount=cleaned.package_amount,
                                    package_unit=cleaned.package_unit,
                                    category_id=cat_id,
                                    is_reviewed=not is_unclassified,
                                )
                                new_articles.append(article_obj)
                                known_articles[ean_str] = (
                                    cleaned.package_amount,
                                    cleaned.package_unit,
                                    cat_id,
                                )
                                clean_pkg_amt = cleaned.package_amount
                                clean_pkg_unit = cleaned.package_unit

                                # Flag unclassified or novel products for review in staging table
                                if is_unclassified:
                                    staging_obj = UnreviewedArticle(
                                        ean=ean_str,
                                        raw_description=raw_desc,
                                        suggested_brand=cleaned.brand_name,
                                        suggested_package=cleaned.package,
                                        suggested_category_id=cat_id,
                                        reason="Unclassified SEPA product",
                                    )
                                    unreviewed_staging.append(staging_obj)

                            unit_price = self._calculate_unit_price(
                                price_int, clean_pkg_amt, clean_pkg_unit
                            )

                            all_prices.append(
                                DailyPrice(
                                    date=process_date,
                                    ean=ean_str,
                                    store_code=store_id_str,
                                    price=price_int,
                                    unit_price=unit_price,
                                )
                            )

                            city = store_city_map.get(store_id_str, "General")
                            metric_key = (ean_str, city)
                            if metric_key not in city_prices_map:
                                city_prices_map[metric_key] = []
                            city_prices_map[metric_key].append(price_int)

                    self._logger.info(
                        "Processed chain archive: %s (stores=%d, prices=%d)",
                        chain_archive.name,
                        len(chain_stores),
                        len(seen_chain_prices),
                    )

                except (SepaArchiveError, FileNotFoundError) as exc:
                    self._logger.warning(
                        "Skipping chain archive due to error: %s (%s)",
                        chain_archive,
                        exc,
                    )
                finally:
                    if chain_temp.exists():
                        shutil.rmtree(chain_temp, ignore_errors=True)

            # 4. Save into Database using SQLAlchemy repositories
            if not all_stores:
                raise ValueError(
                    f"No stores found in harvested data for region {self._target_region} on {process_date}."
                )
            if not all_prices:
                raise ValueError(
                    f"No prices found in harvested data for region {self._target_region} on {process_date}."
                )

            cutoff_date = process_date - timedelta(days=self._window_days - 1)
            with Session(engine) as session:
                cat_repo = SqlAlchemyCatalogRepository(session)
                price_repo = SqlAlchemyPriceRepository(session)

                # 1. Purge prices older than window_days (7-day window)
                purged_stale = price_repo.delete_prices_before_date(cutoff_date)
                if purged_stale > 0:
                    self._logger.info(
                        "Purged %d stale prices older than %s (%d-day window)",
                        purged_stale,
                        cutoff_date,
                        self._window_days,
                    )

                # 2. Idempotent cleanup for process_date
                price_repo.delete_prices_for_date(process_date)
                price_repo.delete_metrics_for_date(process_date)

                # 3. Save stores and articles
                cat_repo.save_stores(all_stores, batch_size=self._batch_size)
                if new_articles:
                    cat_repo.save_articles(new_articles, batch_size=self._batch_size)

                if unreviewed_staging:
                    unique_staging = {s.ean: s for s in unreviewed_staging}.values()
                    for s in unique_staging:
                        stmt = (
                            sqlite_insert(UnreviewedArticle)
                            .values(
                                [
                                    {
                                        "ean": s.ean,
                                        "raw_description": s.raw_description,
                                        "suggested_brand": s.suggested_brand,
                                        "suggested_package": s.suggested_package,
                                        "suggested_category_id": s.suggested_category_id,
                                        "reason": s.reason,
                                    }
                                ]
                            )
                            .on_conflict_do_nothing(index_elements=["ean"])
                        )
                        session.execute(stmt)
                    session.commit()

                # 4. Save new prices for process_date
                price_repo.save_prices(all_prices, batch_size=self._batch_size)

                # 5. Deduplicate across 7-day window: retain only the latest price observation per (ean, store_code)
                deduped = price_repo.deduplicate_prices_keep_latest()
                if deduped > 0:
                    self._logger.info(
                        "Deduplicated %d older prices superseded by %s prices",
                        deduped,
                        process_date,
                    )

                # 6. Recompute Reference Price Metrics across all active stores in the 7-day window
                price_repo.delete_metrics_before_date(process_date)
                active_city_prices = price_repo.get_active_city_prices()

                metric_entities: List[DailyProductMetric] = []
                for (ean, city), p_list in active_city_prices.items():
                    m = PriceMetricsCalculator.calculate_metrics(
                        metric_date=process_date,
                        ean=ean,
                        city=city,
                        prices=p_list,
                    )
                    metric_entities.append(m)

                price_repo.save_metrics(metric_entities, batch_size=self._batch_size)

            # 7. Physical SQLite VACUUM to reclaim unused disk pages
            try:
                with engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT"
                ) as conn:
                    conn.execute(text("VACUUM"))
                self._logger.info(
                    "Successfully executed SQLite VACUUM on %s", output_db_path
                )
            except Exception as vac_err:
                self._logger.warning("SQLite VACUUM skipped or failed: %s", vac_err)

            self._logger.info(
                "Regional ETL completed: %s stores, %s new articles, %s unreviewed, %s prices",
                len(all_stores),
                len(new_articles),
                len(unreviewed_staging),
                len(all_prices),
            )

        except Exception as exc:
            self._logger.error("Regional ETL execution failed: %s", exc)
            raise
