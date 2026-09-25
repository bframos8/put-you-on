# Production runbook

What to do when the site is broken (gameplan 10.4). Written to be followed while tired.

Nothing here contains the AWS account id, the instance id or any secret: every command
looks them up. That keeps the file safe in a public repo, and it keeps working after an
instance rebuild changes the ids.

Architecture in one line: one EC2 box runs nginx, the Next.js frontend and the FastAPI
backend as containers pulled from ECR; Postgres is RDS; deploys go GitHub Actions → SSM.

---

## Get a shell on the box

There is no inbound SSH. Access is SSM only.

```sh
INSTANCE=$(aws ec2 describe-instances \
  --filters 'Name=tag:Name,Values=putyouon-app' 'Name=instance-state-name,Values=running' \
  --query 'Reservations[].Instances[].InstanceId' --output text)
aws ssm start-session --target "$INSTANCE"
sudo -i && cd /opt/putyouon
```

If Session Manager will not connect, the box or its SSM agent is down. Skip to
[Rebuild the instance](#rebuild-the-instance).

---

## Triage: what is actually broken

Run these in order. Each one narrows it down.

| Check | Command | If it fails |
|---|---|---|
| DNS + TLS + nginx + frontend | `curl -sSI https://putyouon.app/` | nginx or frontend down |
| Backend process | `curl -fsS https://putyouon.app/health` | backend down |
| Backend → database | `curl -fsS https://putyouon.app/health/ready` | RDS unreachable |
| Containers | `docker compose -f docker-compose.prod.yaml ps` | see which one |
| Recent logs | `docker compose -f docker-compose.prod.yaml logs --tail 100 backend` | |

`/health` is liveness only and deliberately does not touch the database, so **`/health`
returning 200 does not mean the app works.** `/health/ready` is the one that runs
`SELECT 1`. Check both.

The compose commands above work because every deploy writes `/opt/putyouon/.env` with the
two image refs. If that file is ever missing, compose fails with *"service backend has
neither an image nor a build context specified"* — recover it with:

```sh
printf 'BACKEND_IMAGE=%s\nFRONTEND_IMAGE=%s\n' \
  "$(docker inspect -f '{{.Config.Image}}' putyouon-backend-1)" \
  "$(docker inspect -f '{{.Config.Image}}' putyouon-frontend-1)" > /opt/putyouon/.env
```

### Query the database

There is no psql on the box, and no persistent client image (every deploy runs
`docker image prune -af`, which removes anything without a running container). Run one:

```sh
cd /opt/putyouon && set -a && . ./.env-postgres && set +a
docker run --rm -it --network putyouon_putyouon -e PGPASSWORD="$POSTGRES_PASSWORD" \
  postgres:16-alpine psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB"
```

---

## Roll back to the previous image

**The deployed commit is recorded in `/opt/putyouon/.env`** — the tag on both image refs
is the git SHA. That is where a rollback starts.

> Caution: `.env` names the last SHA the deploy *attempted*. After a failed deploy that is
> not what is serving. Confirm with
> `docker inspect -f '{{.Config.Image}}' putyouon-backend-1`.

### Option A — re-run the previous Deploy workflow (preferred)

Re-running replays the original event, so it redeploys that run's commit, not main's tip.

```sh
gh run list --workflow=Deploy --limit 10 \
  --json databaseId,headSha,conclusion,createdAt \
  --jq '.[] | "\(.databaseId) \(.headSha[0:7]) \(.conclusion) \(.createdAt)"'
gh run rerun <databaseId>
```

Re-run the whole run, not just the deploy job: the deploy job consumes the build job's
outputs, which do not exist on their own.

### Option B — run the deploy by hand on the box

When Actions is down or you need it now. Same script the pipeline runs.

```sh
cd /opt/putyouon
OLD_SHA=<full 40-char sha>
REGISTRY=$(awk -F= '/^BACKEND_IMAGE=/{split($2,a,"/"); print a[1]}' .env)
git fetch --depth 1 origin "$OLD_SHA" && git checkout -q --detach FETCH_HEAD
REGISTRY="$REGISTRY" SHA="$OLD_SHA" bash deploy/deploy.sh
```

### How far back can you roll?

**About five deploys.** The ECR lifecycle policy keeps the last 10 *manifests* with
`tagStatus: any`, and each build pushes two: the image, plus an untagged buildx
attestation of ~40 KB. So ten slots is roughly five deploys, and tagged images do get
expired. Confirm a target still exists before relying on it:

```sh
aws ecr describe-images --repository-name putyouon/backend \
  --query 'sort_by(imageDetails,&imagePushedAt)[].imageTags' --output json
```

If a rollback target has expired, Option B fails at the pull. Rebuild from source instead:
check out the SHA locally, build both images, push them to ECR under that SHA, then run
Option B.

> Worth fixing when there is time: the policy would give a much deeper window if it
> counted only tagged images, or if the workflow disabled buildx provenance.

---

## Roll back a bad migration

Code rollback does **not** undo a migration. `alembic upgrade head` runs on every deploy,
and an older image will not downgrade the schema.

1. **Stop deploys first.** Every merge to main auto-deploys and re-runs `upgrade head`.
2. If the migration has a working `downgrade`, use it:
   ```sh
   docker compose -f docker-compose.prod.yaml run --rm backend alembic downgrade -1
   ```
   then roll the code back. Verify with `alembic current`.
3. If it does not, or data was destroyed, restore the snapshot (below). **Restoring loses
   every write since the snapshot.**

Take a snapshot *before* merging any migration:

```sh
aws rds create-db-snapshot --db-instance-identifier putyouon-db \
  --db-snapshot-identifier "putyouon-db-pre-$(date +%Y%m%d-%H%M)"
```

### Restore from a snapshot

Automated backups run daily with 7-day retention, so point-in-time recovery is available
within that window. This was rehearsed in 9.3 and the restored row counts matched exactly.

Restore to a **new** instance and verify before touching the live one. Never restore over
production as a first move.

```sh
aws rds describe-db-snapshots --db-instance-identifier putyouon-db \
  --query 'sort_by(DBSnapshots,&SnapshotCreateTime)[-5:].[DBSnapshotIdentifier,SnapshotCreateTime]' \
  --output table

aws rds restore-db-instance-from-db-snapshot \
  --db-instance-identifier putyouon-db-restore \
  --db-snapshot-identifier <snapshot-id> \
  --db-instance-class db.t4g.micro --no-publicly-accessible
```

Then point `POSTGRES_HOST` in SSM at the restored endpoint and redeploy:

```sh
aws ssm put-parameter --name /putyouon/prod/POSTGRES_HOST --type String --overwrite \
  --value <new-endpoint>
```

`deploy.sh` re-materializes the env from SSM on every run, so a redeploy picks it up. The
restored instance is **not** in Terraform state — reconcile `infra/rds.tf` afterwards or
the next apply will fight you.

---

## Rebuild the instance

The instance is Terraform-managed, but `infra/main.tf` sets
`ignore_changes = [ami, user_data]`, so editing `user-data.sh` changes nothing on a
running box. It only affects a newly created one. Anything that must apply now has to be
pushed by hand over SSM as well.

**The TLS certificate lives only on this box's EBS volume**, at `/etc/letsencrypt`. A
replaced instance has no certificate and nginx will not start without one. So on a
rebuild, before bringing the stack up, re-run 7.1's bootstrap: a throwaway nginx on :80
serving `/var/www/certbot`, then `certbot certonly --webroot`.

> **Let's Encrypt allows 5 certificates per week for the same set of names.** Burn those
> on retries and you are waiting days, serving nothing. Get the webroot working *before*
> running certbot for real — use `--dry-run` first, which does not count against the
> limit.

Also gone with the old volume: `/var/log/putyouon-deploy.log`, the Alloy WAL, and any
unpushed local state. The database is unaffected, it is RDS.

---

## The ingest worker

The audio download happens on a machine outside AWS (`worker/`, gameplan 10.6), because
YouTube bot-blocks the instance's IP. Two symptoms point here.

**Users stuck on "Building your drop".** A worker that is not running produces no errors
anywhere — the app just has seeds nobody claims, which looks exactly like work in
progress. Check the worker process on the Mac first; its log line is `Claimed N seed(s)`.
Then check the queue:

```sql
SELECT count(*) FILTER (WHERE song_id IS NULL AND ingest_failed_at IS NULL) AS pending,
       count(*) FILTER (WHERE claimed_at IS NOT NULL AND song_id IS NULL) AS claimed,
       count(*) FILTER (WHERE ingest_failed_at IS NOT NULL) AS failed
FROM user_top_songs;
```

`pending` high and `claimed` zero means nothing is working the queue. A stuck `claimed`
row clears itself after the 15-minute lease.

**Turning the worker off** is one parameter: set `INGEST_WORKER_ENABLED` to anything but
`true` (or delete it) and redeploy. The backend goes back to doing the ingest itself,
which on this instance means every download fails — but failures are now bounded, so it
degrades to "no seeds" rather than looping. Clearing `INGEST_WORKER_TOKEN` additionally
makes the whole `/api/v1/ingest/*` surface 404, which is the right move if the worker
machine is lost or the token leaks.

### Re-arming seeds that failed under an old download path

A seed retires after `INGEST_MAX_ATTEMPTS` and nothing un-retires it, so users whose
tracks failed while the download was broken stay stuck even after it is fixed. Run this
**once, after the new path is live** — not before, or the still-deployed old code will
re-fail the rows before the worker ever sees them:

```sql
UPDATE user_top_songs
   SET ingest_failed_at = NULL, ingest_attempts = 0, ingest_error = NULL, claimed_at = NULL
 WHERE song_id IS NULL
   AND ingest_failed_at IS NOT NULL;
```

Scoped to rows that are both unprocessed and retired: it must not zero the attempt count
of a seed that is mid-retry, and it must not touch a seed that already has a song.

This is a manual patch, not a policy. The question 10.5 left open — whether terminal
failures should expire on their own after N days — is still open.

---

## Alarms, and what each one means

All seven notify the SNS topic `putyouon-alerts` by email.

| Alarm | What it means | First move |
|---|---|---|
| `putyouon-site-down` | The box's own 5-minute check failed, or the box went silent. Treats missing data as breaching, so a dead instance fires it. | Triage above |
| `putyouon-ec2-status-check-failed` | The instance or its host is unhealthy | Console; AWS may auto-recover |
| `putyouon-disk-high` | Root volume over 80% of 12 GB | `docker image prune -af`, check `/var/log` |
| `putyouon-cert-expiring` | Under 20 days left, so renewal has failed ~10 times | `systemctl status certbot-renew.timer`, `/var/log/letsencrypt` |
| `putyouon-rds-free-storage-low` | Under 3 GB free | Raise `allocated_storage` in `infra/rds.tf` |
| `putyouon-rds-connections-high` | Over 80 of ~112 | Look for leaked sessions or pool size |
| `putyouon-rds-cpu-credits-low` | Sustained CPU billed as surplus credits. This is a **cost** alarm, not an outage. | Expected during an index build; otherwise investigate load |

Host CPU, memory, disk and network are in Grafana Cloud (9.1), collected by the Alloy
container. Grafana is not in the alerting path — if Alloy dies you lose dashboards, not
alarms.

---

## Things that will surprise you

- **`docker image prune -af`** runs at the end of every deploy and removes any image
  without a running container, including one you just pulled to debug with.
- **nginx config changes need a container recreate, not a reload.** `nginx.prod.conf` is a
  single-file bind mount, resolved by inode at container start. `git checkout` replaces
  the file, so the container keeps reading the old inode. A HUP reloads the stale config
  and reports success. `deploy.sh` handles this with
  `up -d --force-recreate --no-deps nginx`; remember it if you ever edit the config in
  place on the box.
- **A deploy kills any in-flight ingest.** `up -d` recreates the backend container.
- **The first `alembic revision --autogenerate` will emit four spurious constraint
  operations**, renaming `songs_album_id_title_key` and `albums_url_key`. The live names
  are Postgres defaults, the models use the `uq_` convention. Delete them from the
  generated migration unless you mean to rename.
