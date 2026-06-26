# A4 — Encrypt Spotify tokens at rest (app-level Fernet)

> **Status:** Plan for review (agent-checked before any edit).
> **Source item:** A4 in
> [backend-optimization-deferred.md](backend-optimization-deferred.md).
> **Branch:** `Backend-optimization`. **Date:** 2026-06-25.
> **Decision (from the user):** app-level encryption (not pgcrypto). Threat target:
> **DB-at-rest compromise** (dump / RDS snapshot / leaked backup), not a live
> app-server compromise (the app must hold the key to use the tokens).

## Problem

`spotify_access_token` / `spotify_refresh_token` are stored **plaintext** in the
`users` table — [models.py:24-25](../app/db/models.py#L24-L25) (`Column(Text)`), written
by `upsert_user` / `refresh_tokens`
([spotify_auth_service.py:82-122](../app/services/spotify_auth_service.py#L82-L122)). A
DB dump or snapshot hands an attacker durable Spotify access for **every** user. The
tokens live **only** in the DB — not in the session cookie
([session.py:19-20](../app/core/session.py#L19) signs only `user_id`) and not cached in
`app.state`.

## Approach — `EncryptedString` SQLAlchemy `TypeDecorator` + Fernet

Encrypt on write, decrypt on read at the **column type** layer, so ORM attribute access
stays transparent. This is why the change is small: **no read/write call site changes.**

Verified token access sites — all stay untouched because they go through the ORM:
- write: [spotify_auth_service.py:82,84,92-93,120,122](../app/services/spotify_auth_service.py#L82)
- read: [spotify_auth_service.py:114](../app/services/spotify_auth_service.py#L114),
  [songs.py:85](../app/api/v1/songs.py#L85)
- **No API exposure:** tokens appear in **no** `response_model`; `schemas/user.py`
  (`UserCreate`/`UserTokenUpdate`) is **dead code** (no importers) — left as-is,
  flagged for a future cleanup, out of scope here.

### Components

1. **Dependency** — add `cryptography` to
   [backend_requirements.txt](../backend_requirements.txt), **pinned** (it is **not**
   currently installed; only `itsdangerous` is present). Provides `Fernet` /
   `MultiFernet` (AES-128-CBC + HMAC, URL-safe base64 output → fits a `text` column).

2. **Key engine — new `app/core/crypto.py`**
   - Read `TOKEN_ENCRYPTION_KEYS` (comma-separated Fernet keys; **first = primary**
     encrypt key, **all = decrypt candidates** for rotation), mirroring the
     comma-split pattern of `CORS_ALLOWED_ORIGINS`.
   - **Fail-fast at import** if unset/blank — same stance as `SESSION_SECRET`
     ([session.py:5-11](../app/core/session.py#L5)). Never silently store plaintext or
     boot unable to decrypt.
   - Build `MultiFernet([Fernet(k) for k in keys])`; expose `encrypt(str) -> str` and
     `decrypt(str) -> str`. **Fernet operates on bytes**, so the helpers must
     encode/decode UTF-8: `encrypt(s) = _mf.encrypt(s.encode()).decode()` and
     `decrypt(s) = _mf.decrypt(s.encode()).decode()`.
   - Doc the generator: `python -c "from cryptography.fernet import Fernet;
     print(Fernet.generate_key().decode())"`.

3. **Type — new `app/db/types.py`**
   ```python
   class EncryptedString(TypeDecorator):
       impl = Text          # DB column stays TEXT (stores base64 ciphertext)
       cache_ok = True
       def process_bind_param(self, value, dialect):
           return None if value is None else encrypt(value)
       def process_result_value(self, value, dialect):
           return None if value is None else decrypt(value)
   ```
   `None` passthrough preserves the nullable columns. Decrypt is **strict** (raises on
   bad ciphertext) — the migration, not the runtime type, handles legacy plaintext.

4. **Model** — [models.py:24-25](../app/db/models.py#L24-L25): `Column(Text)` →
   `Column(EncryptedString)`. Nothing else. Because `impl = Text`, the **SQL column
   type is unchanged** (still `TEXT`), so Alembic autogenerate sees no schema alter —
   the only migration is a **data** backfill.

## Key management

- **Where:** `TOKEN_ENCRYPTION_KEYS` env var. Local → `.env-backend`; prod → **SSM
  Parameter Store** (SecureString), alongside `SESSION_SECRET` (deployment-gameplan
  Phase 5.1 — add it to that list). Document in
  [.env.example](../.env.example) following the existing entries.
- **⚠️ Alembic/deploy ordering (fail-fast consequence):** because `models.py` will
  import `db/types.py` → `core/crypto.py`, and `alembic/env.py` already imports the
  models, **alembic itself refuses to run any migration unless `TOKEN_ENCRYPTION_KEYS`
  is set in its process env.** Export it **before** `alembic upgrade head` (not just
  before app start) in the deploy step.
- **Rotation (designed in, cheap):** `MultiFernet` decrypts with any key in the list
  and encrypts with the first. To rotate: prepend a new key → new writes use it, old
  rows still decrypt → run a re-encrypt backfill → drop the retired key. No
  flag-day.
- **Loss = unrecoverable tokens** (users must re-auth). Mitigate by storing the key in
  SSM (KMS-backed, backed up) and never only on a laptop.

## Migrating existing plaintext rows

Once the column is `EncryptedString`, reads strict-decrypt — so existing plaintext rows
must be encrypted first. Pre-launch (brief downtime acceptable), recommended:

- **Option 1 — backfill migration (RECOMMENDED).** A new Alembic **data** migration
  whose `upgrade()` rewrites each `users` row's two token columns plaintext→ciphertext
  using `core.crypto.encrypt`. **Idempotent:** for each value, try `decrypt()` — if it
  succeeds the row is already encrypted (skip); if it raises, it's plaintext (encrypt).
  So a re-run never double-encrypts. `downgrade()` decrypts back to plaintext. Row count
  is tiny pre-launch → runs in well under a second. Ordering: run `alembic upgrade head`
  then start the new code (one brief window; matches the deploy's "brief recreate").
- **Option 2 — NULL + re-auth (zero migration code).** Set both columns `NULL` before
  deploy; users reconnect Spotify on next login (`upsert_user` writes fresh encrypted
  tokens). Simplest; costs everyone one reconnect. Fine for test accounts.
- **Option 3 — tolerant runtime decrypt (zero-downtime).** Make `process_result_value`
  catch `InvalidToken` and return the raw value during a transition window, then remove
  it after a backfill. More moving parts; **not** needed pre-launch.

**Recommendation: Option 1.** Clean, production-realistic, idempotent, trivial at
current scale. Option 2 is the acceptable zero-effort fallback.

> ⚠️ **Honest caveat:** encryption protects **future** snapshots. Any RDS
> snapshot/backup taken *before* A4 still contains plaintext — delete or age those out
> after rollout, and rotate the Spotify tokens if a pre-A4 backup may have leaked.

## Validation / tests — new `tests/test_token_encryption.py`

- **crypto.py:** encrypt→decrypt round-trip; rotation (decrypt a value after prepending
  a new key); fail-fast `RuntimeError` when `TOKEN_ENCRYPTION_KEYS` unset.
- **EncryptedString:** bind→result round-trip; `None` passthrough; assert the value
  *written to the DB* is **not** the plaintext (ciphertext at rest).
  - ⚠️ **Test harness note:** `conftest.py` uses `mock_db = MagicMock(spec=Session)`,
    which does **not** exercise column types. Test the type against a **real** engine
    (sqlite in-memory) with a **minimal throwaway table** — **not** `Base.metadata`,
    which includes a pgvector `Vector` column that won't create under sqlite.
- **Migration:** apply the backfill to a seeded copy; confirm ciphertext stored and
  `decrypt` returns the original; confirm idempotent re-run.
- **⚠️ Set `TOKEN_ENCRYPTION_KEYS` at module level in `conftest.py` (the existing
  env-injection block ~lines 47-56, next to `SESSION_SECRET`), BEFORE the
  `from app.db.models import ...` at line ~60 — NOT in a fixture (a fixture runs after
  import, too late, and the whole suite fails at collection).** Use a valid generated
  Fernet key as a hardcoded test constant (`Fernet(key)` validates base64/length, so an
  arbitrary string won't work). Then `pip install` the new dep and re-run full `pytest`.

## Risk / rollback

- **Risk: minimal-to-moderate.** Small surface; the main hazard is key management
  (covered above) and the migration ordering (one brief window).
- **Perf:** Fernet on small token strings, a few times per request — negligible.
- **Rollback:** `alembic downgrade` (decrypt back to plaintext) + revert the column type
  to `Text` + drop the new modules; possible as long as the keys are retained.

## Files changed

| File | Change |
|------|--------|
| [backend_requirements.txt](../backend_requirements.txt) | add pinned `cryptography` |
| `app/core/crypto.py` | **new** — key load (fail-fast) + `MultiFernet` `encrypt`/`decrypt` |
| `app/db/types.py` | **new** — `EncryptedString` TypeDecorator |
| [app/db/models.py](../app/db/models.py) | `spotify_access_token`/`spotify_refresh_token`: `Text` → `EncryptedString` |
| `alembic/versions/<rev>_encrypt_spotify_tokens.py` | **new** — idempotent plaintext→ciphertext backfill (+ downgrade) |
| [.env.example](../.env.example) | document `TOKEN_ENCRYPTION_KEYS` |
| `tests/test_token_encryption.py` | **new** — crypto + type + migration tests |

## Out of scope (recorded)
- Encrypting other columns (email/display_name) — tokens are the durable-access risk.
- KMS envelope encryption — heavier; Fernet + SSM key suffices at this scale.
- `schemas/user.py` dead-code removal — flagged, separate cleanup.
- Purging plaintext from pre-A4 backups — operational follow-up noted in the caveat.
