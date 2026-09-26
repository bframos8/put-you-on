"""
Tests for the external ingest worker API and worker mode (gameplan 10.6).

The worker exists because YouTube bot-blocks the EC2 instance's IP, so the download and
the embedding happen on a machine at home and the result is POSTed back. That makes this
the only place in the app where an embedding arrives from outside the process, and the
only write surface authenticated by a shared token rather than a session cookie. Both of
those are worth pinning down:

  - the token gate: absent config must look like a missing route, a bad token must be a
    clean 401, and no header value may be able to raise
  - the boundary checks: a `vector(1280)` column and an undefined cosine distance are
    both 500s at the database if a bad embedding gets through
  - worker mode in get_recs: it must queue work without blocking, without re-fetching
    from Spotify on every poll, and without setting the per-process flag that nothing
    in that path would ever clear
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

RECS_URL = "/api/v1/items/song_recs/"
CLAIM_URL = "/api/v1/ingest/claim"
COMPLETE_URL = "/api/v1/ingest/complete"
FAIL_URL = "/api/v1/ingest/fail"

TOKEN = "test-worker-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def worker_token(monkeypatch):
    monkeypatch.setenv("INGEST_WORKER_TOKEN", TOKEN)
    return TOKEN


def embedding(value: float = 0.5) -> list[float]:
    return [value] * 1280


# ══════════════════════════════════════════════════════════════════════════════
# The token gate
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkerAuth:
    def test_unconfigured_token_is_404(self, client, monkeypatch):
        """With no token seeded the routes must not exist.

        This is what makes it safe to mount the router unconditionally and ship it long
        before the worker machine does. 401 here would advertise a write surface nobody
        can use yet.
        """
        monkeypatch.delenv("INGEST_WORKER_TOKEN", raising=False)
        resp = client.post(CLAIM_URL, json={"limit": 1}, headers=AUTH)
        assert resp.status_code == 404

    def test_missing_header_is_401(self, client, worker_token):
        assert client.post(CLAIM_URL, json={"limit": 1}).status_code == 401

    def test_wrong_token_is_401(self, client, worker_token):
        resp = client.post(
            CLAIM_URL, json={"limit": 1}, headers={"Authorization": "Bearer nope"}
        )
        assert resp.status_code == 401

    def test_wrong_scheme_is_401(self, client, worker_token):
        resp = client.post(
            CLAIM_URL, json={"limit": 1}, headers={"Authorization": f"Basic {TOKEN}"}
        )
        assert resp.status_code == 401

    def test_non_ascii_token_is_401_not_500(self, client, worker_token):
        """hmac.compare_digest raises TypeError on non-ASCII *str* input.

        Comparing the raw header as a string would turn any request carrying a non-ASCII
        bearer value into an unhandled 500 — and one Sentry event per probe. The
        comparison encodes to bytes first, so this is an ordinary rejection.
        """
        # Sent as raw bytes: httpx refuses to encode a non-ASCII header value itself,
        # so a str here would fail in the test client instead of reaching the app.
        # Starlette decodes header bytes as latin-1, which is how a non-ASCII str gets
        # into the handler in production.
        resp = client.post(
            CLAIM_URL,
            json={"limit": 1},
            headers={b"Authorization": "Bearer \u00e1bc".encode("utf-8")},
        )
        assert resp.status_code == 401

    def test_valid_token_reaches_the_handler(self, client, worker_token, mock_ingest):
        mock_ingest.claim_pending_seeds.return_value = []
        resp = client.post(CLAIM_URL, json={"limit": 1}, headers=AUTH)
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════════════
# /claim
# ══════════════════════════════════════════════════════════════════════════════

class TestClaim:
    def test_returns_jobs_and_lease(self, client, worker_token, mock_ingest):
        from app.services.spotify_ingest_service import INGEST_CLAIM_LEASE_SECONDS

        mock_ingest.claim_pending_seeds.return_value = [
            {
                "id": 7,
                "spotify_url": "https://open.spotify.com/track/abc",
                "track_title": "A Song",
                "artist_name": "An Artist",
                "attempts": 1,
            }
        ]
        resp = client.post(CLAIM_URL, json={"limit": 3}, headers=AUTH)

        assert resp.status_code == 200
        body = resp.json()
        assert body["jobs"][0]["id"] == 7
        assert body["jobs"][0]["attempts"] == 1
        # The worker needs the lease to know how long it has, without hardcoding it.
        assert body["lease_seconds"] == INGEST_CLAIM_LEASE_SECONDS

    def test_defaults_to_a_small_batch(self, client, worker_token, mock_ingest):
        # A claim is a lease with a fixed expiry, so a big batch just risks duplicate
        # work. The default must stay small.
        mock_ingest.claim_pending_seeds.return_value = []
        client.post(CLAIM_URL, json={}, headers=AUTH)
        assert mock_ingest.claim_pending_seeds.call_args[0][1] == 3

    @pytest.mark.parametrize("limit", [0, -1, 11])
    def test_rejects_out_of_range_limits(self, client, worker_token, limit):
        resp = client.post(CLAIM_URL, json={"limit": limit}, headers=AUTH)
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# /complete — the boundary checks
# ══════════════════════════════════════════════════════════════════════════════

class TestCompleteValidation:
    """Every one of these is a 500 at the database if it gets through."""

    def test_rejects_wrong_dimension(self, client, worker_token):
        resp = client.post(
            COMPLETE_URL, json={"id": 1, "embedding": [0.1] * 512}, headers=AUTH
        )
        assert resp.status_code == 422

    def test_rejects_nan(self, client, worker_token):
        # json.loads accepts the bare token NaN and FastAPI parses bodies with the
        # standard library, so this really does arrive as a float('nan').
        body = '{"id": 1, "embedding": [' + ", ".join(["NaN"] + ["0.1"] * 1279) + "]}"
        resp = client.post(
            COMPLETE_URL,
            content=body,
            headers={**AUTH, "Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_rejects_infinity(self, client, worker_token):
        body = '{"id": 1, "embedding": [' + ", ".join(["Infinity"] + ["0.1"] * 1279) + "]}"
        resp = client.post(
            COMPLETE_URL,
            content=body,
            headers={**AUTH, "Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_rejects_all_zeros(self, client, worker_token):
        # Cosine distance against a zero vector is undefined, so this would not error —
        # it would silently produce a meaningless ordering.
        resp = client.post(
            COMPLETE_URL, json={"id": 1, "embedding": [0.0] * 1280}, headers=AUTH
        )
        assert resp.status_code == 422

    def test_rejects_unknown_genre(self, client, worker_token):
        resp = client.post(
            COMPLETE_URL,
            json={"id": 1, "genre": "vaporwave", "embedding": embedding()},
            headers=AUTH,
        )
        assert resp.status_code == 422

    def test_accepts_a_canonical_genre(self, client, worker_token, mock_ingest):
        mock_ingest.complete_seed.return_value = "ok"
        resp = client.post(
            COMPLETE_URL,
            json={"id": 1, "genre": "jazz", "embedding": embedding()},
            headers=AUTH,
        )
        assert resp.status_code == 200

    def test_accepts_a_null_genre(self, client, worker_token, mock_ingest):
        """classify() returns None when no top-5 Discogs label maps.

        The in-process path stores that None happily. Rejecting it here would make those
        seeds impossible to complete, so the worker would have to fail them and they
        would retire at the attempt cap for no reason at all.
        """
        mock_ingest.complete_seed.return_value = "ok"
        resp = client.post(
            COMPLETE_URL, json={"id": 1, "genre": None, "embedding": embedding()}, headers=AUTH
        )
        assert resp.status_code == 200
        assert mock_ingest.complete_seed.call_args[0][1] is None


class TestRejectionLeavesTheSeedAlone:
    """A rejected result must not be charged against the seed (10.7).

    The tempting fix for the silent-retry bug was to record a failure attempt server-side
    when validation rejects, so the cap would eventually retire the seed. That is wrong,
    and measurement is why: the model emits a dense finite 1280-vector even for digital
    silence, and audio too short to embed raises in the worker before anything is posted.
    So a rejection here is never the track's fault — it means the worker's build disagrees
    with this deployment. Charging it to the seed would retire three of a real user's
    tracks per worker bug, and because a recorded failure releases the claim lease the
    retries would be immediate rather than 15 minutes apart.

    The worker stops instead. These tests pin the server half of that: reject, say so
    loudly, change nothing.
    """

    def test_rejection_does_not_record_a_failure(self, client, worker_token, mock_ingest):
        resp = client.post(
            COMPLETE_URL, json={"id": 1, "embedding": [0.1] * 512}, headers=AUTH
        )
        assert resp.status_code == 422
        mock_ingest.record_seed_failure.assert_not_called()

    def test_rejection_does_not_store_the_result(self, client, worker_token, mock_ingest):
        client.post(COMPLETE_URL, json={"id": 1, "embedding": [0.0] * 1280}, headers=AUTH)
        mock_ingest.complete_seed.assert_not_called()

    def test_rejection_is_logged_at_error(self, client, worker_token, caplog):
        """ERROR specifically, because that is what reaches Sentry.

        sentry-sdk's default LoggingIntegration promotes ERROR to an issue. At WARNING this
        would be invisible, which was the original defect — the loop was not merely wrong,
        it was silent.
        """
        import logging

        with caplog.at_level(logging.ERROR, logger="app.api.v1.ingest"):
            client.post(
                COMPLETE_URL, json={"id": 7, "embedding": [0.1] * 99}, headers=AUTH
            )
        assert any(r.levelno == logging.ERROR for r in caplog.records)
        message = " ".join(r.getMessage() for r in caplog.records)
        # The seed id and the received width are what make the log actionable.
        assert "7" in message and "99" in message


class TestCompleteDispatch:
    def test_unknown_seed_is_404(self, client, worker_token, mock_ingest):
        mock_ingest.complete_seed.return_value = "unknown"
        resp = client.post(
            COMPLETE_URL, json={"id": 999, "embedding": embedding()}, headers=AUTH
        )
        assert resp.status_code == 404

    def test_already_done_is_reported_not_an_error(self, client, worker_token, mock_ingest):
        # A deploy recreates the backend mid-request, so the worker will re-POST results
        # that already landed. That has to be a no-op, not a second Song.
        mock_ingest.complete_seed.return_value = "already_done"
        resp = client.post(
            COMPLETE_URL, json={"id": 1, "embedding": embedding()}, headers=AUTH
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "already_done"


# ══════════════════════════════════════════════════════════════════════════════
# /fail
# ══════════════════════════════════════════════════════════════════════════════

class TestFail:
    def test_reports_attempts_and_terminality(self, client, worker_token, mock_ingest):
        mock_ingest.record_seed_failure.return_value = (3, True)
        resp = client.post(
            FAIL_URL, json={"id": 1, "error": "download failed"}, headers=AUTH
        )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "attempts": 3, "terminal": True}

    def test_unknown_seed_is_404(self, client, worker_token, mock_ingest):
        # The user's top tracks can move on while the worker is downloading, in which
        # case add_user_top_songs has already deleted the row.
        mock_ingest.record_seed_failure.return_value = None
        resp = client.post(FAIL_URL, json={"id": 999, "error": "x"}, headers=AUTH)
        assert resp.status_code == 404

    def test_oversized_error_is_rejected(self, client, worker_token):
        resp = client.post(FAIL_URL, json={"id": 1, "error": "x" * 5000}, headers=AUTH)
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Worker mode in get_recs
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def worker_mode():
    with patch("app.api.v1.songs.INGEST_WORKER_ENABLED", True):
        yield


class TestGetRecsWorkerMode:
    def _call(self, client, valid_session, mock_user, tracks=None):
        with (
            patch("app.api.v1.songs.auth_service.refresh_tokens", new=AsyncMock(return_value=mock_user)),
            patch(
                "app.api.v1.songs.auth_service.get_top_tracks",
                new=AsyncMock(return_value=tracks if tracks is not None else []),
            ) as mock_tracks,
        ):
            resp = client.get(RECS_URL, cookies={"session": valid_session})
        return resp, mock_tracks

    def test_empty_snapshot_fetches_and_returns_processing(
        self, client, valid_session, mock_user, mock_ingest, worker_mode
    ):
        mock_ingest.snapshot_is_stale.return_value = True
        mock_ingest.pending_seed_count.return_value = 0   # nothing queued yet
        mock_ingest.usable_seed_count.return_value = 0

        resp, mock_tracks = self._call(client, valid_session, mock_user)

        assert resp.json()["status"] == "processing"
        mock_tracks.assert_called_once()
        mock_ingest.add_user_top_songs.assert_called_once()

    def test_does_not_refetch_while_work_is_queued(
        self, client, valid_session, mock_user, mock_ingest, worker_mode
    ):
        """The guard that keeps this from costing a Spotify call on every poll.

        Without it, every request while the worker is working would re-fetch the user's
        top tracks and rewrite the snapshot — the shape of the 10.3 loop, just cheaper.
        """
        mock_ingest.snapshot_is_stale.return_value = True
        mock_ingest.pending_seed_count.return_value = 4   # worker still chewing
        mock_ingest.usable_seed_count.return_value = 0

        resp, mock_tracks = self._call(client, valid_session, mock_user)

        assert resp.json()["status"] == "processing"
        mock_tracks.assert_not_called()
        mock_ingest.add_user_top_songs.assert_not_called()

    def test_dispatches_from_seeds_already_done(
        self, client, valid_session, mock_user, mock_ingest, worker_mode
    ):
        # Partly ingested: some seeds pending, at least one usable. The user gets a
        # dispatch now rather than waiting for the whole batch.
        mock_ingest.snapshot_is_stale.return_value = True
        mock_ingest.pending_seed_count.return_value = 6
        mock_ingest.usable_seed_count.return_value = 4
        mock_ingest.failed_seed_count.return_value = 0

        resp, _ = self._call(client, valid_session, mock_user)

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        mock_ingest.query_recommendations.assert_called_once()

    def test_never_sets_the_processing_flag(
        self, client, valid_session, mock_user, mock_ingest, worker_mode
    ):
        """Nothing in worker mode would ever clear it.

        The in-process path can set app.state.processing_users because its background
        task clears it in a finally. Worker mode starts no such task, so setting the flag
        would create the permanent stuck spinner that today's code does not have.
        """
        from app.main import app

        mock_ingest.snapshot_is_stale.return_value = True
        mock_ingest.pending_seed_count.return_value = 0
        mock_ingest.usable_seed_count.return_value = 0

        self._call(client, valid_session, mock_user)

        assert app.state.processing_users == set()

    def test_flag_off_keeps_the_in_process_path(
        self, client, valid_session, mock_user, mock_ingest
    ):
        # Default-off must mean "nothing changes", so the background ingest still runs.
        mock_ingest.snapshot_is_stale.return_value = True

        with patch("app.api.v1.songs._run_process_top_tracks") as mock_run:
            resp, mock_tracks = self._call(client, valid_session, mock_user)

        assert resp.json()["status"] == "processing"
        mock_tracks.assert_called_once()
        assert mock_run.called
