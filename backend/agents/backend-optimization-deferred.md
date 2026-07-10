# Backend Optimization — DEFERRED

> **Source of truth for work consciously parked** (not abandoned). Companions:
> [backend-optimization-completed.md](backend-optimization-completed.md) and
> [backend-optimization-remaining.md](backend-optimization-remaining.md) (the active
> queue: **P5b** only).
>
> **Updated 2026-07-09:** A3/A4/A5/A6 shipped → completed; A7 deferred (auth is a later
> workstream); P6 deferred (folds into deploy hardening / Phase 1.2). What stays parked
> here: **A1, A2, A7, P6, P1/P2, and Observability Phase 1.**
>
> Each entry states **why** it's deferred and the **trigger to revisit**.

---

## A1 — externalize in-memory state before scaling

**What:** `oauth_states` and `processing_users` live in `app.state`
([main.py:25-26](../app/main.py#L25-L26)), and `slowapi` uses default in-memory storage
([limiter.py:20](../app/core/limiter.py#L20)). With >1 worker or replica: OAuth
callbacks land on a worker that never saw the `state` (spurious `state_mismatch`), the
per-user "processing" guard and daily-limit serialization stop working across workers,
and rate-limit counters fragment.

**Why deferred (user decision):** correct as-is on a single process, and the fix **adds
infrastructure** (Redis or a shared table) to the stack — not wanted pre-launch.

**Direction:** move `oauth_states`/`processing_users` to Redis (or a small Postgres
table); point `slowapi` at a shared Redis backend.

**Trigger to revisit:** the moment you add a second worker/replica — the top item then.

---

## A2 — move heavy ingest off `BackgroundTasks` to a real queue

**What:** `_run_process_top_tracks` ([songs.py:17](../app/api/v1/songs.py#L17)) runs
`spotdl` downloads + TensorFlow inference inside the web process via `BackgroundTasks`.
CPU-bound TF work and subprocess I/O compete with serving; failures aren't retried or
observable; work dies on deploy/restart.

**Why deferred (user decision):** like A1, the fix **adds a worker/queue** to the stack.
Acceptable on a single process pre-launch.

**Direction:** offload to Celery/RQ/arq workers (separate process). The API enqueues a
job; the existing `/status` poll reads job state. Also unblocks A1's `processing_users`
(job state becomes the source of truth) and A5's isolation at the job level.

**Trigger to revisit:** when ingest reliability/observability matters, or before scaling.

---

## A7 — server-side session revocation

**What:** `itsdangerous` session tokens are valid for 30 days regardless of logout
([auth.py:82-87](../app/api/v1/auth.py#L82)); logout only clears the client cookie, so a
leaked token can't be revoked server-side.

**Why deferred (user decision, 2026-07-09):** auth is a later workstream. The fix also
carries a real tradeoff — it gives up the stateless-session model for one DB read per
request.

**Direction:** add a `session_version` on `User`, bake it into the token, and check it
per request; bumping it invalidates all existing sessions. **Effort:** S–M.

**Trigger to revisit:** when tackling auth hardening (and if revocation is judged worth
the per-request DB read).

---

## P1 + P2 — single TF model load + single inference pass

**What:** [spotify_ingest_service.py:29](../app/services/spotify_ingest_service.py#L29)
loads `TensorflowPredictEffnetDiscogs` (output `PartitionedCall:1`, embeddings) and
[audio_genre_classifier.py:16](../app/services/audio_genre_classifier.py#L16) loads the
**same graph again** (output `PartitionedCall:0`, genre). Two full network copies in
memory (P1), and new-song ingest runs the network **twice** over identical audio (P2).
Same finding as housekeeping-audit **H1**.

**Why deferred:** a true single-load needs Essentia's low-level `TensorflowPredict` with
`outputs=["PartitionedCall:0","PartitionedCall:1"]` **and** reproducing EffNet's exact
mel/patch preprocessing. Embeddings are **persisted and drive kNN recs**, so any drift
silently corrupts recommendations — and there's **no ML test/fixture infra** to prove
byte-for-byte equivalence. Moderate benefit on a background path doesn't justify that yet.

**Trigger to revisit:** when ingest moves to a real queue (A2) **and** a committed
numerical-equivalence test exists (synthetic audio, ~0 max-abs-diff for both heads).
Build the test infra first — it's the actual prerequisite.

---

## P6 — drop `create_all`; make Alembic the single schema authority

**What:** [main.py:25](../app/main.py#L25) runs `Base.metadata.create_all` at boot, but no
migration runs `op.create_table` for the six base tables (the root
[ad1aecf9f82f](../alembic/versions/ad1aecf9f82f_initial_schema.py) only `add_column`s onto
an already-existing table). So `create_all` is load-bearing for fresh DBs and silently
diverges prod from the models (can't add indexes, alter columns, or build the HNSW index).

**Why deferred (user decision, 2026-07-09):** fold it into the deploy-hardening
workstream rather than standalone — it's the same work as **deployment-gameplan Phase
1.2** (which wraps it with an `alembic revision --autogenerate` drift diff), and it's the
highest-risk item so far (touches migration history on the live RDS).

**Direction:** author a baseline `op.create_table` migration (the new root the existing
chain builds onto), add an explicit `alembic upgrade head` deploy step, `alembic stamp`
the deployed RDS so its history stays consistent, **then** remove `create_all`.
**Effort:** M.

**Trigger to revisit:** when starting production deploy hardening (Phase 1.2).

---

## Observability Phase 1 — `/metrics` + RED + custom metrics

**What:** add `prometheus-fastapi-instrumentator` and expose `/metrics` (internal-only)
with RED metrics, plus custom metrics — `embed_duration_seconds`,
`spotify_api_errors_total`, `oauth_logins_total` — in
[main.py](../app/main.py), [spotify_ingest_service.py](../app/services/spotify_ingest_service.py),
and [auth.py](../app/api/v1/auth.py). Full plan:
[../../claude-mds/observability-plan.md](../../claude-mds/observability-plan.md).

**Why deferred (user decision):** net-new instrumentation tied to the broader
Grafana-Cloud/deploy rollout; not part of the core optimization pass.

**Trigger to revisit:** when standing up the production deploy + Grafana Cloud (it ships
inside the backend image, observability-plan Phase 1).
