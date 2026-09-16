# Commands

Working runbook for this repo. Paths are relative to the repo root unless noted.

## Backend

Run with SSL (uses the mkcert certs that live in `frontend/`):

```bash
cd backend && uvicorn app.main:app --reload \
  --ssl-keyfile ../frontend/localhost+1-key.pem \
  --ssl-certfile ../frontend/localhost+1.pem
```

## Frontend

```bash
cd frontend && npm run dev
```

## Database

```bash
docker compose up -d
docker exec -it put-you-on-db-1 psql -U ramos -d pyo_db_2
```

The compose service is named `db`, so the container is `put-you-on-db-1`.

Remote (RDS):

```bash
# old
psql -h put-you-on-instance-1.calaeskuuhry.us-east-1.rds.amazonaws.com -U ramos -d put_you_on_db_1 -p 5432 -W

# new, optimized
psql -h put-you-on-instance-2.calaeskuuhry.us-east-1.rds.amazonaws.com -U ramos -d pyo_db -p 5432 -W
```

## Migrations

Run from `backend/`. `TOKEN_ENCRYPTION_KEYS` must be exported or alembic refuses to
start (see `backend/.env.example`).

```bash
# generate a migration from model changes
alembic revision --autogenerate -m "describe the change"

# apply to the database
alembic upgrade head
```

## Spotify OAuth callbacks

Whichever you use must also be registered in the Spotify app dashboard.

```
# via docker (nginx on :443)
https://127.0.0.1/api/v1/auth/spotify/callback

# local uvicorn
https://127.0.0.1:8000/api/v1/auth/spotify/callback
```

## Docker

```bash
docker compose build frontend
docker compose up -d --no-deps frontend
```

## Tests

`backend/.dockerignore` keeps `tests/` and `test-requirements.txt` out of the image,
so the suite runs on the host against a venv, not in the container.

```bash
# backend
cd backend && pytest

# data pipeline
cd data_pipeline && pytest
```
