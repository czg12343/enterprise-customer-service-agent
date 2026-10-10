"""reserve revision for the lightweight RAG architecture decision

Revision ID: 20260711_0004
Revises: 20260710_0003
Create Date: 2026-07-11
"""

from typing import Sequence, Union

revision: str = "20260711_0004"
down_revision: Union[str, Sequence[str], None] = "20260710_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No schema change is needed for BM25 + hashed lexical vectors + RRF.
    pass


def downgrade() -> None:
    pass
