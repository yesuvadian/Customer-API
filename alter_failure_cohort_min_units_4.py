#!/usr/bin/env python3
"""
One-time backfill: raise the system-wide default failure_cohort_threshold_configs
row's min_cohort_units from 3 to 4, aligning it with
EquipmentService.compute_failure_cohort_stats()'s own >=4-unit floor for
within-cohort outlier detection (see equipment_service.py's comment above
the is_outlier/outlier_z_score computation).

Before this, a 3-unit cohort could clear min_cohort_units and be surfaced
(even flagged is_design_problem_candidate) while every unit inside it was
left is_outlier=False purely because 3 units is below the outlier
detector's own >=4 floor -- a cohort-level flag with no per-unit
explanation behind it. Raising the floor to 4 closes that gap: any cohort
that clears min_cohort_units now also clears the outlier detector's floor.

Only touches the system-wide default row (organization_id IS NULL), and
only if it is still at the old default (3) -- an org that explicitly
overrode min_cohort_units (to 3 or any other value) made that choice on
purpose and is left untouched here, same as this table's original seed
script does for admin edits.

Re-running this script is safe: once the default row is at 4 (or was
never 3), it's a no-op.

Usage:
    python alter_failure_cohort_min_units_4.py
"""
from database import VendorSessionLocal
from models import FailureCohortThresholdConfig


OLD_DEFAULT = 3
NEW_DEFAULT = 4


def main():
    db = VendorSessionLocal()
    try:
        default_row = (
            db.query(FailureCohortThresholdConfig)
            .filter(FailureCohortThresholdConfig.organization_id.is_(None))
            .first()
        )
        if default_row is None:
            print(
                "No system-wide default row exists yet -- nothing to backfill. "
                "It will be seeded at the new default (4) next time "
                "alter_failure_cohort_threshold_config.py runs."
            )
            return

        if default_row.min_cohort_units != OLD_DEFAULT:
            print(
                f"Default row's min_cohort_units is already {default_row.min_cohort_units} "
                f"(not the old default {OLD_DEFAULT}) -- left untouched."
            )
            return

        default_row.min_cohort_units = NEW_DEFAULT
        db.commit()
        print(
            f"Updated system-wide default min_cohort_units: "
            f"{OLD_DEFAULT} -> {NEW_DEFAULT}."
        )

        org_overrides = (
            db.query(FailureCohortThresholdConfig)
            .filter(
                FailureCohortThresholdConfig.organization_id.isnot(None),
                FailureCohortThresholdConfig.min_cohort_units == OLD_DEFAULT,
            )
            .all()
        )
        if org_overrides:
            org_ids = ", ".join(str(r.organization_id) for r in org_overrides)
            print(
                f"NOTE: {len(org_overrides)} org-specific override row(s) still have "
                f"min_cohort_units={OLD_DEFAULT} and were left untouched (org id(s): "
                f"{org_ids}). Review manually via the Threshold Config screen if you "
                f"want those orgs aligned to {NEW_DEFAULT} too."
            )
    finally:
        db.close()


if __name__ == "__main__":
    main()
