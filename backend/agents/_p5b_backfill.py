"""Throwaway: batched backfill of songs.genre from albums.genre for candidates.
Commits per batch to keep locks short and avoid one giant transaction on the
1.5GB songs table. Idempotent; only touches fillable rows (album genre present),
so it always terminates. Deleted after P5b lands."""
import os, time
from pathlib import Path
from dotenv import load_dotenv
import psycopg2

load_dotenv(Path("..") / ".env-postgres")
conn = psycopg2.connect(
    dbname=os.environ["POSTGRES_DB"], user=os.environ["POSTGRES_USER"],
    password=os.environ["POSTGRES_PASSWORD"], host=os.environ["POSTGRES_HOST"],
    port=os.environ["POSTGRES_PORT"], connect_timeout=20,
)
conn.autocommit = False
cur = conn.cursor()
BATCH = 10000
total = 0
t0 = time.time()
while True:
    t = time.time()
    # Only select rows that CAN be filled (album genre present) so a NULL-album-
    # genre candidate can never be re-selected forever. Each row gets a non-NULL
    # genre, removing it from the next batch -> guaranteed termination.
    cur.execute(
        """
        WITH batch AS (
            SELECT s.id, a.genre AS g
            FROM songs s
            JOIN albums a ON s.album_id = a.id
            WHERE s.is_candidate = true
              AND s.genre IS NULL
              AND a.genre IS NOT NULL
            LIMIT %s
        )
        UPDATE songs SET genre = batch.g
        FROM batch
        WHERE songs.id = batch.id
        """,
        (BATCH,),
    )
    n = cur.rowcount
    conn.commit()
    total += n
    print(f"batch={n:6d} total={total:7d} ({time.time()-t:.1f}s)", flush=True)
    if n == 0:
        break
print(f"DONE backfilled total={total} in {time.time()-t0:.1f}s", flush=True)
conn.close()
