# P5 Fix Plan — pgvector HNSW recall/speed tuning (LOW/MEDIUM)

> Status: **Plan only — nothing implemented (no code or DB changes).**
> Source finding: [.claude-backend-optimization.md → P5](.claude-backend-optimization.md#L194)
> Grounded in **read-only measurements against the live RDS DB** (2026-06-11),
> not estimates. pgvector **0.8.1**, Postgres on RDS.

## 1. What the live data actually shows

Measured read-only via `EXPLAIN (ANALYZE, BUFFERS)` on the real
[query_recommendations](../app/services/spotify_ingest_service.py#L223-L286) kNN.

- **Corpus**: `songs` = 110,861 rows; **110,833 candidates** (`is_candidate=true`,
  all with a 1280-dim embedding); 28 non-candidates (the user "query seed" songs).
  Genuine HNSW scale — tuning is meaningful here.
- **Index**: `songs_embedding_hnsw_idx USING hnsw (embedding vector_cosine_ops)` at
  **default** params. `hnsw.ef_search=40` (default), `hnsw.iterative_scan=off`
  (default). **No** btree on `albums.genre` or `songs.is_candidate`.
- **`songs.genre` is NULL for all 110,833 candidates** — candidate genre lives only
  on `albums.genre`; the query filters `Album.genre == query_genre` via an outerjoin.
- Genre distribution is skewed: country 16.4k, latin 14.8k, blues 14.0k, reggae
  13.1k, … hip-hop-rap 2.6k, pop 1.2k (22 genres total).

The query over-fetches `pool_size = limit*5 = 50`, then `_dedupe_by_artist` trims to
`limit = 10` distinct artists.

| Path | Plan today | Rows returned (LIMIT 50) | Latency warm / cold |
| --- | --- | --- | --- |
| **Fallback** (no genre) | HNSW Index Scan ✅ | **39** ❌ (`ef_search=40`) | ~12ms / ~0.9s |
| **Genre** (`albums.genre`) | **Parallel Seq Scan** + Hash Join + top-N Sort ❌ | 50 ✅ | ~45ms / ~1.3s, **O(N)** |

### Two distinct, real problems
1. **Fallback under-returns.** `ef_search=40` < `pool_size=50`: HNSW post-filtering
   caps the candidate pool, so only **39** rows come back. That shrinks the
   artist-dedupe pool → can produce **fewer than 10 recs** or lower-quality ones.
   This is a **recommendation-quality bug**, not just latency. Measured:
   `ef_search=100` → returns the full **50**.
2. **Genre branch ignores the HNSW index.** The genre filter is on the *joined*
   `albums` table, so the planner abandons the vector index and **sequentially
   scans all 110k embeddings** + sorts by distance. Correct results, but O(N) and
   growing. Naively raising `ef_search` does **not** help: at `ef_search=200` the
   planner flipped to the index and post-filtering left only **9 rows** (collapse).

### Verified against pgvector 0.8 docs (agent + web)
- HNSW post-filtering returns at most ~`ef_search` rows before LIMIT/filters, so
  `ef_search ≥ pool_size` (+ headroom) is **necessary** to avoid under-returning.
  `ef_search` is capped at 1000; default 40. ✔
- **Iterative index scan** (`hnsw.iterative_scan = relaxed_order | strict_order`)
  keeps pulling from the graph until enough rows pass the filter — **but only for
  filters on the SAME table as the indexed vector.** A join filter on
  `albums.genre` **cannot** be pushed into the scan. → genre must be denormalized
  onto `songs` to benefit. ✔
- `relaxed_order` trades ~1–5% ranking exactness for speed (fine for recs);
  `strict_order` preserves exact ordering. Iterative scan honors
  `hnsw.max_scan_tuples` (default 20,000). ✔
- A btree on `albums.genre` / `songs.is_candidate` would **not** materially help —
  the dominant cost is the vector sort over the filtered set, not the album join
  (~10ms of ~45ms). ✔

## 2. Proposed fix — two tiers

### P5a — fallback recall fix (low-risk, high-value)
Scope `ef_search` per request, sized above the over-fetch pool, inside
`query_recommendations` before the pool `.all()` calls:

```python
from sqlalchemy import text
# ... inside query_recommendations, before building/running base_query:
db.execute(text("SET LOCAL hnsw.ef_search = 100"))
```
- `SET LOCAL` scopes to the open transaction (the Session in
  [songs.py:96](../app/api/v1/songs.py#L96) lives for the whole call;
  `autocommit=False`), so both the genre and fallback pool queries see it.
- **100** = 2× `pool_size`(50) headroom; covers the ~2 rows filtered by
  `is_candidate`/`id`. **Cap at 100** — 200 flips the genre branch to the bad
  index plan (measured 9-row collapse).
- **Measured effect**: fallback 39 → **50** rows; genre branch unchanged (correct
  seq scan). No schema/data change.
- If `pool_size` ever changes, derive the value (e.g. `pool_size * 2`) rather than
  hardcoding.

### P5b — genre-branch index acceleration (bigger; recommend SCHEDULING)
Make the genre-filtered ANN use the index instead of seq-scanning 110k rows:
1. **Denormalize** `albums.genre` → new/existing `songs.genre`:
   - Alembic migration (add nothing if column exists; it does — `songs.genre`).
   - **Backfill** ~110k candidate rows: `UPDATE songs s SET genre = a.genre FROM
     albums a WHERE s.album_id = a.id AND s.is_candidate = true` (batch it).
   - **Keep in sync.** Candidate ingestion is an **external scraper (not in this
     repo)**, so prefer a DB trigger on `albums.genre` / song insert, or have the
     scraper write `songs.genre` directly. (User-path ingest in
     [process_top_tracks](../app/services/spotify_ingest_service.py#L106) already
     sets `Song.genre` for new songs.)
2. **Query change**: genre branch filters `Song.genre == query_genre` (same table)
   instead of `Album.genre`.
3. **Enable iterative scan** for that branch: `SET LOCAL hnsw.iterative_scan =
   'relaxed_order'` (+ keep `ef_search=100`).
4. Optional: revisit index `m` / `ef_construction` once corpus size stabilizes.

- **Expected**: genre branch ~45ms→single-digit ms, index-accelerated, scales.
- **Caveats**: `relaxed_order` approximates ordering slightly; very rare genres may
  still under-return within `max_scan_tuples`; the external-scraper sync is the
  main maintenance cost; a fresh-DB bootstrap still depends on `create_all`
  (orthogonal — see [P6](.claude-backend-optimization.md#L205)).

## 3. Validation (read-only, repeatable)
Re-run the `EXPLAIN (ANALYZE, BUFFERS)` harness used for this plan:
- **P5a**: assert fallback returns 50 (was 39) at `ef_search=100`; assert genre
  branch still returns 50 and stays a seq scan (no 9-row collapse).
- **P5b**: assert the genre branch shows `Index Scan using songs_embedding_hnsw_idx`
  (not Seq Scan) with `iterative_scan=relaxed_order`, returns 50, single-digit ms.
- No unit-test coverage is feasible (queries are Postgres/pgvector-specific and the
  whole service is mocked in the suite) — validate via EXPLAIN on the real DB.

## 4. Files that would change

| File | P5a | P5b |
| --- | --- | --- |
| [app/services/spotify_ingest_service.py](../app/services/spotify_ingest_service.py) | `SET LOCAL hnsw.ef_search` | filter `Song.genre`; `SET LOCAL hnsw.iterative_scan` |
| `backend/alembic/versions/*` | — | backfill migration (+ optional trigger) |
| ingest/scraper sync | — | populate `songs.genre` on candidate insert |

## 5. Recommendation
**Ship P5a, schedule P5b.** P5a is a one-line, measured quality fix (restores the
full 10-rec dedupe pool). P5b is a worthwhile scaling fix but reaches outside this
repo (external scraper) and involves a schema/data migration — do it deliberately,
not as a quick win. **Nothing in this plan has been implemented.**
