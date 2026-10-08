# Deployment Learnings — Concepts & Clarifications

**Companion to** [deployment-gameplan.md](deployment-gameplan.md). This captures the
questions worked through while doing the deployment and the clarified answers — a reference
for *why* each decision was made. A couple of entries note assumptions that got **corrected
by measurement**; those are flagged.

§1–§18 were written alongside Phases 0–5. §19–§27 were added on 2026-10-02, when Phase 10
closed, and cover provisioning through launch. Open follow-ups live in
[deployment-deferred.md](../deployment-deferred.md); the next release is
[pyo-0.0.1-sign-in-change.md](../pyo-0.0.1-sign-in-change.md).

**Context that shaped the answers:** single EC2 instance in `us-east-1`, RDS already live
(`pyo_db`), domain `putyouon.app`, deploying on AWS **deliberately to learn the ecosystem**,
with a planned later move to a cheaper stack (see §12).

---

## 1. Domains & DNS

- **Registrar ≠ DNS host.** Where a domain is *registered* and where its *DNS is hosted* are
  independent. Registered `putyouon.app` at Porkbun and use Porkbun's own DNS.
- **Porkbun vs Route 53.** Route 53's value is deep AWS integration (alias records to
  ALB/CloudFront/S3, ACM validation). For a single EC2 + one Elastic IP, the only record
  needed is one static `A` record → Porkbun DNS handles that trivially. Route 53 would be
  complexity for no benefit here. Revisit only if we scale out to an ALB (then migrate DNS
  to a Route 53 alias record).
- **FQDN (Fully Qualified Domain Name).** The complete spelled-out name (`putyouon.app`)
  that DNS resolves to the Elastic IP. CORS allow-lists and OAuth redirect URIs do
  **exact-string matching**, so they need a *stable* FQDN — a name that never changes. A raw
  public IP changes on stop/start (hence the Elastic IP), and browsers flag bare IPs.

## 2. `.app` is HTTPS-only (a Google TLD quirk)

`.app` is on the **HSTS preload list at the TLD level** — every browser refuses `http://`
for any `.app` host and forces `https://` before sending a byte.

- **Good for us:** reinforces `ENABLE_HSTS=true`; users are protected on their first visit.
- **Does NOT break Let's Encrypt HTTP-01.** LE's validator is *not a browser* and doesn't
  enforce HSTS — it reads the port-80 challenge fine. Keep webroot/HTTP-01; **don't** switch
  to DNS-01. (Confirmed on the LE community forum: "LE doesn't care whether your site uses
  STS Header or not.")
- **Can't browser-test over HTTP** during bootstrap — use `curl -v` or wait for HTTPS.
- **No `AAAA` record in Porkbun.** A stray IPv6 record pointing at a non-listening address
  makes Certbot validation fail; the box is IPv4-only, so `A` record only.

## 3. TLS & certificates

- **What TLS does:** two jobs — **encrypt** traffic (privacy) and **prove identity**
  (authenticity). The "S" in HTTPS.
- **Key pair:** a public key *locks*, a private key *unlocks*. The server hands out its
  public key; only its private key can participate in the encrypted channel. Padlock in the
  browser = valid cert.
- **What a certificate *is*:** a signed file binding **{domain name + public key}**
  together, signed by a **Certificate Authority** (Let's Encrypt). Browsers ship a built-in
  list of trusted CAs. The CA makes you **prove domain control** (the port-80 challenge)
  before it signs; that signature is unforgeable.
- **Chain of trust:** browser checks — signed by a CA I trust? domain matches? not expired?
  → then sets up the encrypted channel. The cert is the ID card; the key pair is the lock.
- **Why the app needs it:** browsers flag plain HTTP; Spotify OAuth *requires* HTTPS
  redirect URIs; HSTS demands it; secure session cookies won't send over HTTP.

## 4. Let's Encrypt & Certbot

- **Let's Encrypt** = a remote **Certificate Authority** — a service/API on the internet.
  You don't "install" it.
- **ACME** = the protocol used to talk to it.
- **Certbot** = the client **installed on the EC2 box** that speaks ACME to LE, proves
  domain control, receives the cert, and writes the files nginx reads. A systemd timer
  auto-renews every ~90 days.
- **Why not Porkbun's free cert?** It's the *same* Let's Encrypt cert. The only difference
  is delivery/renewal: Porkbun's is a **manual** download-and-reinstall every 90 days (built
  for managed hosting); Certbot on a server you control **renews itself forever**. Same cert,
  automated vs. manual — so we ignore the Porkbun perk.

## 5. Load balancing & scaling (ALB)

- **ALB (Application Load Balancer):** an AWS-managed Layer-7 traffic distributor that sits
  *in front of* multiple instances, health-checks them, and can terminate TLS.
- **Scale up (vertical):** a bigger instance. Do this **first** — zero architecture change.
- **Scale out (horizontal):** multiple instances behind an ALB + Auto Scaling Group. TLS
  moves to an **ACM** cert on the ALB (Certbot goes away), DNS moves to a Route 53 alias, and
  the app must be **stateless** (any request can land on any box). Watch: sessions (signed
  cookies fine; in-memory not), and OAuth state (must live in RDS/Redis, not in-process —
  this is the deferred **A1** work).
- Deferred for now; a single instance is correct until metrics say otherwise.

## 6. Region & architecture (Gameplan 0.2)

- **Region:** everything in **`us-east-1`** to co-locate with RDS. Cross-region adds latency
  + egress cost on every query. RDS is the fixed anchor; all else follows it.
- **Architecture:** **amd64/x86_64** (`t3`/`m5`), **not** Graviton/`t4g`.
  `essentia-tensorflow==2.1b6.dev1389` ships prebuilt wheels for **linux x86_64** but **not**
  linux aarch64 — on Graviton, pip would compile from source (painful). The GitHub runner +
  image + instance must all agree on amd64.
- **Why the M4 Mac works but Graviton wouldn't:** wheels are keyed on **(OS + architecture)
  together**. The Mac runs *natively on macOS*, so pip installs the `macosx_arm64` wheel
  (which exists). That's a *different artifact* from `linux_aarch64` (which doesn't exist for
  this version). The deploy runs **Linux**, where only x86_64 has a wheel. Verified on PyPI:
  macOS arm64 ✅, linux x86_64 ✅, linux aarch64 ❌.

## 7. Amazon Linux 2023 kernel: 6.1 vs 6.18

Both share the **same EOL (2029-06-30)** — support end date is *not* the differentiator.
6.18 has newer features/hardware support; **6.1 is the battle-tested default** with
FIPS-validated crypto. A Docker host on a mainstream `t3` needs nothing 6.18 adds → pick the
**x86_64, kernel-6.1 default AMI**. (Kernel choice is a Phase 6.1 launch detail, not 0.2.)

## 8. ECR & the two meanings of "image"

- **Album art** (pictures): the app stores only **URLs** (`image_url` column) pointing at
  Bandcamp/Spotify CDNs — it never hosts image files. No AWS image hosting (S3) needed. ✅
- **Container images** (Docker): the *built backend/frontend app artifacts*. These live in
  **ECR**, and that's what 0.3 creates.
- **Why ECR is required:** the deploy flow is *CI builds images → pushes to ECR → EC2 pulls
  and runs them*. Without a registry the instance has no way to receive the built app. ECR is
  private, IAM-controlled, and same-region (free pulls).

## 9. Cost reality & the free tier

This is **not** a free-tier deployment:
- Free-tier EC2 = `t2`/`t3.micro` (1 GB) only; the app needs more.
- Accounts created after **2025-07-15** get a **$100 credit for 6 months**, not the old
  12-month free tier.
- Public IPv4 / Elastic IP bills **~$3.65/mo** even when attached (since Feb 2024).
- ECR storage ~$1–3/mo (500 MB free for 12 months; the TF image busts that, but it's cheap).

**Where to run setup steps:** AWS Console UI, **CloudShell** (browser terminal,
pre-authenticated, no local setup), or local AWS CLI (`aws configure` first). Phase 0 was
done in the Console.

## 10. RAM sizing — measured, not guessed ⚠️ (corrected assumption)

The plan originally assumed **8 GB (t3.large)**. A direct measurement
(`/usr/bin/time -l` on the pipeline venv, 2026-07-14) showed:

| Scenario | Peak RSS |
|---|---|
| Runtime floor (essentia/TF, no model) | ~217 MB |
| One model loaded | ~277 MB |
| Two models (current state) | **~313 MB** |

Essentia bundles a **lightweight C++ TF backend**, not Python `tensorflow`, so the footprint
is far smaller than assumed. Realistic full-host footprint ~1–2 GB under load →
**start at `t3.medium` (4 GB, ~$30/mo)**, test `t3.small`.

**The two model loads are required, not a bug.** Ingest reads output `PartitionedCall:1`
(embeddings), genre reads `PartitionedCall:0` (genre) off the *same graph*. Consolidating to
one load is the deferred, higher-risk **P1/P2** work (embeddings drive kNN recs; no
numerical-equivalence test infra exists). The second load costs only **~36 MB**, so it is
**not** a memory or cost lever. *(This corrected an earlier wrong claim that "fixing H1
halves the RAM.")*

## 11. Offloading ML / cheaper compute (explored, deferred)

- **AWS Lambda:** cheaper *only if* ML is bursty **and** you also shrink the always-on box
  (Lambda compute is ~7× EC2 per active second; the win is dropping the base box, not Lambda
  being cheap). Traps: 15-min timeout, brutal cold starts on a multi-GB TF container, and the
  download+inference coupling (`spotdl`). It's a real refactor, outside the plan's
  minimal-change scope.
- **Outside AWS:** Google **Cloud Run** / **Modal** (scale-to-zero serverless containers,
  better fit than Lambda) for ML offload; **Hetzner** (CX33, 8 GB ~$7/mo, ~8× cheaper than
  `t3.large`) for the whole app; **Neon/Supabase** for managed Postgres with pgvector.
- **DB gravity:** RDS anchors compute. Moving compute off AWS means cross-cloud latency +
  egress unless the DB moves too.
- **GPU-serverless** (Replicate/RunPod/Baseten): **skip** — the model is small CPU inference;
  a GPU would cost *more*.

## 12. Portability & the planned migration

The **app + data** are portable; the **AWS glue** is not:
- **Transfers cleanly:** Docker images (repush to another registry), `docker-compose`,
  nginx/Certbot, DB *data* (`pg_dump` → `pg_restore` + rebuild HNSW), the `.env` contract,
  Grafana/Alloy observability.
- **Gets rebuilt:** ECR, IAM/OIDC, SSM secrets, SSM deploy, security groups/EIP/SSM-shell,
  RDS backups/alarms (Phases 0.4, 0.5, 5, 6, 8).
- **The one discipline that keeps the app portable:** never call the AWS SDK (`boto3`) from
  `app/`. Secrets reach the app only as plain env vars materialized into `.env` files at
  deploy time — that `env_file` boundary is the portability seam. Keep all AWS-specific
  logic in the *deploy scripts*.

Plan: do this AWS deployment to learn the ecosystem, then migrate to **Hetzner + Neon**
(~$10–20/mo) once learned.

## 13. IAM & OIDC (Gameplan 0.4 / 0.5)

- **Instance role (0.4):** an identity the EC2 box "wears," **trusted only by the EC2
  service**, letting it pull ECR images + read its own SSM secrets — **no static keys on the
  box**. = `AmazonSSMManagedInstanceCore` + a scoped custom policy
  (`putyouon-ec2-ecr-ssm-read`).
- **OIDC deploy role (0.5):** GitHub Actions assumes an AWS role via a **short-lived token**
  GitHub mints per run — no stored access keys (the #1 cloud-credential leak). Trust is
  scoped to `repo:bframos8/put-you-on:ref:refs/heads/main`, so only `main` in this repo can
  assume it. Permissions: ECR push + `ssm:SendCommand` (scoped to the `AWS-RunShellScript`
  document) + `ssm:GetCommandInvocation` (poll the deploy result and fail the job if the
  health gate fails).
- **Least-privilege pattern:** scope every action to specific resource ARNs, except the few
  that can't be scoped (`ecr:GetAuthorizationToken`, `kms:Decrypt`,
  `ssm:GetCommandInvocation` → `*`). Two placeholders were left intentionally broad and are
  tightened later — see the "Phase 0 provisioned" note in the gameplan (KMS key in Phase 5,
  instance ARN in Phase 6.1).

## 14. Branching & how changes reach prod (Gameplan 8 / 11)

- **The model the pipeline assumes: trunk-based (a.k.a. GitHub Flow).** `main` is always
  deployable and *is* prod. Every change = short-lived branch off `main` → PR → CI green →
  merge → build/push (8.2) → deploy (8.3). `Backend-optimization` is the one long-lived
  exception — it merges to `main` once at cutover; after that, per-item PRs (the Phase 11
  cadence).
- **Why "prod pulls images from main" can't collide with development:** the dev machine
  never touches ECR (local compose still `build:`s from whatever branch is checked out),
  and the instance never sees branches — it only pulls images that a `main` merge
  produced. Work-in-progress has **no code path to prod** except merging, which branch
  protection (8.4) + required CI (8.1) gate.
- **The honest gap: no staging environment.** The first place a built image runs "for
  real" is prod. Compensations already in the plan: CI runs pytest *inside the built
  image* (8.1), so the shipped artifact is the tested artifact; deploys are health-gated
  (8.3) and fail loudly; every image is SHA-tagged (8.2), so rollback = redeploy the
  previous SHA (10.4).
- **Want a promotion gate later? Add a GitHub Environment, not a branch.** Mark the
  deploy job `environment: production` with a required reviewer — every merge then builds
  and waits for an approval click before deploying. Same branch, two stages, one line of
  YAML. This is the modern "dev vs prod" split.
- **Git Flow (a standing `develop` branch + `main` as the prod branch) — considered,
  skipped.** It fits batched releases (versioned / app-store software) or a staging
  server tracking `develop`. For a continuously deployed web app it adds constant
  two-branch merge traffic, `develop`-vs-prod drift, and dual-landed hotfixes; DORA
  research correlates trunk-based flow with better delivery outcomes. Mechanics if ever
  wanted: `git checkout -b develop && git push -u origin develop`, set it as the default
  PR target, protect both branches, keep build/deploy workflows filtered to `main` —
  releasing = a `develop → main` PR.
- **How teams track what shipped: the PR is the unit of record.** Each PR says what/why
  and links its issue; branch protection makes the merged-PR list a complete, reviewed
  history of everything that reached prod. **SHA-tagged images** tie the running
  container back to one commit / one PR / one diff — audit trail and rollback lever in
  one. Optional on top: `git tag` + GitHub Releases for human-readable milestones
  (release notes auto-generated from merged PRs).

## 15. Docker image hardening (Gameplan Phase 2)

Concepts worked through while making the two images production-shaped. Per-item landing
notes live in the gameplan (2.1–2.5); this is the reusable *why*.

- **`.dockerignore` patterns are rooted at the build context, unlike `.gitignore`.** A bare
  `__pycache__/` or `*.pyc` in `.dockerignore` matches only the **top level** — nested
  `app/__pycache__` still enters the context. Use a `**/` prefix (`**/__pycache__/`,
  `**/*.pyc`) to match at any depth. (`.gitignore` matches any depth by default; the two
  formats look identical but resolve paths differently — an easy silent miss.)

- **`HEALTHCHECK` is a Dockerfile instruction, not a service or an endpoint.** It's a command
  Docker runs **inside the already-running container** on a schedule; a non-zero exit marks
  the container unhealthy. That "healthy" stamp is what `depends_on: service_healthy` and the
  deploy gate read. It hits the app's *existing* `/health` endpoint over `localhost` — nothing
  new listens.
  - **No `curl` in `python:*-slim` or `node:*-alpine`.** Rather than add a package (weight +
    CVE surface), reuse the interpreter already in the image: `python -c` (urllib) on the
    backend, `node -e` (http) on the frontend. A non-200 or connection error exits non-zero.
  - **`--start-period` covers slow boots** so startup isn't counted as failing — the backend
    needs it for the TF-model load (~tens of seconds); the frontend barely any.

- **Next.js standalone binds to `process.env.HOSTNAME` — and Docker injects
  `HOSTNAME=<container-id>`.** ⚠️ *(bug found while verifying 2.3.)* So `server.js` listened
  only on the container's own IP, and `localhost`/`127.0.0.1` got `ECONNREFUSED` — breaking
  the loopback healthcheck and making the bind fragile in general. Fix: `ENV HOSTNAME=0.0.0.0`
  in the runtime stage, so it accepts both the loopback probe and nginx's proxy to the
  container IP. A standard-but-easy-to-miss standalone-in-Docker gotcha.

- **`NEXT_PUBLIC_*` is inlined into the client JS bundle at BUILD time**, so it must be a
  `--build-arg`; a wrong value can't be corrected at runtime (the browser already has it).
  Several sub-lessons:
  - **A real env var wins over a `.env` file.** Next follows dotenv precedence — an
    already-set `process.env.NEXT_PUBLIC_API_URL` (from the Dockerfile `ENV`) is **not**
    overridden by a committed `.env.production`. Verified by grepping the built bundle: the
    build-arg value baked in, the `.env.production` value did not.
  - **A missing build-arg fails silently, not loudly.** ⚠️ *(fragility found while verifying
    2.5.)* With `ARG` and no default, an unpassed arg sets `ENV …=` to the **empty string**,
    which then shadows the `.env` file too — the bundle bakes an empty URL and every API call
    becomes relative to the frontend's own origin, with **no build error**. Fix: a builder
    guard `RUN test -n "$NEXT_PUBLIC_API_URL" || exit 1` before `npm run build` turns it into
    a loud failure CI catches.
  - **Keep local env files out of the build context.** Broaden `.dockerignore` to `.env*` so
    a stray local `.env.production` can't become a misleading second source of truth. (CI
    checks out a clean tree without gitignored env files, but a developer's local build
    would otherwise pull them in.)

- **Non-root: scope write access to only what needs it.** Both images run unprivileged
  (`app` on the backend, built-in `node` on the frontend). The backend writes downloaded
  audio to one dir (`app/services/downloads`), so *only* that dir is `chown`ed to `app`; the
  rest of `/app` stays root-owned and read-only — a compromised process can't rewrite app
  code. Defense in depth beyond just "not root."

- **Pin the tool, let its fast-moving dep float.** Pinned `spotdl` (was the only unpinned
  dep) for reproducible builds, but deliberately did **not** hard-pin its transitive `yt-dlp`
  — yt-dlp must float to keep pace with YouTube changes or downloads break. Pin the thing you
  control; let the thing that tracks a moving external target update.

- **Floating base tags vs digest pinning — a security/reproducibility tradeoff.** Kept
  `python:3.11-slim-bookworm` / `node:20-alpine` on their **tags**, not digests. A digest pin
  is perfectly reproducible but **freezes you on today's vulnerable OS layers** until someone
  manually bumps it; the floating tag pulls patched layers on each rebuild, which is what
  actually drains a base-image CVE backlog. Chose currency over bit-for-bit reproducibility
  here (the app deps are all version-pinned, so builds are still deterministic where it
  matters).

## 16. Production docker-compose (Gameplan Phase 3)

Concepts worked through building [docker-compose.prod.yaml](../../docker-compose.prod.yaml) and
repairing the dev compose. Per-item landing notes live in the gameplan (3.1–3.5); this is
the reusable *why*.

- **Two compose files, one topology difference: where the database lives.** The dev file
  runs a `pgvector` **container**; the prod file has **no db service** and points
  `POSTGRES_HOST` at RDS. Everything else (service names, network, the nginx proxy targets)
  stays identical so the same [nginx.conf](../../nginx/nginx.conf) upstreams resolve in both. Keep
  the *shape* the same across dev/prod; vary only what genuinely differs.

- **Parameterize the whole image ref, not just the tag.** `image: ${BACKEND_IMAGE}` (deploy
  supplies the full `<acct>.dkr.ecr…/backend:<sha>`) beats hardcoding the registry with a
  `:${IMAGE_TAG}` suffix. It keeps the AWS account id out of the repo — reinforcing the
  env_file/image boundary as the **portability seam** (§12): on the Hetzner move only the
  deploy script's exported vars change, the compose file doesn't. And because the *whole* ref
  is a variable, SHA-pinned rollback (10.4) is a pure env change, no file edit.

- **`depends_on: condition: service_healthy` is only as good as the image's `HEALTHCHECK`.**
  The condition reads the container's health stamp — which exists **because** 2.3 baked a
  `HEALTHCHECK` into both images. Ordering (frontend after backend-healthy, nginx after
  both-healthy) is therefore free here; on an image with no healthcheck the condition would
  hang forever. The two phases interlock: harden the image first, gate on it second.

- **`mem_limit` (classic key) vs `deploy.resources.limits` (swarm key).** Under plain
  `docker compose up` (not swarm), `mem_limit` is the reliable per-container cap;
  `deploy.resources` is honored by modern compose too but was historically swarm-only, so
  `mem_limit` is the unambiguous choice. Cap the **one** memory-risky service (backend +
  transient `spotdl`) so a runaway fails that container, not the box — the small
  frontend/nginx don't need caps.

- **A shared ACME webroot doesn't need a certbot *container*.** Certbot runs on the **host**
  (Phase 7), writes the HTTP-01 challenge into `/var/www/certbot`, and nginx bind-mounts that
  host dir **read-only** to serve it. No compose service, no volume plumbing between
  containers — the host filesystem is the shared medium. `/etc/letsencrypt` mounts the same
  way (`:ro`; nginx only reads certs).

- **Compose `config` interpolates host env at *parse* time — use `$$` to defer to the
  container.** The dev db healthcheck `pg_isready -U $$POSTGRES_USER` needs the doubled `$`
  so compose passes a literal `$POSTGRES_USER` through to the container, where it resolves
  from `.env-postgres`. A single `$` would expand (to empty) in the host shell during
  `docker compose config`. Same rule as any compose value that must survive to runtime.

- **Phase boundary discipline: 3.5 wires nginx, Phase 4 writes nginx.conf.** The prod compose
  mounts Let's Encrypt certs and opens 80+443, but the *config file* still points at the dev
  mkcert pems with no server_name/redirect. That's intentional sequencing, not a bug — the
  prod stack isn't run until the instance exists (Phase 6+), so the interim mismatch never
  executes. Split work along the plan's phase lines even when it leaves a file temporarily
  inconsistent with its mounts.

## 17. Production nginx config (Gameplan Phase 4)

Concepts worked through writing [nginx.prod.conf](../../nginx/nginx.prod.conf). Per-item landing
notes live in the gameplan (4.1–4.4); this is the reusable *why*.

- **Two config files, split on what actually differs: the cert paths.** dev
  [nginx.conf](../../nginx/nginx.conf) reads mkcert `/certs/localhost+1.pem` on `:443` only; prod
  [nginx.prod.conf](../../nginx/nginx.prod.conf) reads the real LE cert and adds the `:80`
  redirect/ACME server. Considered one templated file with the nginx image's
  `envsubst`/`/etc/nginx/templates` mechanism, but a static file per environment is simpler
  and mirrors the two-compose split. Everything cert-*independent* (forwarded headers,
  `/health`, gzip, `/api` timeouts) was **backported to dev** so both exercise the same
  proxying — keep dev and prod behaviourally aligned, vary only the irreducible difference.

- **Set shared `proxy_set_header`s once at `http` level; they inherit downward — but any
  `proxy_set_header` in a narrower block resets the whole set.** nginx directive inheritance
  is by *replacement, not merge*: a `location` that adds even one `proxy_set_header` silently
  drops all the inherited ones. So the four forwarded headers live at `http` scope and the
  `location`s add only `proxy_pass`/`proxy_*_timeout` (non-`proxy_set_header` directives,
  which don't trigger the reset). DRY and correct; adding a per-location header later means
  re-adding all four there.

- **The forwarded headers are load-bearing, not cosmetic.** `X-Forwarded-For`/`-Proto` are
  exactly what uvicorn's `--proxy-headers` (1.4) consumes so `slowapi` rate-limits by real
  client IP instead of collapsing every login attempt into one site-wide nginx-IP bucket.
  nginx setting only `Host` (the old config) quietly defeats the per-user login limits.

- **Don't duplicate a header two layers set.** HSTS is emitted by the app's `ENABLE_HSTS`
  middleware; adding `add_header Strict-Transport-Security` in nginx too would send it twice.
  One authority per header — here, the app owns HSTS, nginx owns TLS.

- **OCSP stapling is now dead config on Let's Encrypt certs.** LE **retired OCSP in 2025** —
  newly issued certs carry no OCSP URL — so `ssl_stapling on;` does nothing but log
  `ssl_stapling ignored, no OCSP responder URL` on every reload. Omitted it (and its
  `ssl_trusted_certificate`/`resolver` scaffolding) rather than ship a directive the gameplan
  named from an earlier era. A reminder to re-check a plan's *specific* directives against the
  CA's current behaviour, not just copy the recipe.

- **ECDHE-only ciphers dodge the `ssl_dhparam` dependency.** Mozilla "intermediate" lists DHE
  suites, which need a generated `dhparam.pem` mounted on the host. Dropping DHE for an
  ECDHE-only list keeps an SSL Labs A+ with **zero extra host artifacts** — one fewer thing to
  generate in Phase 6/7 and mount. TLS 1.3 (which doesn't use these suites at all) covers
  modern clients regardless.

- **Validating an nginx config offline: `nginx -t` needs two things faked, and crossplane is
  the fallback when Docker itself is down.** `nginx -t` in a disposable `nginx:alpine` is the
  real (semantic) check, but two things trip it in isolation:
  - **It stats the `ssl_certificate` files.** Generate a throwaway self-signed cert on the
    host and bind-mount it at the exact paths
    (`/etc/letsencrypt/live/putyouon.app/{fullchain,privkey}.pem`) — the same "fake the
    environment the check demands" trick as the Phase-2 busybox build-context probes.
  - **It resolves literal upstream hostnames at config-load.** `proxy_pass http://backend:8000;`
    makes `nginx -t` do a DNS lookup for `backend`; in a standalone container that isn't on the
    compose network it fails `[emerg] host not found in upstream "backend"` — a *test artifact,
    not a config bug*. Fix with `--add-host backend:127.0.0.1 --add-host frontend:127.0.0.1`
    (or run it on the compose network) so the names resolve.
  - **When Docker's runtime can't even start a container** (it happened this session — `docker
    ps`/`images` worked but `docker run` hung on *any* image, fixed only by a Docker Desktop
    update), fall back to **crossplane** (`pip install crossplane`), nginx Inc's own parser:
    `crossplane.parse(path, strict=True)` checks braces, directive contexts, and arg counts
    against nginx's directive map with no nginx, root, or certs needed. Its blind spot is
    version lag — crossplane 0.5.8's map predates nginx 1.25.1, so it strict-flags the modern
    `http2 on;` as "unknown" (a false positive later confirmed against `nginx -t` on 1.29.7).
    crossplane validates *structure*; only `nginx -t` also validates *semantics* — treat a
    clean crossplane parse as necessary-but-not-sufficient.

## 18. Secrets in SSM Parameter Store (Gameplan Phase 5)

Concepts from wiring [deploy/](../../deploy/) — the SSM seed + materialize scripts. Per-item
landing notes live in the gameplan (5.1–5.3); this is the reusable *why*.

- **The `env_file` boundary is the portability seam — keep all AWS in the deploy scripts.**
  The app reads plain env vars and never calls `boto3`. Secrets reach it only as
  `.env-backend`/`.env-postgres` files that [materialize-env.sh](../../deploy/materialize-env.sh)
  writes from SSM at deploy. That one script is the entire AWS-secrets surface: swap it for
  SOPS/Doppler/plain files and the app half lifts to Hetzner/Neon unchanged (§12).

- **Flat SSM path, split into two files by name prefix.** Params live flat at
  `/putyouon/prod/NAME`; the materializer routes `POSTGRES_*` → `.env-postgres` (the file the
  dev `db` service also reads) and everything else → `.env-backend`, matching the two
  `env_file:` entries. In prod the split is cosmetic (the backend loads both), but keeping it
  makes each file's contract match its `.example`.

- **Parse SSM as JSON, not `--output text`.** Values carry URLs, base64 Fernet keys, and
  arbitrary passwords — tabs/spaces/newlines mangle `--output text`. `--output json` + a
  python3 pass is robust, and the AWS CLI **auto-paginates**, so all params return in one
  `Parameters[]` regardless of the 10-per-page API default (a raw API call would need
  `NextToken`).

- **compose `env_file` reads the whole line after `=` — so write raw `KEY=VALUE`, no quotes.**
  A password like `p@ss#w=rd` or a `TOKEN_ENCRYPTION_KEYS=k1=,k2=` value round-trips
  correctly because the materializer only splits the *name* off the front and never quotes.
  Quoting would be wrong here (compose would treat the quotes as literal). Verified against a
  fake `aws` returning those exact tricky values.

- **Make a misconfig a failed *deploy*, not a broken *boot*.** The materializer exits
  non-zero if `TOKEN_ENCRYPTION_KEYS`/`SESSION_SECRET`/`POSTGRES_PASSWORD` are missing, so an
  incompletely-seeded SSM path fails the deploy step loudly instead of producing env files
  that crash the container after `up -d`. Fail as early and as loudly as the pipeline allows.

- **Encode the "never in prod" rule where it's enforced, not just documented.**
  `DAILY_LIMIT_BYPASS` isn't in the seed script's key lists, so the script *actively skips* it
  ("unknown key") even if an operator pastes it into the values file — the guard is
  executable, not a comment. Same spirit as the app's startup warning: defense at every layer.

- **A file that doesn't start with `.env` isn't caught by an `.env*` gitignore rule.**
  `deploy/prod.env` holds real secrets but `.env*` only matches names *beginning* with `.env`
  (path components), so it slipped through — added an explicit `deploy/prod.env` ignore. The
  committed template `deploy/prod.env.example` is safe (ends in `.example`, no real values).
  Verify a new secret-bearing filename is actually ignored; don't assume a broad-looking glob
  covers it.

- **Testing AWS-calling scripts without AWS: a fake `aws` on `PATH`.** Both scripts shell out
  to `aws`; dropping a tiny `aws` shim (that prints canned `get-parameters-by-path` JSON, or
  echoes the `put-parameter` `--name/--type`) into a dir prepended to `PATH` exercises the
  real parse/split/route/permission logic end-to-end with zero AWS creds — the same
  "fake the environment the check demands" pattern used for the nginx and build-context checks.

## 19. Terraform & working from two machines (Gameplan Bonus A, 6.0)

- **The state bucket is the one thing Terraform can't create.** It was made by hand:
  versioned (so a bad state can be rolled back), encrypted, public access blocked. Its name
  has a random suffix rather than the account id, because it is committed in the backend
  block of a public repo. Locking uses S3 lock files (`use_lockfile = true`, Terraform
  ≥ 1.10), so no DynamoDB table is needed.

- **Re-run `terraform plan` after every apply.** The first apply restored RDS from a
  snapshot, and the follow-up plan wanted to *replace* the database: `storage_encrypted` was
  inherited from the snapshot but not declared, which reads as `true -> null # forces
  replacement`. `prevent_destroy` turned that into a plan error instead of a deletion.
  Declaring the attribute fixed it. Anything a restore or import inherits has to be
  written down, or the next plan tries to "correct" it.

- **Some things stay out of Terraform on purpose.** SSM SecureString values would sit in
  state in plain text, so the seed script owns them. The Porkbun `A` record is manual.
  Phase 0's IAM/OIDC/ECR resources can be imported later with `import` blocks.

- **`ignore_changes = [user_data]` (and `[ami]`) means edits never reach the running box.**
  That stops Terraform replacing the instance for a new AMI or a script tweak, but it also
  means every later change to [user-data.sh](../../infra/user-data.sh) (the certbot timer, the
  metrics timer) had to be installed on the live instance by hand as well. The file is
  the record for a *rebuilt* instance, not for the current one.

- **After the first seed, SSM is the source of truth, and the local values file drifts.**
  `deploy/prod.env` is gitignored and does not sync between machines. By 10.8 it held a
  `SENTRY_DSN` SSM did not have and lacked the three `GRAFANA_*` keys SSM did. Re-running
  the full seed would have pushed stale values over live ones. Change one parameter with
  `aws ssm put-parameter --overwrite`, never re-seed the lot.

- **The seed script silently skips keys it doesn't know** (exit 0, one stderr line). That
  is the guard that keeps `DAILY_LIMIT_BYPASS` out of prod (§18), and also why every new
  parameter (`INGEST_WORKER_TOKEN`, `INGEST_WORKER_ENABLED`) must be added to its
  allowlists or the backend boots without it.

- **Reuse `TOKEN_ENCRYPTION_KEYS`, never regenerate it.** A fresh key boots fine and then
  fails to decrypt every stored Spotify token at the moment of use, not at startup.

## 20. Provisioning EC2 and RDS (Gameplan Phase 6)

- **Size from measurement, then re-check every limit that assumed the old size.** The
  instance went to `t3.small` (2 GB) on the strength of §10's measurements, and the
  backend's `mem_limit: 2g` then equalled all the RAM on the host, so it protected nothing.
  Lowered to `1200m`; measured after launch at 365 MB backend, 64 MB frontend, 6 MB nginx,
  swap untouched.

- **IMDSv2 with a hop limit of 1** stops containers reaching the instance role's
  credentials. The hop limit is the part that matters: a container is one network hop
  further away than the host.

- **CPU credit modes differ between EC2 and RDS.** EC2 is set to `standard`, so a sustained
  burst throttles instead of billing. RDS T-class instances are *always* unlimited and
  can't be switched, so sustained seq scans cost money on top of latency. That is why
  §23's alarm set includes the RDS credit balance.

- **`docker image prune -f` only removes dangling images.** SHA-tagged old images are not
  dangling, so they pile up until a 12 GB disk fills. The deploy uses `-af`. The cost: a
  rollback re-pulls the previous image from ECR.

- **A restored RDS keeps the snapshot's master user, password and KMS key, and its
  storage size is a floor** (30 GB here, even though the data is far smaller). Test a
  login from the instance before trusting SSM's credentials.

- **Private database, reached through the instance.** The restored DB is not publicly
  accessible, and its security group admits 5432 only from the app's security group (by
  reference, not IP). From a laptop, use an SSM port-forward through the instance. For
  anything long-running (the HNSW build), use an SSM shell on the instance under `tmux`,
  because port-forwards drop on idle.

- **AL2023 leaves things out.** No `docker-compose-plugin` in its repos (downloaded from
  Docker's release, pinned and checked against the SHA-256), no `git`, no `certbot`, no
  EPEL. Expect to fetch or containerize each.

- **A deleted RDS can leave a public IPv4 you can't release.** The old instance's Elastic
  IP stayed attached to a leftover network interface, `ServiceManaged: rds`. The account
  can't move or release it; public IPv4 is billed, so open a support case if it lingers.

## 21. Issuing and renewing the certificate (Gameplan Phase 7)

- **Bootstrap TLS without the app stack.** ECR was still empty, so a throwaway
  `nginx:alpine` served the ACME webroot on :80 and was removed afterwards. That kept the
  certificate independent of the deploy pipeline.

- **Webroot, not standalone.** Certbot records the authenticator and repeats it at
  renewal. Standalone needs :80 free, which it won't be once nginx runs.

- **Spend Let's Encrypt's rate limits carefully.** In order: fetch a probe file over the
  public internet, then a staging `--dry-run`, then the real issue. Failures are capped at
  5 per identifier per hour, and reissuing the same name at 5 per week, which matters
  because the certificate lives only on the instance's EBS volume. Rebuild the instance
  and you reissue.

- **The renewal reload is harder than it looks.** `docker compose exec` needs the compose
  directory and its image variables, which a systemd timer doesn't have. systemd doesn't
  run `ExecStartPost` through a shell, so `$` doesn't expand. Certbot's `--deploy-hook`
  runs inside the certbot container, with no Docker socket. What works: a script that
  finds nginx by its `com.docker.compose.service=nginx` label and sends `docker kill -s
  HUP`, and no-ops when nothing is running.

- **An ECDSA certificate only ever negotiates ECDSA suites.** The SSL Labs scan (A+) lists
  no RSA suites even though `ssl_ciphers` names them; they'd matter only if the cert
  became RSA. No OCSP stapling either, since Let's Encrypt retired OCSP (§17).

## 22. CI/CD in practice (Gameplan Phase 8)

- **`cache-from/to: type=gha` needs buildx's container driver.** Without
  `docker/setup-buildx-action` the build fails 18 seconds in with "Cache export is not
  supported for the docker driver". ci.yml had it; deploy.yml didn't.

- **Deploy on CI *completion*, not on the push.** ci.yml also runs on push to `main`, so a
  `push`-triggered deploy would ship while tests were still running. `workflow_run` fixes
  that, with a catch: it reports `github.sha` as main's current tip, so everything has to
  key off the CI run's `head_sha` instead.

- **`ssm:GetParametersByPath` authorizes against the path itself** (`parameter/putyouon/prod`,
  no `/*`). A policy granting only `parameter/putyouon/prod/*` passed every manual check,
  because those used `get-parameter`, a different action. The first deploy failed at step
  1 with `AccessDeniedException` and changed nothing. Test permissions with the exact API
  the automation calls.

- **A tag condition on `ssm:SendCommand` also gates the document ARN,** which carries no
  tags, so a single conditioned statement denies everything. Split it into two
  statements.

- **Polling SSM Run Command has its own traps.** A tag-targeted `SendCommand` returns no
  instance id to poll, so the deploy targets an id from a secret. `--timeout-seconds`
  bounds pickup, not runtime (`executionTimeout=7200` does the latter). `aws ssm wait
  command-executed` gives up after 100 s. Output is capped at 24,000 characters, so the
  full log goes to a file on the box and only the tail comes back on failure.

- **Inside the image, run `python -m pytest`.** The image runs as the non-root `app` user,
  so pip falls back to a user install and the `pytest` script lands off PATH.

- **GitHub occasionally drops a push event.** The merge of `c69c40b` triggered no CI and
  no deploy. An empty commit re-triggers both. To redeploy the *same* commit (for example,
  to pick up a changed SSM value), `gh run rerun` on the last Deploy run does it with no
  commit at all, because every deploy re-materializes SSM.

- **The AWS account id shows in public Actions logs** (the registry host). It isn't a
  credential, but don't expect it to stay hidden.

- **Every commit deploys, including docs.** There's no path filter, so a change that only
  touches `worker/` or `claude-mds/` still builds and rolls out both images. Accepted
  for now.

## 23. Observability, alarms and backups (Gameplan Phase 9)

- **Buy the blind spot first.** EC2 publishes no disk metric to CloudWatch at all. With
  2 GB of RAM, one Grafana Alloy container using its built-in unix exporter (~52 MB) was
  chosen over the planned node_exporter + cAdvisor + app `/metrics`. Disk was the thing
  actually missing; the rest is deferred.

- **Keep observability credentials out of the app's environment.** Grafana's token goes to
  a third env file, `.env-observability`, read only by Alloy.

- **The Grafana remote-write token is write-only.** Confirm data arrives in Grafana
  Explore, not by querying with the token. The first attempt shipped the placeholder
  endpoint and got HTTP 530. Alloy kept retrying from its write-ahead log, so nothing was
  lost.

- **Alarm on a dead instance by alarming on silence.** `SiteUp` uses
  `treat_missing_data = "breaching"`, so a box that stops reporting alarms instead of going
  quiet. That forced a two-stage rollout: the metric had to be flowing before the alarm
  existed, or it would fire on creation.

- **Publish the uptime metric in its own API call.** `put-metric-data` rejects the whole
  call if any value is malformed, so a bad certificate-days reading must not be able to
  suppress `SiteUp` and page falsely.

- **A backup you've never restored is a hypothesis.** The practice restore to a scratch
  `db.t4g.micro` matched production exactly (row counts, alembic head, pgvector version)
  and cost a few cents.

- **ECR lifecycle rules count attestations.** "Keep the last 10" with `tagStatus: any`
  keeps about five deploys, because every buildx build pushes the image *and* an untagged
  provenance manifest. The rollback window is half of what the rule seems to say.

## 24. Operating the box (Gameplan 10.3, 10.4)

- **A single-file bind mount is pinned by inode.** `git checkout` replaces
  `nginx.prod.conf` rather than editing it, so the new content lands on a new inode and
  the running container keeps reading the old one. A HUP reloads the stale file, and
  `nginx -t` inside the container "passes" because it tests the same stale file. Measured:
  7 `add_header` lines on disk, 0 at the same path inside the container. Only recreating
  the container re-resolves the mount, so the deploy runs
  `up -d --force-recreate --no-deps nginx`.

- **`up -d` only recreates containers whose spec changed.** nginx pins `nginx:alpine` and
  bind-mounts its config, so before the fix above its uptime outlived every deploy.

- **Make manual `docker compose` work on the box.** The compose file interpolates
  `${BACKEND_IMAGE}`, which used to exist only inside the deploy script, so `ps` and
  `logs` failed mid-incident. The deploy now writes those values to `.env` next to the
  compose file, which compose auto-loads. That doubles as a record of the last SHA
  attempted.

- **Headers set by app middleware never reach pages the app doesn't serve.** HSTS and
  friends were on `/health` and `/api/` but missing from `/`, which is proxied to Next.js.
  nginx now adds them on `location /` only, because `add_header` at server level would
  duplicate them on the backend's routes. CSP is left out: the API's `default-src 'none'`
  would break every page.

- **Rolling back code doesn't roll back a migration.** `alembic upgrade head` runs every
  deploy and an older image won't downgrade. Stop deploys first, then downgrade or
  restore. Take a snapshot before every merge that carries a migration (two through
  the pipeline so far, both clean).

- **Runbook commands look things up instead of hard-coding them.** No account id, instance
  id or secret in [runbook.md](../../deploy/runbook.md), so it is safe in a public repo and
  survives an instance rebuild.

## 25. Schema and pgvector at launch (Gameplan 10.1, 10.2, 10.5)

- **`alembic stamp` writes one row and creates nothing.** It moved the live database
  onto the squashed baseline without touching tables. Done early, as a guarded
  `UPDATE ... WHERE version_num = '<old>'` (`UPDATE 1`), because the backend image didn't
  exist yet. The first deploy's `upgrade head` printing no `Running upgrade` lines was the
  confirmation.

- **`alembic check` is the schema verification.** It reported no structural drift, only
  two constraint *names* (`songs_album_id_title_key` / `albums_url_key` live, versus the
  models' `uq_*` convention). That is a trap: the next `--autogenerate` will fold a drop
  and re-add of both into whatever migration is being written. Delete those lines unless
  the rename is the point.

- **`docker compose run backend` tests the *deployed* image.** A new migration isn't in
  it, so the first test of 10.5's migration only re-ran the baseline and proved nothing.
  Mount the files in. And test against a table that already has rows: `add_column ...
  NOT NULL` needs a `server_default` or it fails on real data.

- **HNSW builds: set `max_parallel_maintenance_workers = 0` before raising
  `maintenance_work_mem`.** The parallel path allocates the whole setting up front as
  shared memory, which caused the DiskFull that killed the first attempt; serial allocates
  lazily. A bigger instance class does *not* raise `maintenance_work_mem` (RDS's formula
  still gives 64 MB), so the session `SET` does the work. The build took 2m37s, not the
  predicted hour. `db.t4g.medium` was unavailable (`InsufficientDBInstanceCapacity`), so
  check capacity before planning around a class.

- **An index can be rejected by its own cost estimate.** pgvector's cost scales with
  `ef_search`, so at 100 the planner priced the index above a seq scan. 40 brought it back
  on merit, with no `enable_seqscan` hint.

- **`NOT IN (subquery)` blocks the index; `NOT EXISTS` doesn't.** `NOT IN` can't become an
  anti-join (one NULL makes the predicate unknown), so Postgres uses a hashed SubPlan, the
  row estimate distorts, and the planner falls back to a seq scan. Changing it took common
  genres from ~80 ms / ~70k buffers to under 10 ms / ~3k.

- **An EXPLAIN gate has to run the ORM's own SQL.** The hand-written gate query left out
  the `NOT IN` and passed while the app still seq-scanned. Compile the real query with
  `literal_binds` and explain that.

- **Judge plans by buffers, not wall clock.** 86 ms looked fine on a temporarily larger,
  fully cached instance and was a seq scan. Run twice and compare buffer hits and reads.
  Also, `pg_stat_user_indexes.idx_scan` is flushed asynchronously, so reading it right
  after a query gives a false negative.

- **Testing a write path against prod without consuming anything:** run it inside an
  outer transaction with `join_transaction_mode="create_savepoint"`, then roll back. Row
  counts before and after proved no daily dispatch was used.

## 26. Failures that hide (Gameplan 10.3, 10.5, 10.7–10.9)

The theme of Phase 10: almost every serious problem was silent.

- **A broken ingest looped for three months unnoticed.** Every download failed, the run
  "finished", `/status` said ready, the frontend asked for recs, the snapshot was still
  stale, and the whole ingest re-queued. Forever. Nothing reached Sentry because the
  failures were `logger.warning`, and because Sentry had never been configured at all.

- **A retry cap only works if the counter survives.** 10.5 capped attempts at 3, but seeds
  were rewritten with delete-then-insert on every pass, resetting the count to 0. The cap
  could never be reached until the rewrite kept surviving rows.

- **Per-process state lies after a deploy.** `processing_users` lived in memory and was
  lost on restart. `/status` is now derived from the database, and "ready" means "a
  dispatch can be produced", not "the queue is empty".

- **Measure before choosing who to blame.** 10.7's first plan had a 422 from `/complete`
  count as a seed failure. A measurement showed the model returns a valid, non-zero
  embedding even for digital silence, so a 422 can only come from the *worker's build*
  (a dimension mismatch). Charging it to the seed would have let one bad worker retire
  every user's seeds within minutes. Instead the worker stops on 422 and the app logs
  ERROR and leaves the seed alone.

- **Exit loudly, restart gently.** A stopped worker is something a person notices; a
  worker silently retrying isn't. Under launchd, use `ThrottleInterval`, or `KeepAlive`
  restarts it straight back into the same refusal.

- **An unverified Sentry DSN is the same as no DSN.** It was verified with a real event
  through the app's own path: a deliberately malformed `/complete` → ERROR log → Sentry's
  default `LoggingIntegration` → an issue. That one event proved the DSN, egress, init and
  log promotion together.

- **What reaches Sentry, and how it groups.** sentry-sdk promotes `logger.error` to an
  issue by default; WARNING stays a breadcrumb. Log *transitions* (a seed retiring) at
  ERROR and *states* (a user who has no seeds, seen on every page load) at WARNING, or one
  user floods it. Use `%s` arguments, never f-strings, because Sentry groups on the raw
  message and an interpolated user id splits one issue into one per user.

- **Exceptions can carry secrets.** `CalledProcessError` and `TimeoutExpired` both
  stringify the command line, and spotdl's included `--client-secret`. Stored as
  `ingest_error`, that put the Spotify secret into the database and logs on every failed
  download. Fixed by not using `check=True` (build the error from the exit code and
  stderr tail), re-raising timeouts without the argv, and redacting known secrets before
  storing any error text. Checked afterwards: no row ever held it.

- **Some blindness is accepted, and written down.** A dead or sleeping worker still looks
  exactly like work in progress. The real fix (an alarm on pending-seed age) needs an
  app-metrics endpoint the 2 GB box doesn't have yet.

## 27. Datacenter IPs, YouTube and the ingest worker (Gameplan 10.3, 10.6)

- **YouTube bot-challenges EC2 addresses, intermittently.** "Sign in to confirm you're not
  a bot", but 1 of 5 videos still worked, so it's reputation-based. That's harder to
  operate than a clean failure. Newer yt-dlp, a JS runtime, alternative player clients and
  other spotdl providers were all ruled out on that box. A residential IP fixed it.

- **spotdl's "blocked by YouTube Music" message is wrong.** Its pre-flight check searches
  for the letter "a", and the one result currently returned has no video id, so it counts
  zero and aborts. Real searches on the same machine worked. `--audio youtube` skips the
  check.

- **yt-dlp needs a JavaScript runtime, and enables only Deno by default.** Without one it
  falls back to formats with no URLs ("Requested format is not available") or 403s.
  `--yt-dlp-args "--js-runtimes node"` fixes it.

- **Pin yt-dlp with a floor, not an exact version.** 2026.03.03 could not download at all
  from a residential IP; 2026.08.19 worked in under a second, minutes apart. A stale yt-dlp
  fails in ways that look exactly like a block, and one blocker masked the other in 10.3's
  testing on EC2.

- **Programs called by name run whatever's first on PATH.** The worker calls `spotdl`, so
  with a different venv active it silently used that venv's spotdl and its old yt-dlp.
  Run from the activated `.venv.worker` and check `which spotdl`.

- **A pull-based worker keeps the database private.** The worker polls
  `/api/v1/ingest/*` over HTTPS with a bearer token and holds no AWS or database
  credentials. It does hold Spotify's client id and secret, so "no secrets leave AWS"
  isn't true; it's "no AWS secrets".

- **A Postgres table makes a fine work queue at this size.** Claims are
  `UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED) RETURNING`, with a 15-minute
  lease so a dead worker's rows come back. Two workers get disjoint batches. Creating a
  shared `Song` uses a `begin_nested()` savepoint, so losing a unique-key race links to
  the winner instead of poisoning the transaction.

- **The worker fills seeds; the app decides.** Generating the dispatch in the worker would
  spend the user's daily allotment unprompted and bypass the row lock that serializes
  dispatch generation.

- **Validate at the boundary, and know your framework's quirks.** `json.loads` accepts
  `NaN`, and pgvector rejects it mid-transaction as a 500. Pydantic 2.12's
  `Field(allow_inf_nan=False)` on a `list[float]` rejects *every* request, and a field
  validator turns a NaN into a 500 because Starlette can't serialize the error that echoes
  it. The check is a plain function. Separately, `hmac.compare_digest` raises on
  non-ASCII `str`, so tokens are compared as bytes.

- **Prove an embedding computed elsewhere lands in the same space.** The forced test seed
  (a Rick Astley track) came back with its two nearest corpus neighbours being other
  versions of the same song, at cosine distance ~0.1. Nothing else would have shown a
  worker whose model wiring had drifted.

- **Don't download what you'll throw away.** spotdl fetches 320 kbps stereo, and the loader
  immediately resamples to 16 kHz mono. That only matters if bandwidth is billed (a
  proxy); check embeddings at two bitrates before lowering it.
