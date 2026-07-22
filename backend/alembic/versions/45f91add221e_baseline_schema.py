"""baseline schema

Revision ID: 45f91add221e
Revises:
Create Date: 2026-07-17

Squashed baseline — the single root of the migration chain (gameplan 1.2). Prior
to this, the chain's root (``ad1aecf9f82f``) only ``add_column``-ed onto tables
that ``Base.metadata.create_all`` had made at boot, so ``alembic upgrade head``
could never build a fresh database. This migration ``CREATE TABLE``-s the full
current schema so Alembic is the single schema authority; ``create_all`` is gone.

Objects that the ORM models can't express are created here explicitly:
  * ``vector`` extension  — required before the songs.embedding column.
  * ``work_status_enum``  — emitted here by the first table that uses it (albums),
    since this migration's ``sa.Enum`` keeps the default ``create_type=True``. The
    ORM model declares it ``create_type=False`` so the running app never re-creates
    it (nothing else does).
  * ``songs_fill_genre`` trigger — denormalizes albums.genre onto new songs rows
    (originally f6a2b3c4d5e6); autogenerate does not manage triggers, so it lives
    only here. The one-time data backfill from that migration is intentionally
    omitted — a fresh DB has no rows.

Deliberately NOT created: the HNSW index on songs.embedding. It is dropped on the
live DB and its rebuild is P5b / gameplan 10.2 (scale RDS up, build out-of-band),
never the deploy pipeline. See deployment-gameplan.md.

The live RDS is migrated onto this chain with ``alembic stamp 45f91add221e`` at
cutover (gameplan 10.1), not by running this migration.
"""
from typing import Sequence, Union

import app.db.types
import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '45f91add221e'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector must exist before any Vector column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ``work_status_enum`` is created here by the albums.work_status column below
    # (SQLAlchemy emits CREATE TYPE for the first table that uses it). The ORM
    # model declares it create_type=False so the running app never re-creates it.
    op.create_table('artists',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bandcamp_band_id', sa.BigInteger(), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('band_name', sa.Text(), nullable=True),
    sa.Column('band_location', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bandcamp_band_id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('spotify_id', sa.Text(), nullable=False),
    sa.Column('display_name', sa.Text(), nullable=True),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('spotify_access_token', app.db.types.EncryptedString(), nullable=True),
    sa.Column('spotify_refresh_token', app.db.types.EncryptedString(), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('spotify_id')
    )
    op.create_table('albums',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('external_source_id', sa.BigInteger(), nullable=True),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('url', sa.Text(), nullable=True),
    sa.Column('duration', sa.Integer(), nullable=True),
    sa.Column('release_date', sa.Text(), nullable=True),
    sa.Column('artist_name', sa.Text(), nullable=True),
    sa.Column('artist_id', sa.Integer(), nullable=True),
    sa.Column('work_status', sa.Enum('pending', 'in_progress', 'completed', 'failed', name='work_status_enum'), nullable=True),
    sa.Column('image_url', sa.Text(), nullable=True),
    sa.Column('genre', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['artist_id'], ['artists.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('external_source_id'),
    sa.UniqueConstraint('url', name='uq_albums_url')
    )
    op.create_table('songs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('artist_name', sa.Text(), nullable=True),
    sa.Column('album_title', sa.Text(), nullable=True),
    sa.Column('album_id', sa.Integer(), nullable=True),
    sa.Column('embedding', pgvector.sqlalchemy.vector.VECTOR(dim=1280), nullable=True),
    sa.Column('is_candidate', sa.Boolean(), nullable=False),
    sa.Column('spotify_track_id', sa.Text(), nullable=True),
    sa.Column('genre', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['album_id'], ['albums.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('album_id', 'title', name='uq_songs_album_id_title'),
    sa.UniqueConstraint('spotify_track_id')
    )
    op.create_table('user_recommendations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('song_id', sa.Integer(), nullable=False),
    sa.Column('query_song_id', sa.Integer(), nullable=True),
    sa.Column('dispatch_date', sa.Date(), nullable=True),
    sa.Column('recommended_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['query_song_id'], ['songs.id'], ),
    sa.ForeignKeyConstraint(['song_id'], ['songs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_user_recommendations_user_date', 'user_recommendations', ['user_id', 'dispatch_date'], unique=False)
    op.create_table('user_top_songs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('song_id', sa.Integer(), nullable=True),
    sa.Column('spotify_track_id', sa.Text(), nullable=False),
    sa.Column('spotify_url', sa.Text(), nullable=True),
    sa.Column('image_url', sa.Text(), nullable=True),
    sa.Column('artist_name', sa.Text(), nullable=True),
    sa.Column('track_title', sa.Text(), nullable=True),
    sa.Column('album_title', sa.Text(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('genre', sa.Text(), nullable=True),
    sa.Column('snapshot_at', sa.DateTime(), nullable=True),
    sa.Column('used_as_query', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['song_id'], ['songs.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # Keep future scraper-inserted candidate songs self-populating their genre
    # from the parent album (originally f6a2b3c4d5e6). autogenerate does not
    # manage triggers, so this lives only in the baseline.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION songs_fill_genre_from_album() RETURNS trigger AS $$
        BEGIN
          IF NEW.genre IS NULL AND NEW.album_id IS NOT NULL THEN
            SELECT genre INTO NEW.genre FROM albums WHERE id = NEW.album_id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS songs_fill_genre ON songs")
    op.execute(
        """
        CREATE TRIGGER songs_fill_genre
        BEFORE INSERT OR UPDATE OF album_id, genre ON songs
        FOR EACH ROW EXECUTE FUNCTION songs_fill_genre_from_album()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS songs_fill_genre ON songs")
    op.execute("DROP FUNCTION IF EXISTS songs_fill_genre_from_album()")
    op.drop_table('user_top_songs')
    op.drop_index('ix_user_recommendations_user_date', table_name='user_recommendations')
    op.drop_table('user_recommendations')
    op.drop_table('songs')
    op.drop_table('albums')
    op.drop_table('users')
    op.drop_table('artists')
    op.execute("DROP TYPE IF EXISTS work_status_enum")
    # The vector extension is left installed (harmless, may be shared).
