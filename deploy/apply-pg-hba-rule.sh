#!/bin/sh
# Adds a pg_hba.conf rule allowing Docker containers on this host to reach
# the isolated Relu_Vendor2_docker database (see setup-remote-db.sh) —
# scoped to just that database and the relu_user role, not opened up
# broadly. Run this AFTER setup-remote-db.sh has created the database.
#
# 172.16.0.0/12 covers the full private range Docker's default bridge
# networks are assigned from (172.17.0.0/16 through 172.31.0.0/16) — the
# actual subnet a compose project gets can change across recreations, so a
# single subnet like 172.18.0.0/16 isn't reliable long-term.
#
# Auth method matches the existing per-database rule already in
# pg_hba.conf for Relu_Vendor2/relu_user (scram-sha-256), not the broader
# catch-all rule (md5), since this is the same kind of scoped rule.
set -e

DB_NAME="${1:-Relu_Vendor2_docker}"
DB_USER="${2:-relu_user}"

HBA=$(sudo -u postgres psql -tAc "show hba_file;")
RULE="host    $DB_NAME    $DB_USER    172.16.0.0/12    scram-sha-256"

echo "Appending to $HBA:"
echo "  $RULE"
echo "$RULE" | sudo tee -a "$HBA" > /dev/null

echo "Reloading Postgres config..."
sudo -u postgres psql -c "SELECT pg_reload_conf();"

echo "Done. New entry:"
sudo grep "$DB_NAME" "$HBA"
