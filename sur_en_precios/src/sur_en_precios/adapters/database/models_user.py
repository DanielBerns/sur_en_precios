from datetime import datetime, timezone
from typing import List

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class UserBase(DeclarativeBase):
    """Declarative Base for user_data.sqlite tables."""

    pass


class UserModel(UserBase):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    shopping_lists: Mapped[List["ShoppingListModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ShoppingListModel(UserBase):
    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped["UserModel"] = relationship(back_populates="shopping_lists")
    items: Mapped[List["ListItemModel"]] = relationship(
        back_populates="shopping_list", cascade="all, delete-orphan"
    )


class ListItemModel(UserBase):
    __tablename__ = "list_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("shopping_lists.id"), nullable=False, index=True
    )
    ean: Mapped[str] = mapped_column(String(14), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    shopping_list: Mapped["ShoppingListModel"] = relationship(back_populates="items")
