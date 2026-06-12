"""P5b live-RDS runbook: drop HNSW index -> backfill songs.genre -> VACUUM ->
rebuild index -> validate. Throwaway; delete after P5b lands.

Why this shape (measured): songs heap is only ~23 MB; the 1280-dim embeddings are
EXTERNAL/TOAST (626 MB) and are NOT rewritten by a genre-only UPDATE. The real cost
of an in-place backfill is HNSW index churn (~110k non-HOT graph inserts + bloat).
Dropping the index first makes the backfill cheap (heap + small btrees only), then
we rebuild the index clean. Pre-launch, single process, no users -> the
no-index window is acceptable.

Order:
  0. pre-flight read-only snapshot
  1. DROP INDEX songs_embedding_hnsw_idx
  2. batched backfill (10k/commit) of fillable candidates
  3. VACUUM (ANALYZE) songs
  4. CREATE INDEX songs_embedding_hnsw_idx (hnsw, cosine)
  5. ANALYZE songs
  6. validation EXPLAIN (must show Index Scan on songs_embedding_hnsw_idx, 50 rows)

The backfill + index are additive/recoverable: the live app still filters
albums.genre until the code change deploys, and a missing index only degrades recs
to a (correct) seq scan -- re-run step 4 to restore.
"""
import os
import time
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env-postgres")

INDEX = "songs_embedding_hnsw_idx"
BATCH = 10000


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def connect():
    c = psycopg2.connect(
        dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"], connect_timeout=20,
    )
    c.autocommit = True  # DDL / VACUUM / per-batch commits
    return c


def main():
    conn = connect()
    cur = conn.cursor()
    t_start = time.time()

    # 0. pre-flight ---------------------------------------------------------
    cur.execute("SELECT count(*) FILTER (WHERE is_candidate), "
                "count(*) FILTER (WHERE is_candidate AND genre IS NULL) FROM songs")
    cand, cand_null = cur.fetchone()
    cur.execute("SELECT 1 FROM pg_indexes WHERE indexname=%s", (INDEX,))
    has_index = cur.fetchone() is not None
    log(f"pre-flight: candidates={cand} genre_null={cand_null} index_present={has_index}")

    # 1. drop index ---------------------------------------------------------
    log(f"DROP INDEX IF EXISTS {INDEX} ...")
    t = time.time()
    cur.execute(f"DROP INDEX IF EXISTS {INDEX}")
    log(f"  dropped ({time.time()-t:.1f}s)")

    # 2. batched backfill ---------------------------------------------------
    log("backfilling songs.genre from albums.genre (fillable candidates) ...")
    total = 0
    t_bf = time.time()
    while True:
        t = time.time()
        cur.execute(
            """
            WITH batch AS (
                SELECT s.id, a.genre AS g
                FROM songs s JOIN albums a ON s.album_id = a.id
                WHERE s.is_candidate = true AND s.genre IS NULL
                  AND a.genre IS NOT NULL
                LIMIT %s
            )
            UPDATE songs SET genre = batch.g FROM batch WHERE songs.id = batch.id
            """,
            (BATCH,),
        )
        n = cur.rowcount
        total += n
        log(f"  batch={n:6d} total={total:7d} ({time.time()-t:.1f}s)")
        if n == 0:
            break
    log(f"  backfill done: {total} rows in {time.time()-t_bf:.1f}s")

    # 3. VACUUM (ANALYZE) ---------------------------------------------------
    log("VACUUM (ANALYZE) songs ...")
    t = time.time()
    cur.execute("VACUUM (ANALYZE) songs")
    log(f"  vacuum done ({time.time()-t:.1f}s)")

    # 4. rebuild index ------------------------------------------------------
    # Serial build (workers=0) avoids a parallel DSM segment in RDS's small
    # /dev/shm — a 1GB parallel segment failed with DiskFull. maintenance_work_mem
    # here is backend-local (not shared memory), so a modest bump is safe.
    for stmt in ("SET maintenance_work_mem = '512MB'",
                 "SET max_parallel_maintenance_workers = 0"):
        try:
            cur.execute(stmt)
            log(f"  {stmt}")
        except Exception as e:  # RDS may cap these; harmless if it does
            log(f"  (skipped '{stmt}': {type(e).__name__})")
    log(f"CREATE INDEX {INDEX} (hnsw, vector_cosine_ops) ... [the long step]")
    t = time.time()
    cur.execute(
        f"CREATE INDEX {INDEX} ON songs USING hnsw (embedding vector_cosine_ops)"
    )
    log(f"  index built ({time.time()-t:.1f}s)")

    # 5. analyze ------------------------------------------------------------
    cur.execute("ANALYZE songs")
    log("  ANALYZE songs done")

    # 6. validation EXPLAIN -------------------------------------------------
    cur.execute("SELECT id, genre FROM songs "
                "WHERE is_candidate AND genre IS NOT NULL ORDER BY id LIMIT 1")
    seed_id, seed_genre = cur.fetchone()
    cur.execute("SELECT embedding::text FROM songs WHERE id=%s", (seed_id,))
    seed_emb = cur.fetchone()[0]
    cur.execute("SELECT set_config('hnsw.ef_search','100',false)")
    cur.execute("SELECT set_config('hnsw.iterative_scan','relaxed_order',false)")
    log(f"validation EXPLAIN: seed_id={seed_id} genre={seed_genre!r}")
    cur.execute(
        """
        EXPLAIN (ANALYZE, BUFFERS)
        SELECT s.id, a.artist_id
        FROM songs s LEFT JOIN albums a ON s.album_id = a.id
        WHERE s.is_candidate = true AND s.genre = %(g)s AND s.id <> %(seed)s
          AND s.id NOT IN (SELECT song_id FROM user_recommendations WHERE user_id = -1)
        ORDER BY s.embedding <=> %(emb)s::vector
        LIMIT 50
        """,
        {"g": seed_genre, "seed": seed_id, "emb": seed_emb},
    )
    plan = "\n".join(r[0] for r in cur.fetchall())
    print("---- EXPLAIN ----\n" + plan + "\n-----------------", flush=True)

    uses_index = INDEX in plan
    seq_scan = "Seq Scan on songs" in plan
    rows_line = next((l for l in plan.splitlines() if "actual" in l and "rows=" in l), "")
    log(f"VERDICT: uses_hnsw_index={uses_index} seq_scan_on_songs={seq_scan}")
    log(f"  top plan row: {rows_line.strip()}")
    log(f"TOTAL runbook time: {time.time()-t_start:.1f}s")
    if uses_index and not seq_scan:
        log("GATE PASS: genre branch now uses the HNSW index.")
    else:
        log("GATE FAIL: inspect EXPLAIN above. Backfill is harmless; index is rebuilt.")
    conn.close()


if __name__ == "__main__":
    main()
