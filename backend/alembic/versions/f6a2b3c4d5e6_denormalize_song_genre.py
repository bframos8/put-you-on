"""denormalize album genre onto songs + sync trigger

Revision ID: f6a2b3c4d5e6
Revises: e5f1a2b3c4d5
Create Date: 2026-06-12 00:00:00.000000

P5b: the genre-filtered kNN branch filtered the *joined* ``albums.genre`` and so
could not use the ``songs`` HNSW vector index. Denormalize the album's genre onto
``songs.genre`` so the filter lives on the same table as the indexed vector
(pgvector iterative scan only accelerates same-table filters).

The backfill below is idempotent. On the live RDS it is run out-of-band first
(drop HNSW index -> batched backfill -> VACUUM ANALYZE -> rebuild index; see
agents/p5b-genre-denormalization-plan.md), so this UPDATE lands as a no-op and the
migration effectively just installs the sync trigger. On a fresh/empty DB the
UPDATE matches no rows and the trigger keeps future scraper inserts populated.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f6a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5f1a2b3c4d5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill candidate genre from the parent album. Idempotent: re-runs as a
    # no-op once filled. Scoped to fillable candidate rows only.
    op.execute(
        """
        UPDATE songs SET genre = a.genre
        FROM albums a
        WHERE songs.album_id = a.id
          AND songs.is_candidate = true
          AND songs.genre IS NULL
        """
    )

    # Keep future scraper-inserted candidates self-populating. The scraper is
    # external to this repo and always inserts the album (with its genre) before
    # its songs, so the BEFORE INSERT lookup always resolves. The NEW.genre IS NULL
    # guard means an explicitly-set genre (e.g. audio-classified user songs) is
    # never overridden.
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
    # Faithful reverse: candidate genres were NULL before this migration.
    op.execute("UPDATE songs SET genre = NULL WHERE is_candidate = true")
