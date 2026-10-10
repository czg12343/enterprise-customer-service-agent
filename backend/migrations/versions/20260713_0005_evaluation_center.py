"""add evaluation center and LLM usage metrics

Revision ID: 20260713_0005
Revises: 20260711_0004
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260713_0005"
down_revision: Union[str, Sequence[str], None] = "20260711_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "agent_runs",
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_runs",
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0"),
    )
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("triggered_by", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("passed_cases", sa.Integer(), nullable=False),
        sa.Column("answer_accuracy", sa.Float(), nullable=False),
        sa.Column("citation_accuracy", sa.Float(), nullable=False),
        sa.Column("tool_success_rate", sa.Float(), nullable=False),
        sa.Column("average_latency_ms", sa.Float(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("user_satisfaction", sa.Float(), nullable=True),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_runs_triggered_by", "evaluation_runs", ["triggered_by"]
    )
    op.create_index("ix_evaluation_runs_created_at", "evaluation_runs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_created_at", table_name="evaluation_runs")
    op.drop_index("ix_evaluation_runs_triggered_by", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    op.drop_column("agent_runs", "estimated_cost_usd")
    op.drop_column("agent_runs", "completion_tokens")
    op.drop_column("agent_runs", "prompt_tokens")
