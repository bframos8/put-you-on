# Production Deployment Gameplan — Docker on AWS EC2 + GitHub CI/CD

**Date:** 2026-06-15 (revised 2026-07-13 — re-verified against the codebase, agent-audited)
**Branch:** `Backend-optimization`
**Goal:** Take the current multi-service app to a production deployment on a single
AWS EC2 instance, running under Docker Compose, fronted by nginx with Let's Encrypt
TLS, behind a GitHub Actions CI/CD pipeline that tests, builds to ECR, and deploys
via SSM.

> This is an **ordered runbook**. Work top to bottom — later phases assume earlier
> ones are done. Each item states **How** (concrete steps) and **Why** (the reason
> it matters at scale). Items are checkboxes so you can track progress.

---

## Locked decisions (from clarifying Q&A)

| Decision | Choice |
|----------|--------|
| **Database** | AWS **RDS for PostgreSQL** (already provisioned) — app connects over the network; no DB container. |
| **TLS / ingress** | **nginx on the instance + Let's Encrypt (Certbot)**. |
| **Image registry + deploy** | **Amazon ECR** for images; deploy triggered by **SSM Run Command** (no inbound SSH). |
| **Secrets** | **SSM Parameter Store** (SecureString), materialized at deploy time. |
| **Domain** | **Register via Porkbun**; **DNS hosted at Porkbun** (a single `A` record → Elastic IP — not Route 53). |
| **Scope** | **Web app only** (backend + frontend + nginx). `data_pipeline` deferred. |
| **Downtime** | Brief recreate is acceptable — simple pull-and-up deploy. |

---

## Current-state assessment (what exists vs. what's missing)

**What you already have working for you**
- Clean multi-stage [frontend/Dockerfile](../frontend/Dockerfile) (Next.js `standalone`).
- A backend [Dockerfile](../backend/Dockerfile) that builds and runs uvicorn.
- Alembic is set up ([backend/alembic/](../backend/alembic/)) alongside the models.
- Security headers + HSTS toggle already implemented in [main.py](../backend/app/main.py).
- `sentry-sdk` and `slowapi` already in [backend_requirements.txt](../backend/backend_requirements.txt).

**What blocks a production deploy (addressed by the phases below)**
- [docker-compose.yaml](../docker-compose.yaml) is **broken**: `db` service is commented out
  but `backend` still `depends_on: [db]`. No restart policies, healthchecks, or networks.
- **No `.github/` directory** — there is zero CI/CD today.
- Schema is created at runtime via `Base.metadata.create_all()`
  ([main.py:25](../backend/app/main.py#L25)) **and** Alembic exists → two competing schema
  authorities. Production must use Alembic only.
- TLS uses **mkcert localhost certs** hardcoded in compose/nginx; nginx has no real
  `server_name`, no HTTP→HTTPS redirect, no proxy/forwarded headers.
- No `/health` endpoint for healthchecks / deploy gating.
- `sentry-sdk` is installed but **never initialized**.
- Secrets sit in plaintext root `.env-backend` / `.env-postgres` (dev-only pattern).
- Dev TLS material sits in the working tree: `frontend/localhost+1-key.pem` /
  `localhost+1.pem` are **gitignored and were never committed** (`git log --all` is empty
  for them), but [frontend/.dockerignore](../frontend/.dockerignore) doesn't exclude
  `*.pem`, so they enter the frontend build context (builder stage only — the multi-stage
  runtime image doesn't ship them).

---

## Order of operations (the big picture)

```
0. AWS account groundwork (IAM roles, OIDC, ECR repos, domain)
1. App-level production correctness (health, Alembic-only, Sentry, prod config)
2. Harden the Docker images (.dockerignore, non-root, healthcheck, pinning)
3. Production docker-compose (RDS, ECR images, restart, healthchecks, no db service)
4. Production nginx config (real server_name, redirect, forwarded headers, TLS hardening)
5. Secrets in SSM Parameter Store
6. Provision + bootstrap the EC2 instance (Docker, IAM role, SG, Elastic IP, DNS)
7. First TLS certificate (Certbot) + auto-renewal
8. GitHub Actions: CI (test) → Build/Push (ECR) → Deploy (SSM)
9. Observability, backups, alarms
10. Pre-launch verification + cutover + rollback runbook
11. Post-launch: retire Spotify login + search seeding — first workstream through the pipeline
```

Rationale for the ordering: the **images must be correct before you ship them** (phases
1–2), the **runtime topology must be defined before the host exists** (phases 3–5), the
**host must exist and resolve over TLS before CI can deploy to it** (phases 6–7), and CI/CD
is the last thing you wire because it automates a process you've already proven by hand.

---

## Phase 0 — AWS groundwork & prerequisites

- [x] **0.1 Register a domain and create a stable DNS record.**
  **How:** Register the domain at **Porkbun** (~$11–12/yr for `.com`, free WHOIS privacy)
  and manage DNS in **Porkbun's own DNS panel** — no Route 53 hosted zone. You'll add a
  single `A` record pointing at the instance's Elastic IP in Phase 6. (Route 53 isn't
  needed here: the only record is one static `A` → EIP, and TLS is handled by Certbot on
  the box, not ACM. If you later scale out to an ALB, migrate DNS to Route 53 then — see
  the deferred HA note.)
  **Why:** OAuth redirect URIs and CORS need a stable FQDN, and standard 90-day Let's
  Encrypt certificates require a domain. (LE's IP-address certs went GA in Jan 2026, but
  only under the short-lived ~6-day profile — the wrong operational tradeoff here.)

- [x] **0.2 Confirm region and architecture.**
  **How:** Deploy in **`us-east-1` (N. Virginia)** — the same region as the RDS instance
  (`pyo_db`). Use an **x86_64 (`t3`/`m`)** instance, **not** Graviton/`t4g`.
  **Why:** `essentia-tensorflow==2.1b6.dev1389` ([backend_requirements.txt](../backend/backend_requirements.txt))
  ships prebuilt wheels for `linux/amd64`; ARM wheels are not reliably available and you'd be
  stuck compiling. GitHub runners are amd64 by default, so images will match.

- [x] **0.3 Create the ECR repositories.**
  **How:** `aws ecr create-repository --repository-name putyouon/backend` and
  `.../frontend`. Enable **scan-on-push** and a **lifecycle policy** (e.g. keep last 10
  images).
  **Why:** Private, IAM-controlled image storage co-located with EC2 (fast pulls, no
  egress); scanning catches known CVEs; lifecycle policy stops untagged layers from
  accumulating cost.

- [x] **0.4 Create the EC2 instance IAM role (instance profile).**
  **How:** Role with: `AmazonSSMManagedInstanceCore` (SSM agent), ECR pull
  (`ecr:GetAuthorizationToken`, `BatchGetImage`, `GetDownloadUrlForLayer`), and scoped SSM
  read (`ssm:GetParametersByPath` on `arn:aws:ssm:*:*:parameter/putyouon/prod/*` +
  `kms:Decrypt` on the key).
  **Why:** The instance pulls images and secrets using its role — **no static AWS keys on
  the box**. SSM core is what lets you deploy and get a shell without opening SSH.

- [x] **0.5 Create the GitHub Actions deploy role via OIDC.**
  **How:** Add GitHub's OIDC provider to IAM, then a role trusted by your repo with: ECR
  push, `ssm:SendCommand` scoped to your instance + the `AWS-RunShellScript` document, and
  `ssm:GetCommandInvocation` so the deploy job can poll the command result (without it,
  8.3 can fire the deploy but never fail the job when the health gate fails).
  **Why:** OIDC gives CI short-lived, repo-scoped credentials — **no long-lived AWS access
  keys stored in GitHub secrets** (the single most common cloud-credential leak).

> **Phase 0 provisioned (all in `us-east-1`) — recorded 2026-07-17:**
> - **Domain:** `putyouon.app` (registered + DNS at Porkbun; `A` record added in 6.4).
> - **ECR repos:** `putyouon/backend`, `putyouon/frontend` (private, scan-on-push,
>   keep-last-10 lifecycle).
> - **Instance role (0.4):** `putyouon-ec2-instance-role` = managed
>   `AmazonSSMManagedInstanceCore` + customer policy `putyouon-ec2-ecr-ssm-read`.
> - **CI/CD OIDC (0.5):** provider `token.actions.githubusercontent.com`; role
>   `putyouon-github-actions-deploy` (trusts `repo:bframos8/put-you-on:ref:refs/heads/main`)
>   + customer policy `putyouon-cicd-deploy-permissions`. Its **role ARN** is what Phase 8
>   wires as `role-to-assume`.
>
> **Two intentional placeholders to tighten later — do not forget:**
> - **Phase 5:** scope `kms:Decrypt` in `putyouon-ec2-ecr-ssm-read` from `*` to the real
>   SecureString KMS key ARN once the key is chosen.
> - **Phase 6.1:** scope `ssm:SendCommand` in `putyouon-cicd-deploy-permissions` from
>   `instance/*` to the specific instance ARN once the instance exists.
>
> Concepts behind every Phase 0 decision are written up in
> [deployment-learnings.md](deployment-learnings.md).

---

## Phase 1 — App-level production correctness

> These are code changes. Do them first so the images you build in Phase 2 are already
> production-shaped.

- [x] **1.1 Add a `/health` endpoint to the backend.**
  **How:** A tiny router returning `200 {"status":"ok"}`; optionally a `/health/ready` that
  does a cheap `SELECT 1` against the DB. Register it in [main.py](../backend/app/main.py)
  (unauthenticated, not rate-limited).
  **Why:** Compose healthchecks, nginx upstream checks, the deploy script's "is it back up?"
  gate, and external uptime monitors all need a cheap liveness/readiness signal.

- [x] **1.2 Make Alembic the single schema authority; stop `create_all` in production.**
  *(Absorbs deferred item **P6** — see
  [backend-optimization-deferred.md](../backend/agents/backend-optimization-deferred.md).)*
  > **Code landed 2026-07-17 (squash approach).** The 8-migration chain was
  > **squashed to a single baseline root**
  > [45f91add221e](../backend/alembic/versions/45f91add221e_baseline_schema.py)
  > (`down_revision=None`) that `CREATE TABLE`s the full current schema + the `vector`
  > extension + `work_status_enum` + the `songs_fill_genre` trigger; the old 8 migrations
  > were deleted. The models now declare `uq_albums_url`, `uq_songs_album_id_title`, and
  > the composite `ix_user_recommendations_user_date` (previously only in migrations) so
  > models are the honest source of truth. `Base.metadata.create_all` was **removed
  > outright** from [main.py](../backend/app/main.py) (not flag-guarded). Verified on a
  > throwaway pgvector container: `upgrade head` succeeds on an empty DB, the
  > `--autogenerate` drift diff is empty, `downgrade base` + re-up is clean, and all 146
  > backend tests pass. The **HNSW index is intentionally not in the baseline** (belongs
  > to P5b/10.2). **Remaining (not code — executed at cutover):** the live-RDS
  > `alembic stamp 45f91add221e` (10.1) and the deploy `alembic upgrade head` step (8.3).
  **How:**
  (a) **Author a baseline `op.create_table` root migration.** The current root
  ([ad1aecf9f82f](../backend/alembic/versions/ad1aecf9f82f_initial_schema.py)) only
  `add_column`s onto an already-existing table — no migration creates the six base tables,
  so `create_all` is load-bearing for fresh DBs today. The new root must open with
  `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` (no migration installs pgvector,
  so a fresh-DB `upgrade head` would otherwise fail on the vector columns). Use
  `alembic revision --autogenerate` as a drift check: reconcile until it produces an empty
  diff against the models.
  (b) **Audit the live DB's `alembic_version` and `alembic stamp` it onto the re-rooted
  chain.** Live DB and repo head currently match (`b8c9d0e1f2a3` — today's `upgrade head`
  is a no-op), but step (a) rewrites the chain's root: without a stamp onto the new chain,
  the first deploy's `alembic upgrade head` would try to re-run history — duplicate-column
  failures, or worse, re-running
  [d9e1f3a4b205](../backend/alembic/versions/d9e1f3a4b205_add_hnsw_index_songs_embedding.py)
  and silently kicking off the ~1-hour HNSW build that P5b gates behind an RDS scale-up
  (see 10.2 — that migration is recorded as applied, but its index was later dropped
  manually; the rebuild belongs to P5b, not alembic).
  (c) Remove the `Base.metadata.create_all(bind=engine)` call at
  [main.py:25](../backend/app/main.py#L25), or guard it behind a `RUN_CREATE_ALL=true`
  flag used only for local dev. (d) Deployment runs `alembic upgrade head` as an explicit
  step (Phase 8).
  **Why:** `create_all` only ever **adds missing tables** — it never alters columns, adds
  indexes, or drops things. Shipping schema changes with it silently diverges prod from your
  models. Two schema authorities is a classic production data hazard.
  **Risk:** Medium-high — verify the baseline and the stamp carefully against RDS before
  cutting over. This is the highest-risk correctness item in the plan.

- [x] **1.3 Initialize Sentry.**
  > **Code landed 2026-07-22.** `sentry_sdk.init` added to
  > [main.py](../backend/app/main.py), guarded by `SENTRY_DSN` presence (no-op in
  > local dev / tests — verified both ways; all 146 backend tests pass). Init runs
  > **before app-module imports** so import-time/startup failures are captured too.
  > Made **env-driven** rather than hardcoded: `SENTRY_ENVIRONMENT` (default
  > `"production"`) and `SENTRY_TRACES_SAMPLE_RATE` (default **`0.0` — errors only**)
  > join `SENTRY_DSN` in [.env.example](../backend/.env.example), materialized from
  > SSM at deploy (Phase 5). Performance tracing defaults **off** so the RED/latency
  > story stays owned by the Grafana stack
  > ([observability-plan.md](observability-plan.md)) with zero overlap; raise the
  > rate later to debug a slow endpoint. **Remaining (ops, not code):** create the
  > Sentry project and add the real `SENTRY_DSN` under `/putyouon/prod/` (Phase 5).
  **How:** In [main.py](../backend/app/main.py), `import sentry_sdk` and
  `sentry_sdk.init(dsn=os.getenv("SENTRY_DSN"), traces_sample_rate=..., environment="prod")`
  guarded by the env var being present (no-op locally). Add `SENTRY_DSN` to
  [.env.example](../backend/.env.example) as part of this item (it's absent today).
  **Why:** You already pay for the dependency. Production without error tracking means you
  learn about failures from users, not dashboards.

- [x] **1.4 Set the production process model for uvicorn.**
  > **Code landed 2026-07-22.** Backend [Dockerfile](../backend/Dockerfile) CMD now runs
  > uvicorn with `--proxy-headers --forwarded-allow-ips=*` (1 worker, uvicorn's default).
  > Baked into the image (not a compose override) so the Phase 2 image is production-shaped
  > and dev, which also runs behind nginx, matches prod. `=*` is safe: port 8000 is never
  > published, only nginx on the internal network reaches it. Verified by booting the real
  > app with the flags: a request with `X-Forwarded-For: 203.0.113.7` is logged by uvicorn
  > with client `203.0.113.7` (vs `127.0.0.1` without it), so `get_remote_address`/`slowapi`
  > now key the unauthenticated login routes ([auth.py](../backend/app/api/v1/auth.py)
  > `20/minute` + `10/minute`) on the real client IP instead of one site-wide nginx bucket.
  > Worker scaling stays deferred to metrics (6.1); the test suite is unaffected (change is
  > in the container launch command, not importable code).
  **How:** Run uvicorn with `--proxy-headers --forwarded-allow-ips="*"` (it sits behind
  nginx). For multi-core use, add workers — but **measure first**: each worker is a **full
  copy** of the app, and the P1/P2 double model load means that copy carries both model
  instances. That copy is smaller than once assumed — ~313 MB for both models plus the
  FastAPI stack ≈ **~0.5–1 GB per worker** (measured 2026-07-14; see 6.1) — so a `t3.medium`
  can host a worker or two, but confirm RAM headroom before scaling. Start with **1 worker**
  and scale up only if metrics allow.
  **Why:** `--proxy-headers` makes the app see the real client IP. Without it, `slowapi`
  keys every request on nginx's address ([limiter.py](../backend/app/core/limiter.py) uses
  `get_remote_address`), so the unauthenticated login/callback limits collapse into one
  **site-wide** bucket — ~21 logins/minute across all users starts returning 429s. (HSTS is
  *not* affected: it's a static `ENABLE_HSTS` toggle, scheme-independent.) Worker count is
  a memory/throughput tradeoff specific to this TF-heavy service.

- [x] **1.5 Point all environment config at the real domain.**
  > **Code landed 2026-07-22.** The domain *values* (`ENABLE_HSTS=true` and the three
  > `https://putyouon.app` origins/redirect) are production env set in SSM at deploy
  > (Phase 5), not repo changes; [.env.example](../backend/.env.example) keeps its
  > localhost dev defaults. The Phase-1 repo deliverable: documented the previously
  > undocumented `DAILY_LIMIT_BYPASS` (dev-only escape hatch; blank = limit enforced;
  > must stay unset in prod, where the app warns at startup if enabled). Two adjacent
  > fixes folded in: (a) corrected the `SPOTIFY_REDIRECT_URI` code fallback in
  > [spotify_auth_service.py](../backend/app/services/spotify_auth_service.py) from
  > `.../auth/spotify/callback` to `.../api/v1/auth/spotify/callback` (the real route
  > per main.py+auth.py; the old default 404'd, the silent-localhost-fallback trap 5.1
  > warns about); (b) added a committed
  > [.env-postgres.example](../backend/.env-postgres.example) template for the backend's
  > second env_file (`POSTGRES_*`), broadening the `.gitignore` negation to
  > `!.env*.example` (verified the real `.env-backend`/`.env-postgres` secret files stay
  > ignored). All 146 backend tests pass.
  **How:** In production env (Phase 5): `ENABLE_HSTS=true`,
  `CORS_ALLOWED_ORIGINS=https://putyouon.app`, `FRONTEND_URL=https://putyouon.app`,
  `SPOTIFY_REDIRECT_URI=https://putyouon.app/api/v1/auth/spotify/callback`. Ensure
  `DAILY_LIMIT_BYPASS` stays **unset** in prod (it disables the daily dispatch limit) and
  document it in [.env.example](../backend/.env.example), where it's missing today. Keep
  [backend/.env.example](../backend/.env.example) updated as the documented contract.
  **Why:** These currently default to `localhost`/`127.0.0.1`. OAuth, CORS, and HSTS all
  break or become insecure if they don't match the served origin.

- [x] **1.6 Register the production OAuth callback in the Spotify dashboard.**
  > **Done manually 2026-07-22.** `https://putyouon.app/api/v1/auth/spotify/callback`
  > added to the Spotify app's Redirect URIs (ops step, no code). Matches the
  > `SPOTIFY_REDIRECT_URI` prod value Phase 5 materializes from SSM (and the corrected
  > `/api/v1` fallback landed in 1.5).
  **How:** Add `https://putyouon.app/api/v1/auth/spotify/callback` to your Spotify app's
  Redirect URIs.
  **Why:** Spotify rejects any redirect URI not pre-registered — OAuth will fail on first
  login otherwise. Easy to forget; blocks the entire core flow.

- [x] **1.7 Keep dev TLS material out of the build context.**
  > **Code landed 2026-07-22.** Added `*.pem` to
  > [frontend/.dockerignore](../frontend/.dockerignore) (it previously listed only
  > node_modules/.next/.env*.local). The correction below holds: the mkcert pems were
  > never committed (root .gitignore covers them; `git log --all` empty), so no history
  > purge was needed. But the .dockerignore rule was still outstanding: the builder
  > stage's `COPY . .` ([frontend/Dockerfile](../frontend/Dockerfile) line 5) pulled the
  > working-tree pems into the build context / builder layer / cache. Verified with a
  > throwaway `busybox` + `COPY . /ctx` build against the real context: pems now absent
  > (OK_NO_PEM_IN_CONTEXT). The multi-stage runtime image was already clean; this closes
  > the builder side. Prod de-reference is moot (no docker-compose.prod.yaml yet; Phase
  > 3.5 mounts Let's Encrypt certs, not mkcert pems).
  **How:** Add `*.pem` to [frontend/.dockerignore](../frontend/.dockerignore) (it lists
  only `node_modules`/`.next`/`.env*.local` today) and don't reference the mkcert files in
  prod config. *(Corrected: the pems were never committed — root `.gitignore` covers
  `*.pem` and `git log --all` is empty for them — so no rotation or history purge is
  needed. The multi-stage build already keeps them out of the runtime image; this closes
  the builder stage/cache too.)*
  **Why:** Private keys don't belong in any image layer, including intermediate ones.

- [x] **1.8 (Recommended, from your audit) Replace `print()` with `logging`.**
  > **Code landed 2026-07-22.** Migrated the 7 real `print()` calls in `backend/app`
  > (main.py DAILY_LIMIT_BYPASS warning; auth.py callback failure; 5 in
  > spotify_ingest_service.py) to per-module `logging.getLogger(__name__)` at
  > level-appropriate calls (info/warning/error, `%`-style lazy args). Added
  > `logging.basicConfig` at startup in [main.py](../backend/app/main.py) with an
  > env-driven `LOG_LEVEL` (default INFO; documented in
  > [.env.example](../backend/.env.example)) and a timestamp/level/name format, so
  > output now has levels/timestamps and can be routed or silenced. `auth.py`
  > deliberately logs only `type(e).__name__` (no traceback) to preserve the S2
  > no-sensitive-data guard on the OAuth callback; since that log moved stdout->stderr,
  > migrated `test_failed_callback_does_not_log_code_or_traceback` from `capsys` to
  > `caplog` (plus a positive assertion, so the guard stays live). The 2 remaining
  > `print(` occurrences (crypto.py, session.py) are string literals in error messages
  > (key-gen hints), not calls. `data_pipeline`'s ~69 prints stay deferred with the rest
  > of the pipeline. All 146 backend tests pass; log format + LOG_LEVEL gating verified
  > at runtime.
  **How:** `logger = logging.getLogger(__name__)` per module; `logger.info/warning/exception`.
  This is **H3** in [housekeeping-audit.md](housekeeping-audit.md).
  **Why:** Production needs log levels, timestamps, and the ability to route/silence output.
  `print()` to stdout can't be filtered and loses exception context. Non-blocking, can be
  staged, but do it before you're debugging prod through `docker logs`.

---

## Phase 2 — Harden the Docker images

- [x] **2.1 Add `backend/.dockerignore`.**
  > **Code landed 2026-07-25.** Added [backend/.dockerignore](../backend/.dockerignore)
  > (none existed; the backend Dockerfile's bare `COPY . .` was baking everything in).
  > Excludes `tests/`, `pytest.ini`, `test-requirements.txt`, `.pytest_cache/`, `agents/`,
  > `__pycache__/`, `*.pyc`/`*.pyo`, `.env*`, and `*.pem`; keeps `app/` (incl.
  > `app/models/*.pb` runtime TF model), `alembic/`, `alembic.ini`,
  > `backend_requirements.txt`. **Non-obvious:** dockerignore patterns are rooted at the
  > build context (unlike `.gitignore`, which matches at any depth), so bare
  > `__pycache__/`/`*.pyc` left nested caches (`app/__pycache__`, …) in the context — fixed
  > by prefixing with `**/`. Verified by building a throwaway `busybox` image with
  > `COPY . /ctx` against the real context (the 1.7 approach): every excluded path absent
  > (incl. nested pycache dirs + the `.env*.example` templates), every runtime path present
  > (incl. the `.pb` model + `alembic/env.py`). Dropping the test files is exactly what 8.1
  > expects — CI mounts them back in.
  **How:** Exclude `tests/`, `pytest.ini`, `test-requirements.txt`, `.pytest_cache/`,
  `agents/`, `__pycache__/`, `*.pyc`, `.env*`, and any local certs/scratch. **Keep**
  `app/` (including `app/models/*.pb` — the runtime TF model), `alembic/`, `alembic.ini`,
  `backend_requirements.txt`. (CI mounts the test files back in — see 8.1.)
  **Why:** The current backend [Dockerfile](../backend/Dockerfile) does `COPY . .` with no
  ignore file, baking tests/cache/agents into the image — larger images, slower pulls, more
  attack surface. (The frontend already has a [.dockerignore](../frontend/.dockerignore).)

- [x] **2.2 Run both images as a non-root user.**
  > **Code landed 2026-07-25.** Backend [Dockerfile](../backend/Dockerfile): `useradd
  > --create-home app` + `USER app` before CMD. **Non-obvious:** the ingest path writes
  > downloaded audio under `app/services/downloads`
  > ([spotify_ingest_service.py:27-33](../backend/app/services/spotify_ingest_service.py#L27-L33)
  > — `mkdir` + `mkdtemp`), so that one dir is pre-created and `chown`ed to `app`; the rest
  > of `/app` stays root-owned and read-only (a compromised process can't rewrite app code).
  > Frontend [Dockerfile](../frontend/Dockerfile): `USER node` (the image's built-in uid-1000
  > user) in the runtime stage — the standalone server only reads the root-owned,
  > world-readable files and writes nothing. Verified by building both and running: backend
  > `whoami`=`app`/uid 1000, downloads dir writable, `/app/app` code write **denied**;
  > frontend `whoami`=`node`/uid 1000, `server.js` present.
  **How:** Backend: add a `useradd app` and `USER app` before `CMD`. Frontend: switch to the
  built-in `node` user in the runtime stage.
  **Why:** Defense in depth — a container escape or RCE shouldn't land as root. Standard
  baseline for production images.

- [x] **2.3 Add a `HEALTHCHECK` to each image.**
  > **Code landed 2026-07-25.** Both base images lack `curl`, so instead of adding a
  > package the probes reuse the runtime already present: backend
  > [Dockerfile](../backend/Dockerfile) runs `python -c` (urllib) against the existing
  > `/health` liveness endpoint ([health.py](../backend/app/api/v1/health.py), shipped in
  > 1.1); frontend [Dockerfile](../frontend/Dockerfile) runs `node -e` (http) against `/`.
  > Timing: `--interval=30s --timeout=5s --retries=3`, with `--start-period=40s` on the
  > backend (covers the TF model load) and `10s` on the frontend. **Found + fixed a real
  > prod bug while verifying:** Next's standalone `server.js` binds to
  > `process.env.HOSTNAME`, which Docker injects as the container id, so it listened only
  > on the container's own IP and `localhost`/`127.0.0.1` got `ECONNREFUSED` — not just a
  > failed probe but a fragile bind. Added `ENV HOSTNAME=0.0.0.0 PORT=3000` so it accepts
  > both the loopback probe and nginx's proxy to the container IP. Verified end-to-end:
  > built + booted both containers and polled `docker inspect` health — both flip to
  > `healthy` (probe `exit=0`), backend `/health` logs `200`.
  **How:** Backend: `HEALTHCHECK CMD curl -f http://localhost:8000/health || exit 1`.
  Frontend: hit `http://localhost:3000/`. (Install `curl` or use a tiny Python/Node check.)
  **Why:** Lets Docker/Compose report container health, which the deploy gate and
  `depends_on: condition: service_healthy` rely on.

- [x] **2.4 Pin base images and keep the build lean.**
  > **Code landed 2026-07-25.** Pinned `spotdl` → **`spotdl==4.5.2`** in
  > [backend_requirements.txt](../backend/backend_requirements.txt) (it was the only
  > unpinned dep; 4.5.2 is what pip was already resolving, so no behavior change — just
  > reproducibility). Everything else was already in place: `--no-cache-dir` present
  > ([Dockerfile](../backend/Dockerfile) pip step), `ffmpeg` installed (apt step), bases
  > kept on their tags. **Deliberately did NOT pin bases by digest:** the tags
  > `python:3.11-slim-bookworm` / `node:20-alpine` float to patched OS layers each build,
  > which is what drains the base-image CVE backlog the IDE flags; a digest pin would
  > freeze us on today's vulnerable layers until manually bumped. Also left `spotdl`'s
  > `yt-dlp` transitive dep to spotdl's own range rather than hard-pinning it — yt-dlp must
  > float to track YouTube changes or downloads break. Verified: full rebuild is green,
  > `spotdl` reports 4.5.2 and imports, `ffmpeg` present in the image.
  **How:** Keep `python:3.11-slim-bookworm` / `node:20-alpine`; consider pinning by digest.
  Pin `spotdl` in [backend_requirements.txt](../backend/backend_requirements.txt) — it's
  bare today, so every build can resolve a different version of the tool driving the whole
  download path. Backend is mostly binary wheels, so a heavy multi-stage split isn't
  required — but ensure `--no-cache-dir` (already present) and that `ffmpeg` (needed by
  `spotdl`) stays.
  **Why:** Reproducible builds and a smaller runtime surface. ffmpeg is a real runtime
  dependency of the audio path — don't drop it.

- [x] **2.5 Confirm the frontend build bakes the right API URL.**
  > **Confirmed + hardened 2026-07-28.** Verified empirically: building the frontend with
  > `--build-arg NEXT_PUBLIC_API_URL=https://putyouon.app` inlines `putyouon.app` into the
  > client bundle (4 chunks) with **zero** `127.0.0.1` — proving the Dockerfile `ENV` (a
  > real env var) wins over any `.env` file per Next's precedence. **Two footguns found +
  > closed:** (1) a missing build-arg used to bake an *empty* URL silently (all API calls
  > become relative to the frontend's own origin, no build error) — added a builder-stage
  > guard `RUN test -n "$NEXT_PUBLIC_API_URL" || exit 1` before `npm run build`, so a
  > dropped arg now **fails the build loudly** (verified: no-arg build errors with the
  > guard message). (2) A stray local `.env.production` (`127.0.0.1`) entered the build
  > context and looked authoritative though it was shadowed — broadened
  > [frontend/.dockerignore](../frontend/.dockerignore) `.env*.local` → `.env*` so no local
  > env file can reach the context (build-arg is the sole source). Note: `.env.production`/
  > `.env.local` are **gitignored/untracked** (local-only, never in CI), so the `.dockerignore`
  > rule is the committable neutralization; the files themselves need no repo change.
  **How:** The image must be built with `--build-arg NEXT_PUBLIC_API_URL=https://putyouon.app`
  (wired in CI, Phase 8). Today compose passes `https://127.0.0.1`
  ([docker-compose.yaml:20](../docker-compose.yaml#L20)).
  **Why:** `NEXT_PUBLIC_*` values are **inlined into the client bundle at build time**. A
  wrong value can't be fixed at runtime — the browser would call `127.0.0.1`.

---

## Phase 3 — Production docker-compose

- [x] **3.1 Create `docker-compose.prod.yaml` (keep the dev one for local).**
  > **Code landed 2026-08-04.** Added [docker-compose.prod.yaml](../docker-compose.prod.yaml)
  > (dev [docker-compose.yaml](../docker-compose.yaml) kept + separately repaired, see below).
  > **Image reference is fully parameterized** — `image: ${BACKEND_IMAGE}` /
  > `${FRONTEND_IMAGE}`, not a hardcoded ECR URI — so the deploy step (8.3) supplies the
  > whole ref including the git-SHA tag. Chosen over baking `<acct>.dkr.ecr…:${IMAGE_TAG}`
  > into the file because it keeps the AWS account id out of the repo (reinforces the
  > env_file/image portability seam for the planned Hetzner move, §12) and makes SHA-pinned
  > rollback (10.4) a pure env change. No `build:` anywhere — the box only pulls.
  **How:** Prod compose uses `image: <acct>.dkr.ecr.<region>.amazonaws.com/putyouon/backend:<tag>`
  (and frontend) instead of `build:`. The instance pulls; it never builds.
  **Why:** Building on the box competes with the running app for CPU/RAM (your backend image
  is heavy) and couples deploys to a working toolchain on the host. Pull pre-built, tested
  images instead.

- [x] **3.2 Remove the DB service and the broken dependency.**
  > **Code landed 2026-08-04.** The prod compose has **no `db` service** and no
  > `depends_on: db`; backend reaches RDS purely via `POSTGRES_*` from `.env-postgres`
  > (confirmed the exact names at [database.py:10-14](../backend/app/db/database.py#L10-L14):
  > `POSTGRES_DB/USER/PASSWORD/HOST/PORT`). **The dev compose was separately repaired**
  > (decision: in-scope this phase): the commented `db` block was restored as a real
  > `pgvector/pgvector:pg16` service *with a `pg_isready` healthcheck*, and backend's
  > broken `depends_on: [db]` became `depends_on: { db: { condition: service_healthy } }`
  > so `docker compose up` works locally again (it was dead before — backend depended on a
  > commented-out service). Dev keeps `build:` + the mkcert localhost certs; only prod
  > drops the db.
  **How:** Delete the commented `db` block and `depends_on: [db]`. The backend reaches RDS
  via `POSTGRES_HOST=<rds-endpoint>` (plus `POSTGRES_PORT/DB/USER/PASSWORD`) from env
  (Phase 5) — those are the names [database.py](../backend/app/db/database.py) reads.
  **Why:** Today's compose references a `db` service that doesn't exist, so `backend` can't
  start. RDS is your database now.

- [x] **3.3 Add restart policies, healthchecks, an explicit network, and log limits.**
  > **Code landed 2026-08-04.** All three prod services get `restart: unless-stopped`, a
  > named bridge network `putyouon`, and a `json-file` logging block (`max-size: 10m`,
  > `max-file: 3`). Ordering uses `condition: service_healthy`: frontend waits on backend
  > healthy, nginx waits on **both** backend and frontend healthy — leaning on the
  > `HEALTHCHECK`s already baked into both images in 2.3 (no compose-level healthcheck
  > needed for those). nginx itself gets no healthcheck (nothing depends on it) and keeps
  > its service name so the existing [nginx.conf](../nginx/nginx.conf) `frontend:3000` /
  > `backend:8000` upstreams still resolve on the shared network. Verified via
  > `docker compose config`: the render shows the healthy conditions, restart policy, and
  > log caps on every service.
  **How:** `restart: unless-stopped` on every service; `depends_on` with
  `condition: service_healthy`; a named bridge network; and a logging block
  (`json-file`, `max-size: 10m`, `max-file: 3`).
  **Why:** Survive crashes and instance reboots; start in the right order; and cap log growth
  so a chatty container can't fill the disk and take down the box.

- [x] **3.4 Set resource limits, especially on the backend.**
  > **Code landed 2026-08-04.** Backend gets `mem_limit: 2g` (top of the gameplan's
  > 1.5–2 GB range): ~313 MB for both models plus transient `spotdl`/audio overhead, with
  > ~2 GB still free for frontend/nginx/OS on a 4 GB `t3.medium`. Cap put on the backend
  > only per the plan — frontend/nginx are small and left uncapped (the log caps in 3.3 and
  > image prune in 8.3 are the other disk-growth mitigations). Uses the classic non-swarm
  > `mem_limit` key (not `deploy.resources`) since this runs under plain `docker compose`;
  > confirmed the render resolves it to 2147483648 bytes.
  **How:** Give the backend a `mem_limit` sized to (per-worker footprint × workers +
  transient `spotdl`/audio overhead), with headroom below total instance RAM. On a
  `t3.medium`, a ~1.5–2 GB cap leaves room for the frontend/nginx and OS.
  **Why:** The backend isn't especially memory-hungry (~313 MB for both model instances,
  measured — see 6.1), but a runaway (concurrent ingests spawning `spotdl` subprocesses, or
  a leak) shouldn't be able to OOM the host and take nginx/frontend down with it. A cap fails
  one container, not the box.

- [x] **3.5 Wire nginx to Let's Encrypt certs and expose 80 + 443.**
  > **Code landed 2026-08-04.** Prod nginx publishes `80:80` **and** `443:443`, mounts
  > `/etc/letsencrypt:/etc/letsencrypt:ro` (real certs, Certbot-managed on the host, Phase
  > 7) and the shared ACME webroot `/var/www/certbot:/var/www/certbot:ro`, and **drops the
  > mkcert `localhost+1*.pem` mounts** entirely (those stay only in the dev compose). The
  > webroot is a **host bind-mount, not a compose service** — Certbot runs on the box (Phase
  > 7) and writes the HTTP-01 challenge into `/var/www/certbot`; nginx only needs to *read*
  > it, hence `:ro`. **Scope note:** this item is only the compose *wiring*. The
  > [nginx.conf](../nginx/nginx.conf) *contents* still reference the dev `/certs` pems and
  > have no server_name/redirect/forwarded-headers — that rewrite is **Phase 4**, and this
  > prod stack isn't run until the instance exists (Phase 6+), so the interim mismatch never
  > executes.
  **How:** Publish `80:80` and `443:443`; mount the host's `/etc/letsencrypt:/etc/letsencrypt:ro`
  and an ACME webroot. Drop the localhost `.pem` mounts.
  **Why:** Real certs live on the host (managed by Certbot in Phase 7); port 80 is needed for
  the ACME HTTP-01 challenge and the HTTPS redirect.

---

## Phase 4 — Production nginx config

- [x] **4.1 Real `server_name` + HTTP→HTTPS redirect + ACME challenge.**
  > **Code landed 2026-08-06.** Phase 4 is a **separate [nginx.prod.conf](../nginx/nginx.prod.conf)**
  > (the dev [nginx.conf](../nginx/nginx.conf) keeps mkcert localhost certs — cert paths
  > genuinely differ, so a two-file split mirrors the two-compose pattern rather than an
  > envsubst template). [docker-compose.prod.yaml](../docker-compose.prod.yaml) now mounts
  > `nginx.prod.conf` at `/etc/nginx/nginx.conf`. The `:80` server has
  > `server_name putyouon.app;`, `location /.well-known/acme-challenge/ { root /var/www/certbot; }`
  > (the webroot bind-mounted in 3.5), and `return 301 https://$host$request_uri;` for
  > everything else. **Apex only** — no `www` (6.4 hasn't set a `www` record; add it +
  > cert SAN later if wanted).
  **How:** A `:80` server with `server_name putyouon.app;`, a
  `location /.well-known/acme-challenge/ { root /var/www/certbot; }`, and
  `return 301 https://$host$request_uri;` for everything else.
  **Why:** Certbot HTTP-01 validation hits port 80; all real traffic should be forced to TLS.

- [x] **4.2 Forward the headers the app depends on.**
  > **Code landed 2026-08-06.** All four headers (`Host`, `X-Real-IP`, `X-Forwarded-For`,
  > `X-Forwarded-Proto`) set **once at `http` level** so both the `/` and `/api/` locations
  > inherit them (the locations add only `proxy_pass`/timeouts, which does *not* reset
  > inherited `proxy_set_header`s — DRY without repetition). This is what makes uvicorn's
  > `--proxy-headers` (1.4) see the real client IP, so `slowapi` keys the unauthenticated
  > login limits per-user instead of one site-wide nginx bucket. **Backported the same
  > headers to the dev [nginx.conf](../nginx/nginx.conf)** (decision: keep dev/prod aligned)
  > so dev exercises the same IP-keyed rate limiting. Confirmed the app reads these:
  > HSTS/scheme + slowapi at [main.py:60-102](../backend/app/main.py#L60-L102).
  **How:** On the proxy locations add `proxy_set_header X-Forwarded-Proto $scheme;`,
  `X-Forwarded-For $proxy_add_x_forwarded_for;`, `X-Real-IP $remote_addr;`, `Host $host;`.
  **Why:** The backend runs `--proxy-headers` and uses these for HSTS correctness and for
  `slowapi` to rate-limit by real client IP. Today's [nginx.conf](../nginx/nginx.conf) only
  sets `Host`.

- [x] **4.3 Raise timeouts and body limits for the ML path.**
  > **Code landed 2026-08-06.** `proxy_read_timeout`/`proxy_send_timeout` set to **300s** on
  > `/api/` (lifts nginx's 60s default so a slow audio-download + embedding request isn't cut
  > off with a 504). `client_max_body_size 10m` — verified there are **no upload endpoints**
  > (no `UploadFile`/`File`/multipart anywhere in `backend/app`; audio is fetched server-side
  > by spotdl), so bodies are small JSON and 10m is generous headroom, not a real constraint.
  > Also added a dedicated **`location /health` → backend** (root-mounted, no `/api` prefix —
  > [health.py:10](../backend/app/api/v1/health.py#L10)) so the external uptime monitor (9.2)
  > and nginx upstream check hit a stable path instead of falling through to the frontend.
  > Both landed in prod and dev.
  **How:** `client_max_body_size` to a sane cap, and bump `proxy_read_timeout` /
  `proxy_send_timeout` on `/api/` (the ingest/classify path can run long).
  **Why:** Audio download + embedding is slow; nginx's default 60s read timeout can cut off
  legitimate long requests with a 504.

- [x] **4.4 TLS hardening + gzip.**
  > **Code landed 2026-08-06.** Mozilla-**intermediate** TLS: `TLSv1.2 TLSv1.3`,
  > `ssl_prefer_server_ciphers off`, session cache/timeout, `ssl_session_tickets off`, plus
  > `http2 on;`. **ECDHE-only cipher list** deliberately — it drops the DHE suites so **no
  > `ssl_dhparam` file is needed** (no extra host artifact to generate/mount), still an SSL
  > Labs A+. `gzip on` for text/JSON. **Two intentional deviations from this item's letter:**
  > (1) **OCSP stapling omitted** — Let's Encrypt **retired OCSP in 2025** (issued certs no
  > longer carry an OCSP URL), so `ssl_stapling` would be inert and log a warning on every
  > reload; documented inline. (2) **HSTS not set in nginx** — the app already emits it via
  > the `ENABLE_HSTS` middleware ([main.py:90-92](../backend/app/main.py#L90-L92)); setting it
  > here too would duplicate the header. Both configs pass **`nginx -t`** on nginx 1.29.7
  > (`test is successful`) — run in a throwaway `nginx:alpine` with a host-generated cert
  > bind-mounted at the LE path and `--add-host backend/frontend:127.0.0.1` so the literal
  > upstream names resolve at config-load. (Docker's runtime was wedged mid-session and
  > couldn't start any container; a Docker Desktop update fixed it. While it was down, a
  > **crossplane** strict-parse stood in — its lone `http2` "unknown directive" flag was a
  > false positive from crossplane 0.5.8's pre-1.25.1 map, since confirmed: 1.29.7 accepts
  > `http2 on;`.)
  **How:** Mozilla "intermediate" `ssl_protocols`/`ssl_ciphers`, OCSP stapling, `gzip on` for
  text/JSON.
  **Why:** A clean SSL Labs grade and smaller responses. Cheap, standard, expected at scale.

---

## Phase 5 — Secrets in SSM Parameter Store

- [ ] **5.1 Define a parameter namespace.**
  **How:** Store each secret as a **SecureString** under `/putyouon/prod/…`:
  `SESSION_SECRET`, **`TOKEN_ENCRYPTION_KEYS`** (required — both the app and alembic
  refuse to start without it, [crypto.py](../backend/app/core/crypto.py)),
  `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SENTRY_DSN`, and the `POSTGRES_*` DB
  credentials/host. Store the **non-secret config in the same path as `String` params** so
  5.2 materializes the full contract in one pull: `FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`,
  `SPOTIFY_REDIRECT_URI`, `ENABLE_HSTS` (and optionally `SPOTIFY_HTTP_TIMEOUT`,
  `OAUTH_STATE_TTL_SECONDS`). If any of these non-secrets are omitted the app still starts
  and silently falls back to `127.0.0.1` origins — broken OAuth/CORS with no startup
  error.
  **Why:** Central, encrypted (KMS), IAM-scoped, and auditable — no plaintext secrets in the
  repo, the image, or CI logs.

- [ ] **5.2 Materialize secrets at deploy time.**
  **How:** The deploy script (Phase 8) runs
  `aws ssm get-parameters-by-path --path /putyouon/prod --with-decryption` and writes
  `.env-backend` / `.env-postgres` on the instance with `chmod 600`, owned by root, then
  `docker compose --env-file` / `env_file:` consumes them.
  **Why:** Keeps the app's existing `env_file` contract (minimal app change) while the source
  of truth stays in SSM. Files are root-only and regenerated each deploy. Note: compose
  `env_file:` injection is **mandatory** — the in-code dotenv fallbacks
  ([main.py:8](../backend/app/main.py#L8), [database.py](../backend/app/db/database.py))
  resolve to `/` inside the image and are silent no-ops; don't "fix" a config problem by
  baking env files into the image.

- [ ] **5.3 Keep `.env.example` authoritative, never commit real env.**
  **How:** `.gitignore` already covers `.env-*` (keep it). Update
  [backend/.env.example](../backend/.env.example) whenever a var is added.
  **Why:** New contributors and the deploy script both rely on the example as the contract.

---

## Phase 6 — Provision & bootstrap the EC2 instance

- [ ] **6.1 Launch the instance.**
  **How:** Amazon Linux 2023 (SSM agent preinstalled) or Ubuntu 22.04, **x86_64** (kernel-6.1
  default AMI), start at **t3.medium (4 GB RAM)** and right-size from metrics — `t3.small`
  (2 GB) is worth testing (see Why). Attach the **instance IAM role** from 0.4. Use a gp3 EBS
  root volume with room for images (≥30 GB).
  **Why:** Contrary to the earlier 8 GB assumption, a direct measurement (2026-07-14,
  `/usr/bin/time -l` on the pipeline venv) put the Essentia/TF runtime + **both** required
  model instances (P1/P2 — embeddings `PartitionedCall:1` and genre `PartitionedCall:0` off
  the same graph) at only **~313 MB** — Essentia ships a lightweight C++ TF backend, not
  Python `tensorflow`. Realistic full-host footprint (FastAPI stack + transient `spotdl`
  subprocess + audio buffers + frontend/nginx containers + OS) is ~1–2 GB under load, so
  **4 GB gives comfortable headroom at ~half the `t3.large` cost**. Validate the backend
  container under a couple of concurrent ingests before trusting `t3.small`. The IAM role is
  what enables image/secret pulls and SSM access without keys.

- [ ] **6.2 Lock down the security group.**
  **How:** Inbound **80 + 443 from 0.0.0.0/0** only. **No port 22** — use **SSM Session
  Manager** for shell access. Ensure the **RDS security group allows 5432 from this
  instance's SG**.
  **Why:** Closing SSH removes the most-attacked port entirely; SSM gives audited,
  key-less shell access. The RDS rule is what lets the app reach the database.

- [ ] **6.3 Install Docker Engine + Compose plugin; enable on boot.**
  **How:** Install `docker` and `docker-compose-plugin`, `systemctl enable --now docker`,
  add the deploy user to the `docker` group.
  **Why:** Compose runs your stack; enabling on boot means an instance reboot brings the app
  back automatically (with the `restart` policies from 3.3).

- [ ] **6.4 Allocate an Elastic IP and point DNS at it.**
  **How:** Allocate + associate an Elastic IP; in **Porkbun's DNS panel** create an `A`
  record `putyouon.app → EIP` (add `www` as a second `A`/`CNAME` if you want it). Create
  **only** the `A` record — do **not** add an `AAAA`/IPv6 record: the box is IPv4-only, and
  a stray `AAAA` pointing at a non-listening address makes Certbot validation fail. Allow
  for DNS propagation before running Certbot in Phase 7.
  **Why:** Certbot and OAuth need a **stable** address. A default public IP changes on
  stop/start and would break TLS and redirects. Certbot's HTTP-01 challenge (Phase 7)
  needs the `A` record already resolving to the EIP.

- [ ] **6.5 Verify RDS state.**
  **How:** The database is already live (`pyo_db`: migrations applied, ~110k rows, genre
  backfill done — see
  [backend-optimization-remaining.md](../backend/agents/backend-optimization-remaining.md)),
  so this is **verification, not setup**: confirm `CREATE EXTENSION IF NOT EXISTS vector;`
  is a no-op, confirm the app's DB user privileges, and confirm reachability from the
  instance SG (6.2). The schema reconcile + stamp happens in 1.2/10.1; the HNSW rebuild in
  10.2.
  **Why:** Treating a live, populated database as fresh is how deploys corrupt data. The
  remaining DB work is tracked and sequenced elsewhere, not re-done here.

---

## Phase 7 — First TLS certificate + auto-renewal

- [ ] **7.1 Issue the initial certificate.**
  **How:** With DNS resolving (6.4) and nginx serving the ACME challenge on port 80, run
  Certbot (webroot mode against `/var/www/certbot`, or the standalone/nginx plugin) to issue
  a cert for `putyouon.app`. **Note — `.app` is HSTS-preloaded at the TLD level:** browsers
  force HTTPS for every `.app` host, but this does **not** block HTTP-01 — Let's Encrypt's
  validator isn't a browser and reads the port-80 challenge fine, so keep webroot/HTTP-01
  (don't switch to DNS-01). The catch: you can't sanity-check `http://putyouon.app` in a
  browser during bootstrap — use `curl -v` or verify only once HTTPS is live. Bootstrap
  order: bring nginx up serving just the challenge path on `:80` → run Certbot → then add
  the `:443` server block and reload.
  **Why:** This is the bootstrap that turns on HTTPS; everything downstream assumes a valid
  cert at `/etc/letsencrypt/live/putyouon.app/`.

- [ ] **7.2 Automate renewal + nginx reload.**
  **How:** A systemd timer (or cron) running `certbot renew` twice daily, with a deploy hook
  that reloads nginx (`docker compose exec nginx nginx -s reload`).
  **Why:** Let's Encrypt certs last 90 days. Unattended renewal is the difference between
  "set and forget" and a site-down incident every quarter.

---

## Phase 8 — GitHub Actions CI/CD

> Three workflows. Protect `main` so nothing merges without green CI.
>
> **Branching model: trunk-based — `main` *is* prod.** Changes ride short-lived feature
> branches → PR → green CI → merge, and the merge deploys. No standing `develop` branch:
> local dev builds from your checkout (dev compose `build:`), while the instance only
> pulls images a `main` merge produced — unmerged work has no path to prod. If
> merge-equals-deploy ever feels too hot once real users exist, add a **GitHub
> Environment approval gate** on the deploy job (required reviewer), not an environment
> branch. Full rationale + team-workflow notes:
> [deployment-learnings.md §14](deployment-learnings.md).

- [ ] **8.1 CI workflow — test on every PR and push.**
  **How:**
  - **Backend:** build the backend image, then run the tests **in a container from that
    image**, mounting the test files back in (2.1 excludes them from the image, and pytest
    lives in [test-requirements.txt](../backend/test-requirements.txt), not the image):
    `docker run -v ./backend/tests:/app/tests -v ./backend/pytest.ini:/app/pytest.ini -v
    ./backend/test-requirements.txt:/app/test-requirements.txt <image> sh -c "pip install
    -r test-requirements.txt && pytest"`. No extra env wiring needed —
    [conftest.py](../backend/tests/conftest.py) injects all required env vars. Cache pip
    layers.
  - **Frontend:** `npm ci`, `npm run lint`, `npm run build`.
  **Why:** Testing inside the built image means the test environment equals production — no
  "works in CI, breaks in the image" gaps, and it validates the image as a side effect.
  Installing `essentia-tensorflow` from scratch on a raw runner is slow and flaky; the image
  already has it. `npm run build` catches type/build breaks that lint misses. *(The
  `data_pipeline` suite is out of scope this pass but can be added later as a separate job.)*

- [ ] **8.2 Build & Push workflow — on merge to `main`.**
  **How:** Authenticate to AWS via **OIDC** (role from 0.5), `docker login` to ECR, build
  **backend** and **frontend** (the latter with
  `--build-arg NEXT_PUBLIC_API_URL=https://putyouon.app`), tag with both the **git SHA** and
  `latest`, and push to ECR.
  **Why:** Immutable SHA tags make every deploy traceable and **instantly rollback-able**
  (re-point to the previous SHA). OIDC means no AWS keys in GitHub.

- [ ] **8.3 Deploy workflow — `ssm:SendCommand` to the instance.**
  **How:** Send a shell script via `AWS-RunShellScript` that, on the instance:
  1. materializes secrets from SSM (5.2),
  2. `aws ecr get-login-password | docker login …`,
  3. `docker compose -f docker-compose.prod.yaml pull`,
  4. runs `alembic upgrade head` via `docker compose -f docker-compose.prod.yaml run --rm
     backend alembic upgrade head` — compose `run` (not a bare `docker run`) so `env_file:`
     supplies `POSTGRES_*` **and** `TOKEN_ENCRYPTION_KEYS`, both required by the alembic
     import chain ([env.py](../backend/alembic/env.py) →
     [crypto.py](../backend/app/core/crypto.py)). First deploy runs only after 1.2's
     reconcile + stamp has landed (see 10.1),
  5. `docker compose … up -d`,
  6. polls `/health` until green (fail the job if it doesn't recover),
  7. `docker image prune -f`.
  **Why:** SSM needs **no inbound SSH** and leaves an audit trail. Running migrations as an
  explicit pre-`up` step (not at app startup) keeps schema changes deliberate and observable.
  The health poll turns a bad deploy into a failed CI job instead of a silent outage. Image
  prune stops the disk from filling with old layers. Note: the recreate in step 5 kills any
  in-flight ingest (`BackgroundTasks` dies with the process — deferred A2); rows already
  written persist, but a user's run silently stops. Acceptable for now — prefer deploying
  during quiet hours.

- [ ] **8.4 Branch protection + required checks.**
  **How:** Require the CI workflow to pass and the branch to be up to date before merge to
  `main`.
  **Why:** Automated deploy from `main` is only safe if `main` is always green and reviewed.

---

## Phase 9 — Observability, backups, alarms

- [ ] **9.1 Metrics + dashboards: follow the observability plan.**
  **How:** Collection and dashboards are specified in
  [observability-plan.md](observability-plan.md) (locked: Grafana Cloud + a local Alloy
  agent scraping node_exporter, cAdvisor, and the app's `/metrics`; RDS via the CloudWatch
  *data source*). Do **not** add the CloudWatch agent — it would duplicate that collection
  layer on a RAM-tight box. (Container log size is already capped per 3.3.)
  **Why:** One collection stack, already decided and sized for this instance.

- [ ] **9.2 Minimal alarms on the things that page you.**
  **How:** The observability plan defers full alerting to its Phase 6, but keep a **tiny
  CloudWatch alarm set** on what's native without an agent: RDS free storage, RDS
  connections, EC2 status checks — plus an external uptime check on `/health`. (EC2
  **disk** is *not* a native CloudWatch metric; disk visibility comes from node_exporter
  in the Grafana stack — watch that dashboard until its alerting phase lands. 3.3's log
  caps and 8.3's image prune are the mitigations meanwhile.)
  **Why:** Dashboards don't page you. Disk-full and RDS-connection-exhaustion are the two
  most common ways this class of app falls over; these alarms read AWS-side metrics
  directly and don't touch the Grafana stack.

- [ ] **9.3 Confirm RDS backups + test a restore.**
  **How:** Verify automated backups + retention on RDS; do one **practice restore** to a
  scratch instance.
  **Why:** A backup you've never restored is a hypothesis, not a backup. RDS makes this easy —
  use it.

---

## Phase 10 — Pre-launch verification & cutover

- [ ] **10.1 Reconcile + stamp live RDS, then run migrations and verify schema.**
  **How:** Take an RDS snapshot first. Execute 1.2's audit: confirm the live
  `alembic_version` is `b8c9d0e1f2a3` (the pre-1.2 repo head — now **deleted** by the
  squash, so it no longer exists in the chain). Then **`alembic stamp 45f91add221e`** to
  point the live DB at the new squashed baseline
  ([45f91add221e](../backend/alembic/versions/45f91add221e_baseline_schema.py)) — `stamp`
  only rewrites `alembic_version`, it does **not** re-run any `CREATE TABLE`, so it's safe
  against the already-populated RDS. Then `alembic upgrade head` (a no-op at cutover — the
  baseline *is* head) and confirm tables/indexes/`vector` columns match the models.
  **Why:** This is the moment the 1.2 reconciliation pays off — verify before traffic, not
  after. Without the stamp, the deploy's `alembic upgrade head` would find the live
  `b8c9d0e1f2a3` missing from the chain and error (a safe, loud failure — not data loss).

- [ ] **10.2 Finish P5b — rebuild the HNSW index (launch gate).**
  **How:** Run the Path A runbook in
  [backend-optimization-remaining.md](../backend/agents/backend-optimization-remaining.md):
  scale RDS up, `CREATE INDEX … USING hnsw`, pass the EXPLAIN gate, scale back down, then
  land the query change. Coordinate with 10.1's stamp so the deploy pipeline never
  triggers the build itself.
  **Why:** The index is currently dropped — both kNN branches seq-scan. Launching without
  it means every recommendation request pays full-table-scan latency.

- [ ] **10.3 End-to-end smoke test.**
  **How:** Full Spotify OAuth round-trip on the real domain, a top-tracks fetch, and one ML
  ingest/classify call. Check security headers + HSTS and an SSL Labs scan.
  **Why:** OAuth, CORS, HSTS, and TLS only fully exercise against the real origin — this is
  the test the dev environment can't give you.

- [ ] **10.4 Document the rollback procedure.**
  **How:** Write down: re-run the Deploy workflow pinned to the previous image SHA; if a
  migration was destructive, restore from the RDS snapshot taken pre-deploy.
  **Why:** Brief downtime is acceptable, but an *unrecoverable* deploy is not. A one-page
  runbook turns a 2 a.m. incident into a checklist.

---

## Phase 11 — First post-launch workstream: retire Spotify login (pipeline shakedown)

> The app **launches as-is with Spotify OAuth** — the ~25-user dev-mode cap is accepted
> at cutover. This phase then implements
> [spotify-ingest-without-quota-plan.md](spotify-ingest-without-quota-plan.md) (email +
> Google login, search-and-pick seeding, playlist import) as the **first real test of
> the live CI/CD pipeline**: every step lands as a PR → CI (8.1) → merge → build/push
> (8.2) → deploy (8.3), under branch protection (8.4).

- [ ] **11.1 Ship Phase A (identity) through the pipeline, item by item.**
  **How:** Implement A1–A8 from that plan as individual PRs. **A1's migration is the
  first live exercise of the deploy's `alembic upgrade head` step** (8.3 step 4): it
  extends the chain 1.2 re-rooted, and 10.1's practice applies — take an RDS snapshot
  before merging it. Before merging A5: create the Google OAuth client, register
  `https://putyouon.app/api/v1/auth/google/callback`, and add `GOOGLE_CLIENT_SECRET`
  (SecureString) + `GOOGLE_CLIENT_ID` / `GOOGLE_REDIRECT_URI` (String) under
  `/putyouon/prod/` (5.1 pattern) — 5.2 materializes them on the next deploy with no
  other change.
  **Why:** A schema migration + a secrets change + rolling code changes is exactly the
  deploy shape the pipeline exists for — better to shake it out on a planned workstream
  than during an emergency.

- [ ] **11.2 Retire the Spotify login in prod; re-run the smoke test.**
  **How:** Once A6 deploys, the 1.6 Spotify redirect URI is retired and the 25-user cap
  stops constraining signups. Repeat 10.3's smoke test against the real origin with
  **email + Google logins** in place of the Spotify round-trip (cookies, CORS, TLS,
  redirect returns).
  **Why:** The cutover smoke test proved the Spotify flow; this proves its replacement
  under the same real-origin conditions the dev environment can't reproduce.

- [ ] **11.3 Ship Phases B and C (search-and-pick, playlist import) the same way.**
  **How:** Continue the per-item PR cadence for B1–B6, then C1–C3. Two post-launch
  cautions: 8.3's recreate kills in-flight ingests and there are now real users — merge
  during quiet hours; and between Phase A and B5's picker, new registrants see only the
  minimal `needs_seeds` state — bundle A7 + B5 into adjacent merges if that gap matters.
  **Why:** Search-and-pick is the real onboarding once the cap is gone — Phase A without
  B leaves new users a dashboard with nothing to seed it.

---

## Deferred / follow-up (explicitly out of this pass)

- **`data_pipeline` deployment** — packaging and scheduling (cron/systemd/EventBridge) is a
  separate effort once the web app is live.
  - *Note (1.2 cleanup, 2026-07-17):* the old `data_pipeline/db/init_db.py` — a dormant,
    stale, destructive (`DROP TABLE … CASCADE`) hand-written schema bootstrap and a second
    schema authority — was **deleted** as part of 1.2. When the pipeline is deployed, any
    fresh-DB setup it needs should run `alembic upgrade head`, keeping Alembic the single
    authority. (Its orphaned helper `data_pipeline/db/initializer.py`, now used only by its
    own unit test, can be removed too whenever the pipeline work resumes.)
- **Zero-downtime deploys** — current plan accepts brief recreate downtime; blue/green is a
  later upgrade.
- **Model binary in git (audit H2)** — the 18 MB `.pb` committed twice
  ([housekeeping-audit.md](housekeeping-audit.md) H2) bloats clones. Note the backend image
  *must* ship its copy (`app/models/*.pb` is the runtime TF model), so the finding is repo
  bloat only. LFS/history-purge is a deliberate, separate call.
- **HA / autoscaling** — single instance now; an ALB + ASG (and moving TLS to ACM, plus
  migrating DNS from Porkbun to a Route 53 alias record) is the scale-out path if you
  outgrow one box.

- **Cost-driven migration to a cheaper stack (planned, post-learning)** — the AWS-native
  design here (RDS, ECR, IAM/OIDC, SSM secrets + SSM-deploy) carries an AWS-native price
  (~$40–70/mo even right-sized to `t3.medium` — dominated by compute + RDS). This
  deployment is on AWS **deliberately, to learn the ecosystem**; the intended follow-up is a move to a cheaper host — target
  **Hetzner** (CX33, 8 GB, ~$7/mo) for compute + **Neon or Supabase** (managed Postgres
  with pgvector) for the DB — for a ~$10–20/mo total.
  - **Transfers cleanly:** the Docker images (repush to GHCR/Docker Hub), `docker-compose`,
    the nginx config + Certbot TLS flow, the DB *data* (`pg_dump` RDS → `pg_restore` Neon,
    then rebuild the HNSW index on the other side), the `.env` contract, and the Grafana
    Cloud + Alloy observability stack (not AWS-native, so it just re-points).
  - **Gets rebuilt (the AWS glue):** ECR → another registry; IAM roles + OIDC (0.4/0.5) →
    SSH keys (no IAM); SSM Parameter Store (Phase 5) → env files / SOPS / Doppler; SSM Run
    Command deploy (Phase 8) → SSH-based deploy (e.g. Kamal); security groups / Elastic IP
    / SSM shell (Phase 6) → Hetzner firewall / floating IP / SSH; RDS backups + CloudWatch
    alarms (9.2/9.3) → Neon PITR/branching. That's Phases 0.4, 0.5, 5, 6, 8 — a large share
    of the plan's *effort*, but faster the second time (Hetzner's model is simpler), and it
    *is* the transferable concepts the AWS pass teaches.
  - **The one discipline that keeps the app portable:** never call the AWS SDK (`boto3`)
    from `app/`. Secrets reach the app only as plain env vars materialized into `.env` files
    at deploy time (5.2) — that `env_file` boundary is the portability seam. Keep all
    AWS-specific logic in the *deploy scripts*, never in application code, and the app half
    lifts-and-shifts with zero changes.
  - **Interim AWS cost lever (no migration):** the real lever is **right-sizing the
    instance**, not the model. A direct measurement (2026-07-14, `/usr/bin/time -l` on the
    pipeline venv) put the Essentia/TF runtime + model at **~277 MB for one instance and
    ~313 MB for both** — Essentia bundles a lightweight C++ TF backend, not Python
    `tensorflow`. The two model instances are **required, not a bug**: ingest reads output
    `PartitionedCall:1` (embeddings) and genre reads `PartitionedCall:0` off the same graph;
    consolidating to a single load is the deferred, higher-risk **P1/P2** work
    ([backend-optimization-deferred.md](../backend/agents/backend-optimization-deferred.md) —
    embeddings drive kNN recs, no equivalence-test infra), and the second load costs only
    ~36 MB anyway, so it is **not** a memory or cost lever. With a realistic full-host
    footprint of ~1–2 GB under load, size 6.1 at **`t3.medium` (4 GB, ~$30/mo)** rather than
    `t3.large`, add a 1-year Compute Savings Plan (~30–40% off), and you land near ~$20/mo
    with no architecture change.

---

## Critical-path summary (the deploy-blockers, in order)

1. Domain registered + DNS → Elastic IP (0.1, 6.4)
2. Alembic-only schema: baseline root + live-RDS reconcile/stamp, `create_all` removed
   (1.2, 10.1) — **highest risk**
3. `/health` endpoint (1.1)
4. Real-domain env + Spotify redirect URI registered (1.5, 1.6) — OAuth is dead without
   both
5. ECR repos + IAM roles + OIDC (0.3–0.5)
6. Fixed prod compose (no `db`, RDS env, restart/health) (3.x)
7. Prod nginx + first Certbot cert (4.x, 7.x)
8. Secrets in SSM incl. `TOKEN_ENCRYPTION_KEYS`, materialized at deploy (5.x)
9. Instance provisioned + bootstrapped (6.1–6.3)
10. CI → Build/ECR → Deploy/SSM (8.x)
11. HNSW index rebuilt — P5b launch gate (10.2)

Everything else hardens or observes; the eleven above are what stand between you and a
working production deploy. Phase 11 (email/Google login + search seeding) deliberately
sits **after** cutover — it's the pipeline's first workstream, not a launch blocker.
