# Deployment Deferred — Follow-ups Explicitly Out of the Deployment Pass

**Moved out of** [deployment-gameplan.md](completed/deployment-gameplan.md) on 2026-10-02, when Phase 10
closed. Nothing here blocks the running deployment. Each entry says why it was left and,
where there is one, what would make it worth picking up. Item numbers (1.2, 6.1, 10.6, …)
refer to the gameplan; Phase 11 items now live in
[pyo-0.0.1-sign-in-change.md](pyo-0.0.1-sign-in-change.md).

---

- **`data_pipeline` deployment** — packaging and scheduling (cron/systemd/EventBridge) is a
  separate effort once the web app is live.
  - *Note (1.2 cleanup, 2026-07-17):* the old `data_pipeline/db/init_db.py` — a dormant,
    stale, destructive (`DROP TABLE … CASCADE`) hand-written schema bootstrap and a second
    schema authority — was **deleted** as part of 1.2. When the pipeline is deployed, any
    fresh-DB setup it needs should run `alembic upgrade head`, keeping Alembic the single
    authority. (Its orphaned helper `data_pipeline/db/initializer.py`, now used only by its
    own unit test, can be removed too whenever the pipeline work resumes.)
- **The in-process ingest path validates no embedding at all.** `/ingest/complete` checks
  dimensions, finiteness and norm before storing (10.6), but `process_top_tracks` writes
  `embedding` straight into `Song` with no equivalent check, so the flag-off path would store
  a degenerate vector silently — and `Song.spotify_track_id` is unique, so one bad embedding
  for a popular track becomes the query seed for every user who has it (10.6's "poisoned
  seeds cross users"). Filed here rather than as a launch item because the trigger looks
  unreachable in practice: measured 2026-09-25, the model returns a dense finite vector even
  for digital silence, and audio too short to embed raises instead. The asymmetry is still
  real, and the fix is to route both paths through `embedding_problem`.

- **`alembic check` against production always reports the HNSW index.** Found 2026-10-09,
  checking 0.0.1 A1 after it deployed. `songs_embedding_hnsw_idx` was built out of band in
  deployment-gameplan 10.2 (2026-09-25), the day after 10.1 recorded a clean check, and the
  models deliberately don't declare it. So every `alembic check` against production now
  proposes `remove_index` for it, on top of the two known constraint-name differences
  (`albums_url_key`, `songs_album_id_title_key`). Harmless while nobody autogenerates
  against production, which that name drift already rules out, but it is noise that a real
  drift could hide in. Fix: an `include_object` hook in `backend/alembic/env.py` that skips
  that index by name. The same hook could ignore the two name-only differences, or a small
  migration could rename them.

- **Moved into [Put You On 0.0.1](pyo-0.0.1-sign-in-change.md) on 2026-10-02:**
  - *A user's top tracks never refresh once processed.* Resolved by 0.0.1 retiring
    `me/top/tracks` as the seed source (Phase D); seeds become songs people pick.
  - *The frontend's dispatch cache is not scoped to a user* (`pyo:recs`). Now 0.0.1 C3.
  - *There is no account-deletion feature.* Now 0.0.1 Phase E (an endpoint plus a runbook
    procedure).

- **Client IPs can be spoofed through `X-Forwarded-For`.** Found 2026-10-02 while
  re-verifying the 0.0.1 plan. nginx forwards `$proxy_add_x_forwarded_for`, which
  *appends* the real address to whatever the client sent, and uvicorn runs with
  `--forwarded-allow-ips=*`, which takes the **leftmost** entry. So a client choosing its
  own `X-Forwarded-For` chooses the IP that every IP-keyed rate limit sees, including
  0.0.1's `5/minute` on login and register. Fix in nginx: send
  `proxy_set_header X-Forwarded-For $remote_addr;` (nginx is the only proxy, so the
  client address it sees is the real one). Related and smaller: `session_key` puts every
  request with an invalid session cookie in one shared `user:None` bucket. Not folded
  into 0.0.1 (decided 2026-10-02); argon2's cost is the real brake on password guessing
  meanwhile.

- **Zero-downtime deploys** — current plan accepts brief recreate downtime; blue/green is a
  later upgrade.
- **Model binary in git (audit H2)** — the 18 MB `.pb` committed twice
  ([housekeeping-audit.md](completed/housekeeping-audit.md) H2) bloats clones. Note the backend image
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

## The ingest worker's permanent home (formerly gameplan 11.5)

Moved here from the 0.0.1 plan on 2026-10-02: it's infrastructure, not part of the
release, and was not folded in. Until it lands, new users only ingest while the MacBook is
awake and running the worker.

- [ ] **11.5 Give the ingest worker a permanent home on the Mac mini.**
  **How:** 11.4 gets the worker running somewhere; this makes it durable. Running it by
  hand from a laptop is fine for proving the path and wrong as a permanent arrangement: a
  laptop sleeps, and a sleeping worker is indistinguishable from a broken one. Move it to
  the Mac mini that already runs `data_pipeline`:
  1. Clone the repo (or reuse the existing checkout), build the venv from
     [worker/worker_requirements.txt](../worker/worker_requirements.txt), and confirm a
     JavaScript runtime is on PATH — `run.py` refuses to start without one.
  2. Copy `INGEST_WORKER_TOKEN`, `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` into
     `worker/.env`. These are the secrets that live outside AWS; there is still no
     rotation story beyond re-seeding SSM and restarting.
  3. Run it under **launchd**, not cron and not `nohup`: this is a long-lived process, so
     it wants `KeepAlive` and `RunAtLoad` rather than a schedule. `data_pipeline`'s
     `setup_cron.sh` is the wrong model here. Point `StandardOutPath` somewhere that gets
     rotated.
     > **Throttle the restart.** 10.7 makes the worker **exit non-zero** when the app
     > refuses its output, which is deliberate — but a bare `KeepAlive` would then restart
     > it into the same refusal forever. Use `ThrottleInterval` and check the log rather
     > than assuming a running process means a working one.
  4. Stop `caffeinate`-style workarounds from being load-bearing: set the mini to never
     sleep, and verify the worker survives a reboot.
  5. Decide whether the laptop stays as a second worker. It can — claims use
     `FOR UPDATE SKIP LOCKED`, so two workers take disjoint batches safely — but two
     machines holding the same secrets doubles that exposure for very little throughput.
  **Why:** Until this lands, "new users can be onboarded" depends on a laptop being awake,
  and the failure mode is silent: seeds accumulate unclaimed and `/status` says
  `processing` indefinitely. Nothing alerts, so the only signal is the worker's own
  `Claimed N seed(s)` log line (see the runbook's worker section).
