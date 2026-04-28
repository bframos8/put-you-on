"""add dispatch_date and query_song_id to user_recommendations

Revision ID: e5f1a2b3c4d5
Revises: d9e1f3a4b205
Create Date: 2026-04-24 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'e5f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'd9e1f3a4b205'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user_recommendations',
        sa.Column('dispatch_date', sa.Date(), nullable=True),
    )
    op.add_column(
        'user_recommendations',
        sa.Column(
            'query_song_id',
            sa.Integer(),
            sa.ForeignKey('songs.id'),
            nullable=True,
        ),
    )
    op.create_index(
        'ix_user_recommendations_user_date',
        'user_recommendations',
        ['user_id', 'dispatch_date'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_user_recommendations_user_date',
        table_name='user_recommendations',
    )
    op.drop_column('user_recommendations', 'query_song_id')
    op.drop_column('user_recommendations', 'dispatch_date')
