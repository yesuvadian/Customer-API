#!/bin/sh
# One-time setup for the Docker deployment's isolated database — run this
# ON the target server (scp it over, then ssh in and run it there; see
# deploy-docker.ps1's own comments for why this needs its own database).
#
# Usage: bash setup-remote-db.sh [source_db] [target_db] [db_owner]
# Defaults match dev.remote.env's Relu_Vendor2 -> Relu_Vendor2_docker.
set -e

SOURCE_DB="${1:-Relu_Vendor2}"
TARGET_DB="${2:-Relu_Vendor2_docker}"
DB_OWNER="${3:-relu_user}"

echo "Cloning $SOURCE_DB into $TARGET_DB (owner: $DB_OWNER)..."
sudo -u postgres createdb -O "$DB_OWNER" "$TARGET_DB"
# pg_dump | psql, not CREATE DATABASE ... TEMPLATE — the source database is
# live with active connections from the existing bare-metal service, and
# TEMPLATE-based cloning requires no other sessions on the source.
sudo -u postgres pg_dump "$SOURCE_DB" | sudo -u postgres psql "$TARGET_DB"
echo "Clone complete."
echo ""

HBA=$(sudo -u postgres psql -tAc "show hba_file;")
echo "pg_hba.conf is at: $HBA"
echo ""
echo "Existing entries (to match auth method before adding a new rule):"
sudo grep -v '^#' "$HBA" | grep -v '^$'
