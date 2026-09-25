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
>   *(Revised 2026-09-18: scope it with a condition on the tag instead,
>   `ssm:resourceTag/Project = putyouon`, which Terraform's `default_tags` puts on the
>   instance. A fixed instance ARN breaks CI deploys the first time the instance is
>   deliberately replaced, e.g. for a new AMI.)*
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

- [x] **5.1 Define a parameter namespace.**
  > **Code landed 2026-08-11.** The namespace is now defined *as code* in a new
  > [deploy/](../deploy/) dir: [deploy/ssm-parameters.md](../deploy/ssm-parameters.md) is the
  > authoritative manifest (every param, `SecureString` vs `String`, required?, notes), and
  > [deploy/ssm-seed.sh](../deploy/ssm-seed.sh) creates/updates them from a **gitignored**
  > local values file ([deploy/prod.env.example](../deploy/prod.env.example) is the committed
  > template; `deploy/prod.env` is ignored). **KMS decision: AWS-managed `alias/aws/ssm`**
  > (free, no `--key-id` needed) — so the Phase-0 `kms:Decrypt` placeholder tightens to that
  > key's ARN (`aws kms describe-key --key-id alias/aws/ssm`). Type split: SecureString for
  > `SESSION_SECRET`, `TOKEN_ENCRYPTION_KEYS`, `SPOTIFY_CLIENT_ID/SECRET`, `SENTRY_DSN`,
  > `POSTGRES_USER/PASSWORD/DB`; String for the endpoints/config. **`DAILY_LIMIT_BYPASS` is
  > not in the contract** — the seed script actively *skips* it (verified), so it can't reach
  > prod even if listed in the values file. The actual `put-parameter` calls are yours to run
  > (no AWS creds here); the tooling is tested (seed type-routing + unknown-key skip verified
  > against a fake `aws`).
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

- [x] **5.2 Materialize secrets at deploy time.**
  > **Code landed 2026-08-11.** [deploy/materialize-env.sh](../deploy/materialize-env.sh)
  > runs `aws ssm get-parameters-by-path --path /putyouon/prod --with-decryption --output
  > json` (JSON, not `--output text`, so URL/base64/special-char values survive; the CLI
  > auto-paginates so param count doesn't matter) and splits by name: `POSTGRES_*` →
  > `.env-postgres`, everything else → `.env-backend`, next to `docker-compose.prod.yaml`.
  > Parses with **python3** (present on AL2023) and writes raw `KEY=VALUE` (compose reads the
  > whole line after `=`, so no quoting; values may contain `=`/`#`). `umask 077` + explicit
  > `chmod 600`. **Fails loudly** if `TOKEN_ENCRYPTION_KEYS`/`SESSION_SECRET`/
  > `POSTGRES_PASSWORD` are missing — a misconfigured SSM becomes a failed deploy, not a
  > broken boot. **Verified end-to-end** with a fake `aws` returning canned JSON (including a
  > `p@ss#w=rd` password and a `k1=,k2=` token value): correct split, 600 perms, no
  > `POSTGRES_*` leak into the backend file, and the missing-required guard exits non-zero.
  > Phase 8's SSM step just calls this script on the instance.
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

- [x] **5.3 Keep `.env.example` authoritative, never commit real env.**
  > **Code landed 2026-08-11.** [backend/.env.example](../backend/.env.example) +
  > [backend/.env-postgres.example](../backend/.env-postgres.example) were already complete
  > (every var documented from Phases 1/2), so this was mostly upkeep: added a header pointer
  > from `.env.example` to [deploy/ssm-parameters.md](../deploy/ssm-parameters.md) (the prod
  > contract) so the two stay linked, and confirmed `.gitignore` keeps real env out — its
  > `.env*` rule doesn't match `deploy/prod.env` (name doesn't start with `.env`), so added an
  > explicit `deploy/prod.env` ignore while leaving the `deploy/prod.env.example` template
  > tracked.
  **How:** `.gitignore` already covers `.env-*` (keep it). Update
  [backend/.env.example](../backend/.env.example) whenever a var is added.
  **Why:** New contributors and the deploy script both rely on the example as the contract.

---

## Bonus Phase A — Multi-machine readiness & pre-Phase-6 prerequisites

> Inserted after the fact. Phases 1–5 were all **code** — they landed from one checkout
> and needed no AWS credentials. Phase 6 is the first phase that creates **real, billable
> AWS resources**, and it is the first that will be picked up from a **second machine**.
> Three things have to be true before that is safe, and none of them were in the original
> plan because the original plan assumed one machine and deferred every `aws` call.
>
> Do these in order. A.2 blocks Phase 6; A.3 does not, but is much cheaper to add now
> than after two machines have both pushed.

- [ ] **A.1 Bring the working machine up to full capability.**
  **How:** Follow [set_up_new_machine.md](set_up_new_machine.md). For Phase 6
  specifically only the *AWS / deployment work* section is required — AWS CLI v2 +
  credentials, the Session Manager plugin, a psql client, and Porkbun access. The app
  development section (fonts, mkcert, env files, venvs) can wait until you actually
  touch application code.
  **Why:** 6.2 closes port 22 entirely, so the Session Manager plugin is the *only*
  path to a shell on the instance — discovering it is missing while debugging a
  half-provisioned box is the worst time. The licensed fonts are gitignored and are a
  **build-time** input to `next/font/local`, so a machine without them cannot
  `docker compose build frontend` at all; that is invisible until the first frontend
  build.

- [x] **A.2 Seed the SSM parameters. (Blocks Phase 6.)**
  > **Done 2026-09-18.** Seeded from a new machine using CLI credentials for an IAM user,
  > not a root access key, in `us-east-1`. `SENTRY_DSN` was left blank on purpose: the seed
  > script skips empty values, so no parameter exists and
  > [main.py](../backend/app/main.py) skips Sentry init. To turn Sentry on later, fill it in
  > `deploy/prod.env`, re-run the seed, and redeploy.
  **How:** `cp deploy/prod.env.example deploy/prod.env`, fill in real production values,
  then `./deploy/ssm-seed.sh`. Verify with
  `aws ssm get-parameters-by-path --path /putyouon/prod --query 'Parameters[].Name'`.
  **Why:** Phase 5 is checked because the *tooling* landed — 5.1's own note says "the
  actual `put-parameter` calls are yours to run (no AWS creds here)". The namespace is
  still empty. Every later phase assumes it is populated: 5.2's `materialize-env.sh`
  fails loudly on a missing `TOKEN_ENCRYPTION_KEYS`/`SESSION_SECRET`/`POSTGRES_PASSWORD`,
  and 8.3 calls it on every deploy.
  **Risk:** `TOKEN_ENCRYPTION_KEYS` must be the key that encrypted the existing token
  rows in `pyo_db` — generating a fresh one silently orphans every stored Spotify token
  (they fail to decrypt at use, not at boot). Reuse, don't regenerate. `deploy/prod.env`
  is gitignored and will not sync between machines; after seeding, **SSM is the source of
  truth** — pull from it rather than keeping a second copy.

- [x] **A.3 CI workflow — test on every PR and push.** *(Pulled forward from 8.1.)*
  > **Landed 2026-09-18 (PR #11).** [.github/workflows/ci.yml](../.github/workflows/ci.yml)
  > runs `backend` (image build with GHA layer cache, pytest inside it as `app`) and
  > `frontend` (fonts from the private fonts repo, Node 20, lint, build) on every PR and
  > push to `main`. First run green on the PR: backend 2m23s (cold cache), frontend 35s.
  > Two corrections to the spec, both recorded below: the 8.1 test command (bare
  > `pytest` is off PATH for `app`), and the font claim in this item's Why. **Left for
  > 8.4:** make `backend` and `frontend` required checks on `main`.
  **How:** Exactly as specified in 8.1 below — build the backend image and run pytest
  inside it with the test files mounted back in, plus `npm ci` / `npm run lint` /
  `npm run build` for the frontend. No AWS involvement, so this has no dependency on
  Phase 6 or 7.
  **Fonts:** the runner's checkout has no licensed fonts (gitignored, and this repo is
  public), so `npm run build` would fail on every run. They live in the private repo
  `bframos8/put-you-on-fonts`; CI checks it out with a read-only deploy key (Actions
  secret `FONTS_DEPLOY_KEY`) and copies the files into `frontend/src/assets/fonts/`.
  Chosen over a private S3 bucket + OIDC role (keeps this item AWS-free and portable to
  the Hetzner move) and over an encrypted archive in this repo (would sit in public
  history for good). The stakes of a long-lived deploy key are low: the deployed site
  serves these same files to every visitor; the constraint is not redistributing them.
  **Why:** The original 8.1 rationale (test environment equals production) still holds,
  but there is now a second reason to do it *before* Phase 6 rather than after: with two
  machines able to push, "works on mine" is no longer verifiable by either one. CI builds
  from GitHub plus the fonts repo, never from either machine's disk, so it can't catch
  a missing font copy on one machine. What it does is give both machines one font
  source (the fonts repo), so drift can't happen in the first place. It also removes
  the host venv from the backend test path, since the same containerized command runs
  identically on both machines.

---

## Phase 6 — Provision & bootstrap the EC2 instance

> **Revised 2026-09-18 — read before any item below.** Three things changed since this
> phase was written:
> - **Terraform now owns Phase 6's resources** (6.0). The "gameplan checkboxes are the
>   infrastructure state file" rule in [set_up_new_machine.md](set_up_new_machine.md) no
>   longer applies to anything Terraform manages: remote state is the record, and
>   `terraform plan` from either machine shows what exists.
> - **The RDS instance no longer exists.** `put-you-on-instance-2` was deleted on
>   2026-09-08 with a final snapshot
>   (`final-put-you-on-instance-2e36d4fe0-ae3a-457a-9e19-36cd188f6067`: Postgres 16.13,
>   30 GB gp3, encrypted). The "already provisioned / live" wording in the locked
>   decisions, the old 6.5 text and 10.1 is stale. Decision: **restore the snapshot to a new RDS
>   instance, managed by Terraform** (6.5). The SSM `POSTGRES_HOST` seeded in A.2 still
>   names the deleted endpoint and must be updated to the new one.
> - **Sized down.** `t3.small` (2 GB) and a 12 GB root volume instead of `t3.medium` and
>   ≥30 GB (6.1). Both can grow later without rebuilding.
>
> The old instance's public IP (`32.196.93.110`) is still listed as an Elastic IP
> attached to the deleted database's leftover network interface. It is
> **service-managed by RDS** (`ServiceManaged: rds`), so the account can't move or
> release it; it should disappear on its own. If it is still there after 6.5, open an
> AWS support case, since public IPv4 addresses are billed.

- [x] **6.0 Terraform foundation (remote state in S3).**
  > **Landed 2026-09-18.** State bucket `putyouon-tfstate-b43f7b3a` (versioned,
  > SSE-S3, public access blocked), key `prod/terraform.tfstate`, S3 lock files.
  > Terraform 1.16.3, AWS provider 6.65.0. The lock file pins provider hashes for
  > darwin_arm64, darwin_amd64 and linux_amd64. **Gotcha hit on the first apply:** the
  > post-apply plan wanted to *replace* the database because `storage_encrypted` was
  > inherited from the snapshot but not declared (`true -> null # forces
  > replacement`). `prevent_destroy` turned that into a plan error instead of a
  > deletion. Declaring `storage_encrypted = true` fixed it, and the plan now reads "No
  > changes". Re-run `terraform plan` after every apply to catch this kind of thing.
  **How:**
  - **State bucket, created once by hand** (Terraform can't store its state in a bucket
    it hasn't created yet): a private S3 bucket in `us-east-1` with versioning on (so a
    bad state can be rolled back), default encryption, and all public access blocked.
    The name has a random suffix, not the account ID, because it is committed in the
    backend block of a public repo.
  - **Locking with S3 lock files** (`use_lockfile = true`, Terraform ≥ 1.10). No
    DynamoDB table.
  - **Code in [infra/](../infra/)**, one root module, no modules or workspaces (one
    environment). Commit `.terraform.lock.hcl` (pins provider versions for both
    machines); ignore `.terraform/` and any local `*.tfstate*`.
  - **What Terraform manages:** everything new in Phase 6 (instance, security groups,
    Elastic IP, RDS restored from the snapshot).
  - **What it only reads**, via data sources, never changes: the Phase 0 instance
    profile, the default VPC and subnet, the AL2023 AMI ID.
  - **What stays out of Terraform:** SSM parameter values (SecureStrings would sit in
    state in plain text, and `ssm-seed.sh` already owns them), the Porkbun `A` record,
    the Phase 0 IAM/OIDC/ECR resources (importable later with `import` blocks).
  - Plan and apply run from a dev machine. CI does not run Terraform yet.
  **Why:** Phase 6 is the first phase that creates billable resources that keep
  changing, and it is picked up from two machines. Remote state with locking means
  neither machine can create a second instance from a stale checkout, and every change
  is a reviewable diff instead of console clicks. The concepts carry over to the
  Hetzner move (the `hcloud` provider; `terraform init -migrate-state` moves state).
  **Rules:** read every plan before applying, especially `destroy` and `-/+`
  (replace) lines. Once a resource is in Terraform, change it only through Terraform.

- [x] **6.1 Launch the instance.**
  > **Landed 2026-09-18.** `i-073a4c379aed53c50` (`putyouon-app`), t3.small, us-east-1a.
  > At idle: 1.5 of 1.9 GB RAM available, 4.1 of 12 GB disk used (2 GB of that is the
  > swap file). The `mem_limit` and `prune -af` follow-ups below are still open.
  > **Revised 2026-09-18:** `t3.small` (2 GB), 12 GB gp3 root, AZ `us-east-1a` (same
  > AZ as RDS in 6.5, so app-to-DB traffic isn't billed as cross-AZ). Other settings:
  > - **AMI:** latest AL2023 x86_64 from its public SSM parameter, with
  >   `ignore_changes = [ami]`, so a new AMI release doesn't make Terraform replace the
  >   running instance.
  > - **Metadata:** IMDSv2 required, with a hop limit of 1 so containers can't reach
  >   the instance role's credentials.
  > - **CPU credits:** `standard`, so a sustained CPU burst throttles instead of adding
  >   a surprise "unlimited" bill.
  > - **Swap:** a 2 GB swap file.
  >
  > Disk budget: AL2023 plus Docker is about 2 GB. The images are about 1.9 GB
  > (backend 1.64 GB, frontend 0.2 GB, nginx 0.06 GB), about 3.8 GB at peak while a
  > deploy briefly holds two versions. Add 2 GB of swap, about 0.5 GB of logs, and about
  > 0.5 GB for the one-off `postgres:16` (6.5) and `certbot` (Phase 7) images, and the
  > peak is about 9 GB, which leaves roughly 25% headroom. gp3 grows online (modify
  > the volume, then `growpart` and `xfs_growfs`), so starting small is cheap to undo.
  >
  > **Two consequences to handle before the first deploy:**
  > - The backend's `mem_limit: 2g` in
  >   [docker-compose.prod.yaml](../docker-compose.prod.yaml) (3.4) equals all the RAM
  >   on this host, so it no longer protects anything. Measure the backend under a
  >   couple of concurrent ingests on the box, then set the cap below host RAM (likely
  >   ~1.2 GB). *(Set to `1200m` on 2026-09-20. **Measured after the first deploy:**
  >   backend 365 MB of the 1200m cap (30%), frontend 64 MB, nginx 6 MB; host 713 MB
  >   used of 1913 MB with swap untouched. The cap is comfortable — revisit only if
  >   concurrent ingests push it.)*
  > - 8.3's `docker image prune -f` removes only *dangling* images. SHA-tagged old
  >   images are not dangling, so they would pile up until the 12 GB disk fills. Use
  >   `docker image prune -af` there, which removes every image no container uses.
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

- [x] **6.2 Lock down the security group.**
  > **Landed 2026-09-18.** `putyouon-app` (80/443 in) and `putyouon-db` (5432 from
  > `putyouon-app` only). The SSM agent is online, so shell access works without SSH.
  > **Revised 2026-09-18:** two Terraform-managed groups.
  > - **`putyouon-app`** (instance): inbound 80 and 443 from `0.0.0.0/0`, IPv4 only, no
  >   22; all outbound, which the SSM agent, ECR pulls and Let's Encrypt need.
  > - **`putyouon-db`** (RDS): inbound 5432 **only from `putyouon-app`**, by
  >   security-group reference rather than IP.
  >
  > The restored database is **not publicly accessible** (the deleted one was), so the
  > only path to it is through the instance. From a laptop, reach it with an SSM
  > port-forwarding session through the instance.
  **How:** Inbound **80 + 443 from 0.0.0.0/0** only. **No port 22** — use **SSM Session
  Manager** for shell access. Ensure the **RDS security group allows 5432 from this
  instance's SG**.
  **Why:** Closing SSH removes the most-attacked port entirely; SSM gives audited,
  key-less shell access. The RDS rule is what lets the app reach the database.

- [x] **6.3 Install Docker Engine + Compose plugin; enable on boot.**
  > **Landed 2026-09-18.** Checked over SSM Run Command: cloud-init `done`, Docker
  > 25.0.14 enabled, Compose v5.5.1, 2 GB swap active, `/var/www/certbot` present, and
  > IMDS returns 401 without a token (IMDSv2 enforced).
  > **Revised 2026-09-18:** done at first boot by the instance's `user_data` (in
  > [infra/](../infra/)), not by hand.
  > - **Docker:** `dnf install docker`, enabled on boot.
  > - **Compose plugin:** AL2023's repos don't ship `docker-compose-plugin`, so it is
  >   downloaded from Docker's GitHub release, pinned to a version, and checked against
  >   the published SHA-256.
  > - **Also:** creates the swap file from 6.1 and the `/var/www/certbot` webroot
  >   (Phase 7).
  >
  > Deploys run as root through SSM Run Command, so there's no deploy user to add to the
  > `docker` group.
  **How:** Install `docker` and `docker-compose-plugin`, `systemctl enable --now docker`,
  add the deploy user to the `docker` group.
  **Why:** Compose runs your stack; enabling on boot means an instance reboot brings the app
  back automatically (with the `restart` policies from 3.3).

- [x] **6.4 Allocate an Elastic IP and point DNS at it.**
  > **Landed 2026-09-18.** Elastic IP `54.161.87.227` (Terraform output `elastic_ip`).
  > The Porkbun `A` record `putyouon.app -> 54.161.87.227` was added by hand, with no
  > `AAAA`. It resolves on 1.1.1.1 and 8.8.8.8, and the AAAA lookup is empty, so
  > Phase 7 can run Certbot.
  > **Revised 2026-09-18:** Terraform allocates and associates the Elastic IP and prints
  > it as an output. The Porkbun `A` record stays manual.
  **How:** Allocate + associate an Elastic IP; in **Porkbun's DNS panel** create an `A`
  record `putyouon.app → EIP` (add `www` as a second `A`/`CNAME` if you want it). Create
  **only** the `A` record — do **not** add an `AAAA`/IPv6 record: the box is IPv4-only, and
  a stray `AAAA` pointing at a non-listening address makes Certbot validation fail. Allow
  for DNS propagation before running Certbot in Phase 7.
  **Why:** Certbot and OAuth need a **stable** address. A default public IP changes on
  stop/start and would break TLS and redirects. Certbot's HTTP-01 challenge (Phase 7)
  needs the `A` record already resolving to the EIP.

- [x] **6.5 Restore RDS from the final snapshot, then verify it.**
  > **Landed 2026-09-18.** `putyouon-db`
  > (`putyouon-db.calaeskuuhry.us-east-1.rds.amazonaws.com`), restored in 8m22s. SSM
  > `POSTGRES_HOST` updated (version 2). Verified from the instance with the SSM
  > credentials over TLS:
  > - login works as `ramos` (the snapshot's password matches SSM)
  > - `vector` 0.8.1 is installed
  > - `alembic_version = b8c9d0e1f2a3`, as 10.1 expects
  > - 110,861 songs, all with embeddings; 2 users
  > - no HNSW index yet (10.2)
  >
  > **For 10.1:** the live unique constraint is named `songs_album_id_title_key`, while
  > 1.2's models declare `uq_songs_album_id_title`, so expect autogenerate to flag the
  > name after the stamp. The old public IP `32.196.93.110` was still present
  > afterwards.
  > **Revised 2026-09-18:** the database was deleted on 2026-09-08 (see the Phase 6 note),
  > so this item is now **restore, then verify**.
  > - **Restore:** Terraform creates `aws_db_instance` from the final snapshot as
  >   `db.t4g.micro` in `us-east-1a`, in the default DB subnet group, behind
  >   `putyouon-db`, not publicly accessible. The snapshot's 30 GB gp3 is the floor;
  >   storage can't shrink on restore. It keeps the snapshot's master user, password and
  >   KMS key.
  > - **Protection:** 7-day automated backups, `deletion_protection`, a final snapshot
  >   on delete, and `prevent_destroy`. Removing the block by mistake fails the plan
  >   instead of deleting the data.
  > - **Then:** update SSM `/putyouon/prod/POSTGRES_HOST` to the new endpoint (Terraform
  >   output) with `aws ssm put-parameter --overwrite`. The gitignored
  >   `deploy/prod.env` copy is then stale; SSM is the source of truth (A.2).
  > - **Sizing caveat:** `db.t4g.micro` has 1 GB of RAM. `songs.embedding` is
  >   `Vector(1280)`, about 560 MB raw for ~110k rows, so it can't stay cached. kNN
  >   seq scans read from disk until the HNSW index exists (10.2), and even then the
  >   index may not fit. If recommendation latency is bad, move to `db.t4g.small`
  >   (2 GB); it's an in-place modify with a few minutes of downtime.
  > - **CPU credits:** RDS T-class instances always run in *unlimited* mode (unlike
  >   the EC2 `standard` setting in 6.1, it can't be turned off). Sustained seq scans
  >   add surplus-credit charges on top of the latency. 9.2 should alarm on
  >   `CPUCreditBalance` / `CPUSurplusCreditsCharged`.
  > - **Credentials:** a restore keeps the snapshot's master user (`ramos`) and
  >   password. Test a login from the instance before relying on SSM's
  >   `POSTGRES_USER`/`POSTGRES_PASSWORD`. If it fails, reset the password through
  >   Terraform (`password_wo`, an in-place modify), not the console.
  > - **Verification** below is unchanged, but it runs **from the instance** (SSM
  >   shell, `docker run --rm -it postgres:16 psql …`), since the DB has no public
  >   address.
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

- [x] **7.1 Issue the initial certificate.**
  > **Landed 2026-09-19.** Certificate for **`putyouon.app`** (apex only, per 4.1):
  > ECDSA, serial `6c3e…f6f`, expires **2026-12-19**, at the
  > `/etc/letsencrypt/live/putyouon.app/` paths
  > [nginx.prod.conf](../nginx/nginx.prod.conf) already points at. Registered to
  > `bframoslopez@gmail.com`, so Let's Encrypt emails a warning if renewal ever breaks.
  >
  > AL2023 has no `certbot` package and no EPEL, so Certbot runs as the
  > `certbot/certbot` container with `/etc/letsencrypt`, `/var/lib/letsencrypt`,
  > `/var/log/letsencrypt` and `/var/www/certbot` mounted.
  >
  > **Bootstrap without the app stack:** ECR is still empty (8.2), so the compose stack
  > can't serve the challenge. A throwaway `nginx:alpine` container published :80 with
  > the webroot mounted, and was removed afterwards. That kept Phase 7 independent of
  > the 8.3 "get the repo files onto the box" gap.
  >
  > **Webroot, not standalone**, deliberately: Certbot records the authenticator in
  > `renewal/putyouon.app.conf` and repeats it at renewal. Standalone would need :80
  > free, which it won't be once nginx runs. Verified in order: probe file fetched over
  > the public internet, then a staging `--dry-run` (rate limits: 5 failures per
  > identifier per hour), then the real issue.
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

- [x] **7.2 Automate renewal + nginx reload.**
  > **Landed 2026-09-19.** `certbot-renew.timer` (enabled) runs `certbot-renew.service`
  > at 03:00 and 15:00 with up to an hour of jitter, `Persistent=true`. Definitions live
  > in [infra/user-data.sh](../infra/user-data.sh), so a rebuilt instance gets them; they
  > were installed on the running box by hand, since `ignore_changes = [user_data]`
  > means edits don't re-run on an existing instance.
  >
  > **Three deviations from the How below, each deliberate:**
  > - **`docker kill -s HUP` on the container, not `docker compose exec`.** The compose
  >   version needs the compose file's directory and its `BACKEND_IMAGE` variables, which
  >   a timer doesn't have (and 8.3 hasn't put on the box). The script finds nginx by its
  >   `com.docker.compose.service=nginx` label and no-ops when nothing is running.
  > - **A script, not an inline `ExecStartPost`.** systemd doesn't run Exec lines through
  >   a shell and would try to expand the `$`.
  > - **Not certbot's `--deploy-hook`**, which runs inside the certbot container and has
  >   no docker CLI or socket.
  >
  > **Verified:** `renew --dry-run` returned "Simulating renewal … (success)", which is
  > the real webroot path rather than a skipped no-op; `systemctl start
  > certbot-renew.service` finished with `Result=success`.
  >
  > **Two risks to watch:**
  > - **Nothing listens on :80 until the first deploy.** Renewal starts attempting at
  >   ~day 60 (2026-11-19) and will fail quietly against a closed port. Either deploy
  >   (Phase 8) before then, or add an expiry check in 9.2.
  > - **The certificate exists only on this instance's EBS volume.** Replacing the
  >   instance loses `/etc/letsencrypt`, and reissuing is capped at 5 per week for the
  >   same name. 10.4 should say: re-run 7.1's bootstrap after any instance rebuild.
  **Why:** Let's Encrypt certs last 90 days. Unattended renewal is the difference between
  "set and forget" and a site-down incident every quarter.

---

## Phase 8 — GitHub Actions CI/CD

> **The pipeline is live as of 2026-09-20.** A merge to `main` runs CI, then Deploy
> builds both images to ECR and rolls them out over SSM. First successful deploy:
> `c8408e0`, healthy after 2 health-check attempts. `https://putyouon.app` serves over
> a valid Let's Encrypt certificate, HTTP redirects to HTTPS, `/health` returns
> `{"status":"ok"}`, and the backend's security headers (incl. HSTS) are present on API
> routes. Two failures on the way, both recorded below: the missing buildx driver (8.2)
> and the `GetParametersByPath` resource ARN (8.3).

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
  > **Moved to [Bonus Phase A](#bonus-phase-a--multi-machine-readiness--pre-phase-6-prerequisites)
  > (A.3) — do it there, before Phase 6.** It has no AWS dependency, and with a second
  > machine pushing, CI is what keeps the two honest. The spec below is unchanged and
  > remains the authority on *how*; only the sequencing moved. Tick A.3, not this box.
  **How:**
  - **Backend:** build the backend image, then run the tests **in a container from that
    image**, mounting the test files back in (2.1 excludes them from the image, and pytest
    lives in [test-requirements.txt](../backend/test-requirements.txt), not the image):
    `docker run -v ./backend/tests:/app/tests -v ./backend/pytest.ini:/app/pytest.ini -v
    ./backend/test-requirements.txt:/app/test-requirements.txt <image> sh -c "pip install
    -r test-requirements.txt && python -m pytest -p no:cacheprovider"`. No extra env
    wiring needed — [conftest.py](../backend/tests/conftest.py) injects all required env
    vars. Cache pip layers.
    *(Corrected 2026-09-18: the original ended in a bare `pytest`, which fails with
    `pytest: not found`. The image runs as the non-root `app` user (2.2), so pip falls
    back to a user install and the `pytest` script lands in `~/.local/bin`, off PATH.
    `python -m pytest` imports the module instead. Running as `app` rather than
    `--user root` keeps the tests on the production user; `-p no:cacheprovider` only
    silences a warning about the root-owned `/app`. Verified: 146 passed.)*
  - **Frontend:** `npm ci`, `npm run lint`, `npm run build`.
  **Why:** Testing inside the built image means the test environment equals production — no
  "works in CI, breaks in the image" gaps, and it validates the image as a side effect.
  Installing `essentia-tensorflow` from scratch on a raw runner is slow and flaky; the image
  already has it. `npm run build` catches type/build breaks that lint misses. *(The
  `data_pipeline` suite is out of scope this pass but can be added later as a separate job.)*

- [x] **8.2 Build & Push workflow — on merge to `main`.**
  > **Landed 2026-09-20** as the `build` job of
  > [.github/workflows/deploy.yml](../.github/workflows/deploy.yml). OIDC into the 0.5
  > role, ECR login, both images pushed with the git SHA and `latest`, fonts from the
  > private repo (A.3), GHA layer cache on its own scopes so it doesn't race ci.yml's
  > backend build. The registry host comes from the ECR login output and the role ARN
  > from the `AWS_DEPLOY_ROLE_ARN` secret, so the AWS account id stays out of this
  > public repo (it is still visible in this public repo's **Actions logs**, where the
  > build command prints the registry — account ids aren't credentials, but don't
  > expect them to be hidden).
  > **Failed on the first run:** `cache-from/to: type=gha` needs buildx's container
  > driver, so the job must include `docker/setup-buildx-action` (ci.yml had it, this
  > didn't): *"Cache export is not supported for the docker driver"*, 18s in, nothing
  > built.
  **How:** Authenticate to AWS via **OIDC** (role from 0.5), `docker login` to ECR, build
  **backend** and **frontend** (the latter with
  `--build-arg NEXT_PUBLIC_API_URL=https://putyouon.app`), tag with both the **git SHA** and
  `latest`, and push to ECR. The frontend build needs the licensed fonts: fetch them
  exactly as the CI workflow does (checkout of `bframos8/put-you-on-fonts` with
  `FONTS_DEPLOY_KEY`, see A.3) before `docker build`, or the image build fails.
  **Why:** Immutable SHA tags make every deploy traceable and **instantly rollback-able**
  (re-point to the previous SHA). OIDC means no AWS keys in GitHub.

- [x] **8.3 Deploy workflow — `ssm:SendCommand` to the instance.**
  > **Landed 2026-09-20** as the `deploy` job plus
  > [deploy/deploy.sh](../deploy/deploy.sh), which runs on the instance. The 7 steps
  > below are unchanged; what the plan didn't say:
  > - **The 8.3 gap is closed by a git checkout.** The deploy installs `git` (not on the
  >   AMI), clones the public repo to `/opt/putyouon` once, then fetches and checks out
  >   the exact SHA being deployed, so the compose file, nginx config and scripts always
  >   match the images. Never `git clean` there: the materialized `.env` files live in
  >   that directory.
  > - **Triggered by CI completing, not by the push.** ci.yml also runs on push to
  >   `main`, so a `push` trigger would deploy while the tests were still running.
  >   Branch protection gates the merge, not the push after it. Because `workflow_run`
  >   reports `github.sha` as main's tip, everything keys off the CI run's `head_sha`.
  > - **Targeted by instance id, from a secret.** A tag-targeted `SendCommand` returns no
  >   instance id, and this role deliberately can't list invocations, so the result
  >   couldn't be polled.
  > - **`executionTimeout=7200`.** `--timeout-seconds` only bounds pickup, not runtime,
  >   and a cold first pull is ~1.9 GB.
  > - **Polled in a loop, not `aws ssm wait command-executed`**, whose waiter gives up
  >   after 100s and errors if the invocation doesn't exist yet.
  > - **Output goes to `/var/log/putyouon-deploy.log`** with only the interesting lines
  >   echoed, and the tail printed on failure: SSM returns at most 24,000 characters, and
  >   a pull's layer output would bury the actual error.
  > - **Step 7 is `docker image prune -af`** (see 6.1). The cost: a rollback re-pulls the
  >   previous image from ECR.
  >
  > **A Phase 0 permission gap the first deploy exposed:** `putyouon-ec2-ecr-ssm-read`
  > allowed `ssm:GetParametersByPath` on `parameter/putyouon/prod/*` only, but that API
  > authorizes against the **path node** (`parameter/putyouon/prod`, no `/*`), so
  > `materialize-env.sh` failed with `AccessDeniedException`. The policy (now v2) lists
  > both ARNs. Manual checks never caught it because they used `get-parameter`, a
  > different action. The deploy failed loudly at step 1 and changed nothing.
  >
  > **Prep done before the first deploy:** the `ssm:SendCommand` placeholder from 0.5 was
  > scoped to instances tagged `Project=putyouon` (as two statements — a single
  > conditioned statement would also gate the document ARN, which carries no tags, and
  > deny everything), and the backend `mem_limit` was lowered (3.4).
  >
  > **Original gap note (2026-09-18):** nothing puts the repo's runtime files on the instance.
  > The box needs `docker-compose.prod.yaml`, `nginx/nginx.prod.conf` (bind-mounted by
  > compose) and `deploy/materialize-env.sh` (which writes the env files next to the
  > compose file). `git` isn't on the AL2023 AMI either. Pick a fixed directory (e.g.
  > `/opt/putyouon`) and have the deploy script refresh those files there as step 0,
  > either with `dnf install git` + a clone/pull of the public repo at the deployed SHA,
  > or by copying them from S3. 10.1's stamp runs from the same directory. Also use
  > `docker image prune -af` in step 7 (see 6.1).
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

- [x] **8.4 Branch protection + required checks.**
  > **Landed 2026-09-20.** `main` requires the `backend` and `frontend` checks from
  > ci.yml and an up-to-date branch; no required reviewers (solo maintainer), no force
  > pushes, no deletion. The Deploy workflow is deliberately **not** a required check:
  > it doesn't run on PRs, so requiring it would block every merge.
  **How:** Require the CI workflow to pass and the branch to be up to date before merge to
  `main`.
  **Why:** Automated deploy from `main` is only safe if `main` is always green and reviewed.

---

## Phase 9 — Observability, backups, alarms

- [x] **9.1 Metrics + dashboards: follow the observability plan.**
  > **Landed 2026-09-23, deliberately reduced.** One agent, not three: a `grafana/alloy`
  > service in [docker-compose.prod.yaml](../docker-compose.prod.yaml) using Alloy's
  > **built-in unix exporter** ([observability/config.alloy](../observability/config.alloy)),
  > remote-writing host CPU/memory/disk/network to Grafana Cloud every 60s.
  > - **cAdvisor and the app's `/metrics` are deferred.** The box has 2 GB (6.1);
  >   cAdvisor is the heaviest of the plan's three agents and app instrumentation is a
  >   backend code change. This pass buys the thing that was actually blind: **disk**,
  >   which CloudWatch doesn't publish for EC2 at all.
  > - Alloy's built-in exporter replaces a separate node_exporter container. Measured
  >   ~52 MB against a 200m cap; the host mount is read-only.
  > - Not on the app network and the UI isn't exposed: it only talks outbound.
  > - Credentials: `GRAFANA_PROM_URL` / `_USER` / `_TOKEN` in SSM, routed by
  >   [materialize-env.sh](../deploy/materialize-env.sh) into a **third** env file,
  >   `.env-observability`, so a Grafana token never enters the app's environment.
  >   Seeding path updated: `ssm-seed.sh` allowlist, `prod.env.example`,
  >   [ssm-parameters.md](../deploy/ssm-parameters.md).
  > - Series count is ~1,000-1,300 at 60s, well inside the free tier's 10k.
  > - **Live 2026-09-24.** Credentials seeded (stack `prometheus-prod-36-prod-us-west-0`),
  >   Alloy restarted, WAL replayed and no send failures. *(First attempt shipped the
  >   placeholder endpoint from the example command and got HTTP 530 from Grafana's edge;
  >   the agent kept retrying from its WAL, so nothing was lost.)* The remote-write token
  >   is write-only, so confirm data in Grafana Explore, not by querying with it.
  **How:** Collection and dashboards are specified in
  [observability-plan.md](observability-plan.md) (locked: Grafana Cloud + a local Alloy
  agent scraping node_exporter, cAdvisor, and the app's `/metrics`; RDS via the CloudWatch
  *data source*). Do **not** add the CloudWatch agent — it would duplicate that collection
  layer on a RAM-tight box. (Container log size is already capped per 3.3.)
  **Why:** One collection stack, already decided and sized for this instance.

- [x] **9.2 Minimal alarms on the things that page you.**
  > **Landed 2026-09-23** in [infra/monitoring.tf](../infra/monitoring.tf): SNS topic
  > `putyouon-alerts` + email subscription, and 7 alarms, all confirmed `OK`.
  > **AWS-published:** EC2 status check, RDS free storage (<3 GB), RDS connections (>80
  > of ~112 max), RDS CPU credit balance (<30 — the unlimited-mode *cost* risk from 6.5).
  > **Self-reported**, because AWS can't see them: `putyouon-metrics.timer` publishes
  > `SiteUp`, `CertDaysRemaining` and `DiskUsedPercent` to `putyouon/instance` every 5
  > minutes (script + units in [user-data.sh](../infra/user-data.sh), installed on the
  > running box by hand since `ignore_changes = [user_data]`).
  > - **`SiteUp` uses `treat_missing_data = "breaching"`**, so a dead instance alarms
  >   instead of going quiet. That also means the metric must flow *before* the alarm
  >   exists: created in two stages (IAM + SNS, verify datapoints, then alarms).
  > - **`SiteUp` is published in its own API call.** `put-metric-data` rejects the whole
  >   call if any value is malformed, so a bad certificate reading must not be able to
  >   suppress the uptime signal and page falsely.
  > - `CertDaysRemaining < 20` closes the renewal blind spot from 7.2.
  > - Cost: $0 — 3 custom metrics and 7 alarms sit inside CloudWatch's always-free tier.
  > - **Subscription confirmed 2026-09-24**, so alarm notifications now deliver.
  **How:** The observability plan defers full alerting to its Phase 6, but keep a **tiny
  CloudWatch alarm set** on what's native without an agent: RDS free storage, RDS
  connections, EC2 status checks — plus an external uptime check on `/health`. (EC2
  **disk** is *not* a native CloudWatch metric; disk visibility comes from node_exporter
  in the Grafana stack — watch that dashboard until its alerting phase lands. 3.3's log
  caps and 8.3's image prune are the mitigations meanwhile.)
  **Why:** Dashboards don't page you. Disk-full and RDS-connection-exhaustion are the two
  most common ways this class of app falls over; these alarms read AWS-side metrics
  directly and don't touch the Grafana stack.

- [x] **9.3 Confirm RDS backups + test a restore.**
  > **Done 2026-09-23.** Automated backups confirmed: 7-day retention, daily snapshots,
  > point-in-time restore available. **Practice restore performed**, not just inspected:
  > the latest automated snapshot was restored to a scratch `db.t4g.micro`
  > (`putyouon-db-restoretest`, private, same SG) and queried from the instance. Every
  > figure matched production exactly — 110,861 songs all with embeddings, 89,075 albums,
  > 2 users, `alembic_version = 45f91add221e`, pgvector 0.8.1. The scratch instance was
  > then deleted with no final snapshot. Total cost, a few cents.
  **How:** Verify automated backups + retention on RDS; do one **practice restore** to a
  scratch instance.
  **Why:** A backup you've never restored is a hypothesis, not a backup. RDS makes this easy —
  use it.

---

## Phase 10 — Pre-launch verification & cutover

- [x] **10.1 Reconcile + stamp live RDS, then run migrations and verify schema.**
  > **Schema verified 2026-09-24, and 10.1 is closed.** `alembic current` on the live DB
  > returns `45f91add221e (head)`, and `alembic check` (the autogenerate diff, run from
  > the deployed backend image against prod) reports **no structural drift whatsoever** —
  > every table, column, type and `vector` column matches the models. That is the
  > "confirm tables/indexes/vector columns match" step, done by the tool rather than by
  > eye. The HNSW index correctly does *not* appear as a diff, because the models never
  > declare it (it is managed out-of-band; see the baseline's docstring and 10.2).
  >
  > **The only differences are two constraint NAMES**, both live-vs-models and neither
  > structural:
  >
  > | Live (Postgres auto-name) | Models (project convention) |
  > |---|---|
  > | `songs_album_id_title_key` | `uq_songs_album_id_title` |
  > | `albums_url_key` | `uq_albums_url` |
  >
  > The `songs` one was predicted in 6.5; **`albums_url_key` was not** — it surfaced
  > here. **This is a trap for 11.1:** the first `alembic revision --autogenerate` will
  > quietly fold four spurious operations (drop + re-add each constraint) into whatever
  > migration is being written. Delete them from the generated file unless you actually
  > intend to rename the constraints — and if you do intend it, do it as its own
  > migration, since re-adding `uq_songs_album_id_title` rebuilds a unique index over
  > 110k rows and takes a lock while it does.
  > **Stamp done early, 2026-09-20.** The deploy's `alembic upgrade head` could not work
  > until this landed, so it was pulled forward. Snapshot
  > `putyouon-db-pre-alembic-stamp-20260920` was taken first, then the single-row
  > `alembic_version` was moved from `b8c9d0e1f2a3` to `45f91add221e` with a guarded
  > `UPDATE ... WHERE version_num='b8c9d0e1f2a3'` (the column is `varchar(32)`, the
  > table had exactly one row, and the statement reported `UPDATE 1`) — the same single
  > write `alembic stamp` performs, done this way because the backend image didn't exist
  > in ECR yet. **Remaining here:** the first deploy runs `alembic upgrade head`, which
  > should be a no-op; that is the real confirmation. **Confirmed 2026-09-20:** the
  > first deploy's `alembic upgrade head` printed no `Running upgrade` lines, i.e. head
  > was already applied, so the stamp was right. Expect the first `--autogenerate`
  > after cutover to flag the constraint-name drift noted in 6.5.
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

- [x] **10.2 Finish P5b — rebuild the HNSW index (launch gate).**
  > **Done 2026-09-25. `songs_embedding_hnsw_idx` exists, 858 MB, valid and ready.**
  >
  > **The build took 2m37s, not the predicted hour.** Scaled RDS up with
  > `terraform apply -var 'db_instance_class=...'`, set
  > `max_parallel_maintenance_workers = 0` *before* `maintenance_work_mem` (the parallel
  > path allocates the full setting as a DSM segment up front — that is the DiskFull
  > that killed the earlier attempt; serial allocates lazily), then `CREATE INDEX` and
  > `ANALYZE`. No spill notice. The site stayed up the whole time: `CREATE INDEX` takes
  > only a SHARE lock, so reads never blocked, and only writes to `songs` would have.
  >
  > **`db.t4g.medium` was unavailable** — repeated `InsufficientDBInstanceCapacity` in
  > us-east-1a. Built on `db.t4g.small` instead: 1.61 GiB usable, 413 MiB
  > `shared_buffers`, ~1.2 GiB free against a ~650 MiB graph. Note that scaling up does
  > **not** raise `maintenance_work_mem` — RDS's default formula still yields 64 MB on a
  > bigger class, so the session `SET` is what does the work.
  >
  > **The index alone was not enough, and this is the real lesson.** With P5a's
  > `ef_search=100` the planner *rejected its own index*: pgvector's cost estimate scales
  > with `ef_search`, costing the index path 6978 against a sequential scan's 6052.
  > P5a raised `ef_search` because the pool under-filled — a job `iterative_scan` now
  > does properly — so the high value had become self-defeating. Dropping the genre
  > branch to `ef_search=40` costs 4262 and the planner picks the index on merit, with
  > no `enable_seqscan` hint. Measured on prod:
  >
  > | Plan | Time | Buffers |
  > |---|---|---|
  > | Before the index (cold, seq scan) | 8084 ms | 145,400, incl. 7.8 s disk |
  > | `ef=100`, index rejected | 86.7 ms | 79,403 |
  > | `ef=40`, HNSW index scan | **2.8 ms** | **1,778** |
  >
  > The middle row is the trap: 86 ms *looks* fine, but it is a sequential scan whose
  > cost was hidden by everything being cached on a temporarily larger instance. Buffer
  > count, not wall clock, is what predicts behaviour back on the small one.
  >
  > **Gate passed** on all three criteria: `Index Scan using songs_embedding_hnsw_idx`,
  > the full 50 rows (13 removed by filter), and **no Sort node** — the plan is a
  > `Nested Loop Left Join` driven by the index with `albums_pkey` inside, so index
  > order is preserved.
  >
  > **Rare genres deliberately still seq-scan.** At 0.65% selectivity (`ambient`, 722
  > rows) the planner prefers a parallel seq scan at 64 ms, which is correct: it
  > detoasts only the matching embeddings, and buffer traffic scales with matches. The
  > expensive case is the common genres, and those now get the index.
  > **Note 2026-09-18:** the RDS instance is now Terraform-managed (6.5), so do the
  > scale-up and scale-down by changing `instance_class` in
  > [infra/rds.tf](../infra/rds.tf) and applying. Resizing in the console would drift
  > from Terraform. The DB is also private now, so run the hour-long index build from
  > an SSM shell on the instance under `tmux` or `nohup`, not through an SSM
  > port-forward from a laptop (those drop on idle).
  **How:** Run the Path A runbook in
  [backend-optimization-remaining.md](../backend/agents/backend-optimization-remaining.md):
  scale RDS up, `CREATE INDEX … USING hnsw`, pass the EXPLAIN gate, scale back down, then
  land the query change. Coordinate with 10.1's stamp so the deploy pipeline never
  triggers the build itself.
  **Why:** The index is currently dropped — both kNN branches seq-scan. Launching without
  it means every recommendation request pays full-table-scan latency.

- [ ] **10.3 End-to-end smoke test.**
  > **Security headers on `/` fixed first, 2026-09-24.** The check below would have
  > failed: `https://putyouon.app/` returned only `x-powered-by: Next.js`, while
  > `/health` returned the full set. The headers come from the app's
  > `SecurityHeadersMiddleware`, so nothing proxied to Next.js ever got them — including
  > the origin's entry point, which is the hit that decides whether HSTS takes effect at
  > all. nginx now sets HSTS, `X-Content-Type-Options`, `Referrer-Policy` and
  > `X-Frame-Options` on `location /` only (a server-level set would duplicate them on
  > `/api/` and `/health`, since `add_header` appends). **CSP deliberately left out:** the
  > backend's `default-src 'none'` is right for JSON and would break every script, style,
  > font and image on a Next.js page. A real frontend policy is its own pass.
  **How:** Full Spotify OAuth round-trip on the real domain, a top-tracks fetch, and one ML
  ingest/classify call. Check security headers + HSTS and an SSL Labs scan.
  **Why:** OAuth, CORS, HSTS, and TLS only fully exercise against the real origin — this is
  the test the dev environment can't give you.

- [x] **10.4 Document the rollback procedure.**
  > **Written 2026-09-24: [deploy/runbook.md](../deploy/runbook.md).** Covers triage,
  > both rollback paths, migration rollback and snapshot restore, instance rebuild with
  > the certificate caveat, and what each alarm means. It contains no account id,
  > instance id or secret — every command looks them up, so it stays safe in a public
  > repo and survives an instance rebuild.
  >
  > Two things found while writing it, both now in the runbook:
  > - **The rollback window is about five deploys, not ten.** The ECR lifecycle policy
  >   keeps the last 10 manifests with `tagStatus: any`, and every build pushes *two* —
  >   the image plus an untagged ~40 KB buildx attestation. Measured: 14 manifests per
  >   repo, 6 tagged and 7 attestations. Tagged images do get expired. Worth fixing by
  >   counting only tagged images, or by turning off buildx provenance.
  > - **Code rollback does not undo a migration.** `alembic upgrade head` runs on every
  >   deploy and an older image will not downgrade. Stop deploys first, then downgrade or
  >   restore.
  > **Done 2026-09-24 (found 2026-09-23).** `docker compose` run by hand on the box used
  > to **fail**: the compose file uses `${BACKEND_IMAGE}` / `${FRONTEND_IMAGE}` (3.1),
  > which only existed inside [deploy/deploy.sh](../deploy/deploy.sh)'s environment, so a
  > plain `docker compose -f docker-compose.prod.yaml ps` errored with *"service backend
  > has neither an image nor a build context specified"* — mid-incident, which is exactly
  > when you reach for `ps`, `logs` or `down`. The deploy now writes both values to
  > `/opt/putyouon/.env` (atomically, mode 644 — image refs, not secrets), which compose
  > auto-loads for interpolation from the **compose file's** directory, so manual commands
  > work from anywhere on the box. It doubles as a record of the deployed SHA, which is
  > where a rollback starts. The exports still win during a deploy, so a stale file from a
  > failed run is inert; it does name the last SHA *attempted*, not necessarily the one
  > serving.
  >
  > **A second gap found while fixing it: the deploy never reloaded nginx.** `up -d` only
  > recreates a container whose *spec* changed, and nginx pins `nginx:alpine` with a
  > bind-mounted config — so an edit to `nginx.prod.conf` landed on disk via the checkout
  > and the running nginx, which reads its config once at startup, kept serving the old
  > one indefinitely. Visible in `docker ps`: nginx's uptime outlived every deploy. The
  > deploy now recreates the nginx container.
  >
  > A reload was tried first and **did not work**, for a reason worth remembering: the
  > config is a **single-file bind mount**, which Docker resolves by inode at container
  > start. `git checkout` replaces the file instead of editing it, so the new content
  > arrives on a new inode while the container keeps reading the old one, which survives
  > because the mount holds it. The HUP genuinely fired (the worker was replaced) and
  > reloaded the stale config; `nginx -t` inside the container "passed" because it was
  > testing that same old file. Measured 2026-09-24: 7 `add_header` lines on disk, 0 at
  > the identical path inside the container. Only recreating re-resolves the mount, so
  > the deploy uses `up -d --force-recreate --no-deps nginx` (`--no-deps` so it doesn't
  > also recreate the backend and frontend that step 5 just settled).
  **How:** Write down: re-run the Deploy workflow pinned to the previous image SHA; if a
  migration was destructive, restore from the RDS snapshot taken pre-deploy. Also cover
  **instance rebuild**: `/etc/letsencrypt` lives only on the instance's EBS volume, so a
  replaced instance has no certificate. Re-run 7.1's bootstrap (throwaway nginx on :80,
  `certbot certonly --webroot`) before bringing the stack up, and remember reissuing is
  capped at 5 per week for the same name.
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
