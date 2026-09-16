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
- [ ] **Copy the fonts out of band.** `frontend/src/assets/fonts/` — 8 files, ~2.8 MB
      (everything except `SmileySans-Oblique.woff2`, which is tracked). AirDrop, a USB
      stick, or a cloud folder. See [Fonts](#1-fonts-required--the-build-fails-without-them).
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

- [ ] **Porkbun login**, for the DNS `A` record in 6.4.

---

## App development work

Needed to actually run or change the app. Independent of the AWS list above.

### 1. Fonts (required — the build fails without them)

`frontend/src/assets/fonts/` is gitignored. [layout.tsx](../frontend/src/app/layout.tsx)
loads nine files through `next/font/local`, which resolves them **at build time**, so
both `npm run build` and `docker compose build frontend` fail on a fresh clone. Docker
does not rescue you here: the frontend Dockerfile does `COPY . .` then `npm run build`,
and `frontend/.dockerignore` does not exclude fonts. They are a build input, not a
runtime dependency.

Copy the directory by hand. Only `SmileySans-Oblique.woff2` is in the repo; the
Helvetica and Estrella files are commercially licensed and must not be committed to a
public repo.

```
Estrella.otf                          Helvetica-Oblique.ttf
Helvetica.ttf                         helvetica-compressed-5871d14b6903a.otf
Helvetica-Bold.ttf                    helvetica-light-587ebe5a59211.ttf
Helvetica-BoldOblique.ttf             helvetica-rounded-bold-5871d05ead8de.otf
```

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
  from the image, so pytest runs on the host. *(Once gameplan 8.1 lands you can run
  the suite the way CI does — in the built image with the test files mounted back in —
  and skip the backend venv.)*
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

**The gameplan checkboxes are the infrastructure state file.** There is no Terraform
here, so [deployment-gameplan.md](deployment-gameplan.md) is the only record of what
exists in AWS. Phase 6 is the first phase that creates real, billable resources.
Commit and push the checkbox *and* its note immediately after each item — otherwise
the other machine believes 6.1 is unstarted and you launch a second instance.

**`deploy/prod.env` is gitignored and will not sync.** After seeding, SSM is the
source of truth. Do not maintain two copies; pull from SSM if you need the values
elsewhere.

**Local Postgres volumes are independent.** The `pgdata` volumes on the two machines
diverge immediately and permanently. Expected — just don't expect local data to follow
you.

**Fonts and mkcert certs are per-machine.** Certs *should* be (private keys). Fonts
are a one-time copy you will forget about until a frontend build fails.
