# A5 — Per-download temp dir (kill the shared-downloads collision)

> **Status:** Plan for review (agent-checked before any edit).
> **Source item:** A5 in
> [backend-optimization-deferred.md](backend-optimization-deferred.md).
> **Branch:** `Backend-optimization`. **Date:** 2026-06-26.
> **Decision (from the user):** per-**download** temp dir (not per-job), placed
> **under `DOWNLOADS_DIR`**, with the file-finding glob scoped to that temp dir only
> (never the whole `DOWNLOADS_DIR`), and the temp dir cleaned up afterward.

## Problem

[`_download`](../app/services/spotify_ingest_service.py#L44) downloads every track into
one shared [`DOWNLOADS_DIR`](../app/services/spotify_ingest_service.py#L22) and
identifies "its" file by diffing the **entire** dir before/after the `spotdl` run
(`before = set(DOWNLOADS_DIR.rglob("*"))` → run → `rglob` again, keep what's new). Two
concurrent ingests — two `BackgroundTasks` runs of `process_top_tracks` for different
users (real today: two `get_recs` calls) — share that dir, so the diff can attribute
**another job's** file to this one. The whole-dir `rglob` also slows as the dir grows.

## Approach — `tempfile.mkdtemp` per download

Give each `_download` call its own empty temp dir under `DOWNLOADS_DIR`, point `spotdl
--output` at it, and find the audio file by globbing **only that dir**. Because it
starts empty, the before/after diff is gone — any audio file in it is unambiguously
ours. Cleanup removes the whole temp dir (also sweeping spotdl's stray artifacts, e.g.
lyrics/partials). Concurrent calls get distinct dirs (`mkdtemp` is atomic), so jobs
never collide.

### `_download` (rewritten)
```python
def _download(self, spotify_url: str) -> Path:
    job_dir = Path(tempfile.mkdtemp(prefix="ingest_", dir=DOWNLOADS_DIR))
    try:
        subprocess.run(
            ["spotdl", "--no-cache", "--format", "mp3", "--bitrate", "320k",
             "--client-id", os.getenv("SPOTIFY_CLIENT_ID"),
             "--client-secret", os.getenv("SPOTIFY_CLIENT_SECRET"),
             "--output", str(job_dir),
             spotify_url],
            check=True,
        )
        # Glob ONLY this download's temp dir (it started empty) — no whole-
        # DOWNLOADS_DIR diff. Any audio file here is unambiguously ours.
        audio_files = [
            f for f in job_dir.rglob("*")
            if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
        ]
        if not audio_files:
            raise FileNotFoundError(f"spotdl produced no audio file for {spotify_url}")
        return audio_files[0]
    except Exception:
        # Self-clean on failure: callers only _cleanup on a returned path, so a
        # failed download must not leak its temp dir.
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
```

### `_cleanup` (remove the temp dir, not just the file)
```python
def _cleanup(self, audio_path: Path) -> None:
    # Remove the per-download temp dir (the direct child of DOWNLOADS_DIR that
    # _download created), so spotdl's stray files go too. Guard hard against ever
    # rmtree-ing DOWNLOADS_DIR itself; fall back to file-only removal otherwise.
    try:
        top = DOWNLOADS_DIR / audio_path.relative_to(DOWNLOADS_DIR).parts[0]
        if top != DOWNLOADS_DIR and top.is_dir():
            shutil.rmtree(top, ignore_errors=True)
            return
    except (ValueError, IndexError):
        pass
    if audio_path.exists():
        os.remove(audio_path)
```
`relative_to(...).parts[0]` resolves to the top-level temp dir even if spotdl ever
nests, so the whole dir is removed; the `try`/guard means an unexpected path (not under
`DOWNLOADS_DIR`, or directly in it) degrades safely to removing just the file and never
touches `DOWNLOADS_DIR`.

### Imports
Add `import shutil` and `import tempfile` (neither is imported yet).

## Why this is safe — what doesn't break

- **Signatures unchanged.** `_download(self, spotify_url) -> Path` and
  `_cleanup(self, audio_path)` keep their shapes, so both callers — `ingest()`
  ([:34](../app/services/spotify_ingest_service.py#L34)) and `process_top_tracks`
  ([:153](../app/services/spotify_ingest_service.py#L153),
  [:187](../app/services/spotify_ingest_service.py#L187)) — work unchanged.
- **`ingest()` benefits for free** (the dead-but-present caller): the fix lives entirely
  in `_download`/`_cleanup`, so no separate handling.
- **Failure paths covered.** `process_top_tracks` wraps `_download` in
  `try/except: continue` with no dir cleanup of its own, and `ingest()` assigns
  `audio_path` outside its `try` — so neither cleans up a *failed* download. `_download`
  now self-cleans its temp dir on any failure, so nothing leaks.
- **`__init__` keeps `DOWNLOADS_DIR.mkdir(exist_ok=True)`** — still required as the base
  for `mkdtemp(dir=DOWNLOADS_DIR)`.
- **Concurrency-safe.** `tempfile.mkdtemp` atomically creates a unique dir, so parallel
  jobs never share — the whole point of A5.
- **Tests unaffected.** No test references `_download`, `_cleanup`, `DOWNLOADS_DIR`,
  `rglob`, or `mkdtemp`; `process_top_tracks` tests use the genre fast-path / mocked DB
  and never hit a real download, and `test_embed_guard` calls `_embed` directly. The
  unchanged signatures keep any higher-level mocks valid.

## Validation — new `tests/test_download_isolation.py`

Build the service the way `test_embed_guard` does (`SpotifyIngestService()` with
`__init__` no-op'd by the autouse `patch_startup`), and point the module's
`DOWNLOADS_DIR` at a pytest `tmp_path` via `monkeypatch` so nothing writes to the real
dir. Mock `subprocess.run` with a `side_effect` that parses `--output` from the args and
drops a fake `.mp3` into it.

- **happy path:** `_download` returns a `.mp3` that exists, lives in a temp dir that is a
  direct child of `DOWNLOADS_DIR` (not `DOWNLOADS_DIR` itself); `_cleanup` then removes
  that temp dir entirely.
- **isolation:** two `_download` calls return paths in **different** temp dirs.
- **no-audio failure:** `subprocess.run` creates nothing → `_download` raises
  `FileNotFoundError` **and** leaves **no** leftover temp dir under `DOWNLOADS_DIR`
  (self-clean verified).
- **glob scope:** a pre-existing stray file sitting directly in `DOWNLOADS_DIR` is
  **not** returned by `_download` (proves the glob is scoped to the temp dir, not the
  whole downloads dir).
- Then run the full backend suite — expect the prior **133** still green.

## Risk / rollback
- **Risk: low.** Self-contained in two methods; signatures and callers unchanged.
- **Disk:** temp dirs are removed per download (success via caller `_cleanup`, failure
  via `_download` self-clean), so nothing accumulates — strictly better than today.
- **Rollback:** revert the two methods + the two imports.

## Files changed
| File | Change |
|------|--------|
| [app/services/spotify_ingest_service.py](../app/services/spotify_ingest_service.py) | `_download` per-download `mkdtemp` + tmp-scoped glob + self-clean; `_cleanup` removes the temp dir; add `shutil`/`tempfile` imports |
| `tests/test_download_isolation.py` | **new** — happy path, isolation, no-audio self-clean, glob-scope |

## Out of scope (recorded)
- Per-**job** dir (one per `process_top_tracks` run) — rejected in favor of per-download
  (kills the diff, finer isolation, fixes `ingest()` for free).
- System `/tmp` instead of under `DOWNLOADS_DIR` — keep on the app-managed volume.
- A2's job queue (which would isolate jobs at a higher level anyway) — separate item.
