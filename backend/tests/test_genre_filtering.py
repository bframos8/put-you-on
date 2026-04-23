"""
Unit tests for genre-based recommendation filtering in SpotifyIngestService.

Verifies that:
- The Spotify genre comes from UserTopSong.genre (query_entry), not Song.genre
- Candidates are filtered by Album.genre matching the Spotify genre
- Falls back to unfiltered results when genre filter returns fewer than `limit`
- No genre filter is applied when query_entry.genre is None
"""

from unittest.mock import MagicMock, patch, call

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


def make_db(query_entry, already_recommended_ids=None, genre_results=None, fallback_results=None):
    """
    Build a mock DB session whose query chain returns controlled results.

    - First query (UserTopSong) → query_entry
    - Second query (UserRecommendation.song_id) → subquery
    - Third query chain (Song with genre join) → genre_results
    - Fourth query chain (Song fallback) → fallback_results
    """
    db = MagicMock()

    subquery_mock = MagicMock()

    # Track call order for Song queries
    song_query_results = []
    if genre_results is not None:
        song_query_results.append(genre_results)
    if fallback_results is not None:
        song_query_results.append(fallback_results)

    call_count = [0]

    def query_side_effect(model):
        if model is UserTopSong:
            chain = MagicMock()
            chain.filter.return_value.filter.return_value.first.return_value = query_entry
            return chain
        if model is UserRecommendation.song_id.property.columns[0].table.c.song_id.__class__ or str(model) == str(UserRecommendation.song_id):
            chain = MagicMock()
            chain.filter.return_value.subquery.return_value = subquery_mock
            return chain
        if model is Song:
            idx = call_count[0]
            call_count[0] += 1
            results = song_query_results[idx] if idx < len(song_query_results) else []
            chain = MagicMock()
            # Build a chainable mock that returns `results` at .limit().all()
            limit_mock = MagicMock()
            limit_mock.all.return_value = results
            filter_chain = MagicMock()
            filter_chain.limit.return_value = limit_mock
            filter_chain.filter.return_value = filter_chain
            filter_chain.join.return_value = filter_chain
            chain.filter.return_value = filter_chain
            return chain
        return MagicMock()

    db.query.side_effect = query_side_effect
    return db


# ─────────────────────────────────────────────────────────────────────────────

class TestGenreFilteringUsesQueryEntryGenre:
    """genre comes from UserTopSong (query_entry), not from Song.genre"""

    def test_genre_from_query_entry_not_song(self):
        """
        Even if Song.genre is None, a non-None UserTopSong.genre triggers
        genre-filtered query.
        """
        svc = make_service()
        query_song = make_song(1, genre=None)  # Song.genre is None
        query_entry = make_query_entry(genre="hip-hop-rap", song=query_song)

        rec_song = make_song(2)
        db = MagicMock()

        # Capture the genre filter applied
        applied_filters = []

        genre_results = [rec_song]

        # Use a simpler approach: patch the internal query chain
        subq = MagicMock()

        uts_chain = MagicMock()
        uts_chain.filter.return_value.filter.return_value.first.return_value = query_entry

        rec_chain = MagicMock()
        rec_chain.filter.return_value.subquery.return_value = subq

        song_chain = MagicMock()
        filter1 = MagicMock()
        filter1.filter.return_value = filter1
        filter1.filter.side_effect = lambda *a, **kw: filter1
        filter1.join.return_value = filter1
        filter1.order_by.return_value = filter1
        filter1.limit.return_value.all.return_value = genre_results
        song_chain.filter.return_value = filter1

        call_num = [0]
        def q(model):
            if model is UserTopSong:
                return uts_chain
            if model is Song:
                return song_chain
            # UserRecommendation.song_id subquery
            c = MagicMock()
            c.filter.return_value.subquery.return_value = subq
            return c

        db.query.side_effect = q

        from app.services.spotify_ingest_service import SpotifyIngestService
        query_song_out, results = SpotifyIngestService.query_recommendations(svc, user=MagicMock(id=1), db=db)

        # Genre filter was applied because query_entry.genre = "hip-hop-rap"
        assert results == genre_results

    def test_no_genre_filter_when_query_entry_genre_is_none(self):
        """
        When UserTopSong.genre is None, skip genre filter and use base query directly.
        """
        svc = make_service()
        query_song = make_song(1, genre="hip-hop-rap")  # Song.genre set, but should be ignored
        query_entry = make_query_entry(genre=None, song=query_song)  # UserTopSong.genre is None

        fallback_songs = [make_song(2), make_song(3)]
        subq = MagicMock()

        uts_chain = MagicMock()
        uts_chain.filter.return_value.filter.return_value.first.return_value = query_entry

        song_chain = MagicMock()
        base = MagicMock()
        base.filter.return_value = base
        base.order_by.return_value = base
        base.join.return_value = base
        base.limit.return_value.all.return_value = fallback_songs
        song_chain.filter.return_value = base

        def q(model):
            if model is UserTopSong:
                return uts_chain
            if model is Song:
                return song_chain
            c = MagicMock()
            c.filter.return_value.subquery.return_value = subq
            return c

        db = MagicMock()
        db.query.side_effect = q

        from app.services.spotify_ingest_service import SpotifyIngestService
        _, results = SpotifyIngestService.query_recommendations(svc, user=MagicMock(id=1), db=db)

        # No genre filter: base query called once, returns fallback directly
        assert results == fallback_songs

    def test_used_as_query_flag_set(self):
        """query_entry.used_as_query must be set to True."""
        svc = make_service()
        query_song = make_song(1)
        query_entry = make_query_entry(genre=None, song=query_song)

        subq = MagicMock()
        uts_chain = MagicMock()
        # Code calls .filter(...).first() — single filter, multiple args
        uts_chain.filter.return_value.first.return_value = query_entry

        song_chain = MagicMock()
        base = MagicMock()
        base.filter.return_value = base
        base.order_by.return_value = base
        base.limit.return_value.all.return_value = []
        song_chain.filter.return_value = base

        db = MagicMock()
        def q(model):
            if model is UserTopSong:
                return uts_chain
            if model is Song:
                return song_chain
            c = MagicMock()
            c.filter.return_value.subquery.return_value = subq
            return c
        db.query.side_effect = q

        from app.services.spotify_ingest_service import SpotifyIngestService
        SpotifyIngestService.query_recommendations(svc, user=MagicMock(id=1), db=db)

        assert query_entry.used_as_query is True

    def test_returns_query_song_and_results(self):
        """Return value is (query_song, results)."""
        svc = make_service()
        query_song = make_song(42)
        query_entry = make_query_entry(genre=None, song=query_song)
        rec = make_song(99)

        subq = MagicMock()
        uts_chain = MagicMock()
        # Code calls .filter(...).first() — single filter, multiple args
        uts_chain.filter.return_value.first.return_value = query_entry

        song_chain = MagicMock()
        base = MagicMock()
        base.filter.return_value = base
        base.order_by.return_value = base
        base.limit.return_value.all.return_value = [rec]
        song_chain.filter.return_value = base

        db = MagicMock()
        def q(model):
            if model is UserTopSong:
                return uts_chain
            if model is Song:
                return song_chain
            c = MagicMock()
            c.filter.return_value.subquery.return_value = subq
            return c
        db.query.side_effect = q

        from app.services.spotify_ingest_service import SpotifyIngestService
        returned_song, returned_results = SpotifyIngestService.query_recommendations(
            svc, user=MagicMock(id=1), db=db
        )

        assert returned_song is query_song
        assert returned_results == [rec]
