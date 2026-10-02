"""HTTP client for the app's ingest queue (gameplan 10.6).

Three calls, one bearer token, no state. Everything this worker knows about the app is
in here, so pointing it at a different host is a config change.
"""
import logging

import requests

logger = logging.getLogger(__name__)


class ApiError(RuntimeError):
    """The app answered, but not with success."""

    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status


class SeedGone(ApiError):
    """404 on a specific seed: it no longer exists.

    Not a failure to report back — the user's top tracks moved on while this worker was
    downloading, so the row was deleted. Drop the job and carry on.
    """


class FatalRejection(ApiError):
    """422: the app refused this worker's output as unacceptable.

    **Fatal on purpose, and this is the whole of 10.7.** A 422 cannot be the track's
    fault. The app checks three things — 1280 dimensions, all finite, non-zero norm — and
    the model emits a dense finite vector even for digital silence (measured: norm 1.28,
    every one of 1280 components non-zero), while audio too short to embed raises here
    long before anything is posted. So a 422 means this worker's build disagrees with the
    deployment it is talking to: a different model output, a different vector width, or a
    genre vocabulary the server does not share.

    Continuing would be harmful in both available directions. Carrying on re-downloads the
    same track every time its lease expires, forever, for nothing. Reporting it through
    /fail would advance the attempt counter and retire three of the user's seeds per
    worker bug — and because a recorded failure releases the lease immediately rather than
    after 15 minutes, a systematically-rejecting worker would burn every seed of every
    user within minutes.

    So the worker stops. The seed is left exactly as it was for a corrected worker to
    pick up, and a stopped worker is something you can see.
    """


def _for_status(status: int) -> type[ApiError]:
    """Map an HTTP status onto how this worker should treat it.

    Only 422 is fatal. Everything else is transient and gets today's behaviour — retry
    when the lease expires. That matters for the statuses it would be tempting to lump in:
    401 is a token rotated out from under a running worker, 429 is the route's own rate
    limit, 408 and 5xx are the app being restarted mid-deploy. None of them says anything
    about the seed, and treating them as permanent would abandon or retire work over a
    blip.
    """
    if status == 404:
        return SeedGone
    if status == 422:
        return FatalRejection
    return ApiError


def _reclassify(error: ApiError) -> ApiError:
    """Re-raise a per-seed error as its specific type, or return it unchanged."""
    specific = _for_status(error.status)
    if specific is ApiError:
        return error
    return specific(error.status, str(error))


class IngestClient:
    def __init__(self, base_url: str, token: str, timeout: float, verify: bool = True):
        self.base_url = base_url
        self.timeout = timeout
        self.verify = verify
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def _post(self, path: str, payload: dict) -> dict:
        response = self.session.post(
            f"{self.base_url}/api/v1/ingest/{path}",
            json=payload,
            timeout=self.timeout,
            verify=self.verify,
        )
        if not response.ok:
            raise ApiError(response.status_code, response.text[:200])
        return response.json()

    def claim(self, limit: int) -> tuple[list[dict], int]:
        """Lease up to `limit` seeds. Returns (jobs, lease_seconds).

        A 404 here is not a missing seed — the whole router answers 404 while
        INGEST_WORKER_TOKEN is unset on the server, so it means the app has no worker
        configured. Re-raised with that spelled out, because the alternative is staring
        at a bare 404 wondering which of the two it is.
        """
        try:
            body = self._post("claim", {"limit": limit})
        except ApiError as e:
            if e.status == 404:
                raise ApiError(
                    404,
                    "the ingest API is not enabled on this server "
                    "(INGEST_WORKER_TOKEN is unset)",
                ) from e
            raise
        return body.get("jobs", []), body.get("lease_seconds", 0)

    def complete(self, seed_id: int, genre: str | None, embedding: list[float]) -> str:
        try:
            body = self._post(
                "complete", {"id": seed_id, "genre": genre, "embedding": embedding}
            )
        except ApiError as e:
            raise _reclassify(e) from e
        return body.get("status", "")

    def fail(self, seed_id: int, error: str) -> dict:
        try:
            # The server truncates too, but there is no reason to put a whole traceback
            # on the wire to have 500 bytes of it stored.
            return self._post("fail", {"id": seed_id, "error": error[:2000]})
        except ApiError as e:
            raise _reclassify(e) from e
