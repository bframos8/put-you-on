# Codebase Housekeeping Audit

**Date:** 2026-06-12
**Scope:** `backend/`, `data_pipeline/`, `frontend/` (settled code)
**Flag types covered:** code smells / tech debt + TODO/FIXME/HACK markers
**Out of scope this pass:** security & secrets, functional bugs/correctness
**Excluded:** uncommitted WIP (`backend/agents/_p5b_*.py`, `*-plan.md`, `h1-*`, deleted `backend/app/models/models.py`), virtualenvs, `node_modules`, build output

> **Audit only.** Every "How to resolve" is a non-breaking refactor or a deletion of
> verified-dead code. The one item that touches git history (H2) is flagged as
> *handle with care* — do not run it blind.
>
> Findings were independently fact-checked by a second agent; verdicts noted per item.
>
> **Progress (2026-06-12):** Batch 1 — low-risk deletions — **done**: ✅ M2, ✅ M3,
> ✅ M6, ✅ L2 (see resolution lines per item). Committed in `01335bd` + `5bcb92a`.
> Two follow-on **test fixes** surfaced while applying Batch 1 (both expected — a
> deleted method had test coverage, and three integration tests had an unrealistic
> mock): see the **Test fixes from Batch 1** section below. Remaining: Batch 2
> (H1, M1, M4, M5), Batch 3 (H3 + L5), and the policy calls (H2, L1, L3).

---

## Summary

| #  | Flag | Area | Priority | Status |
|----|------|------|----------|--------|
| H1 | Embedding model graph loaded into memory **twice** in the backend process | backend | High | Open (Batch 2) |
| H2 | 18 MB ML model binary committed to git **twice** (~36 MB tracked) | repo-wide | High* | Open (policy call) |
| H3 | `print()` used for logging everywhere (no levels, can't silence) | backend + pipeline | High | Open (Batch 3) |
| M1 | Audio-load + embed logic duplicated across backend and pipeline | backend + pipeline | Medium | Open (Batch 2) |
| M2 | Dead "legacy" `Song` dataclass (only its own test uses it) | pipeline | Medium | ✅ Done |
| M3 | Two orphan frontend UI components (~369 dead lines) | frontend | Medium | ✅ Done |
| M4 | `DatabaseManager` validation boilerplate + inconsistent error handling | pipeline | Medium | Open (Batch 2) |
| M5 | `AUDIO_EXTENSIONS` set duplicated in two files | backend + pipeline | Medium | Open (Batch 2) |
| M6 | Crawler writes `resp.json` on every response + commented-out dead code | pipeline | Medium | ✅ Done |
| L1 | Raw f-string SQL in `_get_albums_to_download` (inconsistent with rest) | pipeline | Low | Open (policy call) |
| L2 | `practice/` scratch dir + `.reminders` tracked in git | repo-wide | Low | ✅ Done |
| L3 | Stale agent/handoff/reference artifacts tracked | repo-wide | Low | Open (policy call) |
| L4 | Profile page renders dead fields (`duration_ms` always `—:—`, hardcoded "Just now") | frontend | Low | Open |
| L5 | Misspelling "succesfully" in two files | pipeline | Low | Open (Batch 3) |

\* H2 priority is high by impact, but the fix touches git history — see the caution note.

> Note: a sweep for literal `TODO`/`FIXME`/`HACK`/`XXX` markers found **none** in source.
> The findings below are structural smells, not annotation cleanup.

---

## High priority

### H1 — Embedding model loaded into memory twice per backend process
**Where:** [backend/app/services/spotify_ingest_service.py:29-32](backend/app/services/spotify_ingest_service.py#L29-L32), [backend/app/services/audio_genre_classifier.py:16-17](backend/app/services/audio_genre_classifier.py#L16-L17)
**What:** `SpotifyIngestService.__init__` instantiates `TensorflowPredictEffnetDiscogs(graphFilename=discogs-effnet-bs64-1.pb, output="PartitionedCall:1")` and then constructs `AudioGenreClassifier()`, which loads the **same `.pb` graph** again with `output="PartitionedCall:0"`. Two full TensorFlow graphs are held in memory for the life of the app (the service is a singleton on `app.state`). *(Verified: CONFIRMED.)*
**Why it's a flag:** Doubles the model's memory footprint and load time at startup for one underlying network that exposes both an embedding head and a classification head.
**How to resolve (non-breaking):** Load the graph once and read both outputs — either share a single `TensorflowPredictEffnetDiscogs` instance configured for the needed output, or have `AudioGenreClassifier` accept an already-loaded model/embeddings instead of constructing its own. Keep the public `ingest()` / `classify()` signatures identical so callers don't change.
**Priority:** High — runtime memory + startup cost on the hot service object.

### H2 — Same 18 MB model binary committed to git in two places
**Where:** `backend/app/models/discogs-effnet-bs64-1.pb`, `data_pipeline/models/discogs-effnet-bs64-1.pb` (both `git ls-files`-tracked, 18,366,619 bytes each)
**What:** The two largest tracked files in the repo are byte-identical copies of the same model. *(Verified: CONFIRMED.)*
**Why it's a flag:** ~36 MB of duplicated binary bloats every clone and lives forever in history. Binaries also don't diff, so each re-commit balloons the pack.
**How to resolve — ⚠️ handle with care:**
- Going forward: stop tracking the `.pb` (add to `.gitignore`) and fetch it at setup time, **or** move both to Git LFS, **or** keep one canonical copy and have one service reference the other's path.
- Purging it from existing history (`git filter-repo` / BFG) is a **destructive, force-push** operation that rewrites commit hashes — only do this deliberately, coordinated with anyone else who has cloned. Do **not** treat it as routine cleanup.
**Priority:** High by impact; low urgency; **do not auto-fix**.

### H3 — `print()` used as the logging mechanism
**Where:** ~69 `print(` calls in `data_pipeline` (non-test) and ~8 in `backend/app` *(Verified: CONFIRMED counts)* — e.g. [spotify_ingest_service.py:145-196](backend/app/services/spotify_ingest_service.py#L145-L196), [data_pipeline/db/manager.py](data_pipeline/db/manager.py), [crawler.py](data_pipeline/link_pipeline/crawler.py)
**What:** Operational/error output goes through `print()` rather than the `logging` module.
**Why it's a flag:** No log levels, no timestamps, can't be silenced or routed, and error context (`print(f"...{e}")`) is lost to stdout. Mixed with genuine user output it's hard to grep in production.
**How to resolve (non-breaking):** Introduce a module-level `logger = logging.getLogger(__name__)` per package and replace prints with `logger.info/warning/error` (use `logger.exception` inside `except`). Mechanical and behavior-preserving. Can be staged file-by-file.
**Priority:** High for maintainability; large surface, so worth doing incrementally.

---

## Medium priority

### M1 — Audio-load + embedding logic duplicated across the two apps
**Where:** [backend/app/services/spotify_ingest_service.py:62-69](backend/app/services/spotify_ingest_service.py#L62-L69) vs [data_pipeline/song_pipeline/song_embedder.py:75-84](data_pipeline/song_pipeline/song_embedder.py#L75-L84)
**What:** `_load_audio`/`_embed` and `_load_song`/`_embed_song` are near-identical: `MonoLoader(sampleRate=16000, resampleQuality=4)` + `frame_embeddings.mean(axis=0)`, plus the `GRAPH_FILE` path constant repeated in three files. The pipeline version adds an empty-frame guard the backend lacks. *(Verified: CONFIRMED.)*
**Why it's a flag:** Two copies drift apart (the guard already has) and the embedding contract lives in two places.
**How to resolve:** Extract a small shared `embedding` helper (load + mean-pool + the empty-frame guard) and have both call it. Note the two apps are separate deploy units with separate venvs, so a literal shared import may need a tiny shared module or copy-with-a-single-source-of-truth; at minimum unify the guard and the `GRAPH_FILE` constant.
**Priority:** Medium.

### M2 — Dead "legacy" `Song` dataclass ✅ DONE (2026-06-12)
**Resolution:** Deleted the `Song` dataclass from `datamodels.py` and its self-referential
`TestSong` class from `tests/tools/test_datamodels.py` (and dropped `Song` from that file's
import). `datamodels` test suite: 9 passed.
**Where:** [data_pipeline/models/datamodels.py:26-33](data_pipeline/models/datamodels.py#L26-L33)
**What:** `Song` is self-labeled *"Legacy song dataclass - kept for compatibility"* and is used by **no production code**. The only reference is `data_pipeline/tests/tools/test_datamodels.py::TestSong`, a test that exists solely to exercise this class. *(Verified: PARTIALLY TRUE — unused in production, but a self-referential test exists.)*
**Why it's a flag:** Dead code kept alive by a dead test; misleads readers into thinking it's load-bearing.
**How to resolve:** Confirm no external/notebook usage, then delete the `Song` dataclass and its `TestSong` test together.
**Priority:** Medium.

### M3 — Orphan frontend UI components (~369 dead lines) ✅ DONE (2026-06-12)
**Resolution:** `git rm`'d both files (zero importers confirmed). `package.json` left
untouched by design — `radix-ui` / `motion/react` are shared meta-packages used by other
components. **Follow-up flagged:** `react-use-measure` is now an orphaned dependency (was
only used by `infinite-slider.tsx`); removing it means lockfile churn, deferred out of a
deletions batch.
**Where:** [frontend/src/components/ui/dropdown-menu.tsx](frontend/src/components/ui/dropdown-menu.tsx) (257 lines), [frontend/src/components/ui/infinite-slider.tsx](frontend/src/components/ui/infinite-slider.tsx) (112 lines)
**What:** Neither component is imported anywhere under `frontend/src`. *(Verified: CONFIRMED — zero importers.)*
**Why it's a flag:** Dead components carry their own deps (e.g. Radix) and noise into the bundle/mental model.
**How to resolve:** Delete both files. If either dropped a now-unused npm dependency, remove it from `package.json` too. Re-run `next build` to confirm nothing referenced them dynamically.
**Priority:** Medium.

### M4 — `DatabaseManager`: repeated validation + inconsistent error handling
**Where:** [data_pipeline/db/manager.py](data_pipeline/db/manager.py) — validation blocks at lines ~42-49, 65-72, 260-267, 306-313; error handling at lines 88/99/291/359 (swallow → return `-1`/`[]`/`False`) vs 158/221 (re-raise)
**What:** The same `if not data / table_name / column_names / len-mismatch` guard is copy-pasted across ~6 methods. Separately, some methods swallow `psycopg.Error` and return a sentinel while others re-raise. *(Verified: CONFIRMED, both parts.)*
**Why it's a flag:** Boilerplate drift, and the mixed error contract means callers can't reason uniformly about failure (silent `-1`/`[]` vs exception).
**How to resolve:** Extract one `_validate_insert(table_name, column_names, data)` helper. Separately, pick a single error policy (recommend: let `psycopg.Error` propagate and let callers decide) and apply it consistently — but treat the policy change as a behavior change to review, not a blind sweep.
**Priority:** Medium.

### M5 — `AUDIO_EXTENSIONS` set duplicated
**Where:** [backend/app/services/spotify_ingest_service.py:23](backend/app/services/spotify_ingest_service.py#L23) and [data_pipeline/song_pipeline/song_downloader.py:110](data_pipeline/song_pipeline/song_downloader.py#L110)
**What:** `{".mp3", ".flac", ".wav", ".m4a", ".ogg"}` defined in both (constant in one, local var in the other). *(Verified: CONFIRMED.)*
**Why it's a flag:** Two sources of truth for "what counts as audio."
**How to resolve:** Promote to one module-level constant per app (each app is independent), or a shared config. Minimal change.
**Priority:** Medium-low.

### M6 — Crawler writes `resp.json` on every response + commented-out dead code ✅ DONE (2026-06-12)
**Resolution:** Removed `_save_resp` entirely (per decision — not gated behind a debug
flag), its call site, the dead commented-out block in `_check_session`, and the now-unused
`import json`. **Test fallout (expected):** `_save_resp` had direct + indirect test coverage
— see **Test fixes from Batch 1** below. `link_pipeline` suite: 57 passed.
**Where:** [data_pipeline/link_pipeline/crawler.py:126-128](data_pipeline/link_pipeline/crawler.py#L126-L128) (`_save_resp`, called from line 111) and [crawler.py:120-124](data_pipeline/link_pipeline/crawler.py#L120-L124) (`_check_session` dead comments)
**What:** `_save_resp` dumps the latest payload to `resp.json` on every OK API response — a debugging artifact left in the hot path. `_check_session` is a `print` plus a commented-out loop. *(Verified: CONFIRMED.)*
**Why it's a flag:** Per-response disk write for no production purpose; vestigial method with dead comments.
**How to resolve:** Remove the `_save_resp` call (or gate it behind a debug flag) and delete the commented-out block in `_check_session` (or the method if it only prints). `resp.json` is already gitignored, so no tracked file to remove.
**Priority:** Medium-low.

---

## Low priority

### L1 — Raw f-string SQL inconsistent with the rest of the data layer
**Where:** [data_pipeline/song_pipeline/song_downloader.py:83-91](data_pipeline/song_pipeline/song_downloader.py#L83-L91)
**What:** `_get_albums_to_download` builds its query with an f-string interpolating `self.batch_limit`, while every query in `manager.py` uses parameterized `psycopg.sql` composition. *(Verified: CONFIRMED.)*
**Why it's a flag:** Inconsistent with the established safe pattern. `batch_limit` is a developer-set int (not user input), so this is a *consistency/tech-debt* note, not an injection finding (security was out of scope this pass).
**How to resolve:** Pass `batch_limit` as a bound parameter, matching `manager.py`.
**Priority:** Low.

### L2 — `practice/` scratch dir and `.reminders` tracked in git ✅ DONE (2026-06-12)
**Resolution:** `git rm --cached .reminders practice/test.py` (untracked, kept on disk per
decision) and added `practice/` + `.reminders` to `.gitignore`.
**Where:** `practice/test.py` (tracked), `.reminders` (tracked). *(Verified: PARTIALLY TRUE — `practice/resp.json` and `backend/agents/_p5b_runbook.log` are on disk but NOT tracked.)*
**What:** A scratch `test.py` and a personal `.reminders` file are committed to the repo.
**Why it's a flag:** Personal/scratch files in version control add noise and confuse contributors about what's load-bearing.
**How to resolve:** `git rm --cached` the scratch files (or delete `practice/` if truly unused) and add them to `.gitignore`. Confirm `practice/test.py` isn't a referenced fixture first.
**Priority:** Low.

### L3 — Stale agent/handoff/reference artifacts tracked
**Where:** `backend/agents/*-fix-plan.md` (completed-work plans, e.g. `s1`–`s6`, `p3-p4`, `p5-hnsw`), `frontend/agent-handoffs-FE/` (3 tracked), `frontend/reference/*.png` (~6 MB tracked)
**What:** Finished planning docs, agent handoff notes, and design-reference PNGs sit in the tree. *(Note: `backend/agents/_p5b_*` and `h1-*`/`p5b-*` plans are **WIP and excluded** from this audit per scope.)*
**Why it's a flag:** Completed-work scratch and multi-MB design PNGs clutter the repo; the PNGs also bloat clones.
**How to resolve:** Decide a home for "done" plan docs (archive folder, wiki, or delete). Consider moving reference images out of git or to LFS. Low urgency, and skip anything still in-flight.
**Priority:** Low.

### L4 — Profile page renders permanently-dead fields
**Where:** [frontend/src/components/profile-content.tsx:7-32](frontend/src/components/profile-content.tsx#L7-L32) and lines 158-159; backend [schemas/song.py](backend/app/schemas/song.py) `TopTrackItem`, [api/v1/songs.py:114](backend/app/api/v1/songs.py#L114)
**What:** `TopTrack` declares `duration_ms`/`popularity`, but the backend `top_tracks` endpoint builds items via `TopTrackItem.from_user_top_song` which never sets `duration_ms` → `formatDuration` always renders `"—:—"`. "Last sync" is hardcoded to `"Just now"`, and `load()` has a `data.items ?? data` fallback for response shapes the API doesn't return. *(Verified: CONFIRMED.)*
**Why it's a flag:** UI advertises data that never arrives; dead type fields and defensive fallbacks for nonexistent shapes mislead future work.
**How to resolve:** Either drop the duration column/`formatDuration` and the unused fields, or have the backend supply `duration_ms` (product call — confirm which before changing). Remove the hardcoded "Just now" or back it with a real timestamp.
**Priority:** Low (cosmetic/correctness-of-display, not a crash).

### L5 — Misspelling "succesfully"
**Where:** [data_pipeline/link_pipeline/crawler.py:116](data_pipeline/link_pipeline/crawler.py#L116), [data_pipeline/db/manager.py:342](data_pipeline/db/manager.py#L342) *(Verified: CONFIRMED.)*
**What:** "succesfully" → "successfully" in log strings.
**How to resolve:** Trivial text fix (folds into the H3 logging pass).
**Priority:** Low.

---

## Test fixes from Batch 1

Two test failures surfaced while applying the Batch-1 deletions. Both were expected
consequences, and both were fixed; the full `data_pipeline` suite is **172 passed**.

- **Crawler tests (caused by M6).** Removing `_save_resp` broke 5 tests in
  [test_bandcamp_crawler.py](data_pipeline/tests/link_pipeline/test_bandcamp_crawler.py):
  `TestSaveResp` tested the deleted method directly, and four `TestOnResponse` tests
  mocked it via `patch.object(crawler, '_save_resp')`. Fixed by deleting `TestSaveResp`,
  dropping the obsolete mock from the four `_on_response` tests (they still assert real
  behavior), and trimming the now-unused `patch`/`call` imports.

- **Pipeline integration tests (pre-existing, unrelated to Batch 1).** Three tests in
  [test_pipeline_integration.py](data_pipeline/tests/song_pipeline/test_pipeline_integration.py)
  were already failing on `372f5af` (verified before any change) with `len(rows) == 16`
  instead of 1/2. Root cause: the downloader loops until `_get_albums_to_download()`
  returns `[]`, but the tests mocked `execute_query` with a **static `return_value`**, so
  it never drained — the real query is `UPDATE...RETURNING`, which claims a batch once and
  then returns `[]`. The downloader looped forever, emitting full `batch_size=16` buffers.
  Fixed by making the mock drain (`execute_query.side_effect = [albums, []]`) in the three
  tests. Production code was correct; the mock was unrealistic. Side benefit: the suite
  dropped from ~3m41s to ~1.2s (those three were spinning until their 5s join timeouts).

---

## Suggested order of attack

1. ✅ **Low-risk deletions** (M2, M3, M6, L2) — **done** (commits `01335bd` + `5bcb92a`;
   test fixes above). Pure removals, verified with the `data_pipeline` test run.
2. **Mechanical refactors** (H1 single model load, M1/M5 dedupe, M4 validation helper) — behavior-preserving, test-backed. ← next
3. **The logging migration** (H3 + L5) — staged file-by-file.
4. **Decide policy** on H2 (LFS vs gitignore vs history purge) and L3/L1 — these need a judgment call, not a blind fix.
