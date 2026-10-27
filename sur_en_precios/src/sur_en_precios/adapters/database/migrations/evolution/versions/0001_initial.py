"""Initial evolution schema: tracked baskets, runs, daily summaries and items.

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-27 09:00:00

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "evolution_baskets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("basket_key", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("composition_hash", sa.String(length=16), nullable=False),
        sa.Column("items_count", sa.Integer(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evolution_baskets_basket_key",
        "evolution_baskets",
        ["basket_key"],
        unique=True,
    )

    op.create_table(
        "evolution_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("price_date", sa.Date(), nullable=True),
        sa.Column("region", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("baskets_evaluated", sa.Integer(), nullable=False),
        sa.Column("baskets_failed", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "evolution_daily_summaries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("price_date", sa.Date(), nullable=False),
        sa.Column("basket_id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("region", sa.String(length=10), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=False),
        sa.Column("composition_hash", sa.String(length=16), nullable=False),
        sa.Column("requested_items_count", sa.Integer(), nullable=False),
        sa.Column("matched_items_count", sa.Integer(), nullable=False),
        sa.Column("active_stores_count", sa.Integer(), nullable=False),
        sa.Column("complete_stores_count", sa.Integer(), nullable=False),
        sa.Column("total_min_price", sa.Integer(), nullable=True),
        sa.Column("total_reference_price", sa.Integer(), nullable=True),
        sa.Column("total_max_price", sa.Integer(), nullable=True),
        sa.Column("best_store_code", sa.String(length=64), nullable=True),
        sa.Column("best_store_label", sa.String(length=255), nullable=True),
        sa.Column("best_store_total", sa.Integer(), nullable=True),
        sa.Column("worst_store_code", sa.String(length=64), nullable=True),
        sa.Column("worst_store_label", sa.String(length=255), nullable=True),
        sa.Column("worst_store_total", sa.Integer(), nullable=True),
        sa.Column("dispersion_pct", sa.Float(), nullable=True),
        sa.Column("store_dispersion_pct", sa.Float(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["basket_id"], ["evolution_baskets.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["run_id"], ["evolution_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "price_date", "basket_id", "city", name="uq_summary_date_basket_city"
        ),
    )
    op.create_index(
        "ix_evolution_daily_summaries_price_date",
        "evolution_daily_summaries",
        ["price_date"],
    )
    op.create_index(
        "ix_evolution_daily_summaries_basket_id",
        "evolution_daily_summaries",
        ["basket_id"],
    )
    op.create_index(
        "ix_evolution_daily_summaries_region",
        "evolution_daily_summaries",
        ["region"],
    )
    op.create_index(
        "ix_evolution_daily_summaries_city",
        "evolution_daily_summaries",
        ["city"],
    )
    op.create_index(
        "ix_summary_basket_city_date",
        "evolution_daily_summaries",
        ["basket_id", "city", "price_date"],
    )

    op.create_table(
        "evolution_daily_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("summary_id", sa.Integer(), nullable=False),
        sa.Column("ean", sa.String(length=32), nullable=False),
        sa.Column("product_name", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("numerator", sa.Integer(), nullable=False),
        sa.Column("denominator", sa.Integer(), nullable=False),
        sa.Column("stores_count", sa.Integer(), nullable=False),
        sa.Column("min_price", sa.Integer(), nullable=True),
        sa.Column("reference_price", sa.Integer(), nullable=True),
        sa.Column("max_price", sa.Integer(), nullable=True),
        sa.Column("cheapest_store_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["summary_id"], ["evolution_daily_summaries.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("summary_id", "ean", name="uq_item_summary_ean"),
    )
    op.create_index(
        "ix_evolution_daily_items_summary_id",
        "evolution_daily_items",
        ["summary_id"],
    )
    op.create_index(
        "ix_evolution_daily_items_ean",
        "evolution_daily_items",
        ["ean"],
    )


def downgrade() -> None:
    op.drop_table("evolution_daily_items")
    op.drop_table("evolution_daily_summaries")
    op.drop_table("evolution_runs")
    op.drop_table("evolution_baskets")
