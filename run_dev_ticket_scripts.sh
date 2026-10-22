#!/usr/bin/env bash
# Copyright (c) 2026 ReLU Technologies Private Limited. All rights reserved.
#
# One-time DB steps for the TSMS tickets (AI dashboards / AI Graph, equipment
# health, row-average table scoring). The Jenkins deploy only runs
# `pip install` and restarts the API, so run this by hand on the server once
# the new API is deployed:
#
#   cd /apps/customer/api
#   bash run_dev_ticket_scripts.sh            # check, apply, recompute
#   bash run_dev_ticket_scripts.sh --check    # only show what's missing (read-only)
#
# Every step is safe to re-run:
#   1. alter_ageing_config.py                       ageing_config / equipment_expected_life tables (+ defaults)
#   2. alter_health_scoring_config.py               health_scoring_config table ("Table scoring"; default worst row)
#   3. alter_exempt_nameplate_inspection_templates.py   nameplate / inspection templates exempt from "no thresholds"
#   4. run_recompute_all_analytics.py               re-evaluate + rescore every stored result (the app's
#                                                   Recompute All only rescores)
set -euo pipefail

API_DIR="${API_DIR:-$(cd "$(dirname "$0")" && pwd)}"
cd "$API_DIR"
PY="${PYTHON:-venv/bin/python}"
command -v "$PY" >/dev/null 2>&1 || PY=python3

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

check() {
    "$PY" - <<'EOF'
from sqlalchemy import text
from database import VendorSessionLocal

s = VendorSessionLocal()
q = lambda sql: s.execute(text(sql)).scalar()
try:
    for t in ("ageing_config", "equipment_expected_life", "health_scoring_config"):
        found = s.execute(text("select to_regclass(:t)"), {"t": "public." + t}).scalar()
        print("  table %-24s %s" % (t, "present" if found else "MISSING"))
    rows = s.execute(text(
        "select template_key, coalesce(template_data->>'category_type', '-') "
        "from public.org_test_templates where template_key in "
        "('power_transformer_nameplate','transformer_physical_inspection','transformer_inspection')"
    )).fetchall()
    for key, ctype in rows:
        print(f"  template {key:34} category_type={ctype}")
    print("  active workflows with no testing request (empty the Recompute All button before 43021eb):",
          q("select count(*) from public.tr_wf_instances where status='active' and testing_request_id is null"))
    print("  stored no-threshold results that are CRITICAL without a Fail verdict:",
          q("select count(*) from public.test_results "
            "where evaluation_result->>'unassessed_reason' = 'no_threshold_values' "
            "and lower(coalesce(test_data->>'overall_result','')) not in ('fail','failed')"))
finally:
    s.close()
EOF
}

log "API dir: $API_DIR  python: $PY"
log "Current state:"
check

if [ "${1:-}" = "--check" ]; then
    log "Check only - nothing changed."
    exit 0
fi

for step in alter_ageing_config.py \
            alter_health_scoring_config.py \
            alter_exempt_nameplate_inspection_templates.py; do
    log "Running $step"
    "$PY" "$step"
done

log "Running run_recompute_all_analytics.py (re-evaluates and rescores every stored result; can take a while)"
"$PY" run_recompute_all_analytics.py

log "State after:"
check
log "Done."
