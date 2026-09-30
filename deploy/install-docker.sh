#!/bin/sh
# One-time Docker install for Oracle Linux 9 (RHEL-compatible, dnf-based) —
# run this on Primary (192.168.0.105) and DR (192.168.0.100) before the
# first `deploy-docker.ps1 -Environment main` run. The dev VM
# (192.168.0.109) already had Docker; these did not.
#
# docker-ce's own repo only publishes for a few named distros; "centos" is
# the correct target for any RHEL-family system (Oracle Linux, Rocky,
# Alma, RHEL itself) since they're binary-compatible at the package level.
set -e

# --setopt=skip_if_unavailable=true: this server has an unrelated, broken
# repo (pgdg13 - an old PostgreSQL 13 YUM repo, HTTP 410 Gone upstream,
# likely stale from before the server was upgraded to Postgres 17). dnf
# refreshes ALL configured repos' metadata before installing anything, so
# without this flag that one dead repo aborts the whole install even
# though it has nothing to do with Docker. Doesn't touch the existing
# repo config, just tells dnf to skip what it can't reach this run.
echo "Installing Docker CE + Compose plugin..."
sudo dnf -y --setopt=skip_if_unavailable=true install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf -y --setopt=skip_if_unavailable=true install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "Enabling and starting the docker service..."
sudo systemctl enable --now docker

echo "Adding erp to the docker group (so future ssh sessions can run docker without sudo)..."
sudo usermod -aG docker erp

echo ""
echo "Done. Verifying:"
sudo docker --version
sudo docker compose version
