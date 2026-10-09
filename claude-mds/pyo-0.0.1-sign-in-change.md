# Put You On 0.0.1 — Sign-in Change

**Product version 0.0.1.** The first release after the production deployment. Replace the
Spotify login with **email + password** and **Sign in with Google**, and let people seed
their recommendations by **searching for songs and picking them**, instead of reading
their Spotify top tracks. That removes the Spotify developer-mode user cap, which is the
only thing stopping new signups today.

**Status:** in progress. Re-verified against the code and against Spotify's and Google's
current docs on 2026-10-02, with two verification agents (one on the codebase, one on the
external APIs). The checkboxes below track what has landed; each ticked item carries a
dated note.

**Where this came from.** This file merges two earlier documents:
- [spotify-ingest-without-quota-plan.md](completed/spotify-ingest-without-quota-plan.md)
  (2026-07-17): the design, decisions and phased steps. Now superseded by this file and
  kept for its options analysis.
- Phase 11 of [deployment-gameplan.md](completed/deployment-gameplan.md): the delivery
  checklist. Its 11.x numbers map onto this file as follows, so older references still
  resolve:

| Old reference | Now |
|---|---|
| 11.1 (ship Phase A, identity) | [Phase A](#phase-a--identity-backend-no-visible-change) and [C1](#phase-c--the-release-frontend) |
| 11.2 (retire Spotify login, smoke test, the deferred new-account worker test) | [Phase D](#phase-d--retire-the-spotify-login) |
| 11.3 (search-and-pick, playlist import) | [Phase B](#phase-b--seeding-backend-no-visible-change) and [C2](#phase-c--the-release-frontend). Playlist import is dropped (see [Not in 0.0.1](#not-in-001)) |
| 11.4 (turn the worker on) | Done 2026-10-02. See [Already done](#already-done-formerly-114) |
| 11.5 (worker on the Mac mini) | Moved to [deployment-deferred.md](deployment-deferred.md) |

Lessons from getting the deployment this far are in
[deployment-learnings.md](completed/deployment-learnings.md). Follow-ups outside this
release are in [deployment-deferred.md](deployment-deferred.md).

---

## Decisions

From the original Q&A (2026-07-17), updated where 2026-10-02's checks changed them.

| Decision | Choice |
|---|---|
| **Login paths** | Two: **email + password** and **Sign in with Google**. Spotify stops being a login path. |
| **One email, one path** | Email is the identity key. A cross-path attempt gets an error that **names the right method**: "An account with this email already exists. Continue with Google to sign in." / "...Sign in with your password." |
| **Passwords** | **argon2id** (one-way; never `EncryptedString`, which is reversible by design). 8 to 128 characters, no composition rules. |
| **Password reset and email confirmation** | **Not in 0.0.1** (decided again 2026-10-02). `email_verified` ships now and gates nothing. Until reset exists, a forgotten password is handled by a manual runbook procedure (E2). |
| **Grandfathered Spotify users** | Re-enter through **Google auto-link**: a verified Google login whose email matches a `spotify` row links onto it. Without this they have no way back in once their 30-day cookie expires. |
| **Spotify OAuth** | Login routes removed (Phase D). `SpotifyAuthService` and the token columns stay dormant for a possible future "connect Spotify". |
| **Seed source** | **Search-and-pick against Spotify's catalog**, using the Client Credentials flow (decided again 2026-10-02, with the policy risk below accepted). |
| **Picks** | **Additive, one track at a time, capped at 25 seeds per user.** Picks append; the old snapshot-sync semantics only remain for grandfathered users until Phase D. The client sends a **track id only**; the server fetches the metadata itself. |
| **Ingest** | **Worker-only for new code** (decided 2026-10-02). New endpoints only write `user_top_songs` rows; the worker claims them. The in-process path is left alone and is not extended. Local dev runs the worker against localhost with `INGEST_WORKER_ENABLED=true`. |
| **Playlist import** | **Dropped** (2026-10-02). Spotify no longer lets an app read a playlist the user doesn't own, and Client Credentials has no user. |
| **Folded in from deferred** | Per-user dispatch cache (C3) and account deletion (Phase E). |

---

## Why this works, and what changed since July

### The cap, and the way around it

Spotify refused extended quota mode because Put You On combines Spotify data with another
service (Bandcamp). That leaves the app in **development mode**, which caps how many
people can log in with Spotify OAuth. The cap only applies to **user** logins. The
**Client Credentials flow** (an app-level token, no user) has no user cap and can still
reach the public catalog. So: stop asking Spotify who the user is (our own accounts do
that), and stop reading their top tracks (they pick songs instead).

Options considered in July, kept for the record: unofficial/internal APIs (rejected:
still need each user's session, and bannable), search-and-pick (chosen), public playlist
link (chosen then, now dead, see below), Exportify CSV and Spotify's data export (not
planned), Last.fm / ListenBrainz (a possible non-Spotify backbone later).

### Spotify's 2026 changes (checked 2026-10-02)

- **February 2026: development mode got stricter.** From 2026-02-11 for new Client IDs,
  and 2026-03-09 for existing ones: the app owner needs **Spotify Premium**, new apps are
  capped at 5 users, and fewer endpoints are available. On 2026-03-09 Spotify postponed
  the *endpoint* changes for existing apps, with no new date; the Premium requirement
  went ahead. Sources:
  [blog 2026-02-06](https://developer.spotify.com/blog/2026-02-06-update-on-developer-access-and-platform-security),
  [migration guide](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide),
  [quota modes](https://developer.spotify.com/documentation/web-api/concepts/quota-modes).
- **Get Several Tracks (`GET /v1/tracks?ids=`) is removed for development mode.** The
  July plan hydrated picks in one batch call. Now it is one `GET /v1/tracks/{id}` per
  pick, which is why picks are added one at a time (B3).
- **Search is capped at `limit=10`** (default 5). The search endpoint asks for 10.
- **Reading a playlist's items is limited to playlists the current user owns or
  collaborates on** (the endpoint is also renamed to `/playlists/{id}/items`). A Client
  Credentials token has no current user, so public playlist import would 403. Dropped.
- **Track fields removed:** `popularity`, `available_markets`, `linked_from`. Nothing
  here reads them. Title, artists, album images and `external_urls` are unchanged.
- **Quota.** Development-mode quotas are shared across all of a developer's Client IDs.
  Going over returns 429 with `"reason": "QUOTA_EXCEEDED"`; the window isn't documented.
  Every search and every pick costs one call.
- **spotdl** stopped using the official API by default in 4.5.0 (2026-05-16). The
  worker's downloads were proven on 2026-10-02 with 4.5.2, so this changes nothing today,
  but it means the worker's Spotify credentials may not be what makes downloads work.

### Accepted risk: Spotify's Developer Policy

Policy **III.5** ("Do not create any product or service which is integrated with streams
or content from another service") applies however the app authenticates, so
search-and-pick does not take Put You On out of scope; it is the same reason extended
quota was refused. Also relevant: **II.4** (Spotify metadata and artwork must carry
attribution and a link back to Spotify), **IV.3** of the Terms (only temporary caching of
metadata and artwork; no "databases of Spotify Content"), and **IV.2.b** (no facilitating
stream ripping). Sources: [policy](https://developer.spotify.com/policy),
[terms](https://developer.spotify.com/terms),
[design guidelines](https://developer.spotify.com/documentation/design).

**Decision (2026-10-02): keep Spotify search for 0.0.1 and accept the risk.** The
current app already carries it. If Spotify revokes the Client ID, search and picks stop
working (existing seeds and recommendations keep working). The way out is a non-Spotify
catalog (see [Not in 0.0.1](#not-in-001)). What 0.0.1 does to stay on the right side of
what it can control: attribution and a "Listen on Spotify" link wherever Spotify artwork
or metadata is shown (C2), and no new Spotify data stored beyond what a seed needs.

---

## Before the first PR

- [x] **P1. Confirm the Spotify account that owns the app has Premium.**
  > **Confirmed 2026-10-07: the owning account has Premium.** The app is bound to 5
  > users under the 2026 development-mode rules, which stops mattering once Phase D
  > retires the Spotify login.
  Since 2026-03-09 a development-mode app whose owner lacks Premium returns 403 ("Active
  premium subscription required for the owner of the app") on every call. Everything in
  Phase B depends on it, so if the subscription ever lapses, search and picks stop.
- [ ] **P2. Google Cloud setup** (needed before A6 merges; can be done any time).
  Create an OAuth client of type "Web application" and an OAuth consent screen with
  only the `openid`, `email` and `profile` scopes. Register both redirect URIs:
  `http://localhost:8000/api/v1/auth/google/callback` and
  `https://putyouon.app/api/v1/auth/google/callback` (localhost is allowed over http).
  With only those scopes the app can be set to **In production** with no test-user list,
  no warning screen and no app verification. **Brand verification** (your name and logo
  on the consent screen instead of just the domain) is optional and needs the domain
  verified in Search Console, a homepage and a privacy policy. Sources:
  [app audience](https://support.google.com/cloud/answer/15549945),
  [brand verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification).
- [ ] **P3. Seed the Google parameters in SSM**, one at a time, never by re-running
  `ssm-seed.sh` (`deploy/prod.env` has drifted from SSM; see
  [deployment-learnings.md §19](completed/deployment-learnings.md)):
  ```sh
  aws ssm put-parameter --name /putyouon/prod/GOOGLE_CLIENT_ID --type String --value '...'
  aws ssm put-parameter --name /putyouon/prod/GOOGLE_REDIRECT_URI --type String \
    --value 'https://putyouon.app/api/v1/auth/google/callback'
  aws ssm put-parameter --name /putyouon/prod/GOOGLE_CLIENT_SECRET --type SecureString --value '...'
  ```
  `materialize-env.sh` routes them to `.env-backend` with no change. The next deploy (or a
  `gh run rerun` of the last Deploy) picks them up.
- [ ] **P4. The worker is running.** True today on the MacBook. Every new seed waits for
  it, so if it's off, new users sit on "processing".

---

## How it ships

One item, one PR: plan, implement, `pytest`, merge, auto-deploy. Each PR carries its own
tests. The order is chosen so that **nothing a user can see changes until the release
(Phase C)**, and nothing in production ever reaches a state that 500s:

1. **Phase A** (identity, backend only) and **Phase B** (seeding, backend only) deploy
   with no visible change. Email and Google endpoints exist but nothing links to them.
2. **Phase C** is the release: the new front door, the picker and the per-user cache,
   merged together in one sitting.
3. **Phase D** retires the Spotify login and runs the live smoke test.
4. **Phase E** adds account deletion.

**Two migrations, two snapshots.** A1 and D2 change the schema. Take an RDS snapshot
before merging each (`aws rds create-db-snapshot`). Both are **hand-written**: the live
database's constraint names differ from the models (`songs_album_id_title_key` and
`albums_url_key` live, `uq_*` in the models), so `--autogenerate` would slip in a drop
and re-add of both. See deployment-gameplan 10.1.

### What the seed statuses mean after 0.0.1

`/song_recs/` and `/status` both answer from the database:

| User's seeds | Status | What the dashboard shows |
|---|---|---|
| None at all | `needs_seeds` (new) | The picker |
| Some waiting for the worker, none usable yet | `processing` | The spinner, polling `/status` |
| At least one usable | `ready` | Today's drop (from `/song_recs/`) |
| Some exist, none usable, none still waiting (all failed) | `no_seeds` | "We couldn't process these songs", and the picker |

Today `/status` answers `processing` for a user with **zero** seeds, forever. That is
harmless now only because every user arrives with Spotify top tracks. It becomes a
permanent spinner the moment seeds stop arriving on their own, which is why A4 comes
before any new kind of account.

---

## Phase A — Identity backend (no visible change)

- [x] **A0. Delete the dead Next.js Spotify token route.** *(S)*
  > **Done 2026-10-09 (PR #31).** Measured before the change: host-run `npm run dev`
  > answered a POST with 500 "Missing Spotify credentials", and production answered with
  > FastAPI's 404, so in practice only host dev could reach it. After: 404 from Next in
  > host dev, and the build no longer lists the route.
  **How:** Delete `frontend/src/app/api/auth/spotify/route.ts`. It exchanges auth codes
  with `SPOTIFY_CLIENT_SECRET` from the frontend environment and returns raw tokens to
  the browser. Nothing calls it, and in production nginx sends `/api/` to the backend so
  it's shadowed, but it is a standing leak if either of those ever changes.
  **Why:** Zero-risk, and it should not wait for the rest.

- [ ] **A1. Migration: multi-provider `users`, unique seeds.** *(M)*
  **How:** One hand-written migration, `down_revision = 'd4e5f6a7b8c9'` (the current
  head; the July plan's `45f91add221e` is two revisions old).
  - `users.spotify_id` becomes nullable. It stays unique (Postgres allows many NULLs).
  - Add `google_id TEXT NULL` with a **named** unique constraint, `uq_users_google_id`.
  - Add `password_hash TEXT NULL`.
  - Add `auth_provider` as an enum `email | google | spotify`, `server_default
    'spotify'`. The default covers every existing row, and keeps `upsert_user` working
    until Phase D without having to set it. **Create the type explicitly** with
    `sa.Enum(..., name="auth_provider_enum").create(bind, checkfirst=True)` before the
    `add_column`, and drop it in `downgrade`. The July plan said to mirror
    `work_status_enum`, but that type only exists because `op.create_table` creates it
    implicitly; `op.add_column` does not. In the model, use `create_type=False`.
  - Add `email_verified BOOLEAN NOT NULL DEFAULT false`.
  - Lowercase existing emails. Check first that no two rows differ only by case (raise if
    they do), then `UPDATE users SET email = lower(email)`. App code normalizes at every
    boundary from here on, so the existing unique constraint (`users_email_key`)
    becomes case-insensitive in practice.
  - Add a unique constraint on `user_top_songs (user_id, spotify_track_id)`, named
    `uq_user_top_songs_user_track`, after checking for existing duplicates. Today
    nothing stops the same track being added twice for a user; with picks, a double
    click or two tabs would.
  - `email NOT NULL` is **not** set here. Until Phase D, Spotify signup can still
    insert `email = None`. That's D2.
  Verify the way 10.5 and 10.6 did: on a scratch pgvector database **with rows already
  in both tables**, `upgrade`, `alembic check` (expect only the two known name
  differences), `downgrade -1`, `upgrade`. Mount the new migration file into the
  container; `docker compose run backend` alone runs the deployed image, which doesn't
  have it.
  **Why:** Today a user row cannot exist without a Spotify id. Everything else builds on
  this.

- [ ] **A2. Password hashing.** *(S)*
  **How:** Pin `argon2-cffi==25.1.0` and `email-validator==2.3.0` in
  `backend/backend_requirements.txt`. `email-validator` is installed in the local venv
  but not in the image, so `EmailStr` would pass tests locally and fail in production;
  pinning closes that. New `app/core/passwords.py` with `hash_password` /
  `verify_password` around argon2-cffi's `PasswordHasher` defaults (argon2id, RFC 9106
  low-memory profile, 64 MiB). Also `needs_rehash` on successful login, so the
  parameters can be raised later without forcing resets. Policy at the schema layer:
  8–128 characters. Never log a password or a hash.
  **Why:** A one-way KDF is the standard for credentials.

- [ ] **A3. The one-path resolver.** *(S)*
  **How:** `resolve_user(db, email, provider)`, used by register, password login and the
  Google callback:
  - no row for the normalized email: the caller may create one;
  - a row with the same provider: return it;
  - a row with a different provider: raise a typed error carrying the owning provider.
    The API layer turns it into the named-method message. A `spotify` row hit from
    password login or register says "This account was created with Spotify. Sign in with
    Google using the same email." A `spotify` row hit from **Google** never errors; it
    auto-links (A6).
  **Why:** One enforcement point instead of three call sites drifting. Known tradeoff:
  the message confirms an email is registered. Accepted for usability, as most consumer
  apps do.

- [ ] **A4. Make `get_recs` and `/status` work for a user with no Spotify tokens.** *(M)*
  **How:** This must deploy **before** A5 and A6. An email or Google user hitting
  `/song_recs/` today gets a 500, because `refresh_tokens` runs on every request and
  compares `token_expires_at` (None) with a datetime.
  - Move `refresh_tokens` inside the only branch that needs a Spotify token: fetching
    top tracks for a grandfathered user with zero seeds. Today it runs on every request,
    including every locked-dispatch replay.
  - Zero seed rows: a user **with** Spotify tokens keeps today's behaviour (fetch top
    tracks, queue them). A user **without** gets `needs_seeds`. A Spotify user whose top
    tracks come back empty also gets `needs_seeds` instead of today's endless
    "processing".
  - `/status`: zero seed rows answers `needs_seeds`, not `processing`.
  - The in-process branch is untouched and only reachable for grandfathered users with
    the flag off.
  - Fix the stale comment in `schemas/song.py` that says the frontend doesn't handle
    `no_seeds` (it does).
  - **Tests:** a tokenless user gets `needs_seeds` from both endpoints with no
    `TypeError`; a token user with zero seeds still fetches; a locked dispatch replays
    without calling `refresh_tokens`.
  **Why:** With seeds no longer fetched automatically, the app has to ask for them.

- [ ] **A5. Email + password endpoints.** *(M)*
  **How:** In `api/v1/auth.py`:
  - First, extract a `set_session_cookie(response, user_id)` helper from the Spotify
    callback's cookie block (httponly, secure, samesite=lax, 30 days). A5, A6 and the
    Spotify callback all use it, rather than three copies of the flags.
  - Replace the dead `schemas/user.py` (imported nowhere) with `RegisterRequest` /
    `LoginRequest` (`EmailStr`, password 8–128).
  - `POST /auth/register {email, password}`: normalize, resolve (an existing `email` row
    gets "An account with this email already exists. Sign in instead."), hash, insert
    `auth_provider='email'`, `email_verified=false`, `display_name=NULL`, set the
    cookie, return JSON.
  - `POST /auth/login {email, password}`: wrong provider gets the named-method message;
    a missing user and a wrong password get the same "Invalid email or password". Hash
    something even when the user is missing, so response time doesn't reveal which.
    Rehash if `needs_rehash`.
  - `slowapi` at `5/minute` on both, keyed by IP. **Known weakness:** the client IP can
    currently be spoofed through `X-Forwarded-For`, so this limit is weaker than it
    looks until the nginx fix in [deployment-deferred.md](deployment-deferred.md) lands.
    argon2's cost is the real brake on guessing.
  - CSRF: none needed beyond what exists. The cookie is SameSite=Lax, and these
    endpoints only accept JSON, which a cross-site form can't send without a CORS
    preflight that fails.
  - **Tests:** happy paths set the cookie; wrong provider in both directions with the
    exact messages; password bounds; the same message for unknown user and wrong
    password; the session works on `/auth/me` and `/song_recs/` (returns `needs_seeds`).
  **Why:** Same cookie contract as today, so `/auth/me`, logout and every authed route
  work unchanged.

- [ ] **A6. Google sign-in.** *(M)* Needs P2 and P3 first.
  **How:** `GoogleAuthService` mirroring `SpotifyAuthService` (hand-rolled `httpx`, no
  OAuth library). Authorize at `https://accounts.google.com/o/oauth2/v2/auth` with
  `openid email profile`; exchange at `https://oauth2.googleapis.com/token`.
  - **Read identity from the ID token** that comes back from the token endpoint, not from
    the userinfo endpoint. Google says an ID token received directly from its token
    endpoint over HTTPS can be trusted without verifying the signature; check `iss` is
    `https://accounts.google.com` or `accounts.google.com` and `aud` is our client id.
    That saves a round trip and a dependency.
    ([OIDC guide](https://developers.google.com/identity/openid-connect/openid-connect))
  - `GET /auth/google/login`: redirect with a CSRF `state`, reusing `oauth_states` and its
    TTL sweep exactly as the Spotify login does.
  - `GET /auth/google/callback`: validate state, exchange the code, **require
    `email_verified=true`** (else redirect with `?error=google_unverified`). Then:
    look up by `google_id` (`sub`) first, which survives the person changing their
    Google email, and never overwrite our stored email on that branch. Otherwise match by
    email:
    - an `email` row: redirect with `?error=use_password`;
    - a `spotify` row: **auto-link** (set `google_id`, `auth_provider='google'`,
      `email_verified=true`; Spotify columns stay dormant). This is how the two existing
      users get back in;
    - no row: create (`auth_provider='google'`, `google_id`, `display_name` from `name`,
      `email_verified=true`).
    Set the cookie and redirect to `FRONTEND_URL`.
  - Config: `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` in
    `backend/.env.example`, `deploy/prod.env.example`, `deploy/ssm-parameters.md`, the
    `ssm-seed.sh` allowlists (SecureString for the secret) and `tests/conftest.py`.
  - **Tests** (mock `httpx`): unverified email rejected; `sub`-first lookup; email row
    gets `use_password`; Spotify row auto-links and keeps its seeds and history; new
    user created; bad state rejected.
  **Why:** It mirrors a flow the codebase already implements once. Looking up by `sub`
  keeps identity stable. Requiring `email_verified` stops an unverified Google address
  claiming someone else's account.
  > OAuth states live in memory (one uvicorn worker), so a deploy in the middle of
  > someone's sign-in sends them back with `state_mismatch`. Accepted: they click again.

---

## Phase B — Seeding backend (no visible change)

- [ ] **B1. Client Credentials token.** *(S)*
  **How:** `get_app_token()` in `spotify_auth_service.py`: POST `SPOTIFY_TOKEN_URL` with
  `grant_type=client_credentials` and the existing `_auth_header`. Cache the token and
  its expiry **at module level** with an `asyncio.Lock` (`auth.py` and `songs.py` each
  hold their own `SpotifyAuthService()`, so an instance attribute would mint two tokens).
  Refresh about 60 seconds before the hour is up.
  Error handling, shared by B2 and B3 through one small wrapper:
  - 429 with `Retry-After`: tell the user to try again in a moment.
  - 429 with `"reason": "QUOTA_EXCEEDED"`: log at **ERROR** (so Sentry raises it). It
    means search is down for everyone.
  - 403 mentioning Premium: log at ERROR with a message that names P1. Same reach.
  **Why:** One app token serves search and picks, with no user cap.

- [ ] **B2. Search.** *(S)*
  **How:** `GET /items/search?q=`: `q` 1–100 characters; proxy
  `GET /v1/search?type=track&limit=10` (10 is now Spotify's maximum). Return a slim
  shape: `id`, `name`, `artist`, `album`, `image_url` (None when `album.images` is
  empty), `duration_ms`, `spotify_url`. The last one is for attribution (C2). Rate limit
  `20/minute` with `session_key`.
  **Why:** A thin proxy keeps the client secret on the server and the response shape
  ours.

- [ ] **B3. Add a seed.** *(M)*
  **How:** `POST /items/seeds {track_id}`, one track per call (Spotify removed the batch
  lookup for development mode).
  1. Check `track_id` looks like a Spotify id (22 base-62 characters) before spending an
     API call on it.
  2. Fetch `GET /v1/tracks/{id}` with the app token. Unknown id: 404 with "We couldn't
     find that song."
  3. Lock the user row (`with_for_update`, as `get_recs` already does) so the cap check
     and the insert can't race. If the track is already a seed, return it with 200. If
     the user already has 25 seeds (failed ones included; they can remove those), 409
     with "You can have up to 25 songs. Remove one to add another."
  4. Insert the `UserTopSong` row. If a `Song` with that `spotify_track_id` already
     exists, link it (`song_id`, `genre`) at insert time, exactly as
     `add_user_top_songs` does, so a track anyone has ever ingested is usable
     immediately with no download. Otherwise the worker claims it on its next poll.
  5. Treat an `IntegrityError` on `uq_user_top_songs_user_track` (two tabs) as "already
     added".
  6. Return the seed with its state (`ready` or `processing`). The dashboard's existing
     `/status` poll then takes over.
  Write this as a new `add_seed` function. Leave `add_user_top_songs` alone: it is the
  grandfathered top-tracks path and is deleted in D1. No `processing_users`, no
  background task (worker-only).
  Rate limit `30/minute` with `session_key`.
  **Tests:** add, re-add is idempotent, cap at 25, unknown id, an existing `Song` links
  immediately, the IntegrityError path.
  **Why:** Fetching by id on the server closes the forged-metadata hole, and linking to
  existing songs makes repeat picks free.
  > **Accepted:** removing a seed and adding it back starts its attempt count from zero,
  > which gets round the 3-attempt cap. Bounded by the rate limit and the cap of 25, and
  > costs only worker downloads. Not worth a soft-delete column.
  > **Accepted:** a dispatch is generated as soon as the first seed is usable, and it is
  > locked for the day. Someone who picks ten songs gets today's drop from whichever
  > lands first. Same bargain as today; worth watching in D3.

- [ ] **B4. Claim seeds fairly across users.** *(S)*
  **How:** `claim_pending_seeds` orders by `id` across all users, so someone who just
  added 25 songs pushes the next new user's first song half an hour back (roughly 70
  seconds a track). Order instead by how many usable seeds the user already has, then by
  id: `ORDER BY (SELECT count(*) FROM user_top_songs u2 WHERE u2.user_id =
  user_top_songs.user_id AND u2.song_id IS NOT NULL), id`. A user with nothing yet goes
  first. Use this correlated subquery, not a window function: Postgres refuses
  `FOR UPDATE` alongside window functions. Check with `EXPLAIN` that it stays cheap
  (the table is tiny).
  **Tests:** with one user holding 25 pending seeds and a second user with one, the first
  claim includes the second user's seed.
  **Why:** The first drop is the moment that decides whether someone comes back.

- [ ] **B5. Remove a seed.** *(S)*
  **How:** `DELETE /items/seeds/{spotify_track_id}`: delete that row for the current
  user. The linked `Song` stays; it serves other users. Nothing references
  `user_top_songs` by foreign key, and today's dispatch reads only recommendations and
  songs, so removal can't break a dispatch. If the worker is holding that seed, its
  `/complete` or `/fail` gets a 404, which it already logs and skips. Add `"DELETE"` to
  `CORSMiddleware.allow_methods` (production is same-origin through nginx; this is for
  host-run dev). Rate limit `30/minute`.
  **Tests:** removes only the caller's row; the worker's `complete_seed` on a removed id
  returns `unknown`.
  **Why:** A cap with no way to remove is a dead end.

- [ ] **B6. List seeds.** *(S)*
  **How:** `GET /items/seeds` returns up to 25 seeds, each with a state: `ready`
  (`song_id` set), `processing` (waiting), or `failed` (`ingest_failed_at` set). The
  existing `/items/top_tracks/` (limit 10, "last synced" from `snapshot_at`) stays until
  C2 stops using it, and is removed in D1.
  **Why:** The picker needs to show what's there and what's still working.

---

## Phase C — The release (frontend)

Merge C1, C2 and C3 together, in one sitting, after Phases A and B are deployed and P1
to P4 are done. Until then nobody can reach the new paths.

- [ ] **C1. Auth pages and entry points.** *(M)*
  **How:** A sign-in page with an email + password form (sign in / create account
  toggle) and a "Continue with Google" button pointing at `/api/v1/auth/google/login`.
  Replace every Spotify entry point: `page.tsx` (the button component and the raw CTA
  link), `navbar-component-01.tsx`, and `spotify-login-button.tsx` itself. Sweep the
  Spotify copy in `page.tsx` and the `layout.tsx` metadata.
  **The landing page has to read `?error=`.** Google errors (`use_password`,
  `google_unverified`, `auth_failed`, `state_mismatch`) come back to `FRONTEND_URL`,
  which is the site root, and today it ignores the parameter. The `/callback` page is
  referenced nowhere; delete it.
  Show the email's local part where `display_name` is empty (today: "Listener"). Show
  API errors as they come, including the named-method messages. Copy: plain, no
  em-dashes.

- [ ] **C2. Picker and seed list.** *(M)*
  **How:** On the dashboard: a search box, results, an add button per result, and the
  user's seeds (from B6) with their state and a remove button. Shown prominently on
  `needs_seeds`; on `no_seeds`, say "We couldn't process these songs. Try adding
  different ones." instead of today's Spotify copy. Keep the `processing` spinner and
  the `/status` poll as they are, and **stop polling on `needs_seeds`** as well.
  Show how many of the 25 are left. Sweep the "top tracks" copy in
  `song-rec-carousel.tsx`, `profile-content.tsx` ("Play a few songs on Spotify and this
  fills itself in") and `dashboard/page.tsx` to "your songs".
  **Spotify attribution (Policy II.4, design guidelines):** wherever Spotify artwork or
  metadata appears (search results, the seed list), include a "Listen on Spotify" link
  to the track and the Spotify logo per the guidelines, and don't crop or overlay the
  artwork.
  **Why:** This is the new onboarding moment: from empty account to first drop in one
  sitting.

- [ ] **C3. Per-user dispatch cache.** *(S)* (folded in from deferred)
  **How:** The carousel caches the day's drop in localStorage under the fixed key
  `pyo:recs` and replays it until midnight Pacific; only logout clears it. On a shared
  browser, a second account signing in the same day sees the first one's drop. Return
  the user's `id` from `/auth/me`, key the cache `pyo:recs:<id>`, and remove any key
  that isn't the current user's on load. Keep clearing on logout.
  **Why:** Email accounts make shared devices realistic.

---

## Phase D — Retire the Spotify login

- [ ] **D1. Remove the Spotify login path.** *(M)*
  **How:** Delete `/auth/spotify/login` and `/auth/spotify/callback`,
  `_refresh_seed_snapshot`, the top-tracks branch of `get_recs`, `add_user_top_songs`,
  `get_top_tracks` and `/items/top_tracks/`. `SpotifyAuthService` keeps `_auth_header`
  and `get_app_token`; `exchange_code`, `upsert_user` and `refresh_tokens` can go or stay
  dormant (keep them if "connect Spotify" is still wanted). The token columns stay.
  `SPOTIFY_REDIRECT_URI` becomes dormant config. `SPOTIFY_CLIENT_ID/SECRET` stay
  (search, picks, the worker).
  **Tests:** a sweep, not a tweak. `app.api.v1.songs.auth_service` is patched 24 times
  (20 in `test_songs.py`, 2 each in `test_rate_limiting.py` and
  `test_ingest_worker.py`). `TestSpotifyLogin` (4) and `TestSpotifyCallback` (11) in
  `test_auth.py` go, as does `TestLoginRateLimit` (3) in `test_rate_limiting.py`.
  `add_user_top_songs` is called directly in `test_query_cleanups.py` and
  `test_ingest_failures.py`; move those tests onto `add_seed`, keeping what they assert
  about queue state. `test_spotify_timeouts.py` stays.

- [ ] **D2. Migration: `email NOT NULL`.** *(S)* Snapshot first.
  **How:** Check no row has a NULL email (fail loudly if one does, and decide by hand),
  then set `NOT NULL`. Hand-written, `down_revision` = A1's.

- [ ] **D3. Live smoke test, including the new-account worker path.** *(S)*
  **How:** Against `https://putyouon.app`: register with email, sign out, sign in; sign
  in with Google; one of the two existing users signs in with Google and lands on their
  own history (auto-link). Check cookies, redirects, error messages, and that HSTS and
  the security headers are still on `/`.
  **This is the test 10.3 carried forward**: the first real new account is the first
  live run of the worker path for a brand-new user. Watch it end to end: `needs_seeds`;
  a few picks; the worker log (`Claimed N seed(s)`, then `done in ...`); `/status` going
  `processing` to `ready`; a drop written for that user; Sentry quiet. Picks of songs
  someone has already ingested should be `ready` instantly. Also check that a second
  account on the same browser doesn't see the first one's drop (C3).
  **Why:** The cutover smoke test proved the Spotify flow; this proves its replacement
  under real-origin conditions that dev can't reproduce.

---

## Phase E — Account deletion (folded in from deferred)

- [ ] **E1. Delete-my-account endpoint.** *(M)*
  **How:** `DELETE /auth/me`. Require a **recent sign-in**: the session cookie is a
  timestamped itsdangerous token, so check it was issued in the last 10 minutes and
  otherwise answer 403 "Sign in again to delete your account." Email accounts also
  confirm their password in the body. Then, in one transaction and in this order
  (none of the foreign keys cascade): `user_recommendations`, `user_top_songs`,
  `users`. `songs` rows stay: they are shared, and some are another user's query song.
  Clear the cookie. Log at INFO with the user id only. Postgres never reuses the id, so
  an old cookie just 401s. Frontend: a "Delete account" control on the profile page,
  a confirmation step, and clearing the C3 cache key on success. Rate limit `5/minute`.
  **Tests:** every row for that user is gone and nobody else's; recommendations that
  used the user's seed songs as `query_song_id` for **other** users are untouched; a
  stale session is refused; the old cookie 401s afterwards.
  **Why:** Email signups make "please delete my account" a realistic request, and the
  answer should not be hand-written SQL.
  > A former Spotify user should also revoke the app from their own Spotify account
  > page. Say so in the confirmation copy.

- [ ] **E2. Runbook: deletion and manual password reset.** *(S)*
  **How:** In `deploy/runbook.md`: the same deletion as SQL, for when the endpoint can't
  be used; and a **manual password reset** for 0.0.1, since there is no reset flow.
  Confirm the request came from the account's email address, generate a long random
  password, store its hash with a one-off `docker compose run --rm backend python -c`
  using `app.core.passwords.hash_password`, and send it to that address by hand. There
  is no "change password" page in 0.0.1, so that password stays theirs until the reset
  flow ships. The runbook should say so plainly rather than promise otherwise.

---

## Not in 0.0.1

- **Password reset and email confirmation.** Signed, time-limited links (the same
  itsdangerous serializer as sessions), plus an email sender (AWS SES starts in sandbox
  and needs a request to leave it; SPF and DKIM records at Porkbun). Then a
  "change password" page, which E2 currently has no answer for.
- **Playlist import.** Dead under Client Credentials (see above). The only way back is a
  user-authorized Spotify connection, which brings the user cap back. Exportify-style
  CSV upload is the fallback if people ask.
- **A non-Spotify catalog.** The way out of the Policy III.5 risk. A keyless public
  catalog (Deezer's or iTunes's search API) plus a worker download by artist and title
  through yt-dlp. Needs a source-agnostic track id instead of `spotify_track_id`.
- **"Connect Spotify"**, within the development-mode user budget, if top tracks are ever
  wanted again.
- **Removing the in-process ingest path.** It can't download on EC2 and nothing new uses
  it. Removing it, along with `processing_users` and the startup model load, may also
  drop essentia from the backend image (currently 1.64 GB). Its own cleanup.
- **Spoofable client IP** and **the worker's move to the Mac mini**: see
  [deployment-deferred.md](deployment-deferred.md).

## Guardrails

- No development-app sharding, no internal-endpoint scraping, no harvesting anyone's
  credentials.
- Spotify use stays at public catalog search and single-track lookups, with attribution.
- Passwords: argon2id only, never logged, nor their hashes. Sessions stay httponly,
  secure, SameSite=Lax.
- UI copy is plain and has no em-dashes.

---

## Already done (formerly 11.4)

**The ingest worker was turned on 2026-10-02.** In the order that mattered: Sentry
first (deployment-gameplan 10.8); the worker started on the MacBook from a fresh
`.venv.worker` (not an older venv, whose yt-dlp 2026.03.x is the version measured
failing) and confirmed polling production on its 60-second idle cadence; only then
`INGEST_WORKER_ENABLED=true` and a redeploy. The worker rode through the restart. A
forced seed then went through the whole path in about a minute (deployment-gameplan
10.3).

One setup trap worth keeping: the worker calls `spotdl` **by name**, so whichever
`spotdl` is first on PATH runs. With another venv active, the worker silently uses that
venv's spotdl and its stale yt-dlp. Always run it from the activated `.venv.worker` and
check `which spotdl`.

**Until the worker moves to the Mac mini, new users only ingest while the MacBook is
awake and running it.** A sleeping worker looks exactly like work in progress; nothing
alerts.
