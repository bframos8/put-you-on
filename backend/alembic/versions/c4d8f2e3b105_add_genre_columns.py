"""add genre columns to albums, songs, user_top_songs

Revision ID: c4d8f2e3b105
Revises: b3c7e1d2a904
Create Date: 2026-03-26 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c4d8f2e3b105'
down_revision: Union[str, Sequence[str], None] = 'b3c7e1d2a904'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('albums', sa.Column('genre', sa.Text(), nullable=True))
    op.add_column('songs', sa.Column('genre', sa.Text(), nullable=True))
    op.add_column('user_top_songs', sa.Column('genre', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('user_top_songs', 'genre')
    op.drop_column('songs', 'genre')
    op.drop_column('albums', 'genre')
