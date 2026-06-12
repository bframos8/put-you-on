# H1 Fix Plan — Delete stale `app/models/models.py` duplicate (HOUSEKEEPING)

> Status: **Plan only — not yet implemented.**
> Source finding: flagged during the P5 investigation (2026-06-11).

## 1. The problem

[app/models/models.py](../app/models/models.py) is a **stale, orphaned duplicate**
of the real ORM models in [app/db/models.py](../app/db/models.py). It carries an
**outdated schema** that no longer matches the database:

- `Album` / `Song` have **no `genre` column**, `Song` has **no `is_candidate`**,
  and it uses a non-existent `Timestamp` type import (the real models use
  `DateTime`).
- Its `WorkStatus` enum uses the default `create_type` (the real one sets
  `create_type=False`).
- It defines only a subset of tables (`Artist`, `Album`, `Song`, …) and is
  generally a snapshot from an earlier point in the project.

### Why it is safe to delete (verified)
- **Imported nowhere.** `grep` across `app/`, `tests/`, and `alembic/` finds no
  `app.models.models`, `from ..models`, or any import referencing it.
- **`app/models/` is not a Python package** — there is no `__init__.py`. The
  directory exists only to hold the ML graph/labels files
  (`discogs-effnet-bs64-1.pb`, `discogs-effnet-bs64-1.json`), which are loaded by
  **path**, not import
  ([spotify_ingest_service.py:21](../app/services/spotify_ingest_service.py#L21),
  [audio_genre_classifier.py:9-10](../app/services/audio_genre_classifier.py#L9)).
  So `models.py` here cannot even be imported as `app.models.models`.
- Alembic does **not** import it (migrations are hand-written; the enum's
  `create_type=False` lives in the real `db/models.py`).

### Why it is worth deleting
- It's a **landmine**: a future reader who opens it could mistake it for the live
  schema (it omits `genre`/`is_candidate`, the columns the rec engine depends on).
- Dead code with a divergent schema is exactly the kind of thing that misleads
  during onboarding or an AI-assisted edit.

## 2. The fix

Delete the single file:

```bash
git rm backend/app/models/models.py
```

- Leave the `app/models/` directory and its `.pb` / `.json` ML assets untouched —
  those are load-bearing.
- No code changes, no import updates (nothing imports it), no test changes.

## 3. Validation

```bash
cd backend && grep -rn "models\.models\|app\.models\b" app tests alembic   # expect no hits
cd backend && pytest                                                       # full suite stays green
```

A clean `grep` + green suite confirms nothing depended on it.

## 4. Files changed

| File | Change |
| --- | --- |
| `backend/app/models/models.py` | **Deleted** (stale duplicate of `app/db/models.py`). |

## 5. Out of scope
- The real models in [app/db/models.py](../app/db/models.py) — unchanged.
- The ML assets in `app/models/` — unchanged.
