"""Role-based knowledge visibility; existing unclassified bases stay internal."""
import sqlalchemy as sa
from alembic import op

revision = "20260905_0006"
down_revision = "20260713_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("knowledge_access",
        sa.Column("base_id", sa.String(32), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("visibility", sa.String(20), nullable=False),
    )


def downgrade():
    op.drop_table("knowledge_access")
