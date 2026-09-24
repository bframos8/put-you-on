# Production secrets & config — SSM Parameter Store contract (gameplan Phase 5)

The production app reads **plain environment variables**. In production those come from
AWS **SSM Parameter Store**, under the path `/putyouon/prod/`, materialized into
`.env-backend` / `.env-postgres` on the instance at deploy time. This file is the
authoritative list of what lives there.

- **5.1** create the parameters — [`ssm-seed.sh`](ssm-seed.sh) (run once, re-run to update).
- **5.2** materialize at deploy — [`materialize-env.sh`](materialize-env.sh) (called by the
  Phase 8 SSM deploy step; writes the two `env_file`s the compose services consume).
- **5.3** the local dev contract stays in [`backend/.env.example`](../backend/.env.example) +
  [`backend/.env-postgres.example`](../backend/.env-postgres.example).

> **Portability seam (deployment-learnings §12).** These scripts are the *only* place AWS
> is touched for secrets. The app never calls `boto3`; it reads env vars. To move off AWS
> (the planned Hetzner/Neon migration), swap these two scripts for SOPS/Doppler/plain files
> — the application code doesn't change.

## Encryption key

`SecureString` params are encrypted with the **AWS-managed key `alias/aws/ssm`** (no
`--key-id` needed, no monthly key cost). The instance role's `kms:Decrypt` should be
scoped to that key's ARN — this is the Phase-0 placeholder to tighten (find the ARN with
`aws kms describe-key --key-id alias/aws/ssm --query KeyMetadata.Arn`).

## Parameters

`DAILY_LIMIT_BYPASS` is intentionally **absent** — it must stay unset in prod (the app
warns at startup if it is enabled). Optional params have code defaults; set them in prod
only to override.

| Parameter | Type | Required | Notes |
|---|---|---|---|
| `SESSION_SECRET` | SecureString | ✅ | Session cookie signing key. App refuses to start if unset. |
| `TOKEN_ENCRYPTION_KEYS` | SecureString | ✅ | Fernet key(s) for Spotify tokens at rest. **App *and* alembic** refuse to start if unset. |
| `SPOTIFY_CLIENT_ID` | SecureString | ✅ | Spotify OAuth app id. |
| `SPOTIFY_CLIENT_SECRET` | SecureString | ✅ | Spotify OAuth app secret. |
| `SENTRY_DSN` | SecureString | ✅ | Sentry ingest DSN. (Blank disables Sentry — but in prod set it.) |
| `POSTGRES_USER` | SecureString | ✅ | RDS app user. |
| `POSTGRES_PASSWORD` | SecureString | ✅ | RDS app password. |
| `POSTGRES_DB` | SecureString | ✅ | RDS database name. |
| `POSTGRES_HOST` | String | ✅ | RDS endpoint host. Not secret, but required (no useful default). |
| `POSTGRES_PORT` | String | ✅ | Usually `5432`. |
| `GRAFANA_PROM_URL` | String | ➖ | Grafana Cloud remote-write endpoint (9.1). Consumed by the Alloy agent, not the app. |
| `GRAFANA_PROM_USER` | String | ➖ | Grafana Cloud instance id (numeric). |
| `GRAFANA_PROM_TOKEN` | SecureString | ➖ | Grafana Cloud access token. Metrics stop flowing without it; the app is unaffected. |
| `SPOTIFY_REDIRECT_URI` | String | ✅ | `https://putyouon.app/api/v1/auth/spotify/callback`. Silent localhost fallback if omitted → broken OAuth. |
| `FRONTEND_URL` | String | ✅ | `https://putyouon.app`. |
| `CORS_ALLOWED_ORIGINS` | String | ✅ | `https://putyouon.app`. |
| `ENABLE_HSTS` | String | ✅ | `true` in prod (TLS terminates at nginx). |
| `SENTRY_ENVIRONMENT` | String | optional | Defaults to `production`. |
| `SENTRY_TRACES_SAMPLE_RATE` | String | optional | Defaults to `0.0` (errors only). |
| `SPOTIFY_HTTP_TIMEOUT` | String | optional | Defaults to `10.0`. |
| `OAUTH_STATE_TTL_SECONDS` | String | optional | Defaults to `600`. |
| `LOG_LEVEL` | String | optional | Defaults to `INFO`. |

> The four `Required ✅ String` config params (`SPOTIFY_REDIRECT_URI`, `FRONTEND_URL`,
> `CORS_ALLOWED_ORIGINS`, `ENABLE_HSTS`) are required in the operational sense: if omitted
> the app still *starts* but silently falls back to `127.0.0.1` origins / HSTS-off — broken
> OAuth & CORS with **no startup error**. Always seed them.

## Seeding

```sh
cp deploy/prod.env.example deploy/prod.env   # gitignored; fill in real prod values
aws sso login                                # or otherwise provide AWS creds
./deploy/ssm-seed.sh                          # put-parameter for each known key
```

## IAM (already provisioned in Phase 0)

The instance role (`putyouon-ec2-instance-role`) reads these at deploy via
`ssm:GetParametersByPath` on `arn:aws:ssm:*:*:parameter/putyouon/prod/*` + `kms:Decrypt`.
The CI/CD OIDC role does **not** need SSM read — materialization runs *on the instance*,
not in CI.
