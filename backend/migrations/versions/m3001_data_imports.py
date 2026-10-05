"""M3 validated candidates and immutable publication audit."""
from alembic import op
import sqlalchemy as sa
revision = "m3001"
down_revision = "m2001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("data_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("actor_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("base_snapshot_id", sa.String(36), sa.ForeignKey("snapshots.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("as_of", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        sa.Column("snapshot_id", sa.String(36), sa.ForeignKey("snapshots.id")),
        sa.Column("published_by", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("published_at", sa.Float()),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("actor_id", "project_id", "idempotency_key", name="uq_import_idempotency"))
    op.create_index("ix_data_imports_project_id", "data_imports", ["project_id"])


def downgrade():
    op.drop_table("data_imports")
