"""ORM models for the public price database (``public.sqlite``)."""

import datetime as dt
from typing import List, Optional

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class PublicBase(DeclarativeBase):
    """Declarative Base for public.sqlite price database."""

    pass


# --- Store Location Entities ---


class State(PublicBase):
    __tablename__ = "states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(
        String(8), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    cities: Mapped[List["City"]] = relationship(
        back_populates="state", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<State {self.name} ({self.code})>"


class City(PublicBase):
    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("name", "state_id", name="uq_city_name_state"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    state_id: Mapped[int] = mapped_column(
        ForeignKey("states.id"), nullable=False, index=True
    )

    state: Mapped["State"] = relationship(back_populates="cities")
    places: Mapped[List["Place"]] = relationship(
        back_populates="city", cascade="all, delete-orphan"
    )
    metrics: Mapped[List["ArticleMetric"]] = relationship(
        back_populates="city", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<City {self.name}>"


class Place(PublicBase):
    __tablename__ = "places"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    address: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    city_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cities.id"), nullable=True, index=True
    )
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    city: Mapped[Optional["City"]] = relationship(back_populates="places")
    stores: Mapped[List["Store"]] = relationship(back_populates="place")

    def __repr__(self) -> str:
        return f"<Place {self.address}>"


class Flag(PublicBase):
    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flag: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )

    stores: Mapped[List["Store"]] = relationship(back_populates="flag")

    def __repr__(self) -> str:
        return f"<Flag {self.flag}>"


class Business(PublicBase):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )

    stores: Mapped[List["Store"]] = relationship(back_populates="business")

    def __repr__(self) -> str:
        return f"<Business {self.business}>"


class Branch(PublicBase):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )

    stores: Mapped[List["Store"]] = relationship(back_populates="branch")

    def __repr__(self) -> str:
        return f"<Branch {self.branch}>"


class Store(PublicBase):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    flag_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("flags.id"), nullable=True, index=True
    )
    business_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("businesses.id"), nullable=True, index=True
    )
    branch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("branches.id"), nullable=True, index=True
    )
    place_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("places.id"), nullable=True, index=True
    )

    flag: Mapped[Optional["Flag"]] = relationship(back_populates="stores")
    business: Mapped[Optional["Business"]] = relationship(back_populates="stores")
    branch: Mapped[Optional["Branch"]] = relationship(back_populates="stores")
    place: Mapped[Optional["Place"]] = relationship(back_populates="stores")
    prices: Mapped[List["Price"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )

    @property
    def chain_name(self) -> str:
        return self.flag.flag if self.flag else ""

    @property
    def branch_name(self) -> str:
        return self.branch.branch if self.branch else ""

    @property
    def store_name(self) -> str:
        """Alias of :attr:`branch_name`, kept for existing callers."""
        return self.branch_name

    @property
    def city(self) -> str:
        return self.place.city.name if self.place and self.place.city else ""

    def __repr__(self) -> str:
        return f"<Store {self.code}>"


# --- Product Catalog Entities ---


class ArticleBrand(PublicBase):
    __tablename__ = "article_brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )

    cards: Mapped[List["ArticleCard"]] = relationship(back_populates="brand")

    def __repr__(self) -> str:
        return f"<ArticleBrand {self.brand}>"


class ArticleNumber(PublicBase):
    """A product EAN. One EAN may map to several cards (dirty SEPA descriptions)."""

    __tablename__ = "article_numbers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ean: Mapped[str] = mapped_column(
        String(32), unique=True, nullable=False, index=True
    )

    cards: Mapped[List["ArticleCard"]] = relationship(
        back_populates="article_number", cascade="all, delete-orphan"
    )
    prices: Mapped[List["Price"]] = relationship(
        back_populates="article_number", cascade="all, delete-orphan"
    )
    metrics: Mapped[List["ArticleMetric"]] = relationship(
        back_populates="article_number", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ArticleNumber {self.ean}>"


class ArticleCategory(PublicBase):
    __tablename__ = "article_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )

    cards: Mapped[List["ArticleCard"]] = relationship(back_populates="category")

    def __repr__(self) -> str:
        return f"<ArticleCategory {self.content}>"


class ArticleDescription(PublicBase):
    __tablename__ = "article_descriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)

    cards: Mapped[List["ArticleCard"]] = relationship(back_populates="description")

    def __repr__(self) -> str:
        return f"<ArticleDescription {self.content}>"


class ArticleCard(PublicBase):
    """One observed (EAN, description) variant, with its brand and category."""

    __tablename__ = "article_cards"
    __table_args__ = (
        UniqueConstraint(
            "article_number_id",
            "description_id",
            name="uq_article_card_number_description",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_number_id: Mapped[int] = mapped_column(
        ForeignKey("article_numbers.id"), nullable=False, index=True
    )
    description_id: Mapped[int] = mapped_column(
        ForeignKey("article_descriptions.id"), nullable=False, index=True
    )
    brand_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("article_brands.id"), nullable=True, index=True
    )
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("article_categories.id"), nullable=True, index=True
    )

    article_number: Mapped["ArticleNumber"] = relationship(back_populates="cards")
    description: Mapped["ArticleDescription"] = relationship(back_populates="cards")
    brand: Mapped[Optional["ArticleBrand"]] = relationship(back_populates="cards")
    category: Mapped[Optional["ArticleCategory"]] = relationship(back_populates="cards")

    @property
    def ean(self) -> str:
        return self.article_number.ean if self.article_number else ""

    @property
    def name(self) -> str:
        return self.description.content if self.description else ""

    @property
    def brand_name(self) -> str:
        return self.brand.brand if self.brand else ""

    @property
    def category_name(self) -> str:
        return self.category.content if self.category else ""

    def __repr__(self) -> str:
        return f"<ArticleCard {self.ean} {self.name}>"


# --- Price & Metric Entities ---


class Timestamp(PublicBase):
    __tablename__ = "timestamps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    value: Mapped[dt.date] = mapped_column(
        Date, unique=True, nullable=False, index=True
    )

    prices: Mapped[List["Price"]] = relationship(
        back_populates="timestamp", cascade="all, delete-orphan"
    )
    metrics: Mapped[List["ArticleMetric"]] = relationship(
        back_populates="timestamp", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Timestamp {self.value.isoformat()}>"

    @classmethod
    def from_string(cls, string: str) -> "Timestamp":
        """Parse ``YYYY-MM-DD[...]``, ``YYYYMMDDHHMMSS[...]`` or ``YYYYMMDD``.

        Raises:
            ValueError: if the string matches none of the supported formats.
        """
        if "-" in string[:10]:
            value = dt.datetime.strptime(string[:10], "%Y-%m-%d").date()
        elif len(string) >= 14:
            value = dt.datetime.strptime(string[:14], "%Y%m%d%H%M%S").date()
        elif len(string) == 8:
            value = dt.datetime.strptime(string, "%Y%m%d").date()
        else:
            raise ValueError(f"Unrecognised timestamp format: {string!r}")
        return cls(value=value)


class Price(PublicBase):
    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint(
            "timestamp_id",
            "store_id",
            "article_number_id",
            name="uq_price_timestamp_store_article_number",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amount: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )  # Integer Pesos (ARS)
    timestamp_id: Mapped[int] = mapped_column(
        ForeignKey("timestamps.id"), nullable=False, index=True
    )
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id"), nullable=False, index=True
    )
    article_number_id: Mapped[int] = mapped_column(
        ForeignKey("article_numbers.id"), nullable=False, index=True
    )

    timestamp: Mapped["Timestamp"] = relationship(back_populates="prices")
    store: Mapped["Store"] = relationship(back_populates="prices")
    article_number: Mapped["ArticleNumber"] = relationship(back_populates="prices")

    @property
    def store_code(self) -> str:
        return self.store.code if self.store else ""

    @property
    def ean(self) -> str:
        return self.article_number.ean if self.article_number else ""

    @property
    def price(self) -> int:
        return self.amount

    def __repr__(self) -> str:
        return f"<Price {self.store_code} {self.ean} {self.amount}>"


class ArticleMetric(PublicBase):
    __tablename__ = "article_metrics"

    timestamp_id: Mapped[int] = mapped_column(
        ForeignKey("timestamps.id"), primary_key=True, index=True
    )
    article_number_id: Mapped[int] = mapped_column(
        ForeignKey("article_numbers.id"), primary_key=True, index=True
    )
    city_id: Mapped[int] = mapped_column(
        ForeignKey("cities.id"), primary_key=True, index=True
    )
    min_price: Mapped[Optional[int]] = mapped_column(Integer)
    max_price: Mapped[Optional[int]] = mapped_column(Integer)
    reference_price: Mapped[Optional[int]] = mapped_column(Integer)
    price_dispersion: Mapped[Optional[float]] = mapped_column(Float)

    timestamp: Mapped["Timestamp"] = relationship(back_populates="metrics")
    article_number: Mapped["ArticleNumber"] = relationship(back_populates="metrics")
    city: Mapped["City"] = relationship(back_populates="metrics")

    @property
    def ean(self) -> str:
        return self.article_number.ean if self.article_number else ""

    @property
    def date(self) -> Optional[dt.date]:
        return self.timestamp.value if self.timestamp else None

    @property
    def city_name(self) -> str:
        return self.city.name if self.city else ""

    def __repr__(self) -> str:
        return f"<ArticleMetric {self.date} {self.ean} {self.city_name}>"
