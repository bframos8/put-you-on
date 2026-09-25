#!/bin/bash
# First-boot setup for the app host (gameplan 6.3). Runs once, as root, via cloud-init.
# Output lands in /var/log/cloud-init-output.log. Terraform ignores later edits to this
# file for the running instance, so changes here only affect a newly created one.
set -euxo pipefail

# Swap (6.1): 2 GB on a 2 GB box, so a spike (model load plus a spotdl subprocess) slows
# down instead of triggering the OOM killer. Low swappiness keeps it a safety net.
if [ ! -f /swapfile ]; then
  # dd, not fallocate: AWS's documented method, and safe for swap on any filesystem.
  dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap defaults 0 0' >> /etc/fstab
  echo 'vm.swappiness=10' > /etc/sysctl.d/99-swappiness.conf
  sysctl -p /etc/sysctl.d/99-swappiness.conf
fi

# Docker Engine from AL2023's own repo, started now and on every boot (the compose
# restart policies from 3.3 bring the stack back after a reboot).
dnf install -y docker
systemctl enable --now docker

# Compose plugin. AL2023's repos don't ship docker-compose-plugin, so fetch Docker's
# release binary, pinned and checked against its published SHA-256.
COMPOSE_VERSION=v5.5.1
COMPOSE_SHA256=db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64"
echo "${COMPOSE_SHA256}  /usr/local/lib/docker/cli-plugins/docker-compose" | sha256sum -c -
chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose

# ACME webroot that nginx serves read-only and Certbot writes into (3.5, Phase 7).
mkdir -p /var/www/certbot /var/log/letsencrypt

# Certificate renewal (7.2). Certbot runs as a container: AL2023 has no certbot package
# and no EPEL. `renew` re-uses the authenticator recorded at issuance (webroot), so the
# command needs no flags; /var/log/letsencrypt is mounted so a failure still leaves a log
# behind --quiet. The certificate itself is issued once, by hand (7.1) — a fresh instance
# has no /etc/letsencrypt, and this timer simply finds nothing to renew until it does.
cat > /usr/local/bin/reload-nginx.sh <<'EOF'
#!/bin/sh
# HUP the compose-managed nginx so it picks up a renewed certificate. A reload keeps the
# process (and its connections) alive; a restart would drop them. No-op when the stack
# isn't running, so the renewal timer never fails because of it.
ids=$(docker ps -q -f label=com.docker.compose.service=nginx)
[ -n "$ids" ] && docker kill -s HUP $ids
exit 0
EOF
chmod 755 /usr/local/bin/reload-nginx.sh

cat > /etc/systemd/system/certbot-renew.service <<'EOF'
[Unit]
Description=Renew Let's Encrypt certificates (certbot container, webroot)
# Persistent=true can fire this at boot, before dockerd is up.
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/bin/docker run --rm -v /etc/letsencrypt:/etc/letsencrypt -v /var/lib/letsencrypt:/var/lib/letsencrypt -v /var/log/letsencrypt:/var/log/letsencrypt -v /var/www/certbot:/var/www/certbot certbot/certbot renew --quiet
# certbot's own --deploy-hook can't do this: it runs inside the certbot container, which
# has no docker CLI or socket. A script, not an inline command, because systemd would try
# to expand the `$` in a unit file.
ExecStartPost=/usr/local/bin/reload-nginx.sh
EOF

cat > /etc/systemd/system/certbot-renew.timer <<'EOF'
[Unit]
Description=Run certbot renew twice daily

[Timer]
# Twice daily is what Let's Encrypt asks for; renewal only acts inside the last 30 days.
# The random delay spreads load on their API instead of hitting it on the hour.
OnCalendar=*-*-* 03,15:00:00
RandomizedDelaySec=3600
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now certbot-renew.timer

# Self-reported CloudWatch metrics (9.2). These three aren't available to AWS: EC2 has no
# native disk metric, nothing outside the box knows whether the site answers, and nothing
# watches the certificate. The matching alarms live in infra/monitoring.tf; the uptime one
# treats missing data as breaching, so a silent box alarms too.
cat > /usr/local/bin/putyouon-metrics.sh <<'EOF'
#!/bin/bash
set -uo pipefail
REGION=us-east-1
CERT=/etc/letsencrypt/live/putyouon.app/cert.pem

# Through the public name, not localhost: this exercises DNS, nginx, TLS and the app the
# way a user does.
#
# /health/ready, not /health. /health is liveness only — it answers 200 with the database
# completely gone, so the alarm sat green through the single most likely way this app
# breaks. /ready runs SELECT 1 and returns 503 when it can't, which -f turns into a
# non-zero exit and so up=0.
#
# The grep pattern is part of the endpoint choice, not decoration: /health returns
# "ok" and /health/ready returns "ready". Change one without the other and a perfectly
# healthy site publishes up=0, putting you in permanent ALARM ten minutes later.
if curl -fsS -m 10 https://putyouon.app/health/ready | grep -q '"status":"ready"'; then
  up=1
else
  up=0
fi

# SiteUp goes in its own call on purpose. put-metric-data rejects the WHOLE call if any
# value is malformed, and the site-down alarm treats missing data as breaching — so a bad
# certificate reading must not be able to suppress the uptime signal and page you falsely.
aws cloudwatch put-metric-data --region "$REGION" --namespace putyouon/instance \
  --metric-data "MetricName=SiteUp,Value=${up},Unit=None"

metrics=""

# Absent before the certificate is first issued (7.1); that alarm treats missing as OK.
if [ -f "$CERT" ]; then
  end=$(openssl x509 -enddate -noout -in "$CERT" | cut -d= -f2)
  days=""
  [ -n "$end" ] && days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
  [ -n "$days" ] && metrics="MetricName=CertDaysRemaining,Value=${days},Unit=Count"
fi

disk=$(df --output=pcent / | tail -1 | tr -dc '0-9')
[ -n "$disk" ] && metrics="$metrics MetricName=DiskUsedPercent,Value=${disk},Unit=Percent"

if [ -n "$metrics" ]; then
  # shellcheck disable=SC2086 # deliberate word splitting: one entry per metric
  aws cloudwatch put-metric-data --region "$REGION" --namespace putyouon/instance \
    --metric-data $metrics
fi
EOF
chmod 755 /usr/local/bin/putyouon-metrics.sh

cat > /etc/systemd/system/putyouon-metrics.service <<'EOF'
[Unit]
Description=Publish putyouon host metrics to CloudWatch
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/putyouon-metrics.sh
EOF

cat > /etc/systemd/system/putyouon-metrics.timer <<'EOF'
[Unit]
Description=Publish putyouon host metrics every 5 minutes

[Timer]
# Matches the alarms' 300s period. Two missed runs is what trips the site-down alarm, so
# keep systemd's default 1-minute slack from drifting runs into the next window.
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=1s

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now putyouon-metrics.timer

docker --version
docker compose version
