# Backend Optimization — REMAINING (ordered queue)

> **Source of truth for what's left, in priority order.** Companions:
> [backend-optimization-completed.md](backend-optimization-completed.md) and
> [backend-optimization-deferred.md](backend-optimization-deferred.md) (A1, A2, P1/P2,
> Observability Phase 1).
>
> **Order (set 2026-06-26): A6 → A7 → P6 → P5b.**
> Each item gets its own per-item plan markdown + an agent verification before any code
> (the established workflow). A6/A7/P6 below are scoped summaries; **P5b already has a
> full plan** (Path A) because its work was already in flight.

---

## 1. A6 — stop unnecessary re-ingest churn  *(next)*

**What:** [snapshot_is_stale](../app/services/spotify_ingest_service.py#L205-L216)
returns stale once `all_queried`, which triggers a fresh Spotify top-tracks fetch and a
full `UserTopSong` rebuild (DELETE + re-insert) just to refill query candidates. It
rarely re-downloads/re-embeds (existing `Song`s are reused by `spotify_track_id` and
their genre copied), so the real waste is an **unnecessary Spotify call + row churn**
every cycle. Severity: minor.

**Direction:** when the Spotify snapshot is unchanged, reset `used_as_query=False` to
**cycle the existing candidates** instead of rebuilding; only re-fetch when the snapshot
actually changed. **Effort:** S.

**Status:** queued — write `a6-*-plan.md`, agent-verify, then implement.

---

## 2. A7 — server-side session revocation

**What:** `itsdangerous` session tokens are valid for 30 days regardless of logout
([auth.py:82-87](../app/api/v1/auth.py#L82)); logout only clears the client cookie, so a
leaked token can't be revoked.

**Direction:** add a `session_version` (or similar) on `User`, bake it into the token,
and check it per request — bumping it invalidates all existing sessions. **Tradeoff:**
gives up pure statelessness for one DB read per request (decide if revocation is worth
that). **Effort:** S–M.

**Status:** queued — plan + agent-verify first; confirm the statelessness tradeoff is
wanted before implementing.

---

## 3. P6 — drop `create_all`; make Alembic the single schema authority

**What:** [main.py:25](../app/main.py#L25) runs `Base.metadata.create_all` at boot, but
**no migration runs `op.create_table`** for the six base tables — the root
[ad1aecf9f82f](../alembic/versions/ad1aecf9f82f_initial_schema.py) only `add_column`s
onto an already-existing table. So `create_all` is load-bearing for fresh DBs, and it
silently diverges prod from the models (can't add indexes, alter columns, build the HNSW
index).

**Direction:** author a baseline `op.create_table` migration (the new root the existing
chain builds onto), add an explicit `alembic upgrade head` deploy step, `alembic stamp`
the already-deployed RDS so its history stays consistent, **then** remove `create_all`.
**Overlaps deployment-gameplan Phase 1.2**, which adds an `alembic revision
--autogenerate` drift diff — treat them as one work item. **Effort:** M. Higher risk
(touches migration history on a live DB) — do it deliberately. **Status:** queued.

---

## 4. P5b — finish the genre-filtered kNN index  *(last — ops-gated)*

> P5b is last because its blocker is an **ops step** (an RDS scale-up + ~hour index
> build), not code. The remaining-detail/runbook below is authoritative; the older
> [p5b-genre-denormalization-plan.md](p5b-genre-denormalization-plan.md) is kept only for
> its measurement history.

### Confirmed live state (`pyo_db` on RDS, verified 2026-06-23)
| Check | Result | Meaning |
|-------|--------|---------|
| `alembic_version` | `a7b8c9d0e1f2`… (now `b8c9d0e1f2a3` after A4) | migrations applied |
| triggers on `songs` | `songs_fill_genre` present | ✅ sync trigger installed |
| indexes on `songs` | btrees only, **no HNSW** | ❌ `songs_embedding_hnsw_idx` dropped — both kNN branches seq-scan |
| genre backfill | 110,833 candidates filled | ✅ done |

So P5b's data + schema half is finished. **Two things remain: rebuild the vector index,
then land the query change.** The app is *correct but slow* (seq scans) — fine pre-launch.

### Decision: Path A — scale up, rebuild full-vector, scale back
The earlier blocker was building the HNSW index from a laptop against the ~1 GB RDS
(full-vector spilled; halfvec fit but a laptop network blip killed the ~1 hr build).
Path A fixes the root cause — instance size:
1. Temporarily **scale RDS up** (more RAM/IO).
2. `CREATE INDEX … USING hnsw (embedding vector_cosine_ops)` — the graph now fits in RAM
   (no spill), build completes in minutes.
3. Validate with the EXPLAIN gate.
4. **Scale RDS back down** — serving an HNSW index doesn't need the whole graph in RAM,
   only the *build* does.

**Why Path A over halfvec:** full-vector matches the existing index definition
([d9e1:20](../alembic/versions/d9e1f3a4b205_add_hnsw_index_songs_embedding.py#L20),
`vector_cosine_ops`) — so **no migration-parity change, no `::halfvec` cast in the query,
exact recall.**

### Remaining steps
1. **Rebuild the index (operator-run, Path A)** — scale up; `SET maintenance_work_mem`;
   `SET max_parallel_maintenance_workers = 0` (avoid the DSM DiskFull seen before);
   `CREATE INDEX IF NOT EXISTS songs_embedding_hnsw_idx ON songs USING hnsw (embedding
   vector_cosine_ops);` `ANALYZE songs;`. Run from a stable connection; scale back down.
2. **Query change (in-repo)** — in
   [query_recommendations](../app/services/spotify_ingest_service.py#L242), filter
   `Song.genre == query_genre` (instead of `Album.genre` at
   [:299](../app/services/spotify_ingest_service.py#L299)) and scope
   `hnsw.iterative_scan='relaxed_order'` to the genre branch (reset to `off` before the
   exact fallback). `ef_search=2*pool_size` is already set by P5a. **No `::halfvec`.**
3. **Cleanup** — `git rm` the throwaway `_p5b_*.py` scripts.
4. **Migration parity** — none (full-vector matches `d9e1`).

### EXPLAIN gate (after step 1, before step 2 deploys)
With `ef_search=100` + `iterative_scan='relaxed_order'`, the genre query must show
`Index Scan using songs_embedding_hnsw_idx` (not Seq Scan), return the full 50 rows, in
low ms. If it fails: stop and report — nothing is broken (live query still reads
`Album.genre` until step 2 deploys).

**Effort:** rebuild = ops (~minutes once scaled up); query change = S (in-repo).

---

## After the queue
P5b closes the Tier-1 list and the chosen Tier-2 set. What then remains is parked in
[backend-optimization-deferred.md](backend-optimization-deferred.md): A1/A2 (scaling
infra), P1/P2 (fused TF pass — needs test infra), and Observability Phase 1.
