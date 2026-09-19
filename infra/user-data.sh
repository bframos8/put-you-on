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
mkdir -p /var/www/certbot

docker --version
docker compose version
