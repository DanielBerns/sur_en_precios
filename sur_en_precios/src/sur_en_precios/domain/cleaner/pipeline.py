"""Data migration and cleaning pipeline from legacy database to clean SQLAlchemy 2.0 schema."""

from __future__ import annotations

import logging
import sqlite3
from typing import Callable, Dict, List, Optional, Set, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from sur_en_precios.domain.cleaner.article_cleaner import ArticleCleaner
from sur_en_precios.domain.cleaner.brand_cleaner import BrandLexicon, clean_brand_name
from sur_en_precios.domain.cleaner.pos_cleaner import clean_point_of_sale_record
from sur_en_precios.domain.cleaner.text_utils import slugify
from sur_en_precios.domain.models_public import (
    Article,
    Brand,
    Category,
    PointOfSale,
    Tag,
)
from sur_en_precios.domain.taxonomy.categories import DEFAULT_TAXONOMY
from sur_en_precios.domain.taxonomy.classifier import TaxonomyClassifier

logger = logging.getLogger(__name__)


def seed_taxonomy(session: Session) -> Dict[Tuple[str, str], Category]:
    """Seed the default Department and Subcategory hierarchy into the database.

    Returns a mapping of (department_name, subcategory_name) -> Subcategory Category model.
    """
    category_map: Dict[Tuple[str, str], Category] = {}

    for dept_def in DEFAULT_TAXONOMY:
        # Check or create department
        stmt = select(Category).where(Category.slug == dept_def.slug)
        dept = session.scalars(stmt).first()
        if not dept:
            dept = Category(
                name=dept_def.name,
                slug=dept_def.slug,
                level=1,
                description=dept_def.description,
            )
            session.add(dept)
            session.flush()

        for sub_def in dept_def.subcategories:
            sub_stmt = select(Category).where(Category.slug == sub_def.slug)
            sub = session.scalars(sub_stmt).first()
            if not sub:
                sub = Category(
                    name=sub_def.name,
                    slug=sub_def.slug,
                    level=2,
                    parent_id=dept.id,
                    description=sub_def.description,
                )
                session.add(sub)
                session.flush()
            category_map[(dept_def.name, sub_def.name)] = sub

    session.commit()
    return category_map


class MigrationPipeline:
    """ETL Pipeline that reads legacy SQLite database, cleans, categorizes, and saves to target DB."""

    def __init__(
        self,
        source_db_path: str,
        target_session: Session,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self.source_db_path = source_db_path
        self.session = target_session
        self.progress_callback = progress_callback

        self.classifier = TaxonomyClassifier()
        self.brand_cache: Dict[str, Brand] = {}
        self.tag_cache: Dict[str, Tag] = {}
        self.category_map: Dict[Tuple[str, str], Category] = {}

    def _get_or_create_brand(self, brand_name: Optional[str]) -> Optional[Brand]:
        if not brand_name:
            return None
        clean_name = clean_brand_name(brand_name)
        if not clean_name:
            return None

        if clean_name in self.brand_cache:
            return self.brand_cache[clean_name]

        slug = slugify(clean_name)
        stmt = select(Brand).where(Brand.slug == slug)
        existing = self.session.scalars(stmt).first()
        if existing:
            self.brand_cache[clean_name] = existing
            return existing

        brand = Brand(name=clean_name, slug=slug)
        self.session.add(brand)
        self.session.flush()
        self.brand_cache[clean_name] = brand
        return brand

    def _get_or_create_tag(self, tag_name: str) -> Tag:
        clean = tag_name.strip().lower()
        if clean in self.tag_cache:
            return self.tag_cache[clean]

        slug = slugify(clean)
        stmt = select(Tag).where(Tag.slug == slug)
        existing = self.session.scalars(stmt).first()
        if existing:
            self.tag_cache[clean] = existing
            return existing

        tag = Tag(name=clean, slug=slug)
        self.session.add(tag)
        self.session.flush()
        self.tag_cache[clean] = tag
        return tag

    def run(self, limit: Optional[int] = None) -> int:
        """Execute the full data cleaning and migration pipeline."""
        logger.info(f"Connecting to source database: {self.source_db_path}")
        source_conn = sqlite3.connect(self.source_db_path)
        source_cur = source_conn.cursor()

        # 1. Seed taxonomy
        self.category_map = seed_taxonomy(self.session)

        # 2. Build BrandLexicon from all brands in legacy DB
        source_cur.execute("SELECT brand FROM article_brands WHERE brand IS NOT NULL;")
        all_brands = [row[0] for row in source_cur.fetchall()]
        lexicon = BrandLexicon(all_brands)
        cleaner = ArticleCleaner(brand_lexicon=lexicon)

        # 3. Query all article cards and their associated data
        query = """
        SELECT 
            c.code AS ean,
            d.description AS raw_description,
            b.brand AS raw_brand,
            p.package AS raw_package,
            GROUP_CONCAT(t.tag, '||') AS raw_tags
        FROM article_cards ac
        JOIN article_codes c ON ac.code_id = c.id
        JOIN article_descriptions d ON ac.description_id = d.id
        JOIN article_brands b ON ac.brand_id = b.id
        JOIN article_packages p ON ac.package_id = p.id
        LEFT JOIN article_cards_and_article_tags act ON ac.id = act.article_card_id
        LEFT JOIN article_tags t ON act.article_tag_id = t.id
        GROUP BY ac.id
        ORDER BY c.code
        """
        if limit:
            query += f" LIMIT {int(limit)}"

        source_cur.execute(query)
        rows = source_cur.fetchall()
        total_rows = len(rows)
        logger.info(f"Loaded {total_rows} article records from source DB.")

        # 4. Group by EAN to deduplicate the ~708 duplicate cards
        articles_by_ean: Dict[str, List[Tuple]] = {}
        for row in rows:
            ean = row[0].strip()
            articles_by_ean.setdefault(ean, []).append(row)

        processed_count = 0
        batch_size = 2000

        for ean, card_group in articles_by_ean.items():
            # Pick best card if duplicate:
            # Prefer card with named brand over 'sin marca', and card with tags
            best_card = card_group[0]
            if len(card_group) > 1:
                for cand in card_group:
                    cand_brand = (cand[2] or "").lower()
                    best_brand = (best_card[2] or "").lower()
                    if "sin marca" in best_brand and "sin marca" not in cand_brand:
                        best_card = cand
                    elif cand[4] and not best_card[4]:
                        best_card = cand

            _, raw_desc, raw_brand, raw_pkg, raw_tags_str = best_card
            raw_tags = raw_tags_str.split("||") if raw_tags_str else []

            # Clean article fields
            cleaned = cleaner.process(
                ean=ean,
                raw_description=raw_desc,
                raw_brand=raw_brand,
                raw_package=raw_pkg,
                raw_tags=raw_tags,
            )

            # Classify article
            classification = self.classifier.classify(cleaned)
            category = self.category_map.get(
                (classification.department, classification.subcategory)
            )

            # Link Brand
            brand_rel = self._get_or_create_brand(cleaned.brand_name)

            # Check if article with this EAN already exists in target DB
            stmt = select(Article).where(Article.ean == cleaned.ean)
            existing_article = self.session.scalars(stmt).first()
            if existing_article:
                continue

            article = Article(
                ean=cleaned.ean,
                name=cleaned.name,
                clean_description=cleaned.clean_description,
                raw_description=cleaned.raw_description,
                brand_id=brand_rel.id if brand_rel else None,
                brand_name=cleaned.brand_name,
                package=cleaned.package,
                package_amount=cleaned.package_amount,
                package_unit=cleaned.package_unit,
                category_id=category.id if category else None,
            )
            self.session.add(article)

            # Link unique tags
            seen_tag_ids: Set[int] = set()
            for t_name in classification.tags:
                tag_model = self._get_or_create_tag(t_name)
                if tag_model.id not in seen_tag_ids:
                    seen_tag_ids.add(tag_model.id)
                    article.tags.append(tag_model)

            processed_count += 1

            if processed_count % batch_size == 0:
                self.session.commit()
                if self.progress_callback:
                    self.progress_callback(processed_count, len(articles_by_ean))

        self.session.commit()
        if self.progress_callback:
            self.progress_callback(processed_count, len(articles_by_ean))

        # 5. Also migrate Points of Sale
        self._migrate_points_of_sale(source_cur)

        source_conn.close()
        logger.info(
            f"Successfully migrated and cleaned {processed_count} unique articles."
        )
        return processed_count

    def _migrate_points_of_sale(self, source_cur: sqlite3.Cursor) -> None:
        """Migrate Points of Sale from source DB to target DB."""
        source_cur.execute("""
        SELECT 
            pos.id,
            pos.code,
            b.business,
            f.flag,
            br.branch,
            p.address,
            c.name AS city,
            s.name AS state
        FROM points_of_sale pos
        LEFT JOIN businesses b ON pos.business_id = b.id
        LEFT JOIN flags f ON pos.flag_id = f.id
        LEFT JOIN branches br ON pos.branch_id = br.id
        LEFT JOIN points_of_sale_and_places pos_p ON pos.id = pos_p.point_of_sale_id
        LEFT JOIN places p ON pos_p.place_id = p.id
        LEFT JOIN cities c ON p.city_id = c.id
        LEFT JOIN states s ON c.state_id = s.id
        GROUP BY pos.id;
        """)
        for row in source_cur.fetchall():
            pos_id, code, business, flag, branch, address, city, state = row
            stmt = select(PointOfSale).where(PointOfSale.code == code)
            if self.session.scalars(stmt).first():
                continue
            cleaned = clean_point_of_sale_record(
                code=code,
                business=business,
                flag=flag,
                branch=branch,
                address=address,
                city=city,
                state=state,
            )
            pos = PointOfSale(
                code=cleaned.code,
                sepa_id=cleaned.sepa_id,
                comercio_id=cleaned.comercio_id,
                bandera_id=cleaned.bandera_id,
                sucursal_id=cleaned.sucursal_id,
                business_name=cleaned.business_name,
                holding_group=cleaned.holding_group,
                brand_name=cleaned.brand_name,
                store_format=cleaned.store_format,
                branch_name=cleaned.branch_name,
                address=cleaned.address,
                city=cleaned.city,
                province=cleaned.province,
                province_code=cleaned.province_code,
                latitude=cleaned.latitude,
                longitude=cleaned.longitude,
            )
            self.session.add(pos)
        self.session.commit()
