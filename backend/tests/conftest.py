"""
Shared fixtures for the backend test suite.

Key design decisions
--------------------
* Env vars are injected at module load time (before any app import) so that
  - itsdangerous uses our test secret for session signing
  - load_dotenv in app/main.py cannot override them (it never sets override=True)
  - SQLAlchemy create_engine gets a valid-looking URL without connecting

* Heavy startup operations are patched for every test via an autouse fixture:
  - Base.metadata.create_all  →  no-op (avoids real Postgres)
  - SpotifyIngestService.__init__  →  no-op (avoids loading Essentia/TF model)
  - engine.dispose  →  no-op

* The `client` fixture creates a fresh TestClient per test, overrides `get_db`
  with a MagicMock Session, and replaces app.state.ingest_service with a mock
  AFTER the lifespan has run.

* Because `app` is a module-level singleton, `dependency_overrides` is cleared
  in fixture teardown so tests cannot bleed into each other.
"""

import os
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# ── Compatibility shim: starlette 0.27.0 passes app= to httpx.Client.__init__
# but httpx >= 0.25 removed that parameter.  Strip it so TestClient works.
_orig_httpx_client_init = httpx.Client.__init__


def _compat_httpx_client_init(self, *args, **kwargs):
    kwargs.pop("app", None)
    _orig_httpx_client_init(self, *args, **kwargs)


httpx.Client.__init__ = _compat_httpx_client_init

# ── 1. Inject env vars BEFORE any app module is imported ──────────────────────
os.environ["SESSION_SECRET"] = "test-secret-for-unit-tests-only"
os.environ["SPOTIFY_CLIENT_ID"] = "test_client_id"
os.environ["SPOTIFY_CLIENT_SECRET"] = "test_client_secret"
os.environ["FRONTEND_URL"] = "https://127.0.0.1:3000/dashboard"
os.environ["SPOTIFY_REDIRECT_URI"] = "http://localhost:8000/api/v1/auth/spotify/callback"
os.environ["POSTGRES_DB"] = "test_db"
os.environ["POSTGRES_USER"] = "test_user"
os.environ["POSTGRES_PASSWORD"] = "test_pass"
os.environ["POSTGRES_HOST"] = "localhost"
os.environ["POSTGRES_PORT"] = "5432"

# ── 2. Now safe to import app modules ─────────────────────────────────────────
from app.core.session import create_session  # noqa: E402
from app.db.models import Album, Song, User  # noqa: E402

FRONTEND = "https://127.0.0.1:3000/dashboard"


# ── 3. Patch heavy startup operations for the entire test session ─────────────

@pytest.fixture(autouse=True)
def patch_startup():
    """
    Prevent real DB table creation and Essentia model loading during lifespan.
    Applied to every test automatically.
    """
    with (
        patch("app.db.models.Base.metadata.create_all"),
        patch(
            "app.services.spotify_ingest_service.SpotifyIngestService.__init__",
            return_value=None,
        ),
        patch("app.db.database.engine.dispose"),
    ):
        yield


# ── 4. Domain object fixtures ─────────────────────────────────────────────────

@pytest.fixture
def mock_user():
    user = User(
        id=1,
        spotify_id="spotify_user_123",
        display_name="Test User",
        email="test@example.com",
        spotify_access_token="test_access_token",
        spotify_refresh_token="test_refresh_token",
        token_expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    return user


@pytest.fixture
def valid_session(mock_user):
    """A valid itsdangerous-signed session token for mock_user."""
    return create_session(mock_user.id)


@pytest.fixture
def mock_query_song():
    song = MagicMock(spec=Song)
    song.id = 100
    song.title = "Query Track"
    song.artist_name = "Query Artist"
    song.album_title = "Query Album"
    album = MagicMock(spec=Album)
    album.image_url = "https://img.example.com/q.jpg"
    album.external_source_id = 999
    album.url = "https://bandcamp.com/album/query"
    song.album = album
    return song


@pytest.fixture
def mock_rec_song():
    song = MagicMock(spec=Song)
    song.id = 200
    song.title = "Rec Track"
    song.artist_name = "Rec Artist"
    song.album_title = "Rec Album"
    album = MagicMock(spec=Album)
    album.image_url = "https://img.example.com/r.jpg"
    album.external_source_id = 888
    album.url = "https://bandcamp.com/album/rec"
    song.album = album
    return song


# ── 5. DB mock ────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db(mock_user):
    """
    Mock SQLAlchemy Session.
    Default: any query().filter().first() returns mock_user.
    Also supports the FOR UPDATE lock acquired by the recs endpoint:
        db.query(User).filter(...).with_for_update().one() -> mock_user
    Individual tests may override these (e.g. set .first.return_value = None).
    """
    db = MagicMock(spec=Session)
    db.query.return_value.filter.return_value.first.return_value = mock_user
    db.query.return_value.filter.return_value.with_for_update.return_value.one.return_value = mock_user
    return db


# ── 6. Ingest service mock ────────────────────────────────────────────────────

@pytest.fixture
def mock_ingest(mock_query_song, mock_rec_song):
    svc = MagicMock()
    svc.snapshot_is_stale.return_value = False
    svc.get_todays_dispatch.return_value = None
    svc.query_recommendations.return_value = (mock_query_song, [mock_rec_song])
    return svc


# ── 7. TestClient ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(mock_db, mock_ingest):
    """
    TestClient with:
    - get_db overridden with mock_db
    - app.state.ingest_service replaced with mock_ingest after lifespan runs
    - raise_server_exceptions=False so 500s come back as HTTP responses
    """
    from app.db.database import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: mock_db

    with TestClient(app, raise_server_exceptions=False) as c:
        # Lifespan has already run; swap in our mock ingest service.
        app.state.ingest_service = mock_ingest
        # Reset rate-limiter counters so each test starts from zero.
        from app.core.limiter import limiter
        limiter._storage.reset()
        yield c

    app.dependency_overrides.clear()
