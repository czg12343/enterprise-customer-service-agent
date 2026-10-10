"""add logistics delivery timestamp

Revision ID: 20260710_0002
Revises: 20260710_0001
Create Date: 2026-07-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260710_0002"
down_revision: Union[str, Sequence[str], None] = "20260710_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("logistics") as batch_op:
        batch_op.add_column(sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("logistics") as batch_op:
        batch_op.drop_column("delivered_at")

