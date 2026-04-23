"""add hnsw index on songs embedding

Revision ID: d9e1f3a4b205
Revises: c4d8f2e3b105
Create Date: 2026-04-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd9e1f3a4b205'
down_revision: Union[str, Sequence[str], None] = 'c4d8f2e3b105'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS songs_embedding_hnsw_idx ON songs USING hnsw (embedding vector_cosine_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS songs_embedding_hnsw_idx")
