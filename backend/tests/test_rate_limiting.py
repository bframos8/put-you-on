"""
Rate-limiting tests for /api/v1/auth and /api/v1/items endpoints.

Design notes
------------
slowapi stores hit-counts in an in-memory store that is shared across the
singleton `app`.  To avoid test-order dependencies we create a *fresh*
TestClient (and therefore a fresh lifespan / state) for each class, and we
reset the limiter storage between tests via the _reset_limits() helper.

Limits configured in the app:
  POST /auth/spotify/login    20 / minute  (by IP)
  POST /auth/spotify/callback 10 / minute  (by IP)
  GET  /auth/me               60 / minute  (by session key)
  GET  /auth/logout           10 / minute  (by session key)
  GET  /items/song_recs/       2 / minute  (by session key)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reset_limits(app) -> None:
    """Clear slowapi's in-memory hit counters so tests start from zero."""
    try:
        limiter = app.state.limiter
        limiter._storage.reset()  # works for MemoryStorage
    except Exception:
        pass  # if storage backend doesn't support reset, tests may still pass


def _make_fresh_client(mock_db, mock_ingest):
    """
    Build an isolated TestClient with its own lifespan so rate-limit counts
    start fresh.  The patches must wrap the entire TestClient context.
    """
    from app.db.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mock_db

    ctx_patches = [
        patch("app.db.models.Base.metadata.create_all"),
        patch(
            "app.services.spotify_ingest_service.SpotifyIngestService.__init__",
            return_value=None,
        ),
        patch("app.db.database.engine.dispose"),
    ]
    return ctx_patches, app


# ══════════════════════════════════════════════════════════════════════════════
# /auth/spotify/login  — limit: 20 / minute
# ══════════════════════════════════════════════════════════════════════════════

class TestLoginRateLimit:
    def test_first_request_is_allowed(self, client):
        with patch(
            "app.api.v1.auth.auth_service.get_auth_url",
            return_value=("https://accounts.spotify.com/authorize?state=s0", "s0"),
        ):
            resp = client.get("/api/v1/auth/spotify/login", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_twenty_requests_are_all_allowed(self, mock_db, mock_ingest):
        """20 requests within the window must all succeed (below the limit)."""
        ctx_patches, app = _make_fresh_client(mock_db, mock_ingest)
        with (
            ctx_patches[0],
            ctx_patches[1],
            ctx_patches[2],
        ):
            with TestClient(app, raise_server_exceptions=False) as c:
                _reset_limits(app)
                app.state.ingest_service = mock_ingest
                statuses = []
                for i in range(20):
                    with patch(
                        "app.api.v1.auth.auth_service.get_auth_url",
                        return_value=(f"https://accounts.spotify.com/authorize?state=s{i}", f"s{i}"),
                    ):
                        statuses.append(
                            c.get("/api/v1/auth/spotify/login", follow_redirects=False).status_code
                        )
        app.dependency_overrides.clear()
        assert all(s in (302, 307) for s in statuses)

    def test_twenty_first_request_is_rate_limited(self, mock_db, mock_ingest):
        """The 21st request in the same window must return 429."""
        ctx_patches, app = _make_fresh_client(mock_db, mock_ingest)
        with (
            ctx_patches[0],
            ctx_patches[1],
            ctx_patches[2],
        ):
            with TestClient(app, raise_server_exceptions=False) as c:
                _reset_limits(app)
                app.state.ingest_service = mock_ingest
                statuses = []
                for i in range(21):
                    with patch(
                        "app.api.v1.auth.auth_service.get_auth_url",
                        return_value=(f"https://accounts.spotify.com/authorize?state=rl{i}", f"rl{i}"),
                    ):
                        statuses.append(
                            c.get("/api/v1/auth/spotify/login", follow_redirects=False).status_code
                        )
        app.dependency_overrides.clear()
        assert statuses[-1] == 429


# ══════════════════════════════════════════════════════════════════════════════
# /items/song_recs/  — limit: 2 / minute  (tightest limit in the app)
# ══════════════════════════════════════════════════════════════════════════════

class TestSongRecsRateLimit:
    def test_two_requests_are_allowed(self, mock_db, mock_ingest, mock_user, valid_session):
        ctx_patches, app = _make_fresh_client(mock_db, mock_ingest)
        mock_ingest.snapshot_is_stale.return_value = False

        with (
            ctx_patches[0],
            ctx_patches[1],
            ctx_patches[2],
        ):
            with TestClient(app, raise_server_exceptions=False) as c:
                _reset_limits(app)
                app.state.ingest_service = mock_ingest
                statuses = []
                for _ in range(2):
                    with patch(
                        "app.api.v1.songs.auth_service.refresh_tokens",
                        new=AsyncMock(return_value=mock_user),
                    ):
                        statuses.append(
                            c.get(
                                "/api/v1/items/song_recs/",
                                cookies={"session": valid_session},
                            ).status_code
                        )
        app.dependency_overrides.clear()
        assert all(s == 200 for s in statuses)

    def test_third_request_is_rate_limited(self, mock_db, mock_ingest, mock_user, valid_session):
        ctx_patches, app = _make_fresh_client(mock_db, mock_ingest)
        mock_ingest.snapshot_is_stale.return_value = False

        with (
            ctx_patches[0],
            ctx_patches[1],
            ctx_patches[2],
        ):
            with TestClient(app, raise_server_exceptions=False) as c:
                _reset_limits(app)
                app.state.ingest_service = mock_ingest
                statuses = []
                for _ in range(3):
                    with patch(
                        "app.api.v1.songs.auth_service.refresh_tokens",
                        new=AsyncMock(return_value=mock_user),
                    ):
                        statuses.append(
                            c.get(
                                "/api/v1/items/song_recs/",
                                cookies={"session": valid_session},
                            ).status_code
                        )
        app.dependency_overrides.clear()
        assert statuses[-1] == 429


# ══════════════════════════════════════════════════════════════════════════════
# /auth/logout  — limit: 10 / minute
# ══════════════════════════════════════════════════════════════════════════════

class TestLogoutRateLimit:
    def test_eleventh_logout_is_rate_limited(self, mock_db, mock_ingest, valid_session):
        ctx_patches, app = _make_fresh_client(mock_db, mock_ingest)

        with (
            ctx_patches[0],
            ctx_patches[1],
            ctx_patches[2],
        ):
            with TestClient(app, raise_server_exceptions=False) as c:
                _reset_limits(app)
                app.state.ingest_service = mock_ingest
                statuses = [
                    c.post(
                        "/api/v1/auth/logout",
                        cookies={"session": valid_session},
                        follow_redirects=False,
                    ).status_code
                    for _ in range(11)
                ]
        app.dependency_overrides.clear()
        assert statuses[-1] == 429
