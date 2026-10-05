"""Append-only snapshot publication and restoration history."""
from alembic import op
import sqlalchemy as sa
revision = 'm3201'
down_revision = 'm3101'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('snapshot_activations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('snapshot_id', sa.String(36), sa.ForeignKey('snapshots.id'), nullable=False),
        sa.Column('previous_snapshot_id', sa.String(36), sa.ForeignKey('snapshots.id')),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(30), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id')),
        sa.Column('actor_name', sa.String(50), nullable=False),
        sa.Column('reason', sa.String(500), nullable=False),
        sa.Column('idempotency_key', sa.String(100)),
        sa.Column('request_hash', sa.String(64)),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('project_id', 'revision', name='uq_activation_revision'),
        sa.UniqueConstraint('project_id', 'actor_id', 'idempotency_key', name='uq_activation_request'))
    op.create_index('ix_snapshot_activations_project_id', 'snapshot_activations', ['project_id'])


def downgrade():
    op.drop_table('snapshot_activations')
