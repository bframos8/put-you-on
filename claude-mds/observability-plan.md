# Observability Plan — Grafana Cloud for Server + Database Metrics

**Date:** 2026-06-15
**Branch:** `Backend-optimization`
**Companion to:** [deployment-gameplan.md](deployment-gameplan.md) (single EC2 + RDS + nginx +
ECR/SSM). This plan assumes that topology and slots into the same `docker-compose.prod.yaml`
and SSM-based deploy flow.
**Goal:** Continuous visibility into the **EC2 server** (host + containers + FastAPI app) and
the **RDS database**, with dashboards in Grafana — built to stay inside the free tier and to
avoid loading down a RAM-constrained, TensorFlow-heavy instance.

> Ordered runbook. Each item has **How** (concrete) and **Why** (the reason it matters).
> Checkboxes track progress.

---

## Locked decisions (from clarifying Q&A)

| Decision | Choice |
|----------|--------|
| **Hosting** | **Grafana Cloud (free tier)** — managed Grafana, Prometheus (Mimir) storage, dashboards. A local **Grafana Alloy** agent scrapes and remote-writes out. |
| **Server scope** | **Host** (node_exporter) + **Containers** (cAdvisor) + **App** (FastAPI RED + custom metrics via `/metrics`). |
| **Database scope** | **RDS CloudWatch metrics only**, surfaced via Grafana Cloud's **CloudWatch data source** (no `postgres_exporter`, no Performance Insights this pass). |
| **Alerting** | **Dashboards only now.** Alert rules scaffolded in Phase 6 for a later pass. |
| **Out of scope** | Logs/Loki, nginx exporter, `data_pipeline` metrics, postgres-internal/query-level metrics. |

---

## Architecture at a glance

```
                EC2 instance (docker compose)
   ┌─────────────────────────────────────────────────┐
   │  backend (FastAPI)  ──exposes──►  :8000/metrics   │
   │  node_exporter      ──host CPU/mem/disk/net──┐    │
   │  cadvisor           ──per-container CPU/mem──┤    │
   │                                              ▼    │
   │  grafana-alloy  ──scrapes all 3, remote_write─────┼──► Grafana Cloud
   └─────────────────────────────────────────────┬────┘     (Mimir / Prometheus)
                                                  │                ▲
   AWS RDS ──► CloudWatch metrics  ◄──────────────┼── Grafana Cloud │
                                                  │   CloudWatch     │
   Grafana Cloud Dashboards  ◄─────────────────── data source ──────┘
```

- **Push for server/app metrics:** Alloy scrapes locally and **remote-writes** to Grafana
  Cloud — so nothing but the agent needs to leave the box, and Grafana Cloud stores/queries.
- **Pull for RDS:** Grafana Cloud's CloudWatch data source queries CloudWatch directly at
  dashboard-view time. No agent or exporter touches the database.

**Why this shape:** It keeps the heavy components (storage, query engine, Grafana UI) off your
memory-tight instance, leaving only ~3 small agents/exporters local. CloudWatch already has
the RDS metrics you asked for, so pulling them via a data source avoids running and securing a
`postgres_exporter` against the database.

---

## Order of operations

```
0. Grafana Cloud account + endpoints/tokens + CloudWatch IAM
1. Instrument the FastAPI app (code: /metrics + RED + custom)   ← code change, ships in image
2. Add node_exporter, cAdvisor, Alloy to docker-compose.prod    ← collection layer
3. Store Grafana Cloud + CloudWatch creds in SSM Parameter Store ← secrets
4. Wire RDS into Grafana via the CloudWatch data source
5. Build/import dashboards (host, containers, app, RDS)
6. (Deferred) Alerting — rules scaffolded, routing later
7. Verify, set free-tier/cardinality guardrails
```

Rationale: the app instrumentation is a **code change**, so it goes first and ships inside the
backend image (same as the deployment plan's Phase 1). The collection layer and secrets come
next, then the database wiring, then dashboards on top of data that's already flowing.

---

## Phase 0 — Grafana Cloud account & AWS access

- [ ] **0.1 Create a Grafana Cloud stack (free tier).**
  **How:** Sign up, create a stack, and from **Connections → Prometheus / "remote_write"**
  copy the **remote-write URL**, **username/instance ID**, and a generated **API token**
  (scope: `metrics:write`).
  **Why:** These three values are what Alloy uses to push metrics. The free tier (10k active
  series, 14-day retention) is sufficient for one app + host + containers if you keep
  cardinality in check (Phase 7).

- [ ] **0.2 Create a read-only IAM principal for the CloudWatch data source.**
  **How:** An IAM policy allowing `cloudwatch:GetMetricData`, `GetMetricStatistics`,
  `ListMetrics`, `DescribeAlarmsForMetric`, `cloudwatch:DescribeAlarms`, `tag:GetResources`,
  and `ec2:DescribeRegions`. Prefer an **IAM role that Grafana Cloud assumes** (with the
  external ID Grafana provides) over a long-lived access key.
  **Why:** Grafana Cloud needs read access to pull RDS metrics. Assume-role with an external
  ID avoids storing static AWS keys in Grafana, mirroring the OIDC stance in the deployment
  plan.

---

## Phase 1 — Instrument the FastAPI app

> Code change in the backend. Do it first so it's baked into the image the deploy pipeline
> ships.

- [ ] **1.1 Add the instrumentation dependency.**
  **How:** Add `prometheus-fastapi-instrumentator` (pulls in `prometheus_client`) to
  [backend/backend_requirements.txt](../backend/backend_requirements.txt), pinned.
  **Why:** It wires Prometheus-format RED metrics into FastAPI with a few lines and exposes a
  scrape endpoint — far less custom code than raw `prometheus_client` for the HTTP layer.

- [ ] **1.2 Expose `/metrics` and the RED baseline.**
  **How:** In [backend/app/main.py](../backend/app/main.py), after `app` is built:
  ```python
  from prometheus_fastapi_instrumentator import Instrumentator
  Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
  ```
  This gives request **R**ate, **E**rror rate, and **D**uration (latency histogram) per route
  and status code.
  **Why:** RED is the universal "is the service healthy and fast?" triad. Per-route + status
  lets you see exactly which endpoint is erroring or slow.

- [ ] **1.3 Keep `/metrics` internal-only.**
  **How:** Do **not** add an nginx `location /metrics` block — nginx only proxies `/` and
  `/api/`, so `/metrics` stays reachable only on the docker network (where Alloy scrapes
  `backend:8000/metrics`). Optionally also gate it by network in compose.
  **Why:** Metrics can leak internal structure and request volumes; there's no reason to
  expose them publicly. Alloy is in the same compose network, so internal scraping is enough.

- [ ] **1.4 Add the custom metrics that matter for this app.**
  **How:** With `prometheus_client`, add a few module-level metrics and record them at the
  right call sites:
  - **ML embed/ingest duration** — a `Histogram("embed_duration_seconds", ...)` timed around
    the embed/ingest path in
    [spotify_ingest_service.py](../backend/app/services/spotify_ingest_service.py) (`_embed` /
    `add_user_top_songs`).
  - **Spotify API latency + failures** — a `Histogram` + `Counter("spotify_api_errors_total",
    ["endpoint"])` around the `httpx` calls (the ones governed by `SPOTIFY_HTTP_TIMEOUT`).
  - **OAuth outcomes** — `Counter("oauth_logins_total", ["result"])` incremented in the
    Spotify callback in `backend/app/api/v1/auth.py`.
  **Why:** RED covers the HTTP edge, but the things most likely to hurt *this* product are the
  slow ML embed step and the external Spotify dependency. These three turn "users say it's
  slow" into a graph that says where.

- [ ] **1.5 Guard cardinality in custom metrics.**
  **How:** Label only by **low-cardinality** dimensions (endpoint name, result =
  success/failure). **Never** label by user ID, Spotify track ID, or session.
  **Why:** Each label-value combination is a new time series. High-cardinality labels blow
  past the free tier's 10k series and balloon memory. This is the #1 self-inflicted
  observability cost.

---

## Phase 2 — Add the collection layer to compose

> All three are public images — pin versions, pull from Docker Hub/quay (no ECR needed). They
> join `docker-compose.prod.yaml` and ride the existing SSM deploy. Give each a small
> `mem_limit` so monitoring can't starve the app.

- [ ] **2.1 node_exporter (host metrics).**
  **How:** Add `prom/node-exporter` with the standard host mounts (`/proc`, `/sys`, `/:/host/root:ro`)
  and `--path.rootfs=/host/root`. No published ports — Alloy scrapes it on the internal
  network.
  **Why:** Host CPU, memory, **disk space/IO**, network, and load are the base layer. Disk-full
  is the most common way this class of box dies (the deployment plan flags it too); node_exporter
  is how you see it coming.

- [ ] **2.2 cAdvisor (per-container metrics).**
  **How:** Add `gcr.io/cadvisor/cadvisor` with `/var/run/docker.sock`, `/sys`,
  `/var/lib/docker` mounts (read-only where possible). Consider a longer
  `--housekeeping_interval` to cut its CPU use. No public ports.
  **Why:** Splits "the box is using 7 GB" into "the **backend** is using 5 GB of it" — exactly
  the visibility you need given the double-loaded TF model (audit H1) and the per-worker memory
  question from the deployment plan.

- [ ] **2.3 Grafana Alloy (the agent).**
  **How:** Add `grafana/alloy` with a mounted `alloy/config.alloy` (committed to the repo)
  that defines three `prometheus.scrape` targets — node_exporter, cadvisor,
  `backend:8000/metrics` — and one `prometheus.remote_write` to the Grafana Cloud URL, with
  credentials from env (Phase 3). Add a global `external_labels` set (e.g.
  `instance="prod-1"`, `app="putyouon"`).
  **Why:** Alloy is Grafana's current unified agent (successor to Grafana Agent). One small
  process scrapes everything locally and ships it out — so only the agent egresses, and Grafana
  Cloud does the storage/querying your instance can't afford to.

- [ ] **2.4 Cap monitoring's footprint.**
  **How:** `mem_limit` each (~64–128 MB node_exporter/alloy, ~128–256 MB cadvisor),
  `restart: unless-stopped`, and the same json-file log caps as the rest of the stack.
  **Why:** Observability must never be the reason the app OOMs. Hard caps make monitoring fail
  before the app does.

---

## Phase 3 — Secrets in SSM Parameter Store

- [ ] **3.1 Store the Grafana Cloud remote-write credentials.**
  **How:** SecureString params under `/putyouon/prod/`:
  `GRAFANA_CLOUD_PROM_URL`, `GRAFANA_CLOUD_PROM_USER`, `GRAFANA_CLOUD_API_TOKEN`. The deploy
  step (deployment plan Phase 5.2/8.3) writes them into Alloy's env alongside the app secrets.
  **Why:** The API token is a write credential to your metrics backend — it belongs in SSM with
  everything else, never in the repo or the Alloy config file.

- [ ] **3.2 Store CloudWatch access for Grafana Cloud.**
  **How:** If using assume-role (preferred), record the role ARN + external ID in Grafana
  Cloud's data-source config. If you fall back to an access key, store it as a SecureString and
  enter it in Grafana — don't commit it.
  **Why:** Same principle — read access to your AWS metrics is a credential to protect and
  rotate.

---

## Phase 4 — Wire RDS into Grafana via CloudWatch

- [ ] **4.1 Add the CloudWatch data source in Grafana Cloud.**
  **How:** Connections → Add data source → CloudWatch; set the region (your RDS region) and the
  assume-role/key from 0.2/3.2. Test the connection.
  **Why:** This is the entire database story for this pass — Grafana queries the RDS metrics
  CloudWatch already publishes, with nothing running against the database itself.

- [ ] **4.2 Confirm the RDS metrics you care about are present.**
  **How:** Verify these `AWS/RDS` metrics for your DB instance: `CPUUtilization`,
  `DatabaseConnections`, `FreeableMemory`, `FreeStorageSpace`, `ReadLatency`/`WriteLatency`,
  `ReadIOPS`/`WriteIOPS`, and (if applicable) `ReplicaLag`/`BurstBalance`.
  **Why:** These five-ish are the ones that predict RDS trouble: connection exhaustion (the app
  pools 10+20 per worker — see [database.py:18-24](../backend/app/db/database.py#L18-L24)),
  storage-full, and latency creep. Confirm they exist before building panels on them.

---

## Phase 5 — Dashboards

- [ ] **5.1 Host dashboard.**
  **How:** Import **Node Exporter Full** (Grafana dashboard ID **1860**); point it at the
  Grafana Cloud Prometheus data source; filter by the `instance` external label.
  **Why:** A battle-tested, comprehensive host dashboard out of the box — no reason to hand-roll
  CPU/mem/disk panels.

- [ ] **5.2 Container dashboard.**
  **How:** Import a cAdvisor/Docker dashboard (e.g. ID **14282** or **193**) and trim to your
  three services.
  **Why:** Instant per-container CPU/memory so you can watch the backend's footprint against its
  `mem_limit` and tune worker count.

- [ ] **5.3 Application dashboard (build).**
  **How:** A custom board with: request rate, error % (4xx/5xx), and p50/p95/p99 latency from
  the RED histogram; plus panels for `embed_duration_seconds`, Spotify latency/error counters,
  and `oauth_logins_total{result=...}`.
  **Why:** This is the screen you'll actually watch — it ties HTTP health to the ML and Spotify
  internals that are unique to this app.

- [ ] **5.4 RDS dashboard.**
  **How:** Build (or import an AWS/RDS community board) on the CloudWatch data source with the
  4.2 metrics; put **DatabaseConnections** and **FreeStorageSpace** front and center.
  **Why:** Those two are your earliest warnings of the two most likely DB outages — pool
  exhaustion and disk-full.

---

## Phase 6 — Alerting (deferred — scaffold only)

> You chose dashboards-only for now. Recorded here so the rules aren't reinvented later;
> Grafana Cloud's free tier includes alerting when you're ready.

- [ ] **6.1 Draft the alert rules (don't route yet).** Candidate rules:
  - **Instance/target down** — Alloy stops reporting, or `up == 0` for node_exporter/backend.
  - **Disk space low** — node_exporter root filesystem < 15%.
  - **Memory pressure** — sustained high memory / approaching `mem_limit`.
  - **App error spike** — 5xx rate over a threshold for N minutes.
  - **RDS** — `DatabaseConnections` near `max_connections`; `FreeStorageSpace` low; CPU
    sustained high.
  - **TLS cert expiry** — Let's Encrypt cert < 14 days (ties to deployment plan Phase 7).
  **Why:** These map 1:1 to the failure modes the dashboards expose. Writing them down now means
  enabling alerting later is wiring a notifier (email/Slack), not rediscovering what to watch.

- [ ] **6.2 Pick a routing channel when you turn it on.** Email is zero-setup; Slack via webhook
  if you live there.
  **Why:** Dashboards tell you when you look; alerts tell you when you're not looking. This is
  the gap to close in the next pass.

---

## Phase 7 — Verify & guardrails

- [ ] **7.1 Confirm data is flowing.**
  **How:** In Grafana Cloud Explore, query `up`, `node_memory_MemAvailable_bytes`,
  `container_memory_usage_bytes`, and one custom metric (`embed_duration_seconds_count`).
  Confirm RDS metrics render from the CloudWatch source.
  **Why:** Proves each of the three pipelines (host, container, app) and the DB source
  end-to-end before you rely on them.

- [ ] **7.2 Watch the free-tier active-series count.**
  **How:** Check Grafana Cloud's billing/usage view for active series; cAdvisor + node_exporter
  are the biggest contributors. Drop unused cAdvisor metrics via an Alloy
  `metric_relabel_configs` keep/drop list if you approach 10k.
  **Why:** The free tier caps at 10k series. cAdvisor especially is verbose — trimming keeps you
  free and keeps queries fast.

- [ ] **7.3 Sanity-check resource impact on the box.**
  **How:** After rollout, look at the container dashboard for node_exporter/cadvisor/alloy
  memory against their caps and overall host headroom.
  **Why:** Confirms the monitoring layer is the lightweight tenant it's supposed to be on a
  RAM-constrained instance.

---

## Integration with the deployment pipeline

- The three new containers live in **`docker-compose.prod.yaml`** and are pulled/started by the
  **same SSM deploy** (deployment plan Phase 8.3) — no separate deploy path.
- **Alloy config** (`alloy/config.alloy`) and dashboard JSON are **committed to the repo** so
  monitoring is versioned with the app (dashboards-as-code).
- **Credentials** (Grafana Cloud token, CloudWatch access) come from **SSM Parameter Store**,
  consistent with the deployment plan's secret handling — nothing monitoring-related is
  committed.
- The backend `/metrics` change ships in the **backend image** like any other code change and
  is covered by the existing CI.

---

## Critical-path summary

1. Grafana Cloud stack + remote-write token (0.1)
2. CloudWatch read IAM for the data source (0.2)
3. FastAPI `/metrics` + RED + custom metrics, internal-only (1.x)
4. node_exporter + cAdvisor + Alloy in compose, capped (2.x)
5. Creds in SSM; Alloy remote-writes; CloudWatch data source live (3.x, 4.x)
6. Dashboards: host (1860), containers, app, RDS (5.x)

Alerting (Phase 6) is deferred by decision; everything above gets you live dashboards over
server **and** database with minimal load on a memory-tight box.
