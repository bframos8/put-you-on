# CLAUDE.md

Project context and working preferences for Claude Code. Committed on purpose so it
travels between machines.

## What this is

A music recommendation app. Users log in with Spotify; their top songs are embedded
with an Essentia model; recommendations come from pgvector nearest-neighbour search
over a song corpus scraped from Bandcamp. Max 10 recommendations per user per day.

## Layout

| Path | What lives there |
|---|---|
| [backend/](backend/) | FastAPI app. Routes in `app/api/v1/` (`auth`, `health`, `songs`), config in `app/core/`, SQLAlchemy in `app/db/`, business logic in `app/services/`, migrations in `alembic/`. |
| [frontend/](frontend/) | Next.js (app router) + TypeScript. Pages in `src/app/`, shared UI in `src/components/`, self-hosted fonts in `src/assets/fonts/`. |
| [data_pipeline/](data_pipeline/) | Offline ingestion, not part of the web app. `link_pipeline/` crawls Bandcamp for album links; `song_pipeline/` downloads, embeds, and inserts songs. Driven by cron (`setup_cron.sh`). |
| [deploy/](deploy/) | SSM Parameter Store seeding and env materialization for production. |
| [nginx/](nginx/) | TLS-terminating reverse proxy config, dev and prod. |
| [claude-mds/](claude-mds/) | Planning and decision docs. Start with [deployment-gameplan.md](claude-mds/deployment-gameplan.md) and [commands.md](claude-mds/commands.md). |

## Running it

See [claude-mds/commands.md](claude-mds/commands.md) for the full runbook. The short
version: `docker compose up -d` brings up Postgres, backend, frontend, and nginx on
`https://127.0.0.1`. Backend and frontend can also run directly on the host for
faster iteration.

Two things Docker does not provide and that a fresh clone will not have:
mkcert certificates at `frontend/localhost+1*.pem` (bind-mounted by the nginx
service), and the licensed fonts in `frontend/src/assets/fonts/` (needed at
**build** time by `next/font/local`, so `docker compose build frontend` fails
without them). Both are gitignored deliberately.

## Configuration

Local dev reads `.env-backend` and `.env-postgres` at the repo root, plus
`frontend/.env.local`. Every one of them is gitignored; each has a committed
`.example` template describing the contract. Production values live in SSM
Parameter Store and are materialized at deploy — see
[deploy/ssm-parameters.md](deploy/ssm-parameters.md). Never commit real values.

`SESSION_SECRET` and `TOKEN_ENCRYPTION_KEYS` are required: the app refuses to boot
without them, and alembic refuses to run without the latter.

`NEXT_PUBLIC_*` variables are inlined into the client bundle at build time. In
Docker they come from the compose build-arg, never from a `.env` file — the
frontend `.dockerignore` excludes `.env*` so there is only one source of truth.

## Testing

`cd backend && pytest` and `cd data_pipeline && pytest`. Both run on the host
against a venv; `backend/.dockerignore` deliberately keeps the test suite out of
the runtime image.

## Working preferences

**Scope.** Make the change that was asked for and no more. Do not refactor
surrounding code, rename things, or "fix" style for convention's sake unless it is
required for the task. If a change looks worth making but is out of scope, say so
rather than doing it.

**Plan first.** For anything spanning more than one file, lay out a per-item plan
and get agreement before writing code.

**Prose and UI copy.** Write like a person, not like an LLM. No em-dashes in
product or UI copy. Avoid the marketing register: no "seamless", "robust",
"leverage", "delve". Plain, direct sentences.

**Comments.** This codebase comments the *why*, often at length, especially where
behaviour is surprising (see the Dockerfiles and `.dockerignore` files). Match that
when touching those areas; do not strip existing explanatory comments.

**Migrations.** Alembic is the single authority on schema. No `create_all`. See
[claude-mds/phase-1-decisions.md](claude-mds/phase-1-decisions.md).

**Commits.** Do not add AI-attribution trailers or `Co-Authored-By` lines.

**Verification.** Do not spawn agents to double-check work without asking first.

## Constraints worth knowing

The Spotify app is quota-limited to roughly 25 OAuth users, so anything requiring
broad `user-top-read` access is off the table; prefer Client Credentials plus
user-provided data. Background at
[claude-mds/spotify-ingest-without-quota-plan.md](claude-mds/spotify-ingest-without-quota-plan.md).
