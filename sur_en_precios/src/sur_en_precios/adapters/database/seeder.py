"""Database seeder to populate public.sqlite from hermes_clean.db master catalog."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine

from sur_en_precios.domain.models_public import PublicBase

logger = logging.getLogger(__name__)

DEFAULT_HERMES_DB_PATH = Path(
    "/home/dberns/Projects/github/DanielBerns/hermes_reborn/hermes_clean.db"
)


def seed_master_catalog(
    target_db_path: Path | str,
    source_hermes_db: Path | str = DEFAULT_HERMES_DB_PATH,
    force_recreate: bool = False,
) -> dict[str, int]:
    """Seed the target database with master catalog data from hermes_clean.db.

    Transfers:
      - categories (12 departments + 81 subcategories)
      - brands (~4,083 standardized brands)
      - tags (~29,576 facet keywords)
      - articles (~50,230 cleaned retail products)
      - article_tags (~59,014 tag associations)
      - points_of_sale (~4,727 normalized store locations)

    Returns a dict with the row count seeded per table.
    """
    target_path = Path(target_db_path).resolve()
    source_path = Path(source_hermes_db).resolve()

    if not source_path.exists():
        raise FileNotFoundError(f"Source master database not found at {source_path}")

    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize SQLAlchemy tables if not already present
    engine = create_engine(f"sqlite:///{target_path}")
    if force_recreate and target_path.exists():
        target_path.unlink()
    PublicBase.metadata.create_all(engine)
    engine.dispose()

    counts: dict[str, int] = {}

    # Fast SQLite native ATTACH copy
    with sqlite3.connect(str(target_path)) as con:
        cur = con.cursor()
        cur.execute("PRAGMA synchronous = OFF")
        cur.execute("PRAGMA journal_mode = MEMORY")

        cur.execute(f"ATTACH DATABASE '{source_path}' AS hermes")

        # 1. categories
        cur.execute(
            """
            INSERT OR IGNORE INTO categories (id, name, slug, level, description, parent_id)
            SELECT id, name, slug, level, description, parent_id FROM hermes.categories
            """
        )
        counts["categories"] = cur.execute(
            "SELECT count(*) FROM categories"
        ).fetchone()[0]

        # 2. brands
        cur.execute(
            """
            INSERT OR IGNORE INTO brands (id, name, slug)
            SELECT id, name, slug FROM hermes.brands
            """
        )
        counts["brands"] = cur.execute("SELECT count(*) FROM brands").fetchone()[0]

        # 3. tags
        cur.execute(
            """
            INSERT OR IGNORE INTO tags (id, name, slug)
            SELECT id, name, slug FROM hermes.tags
            """
        )
        counts["tags"] = cur.execute("SELECT count(*) FROM tags").fetchone()[0]

        # 4. articles (with is_reviewed = 1)
        cur.execute(
            """
            INSERT OR IGNORE INTO articles (
                id, ean, name, clean_description, raw_description,
                brand_id, brand_name, package, package_amount, package_unit,
                category_id, is_reviewed
            )
            SELECT
                id, ean, name, clean_description, raw_description,
                brand_id, brand_name, package, package_amount, package_unit,
                category_id, 1
            FROM hermes.articles
            """
        )
        counts["articles"] = cur.execute("SELECT count(*) FROM articles").fetchone()[0]

        # 5. article_tags
        cur.execute(
            """
            INSERT OR IGNORE INTO article_tags (article_id, tag_id)
            SELECT article_id, tag_id FROM hermes.article_tags
            """
        )
        counts["article_tags"] = cur.execute(
            "SELECT count(*) FROM article_tags"
        ).fetchone()[0]

        # 6. points_of_sale
        cur.execute(
            """
            INSERT OR IGNORE INTO points_of_sale (
                id, code, sepa_id, comercio_id, bandera_id, sucursal_id,
                business_name, holding_group, brand_name, store_format,
                branch_name, address, city, province, province_code,
                latitude, longitude
            )
            SELECT
                id, code, sepa_id, comercio_id, bandera_id, sucursal_id,
                business_name, holding_group, brand_name, store_format,
                branch_name, address, city, province, province_code,
                latitude, longitude
            FROM hermes.points_of_sale
            """
        )
        counts["points_of_sale"] = cur.execute(
            "SELECT count(*) FROM points_of_sale"
        ).fetchone()[0]

        con.commit()
        cur.execute("DETACH DATABASE hermes")

    logger.info(
        "Master catalog seeded successfully into %s: %s",
        target_path,
        counts,
    )
    return counts
