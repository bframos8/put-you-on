# Optimization Plan — Housekeeping Batch 2 (scoped)

**Date:** 2026-06-12
**Source:** [housekeeping-audit.md](housekeeping-audit.md)
**Branch:** `Backend-optimization`

This plan covers the subset of audit items selected for this pass. Findings were
re-verified against current code (file:line below) before planning — notably H1's
stated fix was found infeasible and pulled out of scope.

## ✅ Status — COMPLETE (2026-06-15)

All in-scope items shipped on `Backend-optimization` in four revertible commits.
Migration applied to the live DB; both suites green; frontend build + lint clean.

| Group | Commit | Items | Result |
|-------|--------|-------|--------|
| Pipeline dedup | `2378b09` | M5, M4 | pipeline suite **172 passed** |
| Backend guard | `05a125b` | M1 | backend suite green (+5 guard tests) |
| L4 migration + wire-up | `fe00c5b` | L4(a) | migration `a7b8c9d0e1f2` applied; DB at head; `user_top_songs.duration_ms` = INTEGER live |
| L4 UI | `d31fa00` | L4(b), L4(c) | backend **127 passed**; `next build` + `eslint` clean |

**Deviations from the plan as written (all verified by a double-check agent):**
- **M4 shipped as TWO helpers**, not one — the single-row and batch methods raise
  genuinely different message sets, so one helper couldn't preserve exact contracts.
- **L4(b) "Last sync" = absolute date/time** (user decision), "Never" when no snapshot.
- **`popularity` kept** as-is (user decision).
- **Caveat (open, non-blocking):** `snapshot_at` is a naive `datetime.now()`, so the
  absolute "Last sync" can skew if server/browser timezones differ. Fine for an MVP
  label; tz-aware UTC is a future follow-up.

## Decisions captured (from the user)

| Item | Decision |
|------|----------|
| **M1** | In scope — unify the audio-load/embed logic (esp. the empty-frame guard). |
| **M5** | In scope — single source of truth for `AUDIO_EXTENSIONS`. |
| **M4** | In scope — **validation helper only**. Do **not** touch the error-contract split this pass. |
| **L4** | In scope — **wire up `duration_ms`** (real data) + back "Last sync" with a real timestamp. |
| **H2** | **Leave as-is** — no change this pass (documented, not forgotten). |
| **H1** | **Deferred** — see "Why H1 is out" below. |
| **H3 + L5** | Deferred (logging migration not selected). |
| **L1, L3** | Deferred (policy calls not selected). |

### Why H1 is out
The audit proposed "load the graph once and read both outputs." Verification showed the
two consumers use **different** output nodes of the same `.pb`:
- `SpotifyIngestService` → `output="PartitionedCall:1"` (embeddings) —
  [spotify_ingest_service.py:29-31](backend/app/services/spotify_ingest_service.py#L29-L31)
- `AudioGenreClassifier` → `output="PartitionedCall:0"` (genre head) —
  [audio_genre_classifier.py:16-18](backend/app/services/audio_genre_classifier.py#L16-L18)

In Essentia, `output=` is fixed at construction; one instance exposes one node. So neither
"share one instance" nor "pass the loaded model in" works — a true single-load requires
dropping to raw TensorFlow to pull both heads from one session. That's a deliberate
refactor with real risk, not the mechanical win the audit implied. **Out of this pass.**

---

## Items

### M5 — Single source of truth for `AUDIO_EXTENSIONS`
> **✅ Done** (`2378b09`) — `AUDIO_EXTENSIONS` promoted to a module constant in
> [song_downloader.py](data_pipeline/song_pipeline/song_downloader.py) and referenced
> inside `_download_songs`. Backend unchanged. Pipeline suite 172 passed.

**Verified state:**
- Backend already a module constant: [spotify_ingest_service.py:23](backend/app/services/spotify_ingest_service.py#L23) — `AUDIO_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a", ".ogg"}`
- Pipeline is a **local var** inside a method: [song_downloader.py:110](data_pipeline/song_pipeline/song_downloader.py#L110) — `audio_extensions = {'.mp3', ...}`

The two apps are **separate deploy units with separate venvs** (`.venv.backend`,
`.venv.pipeline`), so there is no shared import to lean on. The fix is one module-level
constant **per app**.

**Change:** In `song_downloader.py`, promote the set to a module-level
`AUDIO_EXTENSIONS` constant at the top of the file and reference it inside the method.
(Backend is already correct — no change.)

**Risk:** Trivial. **Tests:** pipeline suite.

---

### M1 — Unify audio-load / embed (kill the guard drift)
> **✅ Done** (`05a125b`) — empty-frame guard added to the backend's `_embed`, byte-identical
> message to the pipeline; mirror comments added in both
> [spotify_ingest_service.py](backend/app/services/spotify_ingest_service.py) and
> [song_embedder.py](data_pipeline/song_pipeline/song_embedder.py). Confirmed the only live
> caller (`process_top_tracks`) already catches + skips, and `ingest()` is unused — no caller
> depended on the silent path. Added [test_embed_guard.py](backend/tests/test_embed_guard.py)
> (5 cases) mirroring the pipeline's guard tests.

**Verified state:** near-identical, the only material difference is an empty-frame guard
that exists in the pipeline but **not** the backend:
- Backend [spotify_ingest_service.py:62-69](backend/app/services/spotify_ingest_service.py#L62-L69) — `_load_audio` / `_embed`, **no guard**
- Pipeline [song_embedder.py:75-84](data_pipeline/song_pipeline/song_embedder.py#L75-L84) — `_load_song` / `_embed_song`, **has** the empty-frame `ValueError` guard

Because the apps don't share a venv, a literal shared import would mean publishing a real
shared package into both environments — that's packaging work, **not** mechanical, and is
out of this pass. The pragmatic, behavior-preserving fix is to **eliminate the drift**:

**Change:** Add the same empty-frame guard to the backend's `_embed`, matching the
pipeline's contract:
```python
def _embed(self, audio: np.ndarray) -> np.ndarray:
    frame_embeddings = self.model(audio)
    if not isinstance(frame_embeddings, np.ndarray) or frame_embeddings.ndim == 0 or len(frame_embeddings) == 0:
        raise ValueError(f"Model returned no frames — audio may be too short ({len(audio) / 16000:.2f}s)")
    return frame_embeddings.mean(axis=0)
```
Add a short comment in both files noting they intentionally mirror one contract
(single source-of-truth-by-convention). Full extraction into a shared package is a
**follow-up**, recorded here, not done now.

**Risk:** Low. Backend gains a guard that raises on degenerate audio instead of producing
a garbage mean — verify no caller depends on the silent path. **Tests:** backend suite
(check `_embed` callers / ingest path).

---

### M4 — `DatabaseManager` validation helper (helper only)
> **✅ Done** (`2378b09`) — shipped as **TWO** helpers in
> [manager.py](data_pipeline/db/manager.py), not one: the 6 methods use two distinct guard
> shapes that a single helper can't reproduce 1:1.
> - `_validate_single_insert` (4 single-row methods: `insert_row`, `insert_row_and_return_id`,
>   `upsert_row`, `upsert_row_and_return_id`) — keeps the `len(columns) != len(data)` check and
>   the "…insert **row** without…" messages.
> - `_validate_batch_insert` (2 batch methods: `insert_rows`, `insert_rows_ignore_conflicts`) —
>   no length check, "…insert without…" messages.
> Each upsert's `conflict_column` check stays inline. Error-contract split left untouched as
> planned. Pipeline DB guard tests pass unchanged.

**Verified state:** the same guard (`if not data / table_name / column_names`,
`len(column_names) != len(data)`) is copy-pasted across **6** methods in
[data_pipeline/db/manager.py](data_pipeline/db/manager.py):

| Method | Guard lines |
|--------|-------------|
| `insert_row` | 42-49 |
| `insert_row_and_return_id` | 65-72 |
| `insert_rows` | 138-143 |
| `insert_rows_ignore_conflicts` | 195-200 |
| `upsert_row` | 260-269 |
| `upsert_row_and_return_id` | 306-315 |

**Change:** Extract one private helper and call it from each of the 6 methods, preserving
the exact same exception type/message they currently raise:
```python
def _validate_insert(self, table_name, column_names, data) -> None:
    # same checks the 6 methods currently inline
    ...
```
**Explicitly NOT in this pass:** the error-contract split (some methods swallow
`psycopg.Error` and return `-1`/`[]`/`False` at lines 86/96/182/243/288/357, others
re-raise at 155/218). Per the decision, leave that behavior untouched — it's a reviewed
behavior change, not a mechanical refactor.

**Risk:** Low if the helper reproduces the existing checks/messages 1:1. **Tests:**
pipeline DB suite — the guard tests should pass unchanged.

---

### L4 — Wire up `duration_ms` + real "Last sync"
> **✅ Done** — (a) `fe00c5b`, (b)+(c) `d31fa00`. Details under each sub-part below.

This one has two parts with **different cost**.

#### (a) `duration_ms` — needs a column migration
> **✅ Done** (`fe00c5b`) — Alembic revision
> [a7b8c9d0e1f2](backend/alembic/versions/a7b8c9d0e1f2_add_duration_ms_to_user_top_songs.py)
> (`down_revision = f6a2b3c4d5e6`) adds the nullable column; `duration_ms = Column(Integer)`
> on `UserTopSong`; `add_user_top_songs` persists `track.get("duration_ms")`;
> `from_user_top_song` passes it through. **Applied to the live DB** — `alembic current` =
> `a7b8c9d0e1f2 (head)`, `user_top_songs.duration_ms` = INTEGER. Existing rows stay NULL
> until the next sync rebuilds the snapshot. Test: `_make_top_song` sets `duration_ms`
> explicitly (spec'd-mock fix) + a flow-through assertion.

**Verified state:** the top-tracks endpoint serves **persisted** rows via
[song.py:49-57 `from_user_top_song`](backend/app/schemas/song.py#L49-L57), and
[UserTopSong](backend/app/db/models.py#L92-L106) has **no `duration_ms` column**.
Spotify's top-tracks payload **does** include `duration_ms`, but
[`add_user_top_songs`](backend/app/services/spotify_ingest_service.py#L86-L109) never
stores it. So a true wire-up is end-to-end:

1. **Migration** — add `duration_ms = Column(Integer)` to `UserTopSong` via a new
   Alembic revision in [backend/alembic/versions/](backend/alembic/versions/) (backend
   uses Alembic + a `create_all` fallback at [main.py:25](backend/app/main.py#L25)).
2. **Ingest** — in `add_user_top_songs`, persist `duration_ms=track.get("duration_ms")`
   on the `UserTopSong(...)` construction (~line 97-108).
3. **Schema** — in `from_user_top_song`, pass `duration_ms=row.duration_ms` through
   (the `TopTrackItem.duration_ms` field already exists at
   [song.py:45](backend/app/schemas/song.py#L45)).
4. **Frontend** — none needed: `formatDuration(t.duration_ms)` already renders it at
   [profile-content.tsx:258](frontend/src/components/profile-content.tsx#L258); it just
   stops being `"—:—"` once data flows. Existing rows show `"—:—"` until the next sync
   re-populates them (acceptable — the table is rebuilt each sync via the `delete()` at
   [spotify_ingest_service.py:87](backend/app/services/spotify_ingest_service.py#L87)).

#### (b) "Last sync" — no migration (use existing `snapshot_at`)
> **✅ Done** (`d31fa00`) — `last_synced_at` exposed on **`TopTracksResponse`** (wrapper, not
> per-item), derived in the route via
> `max((r.snapshot_at for r in rows if r.snapshot_at), default=None)`. Frontend replaces the
> hardcoded `"Just now"` with `formatSyncTime(lastSync)` — **absolute date/time** (e.g.
> "Jun 15, 2:30 PM"), `"Never"` when null. ⚠️ naive-datetime tz caveat noted above. Tests:
> `_make_top_song` sets `snapshot_at`; empty-response assertion updated to
> `{"tracks": [], "last_synced_at": None}`; +2 `last_synced_at` cases.

**Verified state:** hardcoded `"Just now"` at
[profile-content.tsx:159](frontend/src/components/profile-content.tsx#L159);
`UserTopSong.snapshot_at` already exists and is set on every ingest
([models.py:105](backend/app/db/models.py#L105),
[spotify_ingest_service.py:107](backend/app/services/spotify_ingest_service.py#L107)).

1. **Schema** — expose `snapshot_at` (e.g. on `TopTracksResponse` or each item) from
   `from_user_top_song`.
2. **Frontend** — replace the hardcoded `"Just now"` with a value derived from the
   timestamp (relative or formatted). Human copy, not AI-flavored.

#### (c) Cleanup while here
> **✅ Done** (`d31fa00`) — `data.tracks ?? data.items ?? data` collapsed to
> `data.tracks ?? []`. `popularity` **kept** as-is (user decision).

Remove the dead response-shape fallback at
[profile-content.tsx:74](frontend/src/components/profile-content.tsx#L74):
`data.tracks ?? data.items ?? data` → the API only returns `{ tracks: [...] }`, so this
collapses to `data.tracks`. The unused `popularity` field
([song.py:46](backend/app/schemas/song.py#L46),
[profile-content.tsx:15](frontend/src/components/profile-content.tsx#L15)) can stay or be
dropped — flag, low priority.

**Risk:** Medium (touches a migration + ingest + schema + UI). Sequence the migration
first, then ingest/schema, then verify the UI end-to-end. **Tests:** backend schema/API
tests; manual UI check via `/verify` or `/run`.

---

### H2 — Model binary: leave as-is (documented)
**Decision: no change this pass.** Recorded so it doesn't silently fall off:
- Both `.pb` (18 MB each) are git-tracked, no `.gitignore` entry, path hardcoded in 3
  files ([audio_genre_classifier.py](backend/app/services/audio_genre_classifier.py),
  [spotify_ingest_service.py](backend/app/services/spotify_ingest_service.py),
  [song_embedder.py](data_pipeline/song_pipeline/song_embedder.py)).
- A future pass should pick: gitignore+fetch / Git LFS / single canonical copy. History
  purge remains a separate, deliberate, destructive call — not routine cleanup.

---

## Order of execution
1. **M5** — promote the constant (smallest, isolated).
2. **M4** — extract `_validate_insert`, call from the 6 methods.
3. **M1** — add the empty-frame guard to backend `_embed`.
   → Run the **data_pipeline** suite after 1–2, the **backend** suite after 3.
4. **L4(a)** — Alembic migration for `duration_ms`, then ingest + schema wiring.
5. **L4(b)** — expose `snapshot_at`, replace hardcoded "Last sync".
6. **L4(c)** — drop the dead `data.items ?? data` fallback.
   → Backend tests, then verify the profile page end-to-end.

Commit in logical groups (pipeline dedup; backend guard; L4 migration; L4 UI) so each is
revertible.

## Verification — results
- **Pipeline:** `data_pipeline` suite **172 passed** (matches the audit baseline). ✅
- **Backend:** suite **127 passed** (was 118 + 9 new tests); `_embed` guard caller path
  confirmed. ✅
- **Frontend:** `next build` ✓ and `eslint` ✓ clean. Migration applied live; durations and
  "Last sync" will render from real data on the **next sync** (existing pre-column rows show
  `"—:—"` until their snapshot is rebuilt). A manual profile-page check post-sync is the only
  remaining human step.

## Explicitly out of scope (deferred, not dropped)
H1 (single model load — needs raw-TF), H3 + L5 (logging migration), L1 (f-string SQL),
L3 (stale artifacts), H2 (binary strategy), M4 error-contract unification.
