# A3 — Stop blocking the event loop with sync DB work (the `def` route fix)

> **Status:** Plan for review (agent-checked before any edit).
> **Source item:** A3 in
> [backend-optimization-deferred.md](backend-optimization-deferred.md) /
> [.claude-backend-optimization.md](.claude-backend-optimization.md).
> **Branch:** `Backend-optimization`. **Date:** 2026-06-25.
> **Decision driver (from the user):** don't switch off async for convention's sake;
> only change a route where sync is *genuinely* better, and don't introduce new issues.

## Problem (A3, grounded in the code)

`async def` routes that do **synchronous** psycopg2 DB work run that work directly on
the event loop. Under concurrency the loop can't serve other requests while a sync DB
call is in flight, so unrelated requests serialize. FastAPI's intended fix: a route
declared plain `def` runs in the threadpool, so its blocking work never touches the
loop.

## Investigation — does async serve a real purpose here? (verified 2026-06-25)

- **No concurrent fan-out anywhere.** `grep` for `gather`/`create_task`/`as_completed`/
  `TaskGroup` across `app/` → none. Every Spotify call is `await`ed **sequentially**,
  one per request.
- **The ingest service is fully synchronous.** `app/services/spotify_ingest_service.py`
  has zero `async`/`await`. So inside `get_recs`, all the DB work
  (`with_for_update().one()`, `get_todays_dispatch`, `snapshot_is_stale`,
  `add_user_top_songs`, `query_recommendations`, `db.commit()`) already runs on the
  event loop regardless of the route keyword.
- **Async `httpx` is used only in `SpotifyAuthService`** (4 `AsyncClient` blocks). Its
  benefit is **cross-request**: while one request awaits Spotify's network response,
  the loop can serve others. Real, but scale-dependent — and not in-request
  concurrency (there is none).
- **`get_db` and `get_current_user` are sync dependencies** → FastAPI already runs them
  in the threadpool for every route. The loop-blocking is specifically the DB work in
  route **bodies**.

## Route inventory & decision

| Route | File:line | `await`? | Blocking DB in body? | Decision |
|-------|-----------|----------|----------------------|----------|
| `get_top_tracks` | [songs.py:102](../app/api/v1/songs.py#L102) | no | **yes** (`db.query(UserTopSong)…all()`) | **→ `def`** |
| `get_recs` | [songs.py:60](../app/api/v1/songs.py#L60) | yes (2 Spotify) | yes (lock + ingest svc) | keep `async` |
| `spotify_callback` | [auth.py:43](../app/api/v1/auth.py#L43) | yes (3 Spotify) | light (`upsert_user` commit) | keep `async` |
| `get_status` | [songs.py:48](../app/api/v1/songs.py#L48) | no | no (in-memory set) | keep `async` |
| `me` | [auth.py:78](../app/api/v1/auth.py#L78) | no | no | keep `async` |
| `logout` | [auth.py:84](../app/api/v1/auth.py#L84) | no | no | keep `async` |
| `spotify_login` | [auth.py:33](../app/api/v1/auth.py#L33) | no | no (in-memory dict) | keep `async` |

### Why only `get_top_tracks` changes
- **Group 1 (`get_top_tracks`) → `def`:** does a real blocking DB query, awaits
  nothing. Converting moves it to the threadpool with zero loss — no async I/O to
  sacrifice, no service changes, no concurrency given up. This is the textbook A3 case.
- **Group 2 (`get_recs`, `spotify_callback`) stay `async`:** the async on the Spotify
  calls is justified (non-blocking outbound network). Making them `def` would force
  `SpotifyAuthService` to sync `httpx.Client`, churn `test_spotify_timeouts.py` /
  `test_auth.py` / `test_songs.py`, and push legitimate async I/O into the bounded
  (~40-thread) threadpool — i.e. *introduce more* for marginal gain at single-worker,
  pre-launch scale. See "Known residual" for the correct future fix.
- **Group 3 (`get_status`/`me`/`logout`/`spotify_login`) stay `async`:** they do no
  blocking I/O in the body, so `def` would only **add** a threadpool dispatch hop — a
  tiny cost, not a benefit. The lone sync dependency (`get_current_user`) is already
  threadpooled. Converting would buy nothing but uniformity, which we're not
  optimizing for.

## The change (one route)

In [app/api/v1/songs.py:102](../app/api/v1/songs.py#L102):

```python
# before
async def get_top_tracks(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TopTracksResponse:

# after
def get_top_tracks(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TopTracksResponse:
```

Body is unchanged. That is the entire functional diff.

### Why it's safe
- **No `await` in the body** — nothing to lose by dropping `async`.
- **`slowapi` works with sync routes.** The `@limiter.limit(..., key_func=session_key)`
  decorator supports both; the required `request: Request` param is present.
- **Session lifecycle is fine.** For a `def` route FastAPI runs the whole body in one
  threadpool thread; the `get_db` session is created, used, and closed within that same
  thread (sync SQLAlchemy is safe when a session isn't shared across threads — it
  isn't here).
- **Return type / response model unchanged** (`TopTracksResponse`).

## Known residual (documented, not fixed now)
`get_recs` still runs blocking DB on the loop. The right fix is **not** a sync
conversion (it would threadpool the justified async Spotify I/O) but offloading **just
the DB calls** via `await run_in_threadpool(...)` / `asyncio.to_thread(...)` while
keeping the route async. Deferred deliberately: it adds wrapping complexity around the
`BackgroundTasks` + session interplay, and the blocking is minor today (`get_recs` is
rate-limited to 2/min/user and the heavy work — downloads, TF inference — is already in
`BackgroundTasks`). Revisit if/when concurrency makes it measurable (ties to the
deployment plan's worker-count decision).

## Validation
- `pytest backend/tests/test_top_tracks.py` — the endpoint's direct coverage; must stay
  green (TestClient calls the route the same way whether `def` or `async def`).
- `pytest` (full backend suite) — confirm no regression elsewhere.
- Optional manual: hit `/api/v1/items/top_tracks/` and confirm identical JSON
  (`tracks` + `last_synced_at`).

## Risk / rollback
- **Risk: minimal.** One keyword on one route; no behavior change, no signature change,
  no dependency change.
- **Rollback:** revert the single line (`def` → `async def`).

## Files changed
| File | Change |
|------|--------|
| [app/api/v1/songs.py](../app/api/v1/songs.py) | `get_top_tracks`: `async def` → `def` (body unchanged) |

## Out of scope (recorded so it isn't re-litigated)
- Converting `SpotifyAuthService` to sync httpx (rejected — would threadpool justified
  async I/O + churn tests for no real gain at current scale).
- `run_in_threadpool` offload for `get_recs`/`spotify_callback` (future option above).
- Async SQLAlchemy + asyncpg (the other A3 direction — a much larger architectural
  change; not chosen).
- Group 3 conversions (no benefit).
