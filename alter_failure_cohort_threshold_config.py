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
from sqlalchemy import text
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
        # create_all only creates a MISSING table -- it never alters an
        # existing one, so outlier_z_score (added after this table's first
        # release, for within-cohort outlier detection) needs its own
        # idempotent ADD COLUMN. The DEFAULT clause backfills any row that
        # already exists (e.g. the seeded default row below, from before
        # this column existed) in the same statement.
        db.execute(text(
            "ALTER TABLE public.failure_cohort_threshold_configs "
            "ADD COLUMN IF NOT EXISTS outlier_z_score NUMERIC(4,2) NOT NULL DEFAULT 3.0"
        ))
        db.commit()
        print("Ensured failure_cohort_threshold_configs.outlier_z_score column exists.")

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
