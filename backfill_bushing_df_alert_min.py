#!/usr/bin/env python3
"""
One-time fix: remove the erroneous alert_min floor from every OrgTestTemplate
row's bushing %D.F thresholds (400/220/66/33/11 kV).

OrgTestTemplate rows are seeded once from test_templates.py by
provision_global_defaults() and never auto-synced afterward - editing
test_templates.py alone does not fix already-seeded rows in the DB, which
is what live evaluation actually reads (see EvaluationService.get_template_data,
DB-first resolution). This script applies the same fix directly to every
stored OrgTestTemplate row, org-specific or global.

Root cause: alert_min was set equal to normal_max on an ascending-is-bad
parameter (lower %D.F is better), so it fired before normal_max/alert_max/
critical_above were ever checked - flagging genuinely good low readings
as ALERT (e.g. 0.22 against a 0.5 normal_max).

Usage:
    python fix_bushing_df_alert_min.py --dry-run   # report only, no writes
    python fix_bushing_df_alert_min.py              # apply, then run
                                                      # run_recompute_all_analytics.py
"""
import argparse

from database import VendorSessionLocal
from models import OrgTestTemplate
from sqlalchemy.orm.attributes import flag_modified

_BUSHING_PREFIX = "bushing_"
_BUSHING_SUFFIX = "_test_results"
_COL_KEY = "df_corrected_20c"


def run_fix(dry_run: bool):
    db = VendorSessionLocal()
    try:
        rows = db.query(OrgTestTemplate).all()
        changed = []

        for row in rows:
            td = row.template_data or {}
            row_changed = False
            for section in td.get("sections", []):
                for field in section.get("fields", []):
                    fk = field.get("key", "")
                    if not (fk.startswith(_BUSHING_PREFIX) and fk.endswith(_BUSHING_SUFFIX)):
                        continue
                    cev = (field.get("table_evaluation") or {}).get("column_evaluations", {}).get(_COL_KEY)
                    if not cev:
                        continue
                    nm_max = cev.get("normal_max")
                    al_min = cev.get("alert_min")
                    if nm_max is not None and al_min is not None and al_min == nm_max:
                        cev["alert_min"] = None
                        row_changed = True

            if row_changed:
                changed.append((row.template_key, row.org_id))
                if not dry_run:
                    flag_modified(row, "template_data")

        print(f"{'[DRY RUN] ' if dry_run else ''}Rows to fix: {len(changed)} (of {len(rows)} total)")
        for template_key, org_id in changed:
            print(f"  {template_key} | org_id={org_id}")

        if not dry_run:
            db.commit()
            print("Fix committed.")
            print("Now run: python run_recompute_all_analytics.py")
        else:
            db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_fix(dry_run=args.dry_run)
