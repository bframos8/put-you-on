# Backend Optimization — COMPLETED

> **Source of truth for finished work.** Split out of
> [.claude-backend-optimization.md](.claude-backend-optimization.md) on 2026-06-23
> so each stage has one authoritative file. Companions:
> [backend-optimization-deferred.md](backend-optimization-deferred.md) and
> [backend-optimization-remaining.md](backend-optimization-remaining.md).
>
> Every item here was verified against the code and/or the live RDS, not just the
> plan notes. Corrections applied during the split are called out under
> **Corrections** at the bottom.

---

## Security (Tier 1) — all done 2026-06-10

Shipped in `372f5af` ("Security hardening, timeouts, and query cleanups"). Each has
a per-item fix-plan retained for detail.

| Item | What | Plan |
|------|------|------|
| **S1** | Removed hardcoded `SESSION_SECRET` default; fail-fast at import if missing | [s1-session-secret-fix-plan.md](s1-session-secret-fix-plan.md) |
| **S2** | Removed cookie `print` + `traceback.print_exc()` token/PII leaks | [s2-debug-logging-leak-fix-plan.md](s2-debug-logging-leak-fix-plan.md) |
| **S3** | CORS driven by `CORS_ALLOWED_ORIGINS` (real port), tightened methods/headers | [s3-cors-origin-fix-plan.md](s3-cors-origin-fix-plan.md) |
| **S4** | Explicit `SPOTIFY_HTTP_TIMEOUT` (10s) on all outbound Spotify clients | [s4-spotify-timeouts-fix-plan.md](s4-spotify-timeouts-fix-plan.md) |
| **S5** | OAuth `state` TTL via `OAUTH_STATE_TTL_SECONDS` (600s) + login sweep | [s5-oauth-state-ttl-fix-plan.md](s5-oauth-state-ttl-fix-plan.md) |
| **S6** | Baseline security headers + gated HSTS via pure-ASGI middleware | [s6-security-headers-fix-plan.md](s6-security-headers-fix-plan.md) |

🎉 **All Tier-1 security items (S1–S6) complete.**

---

## Performance (Tier 1)

| Item | What | When / commit | Plan |
|------|------|---------------|------|
| **P3** | `selectinload` eager-loads on dispatch/recs (kills N+1 on `Song.album`) | 2026-06-11, `372f5af` | [p3-p4-query-cleanups-fix-plan.md](p3-p4-query-cleanups-fix-plan.md) |
| **P4** | Batched `Song.spotify_track_id.in_(...)` lookups in top-song ingest | 2026-06-11, `372f5af` | [p3-p4-query-cleanups-fix-plan.md](p3-p4-query-cleanups-fix-plan.md) |
| **P5a** | `hnsw.ef_search` scoped to `2*pool_size` per query (fallback recall 39 → 50) | 2026-06-12, `01335bd`/`5bcb92a` | [p5-hnsw-tuning-fix-plan.md](p5-hnsw-tuning-fix-plan.md) |

---

## P5b (genre denormalization) — DONE PORTION

P5b is partially complete. The data + schema half is **done and confirmed on live
RDS**; the index rebuild + query change are the only things left and live in
[backend-optimization-remaining.md](backend-optimization-remaining.md).

**Confirmed done on live RDS (`pyo_db`, verified 2026-06-23):**
- ✅ `songs.genre` backfilled from `albums.genre` for all **110,833** candidates.
- ✅ `VACUUM (ANALYZE) songs` run.
- ✅ **Sync trigger `songs_fill_genre` installed** — `SELECT tgname FROM pg_trigger …`
  returns `songs_fill_genre`. The trigger migration
  [f6a2b3c4d5e6](../alembic/versions/f6a2b3c4d5e6_denormalize_song_genre.py) ran as a
  side effect of `alembic upgrade head` during the L4(a) work; `alembic_version` =
  **`a7b8c9d0e1f2`** (head). New scraper candidates now self-populate `songs.genre`.

Full plan + measurement history:
[p5b-genre-denormalization-plan.md](p5b-genre-denormalization-plan.md).

---

## Housekeeping — Batch 1 (low-risk deletions), done 2026-06-12

Commits `01335bd`, `5bcb92a`, `7768256`. Source audit:
[../../claude-mds/housekeeping-audit.md](../../claude-mds/housekeeping-audit.md).

| Item | What |
|------|------|
| **M2** | Deleted dead "legacy" `Song` dataclass + its self-referential test |
| **M3** | Deleted 2 orphan frontend UI components (~369 dead lines) |
| **M6** | Removed `_save_resp` per-response disk write + dead crawler comments |
| **L2** | `git rm --cached` scratch `practice/` + `.reminders`, gitignored them |
| **H1** | Deleted stale `app/models/models.py` duplicate (see Corrections) |

---

## Housekeeping — Batch 2 (mechanical refactors + L4), done 2026-06-15

Source plan: [../../claude-mds/optimization-plan.md](../../claude-mds/optimization-plan.md).

| Item | What | Commit |
|------|------|--------|
| **M5** | `AUDIO_EXTENSIONS` promoted to a module constant in the pipeline | `2378b09` |
| **M4** | Two `DatabaseManager` validation helpers (single-row + batch) | `2378b09` |
| **M1** | Backend `_embed` empty-frame guard mirrors the pipeline contract | `05a125b` |
| **L4(a)** | `duration_ms` wired end-to-end (migration `a7b8c9d0e1f2` + ingest + schema) | `fe00c5b` |
| **L4(b)** | Real "Last sync" timestamp from `snapshot_at` (absolute date/time) | `d31fa00` |
| **L4(c)** | Dropped dead `data.items ?? data` response-shape fallback | `d31fa00` |

**Open caveats carried forward (non-blocking):**
- Existing `user_top_songs` rows show `"—:—"` / stale duration until the next sync
  rebuilds the snapshot.
- `snapshot_at` is a naive `datetime.now()`, so "Last sync" can skew across
  timezones. tz-aware UTC is a future follow-up.

---

## Corrections applied during the 2026-06-23 split

These fixed contradictions between the older docs so each stage now has one truth:

1. **H1 is DONE, not "planned."** The master doc still read
   "📋 H1 PLANNED — delete stale `app/models/models.py`," but that file was actually
   deleted in `01335bd` (folded silently into the Batch-1 deletions). It is gone and
   untracked. The leftover [h1-stale-models-file-cleanup-plan.md](h1-stale-models-file-cleanup-plan.md)
   is obsolete. ⚠️ Naming note: this optimization-doc "H1" (delete `models.py`) is a
   **different item** from the housekeeping-audit "H1" (double TF model load), which
   maps to **P1/P2** in [backend-optimization-deferred.md](backend-optimization-deferred.md).
2. **P5b's sync trigger IS installed.** The P5b plan §0 (written before the L4(a)
   upgrade) said the trigger was never applied. Live RDS confirms otherwise
   (`songs_fill_genre` present; DB at head `a7b8c9d0e1f2`). The only remaining P5b
   work is the index rebuild + query change.
