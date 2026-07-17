"""
S4 regression: outbound Spotify HTTP calls must use an intentional, configured
timeout (SPOTIFY_HTTP_TIMEOUT, default 10.0s) rather than httpx's implicit 5s.

The rest of the suite mocks SpotifyAuthService at the method level, so the real
httpx.AsyncClient construction is never exercised there. These tests patch
httpx.AsyncClient directly and assert the configured timeout is passed for every
outbound call site.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import spotify_auth_service
from app.services.spotify_auth_service import SpotifyAuthService


def _fake_client(json_payload: dict) -> MagicMock:
    """An AsyncClient stand-in usable as an async context manager."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = MagicMock(return_value=json_payload)
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)
    return client


def test_default_timeout_is_ten_seconds():
    assert spotify_auth_service.SPOTIFY_HTTP_TIMEOUT == 10.0


@pytest.mark.asyncio
async def test_exchange_code_uses_configured_timeout():
    svc = SpotifyAuthService()
    fake = _fake_client({"access_token": "x"})
    with patch.object(spotify_auth_service.httpx, "AsyncClient", return_value=fake) as mk:
        await svc.exchange_code("code123")
    mk.assert_called_once_with(timeout=spotify_auth_service.SPOTIFY_HTTP_TIMEOUT)


@pytest.mark.asyncio
async def test_get_top_tracks_uses_configured_timeout():
    svc = SpotifyAuthService()
    fake = _fake_client({"items": []})
    with patch.object(spotify_auth_service.httpx, "AsyncClient", return_value=fake) as mk:
        await svc.get_top_tracks("token")
    mk.assert_called_once_with(timeout=spotify_auth_service.SPOTIFY_HTTP_TIMEOUT)


@pytest.mark.asyncio
async def test_get_spotify_profile_uses_configured_timeout():
    svc = SpotifyAuthService()
    fake = _fake_client({"id": "abc"})
    with patch.object(spotify_auth_service.httpx, "AsyncClient", return_value=fake) as mk:
        await svc.get_spotify_profile("token")
    mk.assert_called_once_with(timeout=spotify_auth_service.SPOTIFY_HTTP_TIMEOUT)


@pytest.mark.asyncio
async def test_refresh_tokens_uses_configured_timeout(mock_db):
    from datetime import datetime, timedelta

    svc = SpotifyAuthService()
    user = MagicMock()
    # Force the refresh path: token already expired.
    user.token_expires_at = datetime.now() - timedelta(hours=1)
    user.spotify_refresh_token = "refresh"
    fake = _fake_client(
        {"access_token": "new", "refresh_token": "new_refresh", "expires_in": 3600}
    )
    with patch.object(spotify_auth_service.httpx, "AsyncClient", return_value=fake) as mk:
        await svc.refresh_tokens(mock_db, user)
    mk.assert_called_once_with(timeout=spotify_auth_service.SPOTIFY_HTTP_TIMEOUT)
