"""
Tests for the ingest failure handling added in gameplan 10.5.

The bug these guard against: a seed whose audio could not be fetched stayed
`song_id IS NULL` forever, `snapshot_is_stale` read that as "needs rebuilding", and
every request re-fetched the user's top tracks from Spotify, wiped and rewrote the seed
set, and re-ran the whole failing ingest. An infinite loop, invisible because the
failures are logged as warnings rather than raised.

Three pieces have to hold for that to stay fixed, and each is easy to break
independently:
  - failures are counted and become terminal at INGEST_MAX_ATTEMPTS
  - refreshing the snapshot does NOT reset those counts for tracks that survive
  - with no usable seed, query_recommendations raises a typed error rather than
    AttributeError on None
"""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.db.models import UserTopSong
from app.services.spotify_ingest_service import (
    INGEST_MAX_ATTEMPTS,
    NoUsableSeedsError,
)


def make_service():
    with patch(
        "app.services.spotify_ingest_service.SpotifyIngestService.__init__",
        return_value=None,
    ):
        from app.services.spotify_ingest_service import SpotifyIngestService
        svc = SpotifyIngestService()
    return svc


def make_row(**kwargs):
    row = MagicMock(spec=UserTopSong)
    row.ingest_attempts = kwargs.get("ingest_attempts", 0)
    row.ingest_failed_at = kwargs.get("ingest_failed_at")
    row.ingest_error = kwargs.get("ingest_error")
    row.track_title = kwargs.get("track_title", "A Song")
    row.spotify_track_id = kwargs.get("spotify_track_id", "track1")
    row.song_id = kwargs.get("song_id")
    row.used_as_query = kwargs.get("used_as_query", False)
    return row


class TestRecordFailure:
    def test_first_failure_counts_but_does_not_retire(self):
        svc = make_service()
        row = make_row()
        svc._record_failure(row, RuntimeError("download failed"), MagicMock())
        assert row.ingest_attempts == 1
        assert row.ingest_failed_at is None, "one failure must stay retryable"

    def test_retires_at_the_cap(self):
        svc = make_service()
        row = make_row(ingest_attempts=INGEST_MAX_ATTEMPTS - 1)
        svc._record_failure(row, RuntimeError("nope"), MagicMock())
        assert row.ingest_attempts == INGEST_MAX_ATTEMPTS
        assert row.ingest_failed_at is not None, (
            "reaching the cap must set ingest_failed_at — that is what makes "
            "snapshot_is_stale stop re-queueing the ingest"
        )

    def test_error_is_truncated(self):
        # spotdl tracebacks run to kilobytes and this string is shown to the user.
        svc = make_service()
        row = make_row()
        svc._record_failure(row, RuntimeError("x" * 5000), MagicMock())
        assert len(row.ingest_error) <= 500

    def test_failure_is_committed(self):
        # The processing branch rolls back before recording, so the counter has to be
        # committed separately or it is lost with the rolled-back transaction.
        svc = make_service()
        db = MagicMock()
        svc._record_failure(make_row(), RuntimeError("x"), db)
        db.commit.assert_called_once()


class TestSnapshotRefreshPreservesState:
    """The attempt cap is worthless if refreshing the snapshot resets the counters.

    add_user_top_songs used to be an unconditional delete-then-insert, so a failed seed
    came back with ingest_attempts=0 on every pass and could never reach the cap.
    """

    def _track(self, track_id, title="T"):
        return {
            "id": track_id,
            "external_urls": {"spotify": f"https://open.spotify.com/track/{track_id}"},
            "album": {"images": [{"url": "http://img"}], "name": "Album"},
            "artists": [{"name": "Artist"}],
            "name": title,
            "duration_ms": 1000,
        }

    def _db(self, existing_rows):
        db = MagicMock()
        # First query(UserTopSong) -> existing rows; second query(Song) -> corpus matches.
        db.query.return_value.filter.return_value.all.side_effect = [existing_rows, []]
        return db

    def test_surviving_track_keeps_its_attempts(self):
        svc = make_service()
        survivor = make_row(spotify_track_id="track1", ingest_attempts=2)
        db = self._db([survivor])

        svc.add_user_top_songs([self._track("track1")], MagicMock(id=1), db)

        assert survivor.ingest_attempts == 2, (
            "refreshing the snapshot must not reset attempts for a track that is "
            "still in the user's top tracks, or the cap never accumulates"
        )
        db.delete.assert_not_called()

    def test_surviving_track_keeps_terminal_failure(self):
        svc = make_service()
        failed_at = datetime(2026, 9, 25, 12, 0, 0)
        survivor = make_row(
            spotify_track_id="track1",
            ingest_attempts=INGEST_MAX_ATTEMPTS,
            ingest_failed_at=failed_at,
        )
        db = self._db([survivor])

        svc.add_user_top_songs([self._track("track1")], MagicMock(id=1), db)

        assert survivor.ingest_failed_at == failed_at

    def test_surviving_track_keeps_used_as_query(self):
        # A6 walks the seed pool via used_as_query; wiping it lost its place.
        svc = make_service()
        survivor = make_row(spotify_track_id="track1", used_as_query=True)
        db = self._db([survivor])

        svc.add_user_top_songs([self._track("track1")], MagicMock(id=1), db)

        assert survivor.used_as_query is True

    def test_departed_track_is_deleted(self):
        svc = make_service()
        gone = make_row(spotify_track_id="old_track")
        db = self._db([gone])

        svc.add_user_top_songs([self._track("new_track")], MagicMock(id=1), db)

        db.delete.assert_called_once_with(gone)

    def test_metadata_is_refreshed_on_survivors(self):
        svc = make_service()
        survivor = make_row(spotify_track_id="track1", track_title="Old Title")
        db = self._db([survivor])

        svc.add_user_top_songs([self._track("track1", title="New Title")], MagicMock(id=1), db)

        assert survivor.track_title == "New Title"


class TestNoUsableSeedsGuard:
    def test_raises_typed_error_instead_of_attribute_error(self):
        """With every seed failed, there is no query entry.

        Before 10.5 this was unreachable, because an unprocessed snapshot always counted
        as stale and got re-ingested first. Making failures terminal makes it reachable,
        and without the guard the next line does `None.song` → AttributeError → 500,
        which the frontend swallows, leaving a blank page and no explanation.
        """
        svc = make_service()
        db = MagicMock()
        db.execute.return_value = MagicMock()
        # No seed has a song behind it, and the A6 retry finds nothing either.
        db.query.return_value.filter.return_value.first.return_value = None
        db.query.return_value.filter.return_value.update.return_value = 0

        with pytest.raises(NoUsableSeedsError):
            svc.query_recommendations(MagicMock(id=1), db)
