"""
P4 regression: top-song ingest lookups are batched into a single Song query
instead of one query per track. See agents/p3-p4-query-cleanups-fix-plan.md.

(P3's eager-loading can't be meaningfully asserted against a mocked Session —
loader options are inert on a MagicMock and need a real Postgres/pgvector DB to
observe query counts — so it's covered by the existing route tests staying green.)
"""

from unittest.mock import MagicMock

from app.db.models import Song
from app.services.spotify_ingest_service import SpotifyIngestService


def _track(i: int) -> dict:
    return {
        "id": f"track{i}",
        "external_urls": {"spotify": f"https://open.spotify.com/track/{i}"},
        "album": {"name": f"Album {i}", "images": [{"url": f"http://img/{i}"}]},
        "artists": [{"name": f"Artist {i}"}],
        "name": f"Song {i}",
    }


def _song_lookup_calls(db: MagicMock) -> list:
    return [c for c in db.query.call_args_list if c.args and c.args[0] is Song]


class TestTopSongLookupBatching:
    def test_add_user_top_songs_batches_song_lookup(self, mock_user):
        svc = SpotifyIngestService()  # __init__ no-op'd by the patch_startup fixture
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []  # no existing songs

        svc.add_user_top_songs([_track(i) for i in range(10)], mock_user, db)

        assert len(_song_lookup_calls(db)) == 1  # one batched IN(...) query, not 10

    def test_add_user_top_songs_handles_empty_tracks(self, mock_user):
        svc = SpotifyIngestService()
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        svc.add_user_top_songs([], mock_user, db)

        assert len(_song_lookup_calls(db)) == 0  # no track ids → no Song query
