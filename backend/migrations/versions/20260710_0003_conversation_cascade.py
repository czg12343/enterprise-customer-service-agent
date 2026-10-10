"""enforce conversation cascade constraints

Revision ID: 20260710_0003
Revises: 20260710_0002
Create Date: 2026-07-10
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260710_0003"
down_revision: Union[str, Sequence[str], None] = "20260710_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def _replace_foreign_key(table: str, *, cascade: bool) -> None:
    dialect = op.get_context().dialect.name
    if dialect == "sqlite":
        constraint_name = f"fk_{table}_conversation_id_conversations"
        with op.batch_alter_table(table, naming_convention=NAMING_CONVENTION) as batch_op:
            batch_op.drop_constraint(constraint_name, type_="foreignkey")
            batch_op.create_foreign_key(
                constraint_name,
                "conversations",
                ["conversation_id"],
                ["id"],
                ondelete="CASCADE" if cascade else None,
            )
        return

    constraint_name = f"{table}_conversation_id_fkey"
    op.drop_constraint(constraint_name, table, type_="foreignkey")
    op.create_foreign_key(
        constraint_name,
        table,
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="CASCADE" if cascade else None,
    )


def upgrade() -> None:
    _replace_foreign_key("messages", cascade=True)
    _replace_foreign_key("agent_runs", cascade=True)


def downgrade() -> None:
    _replace_foreign_key("agent_runs", cascade=False)
    _replace_foreign_key("messages", cascade=False)

