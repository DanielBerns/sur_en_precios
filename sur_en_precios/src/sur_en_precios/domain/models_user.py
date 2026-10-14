"""ORM models for the user database (``user_data.sqlite``)."""

import uuid
from datetime import datetime, timezone
from typing import Any, List

import bcrypt
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UserBase(DeclarativeBase):
    """Declarative Base for user_data.sqlite tables."""

    pass


class User(UserBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    baskets: Mapped[List["Basket"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password: str) -> None:
        self.password_hash = bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

    def check_password(self, password: str) -> bool:
        return bcrypt.checkpw(
            password.encode("utf-8"), self.password_hash.encode("utf-8")
        )

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Basket(UserBase):
    __tablename__ = "baskets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uuid: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["User"] = relationship(back_populates="baskets")
    items: Mapped[List["BasketItem"]] = relationship(
        back_populates="basket", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Basket {self.name} ({self.uuid})>"


class BasketItem(UserBase):
    __tablename__ = "basket_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    basket_id: Mapped[int] = mapped_column(
        ForeignKey("baskets.id"), nullable=False, index=True
    )
    ean: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    numerator: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    denominator: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    basket: Mapped["Basket"] = relationship(back_populates="items")

    def __init__(
        self,
        ean: str = "",
        quantity: int = 1,
        selected: bool = True,
        numerator: int = 1,
        denominator: int = 1,
        **kwargs: Any,
    ):
        super().__init__(
            ean=ean,
            quantity=quantity,
            selected=selected,
            numerator=numerator,
            denominator=denominator if denominator != 0 else 1,
            **kwargs,
        )

    @property
    def factor(self) -> float:
        if self.denominator == 0:
            raise ValueError("Denominator cannot be 0")
        return self.numerator / self.denominator

    def __repr__(self) -> str:
        return f"<BasketItem {self.ean} x{self.quantity}>"
