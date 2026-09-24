#!/usr/bin/env bash
# Deploy one commit's images onto the instance (gameplan 8.3).
#
# Runs ON THE INSTANCE as root, invoked by the SSM step in .github/workflows/deploy.yml,
# which has already checked this repo out at $SHA in /opt/putyouon. Requires REGISTRY
# (the ECR host) and SHA (the commit being deployed) in the environment.
#
# Most steps are noisy (a cold pull is ~1.9 GB of layer lines) and SSM only returns the
# last 24,000 characters of output, which is enough to bury the actual error. So the
# chatty parts go to a log file and the interesting lines are echoed; on failure the tail
# of the log is printed so the GitHub job shows why.
set -euo pipefail

: "${REGISTRY:?REGISTRY is required}"
: "${SHA:?SHA is required}"

APP_DIR=/opt/putyouon
LOG=/var/log/putyouon-deploy.log

# compose resolves env_file: and ./nginx/nginx.prod.conf relative to the compose file, and
# SSM starts commands in its own working directory, so this cd is load-bearing.
cd "$APP_DIR"

export BACKEND_IMAGE="$REGISTRY/putyouon/backend:$SHA"
export FRONTEND_IMAGE="$REGISTRY/putyouon/frontend:$SHA"

# The same two values on disk, because compose auto-loads .env from the compose file's
# directory for ${...} interpolation. Without it a plain `docker compose -f ... ps` or
# `logs` on the box doesn't warn, it FAILS ("service frontend has neither an image nor a
# build context specified") — and that is exactly the moment you need those commands,
# mid-incident (10.4). The file also records which SHA is deployed, which is where a
# rollback starts.
#
# Written atomically: a half-written .env would break every compose invocation on the box,
# including this script's own pull/run/up. Mode 644, not the 600 materialize-env.sh uses —
# these are image refs, not secrets, and copying that pattern would imply otherwise. The
# exports above still take precedence during this run (shell beats .env), so a stale file
# from a failed deploy cannot affect a later one; it does mean the file names the last SHA
# *attempted*, which after a failure is not the one still serving.
printf 'BACKEND_IMAGE=%s\nFRONTEND_IMAGE=%s\n' "$BACKEND_IMAGE" "$FRONTEND_IMAGE" \
  > "$APP_DIR/.env.tmp"
chmod 644 "$APP_DIR/.env.tmp"
mv "$APP_DIR/.env.tmp" "$APP_DIR/.env"

COMPOSE=(docker compose -f "$APP_DIR/docker-compose.prod.yaml")

echo "Deploying $SHA"
: > "$LOG"

on_failure() {
  echo "--- deploy failed; last 80 log lines ---"
  tail -80 "$LOG" || true
}
trap on_failure ERR

# 1. Secrets and config from SSM -> .env-backend / .env-postgres, chmod 600, next to the
#    compose file (5.2). Regenerated every deploy; SSM is the source of truth.
echo "==> materializing env from SSM"
bash "$APP_DIR/deploy/materialize-env.sh" >>"$LOG" 2>&1

# 2. ECR login using the instance role (0.4) — no keys on the box.
echo "==> logging in to ECR"
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin "$REGISTRY" >>"$LOG" 2>&1

# 3. Pull the SHA-pinned images. Immutable tags make a deploy traceable and a rollback a
#    redeploy of the previous SHA (10.4).
echo "==> pulling images"
"${COMPOSE[@]}" pull >>"$LOG" 2>&1

# 4. Migrations as an explicit step, before the new code serves. compose run (not docker
#    run) so env_file: supplies POSTGRES_* and TOKEN_ENCRYPTION_KEYS, both of which the
#    alembic import chain needs (alembic/env.py -> app/core/crypto.py).
echo "==> alembic upgrade head"
"${COMPOSE[@]}" run --rm backend alembic upgrade head 2>&1 | tee -a "$LOG" | tail -5

# 5. Recreate the stack. Compose waits for backend and frontend to report healthy before
#    starting what depends on them (3.3). Note: this kills any in-flight ingest.
echo "==> starting the stack"
"${COMPOSE[@]}" up -d >>"$LOG" 2>&1

# 6. Recreate nginx so that a changed config actually takes effect. `up -d` alone never
#    touches it: nginx pins nginx:alpine with no build, so its container spec is identical
#    between deploys and compose sees nothing to do. (Observable: nginx's uptime outlives
#    every deploy while backend and frontend restart.)
#
#    A reload is not enough either, and this is the subtle part. The config is a
#    SINGLE-FILE bind mount, which Docker resolves by inode at container start. `git
#    checkout` replaces the file rather than editing it in place, so the new content
#    arrives on a NEW inode while the container goes on reading the old one — which still
#    exists precisely because the mount holds it. A HUP then reloads the stale config and
#    reports success, and `nginx -t` inside the container "passes" for the same reason: it
#    is testing the old file. Measured 2026-09-24 — the file on disk had the new headers,
#    the identical path inside the container had none, and the worker had genuinely been
#    replaced by the HUP. Recreating the container is what re-resolves the mount.
#
#    --no-deps so this recreates nginx alone; without it, `up SERVICE` would also
#    force-recreate backend and frontend, which step 5 just settled. A broken config is
#    caught by the health gate below, which curls through nginx.
echo "==> recreating nginx"
"${COMPOSE[@]}" up -d --force-recreate --no-deps nginx >>"$LOG" 2>&1

# 7. Health gate: a bad deploy should fail the job, not sit there silently broken. Through
#    nginx on :443 so this also proves TLS and the proxy, not just the backend. -k because
#    the cert is for putyouon.app, which is what the Host header claims.
echo "==> waiting for /health"
for attempt in $(seq 1 20); do
  if curl -fsS -k -m 5 -H 'Host: putyouon.app' https://localhost/health >/dev/null 2>&1; then
    echo "healthy after ${attempt} attempt(s)"
    break
  fi
  if [ "$attempt" -eq 20 ]; then
    echo "health check never passed"
    "${COMPOSE[@]}" ps >>"$LOG" 2>&1 || true
    "${COMPOSE[@]}" logs --tail 50 >>"$LOG" 2>&1 || true
    false
  fi
  sleep 5
done

# 8. Reclaim disk. -af, not -f: plain prune only removes *dangling* images, and SHA-tagged
#    old images aren't dangling, so they would fill the 12 GB disk over time (6.1). The
#    cost is that a rollback re-pulls the previous image from ECR.
echo "==> pruning unused images"
docker image prune -af >>"$LOG" 2>&1

"${COMPOSE[@]}" ps --format '{{.Service}} {{.Status}}'
echo "Deployed $SHA"
