# S4 Fix Plan — Explicit timeouts on outbound Spotify calls (LOW)

> Status: **Plan approved, not yet implemented.**
> Source finding: [.claude-backend-optimization.md → S4](.claude-backend-optimization.md#L110)
> Scope: this plan covers **S4 only**. Previous items
> [S1](s1-session-secret-fix-plan.md), [S2](s2-debug-logging-leak-fix-plan.md),
> and [S3](s3-cors-origin-fix-plan.md) are done; S5 (OAuth state TTL) is next.

## 1. The bug

Every outbound Spotify HTTP call in
[spotify_auth_service.py](../app/services/spotify_auth_service.py) builds a fresh
client with **no explicit `timeout`**:

```python
async with httpx.AsyncClient() as client:   # ← implicit, untuned 5s default
    response = await client.post(...)
```

Four methods do this:
- [exchange_code](../app/services/spotify_auth_service.py#L42) (L43)
- [get_top_tracks](../app/services/spotify_auth_service.py#L56) (L57)
- [get_spotify_profile](../app/services/spotify_auth_service.py#L66) (L67)
- [refresh_tokens](../app/services/spotify_auth_service.py#L103) (L107)

**Audit correction (already in the source doc):** the original "stalls
indefinitely / mild DoS" premise is wrong. `httpx.AsyncClient()` applies a
**default 5s timeout** unless you pass `timeout=None`, and none of these clients
disable it — so nothing can hang forever. Severity is **LOW**. The real issue is
that the 5s is implicit and untuned.

### Verified facts (sweep agent)
- These **4 methods are the only outbound network calls** in `app/`.
  `spotify_ingest_service.py` shells out to `spotdl` via `subprocess` (out of
  scope — that's [A5](.claude-backend-optimization.md#L259));
  `audio_genre_classifier.py` does TensorFlow inference, no network.
- `httpx==0.28.1` ([backend_requirements.txt](../backend_requirements.txt#L4))
  accepts a bare float or `httpx.Timeout(...)` as the `timeout`.
- `load_dotenv()` already runs at module top
  ([spotify_auth_service.py:14-15](../app/services/spotify_auth_service.py#L14)),
  and `conftest.py` injects env **before** importing the app, so a module-level
  `os.getenv` for the timeout is test-safe and matches the existing
  `SPOTIFY_CLIENT_ID` / `SPOTIFY_REDIRECT_URI` reads in the same file.

## 2. The fix (decisions confirmed with the user)

| Decision | Choice |
| --- | --- |
| Scope | **Timeouts only.** A single shared/pooled `AsyncClient` in `lifespan` is **deferred** — at current traffic the connection-reuse win is negligible, and the audit already demoted S4 to LOW. (Revisit alongside the scaling items.) |
| Timeout value | **Env var `SPOTIFY_HTTP_TIMEOUT`, default `10.0`** — tunable per environment like `CORS_ALLOWED_ORIGINS`, parsed as a float. |
| Granularity | **Single budget for all phases** — one value applied to connect/read/write/pool via the client constructor. |

### 2a. `app/services/spotify_auth_service.py`
Add a module-level constant next to the other env reads:

```python
SPOTIFY_HTTP_TIMEOUT = float(os.getenv("SPOTIFY_HTTP_TIMEOUT", "10.0"))
```

Then set it on each per-call client (one edit, applied to all four call sites):

```python
async with httpx.AsyncClient(timeout=SPOTIFY_HTTP_TIMEOUT) as client:
```

Putting the timeout on the **constructor** (not each `.get`/`.post`) makes it the
client default for connect/read/write/pool uniformly — the cleanest single point.

### 2b. `backend/.env.example`
Document the new var next to `CORS_ALLOWED_ORIGINS`:

```dotenv
# Timeout (seconds) for outbound Spotify API calls. Defaults to 10.0 if unset.
SPOTIFY_HTTP_TIMEOUT=10.0
```

### 2c. Test — `backend/tests/test_spotify_timeouts.py` (new)
Tests mock the auth service at the **method level**, so the real client
construction is never exercised by the existing suite. Add one focused regression
test that patches `httpx.AsyncClient` and asserts the configured timeout is passed:

```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.services import spotify_auth_service
from app.services.spotify_auth_service import SpotifyAuthService

@pytest.mark.asyncio
async def test_exchange_code_uses_configured_timeout():
    svc = SpotifyAuthService()
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"access_token": "x"}
    fake_client.post = AsyncMock(return_value=fake_resp)

    with patch.object(spotify_auth_service.httpx, "AsyncClient", return_value=fake_client) as mk:
        await svc.exchange_code("code123")

    mk.assert_called_once_with(timeout=spotify_auth_service.SPOTIFY_HTTP_TIMEOUT)
    assert spotify_auth_service.SPOTIFY_HTTP_TIMEOUT == 10.0
```

> `pytest-asyncio` is already used in the suite (the rate-limiting tests await
> async mocks); if a marker/mode tweak is needed, mirror the existing async tests.

## 3. Why this is safe

- Only `spotify_auth_service.py` constructs outbound clients — nothing else changes.
- The env var is read at module import with a `10.0` default, so existing tests
  (which never set it) keep the same effective behavior, only now **explicit**.
- No call signatures change; routes and tests that patch service methods are
  untouched.

## 4. Files changed

| File | Change |
| --- | --- |
| [app/services/spotify_auth_service.py](../app/services/spotify_auth_service.py) | Add `SPOTIFY_HTTP_TIMEOUT` constant; pass it to all 4 `AsyncClient(...)` constructions. |
| `backend/.env.example` | Document `SPOTIFY_HTTP_TIMEOUT`. |
| `backend/tests/test_spotify_timeouts.py` | **New** — asserts the configured timeout is passed to the client. |

## 5. Validation

```bash
cd backend && pytest                          # full suite stays green
cd backend && pytest tests/test_spotify_timeouts.py -v
```

## 6. Out of scope (deferred / next items)

- **Shared `AsyncClient` in `lifespan`** (connection reuse) — deferred until
  traffic/scaling justifies it; ties into [A1](.claude-backend-optimization.md#L218).
- **S5** — OAuth `state` TTL — the next item per the execution order.
