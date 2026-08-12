#!/usr/bin/env bash
# Seed the /putyouon/prod/* SSM parameters from a local values file (gameplan 5.1).
#
# Run ONCE, and re-run any time to update values (uses --overwrite). Requires AWS creds
# that can ssm:PutParameter and use the default SSM KMS key (alias/aws/ssm). Values come
# from a LOCAL, GITIGNORED file — never committed:
#
#   cp deploy/prod.env.example deploy/prod.env   # then fill in real prod values
#   aws sso login                                # or otherwise provide AWS creds
#   ./deploy/ssm-seed.sh                          # optional: pass a different values file
#
# See deploy/ssm-parameters.md for the full contract. This is the only place the param
# type (SecureString vs String) is decided.
set -euo pipefail

SSM_PATH="${SSM_PATH:-/putyouon/prod}"
VALUES_FILE="${1:-"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prod.env"}"

if [ ! -f "$VALUES_FILE" ]; then
  echo "ERROR: values file not found: $VALUES_FILE" >&2
  echo "       cp deploy/prod.env.example deploy/prod.env and fill it in." >&2
  exit 1
fi

# Secrets -> SecureString (encrypted with alias/aws/ssm); config -> String.
# DAILY_LIMIT_BYPASS is intentionally absent — it must stay UNSET in prod.
SECURESTRING_KEYS="SESSION_SECRET TOKEN_ENCRYPTION_KEYS SPOTIFY_CLIENT_ID SPOTIFY_CLIENT_SECRET SENTRY_DSN POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB"
STRING_KEYS="POSTGRES_HOST POSTGRES_PORT SPOTIFY_REDIRECT_URI FRONTEND_URL CORS_ALLOWED_ORIGINS ENABLE_HSTS SENTRY_ENVIRONMENT SENTRY_TRACES_SAMPLE_RATE SPOTIFY_HTTP_TIMEOUT OAUTH_STATE_TTL_SECONDS LOG_LEVEL"

type_for() {
  local key="$1" k
  for k in $SECURESTRING_KEYS; do [ "$k" = "$key" ] && { echo SecureString; return; }; done
  for k in $STRING_KEYS;       do [ "$k" = "$key" ] && { echo String;       return; }; done
  echo ""  # unknown key
}

count=0
# Read KEY=VALUE lines; skip blanks/comments. Everything after the first '=' is the
# value (so values may themselves contain '='). No `source` — we never execute the file.
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in ''|'#'*) continue ;; esac
  case "$line" in *'='*) : ;; *) continue ;; esac  # require a '='
  key="${line%%=*}"
  val="${line#*=}"
  key="${key//[[:space:]]/}"                        # trim whitespace around the key
  [ -z "$val" ] && { echo "skip empty: $key" >&2; continue; }

  ptype="$(type_for "$key")"
  if [ -z "$ptype" ]; then
    echo "skip unknown key (not in contract): $key" >&2
    continue
  fi

  echo "put ${SSM_PATH}/${key} (${ptype})"
  aws ssm put-parameter \
    --name "${SSM_PATH}/${key}" \
    --type "$ptype" \
    --value "$val" \
    --overwrite >/dev/null
  count=$((count + 1))
done < "$VALUES_FILE"

echo "seeded ${count} parameter(s) under ${SSM_PATH}."
