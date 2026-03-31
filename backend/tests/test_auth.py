"""
Tests for /api/v1/auth endpoints.

OAuth approach
--------------
We cannot drive a real Spotify browser flow in CI, so:
  - get_auth_url / exchange_code / get_spotify_profile / upsert_user are mocked
    via unittest.mock.patch on the module-level auth_service instance.
  - Session tokens are generated with the real create_session() helper (same
    SECRET injected in conftest.py) and sent as cookies, so get_current_user
    runs its actual logic against the mocked DB.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PREFIX = "/api/v1/auth"
FRONTEND = "https://127.0.0.1:3000/dashboard"

# ── Helpers ───────────────────────────────────────────────────────────────────

def _seed_state(client, state: str = "valid_state") -> None:
    """Plant an OAuth state into app.state.oauth_states."""
    from app.main import app
    app.state.oauth_states[state] = time.time()


_mock_token_data = {
    "access_token": "spotify_access_tok",
    "refresh_token": "spotify_refresh_tok",
    "expires_in": 3600,
    "token_type": "Bearer",
}

_mock_profile = {
    "id": "sp_user_123",
    "display_name": "Test User",
    "email": "test@example.com",
}


# ══════════════════════════════════════════════════════════════════════════════
# /auth/spotify/login
# ══════════════════════════════════════════════════════════════════════════════

class TestSpotifyLogin:
    def test_redirects_to_spotify_authorize_url(self, client):
        with patch(
            "app.api.v1.auth.auth_service.get_auth_url",
            return_value=("https://accounts.spotify.com/authorize?foo=bar", "state_abc"),
        ):
            resp = client.get(f"{PREFIX}/spotify/login", follow_redirects=False)

        assert resp.status_code in (302, 307)
        assert "accounts.spotify.com" in resp.headers["location"]

    def test_oauth_state_is_stored(self, client):
        from app.main import app

        with patch(
            "app.api.v1.auth.auth_service.get_auth_url",
            return_value=("https://accounts.spotify.com/authorize?state=xyz", "xyz"),
        ):
            client.get(f"{PREFIX}/spotify/login", follow_redirects=False)

        assert "xyz" in app.state.oauth_states

    def test_multiple_logins_store_distinct_states(self, client):
        from app.main import app

        for i, state in enumerate(["s1", "s2", "s3"]):
            with patch(
                "app.api.v1.auth.auth_service.get_auth_url",
                return_value=(f"https://accounts.spotify.com/authorize?state={state}", state),
            ):
                client.get(f"{PREFIX}/spotify/login", follow_redirects=False)

        for state in ["s1", "s2", "s3"]:
            assert state in app.state.oauth_states


# ══════════════════════════════════════════════════════════════════════════════
# /auth/spotify/callback
# ══════════════════════════════════════════════════════════════════════════════

class TestSpotifyCallback:
    # ── happy path ────────────────────────────────────────────────────────────

    def test_valid_callback_redirects_to_frontend(self, client, mock_user):
        _seed_state(client)
        with (
            patch("app.api.v1.auth.auth_service.exchange_code", new=AsyncMock(return_value=_mock_token_data)),
            patch("app.api.v1.auth.auth_service.get_spotify_profile", new=AsyncMock(return_value=_mock_profile)),
            patch("app.api.v1.auth.auth_service.upsert_user", new=AsyncMock(return_value=mock_user)),
        ):
            resp = client.get(
                f"{PREFIX}/spotify/callback?code=authcode&state=valid_state",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert resp.headers["location"] == FRONTEND

    def test_valid_callback_sets_session_cookie(self, client, mock_user):
        _seed_state(client)
        with (
            patch("app.api.v1.auth.auth_service.exchange_code", new=AsyncMock(return_value=_mock_token_data)),
            patch("app.api.v1.auth.auth_service.get_spotify_profile", new=AsyncMock(return_value=_mock_profile)),
            patch("app.api.v1.auth.auth_service.upsert_user", new=AsyncMock(return_value=mock_user)),
        ):
            resp = client.get(
                f"{PREFIX}/spotify/callback?code=authcode&state=valid_state",
                follow_redirects=False,
            )

        assert "session" in resp.cookies

    def test_state_is_consumed_after_successful_callback(self, client, mock_user):
        """State tokens are single-use — re-using the same state should fail."""
        from app.main import app

        _seed_state(client, "one_time_state")
        with (
            patch("app.api.v1.auth.auth_service.exchange_code", new=AsyncMock(return_value=_mock_token_data)),
            patch("app.api.v1.auth.auth_service.get_spotify_profile", new=AsyncMock(return_value=_mock_profile)),
            patch("app.api.v1.auth.auth_service.upsert_user", new=AsyncMock(return_value=mock_user)),
        ):
            client.get(
                f"{PREFIX}/spotify/callback?code=code&state=one_time_state",
                follow_redirects=False,
            )

        assert "one_time_state" not in app.state.oauth_states

    # ── error / edge cases ────────────────────────────────────────────────────

    def test_unknown_state_redirects_with_state_mismatch_error(self, client):
        resp = client.get(
            f"{PREFIX}/spotify/callback?code=code&state=never_stored",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        assert "state_mismatch" in resp.headers["location"]

    def test_missing_state_param_redirects_with_error(self, client):
        resp = client.get(
            f"{PREFIX}/spotify/callback?code=code",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        assert "state_mismatch" in resp.headers["location"]

    def test_spotify_error_param_redirects_with_that_error(self, client):
        """If Spotify sends ?error=access_denied, we forward it."""
        _seed_state(client)
        resp = client.get(
            f"{PREFIX}/spotify/callback?error=access_denied&state=valid_state",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        assert "access_denied" in resp.headers["location"]

    def test_exchange_code_failure_redirects_with_auth_failed(self, client):
        _seed_state(client, "err_state")
        with patch(
            "app.api.v1.auth.auth_service.exchange_code",
            new=AsyncMock(side_effect=Exception("token endpoint down")),
        ):
            resp = client.get(
                f"{PREFIX}/spotify/callback?code=bad&state=err_state",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "auth_failed" in resp.headers["location"]

    def test_get_profile_failure_redirects_with_auth_failed(self, client):
        _seed_state(client, "prof_err_state")
        with (
            patch("app.api.v1.auth.auth_service.exchange_code", new=AsyncMock(return_value=_mock_token_data)),
            patch(
                "app.api.v1.auth.auth_service.get_spotify_profile",
                new=AsyncMock(side_effect=Exception("profile API down")),
            ),
        ):
            resp = client.get(
                f"{PREFIX}/spotify/callback?code=code&state=prof_err_state",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "auth_failed" in resp.headers["location"]

    def test_upsert_user_failure_redirects_with_auth_failed(self, client):
        _seed_state(client, "db_err_state")
        with (
            patch("app.api.v1.auth.auth_service.exchange_code", new=AsyncMock(return_value=_mock_token_data)),
            patch("app.api.v1.auth.auth_service.get_spotify_profile", new=AsyncMock(return_value=_mock_profile)),
            patch(
                "app.api.v1.auth.auth_service.upsert_user",
                new=AsyncMock(side_effect=Exception("DB write failed")),
            ),
        ):
            resp = client.get(
                f"{PREFIX}/spotify/callback?code=code&state=db_err_state",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "auth_failed" in resp.headers["location"]

    def test_callback_without_code_still_attempts_exchange(self, client):
        """No ?code param — exchange_code receives None which should raise."""
        _seed_state(client, "no_code_state")
        with patch(
            "app.api.v1.auth.auth_service.exchange_code",
            new=AsyncMock(side_effect=Exception("missing code")),
        ):
            resp = client.get(
                f"{PREFIX}/spotify/callback?state=no_code_state",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "auth_failed" in resp.headers["location"]


# ══════════════════════════════════════════════════════════════════════════════
# /auth/me
# ══════════════════════════════════════════════════════════════════════════════

class TestMe:
    # ── unauthenticated ───────────────────────────────────────────────────────

    def test_no_session_cookie_returns_401(self, client):
        resp = client.get(f"{PREFIX}/me")
        assert resp.status_code == 401

    def test_invalid_session_token_returns_401(self, client):
        resp = client.get(f"{PREFIX}/me", cookies={"session": "not.a.valid.token"})
        assert resp.status_code == 401

    def test_empty_session_cookie_returns_401(self, client):
        resp = client.get(f"{PREFIX}/me", cookies={"session": ""})
        assert resp.status_code == 401

    def test_tampered_session_signature_returns_401(self, client):
        from app.core.session import create_session

        token = create_session(1)
        # Corrupt the itsdangerous HMAC signature (last segment)
        parts = token.rsplit(".", 1)
        tampered = parts[0] + ".INVALIDSIGNATURE"
        resp = client.get(f"{PREFIX}/me", cookies={"session": tampered})
        assert resp.status_code == 401

    def test_session_for_nonexistent_user_returns_401(self, client, valid_session, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        resp = client.get(f"{PREFIX}/me", cookies={"session": valid_session})
        assert resp.status_code == 401

    # ── authenticated ─────────────────────────────────────────────────────────

    def test_valid_session_returns_200(self, client, valid_session):
        resp = client.get(f"{PREFIX}/me", cookies={"session": valid_session})
        assert resp.status_code == 200

    def test_valid_session_returns_display_name_and_email(self, client, valid_session, mock_user):
        resp = client.get(f"{PREFIX}/me", cookies={"session": valid_session})
        data = resp.json()
        assert data["display_name"] == mock_user.display_name
        assert data["email"] == mock_user.email

    def test_response_contains_only_expected_fields(self, client, valid_session):
        resp = client.get(f"{PREFIX}/me", cookies={"session": valid_session})
        data = resp.json()
        assert set(data.keys()) == {"display_name", "email"}

    def test_session_signed_with_wrong_secret_returns_401(self, client):
        """Token created with a different secret should not authenticate."""
        from itsdangerous import URLSafeTimedSerializer

        bad_serializer = URLSafeTimedSerializer("completely-different-secret")
        bad_token = bad_serializer.dumps(1, salt="session")
        resp = client.get(f"{PREFIX}/me", cookies={"session": bad_token})
        assert resp.status_code == 401

    def test_session_signed_with_wrong_salt_returns_401(self, client):
        from itsdangerous import URLSafeTimedSerializer

        serializer = URLSafeTimedSerializer("test-secret-for-unit-tests-only")
        wrong_salt_token = serializer.dumps(1, salt="wrong-salt")
        resp = client.get(f"{PREFIX}/me", cookies={"session": wrong_salt_token})
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════════════
# /auth/logout
# ══════════════════════════════════════════════════════════════════════════════

class TestLogout:
    def test_logout_redirects_to_frontend(self, client):
        resp = client.get(f"{PREFIX}/logout", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert resp.headers["location"] == FRONTEND

    def test_logout_without_session_still_redirects(self, client):
        resp = client.get(f"{PREFIX}/logout", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_logout_clears_session_cookie(self, client, valid_session):
        resp = client.get(
            f"{PREFIX}/logout",
            cookies={"session": valid_session},
            follow_redirects=False,
        )
        # Starlette's delete_cookie sets Max-Age=0
        set_cookie = resp.headers.get("set-cookie", "").lower()
        assert "session" in set_cookie
        assert "max-age=0" in set_cookie
