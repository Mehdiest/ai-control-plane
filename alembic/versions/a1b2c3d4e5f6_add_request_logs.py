"""add request_logs table

Revision ID: a1b2c3d4e5f6
Revises: ca8bd278d99d
Create Date: 2026-07-12 03:13:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'ca8bd278d99d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('request_logs',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('tenant_id', sa.String(length=120), nullable=False),
    sa.Column('request_type', sa.String(length=100), nullable=False),
    sa.Column('resolved_service', sa.String(length=120), nullable=False),
    sa.Column('resolution', sa.String(length=40), nullable=False),
    sa.Column('latency_ms', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_request_logs_tenant_id'), 'request_logs', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_request_logs_request_type'), 'request_logs', ['request_type'], unique=False)
    op.create_index(op.f('ix_request_logs_resolved_service'), 'request_logs', ['resolved_service'], unique=False)
    op.create_index(op.f('ix_request_logs_resolution'), 'request_logs', ['resolution'], unique=False)
    op.create_index(op.f('ix_request_logs_created_at'), 'request_logs', ['created_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_request_logs_created_at'), table_name='request_logs')
    op.drop_index(op.f('ix_request_logs_resolution'), table_name='request_logs')
    op.drop_index(op.f('ix_request_logs_resolved_service'), table_name='request_logs')
    op.drop_index(op.f('ix_request_logs_request_type'), table_name='request_logs')
    op.drop_index(op.f('ix_request_logs_tenant_id'), table_name='request_logs')
    op.drop_table('request_logs')