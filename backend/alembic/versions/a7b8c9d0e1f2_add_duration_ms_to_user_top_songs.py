"""add duration_ms to user_top_songs

Revision ID: a7b8c9d0e1f2
Revises: f6a2b3c4d5e6
Create Date: 2026-06-15 00:00:00.000000

L4: Spotify's top-tracks payload carries duration_ms but add_user_top_songs
never stored it, so the profile UI rendered "—:—". Add the nullable column so
the ingest can persist it. Existing rows stay NULL until the next sync rebuilds
the snapshot (the table is delete()'d and re-inserted each sync), which is
acceptable — they render "—:—" until then.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user_top_songs',
        sa.Column('duration_ms', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user_top_songs', 'duration_ms')
