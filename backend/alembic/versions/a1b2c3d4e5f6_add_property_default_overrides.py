"""add_property_default_overrides

Revision ID: a1b2c3d4e5f6
Revises: 634d7645dec6
Create Date: 2026-05-18 00:00:00.000000

"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "634d7645dec6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "property_default_overrides",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("property_definition_id", sa.Text(), nullable=False),
        sa.Column("curriculum_node_id", sa.Text(), nullable=False),
        sa.Column("override_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["property_definition_id"], ["property_definitions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("property_definition_id", "curriculum_node_id", name="uq_property_default_overrides_pair"),
    )
    op.create_index("ix_property_default_overrides_node_id", "property_default_overrides", ["curriculum_node_id"])
    op.create_index("ix_property_default_overrides_property_id", "property_default_overrides", ["property_definition_id"])


def downgrade() -> None:
    op.drop_index("ix_property_default_overrides_property_id", table_name="property_default_overrides")
    op.drop_index("ix_property_default_overrides_node_id", table_name="property_default_overrides")
    op.drop_table("property_default_overrides")
