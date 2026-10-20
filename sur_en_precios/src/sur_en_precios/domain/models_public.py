"""SQLAlchemy 2.0 ORM Models for the public price database (``public.sqlite``).

Defines a clean, standardized schema for articles, hierarchical retail categories,
brands, facet tags, points of sale, daily regional prices, metrics, and unreviewed staging.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class PublicBase(DeclarativeBase):
    """Base class for all SQLAlchemy 2.0 public models."""

    pass


# Association table for Article <-> Tag (Many-to-Many)
article_tags = Table(
    "article_tags",
    PublicBase.metadata,
    Column("article_id", ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_article_tags_article_id", "article_id"),
    Index("ix_article_tags_tag_id", "tag_id"),
)


class Category(PublicBase):
    """Hierarchical category representing retail departments and subcategories.

    Level 1: Department (e.g., 'Almacén', 'Bebidas', 'Limpieza')
    Level 2: Subcategory (e.g., 'Aceites y Vinagres', 'Vinos Tintos')
    """

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    parent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Self-referential relationship for hierarchy
    parent: Mapped[Optional[Category]] = relationship(
        "Category",
        remote_side=[id],
        back_populates="children",
    )
    children: Mapped[List[Category]] = relationship(
        "Category",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="Category.name",
    )

    articles: Mapped[List[Article]] = relationship(
        "Article",
        back_populates="category",
        lazy="selectin",
    )

    def __init__(self, **kwargs: Any) -> None:
        if "content" in kwargs and "name" not in kwargs:
            kwargs["name"] = kwargs.pop("content")
        if "name" in kwargs and "slug" not in kwargs:
            from sur_en_precios.domain.cleaner.text_utils import slugify
            kwargs["slug"] = slugify(kwargs["name"])
        super().__init__(**kwargs)

    @property
    def content(self) -> str:
        return self.name

    @property
    def full_path(self) -> str:
        """Returns the full hierarchical path, e.g. 'Bebidas > Vinos Tintos'."""
        if self.parent:
            return f"{self.parent.name} > {self.name}"
        return self.name

    def __repr__(self) -> str:
        return f"<Category(id={self.id}, name='{self.name}', level={self.level})>"


class Brand(PublicBase):
    """Cleaned manufacturer/retail brand entity."""

    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    articles: Mapped[List[Article]] = relationship(
        "Article",
        back_populates="brand",
        lazy="selectin",
    )

    def __init__(self, **kwargs: Any) -> None:
        if "brand" in kwargs and "name" not in kwargs:
            kwargs["name"] = kwargs.pop("brand")
        if "name" in kwargs and "slug" not in kwargs:
            from sur_en_precios.domain.cleaner.text_utils import slugify
            kwargs["slug"] = slugify(kwargs["name"])
        super().__init__(**kwargs)

    @property
    def brand(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<Brand(id={self.id}, name='{self.name}')>"



class Tag(PublicBase):
    """Keyword / facet tag for fine-grained querying (e.g. 'malbec', 'sin gas', 'doypack')."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    articles: Mapped[List[Article]] = relationship(
        "Article",
        secondary=article_tags,
        back_populates="tags",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Tag(id={self.id}, name='{self.name}')>"


class Article(PublicBase):
    """Cleaned article / product entity with standardized fields."""

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ean: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    clean_description: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    raw_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Brand details
    brand_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("brands.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    brand_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)

    # Package details
    package: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    package_amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    package_unit: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)

    # Category association
    category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Review status (True for Hermes seed, False for unreviewed newly discovered items)
    is_reviewed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    brand: Mapped[Optional[Brand]] = relationship("Brand", back_populates="articles")
    category: Mapped[Optional[Category]] = relationship("Category", back_populates="articles")
    tags: Mapped[List[Tag]] = relationship(
        "Tag",
        secondary=article_tags,
        back_populates="articles",
        lazy="selectin",
    )
    prices: Mapped[List[DailyPrice]] = relationship(
        "DailyPrice",
        back_populates="article",
        cascade="all, delete-orphan",
    )
    metrics: Mapped[List[DailyProductMetric]] = relationship(
        "DailyProductMetric",
        back_populates="article",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs: Any) -> None:
        if "article_number" in kwargs and "ean" not in kwargs:
            an = kwargs.pop("article_number")
            kwargs["ean"] = getattr(an, "ean", str(an))
        if "description" in kwargs and "clean_description" not in kwargs:
            d = kwargs.pop("description")
            kwargs["clean_description"] = getattr(d, "content", getattr(d, "clean_description", str(d)))
            if "name" not in kwargs:
                kwargs["name"] = kwargs["clean_description"]
        if "name" in kwargs and "clean_description" not in kwargs:
            kwargs["clean_description"] = kwargs["name"]
        if "clean_description" in kwargs and "name" not in kwargs:
            kwargs["name"] = kwargs["clean_description"]
        if "brand" in kwargs and "brand_name" not in kwargs:
            b = kwargs.pop("brand")
            kwargs["brand_name"] = getattr(b, "brand", getattr(b, "name", str(b)))
        if "category" in kwargs and "category_id" not in kwargs:
            c = kwargs.pop("category")
            if isinstance(c, Category):
                kwargs["category"] = c
            else:
                kwargs["category_id"] = getattr(c, "id", None)
        kwargs.setdefault("is_reviewed", True)
        super().__init__(**kwargs)


    @property
    def description(self) -> str:
        """Alias for clean_description."""
        return self.clean_description

    @property
    def category_name(self) -> Optional[str]:
        """Name of the associated category or subcategory, if assigned."""
        return self.category.name if self.category else None

    def __repr__(self) -> str:
        return (
            f"<Article(id={self.id}, ean='{self.ean}', name='{self.name}', "
            f"brand='{self.brand_name}', package='{self.package}')>"
        )


class PointOfSale(PublicBase):
    """Store, branch, or point of sale entity with standardized commercial and geographic attributes."""

    __tablename__ = "points_of_sale"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    sepa_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    comercio_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    bandera_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    sucursal_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)

    # Corporate & Brand hierarchy
    business_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True, index=True)
    holding_group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    brand_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    store_format: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)

    # Location details
    branch_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    province: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    province_code: Mapped[Optional[str]] = mapped_column(String(10), nullable=True, index=True)

    # Geolocation (optional coordinates)
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationships
    prices: Mapped[List[DailyPrice]] = relationship(
        "DailyPrice",
        back_populates="point_of_sale",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs: Any) -> None:
        # Translate legacy kwargs if passed
        if "place" in kwargs:
            p = kwargs.pop("place")
            if "address" not in kwargs and hasattr(p, "address"):
                kwargs["address"] = getattr(p, "address", None)
            if "city" not in kwargs and hasattr(p, "city"):
                c = getattr(p, "city", None)
                kwargs["city"] = getattr(c, "name", str(c)) if c else None
            if "latitude" not in kwargs and hasattr(p, "latitude"):
                kwargs["latitude"] = getattr(p, "latitude", None)
            if "longitude" not in kwargs and hasattr(p, "longitude"):
                kwargs["longitude"] = getattr(p, "longitude", None)
        if "business" in kwargs and "business_name" not in kwargs:
            bu = kwargs.pop("business")
            kwargs["business_name"] = getattr(bu, "business", getattr(bu, "name", str(bu)))
        if "flag" in kwargs and "brand_name" not in kwargs:
            fl = kwargs.pop("flag")
            kwargs["brand_name"] = getattr(fl, "flag", getattr(fl, "brand", str(fl)))
        if "branch" in kwargs and "branch_name" not in kwargs:
            br = kwargs.pop("branch")
            kwargs["branch_name"] = getattr(br, "branch", getattr(br, "name", str(br)))
        if "state" in kwargs and "province" not in kwargs:
            kwargs["province"] = kwargs.pop("state")
        super().__init__(**kwargs)

    @property
    def place(self) -> Any:
        return Place(
            address=self.address,
            city=City(name=self.city) if self.city else None,
            latitude=self.latitude,
            longitude=self.longitude,
        )

    @property
    def chain_name(self) -> str:
        b = self.brand_name
        return getattr(b, "flag", getattr(b, "brand", str(b))) if b else ""

    @property
    def store_name(self) -> str:
        b = self.branch_name
        return getattr(b, "branch", getattr(b, "name", str(b))) if b else ""

    @property
    def business(self) -> Optional[str]:
        return self.business_name

    @business.setter
    def business(self, value: Optional[str]) -> None:
        self.business_name = value

    @property
    def brand(self) -> Optional[str]:
        return self.brand_name

    @brand.setter
    def brand(self, value: Optional[str]) -> None:
        self.brand_name = value

    @property
    def flag(self) -> Optional[str]:
        return self.brand_name

    @flag.setter
    def flag(self, value: Optional[str]) -> None:
        self.brand_name = value

    @property
    def branch(self) -> Optional[str]:
        return self.branch_name

    @branch.setter
    def branch(self, value: Optional[str]) -> None:
        self.branch_name = value

    @property
    def state(self) -> Optional[str]:
        return self.province

    @state.setter
    def state(self, value: Optional[str]) -> None:
        self.province = value

    def __repr__(self) -> str:
        return (
            f"<PointOfSale(id={self.id}, code='{self.code}', brand='{self.brand_name}', "
            f"branch='{self.branch_name}', city='{self.city}', province='{self.province}')>"
        )


class DailyPrice(PublicBase):
    """Daily observed price for an article at a specific point of sale."""

    __tablename__ = "daily_prices"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, nullable=False, index=True)
    ean: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("articles.ean", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    store_code: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("points_of_sale.code", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    price: Mapped[int] = mapped_column(Integer, nullable=False)  # Integer Pesos Argentinos (ARS)
    unit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # Price per standard base unit

    # Relationships
    article: Mapped[Article] = relationship("Article", back_populates="prices")
    point_of_sale: Mapped[PointOfSale] = relationship("PointOfSale", back_populates="prices")

    def __init__(self, **kwargs: Any) -> None:
        if "store_id" in kwargs and "store_code" not in kwargs:
            kwargs["store_code"] = str(kwargs.pop("store_id"))
        elif "store_id" in kwargs:
            kwargs.pop("store_id")
        if "amount" in kwargs and "price" not in kwargs:
            kwargs["price"] = kwargs.pop("amount")
        if "timestamp" in kwargs and "date" not in kwargs:
            ts = kwargs.pop("timestamp")
            kwargs["date"] = getattr(ts, "value", ts)
        elif "timestamp" in kwargs:
            kwargs.pop("timestamp")
        if "article_number" in kwargs:
            an = kwargs.pop("article_number")
            if "ean" not in kwargs:
                kwargs["ean"] = getattr(an, "ean", str(an))
        if "store" in kwargs:
            st = kwargs.pop("store")
            if "store_code" not in kwargs:
                kwargs["store_code"] = getattr(st, "code", str(st))
        super().__init__(**kwargs)

    @property
    def store(self) -> PointOfSale:
        return self.point_of_sale

    @store.setter
    def store(self, value: Any) -> None:
        if isinstance(value, PointOfSale):
            self.point_of_sale = value
        elif hasattr(value, "code"):
            self.store_code = getattr(value, "code")

    @property
    def article_number(self) -> Article:
        return self.article

    @article_number.setter
    def article_number(self, value: Any) -> None:
        if isinstance(value, Article):
            self.article = value
        elif hasattr(value, "ean"):
            self.ean = getattr(value, "ean")

    def __repr__(self) -> str:
        return f"<DailyPrice(date={self.date}, ean='{self.ean}', store='{self.store_code}', price={self.price})>"


class DailyProductMetric(PublicBase):
    """Daily calculated price metrics and dispersion for an article in a specific city."""

    __tablename__ = "daily_product_metrics"

    date: Mapped[dt.date] = mapped_column(Date, primary_key=True, nullable=False, index=True)
    ean: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("articles.ean", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        index=True,
    )
    city: Mapped[str] = mapped_column(String(100), primary_key=True, nullable=False, index=True)

    min_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    median_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    geo_mean_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price_dispersion: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_change_7d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_change_30d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pct_change_90d: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationships
    article: Mapped[Article] = relationship("Article", back_populates="metrics")

    def __init__(self, **kwargs: Any) -> None:
        if "timestamp" in kwargs and "date" not in kwargs:
            ts = kwargs.pop("timestamp")
            kwargs["date"] = getattr(ts, "value", ts)
        if "article_number" in kwargs and "ean" not in kwargs:
            an = kwargs.pop("article_number")
            kwargs["ean"] = getattr(an, "ean", str(an))
        if "city" in kwargs:
            c = kwargs.pop("city")
            kwargs["city"] = getattr(c, "name", str(c))
        if "reference_price" in kwargs and "median_price" not in kwargs:
            kwargs["median_price"] = kwargs.pop("reference_price")
        super().__init__(**kwargs)


    @property
    def city_name(self) -> str:
        return self.city

    @property
    def reference_price(self) -> Optional[int]:
        return self.median_price

    @property
    def article_number(self) -> Article:
        return self.article

    def __repr__(self) -> str:
        return f"<DailyProductMetric(date={self.date}, ean='{self.ean}', city='{self.city}', median={self.median_price})>"



class UnreviewedArticle(PublicBase):
    """Staging table for newly discovered or low-confidence unclassified products."""

    __tablename__ = "unreviewed_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ean: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    raw_description: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_brand: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    suggested_package: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    suggested_category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=lambda: dt.datetime.now(dt.timezone.utc), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(255), default="Unclassified / New SEPA Article")

    suggested_category: Mapped[Optional[Category]] = relationship("Category")

    def __repr__(self) -> str:
        return f"<UnreviewedArticle(ean='{self.ean}', desc='{self.raw_description}')>"


# Aliases for backward compatibility with repositories and use cases
Store = PointOfSale
Price = DailyPrice
ArticleMetric = DailyProductMetric
ArticleCard = Article
ArticleNumber = Article
ArticleBrand = Brand
ArticleCategory = Category


class Timestamp:
    """Compatibility helper for legacy timestamp wrappers."""

    def __init__(self, value: Any = None, id: Optional[int] = None) -> None:
        self.id = id
        self.value = value

    def __repr__(self) -> str:
        return f"<Timestamp {self.value}>"


class City:
    """Compatibility helper for legacy city references."""

    def __init__(self, name: str = "", state: Any = None, id: Optional[int] = None) -> None:
        self.id = id
        self.name = name
        self.state = state

    def __str__(self) -> str:
        return self.name

    def __repr__(self) -> str:
        return f"<City {self.name}>"


class State:
    """Compatibility helper for legacy state references."""

    def __init__(self, code: str = "", name: str = "", id: Optional[int] = None) -> None:
        self.id = id
        self.code = code
        self.name = name

    def __repr__(self) -> str:
        return f"<State {self.name} ({self.code})>"


class Place:
    """Compatibility helper for legacy place references."""

    def __init__(
        self,
        address: Optional[str] = None,
        city: Any = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        id: Optional[int] = None,
    ) -> None:
        self.id = id
        self.address = address
        self.city = city
        self.latitude = latitude
        self.longitude = longitude

    def __repr__(self) -> str:
        return f"<Place {self.address}>"


class Flag:
    """Compatibility helper for legacy banner/flag references."""

    def __init__(self, flag: str = "", id: Optional[int] = None) -> None:
        self.id = id
        self.flag = flag

    def __repr__(self) -> str:
        return f"<Flag {self.flag}>"


class Business:
    """Compatibility helper for legacy business references."""

    def __init__(self, business: str = "", id: Optional[int] = None) -> None:
        self.id = id
        self.business = business

    def __repr__(self) -> str:
        return f"<Business {self.business}>"


class Branch:
    """Compatibility helper for legacy branch references."""

    def __init__(self, branch: str = "", id: Optional[int] = None) -> None:
        self.id = id
        self.branch = branch

    def __repr__(self) -> str:
        return f"<Branch {self.branch}>"


class ArticleDescription:
    """Compatibility helper for legacy description references."""

    def __init__(self, content: str = "", id: Optional[int] = None) -> None:
        self.id = id
        self.content = content

    def __str__(self) -> str:
        return self.content

    def __repr__(self) -> str:
        return f"<ArticleDescription {self.content}>"


