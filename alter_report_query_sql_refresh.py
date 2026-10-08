"""
ALTER: push the current report SQL from seed.py into report_query_keys.

Report queries run from report_query_keys.sql_template in the database, not
from seed.py, so a SQL fix in seed_report_query_keys() does nothing on an
existing dev/prod database until it is re-upserted. This runs ONLY that
upsert (no users, roles, modules or sample data — unlike `python seed.py`).

Fixes carried by this refresh include:
  - equipment_performance_report: plain Run (no equipment chosen) lists
    every equipment with tests, adds UEIC
  - failure_resolution_report: outcome read from the latest recommendation
  - transformer_repair_status_report: due / actual / delay days from stages
  - taqc_compliance_report: oldest_open_days (oldest OPEN observation)
  - calibration_compliance_report / upcoming_due_tests_report: fall back to
    the equipment's department
  - network_health_summary_report / equipment_failure_performance_report:
    case-insensitive risk_level buckets
  - missed_schedules_report: untitled schedules get
    "<test type> — <equipment type>"

report_query_keys.sql_template is not editable from the app, so overwriting
it from seed.py loses nothing. Safe to run multiple times.

Usage (on the dev or prod API server, from the API folder, so its .env
points at that environment's database):
    python alter_report_query_sql_refresh.py --check   # list what would change
    python alter_report_query_sql_refresh.py           # apply
"""

from __future__ import annotations

import sys

from database import SessionLocal
from models import ReportQueryKey
from seed import seed_report_query_keys


def _snapshot(db) -> dict:
    return {
        k.key: ((k.sql_template or "").strip(), k.org_alias, k.label, k.group_name)
        for k in db.query(ReportQueryKey).all()
    }


def main() -> None:
    check = "--check" in sys.argv
    db = SessionLocal()
    try:
        before = _snapshot(db)
        if check:
            # Run the upsert inside the transaction, compare, then roll back.
            db.commit = lambda: None  # type: ignore[method-assign]
        seed_report_query_keys(db)
        after = _snapshot(db)

        added = sorted(set(after) - set(before))
        changed = sorted(k for k in after if k in before and after[k] != before[k])
        for k in added:
            print(f"  [NEW]     {k}")
        for k in changed:
            what = "SQL" if after[k][0] != before[k][0] else "label/group/alias"
            print(f"  [CHANGED] {k} ({what})")

        if check:
            db.rollback()
            print(f"\n--check: {len(added)} new, {len(changed)} changed. Nothing written.")
        else:
            print(f"\n{len(added)} report query key(s) added, {len(changed)} updated.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
