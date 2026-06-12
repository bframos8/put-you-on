# P5b Implementation Plan — Denormalize genre onto `songs` + iterative scan

> Status: **Plan for review — agent-checked + DB-measured before any write.**
> Parent: [p5-hnsw-tuning-fix-plan.md](p5-hnsw-tuning-fix-plan.md) (P5a is done).
> Goal: make the **genre-filtered** kNN branch use the HNSW index instead of
> sequentially scanning all 110k candidate embeddings.
>
> **Revised 2026-06-12** after read-only measurement of the live `songs` layout +
> an agent review of the Postgres/pgvector update mechanics. The original cost
> model ("1.5 GB table → ~550 MB row rewrite") was **wrong** — see §2b. Chosen
> rollout: **drop the HNSW index → backfill → rebuild it** (decision below).

## 1. Why (measured)

The genre branch filters `Album.genre` (a **joined** table), so the planner can't
use the `songs` vector index and seq-scans all 110,833 candidates (~45ms warm,
~1.3s cold, O(N)). pgvector 0.8 iterative scan only helps **same-table** filters,
so the filter must live on `songs`. Verified DB state (read-only, 2026-06-11/12):

- 110,833 candidates; **all** have `album_id` + a non-null `albums.genre` →
  backfill covers 100%, **0** unbackfillable rows.
- `songs.genre` exists (`text`, nullable) but is **NULL for every candidate**.
- Non-candidate user songs have `album_id IS NULL` (Spotify tracks, no `albums`
  row) and get their genre from audio classification — so they are **not** touched
  by an `is_candidate`-scoped backfill.
- Deployed DB is Alembic-tracked, **stamped at head `e5f1a2b3c4d5`**, Postgres
  **16.13**, and has **no existing triggers**. `alembic/env.py` builds the URL from
  `.env-postgres`, so `alembic upgrade head` runs only a new migration against RDS.

### Source of the backfilled value
`songs.genre` is copied from its parent **`albums.genre`** (the album's genre, set
by the external scraper at scrape time). User-path songs keep their
audio-classified genre (set in [process_top_tracks](../app/services/spotify_ingest_service.py#L155));
the backfill never touches them (`album_id IS NULL`, and the trigger guards on
`NEW.genre IS NULL`).

## 2. Approach

Three coordinated pieces; the first two are **additive** (don't change current
query behavior, which still reads `albums.genre` until the code change deploys):

### 2a. Alembic migration (`down_revision = 'e5f1a2b3c4d5'`)
The migration is the **canonical, idempotent** definition so fresh/other
environments reproduce the end state. On the live RDS the heavy backfill is done
out-of-band first (§2b), so the migration's `UPDATE` lands as a **no-op** and it
effectively just installs the trigger.

**Backfill** existing candidates (idempotent — re-runs as a no-op once filled):
```sql
UPDATE songs SET genre = a.genre
FROM albums a
WHERE songs.album_id = a.id
  AND songs.is_candidate = true
  AND songs.genre IS NULL;
```
**Sync trigger** so future scraper-inserted candidates self-populate (the scraper
is external to this repo, so the DB must maintain this itself):
```sql
CREATE OR REPLACE FUNCTION songs_fill_genre_from_album() RETURNS trigger AS $$
BEGIN
  IF NEW.genre IS NULL AND NEW.album_id IS NOT NULL THEN
    SELECT genre INTO NEW.genre FROM albums WHERE id = NEW.album_id;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS songs_fill_genre ON songs;   -- idempotent re-run safety
CREATE TRIGGER songs_fill_genre
BEFORE INSERT OR UPDATE OF album_id, genre ON songs
FOR EACH ROW EXECUTE FUNCTION songs_fill_genre_from_album();
```
- The `NEW.genre IS NULL` guard means it **never overrides** an explicitly-set
  genre (e.g. `process_top_tracks` sets `Song.genre` from audio classification on
  the user path — those rows keep their classified genre).
- **Scraper ordering is known**: the scraper always inserts the **album first**,
  then the album's songs. So at candidate-song INSERT the parent `albums` row (with
  its genre) already exists, and the `BEFORE INSERT` lookup always resolves — no
  album-side trigger needed.
- **Downgrade**: `DROP TRIGGER IF EXISTS` + drop function, then `UPDATE songs SET
  genre = NULL WHERE is_candidate = true` (faithful reverse — candidates were NULL
  before).

### 2b. Apply to RDS — drop-index → backfill → rebuild (CHOSEN)

**Corrected cost model (measured, replaces the old "550 MB rewrite"):** the
`songs` table is 1523 MB but that is **heap 23 MB + indexes 874 MB + TOAST 626 MB**.
The `embedding vector(1280)` column is stored **EXTERNAL (TOAST)**, so an UPDATE
that changes only `genre` **reuses the existing TOAST pointers** — the 626 MB of
embeddings is **not** rewritten. The heap delta is ~110k × ~214 B ≈ **23 MB + WAL**:
trivial. The real cost is **HNSW index churn**: at fillfactor 100 (packed
bulk-load) the genre-only updates are almost all **non-HOT**, so each of ~110k rows
would insert a new entry into the HNSW graph and leave a dead one behind
(~110k serial graph inserts + index bloat until VACUUM). `genre` is unindexed, so
the updates are HOT-*eligible* — the only thing forcing non-HOT is page free space.

**Therefore: drop the HNSW index, backfill with it gone (no graph inserts to do),
then rebuild it clean.** This skips ~110k incremental HNSW inserts entirely and
leaves zero index bloat; the bulk `CREATE INDEX` (using `maintenance_work_mem` /
parallel workers) is faster than incremental inserts. Cost: a maintenance window
where vector queries seq-scan — acceptable pre-launch (single process, no real
users); run it during no traffic.

Runbook (live RDS, in order):
1. `DROP INDEX songs_embedding_hnsw_idx;`
2. **Batch-backfill** the live DB (10k rows/commit) via the throwaway script. With
   the HNSW index gone, updates only touch the three small btrees (and are mostly
   HOT-eligible), so this is fast and lock-light. The backfill is **additive and
   invisible to the running app** — current code filters `albums.genre` and never
   reads candidate `songs.genre`. The script selects only *fillable* rows
   (`a.genre IS NOT NULL`) so it always terminates.
   - ⚠️ The script ([_p5b_backfill.py](_p5b_backfill.py)) loads
     `Path("..")/".env-postgres"`; the env file is at the **repo root**, so run it
     from `backend/` (not `backend/agents/`), or fix the path first.
3. `VACUUM (ANALYZE) songs;` — reclaim dead heap/btree tuples from the backfill and
   refresh planner stats (the genre column's NULL fraction changed).
4. `CREATE INDEX songs_embedding_hnsw_idx ON songs USING hnsw (embedding vector_cosine_ops);`
   then `ANALYZE songs;`.
5. **Gate — `EXPLAIN ANALYZE` the new genre query** (see §3). Only proceed if it
   shows an HNSW **Index Scan** returning the full 50 rows.
6. `cd backend && alembic upgrade head` — deployed DB is stamped at `e5f1`, so only
   the new migration runs. Its backfill `UPDATE … WHERE genre IS NULL` is now a
   **no-op** and it installs the trigger + stamps the revision. (The HNSW index is
   owned by the earlier `d9e1f3a4b205` migration — the new migration does **not**
   recreate it.)

**Timing:** with this approach the backfill is seconds (heap-only, no HNSW
maintenance), the index rebuild is the dominant step (~minutes, bulk-optimized),
and the `alembic upgrade` itself is sub-second (no-op UPDATE + trigger). The exact
rebuild time is best confirmed by the operator during the window.

> _Rejected alternative — in-place batched backfill (index left live):_ keeps the
> index up but pays ~110k serial HNSW inserts (~1–5 min, order-of-magnitude) **plus**
> ~110k dead index entries that need a follow-up `VACUUM (ANALYZE)` to clear. Slower
> and leaves transient bloat; only preferable if dropping the index for a few minutes
> were unacceptable (it isn't, pre-launch).

### 2c. Query change — [query_recommendations](../app/services/spotify_ingest_service.py#L236)
- Genre branch: filter **`Song.genre == query_genre`** instead of `Album.genre`.
  The value still comes from `query_entry.genre` (the seed's genre) — semantically
  identical, since backfill+trigger guarantee `songs.genre == albums.genre` for
  candidates. The `outerjoin(Song.album)` stays (still needed for `Album.artist_id`
  in the artist dedupe).
- Enable iterative scan **only for the genre branch**, reset before the exact
  fallback so the fallback's ordering stays exact (ef_search is already set to
  `pool_size*2` at the top of the method by P5a):
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
- `relaxed_order` (≈95–99% ranking fidelity, fine for recs) keeps pulling from the
  HNSW graph until `pool_size` genre matches pass, bounded by
  `hnsw.max_scan_tuples` (default 20,000). Selectivity check: smallest genres
  (~1,156 candidates ≈ 1%) need ~5,000 tuples scanned for 50 hits — well under the
  cap. Genres with `< pool_size` total candidates return fewer; the existing
  `len(results) < limit` fallback tops up, unchanged.

## 3. Validation — the gate (after step 2b.4, before code/trigger)

> The index must be **rebuilt** before this gate (step 2b.4) — you can't EXPLAIN an
> index scan while the index is dropped.

Run read-only:
```
SELECT set_config('hnsw.ef_search','100',true);
SELECT set_config('hnsw.iterative_scan','relaxed_order',true);
EXPLAIN (ANALYZE, BUFFERS)
  SELECT s.id, a.artist_id FROM songs s LEFT JOIN albums a ON s.album_id=a.id
  WHERE s.is_candidate=true AND s.genre='hip-hop-rap' AND s.id <> <seed>
    AND s.id NOT IN (SELECT song_id FROM user_recommendations WHERE user_id = -1)
  ORDER BY s.embedding <=> '<seed-emb>'::vector LIMIT 50;
```
(The `NOT IN` anti-join is included because the agent review flagged it as the
piece most likely to block the index scan.)

**Pass criteria**: plan shows `Index Scan using songs_embedding_hnsw_idx` (not Seq
Scan), returns **50** rows, single-digit-to-low-ms. **If it fails**, stop and
report — the persisted backfill is harmless (current query still uses
`albums.genre`) and can be reverted with
`UPDATE songs SET genre = NULL WHERE is_candidate = true`; no trigger or code has
been touched yet.

Post-apply: re-run the same EXPLAIN (committed) to confirm; run `pytest`
(the service is mocked in route tests; `test_genre_filtering`'s mock chain absorbs
the new `Song.genre` filter and `set_config` calls — expected green with no test
edits, but confirm).

## 4. Risk / rollback
- Backfill + trigger are **additive**; the live app keeps working on `albums.genre`
  until the new code deploys. No broken intermediate state.
- The **dropped-index window** is the one live-impact moment: vector queries
  seq-scan until the rebuild completes. Run during no traffic; pre-launch this is a
  non-issue. If interrupted, simply re-`CREATE INDEX` to restore the prior state.
- Trigger adds one indexed PK lookup per `songs` insert/update — small cost on the
  scraper's bulk inserts; acceptable for correctness.
- **Known limitation**: if an `albums.genre` is *changed* after its songs exist,
  `songs.genre` won't auto-update (no album-side trigger). Album genre is set at
  scrape time and rarely changes; documented, not handled. (Candidate *inserts* are
  fully covered because the scraper inserts albums before songs.)
- Rollback = `alembic downgrade -1` (drops trigger/function, nulls candidate
  genres). The code change reverts independently.

## 5. Files changed
| File | Change |
| --- | --- |
| `backend/alembic/versions/<rev>_denormalize_song_genre.py` | **New** — idempotent backfill + `DROP TRIGGER IF EXISTS` + sync trigger (+ downgrade). |
| [app/services/spotify_ingest_service.py](../app/services/spotify_ingest_service.py) | Genre branch filters `Song.genre`; scope `hnsw.iterative_scan` per branch. |
| [_p5b_backfill.py](_p5b_backfill.py) | Throwaway live-DB batched backfill (run from `backend/`; delete after P5b lands). |
