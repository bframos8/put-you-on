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
| [claude-mds/](claude-mds/) | Planning and decision docs. Active plans sit at the top level; finished ones move to `completed/`. [commands.md](claude-mds/commands.md) is the runbook. |

## Running it

See [claude-mds/commands.md](claude-mds/commands.md) for the full runbook. The short
version: `docker compose up -d` brings up Postgres, backend, frontend, and nginx on
`https://127.0.0.1`. Backend and frontend can also run directly on the host for
faster iteration.

Two things Docker does not provide and that a fresh clone will not have:
mkcert certificates at `frontend/localhost+1*.pem` (bind-mounted by the nginx
service), and the licensed fonts in `frontend/src/assets/fonts/` (needed at
**build** time by `next/font/local`, so `docker compose build frontend` fails
without them). Both are gitignored deliberately. The fonts live in the private repo
`bframos8/put-you-on-fonts`; CI and new machines copy them in from there (see
[claude-mds/set_up_new_machine.md](claude-mds/set_up_new_machine.md)).

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
the runtime image. CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs the
backend suite inside the built image instead, with the tests mounted back in.

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
[claude-mds/phase-1-decisions.md](claude-mds/completed/phase-1-decisions.md).

**Commits.** Do not add AI-attribution trailers or `Co-Authored-By` lines.

**Agents.** Ask before running any agent, including in the feature workflow below. Say
what the agent would check or answer. The user may answer it directly, which makes the
agent unnecessary, or confirm that the agent should run.

## Branches and the feature workflow

**Branch names.** `<type>/v<version>/<short-description>`, lowercase with hyphens.
`<type>` says what kind of change it is: `feature`, `bugfix`, `hotfix`, `refactor`,
`design`, `test` or `docs` (add another only when a change fits none of these).
`<version>` is the product version the change ships in. Example:
`refactor/v0.0.1/delete-nextjs-spotify-route`. Branch from an up-to-date `main`, one
change per branch and per PR.

**Feature workflow.** Every change in a release plan (currently
[claude-mds/pyo-0.0.1-sign-in-change.md](claude-mds/pyo-0.0.1-sign-in-change.md)) goes
through these steps in order:

1. **Understand the problem.** Read the code the change touches and check that what the
   plan says about it is still true. Summarize what you found.
2. **Ask clarifying questions** as plain options. Do not mark any option as
   recommended. Wait for the answers.
3. **Write the plan and a test plan.** The test plan says what proves the change works:
   tests to add or change, and any local, CI or production check.
4. **Verify assumptions and test cases.** List every assumption in the plan that isn't
   certain, and what needs checking about the test cases (that they test the intended
   behaviour and would fail without the change). Ask before running an agent on them;
   the user may answer some or all directly.
5. **Get approval on the plan**, then implement and run the test plan.
6. **Review the finished diff** for correctness, simplicity and project conventions.
   Ask before running review agents. Bring the findings back before opening the PR.
7. **Open the PR.** Once checks pass, merge with a merge commit
   (`gh pr merge --merge`, never squash) and confirm the deploy succeeded.

## Constraints worth knowing

The Spotify app is quota-limited to roughly 25 OAuth users, so anything requiring
broad `user-top-read` access is off the table; prefer Client Credentials plus
user-provided data. Background at
[claude-mds/completed/spotify-ingest-without-quota-plan.md](claude-mds/completed/spotify-ingest-without-quota-plan.md).
