# Backend Optimization — REMAINING (active plan)

> **Source of truth for what's left.** Split out of
> [.claude-backend-optimization.md](.claude-backend-optimization.md) on 2026-06-23.
> Companions: [backend-optimization-completed.md](backend-optimization-completed.md)
> and [backend-optimization-deferred.md](backend-optimization-deferred.md).
>
> The only active item is **finishing P5b**. Everything else is either done
> (completed file) or consciously parked (deferred file). This file supersedes the
> status/approach sections of
> [p5b-genre-denormalization-plan.md](p5b-genre-denormalization-plan.md); that doc is
> retained for its measurement history (the failed index-build attempts in its §6).

---

## Confirmed live state (`pyo_db` on RDS, verified 2026-06-23)

| Check | Result | Meaning |
|-------|--------|---------|
| `SELECT version_num FROM alembic_version` | `a7b8c9d0e1f2` (head) | All migrations applied |
| triggers on `songs` | `songs_fill_genre` present | ✅ sync trigger installed (P5b done) |
| indexes on `songs` | 3 btrees only, **no HNSW** | ❌ `songs_embedding_hnsw_idx` dropped — both kNN branches **seq-scan** |
| genre backfill | 110,833 candidates filled | ✅ done |

So P5b's data + schema half is finished. **Two things remain: rebuild the vector
index, then land the query change.** The app is currently *correct but slow* (seq
scans) — fine pre-launch with no users.

---

## Decision: Path A — scale up, rebuild full-vector, scale back

The earlier blocker was building the HNSW index **from a laptop against the ~1 GB RDS
instance**: full-vector spilled the in-progress graph and collapsed to ~0.18
tuples/sec; halfvec fit but a laptop network blip severed the ~1 hr connection (full
history in [p5b-genre-denormalization-plan.md](p5b-genre-denormalization-plan.md) §6).

**Path A fixes the root cause — instance size — instead of working around it:**

1. Temporarily **scale the RDS instance up** (more RAM + IO).
2. `CREATE INDEX` the **full-precision** HNSW index — the graph now fits in RAM, so no
   spill; the build completes in minutes, not days.
3. Validate with the EXPLAIN gate.
4. **Scale the instance back down.** Serving an HNSW index does **not** need the whole
   graph in RAM (queries traverse pages on demand), so a full-vector index queries
   fine on the small instance afterward — only the *build* was memory-hungry.

**Why Path A over halfvec (the old direction):** full-vector keeps the index
expression `embedding vector_cosine_ops`, which is **exactly what the existing
migration already defines** ([d9e1f3a4b205:20](../alembic/versions/d9e1f3a4b205_add_hnsw_index_songs_embedding.py#L20)).
That means:
- **No migration-parity change** — fresh DBs and live stay identical.
- **No `::halfvec` cast** in the query — the change in §2 is just the genre filter +
  iterative scan.
- **Exact recall** (no fp16 precision loss).

Cost: a brief resize reboot (acceptable pre-launch, no users) and remembering to scale
back down.

---

## Remaining steps

### Step 1 — Rebuild the HNSW index (operator-run, Path A)

> This is a long-running `CREATE INDEX` against your RDS — an **ops step you run**, not
> something driven from this repo's tooling. Run it from a **stable connection**: ideal
> is an in-VPC host (e.g. the prod EC2 once it exists, per the deployment plan); from a
> laptop, use TCP keepalives + `nohup`/`screen` and rely on the scaled-up instance
> making the build short.

1. **Scale up RDS** (console or CLI), apply immediately. A class with ≥8 GB RAM and
   better baseline IO comfortably holds the ~568 MB full-vector graph plus the 626 MB
   TOAST reads. Wait for `available`.
2. **Build** (serial is safe; the graph fits so no spill):
   ```sql
   SET maintenance_work_mem = '2GB';
   SET max_parallel_maintenance_workers = 0;   -- avoid the /dev/shm DSM DiskFull seen before
   CREATE INDEX IF NOT EXISTS songs_embedding_hnsw_idx
     ON songs USING hnsw (embedding vector_cosine_ops);
   ANALYZE songs;
   ```
   (Index name + opclass deliberately match [d9e1](../alembic/versions/d9e1f3a4b205_add_hnsw_index_songs_embedding.py)
   so the schema stays consistent with the migration that owns it.)
3. **Gate — EXPLAIN** (see "Validation" below). Only proceed if the genre branch shows
   an HNSW **Index Scan** returning the full 50 rows.
4. **Scale RDS back down** to the normal instance class.

> If parallel build is desired for speed on the scaled instance, it may now work
> (bigger `/dev/shm`); test with a couple of workers, but serial is the safe default.

### Step 2 — Land the query change (in-repo; I implement on request)

[query_recommendations](../app/services/spotify_ingest_service.py#L242) — the genre
branch currently filters the **joined** `Album.genre`
([:299](../app/services/spotify_ingest_service.py#L299)), which the planner can't
serve from the `songs` vector index. Switch it to the denormalized `Song.genre` and
enable iterative scan **only** for that branch (reset before the exact fallback so the
fallback's ordering stays exact). `ef_search = 2*pool_size` is already set at the top
of the method by P5a.

```python
if query_genre:
    db.execute(text("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)"))
    pool = base_query.filter(Song.genre == query_genre).limit(pool_size).all()
    results = self._dedupe_by_artist(pool, limit)

if len(results) < limit:
    db.execute(text("SELECT set_config('hnsw.iterative_scan', 'off', true)"))
    pool = base_query.limit(pool_size).all()
    results = self._dedupe_by_artist(pool, limit)
```

- Keep the `outerjoin(Song.album)` — still needed for `Album.artist_id` in the artist
  dedupe.
- The seed value still comes from `query_entry.genre`; backfill + trigger guarantee
  `songs.genre == albums.genre` for candidates, so this is semantically identical.
- `relaxed_order` (~95–99% ranking fidelity, fine for recs) keeps pulling from the
  graph until `pool_size` genre matches pass, bounded by `hnsw.max_scan_tuples`
  (default 20,000); the smallest genres (~1% ≈ 1,156 candidates) need ~5,000 tuples
  for 50 hits — well under the cap.
- **No `::halfvec` cast** (Path A is full-vector).

### Step 3 — Cleanup

- `git rm` the throwaway live-DB scripts once the index is rebuilt and the query change
  is in: [_p5b_backfill.py](_p5b_backfill.py), [_p5b_runbook.py](_p5b_runbook.py),
  [_p5b_halfvec_rebuild.py](_p5b_halfvec_rebuild.py) (and their `.log` siblings if
  tracked).
- Obsolete plan file to retire: [h1-stale-models-file-cleanup-plan.md](h1-stale-models-file-cleanup-plan.md)
  (H1 already shipped — see the completed file).

### Step 4 — Migration parity

**None required.** Path A rebuilds the same `vector_cosine_ops` index the
[d9e1](../alembic/versions/d9e1f3a4b205_add_hnsw_index_songs_embedding.py) migration
already defines, so fresh DBs reproduce the live index with no edits. (This is the
parity headache halfvec would have added — Path A avoids it.)

---

## Validation — the EXPLAIN gate (after Step 1, before Step 2 deploys)

The index must exist before this runs. Read-only:

```sql
SELECT set_config('hnsw.ef_search','100',true);
SELECT set_config('hnsw.iterative_scan','relaxed_order',true);
EXPLAIN (ANALYZE, BUFFERS)
  SELECT s.id, a.artist_id FROM songs s LEFT JOIN albums a ON s.album_id = a.id
  WHERE s.is_candidate = true AND s.genre = 'hip-hop-rap' AND s.id <> <seed>
    AND s.id NOT IN (SELECT song_id FROM user_recommendations WHERE user_id = -1)
  ORDER BY s.embedding <=> '<seed-emb>'::vector LIMIT 50;
```

**Pass criteria:** plan shows `Index Scan using songs_embedding_hnsw_idx` (not Seq
Scan), returns **50** rows, single-digit-to-low-ms. **If it fails:** stop and report —
nothing is broken (the live query still reads `Album.genre` until Step 2 deploys), and
the only thing to undo is the index itself.

**Post-deploy:** re-run the same EXPLAIN (commit the output), run `pytest`
(`test_genre_filtering`'s mock chain absorbs the new `Song.genre` filter + `set_config`
calls — expected green, confirm).

---

## Risk / rollback

- **Resize window:** brief RDS reboot on scale up/down — pre-launch, no users,
  acceptable. Don't forget to scale **back down**.
- **Dropped-index window:** already in effect (queries seq-scan today); the rebuild
  *ends* it. If the build is interrupted, just re-run `CREATE INDEX`.
- **Query change** is independent and revertible (one commit); it only takes effect
  once deployed, so it can't half-break the live app.
- **Known limitation (documented, not handled):** if an `albums.genre` is *changed*
  after its songs exist, `songs.genre` won't auto-update (no album-side trigger).
  Album genre is set once at scrape time and rarely changes.

---

## Files involved

| File | Change |
|------|--------|
| RDS (operator) | Scale up → `CREATE INDEX` full-vector → EXPLAIN gate → scale down |
| [app/services/spotify_ingest_service.py](../app/services/spotify_ingest_service.py) | Genre branch filters `Song.genre`; scope `hnsw.iterative_scan` per branch |
| [_p5b_*.py](.) | `git rm` after P5b lands |
| [d9e1f3a4b205…py](../alembic/versions/d9e1f3a4b205_add_hnsw_index_songs_embedding.py) | **No change** (full-vector matches) |

---

## After P5b

P5b closes the Tier-1 list. Next candidates come from
[backend-optimization-deferred.md](backend-optimization-deferred.md): **P6 / deploy
Phase 1.2** (Alembic-only schema) is the highest-value next step toward production;
**A4** (token encryption) is the cheapest pre-launch security hardening.
