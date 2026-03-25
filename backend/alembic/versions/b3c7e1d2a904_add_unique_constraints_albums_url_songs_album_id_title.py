"""add unique constraints: albums.url and songs(album_id, title)

Revision ID: b3c7e1d2a904
Revises: ad1aecf9f82f
Create Date: 2026-03-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b3c7e1d2a904'
down_revision: Union[str, Sequence[str], None] = 'ad1aecf9f82f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Remap user_recommendations referencing duplicate songs to the surviving song id
    op.execute("""
        UPDATE user_recommendations ur
        SET song_id = keeper.id
        FROM (
            SELECT MIN(id) AS id, album_id, title
            FROM songs
            GROUP BY album_id, title
        ) AS keeper
        JOIN songs duplicate ON duplicate.album_id = keeper.album_id
                             AND duplicate.title = keeper.title
                             AND duplicate.id != keeper.id
        WHERE ur.song_id = duplicate.id
    """)
    # Remove duplicate songs, keeping the lowest id for each (album_id, title) pair
    op.execute("""
        DELETE FROM songs
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM songs
            GROUP BY album_id, title
        )
    """)
    op.create_unique_constraint('uq_albums_url', 'albums', ['url'])
    op.create_unique_constraint('uq_songs_album_id_title', 'songs', ['album_id', 'title'])


def downgrade() -> None:
    op.drop_constraint('uq_songs_album_id_title', 'songs', type_='unique')
    op.drop_constraint('uq_albums_url', 'albums', type_='unique')
