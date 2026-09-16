# put-you-on

App flow: 

- User logs into Spotify Account using OAuth
- This creates a user in database with corresponding Spotify metadata  
- Top Songs are downloaded from Youtube 
- Audio files are run through Essentia Model for embeddings
- Embeddings and metadata are added to database with a flag to not use song as a recommendation 
- Call on 10 closest neighbors per song, cache in metadata of song.
- Give 10 recommended songs per day max. 


Tech Stack for active web application: 

- Frontend: Built using Typescript, Javascript, CSS, and HTML via React with Next.js hosted on AWS EC2. 
    - Testing: Typescript check and manual checks of documentation from next.js and endpoint checks via browser. 

- Backend: Built using Python via FastAPI. Implemented RESTful API to enable auth flow, user ingestion, and recommendation pipelines. Hosted on AWS EC2. 
    - Testing: Full suite of tests in Python using Pytest and Unittest libraries. 

- Database: Deployed relational database via PostgreSQL 16.13 with PGVector extension. Utilizes enums for restricting entries. Uses indexing and relations for quick recommendations via vector search. Hosted on AWS Relational Database Service (RDS). 

- DevOps: Github Actions automatically runs test suites on a PR. If tests pass and after manual check, new version is deployed via Docker and Docker compose onto AWS EC2 instance. 

- Security: All secrets are kept in .env files for local development and in Github Secrets for production. 


Data pipeline for database populating: 

- Nightly Cron Jobs for two different stages.

- Cron Job 1: Web-crawler using Python via Playwright to extract new album website links from every main category in BandCamp. 
    - Adds album link to database if link has not been cached in session history or in database. 

- Cron Job 2: Process album links and insert songs into database via a feeder-consumer design pattern with each job on a different core (Python has the GLI so not exactly parallel). 
    - Web-scrape audio files and metadata using BandCamp-dl library
    - Audio files are ran through Essentia Model for vector embedding
    - Audio files are deleted to save memory and adhere to standard policies. 
    - Embedding and audio metadata is inserted into songs table in database. 

AI tools:
- Claude is my tool of choice. I use skills for consistent code generation and direction(/frontend-design and /feature-dev). CLAUDE.md holds project context and my development preferences, and is committed so it travels between machines.

# Setting up on a new machine

`git clone` gets you the code, the Claude docs in `claude-mds/`, the skills in
`.claude/skills/`, and the `.env` templates. Four things it deliberately does not
get you, because they are secrets or licensed files.

**1. Fonts (required — the build fails without them).**
`frontend/src/assets/fonts/` is gitignored. `frontend/src/app/layout.tsx` loads nine
files through `next/font/local`, which resolves them at build time, so both
`npm run build` and `docker compose build frontend` fail on a fresh clone. Copy the
directory over by hand. Only `SmileySans-Oblique.woff2` is in the repo; the Helvetica
and Estrella files are commercially licensed and must not be committed to a public
repo.

**2. TLS certificates.** The nginx service bind-mounts `frontend/localhost+1.pem`
and `frontend/localhost+1-key.pem`, and `npm run dev` passes them to Next. Do not
copy these — the `-key.pem` is a private key. Regenerate:

```bash
brew install mkcert && mkcert -install
cd frontend && mkcert 127.0.0.1 localhost
```

**3. Local environment files.** Copy each template and fill it in:

```bash
cp backend/.env.example           .env-backend
cp backend/.env-postgres.example  .env-postgres
cp frontend/.env.local.example    frontend/.env.local
```

`SESSION_SECRET` and `TOKEN_ENCRYPTION_KEYS` should be generated fresh rather than
copied (the generation commands are in `backend/.env.example`). Postgres credentials
are yours to choose. Only the Spotify client ID and secret have to match the other
machine — take them from the Spotify developer dashboard.

**4. AWS credentials**, if you intend to deploy or touch SSM: `aws configure`.
Production secrets live in Parameter Store and are materialized at deploy, so nothing
production-related needs to be copied between machines. See `deploy/ssm-parameters.md`.

## Dependencies

Docker covers most of this. `docker compose up -d` builds the backend and frontend
images from `backend/backend_requirements.txt` and `frontend/package-lock.json`, and
pulls `pgvector/pgvector:pg16` and `nginx:alpine`. No host Python or Node needed to
*run* the web app.

Three things still need host-side setup, because they are not containerized:

- **The data pipeline** has no Dockerfile. It runs on the host from
  `data_pipeline/pipeline_requirements.txt` in a venv.
- **Tests.** `backend/.dockerignore` excludes `tests/` and `test-requirements.txt`
  from the image, so pytest runs on the host against a venv.
- **Alembic**, when running migrations from the host rather than exec'ing into the
  container.

```bash
python3.11 -m venv .venv.backend  && .venv.backend/bin/pip  install -r backend/backend_requirements.txt -r backend/test-requirements.txt
python3.11 -m venv .venv.pipeline && .venv.pipeline/bin/pip install -r data_pipeline/pipeline_requirements.txt
```

Verified against Python 3.11 and Node 20 (the version in the frontend image).

# Project Steps
Development Phase 1: 

1. Setup local Postgres database for link checking capabilities 
    1. album, song, artist tables to start.

2. Setup locally run web-crawler that feeds into local PostgreSQL.
3. Optionally containerize 

Development Phase 2: 

1. Setup locally run scraper that downloads each album from album table links 
2. Process songs and insert into local PostgreSQL.
3. Optionally contanerize 

Developments Phase 3: 

1. Deploy database onto AWS RDS and run nightly Cron Jobs for pipelines. 
1. Start new next.js project 
2. Create the api calls 
3. Create the front end that hooks up to backend 
4. Once working correctly and stable, containerize and send to AWS EC2 

Disclaimer: 
This app stores your Spotify ID, display name, email, and OAuth tokens; tokens are used to fetch your top tracks; data is stored in Postgres on AWS RDS in us-east-1.





