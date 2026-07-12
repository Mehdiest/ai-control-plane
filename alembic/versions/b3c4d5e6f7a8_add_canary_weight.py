"""add canary weight columns

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-07-12 16:15:00.000000

Phase 5 — Canary Rollout

Adds the `weight` column to the `policies` table (traffic share within
a priority group) and the `policy_name` / `policy_weight` columns to
`request_logs` so the observability dashboard can show the canary split.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # policies.weight — canary traffic share within a priority group.
    # Defaults to 100 so existing policies receive 100% of traffic until
    # an operator explicitly configures a canary split.
    op.add_column(
        'policies',
        sa.Column('weight', sa.Integer(), nullable=False, server_default='100'),
    )

    # request_logs.policy_name / policy_weight — which policy handled the
    # request and its weight at resolution time (canary observability).
    op.add_column(
        'request_logs',
        sa.Column('policy_name', sa.String(length=120), nullable=True),
    )
    op.add_column(
        'request_logs',
        sa.Column('policy_weight', sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f('ix_request_logs_policy_name'), 'request_logs', ['policy_name'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_request_logs_policy_name'), table_name='request_logs')
    op.drop_column('request_logs', 'policy_weight')
    op.drop_column('request_logs', 'policy_name')
    op.drop_column('policies', 'weight')