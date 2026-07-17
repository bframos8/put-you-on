# Deployment Learnings — Concepts & Clarifications

**Companion to** [deployment-gameplan.md](deployment-gameplan.md). This captures the
questions worked through while doing the deployment and the clarified answers — a reference
for *why* each decision was made. A couple of entries note assumptions that got **corrected
by measurement**; those are flagged.

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
