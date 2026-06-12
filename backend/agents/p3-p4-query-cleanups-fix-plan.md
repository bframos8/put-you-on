# P3 + P4 Fix Plan — N+1 query cleanups in ingest/dispatch (MEDIUM / LOW)

> Status: **Plan approved, not yet implemented.**
> Source findings: [.claude-backend-optimization.md → P3](.claude-backend-optimization.md#L173),
> [→ P4](.claude-backend-optimization.md#L186).
> Scope: **P3 and P4 only.** All Tier-1 security items (S1–S6) are done. **P6 is
> deferred** — see §6 (its premise is broken; it needs a baseline migration first).

## 1. The bugs

### P3 — N+1 lazy loads when building dispatch responses
- [get_todays_dispatch](../app/services/spotify_ingest_service.py#L288-L300) runs
  one query for `UserRecommendation` rows, then returns
  `rows[0].query_song` and `[r.song for r in rows]`. Each `r.song` is a lazy load,
  and [SongResponse.from_song](../app/schemas/song.py#L26-L35) then touches
  `song.album` for each — so ~10 recs trigger ~10–20 extra queries per fetch.
- [query_recommendations](../app/services/spotify_ingest_service.py#L223-L286)
  returns candidate `Song`s from `db.query(Song, Album.artist_id)`. Their `.album`
  is **not** populated (the `outerjoin` only feeds `artist_id` + ordering), so the
  serializer lazy-loads `song.album` per result.

### P4 — N+1 in top-song ingest lookups
- [add_user_top_songs](../app/services/spotify_ingest_service.py#L86-L104) and
  [process_top_tracks](../app/services/spotify_ingest_service.py#L121-L122) query
  `Song` **once per track** by `spotify_track_id` inside a loop.

### Verified facts (sweep agent)
- All four methods are **entirely mocked** in the test suite (the whole
  `SpotifyIngestService` is replaced by a `MagicMock` in
  [conftest.py](../tests/conftest.py#L156-L181)), so changing their internal
  queries cannot break existing route tests.
- Relationships for eager-loading exist:
  [UserRecommendation.song](../app/db/models.py#L123),
  [.query_song](../app/db/models.py#L124),
  [Song.album](../app/db/models.py#L83).
- `query_recommendations` selects `Album.artist_id` as a **column**, not the full
  `Album` entity — so `contains_eager(Song.album)` is awkward there; `selectinload`
  is the robust choice (one batched `albums WHERE id IN (...)` query).
- The unit suite uses Postgres/pgvector-specific SQL (`Vector`,
  `cosine_distance`), so a real query-count integration test isn't feasible here.

## 2. The fix

### 2a. P3 — eager-load in `spotify_ingest_service.py`
Add `selectinload` to the import and apply it:

```python
from sqlalchemy.orm import Session, selectinload
```

`get_todays_dispatch` — load the rec's song + its album, and the query_song, in
batched follow-up queries instead of per-row lazy loads:

```python
rows = (
    db.query(UserRecommendation)
    .options(
        selectinload(UserRecommendation.song).selectinload(Song.album),
        selectinload(UserRecommendation.query_song),
    )
    .filter(
        UserRecommendation.user_id == user.id,
        UserRecommendation.dispatch_date == today_pst(),
    )
    .order_by(UserRecommendation.id.asc())
    .all()
)
```
> `query_song` only feeds `query_title`/`query_artist` (columns), so its album is
> not chained — but eager-loading the relationship avoids a lazy load on
> `rows[0].query_song`.

`query_recommendations` — load each candidate's album so the serializer doesn't
re-query (applies to both the genre-filtered and fallback pools, which share
`base_query`):

```python
base_query = (
    db.query(Song, Album.artist_id)
    .outerjoin(Song.album)
    .options(selectinload(Song.album))
    .filter(Song.is_candidate == True)
    .filter(Song.id != query_song.id)
    .filter(Song.id.not_in(already_recommended))
    .order_by(Song.embedding.cosine_distance(query_song.embedding))
)
```

### 2b. P4 — batch the per-track `Song` lookups
`add_user_top_songs` — one `IN (...)` query into a dict before the loop:

```python
def add_user_top_songs(self, tracks, user, db):
    db.query(UserTopSong).filter(UserTopSong.user_id == user.id).delete()
    snapshot_at = datetime.now()
    track_ids = [t["id"] for t in tracks]
    existing_by_track = {
        s.spotify_track_id: s
        for s in db.query(Song).filter(Song.spotify_track_id.in_(track_ids)).all()
    } if track_ids else {}
    for track in tracks:
        spotify_track_id = track["id"]
        song = existing_by_track.get(spotify_track_id)
        db.add(UserTopSong(... song_id=song.id if song else None,
                           genre=song.genre if song else None ...))
    db.commit()
```

`process_top_tracks` — same pattern; snapshot existing songs once (track ids are
unique, so no in-loop creation invalidates the snapshot):

```python
unprocessed = (... existing query ...).all()
track_ids = [t.spotify_track_id for t in unprocessed]
existing_by_track = {
    s.spotify_track_id: s
    for s in db.query(Song).filter(Song.spotify_track_id.in_(track_ids)).all()
} if track_ids else {}
for top_song in unprocessed:
    existing = existing_by_track.get(top_song.spotify_track_id)
    ...
```
> The dict returns session-attached `Song` objects, so the existing
> `existing.genre = genre` mutation still works.

### 2c. Test — `backend/tests/test_query_cleanups.py` (new)
A focused regression for P4 (the one cleanly assertable change): instantiating a
real `SpotifyIngestService` is cheap in tests (`patch_startup` no-ops `__init__`),
so assert `add_user_top_songs` issues a **single** `Song` lookup regardless of
track count:

```python
from unittest.mock import MagicMock
from app.db.models import Song
from app.services.spotify_ingest_service import SpotifyIngestService

def _track(i):
    return {
        "id": f"track{i}",
        "external_urls": {"spotify": f"https://open.spotify.com/track/{i}"},
        "album": {"name": f"Album {i}", "images": [{"url": f"http://img/{i}"}]},
        "artists": [{"name": f"Artist {i}"}],
        "name": f"Song {i}",
    }

def test_add_user_top_songs_batches_song_lookup(mock_user):
    svc = SpotifyIngestService()
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []  # no existing songs
    svc.add_user_top_songs([_track(i) for i in range(10)], mock_user, db)
    song_lookups = [c for c in db.query.call_args_list if c.args and c.args[0] is Song]
    assert len(song_lookups) == 1   # batched, not one-per-track
```
> P3's eager-loading can't be meaningfully asserted against a mocked `Session`
> (loader options are inert on a `MagicMock`) and needs a real Postgres/pgvector
> DB to observe query counts — out of scope for this unit suite. The existing
> route tests confirm dispatch/recs still serialize correctly.

## 3. Why this is safe

- The methods are mocked in route tests → no behavioral test breaks; the new P4
  test pins the batching.
- P3 is loader-only (same rows, fewer queries); P4 snapshots a unique-keyed set,
  so results are identical to the per-track lookups.

## 4. Files changed

| File | Change |
| --- | --- |
| [app/services/spotify_ingest_service.py](../app/services/spotify_ingest_service.py) | P3: `selectinload` on `get_todays_dispatch` + `query_recommendations`. P4: batched `Song.in_(...)` lookups in `add_user_top_songs` + `process_top_tracks`. |
| `backend/tests/test_query_cleanups.py` | **New** — asserts P4 batches the Song lookup. |

## 5. Validation

```bash
cd backend && pytest                              # full suite stays green
cd backend && pytest tests/test_query_cleanups.py -v
```

## 6. P6 — deferred (premise broken)

P6 ("drop `create_all`, rely on Alembic") is **unsafe as written**: no migration
in [alembic/versions](../alembic/versions/) runs `op.create_table` for the core
tables — the root migration
[ad1aecf9f82f](../alembic/versions/ad1aecf9f82f_initial_schema.py#L21) only
`add_column`s onto an already-existing `user_top_songs`. The six base tables are
created **only** by `create_all`; `alembic upgrade head` on a fresh DB would fail
with `relation "user_top_songs" does not exist`, and the
[Dockerfile](../Dockerfile) has no `alembic upgrade` step. Properly closing P6
requires authoring a baseline `create_table` migration and stamping the
already-deployed DB — **M effort, not XS**. Tracked as re-scoped in the
optimization doc; not done in this pass.
