# Backend Optimization — DEFERRED

> **Source of truth for work consciously parked** (not abandoned). Split out of
> [.claude-backend-optimization.md](.claude-backend-optimization.md) on 2026-06-23.
> Companions: [backend-optimization-completed.md](backend-optimization-completed.md)
> and [backend-optimization-remaining.md](backend-optimization-remaining.md) (the
> one active item, P5b).
>
> Each entry states **why** it's deferred and the **trigger to revisit** — the
> concrete condition under which it should move into the remaining/active stage.

---

## P1 + P2 — single TF model load + single inference pass

**What:** [spotify_ingest_service.py:29](../app/services/spotify_ingest_service.py#L29)
loads `TensorflowPredictEffnetDiscogs` (output `PartitionedCall:1`, embeddings) and
[audio_genre_classifier.py:16](../app/services/audio_genre_classifier.py#L16) loads
the **same graph again** (output `PartitionedCall:0`, genre). Two full network copies
in memory (P1), and new-song ingest runs the network **twice** over identical audio
(P2). This is the same finding as housekeeping-audit **H1**.

**Why deferred:** A true single-load requires dropping to Essentia's low-level
`TensorflowPredict` with `outputs=["PartitionedCall:0","PartitionedCall:1"]` **and**
reproducing EffNet's exact mel/patch preprocessing (an experiment mismatched on band
count, tensor layout, and last-patch handling). Embeddings are **persisted to
Postgres and drive kNN recs**, so any drift silently corrupts recommendations — and
there is **no ML test/fixture infra** to prove byte-for-byte equivalence. Moderate
benefit on a **background ingest** path doesn't justify that validation burden yet.

**Trigger to revisit:** when ingest moves to a real queue (A2) **and** a committed
numerical-equivalence test exists (synthetic audio, ~0 max-abs-diff for both heads).
Build the test infra first; it is the actual prerequisite.

**Effort:** M (both, as one fused refactor).

---

## P6 — drop `create_all`; rely on Alembic

**What:** [main.py:25](../app/main.py#L25) runs `Base.metadata.create_all` at boot.
It can't create the HNSW index or run migrations, so it diverges from the real schema
and masks migration drift.

**Why deferred (premise was broken):** "just remove `create_all`" is unsafe — **no
migration runs `op.create_table`** for the six base tables; the root
[ad1aecf9f82f](../alembic/versions/ad1aecf9f82f_initial_schema.py) only `add_column`s
onto an already-existing `user_top_songs`. On a fresh DB, `alembic upgrade head` would
fail. So `create_all` is currently load-bearing for bootstrap. Removing it first needs
a **baseline `create_table` migration**, an `alembic upgrade head` deploy step, and an
`alembic stamp` of the already-deployed DB.

**Overlap:** this is the same work as **deployment-gameplan Phase 1.2** — but broader
there (it adds an `alembic revision --autogenerate` drift diff against RDS). Treat
them as **one work item**, and do it as part of the deploy hardening, not as a
standalone quick win. See
[../../claude-mds/deployment-gameplan.md](../../claude-mds/deployment-gameplan.md) §1.2.

**Trigger to revisit:** when starting the production-deploy hardening (it's the
highest-risk correctness item on that path).

**Effort:** M.

---

## Tier 2 — architectural (review before scaling)

Correct as-is on a single process / pre-launch. These are the items to resolve
**before adding a second worker/replica**, in roughly this order.

| # | What | Direction | Revisit when |
|---|------|-----------|--------------|
| **A1** | `oauth_states` / `processing_users` in `app.state`; in-memory `slowapi` limiter | Move to Redis (or small Postgres table); point `slowapi` at shared Redis | The moment you add a 2nd worker/replica — **top item** |
| **A2** | Heavy ingest on FastAPI `BackgroundTasks` (spotdl + TF in the web process) | Offload to Celery/RQ/arq workers; API enqueues, `/status` reads job state | Ingest reliability/observability matters, or before scaling |
| **A3** | `async def` routes doing **blocking** psycopg2 DB work on the event loop | Make DB routes plain `def` (threadpool) **or** adopt async SQLAlchemy + asyncpg | Under real concurrency |
| **A4** | Spotify access/refresh tokens stored **plaintext** ([models.py:24-25](../app/db/models.py#L24-L25)) | Encrypt with an app key (Fernet) or `pgcrypto` | **Pre-launch is cheapest** — do before real users exist |
| **A5** | Shared downloads dir → concurrent ingests can pick up each other's files | Per-job `tempfile.mkdtemp` as `--output`, torn down in `finally` | Falls out naturally once A2 isolates jobs |
| **A6** | Re-ingest churn: `snapshot_is_stale` rebuilds `UserTopSong` once `all_queried` | When snapshot unchanged, reset `used_as_query=False` instead of rebuilding | Minor; opportunistic |
| **A7** | Stateless logout can't revoke a leaked 30-day session token | Add a `session_version` on `User` baked into the token (DB read per request) | If revocation becomes a requirement |

**Pre-launch-cheap callouts:** **A4** (token encryption — introduce the column format
before there's data to migrate) and **A5** (download isolation) are the two Tier-2
items most worth pulling forward if you want hardening before launch; the rest are
genuinely scale-gated.

---

## Not an optimization-list item, but pending backend code (cross-reference)

- **Observability Phase 1** (separate plan,
  [../../claude-mds/observability-plan.md](../../claude-mds/observability-plan.md)):
  `/metrics` + RED + custom metrics (`embed_duration_seconds`, Spotify latency/errors,
  `oauth_logins_total`) in `main.py` / `spotify_ingest_service.py` / `auth.py`. All
  Phase-0/1 boxes unchecked. Net-new code, not part of this list — noted so it isn't
  conflated with the items above.
