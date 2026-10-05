"""Append-only feedback and knowledge maintenance history."""
from alembic import op
import sqlalchemy as sa

revision = 'v1101'
down_revision = 'm3201'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('analysis_feedback',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('analysis_id', sa.String(36), sa.ForeignKey('analyses.id'), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(100), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('rating', sa.String(30), nullable=False),
        sa.Column('comment', sa.String(1000), nullable=False),
        sa.Column('context', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('actor_id', 'analysis_id', 'idempotency_key', name='uq_feedback_request'))
    op.create_index('ix_analysis_feedback_analysis_id', 'analysis_feedback', ['analysis_id'])
    op.create_table('knowledge_changes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('document_id', sa.String(36), sa.ForeignKey('documents.id'), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('idempotency_key', sa.String(100), nullable=False),
        sa.Column('request_hash', sa.String(64), nullable=False),
        sa.Column('action', sa.String(30), nullable=False),
        sa.Column('reason', sa.String(1000), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.UniqueConstraint('project_id', 'actor_id', 'idempotency_key', name='uq_knowledge_request'))
    op.create_index('ix_knowledge_changes_project_id', 'knowledge_changes', ['project_id'])


def downgrade():
    op.drop_table('knowledge_changes')
    op.drop_table('analysis_feedback')
