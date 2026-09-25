"""Request and response bodies for the ingest worker API (gameplan 10.6).

Everything here exists to validate at the boundary. The worker runs on a machine outside
the AWS account, computes an embedding with its own copy of the model, and POSTs the
result back — so this module is the last place a bad value can be stopped before it
reaches a `vector(1280)` column or the genre filter.

Three failure modes are worth naming, because none of them is theoretical:

- `json.loads` accepts the bare tokens `NaN` and `Infinity`, and FastAPI parses request
  bodies with the standard library. A plain `list[float]` field passes them straight
  through to pgvector, which rejects them server-side, mid-transaction, as a 500.
- A zero vector makes cosine distance undefined, so a seed embedded from silence would
  produce a meaningless ordering rather than an error.
- A genre outside the canonical vocabulary matches nothing in the corpus, so the
  genre-filtered branch quietly returns an empty pool and every dispatch for that user
  falls through to the unfiltered one.

Two notes on *how* the embedding is checked, both found by measurement and both
counter-intuitive enough to be worth writing down.

**It is not `Field(allow_inf_nan=False)`.** On the pinned pydantic 2.12.5, that setting
applied to a `list[float]` raises `TypeError: must be real number, not list` on *valid*
input — it breaks every request. It only behaves when annotated onto the item type.

**It is not a `field_validator` either**, which is the obvious alternative. A pydantic
validation error carries the offending value in its `input` field, FastAPI returns that
as the 422 body, and Starlette serializes responses with `json.dumps(..., allow_nan=False)`
— so a NaN in the input makes the 422 itself unserializable and the request 500s instead.
The value is still rejected, but with the wrong status and a Sentry event for something
that is just a bad request. It would also echo 1280 floats back in the error body.

So `embedding_problem` below is a plain function the endpoint calls, and the endpoint
raises an HTTPException whose detail is a short string. The genre check stays in pydantic
because its input is a short string that serializes fine.
"""
import math

from pydantic import BaseModel, Field, field_validator

from ..services.genre_normalizer import CANONICAL_GENRES

# Must match Song.embedding's Vector(1280) and the Essentia model's output width.
EMBEDDING_DIMENSIONS = 1280


class ClaimRequest(BaseModel):
    # Small by default: a claim is a lease with a fixed expiry, so a worker that grabs
    # more than it can finish before the lease runs out just causes duplicate work.
    limit: int = Field(default=3, ge=1, le=10)


class ClaimedSeed(BaseModel):
    id: int
    # Nullable because the columns are. A seed with no spotify_url cannot be downloaded;
    # the worker fails it rather than crashing, and it retires after INGEST_MAX_ATTEMPTS.
    spotify_url: str | None = None
    track_title: str | None = None
    artist_name: str | None = None
    attempts: int = 0


class ClaimResponse(BaseModel):
    jobs: list[ClaimedSeed] = []
    # Returned so the worker can see how long it has without hardcoding the server's
    # value, and log when a job is taking long enough to risk losing its claim.
    lease_seconds: int


class CompleteRequest(BaseModel):
    id: int
    # Optional, and that is not sloppiness: AudioGenreClassifier.classify returns None
    # when none of the top-5 Discogs labels maps to a canonical genre, and the in-process
    # path stores that None happily. Requiring a genre here would make those seeds
    # impossible to complete, so the worker would have to fail them and they would retire
    # at the attempt cap for no reason.
    genre: str | None = None
    # Checked by embedding_problem() in the endpoint, not here. See the module docstring.
    embedding: list[float]

    @field_validator("genre")
    @classmethod
    def _genre_is_canonical(cls, value: str | None) -> str | None:
        if value is not None and value not in CANONICAL_GENRES:
            raise ValueError(f"genre {value!r} is not one of the canonical genres")
        return value


def embedding_problem(embedding: list[float]) -> str | None:
    """Return a short reason the embedding is unusable, or None if it is fine.

    A string rather than an exception so the caller controls the status code and the
    response body stays small — see the module docstring for why this is not a pydantic
    validator.
    """
    if len(embedding) != EMBEDDING_DIMENSIONS:
        return f"embedding must have {EMBEDDING_DIMENSIONS} dimensions, got {len(embedding)}"
    if not all(math.isfinite(component) for component in embedding):
        return "embedding contains a non-finite value (NaN or Infinity)"
    if not any(component != 0.0 for component in embedding):
        return "embedding is all zeros, which makes cosine distance undefined"
    return None


class CompleteResponse(BaseModel):
    # "ok", "already_done", or "unknown".
    status: str


class FailRequest(BaseModel):
    id: int
    # Truncated here as well as in _record_failure: no reason to accept a multi-megabyte
    # traceback into memory just to store 500 bytes of it.
    error: str = Field(default="", max_length=2000)


class FailResponse(BaseModel):
    status: str
    attempts: int
    # True once the seed has hit INGEST_MAX_ATTEMPTS and will not be handed out again.
    terminal: bool
