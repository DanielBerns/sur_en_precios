from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class PublicBase(DeclarativeBase):
    """Declarative Base for public.sqlite price database."""

    pass


# --- Store Location Entities ---

class State(PublicBase):
    __tablename__ = "states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(8), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    cities: Mapped[List["City"]] = relationship(
        back_populates="state", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<State {self.name} ({self.code})>"


class City(PublicBase):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    state_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("states.id"), nullable=True, index=True
    )

    state: Mapped[Optional["State"]] = relationship(back_populates="cities")
    places: Mapped[List["Place"]] = relationship(
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
    points_of_sale: Mapped[List["PointOfSale"]] = relationship(
        back_populates="place"
    )

    def __repr__(self) -> str:
        return f"<Place {self.address}>"


class Flag(PublicBase):
    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flag: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)

    points_of_sale: Mapped[List["PointOfSale"]] = relationship(back_populates="flag")


class Business(PublicBase):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)

    points_of_sale: Mapped[List["PointOfSale"]] = relationship(back_populates="business")


class Branch(PublicBase):
    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)

    points_of_sale: Mapped[List["PointOfSale"]] = relationship(back_populates="branch")


class PointOfSale(PublicBase):
    __tablename__ = "points_of_sale"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    flag_id: Mapped[Optional[int]] = mapped_column(ForeignKey("flags.id"), nullable=True, index=True)
    business_id: Mapped[Optional[int]] = mapped_column(ForeignKey("businesses.id"), nullable=True, index=True)
    branch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("branches.id"), nullable=True, index=True)
    place_id: Mapped[Optional[int]] = mapped_column(ForeignKey("places.id"), nullable=True, index=True)

    flag: Mapped[Optional["Flag"]] = relationship(back_populates="points_of_sale")
    business: Mapped[Optional["Business"]] = relationship(back_populates="points_of_sale")
    branch: Mapped[Optional["Branch"]] = relationship(back_populates="points_of_sale")
    place: Mapped[Optional["Place"]] = relationship(back_populates="points_of_sale")
    prices: Mapped[List["Price"]] = relationship(
        back_populates="point_of_sale", cascade="all, delete-orphan"
    )

    @property
    def chain_name(self) -> str:
        return self.flag.flag if self.flag else ""

    @property
    def store_name(self) -> str:
        return self.branch.branch if self.branch else ""


# StoreModel alias for backwards compatibility with repository layer
StoreModel = PointOfSale


# --- Product Catalog Entities ---

class ArticleBrand(PublicBase):
    __tablename__ = "article_brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)

    cards: Mapped[List["ArticleCard"]] = relationship(back_populates="brand")


class ArticleCategory(PublicBase):
    __tablename__ = "article_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)

    cards: Mapped[List["ArticleCard"]] = relationship(back_populates="category")


class ArticleCode(PublicBase):
    __tablename__ = "article_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ean: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    cards: Mapped[List["ArticleCard"]] = relationship(back_populates="code")
    prices: Mapped[List["Price"]] = relationship(
        back_populates="article_code", cascade="all, delete-orphan"
    )


class ArticleDescription(PublicBase):
    __tablename__ = "article_descriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    description: Mapped[str] = mapped_column(Text, unique=True, nullable=False, index=True)

    cards: Mapped[List["ArticleCard"]] = relationship(back_populates="description")


class ArticleCard(PublicBase):
    __tablename__ = "article_cards"
    __table_args__ = (
        UniqueConstraint("code_id", name="uq_article_card_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    brand_id: Mapped[Optional[int]] = mapped_column(ForeignKey("article_brands.id"), nullable=True, index=True)
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("article_categories.id"), nullable=True, index=True)
    description_id: Mapped[Optional[int]] = mapped_column(ForeignKey("article_descriptions.id"), nullable=True, index=True)
    code_id: Mapped[int] = mapped_column(ForeignKey("article_codes.id"), unique=True, nullable=False, index=True)

    brand: Mapped[Optional["ArticleBrand"]] = relationship(back_populates="cards")
    category: Mapped[Optional["ArticleCategory"]] = relationship(back_populates="cards")
    description: Mapped[Optional["ArticleDescription"]] = relationship(back_populates="cards")
    code: Mapped["ArticleCode"] = relationship(back_populates="cards")

    @property
    def ean(self) -> str:
        return self.code.ean if self.code else ""

    @property
    def name(self) -> str:
        return self.description.description if self.description else ""


# ProductModel alias for backwards compatibility
ProductModel = ArticleCard


# --- Price & Metric Entities ---

class Timestamp(PublicBase):
    __tablename__ = "timestamps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    prices: Mapped[List["Price"]] = relationship(
        back_populates="timestamp", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return self.timestamp.strftime("%Y%m%d%H%M%S")

    @classmethod
    def from_string(cls, string: str) -> "Timestamp":
        dt = datetime.strptime(string[:14], "%Y%m%d%H%M%S") if len(string) >= 14 else datetime.strptime(string[:10], "%Y-%m-%d")
        return cls(timestamp=dt)


class Price(PublicBase):
    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint(
            "timestamp_id",
            "point_of_sale_id",
            "article_code_id",
            name="uq_price_timestamp_pos_article",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, index=True)  # Integer Pesos (ARS)
    timestamp_id: Mapped[int] = mapped_column(ForeignKey("timestamps.id"), nullable=False, index=True)
    point_of_sale_id: Mapped[int] = mapped_column(ForeignKey("points_of_sale.id"), nullable=False, index=True)
    article_code_id: Mapped[int] = mapped_column(ForeignKey("article_codes.id"), nullable=False, index=True)

    timestamp: Mapped["Timestamp"] = relationship(back_populates="prices")
    point_of_sale: Mapped["PointOfSale"] = relationship(back_populates="prices")
    article_code: Mapped["ArticleCode"] = relationship(back_populates="prices")

    @property
    def store_id(self) -> str:
        return self.point_of_sale.code if self.point_of_sale else ""

    @property
    def ean(self) -> str:
        return self.article_code.ean if self.article_code else ""

    @property
    def price(self) -> int:
        return self.amount


# DailyPriceModel alias
DailyPriceModel = Price


class DailyProductMetricModel(PublicBase):
    __tablename__ = "daily_product_metrics"

    date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False, index=True)
    ean: Mapped[str] = mapped_column(String(14), primary_key=True, nullable=False, index=True)
    city: Mapped[str] = mapped_column(Text, primary_key=True, nullable=False, index=True)
    min_price: Mapped[Optional[int]] = mapped_column(Integer)
    max_price: Mapped[Optional[int]] = mapped_column(Integer)
    median_price: Mapped[Optional[int]] = mapped_column(Integer)
    reference_price: Mapped[Optional[int]] = mapped_column(Integer)
    price_dispersion: Mapped[Optional[float]] = mapped_column(Float)
    pct_change_7d: Mapped[Optional[float]] = mapped_column(Float)
    pct_change_30d: Mapped[Optional[float]] = mapped_column(Float)
    pct_change_90d: Mapped[Optional[float]] = mapped_column(Float)
