"""Append-only human reviews and serialized revision heads."""
from alembic import op
import sqlalchemy as sa

revision = 'v1301'
down_revision = 'v1101'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('human_review_states',
        sa.Column('run_id', sa.String(36), sa.ForeignKey('agent_runs.id'), primary_key=True),
        sa.Column('revision', sa.Integer(), nullable=False))
    op.create_table('human_review_records',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('agent_runs.id'), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('actor_name', sa.String(50), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sa.String(100), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(30), nullable=False),
        sa.Column('conclusion', sa.String(2000), nullable=False),
        sa.Column('basis', sa.String(2000), nullable=False),
        sa.Column('next_step', sa.String(1000), nullable=False),
        sa.Column('evidence_ids', sa.JSON(), nullable=False),
        sa.Column('handled_feedback_ids', sa.JSON(), nullable=False),
        sa.Column('self_review', sa.Boolean(), nullable=False),
        sa.Column('snapshot_set_id', sa.String(36), sa.ForeignKey('snapshots.id'), nullable=False),
        sa.Column('analysis_hash', sa.String(64), nullable=True),
        sa.Column('source_token', sa.String(64), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('run_id', 'revision', name='uq_human_review_revision'),
        sa.UniqueConstraint('run_id', 'actor_id', 'idempotency_key', name='uq_human_review_request'))
    op.create_index('ix_human_review_records_run_id', 'human_review_records', ['run_id'])


def downgrade():
    op.drop_table('human_review_records')
    op.drop_table('human_review_states')
