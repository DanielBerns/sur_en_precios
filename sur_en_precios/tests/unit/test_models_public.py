"""Unit tests for refactored SQLAlchemy 2.0 schema in ``sur_en_precios.domain.models_public``.

Scope: ORM models in ``models_public`` (Category, Brand, Tag, Article, PointOfSale,
DailyPrice, DailyProductMetric, UnreviewedArticle) and backward compatibility wrappers.
Every test runs against a fresh in-memory SQLite database with foreign-key enforcement enabled.
"""

import datetime as dt
from typing import Any, Iterator

import pytest
from sqlalchemy import Engine, create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, configure_mappers

from sur_en_precios.domain.models_public import (
    Article,
    ArticleBrand,
    ArticleCard,
    ArticleCategory,
    ArticleDescription,
    ArticleMetric,
    ArticleNumber,
    Branch,
    Brand,
    Business,
    Category,
    City,
    DailyPrice,
    DailyProductMetric,
    Flag,
    Place,
    PointOfSale,
    Price,
    PublicBase,
    State,
    Store,
    Tag,
    Timestamp,
    UnreviewedArticle,
)


@pytest.fixture()
def engine() -> Iterator[Engine]:
    eng = create_engine("sqlite:///:memory:")

    @event.listens_for(eng, "connect")
    def _enable_fk(dbapi_conn: Any, _record: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    PublicBase.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    with Session(engine) as s:
        yield s


# --------------------------------------------------------------------------- #
# Schema registration & configuration
# --------------------------------------------------------------------------- #


def test_mappers_configure_without_errors() -> None:
    configure_mappers()


def test_all_expected_tables_are_registered() -> None:
    assert set(PublicBase.metadata.tables) == {
        "categories",
        "brands",
        "tags",
        "article_tags",
        "articles",
        "points_of_sale",
        "daily_prices",
        "daily_product_metrics",
        "unreviewed_articles",
    }


def test_create_all_builds_every_table(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) == set(PublicBase.metadata.tables)


# --------------------------------------------------------------------------- #
# Category & Taxonomy tests
# --------------------------------------------------------------------------- #


def test_category_hierarchy_parent_children(session: Session) -> None:
    dept = Category(name="Almacén", slug="almacen", level=1)
    session.add(dept)
    session.flush()

    sub1 = Category(name="Aceites", slug="aceites", level=2, parent=dept)
    sub2 = Category(name="Arroz", slug="arroz", level=2, parent=dept)
    session.add_all([sub1, sub2])
    session.commit()

    reloaded_dept = session.scalar(select(Category).where(Category.id == dept.id))
    assert reloaded_dept is not None
    assert len(reloaded_dept.children) == 2
    assert sub1.full_path == "Almacén > Aceites"
    assert dept.full_path == "Almacén"


def test_category_slug_and_content_compat(session: Session) -> None:
    cat = Category(content="Bebidas con Alcohol")
    assert cat.name == "Bebidas con Alcohol"
    assert cat.content == "Bebidas con Alcohol"
    assert cat.slug == "bebidas-con-alcohol"


# --------------------------------------------------------------------------- #
# Brand & Tag tests
# --------------------------------------------------------------------------- #


def test_brand_uniqueness(session: Session) -> None:
    b1 = Brand(name="La Serenísima", slug="la-serenisima")
    session.add(b1)
    session.commit()

    b2 = Brand(name="La Serenísima", slug="la-serenisima")
    session.add(b2)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_article_tags_many_to_many(session: Session) -> None:
    tag1 = Tag(name="sin-tacc", slug="sin-tacc")
    tag2 = Tag(name="vegano", slug="vegano")
    session.add_all([tag1, tag2])
    session.flush()

    article = Article(
        ean="779001",
        name="Galletitas de Arroz",
        clean_description="Galletitas de Arroz",
    )
    article.tags.extend([tag1, tag2])
    session.add(article)
    session.commit()

    loaded = session.scalar(select(Article).where(Article.ean == "779001"))
    assert loaded is not None
    assert len(loaded.tags) == 2
    tag_names = {t.name for t in loaded.tags}
    assert tag_names == {"sin-tacc", "vegano"}


# --------------------------------------------------------------------------- #
# PointOfSale (Store) tests
# --------------------------------------------------------------------------- #


def test_point_of_sale_properties_and_compat(session: Session) -> None:
    pos = PointOfSale(
        code="1-1-100",
        business_name="Carrefour SA",
        brand_name="Carrefour Hiper",
        branch_name="Sucursal Centro",
        city="Bahía Blanca",
        province="Buenos Aires",
        province_code="AR-B",
        latitude=-38.71,
        longitude=-62.26,
    )
    session.add(pos)
    session.commit()

    loaded = session.scalar(select(PointOfSale).where(PointOfSale.code == "1-1-100"))
    assert loaded is not None
    assert loaded.chain_name == "Carrefour Hiper"
    assert loaded.store_name == "Sucursal Centro"
    assert loaded.city == "Bahía Blanca"
    assert loaded.province == "Buenos Aires"
    assert loaded.latitude == -38.71


def test_point_of_sale_legacy_kwargs(session: Session) -> None:
    store = Store(
        code="S100",
        flag=Flag(flag="Vea"),
        branch=Branch(branch="Sucursal 1"),
        business=Business(business="Cencosud SA"),
        place=Place(address="San Martín 200", city=City(name="Trelew")),
    )
    session.add(store)
    session.commit()

    assert store.chain_name == "Vea"
    assert store.store_name == "Sucursal 1"
    assert store.city == "Trelew"
    assert store.address == "San Martín 200"


# --------------------------------------------------------------------------- #
# DailyPrice & DailyProductMetric tests
# --------------------------------------------------------------------------- #


def test_daily_price_creation_and_cascade(session: Session) -> None:
    pos = PointOfSale(code="S01", brand_name="Vea", branch_name="Centro")
    art = Article(
        ean="779001",
        name="Aceite 900ml",
        clean_description="Aceite 900ml",
        package_amount=900.0,
        package_unit="ml",
    )
    session.add_all([pos, art])
    session.commit()

    p = DailyPrice(
        date=dt.date(2026, 10, 1),
        ean="779001",
        store_code="S01",
        price=1800,
        unit_price=2000.0,
    )
    session.add(p)
    session.commit()

    loaded_p = session.scalar(
        select(DailyPrice).where(
            DailyPrice.ean == "779001", DailyPrice.store_code == "S01"
        )
    )
    assert loaded_p is not None
    assert loaded_p.price == 1800
    assert loaded_p.unit_price == 2000.0

    # Delete article should cascade delete prices
    session.delete(art)
    session.commit()

    assert (
        session.scalar(
            select(DailyPrice).where(
                DailyPrice.ean == "779001", DailyPrice.store_code == "S01"
            )
        )
        is None
    )


def test_daily_product_metric_persists_and_cascades(session: Session) -> None:
    art = Article(
        ean="779002",
        name="Leche 1L",
        clean_description="Leche 1L",
    )
    session.add(art)
    session.commit()

    metric = DailyProductMetric(
        date=dt.date(2026, 10, 1),
        ean="779002",
        city="Bahía Blanca",
        min_price=1000,
        max_price=1300,
        median_price=1150,
        geo_mean_price=1140,
        price_dispersion=0.08,
    )
    session.add(metric)
    session.commit()

    loaded_m = session.scalar(
        select(DailyProductMetric).where(
            DailyProductMetric.ean == "779002",
            DailyProductMetric.city == "Bahía Blanca",
        )
    )
    assert loaded_m is not None
    assert loaded_m.geo_mean_price == 1140
    assert loaded_m.price_dispersion == 0.08

    # Delete article cascades to metric
    session.delete(art)
    session.commit()

    assert (
        session.scalar(
            select(DailyProductMetric).where(
                DailyProductMetric.ean == "779002",
                DailyProductMetric.city == "Bahía Blanca",
            )
        )
        is None
    )


def test_unreviewed_article_staging(session: Session) -> None:
    unreviewed = UnreviewedArticle(
        ean="779999",
        raw_description="PROD NOVEDOSO EXTRAÑO 250G",
        suggested_brand="Marca Nueva",
        suggested_package="250g",
        reason="Unclassified SEPA product",
    )
    session.add(unreviewed)
    session.commit()

    loaded = session.scalar(
        select(UnreviewedArticle).where(UnreviewedArticle.ean == "779999")
    )
    assert loaded is not None
    assert loaded.ean == "779999"
    assert loaded.reason == "Unclassified SEPA product"
