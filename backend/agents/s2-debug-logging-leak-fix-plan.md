# S2 Fix Plan — Debug logging leaks session tokens & PII (HIGH)

> Status: **Plan approved, not yet implemented.**
> Source finding: [.claude-backend-optimization.md → S2](.claude-backend-optimization.md#L54)
> Scope: this plan covers **S2 only**. Previous item [S1](s1-session-secret-fix-plan.md)
> is done; S3 (CORS) is next.

## 1. The bug

Two debug prints emit sensitive data to stdout (and therefore to anyone with log
access):

1. **[dependencies.py:8](../app/core/dependencies.py#L8)** — prints **all cookies
   on every authenticated request**, including the `session` token:
   ```python
   print(f"DEBUG get_current_user cookies: {dict(request.cookies)}", flush=True)
   ```
   The `session` cookie is a 30-day itsdangerous-signed token; anyone who reads it
   from logs can replay it and impersonate the user until it expires.

2. **[auth.py:50](../app/api/v1/auth.py#L50)** — a bare `traceback.print_exc()` in
   the OAuth callback exception handler:
   ```python
   except Exception as e:
       print(f"ERROR Spotify callback failed: {type(e).__name__}: {e}", flush=True)
       traceback.print_exc()
   ```
   The printed traceback's frame locals can contain the OAuth `code`,
   `token_data` (`access_token` / `refresh_token`), and the Spotify profile.

### Audit correction (already reflected)
The audit confirms [auth.py:49](../app/api/v1/auth.py#L49) no longer dumps a raw
stack trace — it is "already scrubbed" to `type(e).__name__: {e}`. The remaining
leaks are exactly the two lines above. **No other place in `app/` logs sensitive
data** — verified by a sweep agent (the ingest-service prints at
[spotify_ingest_service.py](../app/services/spotify_ingest_service.py) only emit
track titles / file paths / user-facing error messages, and
[main.py:28](../app/main.py#L28) prints a config-flag warning). The `logging`
module is **not used anywhere** in `app/`.

## 2. The fix (decisions confirmed with the user)

| Decision | Choice |
| --- | --- |
| Scope | **Minimal (audit-corrected)** — delete the two leaky lines only. Do **not** introduce the `logging` module (no logging infra exists; out of scope for an XS security fix). |
| `auth.py:49` scrubbed line | **Also drop the `{e}` message** — log only `type(e).__name__`. Fully removes the chance that an exception string echoes the OAuth `code`. The `?error=auth_failed` redirect already tells the user something failed. |
| Regression test | **Add one** — a `capsys` test asserting neither the session token nor the OAuth code / exception detail / traceback reaches stdout. |

### 2a. `app/core/dependencies.py`
Delete the debug cookie print entirely (line 8). The function keeps its existing
behavior — it already reads `request.cookies.get("session")` on the next line.

```python
def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("session")
    ...
```

### 2b. `app/api/v1/auth.py`
- Drop `traceback.print_exc()` (line 50).
- Tighten the line above it to drop the exception message `{e}`, keeping only the
  exception type:
  ```python
  except Exception as e:
      print(f"ERROR Spotify callback failed: {type(e).__name__}", flush=True)
      return RedirectResponse(url=f"{frontend_url}?error=auth_failed")
  ```
- Remove the now-unused `import traceback` (line 3).

> We keep a single scrubbed `print` (type only) rather than going silent so an
> operator can still see *that* a callback failed and the failure class, without
> any secret-bearing detail. This stays within "minimal scope" — no new logging
> dependency.

### 2c. Test — sensitive data never reaches stdout
Add a `TestNoSensitiveLogging` class to
[tests/test_auth.py](../tests/test_auth.py) (where the OAuth + `/me` flows are
already exercised). Two tests, using pytest's `capsys`:

1. **Authenticated request:** call `/auth/me` with a `valid_session` cookie;
   assert the token string is **not** in captured stdout (and the old
   `"DEBUG get_current_user cookies"` line is gone).
2. **Failed callback:** drive `exchange_code` to raise with a recognizable
   message while passing a recognizable `code`; assert stdout contains **neither**
   the OAuth `code`, the exception message, nor `"Traceback (most recent call
   last)"`. (It may contain the scrubbed `type(e).__name__`.)

## 3. Why this is safe (verified)

- **No tests depend on the stdout of these lines** — a sweep found zero
  `capsys`/`capfd`/`caplog` usage in the existing suite; nothing parses these
  prints.
- Removing the cookie print does not change `get_current_user`'s control flow —
  it reads cookies on the following line regardless.
- Dropping `traceback.print_exc()` and the `{e}` detail does not change the HTTP
  response: the handler still redirects to `?error=auth_failed`. The existing
  `test_*_failure_redirects_with_auth_failed` tests in `test_auth.py` continue to
  pass.

## 4. Files changed

| File | Change |
| --- | --- |
| [app/core/dependencies.py](../app/core/dependencies.py) | Remove the debug cookie `print` (line 8). |
| [app/api/v1/auth.py](../app/api/v1/auth.py) | Remove `traceback.print_exc()`, drop `{e}` from the error print, remove `import traceback`. |
| [tests/test_auth.py](../tests/test_auth.py) | Add `TestNoSensitiveLogging` (2 `capsys` regression tests). |

No changes to `session.py`, `limiter.py`, `dependencies.py` control flow, or
`main.py`.

## 5. Validation

```bash
cd backend && pytest                 # full suite stays green
cd backend && pytest tests/test_auth.py -v   # incl. new no-leak tests
```

## 6. Out of scope (next items, per execution order)

- **S3** — CORS origin/port mismatch in [main.py:41](../app/main.py#L41).
- A future "proper logging" pass (logging module, levels, structured logs) is
  explicitly deferred — S2 is scoped to stopping the leak, not building logging
  infrastructure.
