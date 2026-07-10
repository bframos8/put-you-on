"""
Unit tests for recommendation filtering in SpotifyIngestService.

Verifies that:
- The Spotify genre comes from UserTopSong.genre (query_entry), not Song.genre
- Candidates are filtered by Album.genre matching the Spotify genre
- Falls back to unfiltered results when genre filter returns fewer than `limit`
- No genre filter is applied when query_entry.genre is None
- Recommendations are deduped so every rec is a different artist (Album.artist_id),
  null artists collapse to one slot, and fewer than `limit` recs are returned
  when too few distinct artists are available.
"""

from unittest.mock import MagicMock, patch

import pytest

# Env vars must be set before app imports
import os
os.environ.setdefault("SESSION_SECRET", "test-secret-for-unit-tests-only")
os.environ.setdefault("SPOTIFY_CLIENT_ID", "test_client_id")
os.environ.setdefault("SPOTIFY_CLIENT_SECRET", "test_client_secret")
os.environ.setdefault("POSTGRES_DB", "test_db")
os.environ.setdefault("POSTGRES_USER", "test_user")
os.environ.setdefault("POSTGRES_PASSWORD", "test_pass")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from app.db.models import Album, Song, UserRecommendation, UserTopSong


def make_service():
    """Return a SpotifyIngestService with __init__ skipped."""
    with patch(
        "app.services.spotify_ingest_service.SpotifyIngestService.__init__",
        return_value=None,
    ):
        from app.services.spotify_ingest_service import SpotifyIngestService
        svc = SpotifyIngestService()
    return svc


def make_query_entry(genre: str | None, song: MagicMock) -> MagicMock:
    entry = MagicMock(spec=UserTopSong)
    entry.genre = genre
    entry.song = song
    entry.used_as_query = False
    return entry


def make_song(song_id: int, genre: str | None = None) -> MagicMock:
    s = MagicMock(spec=Song)
    s.id = song_id
    s.genre = genre
    s.embedding = [0.0] * 1280
    return s


def make_db(query_entry, genre_pool=None, fallback_pool=None):
    """
    Build a mock DB session whose query chain returns controlled pools.

    base_query is db.query(Song, Album.artist_id).outerjoin(...)
    .options(selectinload(Song.album)).filter(...)*3 .order_by(...); the genre
    branch then adds .filter(Album.genre==...) and the fallback branch does not.
    Both end in .limit(pool_size).all(). We return `genre_pool` on the first
    .all() call and `fallback_pool` on the second.

    Pools are lists of (Song, artist_id) tuples, matching the real rows.
    """
    db = MagicMock()
    subq = MagicMock()

    uts_chain = MagicMock()
    uts_chain.filter.return_value.filter.return_value.first.return_value = query_entry
    # Some tests call .filter(...).first() with a single filter; support both.
    uts_chain.filter.return_value.first.return_value = query_entry

    base = MagicMock()
    base.outerjoin.return_value = base
    base.options.return_value = base
    base.filter.return_value = base
    base.order_by.return_value = base
    pools = [p for p in (genre_pool, fallback_pool) if p is not None]
    base.limit.return_value.all.side_effect = pools if pools else [[]]

    song_chain = base

    def q(*models):
        model = models[0]
        if model is UserTopSong:
            return uts_chain
        if model is Song:
            return song_chain
        # db.query(UserRecommendation.song_id) → subquery
        c = MagicMock()
        c.filter.return_value.subquery.return_value = subq
        return c

    db.query.side_effect = q
    return db


def run(svc, db):
    from app.services.spotify_ingest_service import SpotifyIngestService
    return SpotifyIngestService.query_recommendations(svc, user=MagicMock(id=1), db=db)


# ─────────────────────────────────────────────────────────────────────────────

class TestDedupeByArtist:
    """The pure _dedupe_by_artist helper: one song per artist, in order."""

    def setup_method(self):
        self.svc = make_service()

    def dedupe(self, pool, limit=10):
        from app.services.spotify_ingest_service import SpotifyIngestService
        return SpotifyIngestService._dedupe_by_artist(pool, limit)

    def test_keeps_first_song_per_artist(self):
        a, b, c = make_song(1), make_song(2), make_song(3)
        # b shares artist 100 with a; only the first (a) survives.
        pool = [(a, 100), (b, 100), (c, 200)]
        assert self.dedupe(pool, limit=10) == [a, c]

    def test_null_artists_collapse_to_one(self):
        a, b, c = make_song(1), make_song(2), make_song(3)
        pool = [(a, None), (b, None), (c, 200)]
        # Only the first null-artist song is kept.
        assert self.dedupe(pool, limit=10) == [a, c]

    def test_stops_at_limit(self):
        pool = [(make_song(i), i) for i in range(20)]
        assert len(self.dedupe(pool, limit=10)) == 10

    def test_returns_fewer_when_too_few_distinct_artists(self):
        a, b, c = make_song(1), make_song(2), make_song(3)
        # All three share one artist → only one rec.
        pool = [(a, 100), (b, 100), (c, 100)]
        assert self.dedupe(pool, limit=10) == [a]

    def test_preserves_similarity_order(self):
        a, b, c = make_song(1), make_song(2), make_song(3)
        pool = [(a, 10), (b, 20), (c, 30)]
        assert self.dedupe(pool, limit=10) == [a, b, c]


class TestGenreFilteringUsesQueryEntryGenre:
    """genre comes from UserTopSong (query_entry), not from Song.genre"""

    def test_genre_from_query_entry_not_song(self):
        """
        Even if Song.genre is None, a non-None UserTopSong.genre triggers
        the genre-filtered query and its pool is used.
        """
        svc = make_service()
        query_song = make_song(1, genre=None)  # Song.genre is None
        query_entry = make_query_entry(genre="hip-hop-rap", song=query_song)

        # 10 distinct artists so the genre branch satisfies `limit` and the
        # fallback is not triggered.
        genre_pool = [(make_song(i), i) for i in range(2, 12)]
        db = make_db(query_entry, genre_pool=genre_pool)

        _, results = run(svc, db)
        assert results == [song for song, _ in genre_pool]

    def test_no_genre_filter_when_query_entry_genre_is_none(self):
        """When UserTopSong.genre is None, skip genre filter; use base query."""
        svc = make_service()
        query_song = make_song(1, genre="hip-hop-rap")  # ignored
        query_entry = make_query_entry(genre=None, song=query_song)

        fallback_pool = [(make_song(i), i) for i in range(2, 12)]  # 10 distinct
        db = make_db(query_entry, fallback_pool=fallback_pool)

        _, results = run(svc, db)
        assert results == [song for song, _ in fallback_pool]

    def test_falls_back_when_genre_pool_has_too_few_artists(self):
        """
        Genre pool that dedupes to fewer than `limit` distinct artists triggers
        the unfiltered fallback, whose result replaces the genre result.
        """
        svc = make_service()
        query_song = make_song(1)
        query_entry = make_query_entry(genre="rock", song=query_song)

        # Genre pool: 2 songs but same artist → 1 distinct, well under limit=10.
        genre_pool = [(make_song(2), 100), (make_song(3), 100)]
        fallback_pool = [(make_song(i), i) for i in range(10, 20)]  # 10 distinct
        db = make_db(query_entry, genre_pool=genre_pool, fallback_pool=fallback_pool)

        _, results = run(svc, db)
        assert results == [song for song, _ in fallback_pool]

    def test_used_as_query_flag_set(self):
        """query_entry.used_as_query must be set to True."""
        svc = make_service()
        query_song = make_song(1)
        query_entry = make_query_entry(genre=None, song=query_song)
        db = make_db(query_entry, fallback_pool=[])

        run(svc, db)
        assert query_entry.used_as_query is True

    def test_returns_query_song_and_results(self):
        """Return value is (query_song, results) with deduped songs."""
        svc = make_service()
        query_song = make_song(42)
        query_entry = make_query_entry(genre=None, song=query_song)
        rec = make_song(99)
        db = make_db(query_entry, fallback_pool=[(rec, 7)])

        returned_song, returned_results = run(svc, db)
        assert returned_song is query_song
        assert returned_results == [rec]

    def test_dedupes_across_returned_recs(self):
        """End-to-end: repeated artists in the pool collapse in the result."""
        svc = make_service()
        query_song = make_song(1)
        query_entry = make_query_entry(genre=None, song=query_song)

        a, b, c = make_song(2), make_song(3), make_song(4)
        fallback_pool = [(a, 100), (b, 100), (c, 200)]  # b dropped (artist 100)
        db = make_db(query_entry, fallback_pool=fallback_pool)

        _, results = run(svc, db)
        assert results == [a, c]


class TestRecycleWhenExhausted:
    """A6: when every processed candidate has been used as a query seed,
    query_recommendations recycles them (reset used_as_query) instead of
    leaving no seed — no re-fetch/rebuild."""

    def test_recycles_seeds_when_all_used(self):
        svc = make_service()
        query_song = make_song(1)
        entry = make_query_entry(genre=None, song=query_song)
        db = make_db(entry, fallback_pool=[(make_song(2), 7)])

        # First seed select finds nothing (all rows already queried); after the
        # recycle reset, the re-pick returns the recycled entry.
        uts_chain = db.query(UserTopSong)
        uts_chain.filter.return_value.first.side_effect = [None, entry]

        returned_song, _ = run(svc, db)

        # It issued the bulk reset (the recycle) and then proceeded normally.
        uts_chain.filter.return_value.update.assert_called_once()
        assert returned_song is query_song
        assert entry.used_as_query is True


class TestSnapshotIsStale:
    """A6: pool exhaustion is no longer 'stale' — only empty or unfinished."""

    def _db(self, total, processed):
        db = MagicMock()
        row = MagicMock()
        row.total = total
        row.processed = processed
        db.query.return_value.filter.return_value.one.return_value = row
        return db

    def test_empty_snapshot_is_stale(self):
        svc = make_service()
        assert svc.snapshot_is_stale(MagicMock(id=1), self._db(0, 0)) is True

    def test_unprocessed_rows_are_stale(self):
        svc = make_service()
        assert svc.snapshot_is_stale(MagicMock(id=1), self._db(10, 7)) is True

    def test_all_processed_and_queried_is_not_stale(self):
        # Formerly all_queried → stale (rebuild). Now it's not stale; the seed
        # pool is recycled by query_recommendations instead.
        svc = make_service()
        assert svc.snapshot_is_stale(MagicMock(id=1), self._db(10, 10)) is False
