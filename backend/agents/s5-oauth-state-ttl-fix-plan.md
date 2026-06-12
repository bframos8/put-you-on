# S5 Fix Plan — OAuth `state` recorded but never expired (MEDIUM)

> Status: **Plan approved, not yet implemented.**
> Source finding: [.claude-backend-optimization.md → S5](.claude-backend-optimization.md#L123)
> Scope: this plan covers **S5 only**. Previous items
> [S1](s1-session-secret-fix-plan.md), [S2](s2-debug-logging-leak-fix-plan.md),
> [S3](s3-cors-origin-fix-plan.md), and [S4](s4-spotify-timeouts-fix-plan.md) are
> done; S6 (security headers) is next.

## 1. The bug

[/spotify/login](../app/api/v1/auth.py#L22) records a CSRF `state` with a
timestamp:

```python
request.app.state.oauth_states[state] = time.time()   # auth.py:26
```

…but [/spotify/callback](../app/api/v1/auth.py#L30) only checks **existence**,
never **age**:

```python
oauth_states = request.app.state.oauth_states          # auth.py:38
if not state or state not in oauth_states:
    return RedirectResponse(url=f"{frontend_url}?error=state_mismatch")
del oauth_states[state]                                 # auth.py:41
```

The stored `time.time()` is written but **never read**. Consequences:
- **Unbounded memory growth** — every abandoned login (user closes the tab at the
  Spotify consent screen) leaves a `state` in the dict forever.
- **No CSRF TTL** — a captured `state` stays valid indefinitely instead of for a
  short window.

### Verified facts (sweep agent)
- `app.state.oauth_states` is touched in **exactly three places**:
  [main.py:26](../app/main.py#L26) (init `{}`), [auth.py:26](../app/api/v1/auth.py#L26)
  (write on login), [auth.py:38-41](../app/api/v1/auth.py#L38) (read/del on
  callback). Nothing else iterates or depends on its shape.
- `os` and `time` are already imported in `auth.py`; a module-level
  `int(os.getenv(...))` matches the existing `get_frontend_url` env read.
- `conftest.py` injects env before import and does **not** set the new var, so the
  default applies in tests; it does **not** monkeypatch `time.time()`, so a test
  can seed an expired state with `time.time() - 700` directly.
- Every existing auth test seeds **fresh** states (`time.time()`) and uses them
  within milliseconds, so neither the sweep nor the TTL check breaks them.

## 2. The fix (decisions confirmed with the user)

| Decision | Choice |
| --- | --- |
| TTL value | **Env var `OAUTH_STATE_TTL_SECONDS`, default `600`** (10 min), parsed as `int`. Documented in `.env.example`. |
| Expired-state error | **Reuse `?error=state_mismatch`** — an expired state is functionally an invalid CSRF token; no new error code / frontend copy. |
| Sweep point | **On each login** (the audit's recommendation) — bounds memory without a background task. The callback additionally rejects an expired-but-present state. |

### 2a. `app/api/v1/auth.py`
Add the constant + a small sweep helper near the top:

```python
OAUTH_STATE_TTL_SECONDS = int(os.getenv("OAUTH_STATE_TTL_SECONDS", "600"))


def _sweep_expired_states(oauth_states: dict, now: float) -> None:
    expired = [s for s, ts in oauth_states.items() if now - ts > OAUTH_STATE_TTL_SECONDS]
    for s in expired:
        del oauth_states[s]
```

> The sweep collects keys first, then deletes — never mutates the dict mid-iteration.

Login — sweep before recording the new state:

```python
@router.get("/spotify/login")
@limiter.limit("20/minute")
async def spotify_login(request: Request):
    auth_url, state = auth_service.get_auth_url()
    oauth_states = request.app.state.oauth_states
    _sweep_expired_states(oauth_states, time.time())
    oauth_states[state] = time.time()
    return RedirectResponse(url=auth_url)
```

Callback — treat an expired state exactly like an unknown one:

```python
    oauth_states = request.app.state.oauth_states
    if not state or state not in oauth_states:
        return RedirectResponse(url=f"{frontend_url}?error=state_mismatch")
    issued_at = oauth_states.pop(state)
    if time.time() - issued_at > OAUTH_STATE_TTL_SECONDS:
        return RedirectResponse(url=f"{frontend_url}?error=state_mismatch")
```

> Using `pop` consumes the state in one step (single-use), so an expired state is
> both removed and rejected. (Replaces the existing `del oauth_states[state]`.)

### 2b. `backend/.env.example`
Document the new var next to `SPOTIFY_HTTP_TIMEOUT`:

```dotenv
# Lifetime (seconds) of an OAuth CSRF `state` before the callback rejects it.
# Defaults to 600 (10 min) if unset.
OAUTH_STATE_TTL_SECONDS=600
```

### 2c. Tests — extend `backend/tests/test_auth.py`
Add to `TestSpotifyCallback`:

```python
    def test_expired_state_redirects_with_state_mismatch(self, client):
        """A state older than OAUTH_STATE_TTL_SECONDS is rejected like an unknown one."""
        from app.main import app
        app.state.oauth_states["old_state"] = time.time() - 700  # > 600s default TTL
        resp = client.get(
            f"{PREFIX}/spotify/callback?code=code&state=old_state",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        assert "state_mismatch" in resp.headers["location"]
        assert "old_state" not in app.state.oauth_states  # consumed, not left to leak
```

Add to `TestSpotifyLogin`:

```python
    def test_login_sweeps_expired_states(self, client):
        """Logging in evicts stale states so the dict can't grow unbounded."""
        from app.main import app
        app.state.oauth_states["stale"] = time.time() - 700
        with patch(
            "app.api.v1.auth.auth_service.get_auth_url",
            return_value=("https://accounts.spotify.com/authorize?state=fresh", "fresh"),
        ):
            client.get(f"{PREFIX}/spotify/login", follow_redirects=False)
        assert "stale" not in app.state.oauth_states   # swept
        assert "fresh" in app.state.oauth_states        # new one kept
```

## 3. Why this is safe

- Only `auth.py` reads/writes `oauth_states`; the sweep helper is local to it.
- The env var is read at import with a `600` default, so existing tests (which
  never set it) keep current behavior and all seed fresh states → unaffected.
- `pop` preserves the existing single-use semantics; the extra check only adds a
  rejection path for genuinely-old states.

## 4. Files changed

| File | Change |
| --- | --- |
| [app/api/v1/auth.py](../app/api/v1/auth.py) | Add `OAUTH_STATE_TTL_SECONDS` + `_sweep_expired_states`; sweep on login; expiry check on callback. |
| `backend/.env.example` | Document `OAUTH_STATE_TTL_SECONDS`. |
| `backend/tests/test_auth.py` | Add expired-state-rejected + login-sweeps-stale tests. |

## 5. Validation

```bash
cd backend && pytest                       # full suite stays green
cd backend && pytest tests/test_auth.py -v
```

## 6. Out of scope (deferred / next items)

- **Cross-worker state** (Redis/Postgres-backed `oauth_states`) — that's
  [A1](.claude-backend-optimization.md#L218); this fix is correct on a single
  process.
- **S6** — baseline security headers — the next item per the execution order.
