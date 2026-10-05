"""M3.1 scoped master data, lazily initialized from immutable snapshots."""
from alembic import op
import sqlalchemy as sa
revision = "m3101"
down_revision = "m3001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("project_catalog",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("department_name_key", sa.String(100)),
        sa.Column("specification", sa.String(200), nullable=False),
        sa.Column("base_unit", sa.String(30), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("project_id", "kind", "code", name="uq_catalog_code"),
        sa.UniqueConstraint("project_id", "kind", "source_id", name="uq_catalog_source"),
        sa.UniqueConstraint("project_id", "kind", "department_name_key", name="uq_catalog_department_name"))
    op.create_index("ix_project_catalog_project_id", "project_catalog", ["project_id"])


def downgrade():
    op.drop_table("project_catalog")
