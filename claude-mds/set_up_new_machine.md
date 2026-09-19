# Setting up on a new machine

`git clone` gets you the code, the planning docs in `claude-mds/`, `CLAUDE.md`, the
skills in `.claude/skills/`, and the `.env` templates. It does not get you secrets,
licensed fonts, or any AWS tooling. This is the checklist for the rest.

The work is split by what you actually intend to do. Deployment work (Phase 6 and on)
needs almost nothing from the app dev setup — it touches no application code — so
skip to [AWS / deployment work](#aws--deployment-work) if that is all you need.

---

## Before leaving the old machine

- [ ] **Push everything.** Check for unpushed commits (`git log --branches --not
      --remotes --oneline`) and branches with no upstream (`git status -sb`).
- [ ] **Note the Spotify client ID and secret**, or just plan to re-read them from the
      Spotify developer dashboard.

---

## AWS / deployment work

Enough to pick up **Phase 6** of the
[deployment gameplan](deployment-gameplan.md). No fonts, no mkcert, no local Postgres,
no venvs, no Node — Phase 6 is instance provisioning, security groups, DNS, and RDS
verification.

- [ ] **Clone the repo.**
- [ ] **AWS CLI v2**, then `aws configure` (or `aws sso login` — `deploy/ssm-seed.sh`
      assumes SSO is an option).

      ```bash
      brew install awscli
      ```

- [ ] **Session Manager plugin.** Gameplan 6.2 closes port 22 entirely, so SSM Session
      Manager is the *only* shell access to the instance. Without this you cannot get
      a prompt on the box.

      ```bash
      brew install --cask session-manager-plugin
      ```

- [ ] **A psql client**, for the RDS verification in 6.5. Either `brew install
      libpq` or borrow one from Docker:

      ```bash
      docker run --rm -it postgres:16 psql -h <rds-endpoint> -U ramos -d pyo_db -W
      ```

- [ ] **Terraform** (≥ 1.10, for S3 lock files). Homebrew's core formula is stuck at
      1.5, so use HashiCorp's tap, then initialize against the shared S3 state:

      ```bash
      brew install hashicorp/tap/terraform
      cd infra && terraform init && terraform plan   # expect "No changes"
      ```

- [ ] **Porkbun login**, for the DNS `A` record in 6.4.

---

## App development work

Needed to actually run or change the app. Independent of the AWS list above.

### 1. Fonts (required — the build fails without them)

`frontend/src/assets/fonts/` is gitignored. [layout.tsx](../frontend/src/app/layout.tsx)
loads seven files through `next/font/local`, which resolves them **at build time**, so
both `npm run build` and `docker compose build frontend` fail on a fresh clone. Docker
does not rescue you here: the frontend Dockerfile does `COPY . .` then `npm run build`,
and `frontend/.dockerignore` does not exclude fonts. They are a build input, not a
runtime dependency.

Only `SmileySans-Oblique.woff2` is in this repo; the Helvetica and Estrella files are
commercially licensed and must not be committed to a public repo. They live in the
private repo `bframos8/put-you-on-fonts` (8 files, ~1.7 MB), the same source CI uses.
Clone it next to this repo and copy them in:

```bash
git clone https://github.com/bframos8/put-you-on-fonts.git ../put-you-on-fonts
cp ../put-you-on-fonts/*.ttf ../put-you-on-fonts/*.otf frontend/src/assets/fonts/
```

Later font changes: `git -C ../put-you-on-fonts pull` and copy again.

### 2. TLS certificates

The nginx service bind-mounts `frontend/localhost+1.pem` and
`frontend/localhost+1-key.pem`, and `npm run dev` passes them to Next. **Do not copy
these** — the `-key.pem` is a private key. Regenerate:

```bash
brew install mkcert && mkcert -install
cd frontend && mkcert 127.0.0.1 localhost
```

### 3. Local environment files

```bash
cp backend/.env.example           .env-backend
cp backend/.env-postgres.example  .env-postgres
cp frontend/.env.local.example    frontend/.env.local
```

Generate `SESSION_SECRET` and `TOKEN_ENCRYPTION_KEYS` fresh rather than copying them
(commands are in `backend/.env.example`). Postgres credentials are yours to choose.
Only the Spotify client ID and secret have to match the other machine.

> **Caveat:** a fresh `TOKEN_ENCRYPTION_KEYS` cannot decrypt tokens encrypted with a
> different key. Fine for an empty local database; if you are pointing at data that
> already has encrypted token rows, reuse the existing key instead.

### 4. Dependencies

Docker covers most of this. `docker compose up -d` builds backend and frontend from
`backend/backend_requirements.txt` and `frontend/package-lock.json`, and pulls
`pgvector/pgvector:pg16` and `nginx:alpine`. No host Python or Node needed to *run*
the web app.

Three things are not containerized and still need host setup:

- **The data pipeline** has no Dockerfile. It runs on the host from
  `data_pipeline/pipeline_requirements.txt`, driven by `setup_cron.sh`.
- **Tests.** `backend/.dockerignore` excludes `tests/` and `test-requirements.txt`
  from the image, so pytest runs on the host. Or run the suite the way CI does, in
  the built image with the test files mounted back in, and skip the backend venv
  (from the repo root, after `docker compose build backend`):

  ```bash
  docker run --rm -v ./backend/tests:/app/tests -v ./backend/pytest.ini:/app/pytest.ini \
    -v ./backend/test-requirements.txt:/app/test-requirements.txt put-you-on-backend \
    sh -c "pip install -r test-requirements.txt && python -m pytest -p no:cacheprovider"
  ```
- **Alembic**, when running migrations from the host rather than exec'ing into the
  container.

```bash
python3.11 -m venv .venv.backend  && .venv.backend/bin/pip  install -r backend/backend_requirements.txt -r backend/test-requirements.txt
python3.11 -m venv .venv.pipeline && .venv.pipeline/bin/pip install -r data_pipeline/pipeline_requirements.txt
```

Verified against Python 3.11 and Node 20 (the version in the frontend image).

---

## Working across two machines

Things that do not travel through git, and how to keep them from biting.

**Terraform state is the record of what exists** for everything in
[infra/](../infra/) (gameplan 6.0). It lives in S3, not in git, so both machines see
the same state, and a `terraform plan` on a machine with a stale checkout shows the
instance already exists instead of creating a second one. Always `git pull` before
`terraform plan`, and never change a Terraform-managed resource in the console. The
gameplan checkboxes still record everything done by hand (Phase 0 IAM/ECR, SSM values,
DNS), so keep committing those notes promptly.

**`deploy/prod.env` is gitignored and will not sync.** After seeding, SSM is the
source of truth. Do not maintain two copies; pull from SSM if you need the values
elsewhere.

**Local Postgres volumes are independent.** The `pgdata` volumes on the two machines
diverge immediately and permanently. Expected — just don't expect local data to follow
you.

**mkcert certs are per-machine**, and should be (private keys). Fonts are not: both
machines and CI copy them from `bframos8/put-you-on-fonts`, so a font change goes
there first.
