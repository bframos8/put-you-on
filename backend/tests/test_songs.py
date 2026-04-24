"""
Tests for /api/v1/items/song_recs/ endpoint.

Auth strategy
-------------
Protected endpoint requires a valid session cookie.  We generate real tokens
with create_session() and let get_current_user run its actual DB-lookup logic
against the mocked Session.  Spotify API calls (refresh_tokens, get_top_tracks)
are mocked with AsyncMock.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import Song

RECS_URL = "/api/v1/items/song_recs/"


# ══════════════════════════════════════════════════════════════════════════════
# Auth gate — every request without a valid session must return 401
# ══════════════════════════════════════════════════════════════════════════════

class TestSongRecsAuthGate:
    def test_no_cookie_returns_401(self, client):
        resp = client.get(RECS_URL)
        assert resp.status_code == 401

    def test_garbage_cookie_returns_401(self, client):
        resp = client.get(RECS_URL, cookies={"session": "garbage.value.here"})
        assert resp.status_code == 401

    def test_tampered_session_returns_401(self, client):
        from app.core.session import create_session

        token = create_session(1)
        tampered = token[:15] + "TAMPERED" + token[23:]
        resp = client.get(RECS_URL, cookies={"session": tampered})
        assert resp.status_code == 401

    def test_session_for_deleted_user_returns_401(self, client, valid_session, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        resp = client.get(RECS_URL, cookies={"session": valid_session})
        assert resp.status_code == 401

    def test_wrong_secret_session_returns_401(self, client):
        from itsdangerous import URLSafeTimedSerializer

        bad_token = URLSafeTimedSerializer("wrong-secret").dumps(1, salt="session")
        resp = client.get(RECS_URL, cookies={"session": bad_token})
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# Happy path — authenticated requests
# ══════════════════════════════════════════════════════════════════════════════

class TestSongRecsHappyPath:
    def test_fresh_snapshot_returns_200(self, client, valid_session, mock_user, mock_ingest):
        mock_ingest.snapshot_is_stale.return_value = False

        with patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        assert resp.status_code == 200

    def test_response_has_required_top_level_fields(self, client, valid_session, mock_user, mock_ingest):
        mock_ingest.snapshot_is_stale.return_value = False

        with patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        data = resp.json()
        assert "query_title" in data
        assert "query_artist" in data
        assert "recommendations" in data
        assert isinstance(data["recommendations"], list)

    def test_recommendation_items_have_correct_schema(self, client, valid_session, mock_user, mock_ingest):
        mock_ingest.snapshot_is_stale.return_value = False

        with patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        rec = resp.json()["recommendations"][0]
        assert set(rec.keys()) == {"id", "title", "artist_name", "album_title", "image_url", "external_source_id", "album_url"}

    def test_query_song_metadata_is_correct(self, client, valid_session, mock_user, mock_ingest, mock_query_song):
        mock_ingest.snapshot_is_stale.return_value = False
        mock_ingest.query_recommendations.return_value = (mock_query_song, [])

        with patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        data = resp.json()
        assert data["query_title"] == mock_query_song.title
        assert data["query_artist"] == mock_query_song.artist_name

    def test_empty_recommendations_list_is_valid(self, client, valid_session, mock_user, mock_ingest, mock_query_song):
        mock_ingest.snapshot_is_stale.return_value = False
        mock_ingest.query_recommendations.return_value = (mock_query_song, [])

        with patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        assert resp.status_code == 200
        assert resp.json()["recommendations"] == []


# ══════════════════════════════════════════════════════════════════════════════
# Stale snapshot — triggers ingest pipeline
# ══════════════════════════════════════════════════════════════════════════════

class TestSongRecsStaleSnapshot:
    def test_stale_snapshot_calls_get_top_tracks(self, client, valid_session, mock_user, mock_ingest):
        mock_ingest.snapshot_is_stale.return_value = True

        with (
            patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)),
            patch("app.api.v1.songs.auth_service.get_top_tracks", new=AsyncMock(return_value=[])) as mock_tracks,
        ):
            client.get(RECS_URL, cookies={"session": valid_session})

        mock_tracks.assert_called_once_with(mock_user.spotify_access_token)

    def test_stale_snapshot_calls_add_user_top_songs(self, client, valid_session, mock_user, mock_ingest):
        mock_ingest.snapshot_is_stale.return_value = True

        with (
            patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)),
            patch("app.api.v1.songs.auth_service.get_top_tracks", new=AsyncMock(return_value=[])),
        ):
            client.get(RECS_URL, cookies={"session": valid_session})

        mock_ingest.add_user_top_songs.assert_called_once()

    def test_stale_snapshot_calls_process_top_tracks(self, client, valid_session, mock_user, mock_ingest):
        mock_ingest.snapshot_is_stale.return_value = True

        with (
            patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)),
            patch("app.api.v1.songs.auth_service.get_top_tracks", new=AsyncMock(return_value=[])),
        ):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        mock_ingest.process_top_tracks.assert_called_once()
        assert resp.status_code == 200

    def test_process_top_tracks_exception_returns_500(self, client, valid_session, mock_user, mock_ingest):
        mock_ingest.snapshot_is_stale.return_value = True
        mock_ingest.process_top_tracks.side_effect = RuntimeError("Audio processing failed")

        with (
            patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)),
            patch("app.api.v1.songs.auth_service.get_top_tracks", new=AsyncMock(return_value=[])),
        ):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        assert resp.status_code == 500
        assert "Audio processing failed" in resp.json()["detail"]

    def test_process_top_tracks_generic_exception_detail_propagated(self, client, valid_session, mock_user, mock_ingest):
        mock_ingest.snapshot_is_stale.return_value = True
        mock_ingest.process_top_tracks.side_effect = Exception("spotdl crashed")

        with (
            patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)),
            patch("app.api.v1.songs.auth_service.get_top_tracks", new=AsyncMock(return_value=[])),
        ):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        assert resp.status_code == 500
        assert "spotdl crashed" in resp.json().get("detail", "")


# ══════════════════════════════════════════════════════════════════════════════
# Edge cases in recommendation data
# ══════════════════════════════════════════════════════════════════════════════

class TestSongRecsEdgeCases:
    def test_song_without_album_returns_null_album_fields(
        self, client, valid_session, mock_user, mock_ingest, mock_query_song
    ):
        """SongResponse.from_song handles song.album = None gracefully."""
        orphan = MagicMock(spec=Song)
        orphan.id = 300
        orphan.title = "Orphan Track"
        orphan.artist_name = "Ghost Artist"
        orphan.album_title = "Unknown"
        orphan.album = None  # no album relation

        mock_ingest.snapshot_is_stale.return_value = False
        mock_ingest.query_recommendations.return_value = (mock_query_song, [orphan])

        with patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        assert resp.status_code == 200
        rec = resp.json()["recommendations"][0]
        assert rec["image_url"] is None
        assert rec["external_source_id"] is None
        assert rec["album_url"] is None

    def test_null_query_song_causes_500(self, client, valid_session, mock_user, mock_ingest):
        """
        If query_recommendations returns (None, []), accessing None.title raises
        AttributeError — this is an unhandled exception, should produce 500.
        """
        mock_ingest.snapshot_is_stale.return_value = False
        mock_ingest.query_recommendations.return_value = (None, [])

        with patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        assert resp.status_code == 500

    def test_query_recommendations_exception_causes_500(self, client, valid_session, mock_user, mock_ingest):
        mock_ingest.snapshot_is_stale.return_value = False
        mock_ingest.query_recommendations.side_effect = Exception("DB vector query failed")

        with patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        assert resp.status_code == 500

    def test_refresh_tokens_updates_user_before_ingest(self, client, valid_session, mock_ingest):
        """refresh_tokens may return an updated User with new tokens; the refreshed
        user's access_token should be what get_top_tracks receives."""
        from app.db.models import User as UserModel
        from datetime import datetime

        refreshed_user = MagicMock(spec=UserModel)
        refreshed_user.id = 1
        refreshed_user.display_name = "Test User"
        refreshed_user.email = "test@example.com"
        refreshed_user.spotify_access_token = "brand_new_access_token"

        mock_ingest.snapshot_is_stale.return_value = True

        with (
            patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=refreshed_user)),
            patch("app.api.v1.songs.auth_service.get_top_tracks", new=AsyncMock(return_value=[])) as mock_tracks,
        ):
            client.get(RECS_URL, cookies={"session": valid_session})

        mock_tracks.assert_called_once_with("brand_new_access_token")

    def test_multiple_recommendations_returned(self, client, valid_session, mock_user, mock_ingest, mock_query_song):
        recs = []
        for i in range(5):
            s = MagicMock(spec=Song)
            s.id = 200 + i
            s.title = f"Rec {i}"
            s.artist_name = f"Artist {i}"
            s.album_title = f"Album {i}"
            from app.db.models import Album
            a = MagicMock(spec=Album)
            a.image_url = None
            a.external_source_id = None
            a.url = None
            s.album = a
            recs.append(s)

        mock_ingest.snapshot_is_stale.return_value = False
        mock_ingest.query_recommendations.return_value = (mock_query_song, recs)

        with patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)):
            resp = client.get(RECS_URL, cookies={"session": valid_session})

        assert resp.status_code == 200
        assert len(resp.json()["recommendations"]) == 5
