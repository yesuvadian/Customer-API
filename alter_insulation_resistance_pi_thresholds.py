"""
Alter: Insulation Resistance (IR) & Polarization Index — auto-evaluate PI
=============================================================================
The ir_readings table's pi_value column (Polarisation Index, computed
client-side as ir_value_10min / ir_value_1min) previously had no automated
acceptance-threshold evaluation - only the tester's own manually-picked
row_result (Pass/Fail) dropdown drove the score, so a PI of 0.8 (IEEE 43:
"Dangerous") could be waved through as "Pass" with nothing catching it.

This patches every already-provisioned insulation_resistance_test
OrgTestTemplate row with a table_evaluation.column_evaluations block on
pi_value, using IEEE 43 bands:
    < 1.0        -> CRITICAL (Dangerous)
    1.0 - 2.0    -> ALERT    (Questionable / Fair)
    >= 2.0       -> NORMAL   (Good)
This runs independently of, and in addition to, the tester's row_result
pick — same coexistence pattern already used by sfra_routine's
correlation_analysis table (numeric column_evaluations + a separate
dropdown column_evaluation on the same table).

Idempotent - safe to re-run; reports "no change" once applied.

Usage:
    python alter_insulation_resistance_pi_thresholds.py --dry-run   # report only
    python alter_insulation_resistance_pi_thresholds.py             # apply
"""
import argparse
import copy

from database import VendorSessionLocal
from models import OrgTestTemplate
from sqlalchemy.orm.attributes import flag_modified

TEMPLATE_KEY = "insulation_resistance_test"

PI_EVALUATION = {
    "critical_below": 1.0,
    "alert_min": 2.0,
    "alert_max": None,
    "critical_above": None,
    "normal_min": None,
    "normal_max": None,
}

REMEDIAL_TEXT = (
    "Polarisation Index below 2.0 (IEEE 43) indicates questionable-to-dangerous "
    "insulation condition — investigate moisture/contamination; a PI below 1.0 "
    "means the winding should not be energised until dried out or otherwise "
    "remediated."
)


def apply_fix(template_data: dict) -> bool:
    """Mutate template_data in place. Returns True if anything changed."""
    changed = False
    for section in template_data.get("sections", []):
        for field in section.get("fields", []):
            if field.get("key") != "ir_readings" or field.get("type") != "table":
                continue

            ev = field.setdefault("table_evaluation", {})
            if not ev.get("enabled"):
                ev["enabled"] = True
                changed = True

            col_evals = ev.setdefault("column_evaluations", {})
            if col_evals.get("pi_value") != PI_EVALUATION:
                col_evals["pi_value"] = copy.deepcopy(PI_EVALUATION)
                changed = True

            if ev.get("remedial_action_text") != REMEDIAL_TEXT:
                ev["remedial_action_text"] = REMEDIAL_TEXT
                changed = True

    return changed


def run_fix(dry_run: bool):
    db = VendorSessionLocal()
    try:
        rows = (
            db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.template_key == TEMPLATE_KEY)
            .all()
        )
        changed_rows = []

        for row in rows:
            td = row.template_data or {}
            if apply_fix(td):
                changed_rows.append((row.id, row.org_id))
                if not dry_run:
                    flag_modified(row, "template_data")

        print(f"{'[DRY RUN] ' if dry_run else ''}Rows to fix: {len(changed_rows)} (of {len(rows)} total for {TEMPLATE_KEY})")
        for row_id, org_id in changed_rows:
            print(f"  id={row_id} | org_id={org_id}")

        if not dry_run:
            db.commit()
            print("Fix committed.")
        else:
            db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_fix(dry_run=args.dry_run)
