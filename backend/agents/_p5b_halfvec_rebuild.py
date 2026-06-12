"""P5b index recovery: rebuild songs HNSW as a HALFVEC index so the build fits in
RAM on the small (~1GB) RDS instance.

The full vector(1280) working set is ~568MB > instance RAM, so a bulk HNSW build
spills to the on-disk insert path (~0.18 tuples/sec -> ~3 days, and fragile over a
single client connection). halfvec (2 bytes/dim) halves the working set to ~284MB,
which fits under maintenance_work_mem -> in-memory build in minutes. Half precision
costs negligible cosine-kNN recall.

Index: songs_embedding_hnsw_idx ON songs USING hnsw ((embedding::halfvec(1280))
halfvec_cosine_ops). The app query must ORDER BY embedding::halfvec(1280) <=>
q::halfvec(1280) to use it (follow-up code change). Throwaway; delete after P5b.
"""
import os
import time
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env-postgres")

INDEX = "songs_embedding_hnsw_idx"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    c = psycopg2.connect(
        dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"], host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"], connect_timeout=20,
    )
    c.autocommit = True
    cur = c.cursor()
    t0 = time.time()

    # 1. Cancel any in-progress CREATE INDEX on songs (the stalled full-vector build).
    cur.execute("""
        SELECT a.pid FROM pg_stat_progress_create_index p
        JOIN pg_stat_activity a USING (pid)
        WHERE p.relid = 'songs'::regclass
    """)
    for (pid,) in cur.fetchall():
        cur.execute("SELECT pg_cancel_backend(%s)", (pid,))
        log(f"cancelled in-progress build pid={pid} -> {cur.fetchone()[0]}")
    # wait for it to clear
    for _ in range(30):
        cur.execute("SELECT count(*) FROM pg_stat_progress_create_index "
                    "WHERE relid='songs'::regclass")
        if cur.fetchone()[0] == 0:
            break
        time.sleep(1)
    log("no build in progress on songs")

    # 2. Drop any leftover index def, then build halfvec.
    cur.execute(f"DROP INDEX IF EXISTS {INDEX}")
    log(f"dropped {INDEX} (if any)")
    for stmt in ("SET maintenance_work_mem = '400MB'",
                 "SET max_parallel_maintenance_workers = 0"):
        cur.execute(stmt); log(f"  {stmt}")

    log(f"CREATE INDEX {INDEX} (hnsw, HALFVEC cosine) ... [should be minutes]")
    t = time.time()
    cur.execute(
        f"CREATE INDEX {INDEX} ON songs "
        f"USING hnsw ((embedding::halfvec(1280)) halfvec_cosine_ops)"
    )
    log(f"  index built ({time.time()-t:.1f}s)")
    cur.execute("ANALYZE songs")
    log("  ANALYZE songs done")

    # 3. Validation EXPLAIN (must use the halfvec index; note the ::halfvec cast).
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
        ORDER BY s.embedding::halfvec(1280) <=> %(emb)s::halfvec(1280)
        LIMIT 50
        """,
        {"g": seed_genre, "seed": seed_id, "emb": seed_emb},
    )
    plan = "\n".join(r[0] for r in cur.fetchall())
    print("---- EXPLAIN ----\n" + plan + "\n-----------------", flush=True)
    uses_index = INDEX in plan
    seq_scan = "Seq Scan on songs" in plan
    log(f"VERDICT: uses_hnsw_index={uses_index} seq_scan_on_songs={seq_scan}")
    log(f"TOTAL time: {time.time()-t0:.1f}s")
    log("GATE PASS." if uses_index and not seq_scan
        else "GATE FAIL — inspect EXPLAIN above.")
    c.close()


if __name__ == "__main__":
    main()
