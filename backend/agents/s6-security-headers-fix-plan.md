# S6 Fix Plan — Missing baseline security headers (LOW/MEDIUM)

> Status: **Plan approved, not yet implemented.**
> Source finding: [.claude-backend-optimization.md → S6](.claude-backend-optimization.md#L133)
> Scope: this plan covers **S6 only**. Previous items
> [S1](s1-session-secret-fix-plan.md), [S2](s2-debug-logging-leak-fix-plan.md),
> [S3](s3-cors-origin-fix-plan.md), [S4](s4-spotify-timeouts-fix-plan.md), and
> [S5](s5-oauth-state-ttl-fix-plan.md) are done. S6 is the last Tier-1 security
> item; after it the plan moves to the performance items (P3, P4, P6).

## 1. The bug

[main.py](../app/main.py) registers **only** `CORSMiddleware` — no baseline
security response headers (`X-Content-Type-Options`, `Referrer-Policy`,
`X-Frame-Options`, `Content-Security-Policy`, HSTS). Responses are therefore
missing standard hardening against MIME-sniffing, clickjacking, referrer leakage,
and (over TLS) protocol downgrade.

### Verified facts (sweep agent)
- **Deployment**: nginx terminates TLS on `:443` ([nginx.conf](../../nginx/nginx.conf))
  and proxies `/api/` → uvicorn on plain HTTP `:8000` ([Dockerfile](../Dockerfile)).
  nginx adds **no** security headers and does **not** set `X-Forwarded-Proto`, so
  the app always sees `scheme=http` even though the client connection is real TLS.
  → HSTS cannot be gated on the request scheme; it needs an explicit signal.
- No route or middleware currently sets any of these headers (grep: zero matches).
- A function-based `@app.middleware("http")` registered after
  `app.add_middleware(CORSMiddleware, ...)` becomes the **outermost** layer — it
  runs for **every** response, including CORS-preflight `OPTIONS`, slowapi `429`s,
  and auth `401`s, and sets distinct headers without clobbering CORS's own.
- A middleware function referencing the module global `ENABLE_HSTS` resolves it at
  **call time**, so tests can `patch("app.main.ENABLE_HSTS", True)` against the
  existing singleton `app` + `client` fixture. `conftest.py` does not set
  `ENABLE_HSTS`, so default-off holds in tests.

## 2. The fix (decisions confirmed with the user)

| Decision | Choice |
| --- | --- |
| HSTS | **Env-gated in the app middleware** — emit `Strict-Transport-Security` only when `ENABLE_HSTS=true` (default off). Keeps all headers in one place; the audit's "only behind real TLS" gate becomes an explicit flag set in TLS environments. |
| Header set | **Trio + locked-down API CSP** — `nosniff`, `Referrer-Policy`, `X-Frame-Options: DENY`, plus `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (fits a JSON-only API that is never framed). |

### Headers emitted

Always:
```
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
X-Frame-Options: DENY
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
```
Only when `ENABLE_HSTS=true`:
```
Strict-Transport-Security: max-age=31536000; includeSubDomains
```
> `max-age` = 1 year. `preload` deliberately **omitted** (preload is a hard-to-undo
> commitment; add later if desired).

### 2a. `app/main.py`
Read the flag next to the CORS config and add the middleware. The static headers
live in a module-level dict so they're declared once:

```python
ENABLE_HSTS = os.getenv("ENABLE_HSTS", "").lower() == "true"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
```

> **Implementation correction (found during validation):** the first attempt used
> a `@app.middleware("http")` function — but that is a `BaseHTTPMiddleware`, which
> under **Starlette 0.27.0 drops the response body when a route attaches a
> `BackgroundTask`**. The stale-snapshot `/song_recs/` path does exactly that
> (`background_tasks.add_task(_run_process_top_tracks, ...)` in
> [songs.py](../app/api/v1/songs.py#L91)), so `test_stale_snapshot_returns_processing_status`
> failed with an empty body. The fix is a **pure ASGI middleware** that stamps the
> headers onto the `http.response.start` message — no body buffering, no
> BackgroundTask interaction:

```python
from starlette.datastructures import MutableHeaders

class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in SECURITY_HEADERS.items():
                    headers.setdefault(key, value)
                if ENABLE_HSTS:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_with_headers)

# registered alongside CORS:
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, ...)
```

> `setdefault` so a route that intentionally sets its own value (none do today)
> would win — defensive, no behavior change now. `ENABLE_HSTS` is read inside
> `send_with_headers` at call time, so the test patch on `app.main.ENABLE_HSTS`
> still works.

### 2b. `backend/.env.example`
Document the new flag next to `OAUTH_STATE_TTL_SECONDS`:

```dotenv
# Emit HSTS (Strict-Transport-Security). Enable ONLY where TLS terminates in
# front of the app (e.g. behind the nginx :443 proxy). Defaults to off.
ENABLE_HSTS=false
```

### 2c. Test — `backend/tests/test_security_headers.py` (new)
Mirrors [test_cors.py](../tests/test_cors.py) house style (class-based,
`resp.headers.get(...)`, uses the `client` fixture):

```python
from unittest.mock import patch
import app.main as main

BASELINE = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "x-frame-options": "DENY",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}

class TestSecurityHeaders:
    def test_baseline_headers_present_on_normal_response(self, client):
        resp = client.get("/api/v1/auth/me")  # 401, but headers still apply
        for name, value in BASELINE.items():
            assert resp.headers.get(name) == value

    def test_headers_present_on_error_response(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401
        assert resp.headers.get("x-frame-options") == "DENY"

    def test_hsts_absent_by_default(self, client):
        resp = client.get("/api/v1/auth/me")
        assert "strict-transport-security" not in resp.headers

    def test_hsts_present_when_enabled(self, client):
        with patch.object(main, "ENABLE_HSTS", True):
            resp = client.get("/api/v1/auth/me")
        assert resp.headers.get("strict-transport-security") == (
            "max-age=31536000; includeSubDomains"
        )
```

> `/auth/me` with no cookie returns 401 — the middleware still runs (it wraps the
> auth dependency), so it's a convenient no-setup endpoint to assert headers on.

## 3. Why this is safe

- Additive only — new response headers, no route/logic changes; CSP/X-Frame are
  inert for a JSON API and harden against framing/sniffing.
- HSTS is **off unless explicitly enabled**, so local HTTP/HTTPS dev is unaffected;
  set `ENABLE_HSTS=true` in the TLS-fronted environments.
- The middleware wraps everything, so 401/429/preflight responses are covered too.

## 4. Files changed

| File | Change |
| --- | --- |
| [app/main.py](../app/main.py) | Add `ENABLE_HSTS` flag, `SECURITY_HEADERS` dict, and pure-ASGI `SecurityHeadersMiddleware` (+ `MutableHeaders` import). |
| `backend/.env.example` | Document `ENABLE_HSTS`. |
| `backend/tests/test_security_headers.py` | **New** — baseline headers present (incl. on errors); HSTS off by default / on when enabled. |

## 5. Validation

```bash
cd backend && pytest                               # full suite stays green
cd backend && pytest tests/test_security_headers.py -v
```

## 6. Out of scope (next items, per execution order)

- Setting `ENABLE_HSTS=true` in the deployed `.env-backend` (ops step, not code).
- **P3, P4, P6** — query + startup performance cleanups — the next items.
