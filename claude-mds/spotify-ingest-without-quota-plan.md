# Spotify Ingest Without Quota Extension — Findings & Implementation Plan

**Date:** 2026-07-14 (identity model 2026-07-17; refined into ordered steps 2026-07-17)
**Branch:** `Backend-optimization`
**Status:** Plan finalized + agent-verified against the code (2026-07-17). **Sequenced
post-deploy:** the app launches as-is with Spotify OAuth, then this plan runs as
[deployment-gameplan **Phase 11**](deployment-gameplan.md) — the first workstream through
the live CI/CD pipeline. One step = one PR (plan + verify + implement + `pytest`), merged
through CI and auto-deployed.

## Locked decisions (from clarifying Q&A, 2026-07-17)

| Decision | Choice |
|----------|--------|
| **Sequencing** | **After the initial production deploy** — launch keeps Spotify OAuth (25-user cap accepted at cutover); this plan is deployment-gameplan **Phase 11**, the pipeline's first real workstream. |
| **Login paths** | Two only: **email + password** and **Sign in with Google**. Spotify is no longer a login path. |
| **One email, one path** | Email is the unique identity key. The cross-path error **names the correct method**: "An account with this email already exists. Continue with Google to sign in." / "…Sign in with your password." |
| **Passwords** | **argon2id hash** (one-way — *not* `EncryptedString`, never reversible). Policy: min 8 / max 128 chars, no composition rules. |
| **Email confirmation / password reset** | **Deferred** to a later phase (D). `email_verified` column ships now, gates nothing yet. |
| **Seed saves** | **Additive with a cap**: picks append to existing seeds (deduped by track), max **25 active seeds**. Current wipe-and-replace semantics retired. |
| **Spotify OAuth login** | **Disabled now, dormant** — routes off, button gone; `SpotifyAuthService` + token columns stay for a future "connect Spotify". Existing rows grandfathered as `auth_provider='spotify'`. |
| **Grandfathered Spotify users** | Re-enter via **Google auto-link**: a verified Google login whose email matches a `spotify` row links `google_id` onto that row and flips it to `google` (Spotify columns stay dormant). Without this they have no login path once their 30-day cookie expires. |
| **Seed source (core)** | **Search-and-pick** against the Spotify catalog (Client Credentials). Playlist import is an add-on **after** search ships (Phase C). |
| **Dedup** | Already built: seeds dedupe on `Song.spotify_track_id`; previously ingested tracks reuse embedding + genre with **no download** (see finding 3). |
| **Picks payload** | Frontend sends **track IDs only**; backend re-hydrates via `GET /v1/tracks?ids=` — never trust client-supplied metadata. |

## Problem

Spotify **denied extended-quota mode** for this app because the product aggregates
music across multiple services (an explicit Developer Policy incompatibility, not a
paperwork gap). That leaves the app in **development mode: hard cap of ~25 OAuth
users**. We need users to seed recommendations from their Spotify taste **without**
that cap, and **without** violating Spotify's ToS (no dev-app sharding, no scraping
internal `api-partner` endpoints with borrowed sessions, no credential harvesting).

## Key insight (the unlock)

**The 25-user cap only applies to the OAuth / Authorization Code flow (user-scoped
tokens).** The **Client Credentials flow** (app-level token, no user login) is **not
capped** and can hit all *public catalog* endpoints:

- `GET /v1/search?type=track` — search
- `GET /v1/tracks?ids=` — hydrate track metadata
- `GET /v1/playlists/{id}` — read **public** playlists

It **cannot** read `/me/top/tracks` (private, user-scoped). So we replace the one
capped call with catalog endpoints the user drives manually.

## Options considered

| Option | Verdict | Notes |
|--------|---------|-------|
| **Unofficial / internal API** | ❌ Reject | Still needs each user's live session token — doesn't escape the cap, and is fragile + bannable. |
| **Search-and-pick** (user searches, selects favorites) | ✅ **Primary** | Powered by Client Credentials → **uncapped**. Lowest friction, works day one for 100% of users. |
| **Public playlist link** (user pastes URL) | ✅ Secondary | `GET /playlists/{id}` via Client Credentials → uncapped. Playlist = curated taste, arguably *better* rec seed than top-tracks. |
| **Exportify-style CSV upload** | 🔵 Not planned | Works for private playlists; revisit only if users ask. |
| **Spotify GDPR "Download your data" upload** | 🔵 Not planned | True history but days of delivery lag — not an onboarding path. |
| **Last.fm / ListenBrainz** | 🔵 Alt backbone | Service-agnostic by design; best if we want a non-Spotify primary source later. |

## Codebase findings (verified against code 2026-07-17)

The current flow is: OAuth → [`get_top_tracks`](../backend/app/services/spotify_auth_service.py#L57) (`/me/top/tracks`)
→ [`add_user_top_songs`](../backend/app/services/spotify_ingest_service.py#L114) → background
[`process_top_tracks`](../backend/app/services/spotify_ingest_service.py#L140) →
[`query_recommendations`](../backend/app/services/spotify_ingest_service.py#L266).

1. **The download/embed path already uses Client Credentials.**
   [`_download`](../backend/app/services/spotify_ingest_service.py#L46) passes
   `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` to spotdl. The genre-classify → embed →
   recommend machinery was **never** the capped part.

2. **`add_user_top_songs` already consumes the exact shape `/search` and `/tracks` return**
   (`id`, `name`, `artists[0].name`, `album.images[0].url`, `album.name`,
   `external_urls.spotify`, `duration_ms`). No reshaping needed.

3. **Dedup across users already exists.** Seeds link to catalog rows by
   `Song.spotify_track_id` (unique). [`process_top_tracks`](../backend/app/services/spotify_ingest_service.py#L163)
   has a fast path: an existing `Song` with a genre is reused — **no download, no
   re-embed**. A track any user ever ingested is free for every later user. (Bandcamp
   catalog rows have `spotify_track_id = NULL`, so they neither collide nor match.)

4. **The session stack is already auth-agnostic.**
   [`create_session`](../backend/app/core/session.py#L19) signs the DB `user.id`;
   [`get_current_user`](../backend/app/core/dependencies.py#L7) looks up by id. Both stay
   untouched; every login path ends with `create_session(user.id)` + the same cookie
   flags as [`spotify_callback`](../backend/app/api/v1/auth.py#L64).

5. **Two Spotify couplings the earlier draft missed — both live in `get_recs`:**
   - [`songs.py:67`](../backend/app/api/v1/songs.py#L67) calls
     [`refresh_tokens`](../backend/app/services/spotify_auth_service.py#L104) on every
     request; its first line compares `user.token_expires_at > datetime.now()`, which
     **raises `TypeError` when the user has no Spotify tokens** (`None > datetime`).
   - The stale branch ([`songs.py:84-94`](../backend/app/api/v1/songs.py#L84)) fetches
     `/me/top/tracks` directly. Both must go (step A6).

6. **`add_user_top_songs` wipes the whole seed set** ([`:115`](../backend/app/services/spotify_ingest_service.py#L115)
   `delete()`) on every call — snapshot semantics that contradict the additive decision
   (step B3 changes this).

7. **`RecsResponse.status` is a free string** ([`schemas/song.py:8`](../backend/app/schemas/song.py#L8)),
   so the new `needs_seeds` status needs no schema migration.

---

## Implementation plan — ordered steps

> Work top to bottom. Each step is its own plan → agent-verify → implement → `pytest` →
> commit cycle. Phase B is the core deliverable; Phase C only starts after B works
> end-to-end.

### Phase A — Identity: login without Spotify

- [ ] **A1. Alembic migration: multi-provider `users` table.** *(M)*
  **How:** One migration on the current head (`b8c9d0e1f2a3`):
  - `spotify_id` → **nullable** (keep `unique`; Postgres allows multiple NULLs).
  - Add `google_id TEXT UNIQUE NULL` (Google's stable `sub` claim).
  - Add `password_hash TEXT NULL`.
  - Add `auth_provider` enum `email|google|spotify` — mirror the
    [`WorkStatus`](../backend/app/db/models.py#L11) pattern
    (`Enum(..., name="auth_provider_enum", create_type=False)`, type created in the
    migration) — with **`server_default='spotify'`** (covers the backfill *and* keeps
    [`upsert_user`](../backend/app/services/spotify_auth_service.py#L88), which doesn't
    set the column, working during the A1→A6 window).
  - Add `email_verified BOOLEAN NOT NULL DEFAULT false` (forward-compat for Phase D).
  - **Normalize emails to lowercase**: backfill `lower(email)` (assert no case-only
    duplicates first) and normalize at every boundary in app code. The existing unique
    constraint then enforces case-insensitive uniqueness de facto.
  - `email NOT NULL` is **deferred to A6's companion migration**: until Spotify signup
    is retired, `upsert_user` can still insert `email=None`
    ([`:91`](../backend/app/services/spotify_auth_service.py#L91)) and would violate it.
  **Why:** Today [`User.spotify_id`](../backend/app/db/models.py#L22) is `NOT NULL` — a
  row literally cannot exist without Spotify. Everything else in A/B builds on this row
  shape.
  **Coordination:** deployment-gameplan 1.2 re-roots the chain **pre-deploy**, so this
  migration lands post-deploy as the first link on the new chain — and the first live run
  of the pipeline's `alembic upgrade head` step (gameplan 8.3/11.1); snapshot RDS before
  merging it. Local dev DBs need `alembic upgrade head` —
  `create_all` won't add columns to existing tables, and with `create_type=False` it
  can't create `auth_provider_enum` on a brand-new DB either (same latent issue as
  `work_status_enum`; fresh DBs are alembic-only, which 1.2 makes official).

- [ ] **A2. Password hashing module.** *(S)*
  **How:** Add `argon2-cffi` to
  [`backend_requirements.txt`](../backend/backend_requirements.txt) (pinned). New
  `app/core/passwords.py`: `hash_password` / `verify_password` wrapping argon2id
  defaults. Policy enforced at the schema layer: 8–128 chars, no composition rules.
  Passwords never logged, never stored raw.
  **Why:** One-way KDF is the standard for credentials;
  [`EncryptedString`](../backend/app/db/types.py) is reversible by design (for API
  tokens) and must not be used here.

- [ ] **A3. One-path resolver (the crux).** *(S)*
  **How:** One helper used by register, password login, and the Google callback —
  `resolve_user(db, email, provider)`:
  - no row for the (normalized) email → caller may create one with `provider`;
  - row exists, same provider → return it (normal login / "already registered, sign in");
  - row exists, different provider → raise a typed error carrying which provider owns
    the email; the API layer renders the named-method message ("An account with this
    email already exists. Continue with Google to sign in." / "…Sign in with your
    password."). A `spotify`-owned email hit from **password** login/register says
    "This account was created with Spotify. Sign in with Google using the same email."
    (A5's auto-link is that user's re-entry path); a `spotify`-owned email hit from
    **Google** never errors — it auto-links (A5). UI copy stays human, no em-dashes.
  **Why:** Single enforcement point = no drift between three call sites. Known tradeoff:
  the message confirms an email is registered (account enumeration) — accepted for UX,
  standard for consumer apps.

- [ ] **A4. Email/password endpoints.** *(M)*
  **How:** In [`auth.py`](../backend/app/api/v1/auth.py):
  - `POST /auth/register` `{email, password}` → validate + normalize, one-path check
    (existing email-provider row → "already exists, sign in instead"), `hash_password`,
    insert `auth_provider='email'`, `email_verified=false`, `display_name=NULL` (A7
    adds an email-local-part fallback — today the frontend shows a generic "Listener"
    when it's null), then set the session cookie with the **same flags** as the Spotify
    callback and return JSON (fetch-based form, no redirect).
  - `POST /auth/login` `{email, password}` → lookup; wrong-provider → named-method
    message; missing user or bad password → the same generic "Invalid email or
    password" (don't reveal which); verify, set cookie.
  - `slowapi` limits: `5/minute` on both (IP-keyed — real client IPs arrive once
    deployment-gameplan 1.4/4.2 land `--proxy-headers` + forwarded headers).
  - Housekeeping in this step: extract a `set_session_cookie(response, user_id)` helper
    (A4 + A5 would otherwise be cookie-flag copies 3 and 4 of
    [`auth.py:65-72`](../backend/app/api/v1/auth.py#L65)); replace the dead
    Spotify-shaped [`schemas/user.py`](../backend/app/schemas/user.py) (imported
    nowhere) with the register/login schemas; pin **`email-validator`** in requirements
    (`EmailStr` needs it and it isn't installed today).
  **Why:** Mirrors the existing cookie contract exactly — [`/me`](../backend/app/api/v1/auth.py#L76),
  `logout`, and every authed route work unchanged.

- [ ] **A5. Google OAuth login.** *(M)*
  **How:** New `GoogleAuthService` mirroring
  [`SpotifyAuthService`](../backend/app/services/spotify_auth_service.py) (hand-rolled
  `httpx`, no new OAuth lib): auth `https://accounts.google.com/o/oauth2/v2/auth`
  (scopes `openid email profile`), token `https://oauth2.googleapis.com/token`, profile
  `https://openidconnect.googleapis.com/v1/userinfo` (`sub`, `email`, `email_verified`,
  `name`, `picture`). Routes in `auth.py`:
  - `GET /auth/google/login` → redirect with CSRF `state`, reusing the existing
    [`oauth_states`](../backend/app/api/v1/auth.py#L24) sweep + TTL verbatim.
  - `GET /auth/google/callback` → validate state, exchange code, fetch userinfo,
    **require Google's `email_verified=true`** (else redirect with an error), then:
    lookup by `google_id` first (stable even if the Google email changes; never
    overwrite our stored email on this branch); else match by email:
    `email`-provider row → redirect `FRONTEND_URL?error=use_password`;
    **`spotify`-provider row → auto-link** (set `google_id=sub`, flip
    `auth_provider='google'`, Spotify columns stay dormant) — this fixes the
    unique-email collision that would otherwise 500 *and* gives grandfathered Spotify
    users their only re-entry path after their cookie expires; no match → create
    (`auth_provider='google'`, `google_id=sub`, `display_name=name`,
    `email_verified=true`). Set cookie, redirect to the dashboard.
  - Config: `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` in
    [`.env.example`](../backend/.env.example) + `.env-backend`. One-time Google Cloud
    Console setup: OAuth web client + consent screen + both redirect URIs
    (`http://localhost:8000/api/v1/auth/google/callback`,
    `https://putyouon.app/api/v1/auth/google/callback`). No Spotify-style hard cap;
    >100 users eventually wants Google's verification review (cosmetic until then).
  **Why:** Google login mirrors a flow the codebase already implements once; `sub`-first
  lookup keeps identity stable; requiring `email_verified` stops one-path bypass via an
  unverified Google address claiming someone else's email.

- [ ] **A6. Retire Spotify login; fix `get_recs` for token-less users.** *(M — the test
  blast radius is large)*
  **How:** Remove the `/auth/spotify/login` + `/auth/spotify/callback` routes, and
  **delete the dead Next.js route
  [`frontend/src/app/api/auth/spotify/route.ts`](../frontend/src/app/api/auth/spotify/route.ts)**
  — it exchanges auth codes with `SPOTIFY_CLIENT_SECRET` in the *frontend* env and
  returns raw tokens to the browser; unused, and a standing leak risk. Service + token
  columns stay dormant for a future "connect". In
  [`get_recs`](../backend/app/api/v1/songs.py#L58): drop the
  [`refresh_tokens`](../backend/app/api/v1/songs.py#L67) call (crashes on
  `token_expires_at=None` — finding 5) and replace the stale branch's top-tracks fetch
  with `needs_seeds` — but **only when the user has zero *processed* seeds**. With ≥1
  processed seed, proceed to `query_recommendations` even if some picks are still
  unprocessed: reusing `snapshot_is_stale` unchanged would permanently wedge a user
  whose one un-downloadable pick can never process (spotdl failures leave `song_id`
  NULL forever). Companion migration: with Spotify signup retired, assert no NULL
  emails and set `email NOT NULL` (deferred from A1).
  **Why:** With no quota there is no auto-refetch; the app must *ask* for seeds instead
  of pulling them. This step makes every authed route provider-agnostic.
  **Tests:** a sweep, not a tweak — `test_songs.py` patches
  `app.api.v1.songs.auth_service` ~20 times, `test_auth.py`'s Spotify login/callback
  classes go, `test_rate_limiting.py` exercises the Spotify login limits.
  (`test_spotify_timeouts.py` survives; it tests the service directly, which stays.)

- [ ] **A7. Frontend: auth pages.** *(M)*
  **How:** Login/register page (email + password form with mode toggle, "Continue with
  Google" button pointed at `/api/v1/auth/google/login` — mirror
  [`spotify-login-button.tsx`](../frontend/src/components/spotify-login-button.tsx)).
  Replace **all three** Spotify entry points: the button component at
  [`page.tsx:83`](../frontend/src/app/page.tsx#L83), the raw CTA anchor at
  [`page.tsx:184`](../frontend/src/app/page.tsx#L184), and the raw link at
  [`navbar-component-01.tsx:73`](../frontend/src/components/shadcn-studio/blocks/navbar-component-01/navbar-component-01.tsx#L73).
  Update [`callback/page.tsx`](../frontend/src/app/callback/page.tsx) copy ("Signing
  you in with Spotify" — the Google redirect reuses this page). Give the dashboard a
  **minimal `needs_seeds` state now** — today the carousel would show "You're all
  caught up" to a seedless user, which is actively wrong; B5 replaces it with the real
  picker. Render the email local part where `display_name` is null (current fallback is
  a generic "Listener"). Surface API errors verbatim, including the named-method
  messages and `?error=use_password` on the callback return. Copy: human, no em-dashes.
  **Why:** The two paths need one obvious front door; the named-method error is the UX
  the one-path rule was chosen for.

- [ ] **A8. Tests (Phase A gate).** *(M)*
  **How:** `pytest` additions: register/login happy paths + cookie set; one-path
  rejections in both directions with exact messages; password policy bounds; Google
  callback (mock `httpx`) incl. unverified-email rejection and `sub`-first lookup;
  `get_recs` returns `needs_seeds` for a fresh email user (no `TypeError`);
  grandfathered `auth_provider='spotify'` row still logs in via session cookie.
  **Why:** Auth regressions are silent and expensive; the suite (127 passing) already
  covers the session contract — extend it before Phase B builds on top.

### Phase B — Search-and-pick seeding (the core)

- [ ] **B1. Client Credentials token manager.** *(S)*
  **How:** `get_app_token()` on `SpotifyAuthService`: POST `SPOTIFY_TOKEN_URL` with
  `grant_type=client_credentials` using the existing
  [`_auth_header`](../backend/app/services/spotify_auth_service.py#L27); cache token +
  expiry (+ an `asyncio.Lock`) at **module level in `spotify_auth_service.py`** — two
  module-level service instances exist ([`auth.py:15`](../backend/app/api/v1/auth.py#L15),
  [`songs.py:14`](../backend/app/api/v1/songs.py#L14)), so an instance attribute would
  mint two tokens, and `app.state` isn't reachable from a service method without
  plumbing `Request` through. Refresh ~60s before the 1h expiry.
  **Why:** App-level, uncapped; one token serves search, hydration, and playlists.

- [ ] **B2. Search endpoint.** *(S)*
  **How:** `GET /items/search?q=` → validate `q` (1–100 chars), proxy
  `GET /v1/search?type=track&limit=10` with the app token, return a slim schema
  (`id`, `name`, `artist`, `album`, `image_url`, `duration_ms`). Rate-limit
  `20/minute` with [`session_key`](../backend/app/core/limiter.py) (authed users).
  **Why:** Thin proxy keeps the client secret server-side and the response shape ours.

- [ ] **B3. Save-picks endpoint + additive seed semantics.** *(M)*
  **How:** `POST /items/picks` `{track_ids: [1–25 ids]}`:
  1. **Guard first:** `user.id in processing_users` → return `{"status": "processing"}`
     (the same guard [`get_recs`](../backend/app/api/v1/songs.py#L70) uses). Without it
     a double POST runs two concurrent pipelines: duplicate downloads,
     unique-violation races on `Song.spotify_track_id`, and two dispatch batches today
     (the `with_for_update` lock protects only the API path, not the background
     callback).
  2. Hydrate server-side via `GET /v1/tracks?ids=` (never trust client metadata).
     Harden: drop `null` entries (bogus ids return null) and tolerate empty
     `album.images` (the current `images[0]` pattern IndexErrors on artless albums).
  3. Rework [`add_user_top_songs`](../backend/app/services/spotify_ingest_service.py#L114)
     to **additive**: drop the `delete()`; skip ids already in the user's seed set;
     enforce the **25 active seed cap** (reject with a clear message if the request
     would exceed it; frontend shows remaining slots); **keep the insert-time linking
     of existing `Song` rows** (`song_id`/`genre` at
     [`:118-135`](../backend/app/services/spotify_ingest_service.py#L118)).
  4. Then exactly what the old stale branch did: `processing_users.add`, background
     [`_run_process_top_tracks`](../backend/app/api/v1/songs.py#L17) with
     `on_first_success=query_recommendations`, return `{"status": "processing"}` — the
     existing `/status` poll and dashboard flow take over unchanged.
  **Why:** Dedup (finding 3) makes repeat picks free; hydration-by-id closes the forged
  metadata hole; reusing the background pipeline means recs appear the same way they do
  today.
  **Tests:** `test_query_cleanups.py` calls `add_user_top_songs` directly and
  `test_songs.py`'s stale-branch trio dies with A6 — both are expected updates here; the
  mocked `db` needs explicit stubs for the new seed-count / existing-seed query chains
  (iterating an unstubbed MagicMock raises).

- [ ] **B4. Remove-a-seed endpoint.** *(S)*
  **How:** `DELETE /items/picks/{spotify_track_id}` → delete that `UserTopSong` row for
  the current user (the linked `Song` row stays — it serves other users and future
  re-picks). Two guards:
  - return `409` while `user.id in processing_users` — deleting a row the background
    run holds aborts its **unguarded fast-path commit**
    ([`spotify_ingest_service.py:167-171`](../backend/app/services/spotify_ingest_service.py#L167))
    with `StaleDataError`, killing the rest of the run;
  - add `"DELETE"` to `CORSMiddleware.allow_methods` in
    [`main.py:88`](../backend/app/main.py#L88) (currently `GET/POST/OPTIONS` — the
    browser preflight would refuse the call outright).
  **Why:** Additive + a hard cap of 25 without removal is a dead end at the cap. Smallest
  possible unblock.

- [ ] **B5. Frontend: picker + seed list.** *(M)*
  **How:** Dashboard picker (search box → results → add), shown prominently when
  `/song_recs/` returns `needs_seeds`; seed list from the existing
  [`/items/top_tracks/`](../backend/app/api/v1/songs.py#L100) endpoint (UI copy says
  "your seeds"; raise its `limit(10)` to the cap) with remove buttons; keep the
  status-poll → carousel flow as is. Sweep the leftover top-tracks copy:
  [`song-rec-carousel.tsx`](../frontend/src/components/song-rec-carousel.tsx) ("your
  top tracks") and
  [`profile-content.tsx`](../frontend/src/components/profile-content.tsx) ("Play a few
  songs on Spotify and this fills itself in").
  **Why:** This is the new onboarding moment — a user must get from empty account to
  first dispatch in one sitting.

- [ ] **B6. Tests (Phase B gate).** *(M)*
  **How:** Token manager caching/refresh (mock `httpx`); search proxy validation;
  picks: additive append, dedup against existing seeds, cap rejection at 25, hydration
  call; delete endpoint; end-to-end `needs_seeds` → picks → `processing` → dispatch
  (existing fixtures already fake the ingest service).
  **Why:** B3 rewires the one write path every rec depends on.

### Phase C — Public playlist import (add-on, only after B ships)

- [ ] **C1. Playlist endpoint.** *(M)*
  **How:** `POST /items/playlist` `{url}` → parse the id from
  `open.spotify.com/playlist/<id>` / `spotify:playlist:<id>`; fetch
  `GET /v1/playlists/{id}/tracks` with the app token (paginate; filter out `is_local`
  and null/episode items); feed the first N tracks that fit the user's remaining seed
  budget through the same additive B3 path. Private/404 → clear error ("Make sure the
  playlist is public.").
  **Why:** A curated playlist is arguably a better taste signal than top-tracks — and
  it's still the uncapped app token.

- [ ] **C2. Frontend: paste-a-playlist.** *(S)*
  **How:** Input + import button beside the picker; show which tracks were added vs
  skipped (cap/dedup).

- [ ] **C3. Tests.** *(S)* URL parsing forms, pagination, local-track filtering, cap
  interaction.

### Phase D — Deferred (unchanged from the earlier draft)

- **Email confirmation:** signed, TTL'd verification link (reuse the `itsdangerous`
  serializer behind sessions) to `/api/v1/auth/verify?token=`; flip `email_verified`
  and gate whatever needs it.
- **Password reset:** same token mechanism; natural companion item.
- **"Connect Spotify" revival** (optional, within the 25-user dev budget) if top-tracks
  import is ever wanted again.

---

## Cross-plan impacts ([deployment-gameplan.md](deployment-gameplan.md))

This plan **is the gameplan's Phase 11** (post-launch, pipeline shakedown). Sequencing
consequences:

- **Launch keeps Spotify OAuth:** gameplan 1.6 (Spotify redirect URI) and the 10.3
  Spotify smoke test stay **required at cutover**. Both retire when A6 deploys —
  gameplan 11.2 re-runs the smoke test with email + Google logins. After A6,
  `SPOTIFY_REDIRECT_URI` becomes dormant config; `SPOTIFY_CLIENT_ID/SECRET` stay
  (Client Credentials + spotdl need them).
- **SSM (5.1 pattern), when A5 ships:** add `GOOGLE_CLIENT_SECRET` (SecureString) and
  `GOOGLE_CLIENT_ID` / `GOOGLE_REDIRECT_URI` (String) under `/putyouon/prod/`; register
  the prod redirect URI in Google Cloud Console **before merging A5** — the next deploy
  materializes them with no other change (5.2).
- **Migrations:** 1.2's re-root lands pre-deploy; A1 then extends the new chain
  post-deploy as the first live run of the deploy's `alembic upgrade head` step (8.3) —
  snapshot RDS before merging it.
- **A→B gap:** between Phase A and B5's picker, new registrants see A7's minimal
  `needs_seeds` state; existing users are unaffected. Bundle A7 + B5 into adjacent
  merges if that gap matters (gameplan 11.3).

## Guardrails

- No dev-app sharding, no internal-endpoint scraping, no credential harvesting.
- Catalog search via Client Credentials is the least policy-sensitive Spotify use, but
  the aggregation policy still nominally governs any Spotify data — keep usage to public
  catalog/metadata and user-provided data.
- Never log passwords or password hashes; argon2id only; sessions stay `httponly` /
  `secure` / `samesite=lax`.
