# Phase 1 — App-level production correctness: decisions & findings

Running log of the key decisions, findings, and gotchas from each Phase 1 item in
[deployment-gameplan.md](deployment-gameplan.md). One section per item; fill in as
each lands.

---

## 1.1 — `/health` endpoint ✅

**Shipped**
- New router [backend/app/api/v1/health.py](../backend/app/api/v1/health.py):
  - `GET /health` → `200 {"status":"ok"}` — liveness, no dependencies touched.
  - `GET /health/ready` → `SELECT 1` via `get_db`; `200 {"status":"ready"}`, or
    `503 {"detail":{"status":"unavailable"}}` if the DB round-trip raises.
- Registered in [main.py](../backend/app/main.py) with **no `/api/v1` prefix**.
- Tests: [backend/tests/test_health.py](../backend/tests/test_health.py) (4 tests).

**Decisions**
- **Mounted at root `/health`, not `/api/v1/health`.** The compose `HEALTHCHECK`
  (2.3), the nginx upstream check (4.x), and the deploy health gate (8.3 step 6)
  all reference `/health`. Keeping it prefix-free means those don't have to carry
  the API version path.
- **Split liveness vs. readiness.** `/health` answers "is the process up?" (what
  Docker/compose restart logic and the deploy gate need); `/health/ready` answers
  "can it actually serve?" by hitting the DB. A DB outage should fail readiness
  (503) without necessarily killing the container on liveness.
- **`SELECT 1` reuses the existing `get_db` dependency**, so the probe exercises
  the real connection pool (`pool_pre_ping=True` is already set in
  [database.py](../backend/app/db/database.py)) rather than a throwaway connection.
- **Unauthenticated and not rate-limited**, per the gameplan — these are infra
  probes hit frequently by Docker/nginx/uptime monitors; `slowapi` limits and
  `get_current_user` would defeat their purpose.

**Findings / gotchas**
- The `SecurityHeadersMiddleware` (default-src 'none' CSP, etc.) still stamps the
  health responses. Harmless for JSON probes / `curl`, but worth remembering if a
  browser ever renders them.
- For 2.3, the image needs `curl` (or a small Python probe) available so the
  Dockerfile `HEALTHCHECK` can hit `/health`.

**Verification** — `pytest tests/test_health.py` (4 passed); full backend suite 146 passed.

---

## 1.2 — Alembic-only schema (remove `create_all`)

_TODO_

## 1.3 — Initialize Sentry

_TODO_

## 1.4 — Production uvicorn process model

_TODO_

## 1.5 — Point env config at the real domain

_TODO_

## 1.6 — Register production OAuth callback (Spotify)

_TODO_

## 1.7 — Keep dev TLS material out of the build context

_TODO_

## 1.8 — Replace `print()` with `logging`

_TODO_
