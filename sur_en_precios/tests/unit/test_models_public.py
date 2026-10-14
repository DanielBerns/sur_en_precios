"""Unit tests for ``sur_en_precios.domain.models_public``.

Scope: only the ORM models in ``models_public``. Every test runs against a fresh
in-memory SQLite database with foreign-key enforcement enabled.
"""

import datetime as dt
from typing import Any, Iterator

import pytest
from sqlalchemy import Engine, UniqueConstraint, create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, configure_mappers

from sur_en_precios.domain.models_public import (
    ArticleBrand,
    ArticleCard,
    ArticleCategory,
    ArticleDescription,
    ArticleMetric,
    ArticleNumber,
    Branch,
    Business,
    City,
    Flag,
    Place,
    Price,
    PublicBase,
    State,
    Store,
    Timestamp,
)

# --------------------------------------------------------------------------- #
# Fixtures & builders
# --------------------------------------------------------------------------- #


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


def _get_or_make_state(session: Session, code: str = "AR-B") -> State:
    state = session.scalar(select(State).where(State.code == code))
    return state or State(code=code, name="Buenos Aires")


def _make_store(
    session: Session,
    code: str = "10-1-1",
    city_name: str = "Bahía Blanca",
    state_code: str = "AR-B",
) -> Store:
    city = City(name=city_name, state=_get_or_make_state(session, state_code))
    place = Place(address="Av. Alem 123", city=city, latitude=-38.7, longitude=-62.3)
    store = Store(
        code=code,
        flag=Flag(flag=f"Flag {code}"),
        business=Business(business=f"Business {code}"),
        branch=Branch(branch=f"Branch {code}"),
        place=place,
    )
    session.add(store)
    session.flush()
    return store


def _make_card(
    session: Session,
    ean: str = "7790001000011",
    description: str | None = None,
) -> ArticleCard:
    number = session.scalar(select(ArticleNumber).where(ArticleNumber.ean == ean))
    card = ArticleCard(
        brand=ArticleBrand(brand=f"Brand {ean} {description or ''}"),
        category=ArticleCategory(content=f"Category {ean} {description or ''}"),
        description=ArticleDescription(content=description or f"Leche entera 1L {ean}"),
        article_number=number or ArticleNumber(ean=ean),
    )
    session.add(card)
    session.flush()
    return card


def _unique_constraints(table: Any) -> dict[str, set[str]]:
    return {
        c.name: {col.name for col in c.columns}
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    }


# --------------------------------------------------------------------------- #
# Module / schema shape
# --------------------------------------------------------------------------- #


def test_mappers_configure_without_errors() -> None:
    configure_mappers()


def test_all_expected_tables_are_registered() -> None:
    assert set(PublicBase.metadata.tables) == {
        "states",
        "cities",
        "places",
        "flags",
        "businesses",
        "branches",
        "stores",
        "article_brands",
        "article_numbers",
        "article_categories",
        "article_descriptions",
        "article_cards",
        "timestamps",
        "prices",
        "article_metrics",
    }


def test_create_all_builds_every_table(engine: Engine) -> None:
    assert set(inspect(engine).get_table_names()) == set(PublicBase.metadata.tables)


def test_no_point_of_sale_naming_left() -> None:
    for table in PublicBase.metadata.tables.values():
        assert "point_of_sale" not in table.name
        for col in table.columns:
            assert "point_of_sale" not in col.name
        for name in _unique_constraints(table):
            assert "pos" not in name.split("_")
    for mapper in PublicBase.registry.mappers:
        assert "point_of_sale" not in mapper.relationships.keys()


def test_article_category_content_has_explicit_length() -> None:
    # Guards against ``String[128]`` (subscript) silently producing ``String()``.
    assert ArticleCategory.__table__.c.content.type.length == 128


def test_city_state_id_is_not_nullable() -> None:
    col = City.__table__.c.state_id
    assert not col.nullable
    assert {fk.target_fullname for fk in col.foreign_keys} == {"states.id"}


def test_city_unique_constraint_is_name_and_state() -> None:
    assert not City.__table__.c.name.unique
    assert _unique_constraints(City.__table__)["uq_city_name_state"] == {
        "name",
        "state_id",
    }


def test_price_store_id_is_an_integer_fk_column() -> None:
    col = Price.__table__.c.store_id
    assert not col.nullable
    assert {fk.target_fullname for fk in col.foreign_keys} == {"stores.id"}
    # Must not be shadowed by a Python property on the class.
    assert "store_id" in inspect(Price).columns


def test_price_unique_constraint_columns() -> None:
    uniques = _unique_constraints(Price.__table__)
    assert uniques["uq_price_timestamp_store_article_number"] == {
        "timestamp_id",
        "store_id",
        "article_number_id",
    }


def test_article_card_unique_constraint_is_number_and_description() -> None:
    assert not ArticleCard.__table__.c.article_number_id.unique
    assert not ArticleCard.__table__.c.description_id.nullable
    uniques = _unique_constraints(ArticleCard.__table__)
    assert uniques["uq_article_card_number_description"] == {
        "article_number_id",
        "description_id",
    }


def test_article_metric_has_composite_primary_key() -> None:
    pk = {c.name for c in ArticleMetric.__table__.primary_key.columns}
    assert pk == {"timestamp_id", "article_number_id", "city_id"}


def test_article_metric_columns() -> None:
    # median_price and pct_change_* were dropped on purpose.
    assert set(ArticleMetric.__table__.c.keys()) == {
        "timestamp_id",
        "article_number_id",
        "city_id",
        "min_price",
        "max_price",
        "reference_price",
        "price_dispersion",
    }


def test_timestamp_value_is_unique_date_column() -> None:
    col = Timestamp.__table__.c.value
    assert col.type.python_type is dt.date
    assert col.unique
    assert not col.nullable


# --------------------------------------------------------------------------- #
# Uniqueness / nullability constraints
# --------------------------------------------------------------------------- #


def test_timestamp_value_is_unique(session: Session) -> None:
    session.add(Timestamp(value=dt.date(2024, 1, 15)))
    session.commit()
    session.add(Timestamp(value=dt.date(2024, 1, 15)))
    with pytest.raises(IntegrityError):
        session.commit()


def test_city_requires_state(session: Session) -> None:
    session.add(City(name="Sin Provincia"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_city_name_unique_per_state_only(session: Session) -> None:
    ba = State(code="AR-B", name="Buenos Aires")
    sj = State(code="AR-J", name="San Juan")
    session.add_all(
        [City(name="San Martín", state=ba), City(name="San Martín", state=sj)]
    )
    session.commit()  # same name, different states: allowed

    session.add(City(name="San Martín", state=ba))
    with pytest.raises(IntegrityError):
        session.commit()


def test_store_code_is_unique(session: Session) -> None:
    session.add(Store(code="X"))
    session.commit()
    session.add(Store(code="X"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_article_number_ean_is_unique(session: Session) -> None:
    session.add(ArticleNumber(ean="1"))
    session.commit()
    session.add(ArticleNumber(ean="1"))
    with pytest.raises(IntegrityError):
        session.commit()


def test_same_ean_may_have_several_descriptions(session: Session) -> None:
    # SEPA data is dirty: one EAN can appear with misspelled/alternative names.
    a = _make_card(session, ean="779", description="Leche entera 1L")
    b = _make_card(session, ean="779", description="Leche entera 1 L")
    session.commit()
    assert a.article_number is b.article_number
    assert {c.name for c in a.article_number.cards} == {
        "Leche entera 1L",
        "Leche entera 1 L",
    }


def test_same_ean_and_description_is_rejected(session: Session) -> None:
    card = _make_card(session, ean="779", description="Leche entera 1L")
    keys = (card.article_number_id, card.description_id)
    session.commit()
    session.expunge_all()

    session.add(ArticleCard(article_number_id=keys[0], description_id=keys[1]))
    with pytest.raises(IntegrityError):
        session.commit()


def test_article_card_requires_description(session: Session) -> None:
    session.add(ArticleCard(article_number=ArticleNumber(ean="1")))
    with pytest.raises(IntegrityError):
        session.commit()


def test_price_unique_per_timestamp_store_article(session: Session) -> None:
    store = _make_store(session)
    number = _make_card(session).article_number
    ts = Timestamp(value=dt.date(2024, 1, 15))
    session.add(Price(amount=1000, timestamp=ts, store=store, article_number=number))
    session.commit()

    session.add(Price(amount=1200, timestamp=ts, store=store, article_number=number))
    with pytest.raises(IntegrityError):
        session.commit()


def test_article_metric_unique_per_primary_key(session: Session) -> None:
    store = _make_store(session)
    number = _make_card(session).article_number
    ts = Timestamp(value=dt.date(2024, 1, 15))
    city = store.place.city
    session.add(ArticleMetric(timestamp=ts, article_number=number, city=city))
    session.commit()
    keys = (ts.id, number.id, city.id)
    session.expunge_all()

    session.add(
        ArticleMetric(timestamp_id=keys[0], article_number_id=keys[1], city_id=keys[2])
    )
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize(
    "model, kwargs",
    [
        (Flag, {"flag": "Coto"}),
        (Business, {"business": "Coto CICSA"}),
        (Branch, {"branch": "Sucursal 1"}),
        (ArticleBrand, {"brand": "La Serenísima"}),
        (ArticleCategory, {"content": "Lácteos"}),
        (ArticleDescription, {"content": "Leche entera 1L"}),
    ],
)
def test_lookup_tables_reject_duplicates(
    session: Session, model: type, kwargs: dict[str, str]
) -> None:
    session.add(model(**kwargs))
    session.commit()
    session.add(model(**kwargs))
    with pytest.raises(IntegrityError):
        session.commit()


def test_price_requires_foreign_keys(session: Session) -> None:
    session.add(Price(amount=100))
    with pytest.raises(IntegrityError):
        session.commit()


# --------------------------------------------------------------------------- #
# Timestamp.from_string
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("20240115103000", dt.date(2024, 1, 15)),
        ("20240115103000_suffix", dt.date(2024, 1, 15)),
        ("20240115", dt.date(2024, 1, 15)),
        ("2024-01-15", dt.date(2024, 1, 15)),
        ("2024-01-15T10:30:00", dt.date(2024, 1, 15)),
        ("2024-01-15 10:30:00", dt.date(2024, 1, 15)),
    ],
)
def test_timestamp_from_string_valid(raw: str, expected: dt.date) -> None:
    ts = Timestamp.from_string(raw)
    assert isinstance(ts, Timestamp)
    assert ts.value == expected


@pytest.mark.parametrize("raw", ["", "abc", "2024/01/15", "2024-13-01", "202401"])
def test_timestamp_from_string_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        Timestamp.from_string(raw)


def test_timestamp_round_trips_as_date(session: Session) -> None:
    session.add(Timestamp.from_string("20240115103000"))
    session.commit()
    session.expunge_all()
    stored = session.scalars(select(Timestamp)).one()
    assert stored.value == dt.date(2024, 1, 15)
    assert not isinstance(stored.value, dt.datetime)


# --------------------------------------------------------------------------- #
# Relationships & back-population
# --------------------------------------------------------------------------- #


def test_location_hierarchy_back_populates(session: Session) -> None:
    store = _make_store(session)
    place = store.place
    city = place.city
    state = city.state
    assert store in place.stores
    assert place in city.places
    assert city in state.cities
    assert store in store.flag.stores
    assert store in store.business.stores
    assert store in store.branch.stores


def test_article_card_back_populates(session: Session) -> None:
    card = _make_card(session)
    assert card in card.article_number.cards
    assert card in card.brand.cards
    assert card in card.category.cards
    assert card in card.description.cards


def test_price_back_populates(session: Session) -> None:
    store = _make_store(session)
    number = _make_card(session).article_number
    ts = Timestamp(value=dt.date(2024, 1, 15))
    price = Price(amount=1500, timestamp=ts, store=store, article_number=number)
    session.add(price)
    session.flush()
    assert price in store.prices
    assert price in ts.prices
    assert price in number.prices
    assert price.store_id == store.id


def test_article_metric_back_populates(session: Session) -> None:
    store = _make_store(session)
    number = _make_card(session).article_number
    ts = Timestamp(value=dt.date(2024, 1, 15))
    city = store.place.city
    metric = ArticleMetric(timestamp=ts, article_number=number, city=city)
    session.add(metric)
    session.flush()
    assert metric in ts.metrics
    assert metric in number.metrics
    assert metric in city.metrics


# --------------------------------------------------------------------------- #
# Cascades
# --------------------------------------------------------------------------- #


def _seed_price_and_metric(session: Session) -> tuple[Store, ArticleNumber, Timestamp]:
    store = _make_store(session)
    number = _make_card(session).article_number
    ts = Timestamp(value=dt.date(2024, 1, 15))
    session.add_all(
        [
            Price(amount=1500, timestamp=ts, store=store, article_number=number),
            ArticleMetric(
                timestamp=ts,
                article_number=number,
                city=store.place.city,
                min_price=1500,
            ),
        ]
    )
    session.commit()
    return store, number, ts


def test_deleting_timestamp_cascades_prices_and_metrics(session: Session) -> None:
    _, _, ts = _seed_price_and_metric(session)
    session.delete(ts)
    session.commit()
    assert session.scalars(select(Price)).all() == []
    assert session.scalars(select(ArticleMetric)).all() == []


def test_deleting_store_cascades_prices_only(session: Session) -> None:
    store, _, _ = _seed_price_and_metric(session)
    session.delete(store)
    session.commit()
    assert session.scalars(select(Price)).all() == []
    assert len(session.scalars(select(ArticleMetric)).all()) == 1


def test_deleting_article_number_cascades_cards_prices_and_metrics(
    session: Session,
) -> None:
    _, number, _ = _seed_price_and_metric(session)
    session.delete(number)
    session.commit()
    assert session.scalars(select(ArticleCard)).all() == []
    assert session.scalars(select(Price)).all() == []
    assert session.scalars(select(ArticleMetric)).all() == []


def test_deleting_city_removes_places_and_metrics_but_keeps_stores(
    session: Session,
) -> None:
    store, _, _ = _seed_price_and_metric(session)
    session.delete(store.place.city)
    session.commit()
    assert session.scalars(select(Place)).all() == []
    assert session.scalars(select(ArticleMetric)).all() == []
    remaining = session.scalars(select(Store)).one()
    assert remaining.place_id is None


def test_deleting_state_cascades_cities(session: Session) -> None:
    store = _make_store(session)
    session.commit()
    session.delete(store.place.city.state)
    session.commit()
    assert session.scalars(select(City)).all() == []


# --------------------------------------------------------------------------- #
# Computed properties
# --------------------------------------------------------------------------- #


def test_store_properties(session: Session) -> None:
    store = _make_store(session, code="S1", city_name="Neuquén")
    assert store.chain_name == "Flag S1"
    assert store.branch_name == "Branch S1"
    assert store.store_name == "Branch S1"
    assert store.city == "Neuquén"


def test_store_properties_default_to_empty_string() -> None:
    store = Store(code="bare")
    assert store.chain_name == ""
    assert store.branch_name == ""
    assert store.store_name == ""
    assert store.city == ""


def test_store_city_empty_when_place_has_no_city() -> None:
    assert Store(code="x", place=Place(address="?")).city == ""


def test_article_card_properties(session: Session) -> None:
    card = _make_card(session, ean="7790001000028")
    assert card.ean == "7790001000028"
    assert card.name == "Leche entera 1L 7790001000028"


def test_article_card_properties_default_to_empty_string() -> None:
    card = ArticleCard()
    assert card.ean == ""
    assert card.name == ""


def test_price_properties(session: Session) -> None:
    store = _make_store(session, code="S9")
    number = _make_card(session, ean="123").article_number
    price = Price(
        amount=2599,
        timestamp=Timestamp(value=dt.date(2024, 1, 15)),
        store=store,
        article_number=number,
    )
    assert price.store_code == "S9"
    assert price.ean == "123"
    assert price.price == 2599


def test_price_properties_without_relations() -> None:
    price = Price(amount=10)
    assert price.store_code == ""
    assert price.ean == ""
    assert price.price == 10


def test_article_metric_properties(session: Session) -> None:
    store = _make_store(session, city_name="Viedma")
    number = _make_card(session, ean="999").article_number
    metric = ArticleMetric(
        timestamp=Timestamp(value=dt.date(2024, 3, 1)),
        article_number=number,
        city=store.place.city,
    )
    assert metric.ean == "999"
    # Regression: ``date`` used to read the non-existent ``timestamp.timestamp``.
    assert metric.date == dt.date(2024, 3, 1)
    assert type(metric.date) is dt.date
    assert metric.city_name == "Viedma"


def test_article_metric_properties_without_relations() -> None:
    metric = ArticleMetric()
    assert metric.ean == ""
    assert metric.date is None
    assert metric.city_name == ""


def test_article_metric_persists_all_values(session: Session) -> None:
    store = _make_store(session)
    number = _make_card(session).article_number
    session.add(
        ArticleMetric(
            timestamp=Timestamp(value=dt.date(2024, 1, 15)),
            article_number=number,
            city=store.place.city,
            min_price=900,
            max_price=1500,
            reference_price=1080,
            price_dispersion=0.12,
        )
    )
    session.commit()
    session.expunge_all()
    m = session.scalars(select(ArticleMetric)).one()
    assert (m.min_price, m.max_price, m.reference_price) == (900, 1500, 1080)
    assert m.price_dispersion == pytest.approx(0.12)
    assert m.date == dt.date(2024, 1, 15)


# --------------------------------------------------------------------------- #
# __repr__
# --------------------------------------------------------------------------- #


def test_reprs_are_informative(session: Session) -> None:
    store = _make_store(session, code="R1", city_name="Rawson")
    card = _make_card(session, ean="555")
    ts = Timestamp(value=dt.date(2024, 1, 15))
    assert repr(store.place.city.state) == "<State Buenos Aires (AR-B)>"
    assert repr(store.place.city) == "<City Rawson>"
    assert repr(store.place) == "<Place Av. Alem 123>"
    assert repr(ts) == "<Timestamp 2024-01-15>"
    assert "R1" in repr(store)
    assert "555" in repr(card.article_number)
    assert "555" in repr(card)
    price = Price(
        amount=10, timestamp=ts, store=store, article_number=card.article_number
    )
    assert "R1" in repr(price) and "555" in repr(price)
