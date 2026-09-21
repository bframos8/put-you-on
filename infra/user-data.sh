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

docker --version
docker compose version
