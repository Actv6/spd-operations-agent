"""Keep historical snapshots and select the newest publication deterministically."""
from alembic import op
import sqlalchemy as sa

revision = "eb2001"
down_revision = "ecd38e5b52ce"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("snapshots", sa.Column("created_at", sa.Float(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("snapshots", "created_at")
