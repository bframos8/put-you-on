#!/usr/bin/env bash
# Materialize prod secrets from SSM into .env-backend / .env-postgres (gameplan 5.2).
#
# Runs ON THE INSTANCE at deploy time (invoked by the Phase 8 SSM deploy step), using the
# instance role's ssm:GetParametersByPath + kms:Decrypt. Writes two root-owned, chmod 600
# env files next to docker-compose.prod.yaml; docker compose's `env_file:` consumes them.
# Params under /putyouon/prod are split by name: POSTGRES_* -> .env-postgres (also the
# file the dev db service reads), everything else -> .env-backend.
#
# Portability seam (deployment-learnings §12): this is the ONLY place SSM is read. The app
# reads plain env vars, never boto3 — swap this script to move off AWS.
set -euo pipefail

SSM_PATH="${SSM_PATH:-/putyouon/prod}"
# Default output dir = repo root (parent of this deploy/ dir), where the compose file and
# its env_file: entries live. Override with OUT_DIR for testing.
OUT_DIR="${OUT_DIR:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}"
BACKEND_ENV="${OUT_DIR}/.env-backend"
POSTGRES_ENV="${OUT_DIR}/.env-postgres"

# Pull every parameter under the path, decrypted, as JSON. The AWS CLI auto-paginates, so
# all params come back in one Parameters[] array regardless of count. JSON (not
# --output text) because values may contain tabs/URLs/base64 that text output mangles.
ssm_json="$(aws ssm get-parameters-by-path \
  --path "$SSM_PATH" \
  --with-decryption \
  --output json)"

# New files are 600 from creation (defense before the explicit chmod below).
umask 077

# Parse + split with python3 (present on Amazon Linux 2023). Writes raw KEY=VALUE lines —
# docker compose reads the whole line after '=' as the value, so no quoting is needed and
# values may contain '=', '#', etc. Fails loudly if a required secret is missing so a
# misconfigured SSM becomes a failed deploy, not a broken container boot.
SSM_JSON="$ssm_json" python3 - "$BACKEND_ENV" "$POSTGRES_ENV" <<'PY'
import json, os, sys

backend_path, postgres_path = sys.argv[1], sys.argv[2]
params = json.loads(os.environ["SSM_JSON"]).get("Parameters", [])

backend, postgres = {}, {}
for p in params:
    name = p["Name"].rsplit("/", 1)[-1]      # /putyouon/prod/FOO -> FOO
    (postgres if name.startswith("POSTGRES_") else backend)[name] = p["Value"]

required = ["TOKEN_ENCRYPTION_KEYS", "SESSION_SECRET"]
missing = [k for k in required if k not in backend or backend[k] == ""]
if "POSTGRES_PASSWORD" not in postgres or postgres["POSTGRES_PASSWORD"] == "":
    missing.append("POSTGRES_PASSWORD")
if missing:
    sys.exit(f"ERROR: required SSM params missing/empty under the path: {', '.join(missing)}")

def write(path, kv):
    with open(path, "w") as f:
        for k in sorted(kv):                 # stable, diff-friendly ordering
            f.write(f"{k}={kv[k]}\n")

write(backend_path, backend)
write(postgres_path, postgres)
sys.stderr.write(f"materialized {len(backend)} backend + {len(postgres)} postgres var(s)\n")
PY

chmod 600 "$BACKEND_ENV" "$POSTGRES_ENV"
