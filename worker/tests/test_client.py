"""
How the worker classifies what the app tells it (gameplan 10.7).

This one mapping is the whole safety property. Get it wrong in either direction and the
consequence lands on a real user's data:

  - treat a 422 as transient and you get a silent infinite loop — the seed's attempt
    counter never moves, so its lease expires every 15 minutes and the same track is
    downloaded and refused again, forever, with nobody told
  - treat a 422 as a seed failure and report it, and a single mis-built worker retires
    three tracks per user in minutes, because a recorded failure releases the lease
    immediately instead of after 15 minutes
  - treat 401, 429 or a 5xx as permanent and you abandon or retire real work over a token
    rotation, a rate limit, or a container restart mid-deploy

So: 422 is fatal and stops the worker, 404 means the seed is gone, everything else is
transient. Tested here rather than left to a code reading because this is exactly the kind
of rule that gets "tidied" into `4xx means permanent" by someone later.
"""
import json
from unittest.mock import MagicMock, patch

import pytest

from client import ApiError, FatalRejection, IngestClient, SeedGone, _for_status


class TestStatusClassification:
    def test_422_is_fatal(self):
        assert _for_status(422) is FatalRejection

    def test_404_is_the_seed_being_gone(self):
        assert _for_status(404) is SeedGone

    @pytest.mark.parametrize("status", [400, 401, 403, 408, 413, 429, 500, 502, 503, 504])
    def test_everything_else_is_transient(self, status):
        # ApiError, i.e. the caller's existing "log it and let the lease retry" path.
        assert _for_status(status) is ApiError, (
            f"{status} must not be permanent: it says nothing about the seed"
        )

    def test_401_is_not_fatal(self):
        # Named separately because it is the tempting one. A token rotated in SSM while a
        # worker is mid-run gives 401 on every call, and stopping would be defensible —
        # but retiring or abandoning seeds over it would not, and the retry path already
        # logs it loudly on each claim.
        assert _for_status(401) is not FatalRejection

    def test_429_is_not_fatal(self):
        # The route is rate-limited at 60/minute. One worker cannot reach that, but 11.5
        # contemplates a second, and a rate limit must never cost a seed.
        assert _for_status(429) is not FatalRejection


def make_client(status: int, body: dict | None = None) -> tuple[IngestClient, MagicMock]:
    response = MagicMock()
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = json.dumps(body or {"detail": "nope"})
    response.json.return_value = body or {}
    client = IngestClient("https://example.invalid", "tok", timeout=1)
    return client, response


class TestCompleteRaisesTheRightType:
    def _call(self, status, body=None):
        client, response = make_client(status, body)
        with patch.object(client.session, "post", return_value=response):
            return client.complete(1, "jazz", [0.1] * 1280)

    def test_422_raises_fatal_rejection(self):
        with pytest.raises(FatalRejection):
            self._call(422)

    def test_404_raises_seed_gone(self):
        with pytest.raises(SeedGone):
            self._call(404)

    def test_500_raises_plain_api_error(self):
        with pytest.raises(ApiError) as exc:
            self._call(500)
        assert not isinstance(exc.value, (FatalRejection, SeedGone))

    def test_success_returns_the_status(self):
        assert self._call(200, {"status": "ok"}) == "ok"

    def test_already_done_is_not_an_error(self):
        # A re-POST after a deploy killed the first request. Must not raise.
        assert self._call(200, {"status": "already_done"}) == "already_done"


class TestFailRaisesTheRightType:
    def _call(self, status, body=None):
        client, response = make_client(status, body)
        with patch.object(client.session, "post", return_value=response):
            return client.fail(1, "download failed")

    def test_404_raises_seed_gone(self):
        # The ordinary case: the user's top tracks moved on and the row was deleted.
        with pytest.raises(SeedGone):
            self._call(404)

    def test_500_raises_plain_api_error(self):
        with pytest.raises(ApiError) as exc:
            self._call(500)
        assert not isinstance(exc.value, (FatalRejection, SeedGone))

    def test_success_returns_the_body(self):
        body = {"status": "ok", "attempts": 2, "terminal": False}
        assert self._call(200, body) == body


class TestClaim:
    def test_404_says_the_api_is_not_enabled(self):
        """A 404 on /claim is not a missing seed.

        The whole router answers 404 while INGEST_WORKER_TOKEN is unset on the server, so
        this is "no worker is configured there" — worth saying, because the bare status is
        indistinguishable from the seed-level 404 that /complete and /fail return.
        """
        client, response = make_client(404)
        with patch.object(client.session, "post", return_value=response):
            with pytest.raises(ApiError) as exc:
                client.claim(3)
        assert "not enabled" in str(exc.value)
        assert not isinstance(exc.value, SeedGone)

    def test_returns_jobs_and_lease(self):
        client, response = make_client(200, {"jobs": [{"id": 1}], "lease_seconds": 900})
        with patch.object(client.session, "post", return_value=response):
            jobs, lease = client.claim(3)
        assert jobs == [{"id": 1}] and lease == 900

    def test_sends_the_bearer_token(self):
        client, _ = make_client(200)
        assert client.session.headers["Authorization"] == "Bearer tok"
