"""Work queue for the external ingest worker (gameplan 10.6).

Why this exists: YouTube bot-challenges the EC2 instance's datacenter IP, so every
`spotdl` download on the box fails and no new user can be onboarded (10.3). Nothing in
yt-dlp's configuration fixes it — version, player clients, alternative providers and
Spotify's deprecated preview_url were all ruled out by measurement. A residential IP
does fix it, so the download and the embedding move to a worker on a machine at home.

The shape is deliberately a pull queue rather than a push: the worker dials out, so the
database keeps its private subnet, no port is opened, and the worker holds no AWS or
database credentials. It does hold the Spotify client id/secret that spotdl needs, plus
the token below, which is the honest cost of this design — secrets do leave the AWS
boundary, by hand, with no rotation story.

**The worker fills seeds; it never generates a dispatch.** That stays in `get_recs`,
inside the `SELECT ... FOR UPDATE` that serializes a user's daily allotment. A worker
that produced dispatches would spend someone's one-a-day unprompted and stamp it with
whatever time the download happened to finish.
"""
import hmac
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ...core.limiter import limiter
from ...db.database import get_db
from ...schemas.ingest import (
    ClaimRequest,
    ClaimResponse,
    ClaimedSeed,
    CompleteRequest,
    CompleteResponse,
    FailRequest,
    FailResponse,
    embedding_problem,
)
from ...services.spotify_ingest_service import (
    INGEST_CLAIM_LEASE_SECONDS,
    SpotifyIngestService,
    get_ingest_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


def require_worker_token(request: Request) -> None:
    """Bearer-token gate for the whole router.

    Read from the environment on every request rather than captured at import, so the
    surface follows the deployed configuration: seeding INGEST_WORKER_TOKEN in SSM and
    redeploying turns these endpoints on, and clearing it turns them off, with no code
    change either way.

    **404, not 401, when the token is unset.** With no token configured there is nothing
    to authenticate against, and answering 401 would advertise a write surface that
    cannot be used. 404 is also what an unconfigured deployment should look like from
    outside: these routes do not exist for it.

    compare_digest gets bytes, never str: on str it raises TypeError for any non-ASCII
    character, which would turn an attacker-controlled header into an unhandled 500 (and
    a Sentry event per probe).
    """
    expected = os.getenv("INGEST_WORKER_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=404, detail="Not Found")

    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        supplied.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Invalid worker token")


# The limit is generous because the caller is trusted infrastructure holding a secret,
# not the public: one claim plus one result per track, a handful of times a minute. It is
# here so a worker stuck in a tight retry loop cannot hammer the box, not as access
# control — that is the token's job.
WORKER_RATE_LIMIT = "60/minute"


@router.post(
    "/claim", response_model=ClaimResponse, dependencies=[Depends(require_worker_token)]
)
@limiter.limit(WORKER_RATE_LIMIT)
async def claim_seeds(
    request: Request,
    body: ClaimRequest,
    db: Session = Depends(get_db),
    ingest_service: SpotifyIngestService = Depends(get_ingest_service),
) -> ClaimResponse:
    # `request` is unused here but must stay in the signature: slowapi inspects the
    # wrapped function for it and raises at call time if it is missing.
    jobs = ingest_service.claim_pending_seeds(db, body.limit, INGEST_CLAIM_LEASE_SECONDS)
    return ClaimResponse(
        jobs=[ClaimedSeed(**job) for job in jobs],
        lease_seconds=INGEST_CLAIM_LEASE_SECONDS,
    )


@router.post(
    "/complete",
    response_model=CompleteResponse,
    dependencies=[Depends(require_worker_token)],
)
@limiter.limit(WORKER_RATE_LIMIT)
async def complete_seed(
    request: Request,
    body: CompleteRequest,
    db: Session = Depends(get_db),
    ingest_service: SpotifyIngestService = Depends(get_ingest_service),
) -> CompleteResponse:
    problem = embedding_problem(body.embedding)
    if problem:
        # 422 by hand rather than through pydantic: a validation error would carry the
        # embedding back in its `input` field, and Starlette serializes with
        # allow_nan=False, so a NaN would make the error response itself unserializable
        # and turn a bad request into a 500.
        raise HTTPException(status_code=422, detail=problem)

    status = ingest_service.complete_seed(body.id, body.genre, body.embedding, db)
    if status == "unknown":
        # The seed was deleted while the worker was working on it, which happens when the
        # user's top tracks move on. Not an error worth retrying.
        raise HTTPException(status_code=404, detail="No such seed")
    logger.info("Worker completed seed %s (%s, genre=%s)", body.id, status, body.genre)
    return CompleteResponse(status=status)


@router.post(
    "/fail", response_model=FailResponse, dependencies=[Depends(require_worker_token)]
)
@limiter.limit(WORKER_RATE_LIMIT)
async def fail_seed(
    request: Request,
    body: FailRequest,
    db: Session = Depends(get_db),
    ingest_service: SpotifyIngestService = Depends(get_ingest_service),
) -> FailResponse:
    result = ingest_service.record_seed_failure(body.id, body.error, db)
    if result is None:
        raise HTTPException(status_code=404, detail="No such seed")
    attempts, terminal = result
    logger.info(
        "Worker failed seed %s (attempt %s, terminal=%s)", body.id, attempts, terminal
    )
    return FailResponse(status="ok", attempts=attempts, terminal=terminal)
