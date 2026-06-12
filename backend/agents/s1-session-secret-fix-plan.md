# S1 Fix Plan — `SESSION_SECRET` hardcoded default (CRITICAL)

> Status: **Plan approved, not yet implemented.**
> Source finding: [.claude-backend-optimization.md → S1](.claude-backend-optimization.md#L31)
> Scope: this plan covers **S1 only**. S2 (log token leak) is the next item.

## 1. The bug

[session.py:4](../app/core/session.py#L4) reads the session-signing key with a
hardcoded fallback:

```python
SESSION_SECRET = os.getenv("SESSION_SECRET", "dev-secret-change-in-production")
_serializer = URLSafeTimedSerializer(SESSION_SECRET)
```

If `SESSION_SECRET` is unset/blank in **any** environment, the serializer signs
and verifies cookies with a publicly known string. An attacker can then mint a
valid `session` cookie for any `user_id` and **fully impersonate any user**.

Blast radius (the same secret gates more than auth):
- [auth.py](../app/api/v1/auth.py) `create_session` — issues the login cookie.
- [dependencies.py](../app/core/dependencies.py) `decode_session` — authenticates every request.
- [limiter.py:8](../app/core/limiter.py#L8) `session_key` — decodes the cookie to
  derive the `user:{id}` rate-limit bucket, so a forged cookie also defeats
  per-user rate limiting.

## 2. Root cause

The secret is read **once at module import time** and the serializer is built
immediately as module-global state ([session.py:5](../app/core/session.py#L5)).
The `os.getenv(..., default)` silently substitutes a known value instead of
refusing to start.

## 3. The fix (decisions confirmed with the user)

| Decision | Choice |
| --- | --- |
| Where to fail fast | **At import in `session.py`** — earliest meaningful point; serializer is built there. |
| Strictness | **Non-blank only** — present and non-whitespace. No min-length / weak-value checks (keep S1 minimal, matches the audit's "missing/blank"). |
| Dev ergonomics | **Add a committed `.env.example`** documenting required vars + how to generate a secret. |

### 3a. `app/core/session.py`

Replace the defaulted read with a fail-fast guard:

```python
import os
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

SESSION_SECRET = os.getenv("SESSION_SECRET")
if not SESSION_SECRET or not SESSION_SECRET.strip():
    raise RuntimeError(
        "SESSION_SECRET is not set. Define it in .env-backend (local) or the "
        "environment (deploy). No default is provided because a known secret "
        "would let anyone forge session cookies. Generate one with: "
        'python -c "import secrets; print(secrets.token_hex(32))"'
    )

_serializer = URLSafeTimedSerializer(SESSION_SECRET)
```

Everything below (`SESSION_MAX_AGE`, `create_session`, `decode_session`) is
unchanged.

### 3b. New `backend/.env.example` (committed)

`.gitignore` ignores `.env-*` / `.env*` but explicitly allows `.env.example`,
so this template is safe to commit. It documents required keys with
placeholders only — **no real secrets**.

```dotenv
# Copy to ../.env-backend (repo root) and fill in real values. Do not commit that file.

# Session cookie signing key — REQUIRED. App refuses to start if unset/blank.
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
SESSION_SECRET=

# Spotify OAuth app credentials
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
SPOTIFY_REDIRECT_URI=http://localhost:8000/api/v1/auth/spotify/callback

# Frontend origin for OAuth redirect
FRONTEND_URL=https://127.0.0.1:3000
```

> Note: `main.py` loads `../.env-backend` (repo root), so the example lives in
> `backend/` as documentation while the real file stays at the repo root where
> it already exists with a 63-char secret.

### 3c. Test — startup fails without the secret

The audit explicitly asks for this ([validation note](.claude-backend-optimization.md#L271)).
Add to `tests/test_session.py`. Because the guard runs at import, the test must
clear the env var and **re-import** the module in isolation:

```python
import importlib
import os
from unittest.mock import patch

class TestSessionSecretRequired:
    def test_import_fails_when_secret_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SESSION_SECRET", None)
            import app.core.session as session_mod
            with pytest.raises(RuntimeError, match="SESSION_SECRET"):
                importlib.reload(session_mod)
        # Restore the module to the test secret for the rest of the suite.
        os.environ["SESSION_SECRET"] = "test-secret-for-unit-tests-only"
        importlib.reload(session_mod)

    def test_import_fails_when_secret_blank(self):
        with patch.dict(os.environ, {"SESSION_SECRET": "   "}):
            import app.core.session as session_mod
            with pytest.raises(RuntimeError, match="SESSION_SECRET"):
                importlib.reload(session_mod)
        os.environ["SESSION_SECRET"] = "test-secret-for-unit-tests-only"
        importlib.reload(session_mod)
```

> The reload + restore is important: `session.py` is module-global singleton
> state shared across the suite. Restoring at the end prevents the reloaded
> module (and its `_serializer`) from bleeding a different secret into other
> tests. We verified all other test files set `SESSION_SECRET` before importing
> app code, so they are unaffected by the fail-fast itself.

## 4. Why this is safe (verified)

A sub-agent traced every entry point that imports `session.py`:
- **uvicorn**: `main.py` calls `load_dotenv()` before importing `limiter` →
  `session.py`, so the secret is present.
- **alembic**: `env.py` imports only `db.database` / `db.models`; it never
  imports `session.py`, so `alembic upgrade head` is unaffected.
- **pytest**: `conftest.py` sets `SESSION_SECRET` before any app import;
  `test_genre_filtering.py` uses `os.environ.setdefault`.
- **Docker**: `Dockerfile` runs `uvicorn app.main:app` with env supplied via the
  container env / `.env-backend`.

No entry point imports `session.py` before its secret is available, so the
fail-fast only fires when the secret is genuinely missing.

## 5. Files changed

| File | Change |
| --- | --- |
| [app/core/session.py](../app/core/session.py) | Remove default; raise `RuntimeError` if missing/blank. |
| `backend/.env.example` | **New** committed template documenting required vars. |
| [tests/test_session.py](../tests/test_session.py) | Add two import-fails-without-secret tests. |

No changes to `limiter.py`, `auth.py`, `dependencies.py`, or `main.py`.

## 6. Validation

```bash
cd backend && pytest          # full suite must stay green
cd backend && pytest tests/test_session.py -v   # incl. new fail-fast tests
```

Manual smoke (optional): `unset SESSION_SECRET && python -c "import app.main"`
should raise `RuntimeError`, and with it set should import cleanly.

## 7. Out of scope (next items, per execution order)

- **S2** — remove cookie `print` in `dependencies.py:8` and the
  `traceback.print_exc()` in `auth.py:50`.
- Then S3–S6, then performance items.
