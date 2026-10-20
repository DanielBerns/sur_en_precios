"""Unit tests for master catalog database seeder."""

import sqlite3
import tempfile
from pathlib import Path

from sur_en_precios.adapters.database.seeder import (
    DEFAULT_HERMES_DB_PATH,
    seed_master_catalog,
)


def test_seed_master_catalog() -> None:
    if not DEFAULT_HERMES_DB_PATH.exists():
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        target_db = Path(tmpdir) / "test_public.sqlite"
        counts = seed_master_catalog(target_db, source_hermes_db=DEFAULT_HERMES_DB_PATH)

        assert counts["categories"] == 81
        assert counts["brands"] > 4000
        assert counts["articles"] > 50000
        assert counts["points_of_sale"] > 4000

        # Verify SQLite data directly
        with sqlite3.connect(str(target_db)) as con:
            cur = con.cursor()
            article_sample = cur.execute(
                "SELECT ean, name, clean_description, brand_name, package, package_amount, package_unit, is_reviewed FROM articles LIMIT 1"
            ).fetchone()
            assert article_sample is not None
            assert len(article_sample[0]) > 0
            assert article_sample[7] == 1  # is_reviewed is True
