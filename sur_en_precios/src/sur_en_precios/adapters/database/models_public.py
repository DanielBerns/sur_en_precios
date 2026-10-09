from datetime import date
from typing import Optional

from sqlalchemy import Date, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class PublicBase(DeclarativeBase):
    """Declarative Base for public.sqlite price database."""

    pass


class ProductModel(PublicBase):
    __tablename__ = "products"

    ean: Mapped[str] = mapped_column(String(14), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    brand: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)
    category: Mapped[Optional[str]] = mapped_column(Text, nullable=True, index=True)


class StoreModel(PublicBase):
    __tablename__ = "stores"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    chain_name: Mapped[str] = mapped_column(Text, nullable=False)
    store_name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    city: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    latitude: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # Optional per SEPA metadata
    longitude: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )  # Optional per SEPA metadata


class DailyPriceModel(PublicBase):
    __tablename__ = "daily_prices"

    date: Mapped[date] = mapped_column(
        Date, primary_key=True, nullable=False, index=True
    )
    ean: Mapped[str] = mapped_column(
        ForeignKey("products.ean"), primary_key=True, nullable=False
    )
    store_id: Mapped[str] = mapped_column(
        ForeignKey("stores.id"), primary_key=True, nullable=False
    )
    price: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # Integer Pesos Argentinos (ARS)


class DailyProductMetricModel(PublicBase):
    __tablename__ = "daily_product_metrics"

    date: Mapped[date] = mapped_column(
        Date, primary_key=True, nullable=False, index=True
    )
    ean: Mapped[str] = mapped_column(String(14), primary_key=True, nullable=False)
    city: Mapped[str] = mapped_column(
        Text, primary_key=True, nullable=False, index=True
    )
    min_price: Mapped[Optional[int]] = mapped_column(Integer)  # Integer Pesos
    max_price: Mapped[Optional[int]] = mapped_column(Integer)  # Integer Pesos
    median_price: Mapped[Optional[int]] = mapped_column(Integer)  # Integer Pesos
    reference_price: Mapped[Optional[int]] = mapped_column(
        Integer
    )  # Geometric mean (integer Pesos)
    price_dispersion: Mapped[Optional[float]] = mapped_column(Float)
    pct_change_7d: Mapped[Optional[float]] = mapped_column(Float)
    pct_change_30d: Mapped[Optional[float]] = mapped_column(Float)
    pct_change_90d: Mapped[Optional[float]] = mapped_column(Float)
