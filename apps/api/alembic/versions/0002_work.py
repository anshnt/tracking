"""task snapshots for the work overview

Revision ID: 0002
Revises: 0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('task_snapshots',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('source', sa.Text(), nullable=False),
    sa.Column('source_ref', sa.Text(), nullable=False),
    sa.Column('assignee_id', sa.UUID(), nullable=True),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('state', sa.Text(), server_default='open', nullable=False),
    sa.Column('due_date', sa.Date(), nullable=True),
    sa.Column('blocker', sa.Text(), nullable=True),
    sa.Column('deliverables', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('review_requested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("state IN ('open', 'in_progress', 'in_review', 'blocked', 'done')", name=op.f('ck_task_snapshots_state')),
    sa.ForeignKeyConstraint(['assignee_id'], ['employees.id'], name=op.f('fk_task_snapshots_assignee_id_employees')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_snapshots')),
    sa.UniqueConstraint('source', 'source_ref', name=op.f('uq_task_snapshots_source'))
    )
    op.create_index('ix_task_snapshots_assignee_id', 'task_snapshots', ['assignee_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_task_snapshots_assignee_id', table_name='task_snapshots')
    op.drop_table('task_snapshots')
