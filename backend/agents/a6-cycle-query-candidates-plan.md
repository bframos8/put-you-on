# A6 — Cycle query candidates instead of re-ingesting on exhaustion

> **Status:** Plan for review (agent-checked before any edit).
> **Source item:** A6 in
> [backend-optimization-remaining.md](backend-optimization-remaining.md).
> **Branch:** `Backend-optimization`. **Date:** 2026-07-09.
> **Decision (from the user):** **Option (b) — cycle-only.** On exhaustion, recycle the
> existing top-song candidates; do **not** auto re-fetch from Spotify ("top songs don't
> update that quickly"). The snapshot is fetched once (first build) and then reused.

## Problem

[snapshot_is_stale](../app/services/spotify_ingest_service.py#L228-L239) returns stale
when `all_queried` (every processed `UserTopSong` has been used as a query seed). That
makes [get_recs](../app/api/v1/songs.py#L84-L94) call Spotify and run
[add_user_top_songs](../app/services/spotify_ingest_service.py#L114) — a full `DELETE` +
re-insert of the user's `UserTopSong` rows. One seed is consumed per daily dispatch, so
this fires roughly **every ~10 days per user**: an unnecessary Spotify call + row churn,
even when the top tracks are unchanged.

## Decision & tradeoff (Option b)

On exhaustion, **recycle**: reset `used_as_query=False` on the user's processed rows and
walk the pool again. `already_recommended` in
[query_recommendations](../app/services/spotify_ingest_service.py#L274) still dedupes
prior recs, so re-using a seed still yields distinct dispatches.

**Accepted tradeoff (documented):** with (b) the top-tracks snapshot is fetched once (on
the first build) and never auto-refreshes — the user's evolving Spotify top tracks won't
flow in until the rows are cleared/rebuilt. This is acceptable because top tracks change
slowly. A periodic/TTL refresh (option a) or a manual "resync" trigger is **out of scope**
and noted for later.

## Changes (two methods, one file)

### 1. `snapshot_is_stale` — drop the `all_queried` trigger
"Stale" should mean **needs a build** (empty or a prior processing run didn't finish),
not "pool exhausted." Remove the `all_queried` condition and the now-unused `queried`
count:
```python
def snapshot_is_stale(self, user: User, db: Session) -> bool:
    result = db.query(
        func.count().label("total"),
        func.count(UserTopSong.song_id).label("processed"),
    ).filter(UserTopSong.user_id == user.id).one()
    if result.total == 0:
        return True
    # Some rows still lack a Song/genre → a prior ingest didn't finish; rebuild.
    # (Pool exhaustion is NOT staleness — query_recommendations recycles instead.)
    return result.processed < result.total
```
`get_recs` is unchanged: with `all_queried` no longer stale, it falls through to
`query_recommendations`, which now recycles rather than crashing on an empty seed.

### 2. `query_recommendations` — recycle when no unqueried seed remains
Right where the seed is selected
([:261-269](../app/services/spotify_ingest_service.py#L261-L269)), handle the
now-reachable "all seeds used" case:
```python
query_entry = (
    db.query(UserTopSong)
    .filter(
        UserTopSong.user_id == user.id,
        UserTopSong.song_id != None,
        UserTopSong.used_as_query == False,
    )
    .first()
)
if query_entry is None:
    # A6: every processed candidate has been a query seed. Recycle them instead
    # of re-fetching from Spotify + rebuilding the snapshot. already_recommended
    # still dedupes, so dispatches stay distinct.
    db.query(UserTopSong).filter(
        UserTopSong.user_id == user.id,
        UserTopSong.song_id != None,
    ).update({UserTopSong.used_as_query: False}, synchronize_session=False)
    query_entry = (
        db.query(UserTopSong)
        .filter(
            UserTopSong.user_id == user.id,
            UserTopSong.song_id != None,
            UserTopSong.used_as_query == False,
        )
        .first()
    )
```
`synchronize_session=False` is correct: the bulk `UPDATE` is emitted in the same
transaction, so the immediately-following re-`SELECT` sees the reset rows; no
already-loaded `UserTopSong` instances are in the identity map at this point. The final
`db.commit()` at the end of the method commits the reset, the chosen seed's
`used_as_query=True`, and the new `UserRecommendation` rows atomically.

## Why this is safe — what doesn't break

- **Invariant preserved:** `query_recommendations` is only reached with ≥1 **processed**
  row — either `get_recs` found the snapshot not-stale (⇒ `processed == total > 0`), or
  the background `unblock` callback fired after ≥1 song processed. So after the recycle,
  the re-pick always finds a seed (no `None.song` crash). Previously `all_queried → stale
  → rebuild` avoided that crash by rebuilding; now the recycle handles it in-place.
- **`get_recs` untouched** — same call sequence
  ([songs.py:84-96](../app/api/v1/songs.py#L84-L96)).
- **Route tests unaffected:** `test_songs.py` / `test_rate_limiting.py` / `conftest.py`
  mock the whole ingest service (`snapshot_is_stale`/`query_recommendations` return
  values), so real-logic changes don't touch them.
- **`test_genre_filtering.py` unaffected:** it drives the real `query_recommendations`
  with a **non-None** `query_entry` ([:47](../tests/test_genre_filtering.py#L47)
  `used_as_query = False`), so the new `if query_entry is None` branch is skipped and the
  existing assertions (incl. `test_used_as_query_flag_set`) still hold.
- **No new query shape breaks a test:** no test asserts `snapshot_is_stale`'s internal
  columns; dropping the `queried` count is invisible externally.

## Validation — new tests (in `tests/test_genre_filtering.py` or a new file)

- **recycle path:** mock the seed query's `.first()` to return `None` then a valid entry
  (`side_effect=[None, entry]`); run `query_recommendations`; assert the bulk
  `.update({used_as_query: False})` was issued on the `UserTopSong` query and a normal
  dispatch is produced (reuse the existing `make_db` pool wiring for the rest).
- **snapshot_is_stale semantics:** mock `db.query(...).filter(...).one()` to return
  rows with `(total, processed)` = (0, 0) → True; (10, 10) [all processed, formerly
  all_queried] → **False** (the behavior change); (10, 7) [unprocessed] → True.
- Run the full backend suite — expect the prior **138** still green (plus the new tests).

## Risk / rollback
- **Risk: low.** Two methods, one file; `get_recs` and all callers unchanged.
- **Rollback:** revert the two methods (restores `all_queried`-triggers-rebuild).

## Files changed
| File | Change |
|------|--------|
| [app/services/spotify_ingest_service.py](../app/services/spotify_ingest_service.py) | `snapshot_is_stale`: drop `all_queried` (+ unused `queried` count); `query_recommendations`: recycle seeds when exhausted |
| `tests/test_genre_filtering.py` (or new) | recycle-path + `snapshot_is_stale`-semantics tests |

## Out of scope (recorded)
- Periodic/TTL refresh of the snapshot (option a) — not chosen; top tracks change slowly.
- A manual "resync top tracks" endpoint — a future way to force a refresh under (b).
- The `has_unprocessed → rebuild` recovery path — unchanged (still re-fetches to retry a
  failed ingest; that's a different scenario from steady-state exhaustion).
