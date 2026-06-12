# S3 Fix Plan — CORS origin doesn't match the real frontend (MEDIUM, also a bug)

> Status: **Plan approved, not yet implemented.**
> Source finding: [.claude-backend-optimization.md → S3](.claude-backend-optimization.md#L72)
> Scope: this plan covers **S3 only**. Previous items
> [S1](s1-session-secret-fix-plan.md) and [S2](s2-debug-logging-leak-fix-plan.md)
> are done; S4 (Spotify timeouts) is next.

## 1. The bug

[main.py:39-45](../app/main.py#L39) configures CORS with a hardcoded origin that
**omits the port**, while the real frontend runs on port 3000:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://127.0.0.1"],   # ← no :3000
    allow_credentials=True,
    allow_methods=["*"],                    # ← too broad with credentials
    allow_headers=["*"],                    # ← too broad with credentials
)
```

The frontend's `Origin` header is `https://127.0.0.1:3000` (every frontend→backend
`fetch` uses `credentials: "include"` — verified across
[auth-gate.tsx](../../frontend/src/components/auth-gate.tsx#L23),
[profile-content.tsx](../../frontend/src/components/profile-content.tsx#L55),
[song-rec-carousel.tsx](../../frontend/src/components/song-rec-carousel.tsx#L129),
[logout/page.tsx](../../frontend/src/app/logout/page.tsx#L19)). An origin
including a port never matches `https://127.0.0.1`, so with
`allow_credentials=True` the browser **rejects every credentialed response** — a
correctness bug, not just hardening. It's also config-rot-prone (the origin is
duplicated, untyped, and drifts from `FRONTEND_URL`).

### Verified facts (sweep agent)
- **Only [main.py](../app/main.py) references CORS** — nothing else changes.
- CORS-governed requests the browser sends to this backend: **methods `GET` and
  `POST`** (GET: `/auth/me`, `/items/status`, `/items/top_tracks/`,
  `/items/song_recs/`; POST: `/auth/logout`), **no custom request headers** (only
  cookies via `credentials: "include"`). `/auth/spotify/login` and
  `/auth/spotify/callback` are full-page **navigations / redirects, not `fetch`**,
  so CORS does not govern them.
- `FRONTEND_URL` ([auth.py:19](../app/api/v1/auth.py#L19)) defaults to
  `https://127.0.0.1:3000/dashboard` — it carries a **path**, so it cannot be
  reused directly as a CORS origin (origins are scheme+host+port only). This is
  why a dedicated origins var is cleaner than parsing `FRONTEND_URL`.
- Starlette `CORSMiddleware`: for an **allowed** origin it echoes
  `Access-Control-Allow-Origin: <origin>` + `Access-Control-Allow-Credentials:
  true`; for a **disallowed** origin the `Access-Control-Allow-Origin` header is
  **absent** — that's the assertion a test uses.
- `conftest.py` injects env vars **before** the app is imported, so a new
  `CORS_ALLOWED_ORIGINS` var read at import time is testable; if unset, the
  default applies.

## 2. The fix (decisions confirmed with the user)

| Decision | Choice |
| --- | --- |
| Origin source | **New `CORS_ALLOWED_ORIGINS` env var**, comma-split (matches the audit). Decoupled from the redirect URL; supports multiple origins. |
| Unset behavior | **Default to `https://127.0.0.1:3000`** (local dev). An allowed-origin is not a secret, so a known localhost default is fine and keeps setup frictionless; prod overrides via env. (Contrast S1, where the secret had no default.) |
| Methods / headers | **Tighten** to `allow_methods=["GET", "POST", "OPTIONS"]`, `allow_headers=["Content-Type"]` — no `"*"` alongside `allow_credentials=True`. |

### 2a. `app/main.py`
Add `import os`, read + parse the origins above the app definition, and update the
middleware:

```python
import os
...
_cors_origins = os.getenv("CORS_ALLOWED_ORIGINS", "https://127.0.0.1:3000")
ALLOWED_ORIGINS = [o.strip() for o in _cors_origins.split(",") if o.strip()]
...
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)
```

`OPTIONS` is included so CORS preflight succeeds; `Content-Type` covers any future
JSON `POST` (today's POST `/logout` is bodyless, but listing it is harmless and
future-proofs the carousel/recs flows).

### 2b. `backend/.env.example`
Document the new var next to `FRONTEND_URL`:

```dotenv
# Allowed CORS origins for the browser frontend (comma-separated, scheme+host+port,
# NO trailing path). Defaults to https://127.0.0.1:3000 if unset.
CORS_ALLOWED_ORIGINS=https://127.0.0.1:3000
```

> The repo-root `.env-backend` may add this var per environment; unset is fine for
> local dev because of the default.

### 2c. Test — allowed origin echoed, disallowed origin rejected
The audit's validation note asks for "a disallowed origin is rejected"
([validation](.claude-backend-optimization.md#L282)). Add a new
`backend/tests/test_cors.py`. Using **preflight `OPTIONS`** requests means the
middleware answers before routing, so no auth/mocking is needed:

```python
PREFLIGHT = {"Access-Control-Request-Method": "GET"}

class TestCORS:
    def test_allowed_origin_is_echoed_with_credentials(self, client):
        resp = client.options(
            "/api/v1/auth/me",
            headers={"Origin": "https://127.0.0.1:3000", **PREFLIGHT},
        )
        assert resp.headers.get("access-control-allow-origin") == "https://127.0.0.1:3000"
        assert resp.headers.get("access-control-allow-credentials") == "true"

    def test_disallowed_origin_is_rejected(self, client):
        resp = client.options(
            "/api/v1/auth/me",
            headers={"Origin": "https://evil.example.com", **PREFLIGHT},
        )
        assert "access-control-allow-origin" not in resp.headers

    def test_portless_localhost_origin_is_rejected(self, client):
        """Regression: the old config allowed https://127.0.0.1 (no port)."""
        resp = client.options(
            "/api/v1/auth/me",
            headers={"Origin": "https://127.0.0.1", **PREFLIGHT},
        )
        assert "access-control-allow-origin" not in resp.headers
```

> The default (`https://127.0.0.1:3000`) applies in tests because conftest does
> not set `CORS_ALLOWED_ORIGINS`; the third test directly proves the original bug
> (port-less origin) is fixed.

## 3. Why this is safe (verified)

- Only `main.py` reads CORS config; no other module is affected.
- The env var is read at import with a default, so existing tests (which never set
  it) get the local dev origin — no conftest change needed.
- Tightened methods/headers cover everything the frontend actually sends (GET,
  POST, no custom headers); `OPTIONS` + `Content-Type` add headroom.

## 4. Files changed

| File | Change |
| --- | --- |
| [app/main.py](../app/main.py) | `import os`; parse `CORS_ALLOWED_ORIGINS` (default local dev); tighten methods/headers. |
| `backend/.env.example` | Document `CORS_ALLOWED_ORIGINS`. |
| `backend/tests/test_cors.py` | **New** — allowed/disallowed/port-less origin tests. |

No changes to `auth.py`, `session.py`, `dependencies.py`, or `FRONTEND_URL`
(its `/dashboard` path is correct for the redirect target).

## 5. Validation

```bash
cd backend && pytest                  # full suite stays green
cd backend && pytest tests/test_cors.py -v
```

## 6. Out of scope (next items, per execution order)

- **S4** — intentional/shared timeouts on outbound Spotify calls.
- Then S5 (OAuth state TTL), S6 (security headers), then performance items.
