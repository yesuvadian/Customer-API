#!/usr/bin/env python3
"""
One-time setup: create failure_cohort_threshold_configs and seed the
system-wide default row (organization_id=NULL) from the current .env
values, so existing behavior is unchanged until an org explicitly
overrides it via the Threshold Config screen.

Same "org can override, default always exists" pattern as
NotificationTemplate -- EquipmentService.compute_failure_cohort_stats()
looks up an org-specific row first, then this NULL default row, then the
.env constants as a last resort.

Re-running this script is safe: it only inserts the default row if one
doesn't already exist, so an admin's already-edited value is never
overwritten.

Usage:
    python alter_failure_cohort_threshold_config.py
"""
from database import VendorSessionLocal
from models import Base, FailureCohortThresholdConfig
import config as _config


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[FailureCohortThresholdConfig.__table__],
    )
    print("Ensured failure_cohort_threshold_configs table exists.")

    db = VendorSessionLocal()
    try:
        existing = (
            db.query(FailureCohortThresholdConfig)
            .filter(FailureCohortThresholdConfig.organization_id.is_(None))
            .first()
        )
        if existing:
            print(
                f"Default row already exists (min_failure_rate={existing.min_failure_rate}, "
                f"min_cohort_units={existing.min_cohort_units}) -- left untouched."
            )
            return

        db.add(FailureCohortThresholdConfig(
            organization_id=None,
            min_failure_rate=_config.DESIGN_PROBLEM_CANDIDATE_MIN_FAILURE_RATE,
            min_cohort_units=_config.FAILURE_COHORT_MIN_UNITS,
        ))
        db.commit()
        print(
            f"Seeded default row from .env: min_failure_rate="
            f"{_config.DESIGN_PROBLEM_CANDIDATE_MIN_FAILURE_RATE}, "
            f"min_cohort_units={_config.FAILURE_COHORT_MIN_UNITS}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
