#!/usr/bin/env python3
"""
One-time setup: move the remaining analytics / SLA / scheduling /
calibration-interval / failure-cohort-display settings from .env into the
database so they're editable in Threshold Config.

  1. failure_cohort_threshold_configs gets 3 new columns
     (dashboard_limit, trend_years, trend_max_series) - was
     FAILURE_COHORT_DASHBOARD_LIMIT / _TREND_YEARS / _TREND_MAX_SERIES.
  2. New table analytics_settings_configs (models.AnalyticsSettingsConfig)
     for ANALYTICS_* (6), REVIEW_SLA_HOURS_* (2), SCHEDULE_ADVANCE_DAYS,
     CALIBRATION_INTERVAL_* (7), NOTIF_* (4), TR_PAGE_SIZE,
     DASHBOARD_PANEL_PAGE_SIZE and the login/OTP/password policy (7) - see
     services/tunable_settings.py.

Both system-wide default rows (organization_id NULL) are seeded from the
current .env values, so behavior is unchanged until an admin edits a value.
Re-running is safe: existing values (an admin's edits) are never
overwritten - only NULL columns are filled.

Usage:
    python alter_tunable_settings.py
"""
from sqlalchemy import text

import config as _config
from database import VendorSessionLocal
from models import AnalyticsSettingsConfig, Base, FailureCohortThresholdConfig
from services.tunable_settings import FIELDS, env_defaults

COHORT_ENV = {
    "dashboard_limit": "FAILURE_COHORT_DASHBOARD_LIMIT",
    "trend_years": "FAILURE_COHORT_TREND_YEARS",
    "trend_max_series": "FAILURE_COHORT_TREND_MAX_SERIES",
}


def main():
    db = VendorSessionLocal()
    try:
        # 1. Failure cohort display columns
        for col in COHORT_ENV:
            db.execute(text(
                "ALTER TABLE public.failure_cohort_threshold_configs "
                f"ADD COLUMN IF NOT EXISTS {col} INTEGER"
            ))
        db.commit()
        print("Ensured failure_cohort_threshold_configs display columns exist.")

        cohort_default = (
            db.query(FailureCohortThresholdConfig)
            .filter(FailureCohortThresholdConfig.organization_id.is_(None))
            .first()
        )
        if cohort_default is None:
            print("[WARN] No failure-cohort default row - run "
                  "alter_failure_cohort_threshold_config.py first, then re-run this.")
        else:
            filled = []
            for col, const in COHORT_ENV.items():
                if getattr(cohort_default, col) is None:
                    setattr(cohort_default, col, int(getattr(_config, const)))
                    filled.append(f"{col}={getattr(cohort_default, col)}")
            db.commit()
            print("Failure-cohort default: " + (", ".join(filled) or "already set, left untouched"))

        # 2. analytics_settings_configs
        Base.metadata.create_all(
            bind=db.get_bind(), tables=[AnalyticsSettingsConfig.__table__]
        )
        print("Ensured analytics_settings_configs table exists.")
        # create_all never alters an existing table - add any setting column
        # introduced after it was first created (type taken from the model).
        dialect = db.get_bind().dialect
        for key in FIELDS:
            coltype = AnalyticsSettingsConfig.__table__.c[key].type.compile(dialect=dialect)
            db.execute(text(
                "ALTER TABLE public.analytics_settings_configs "
                f"ADD COLUMN IF NOT EXISTS {key} {coltype}"
            ))
        db.commit()
        print(f"Ensured all {len(FIELDS)} setting columns exist.")

        default = (
            db.query(AnalyticsSettingsConfig)
            .filter(AnalyticsSettingsConfig.organization_id.is_(None))
            .first()
        )
        if default is None:
            default = AnalyticsSettingsConfig(organization_id=None)
            db.add(default)
        filled = []
        for key, val in env_defaults().items():
            if getattr(default, key) is None and val is not None:
                setattr(default, key, val)
                filled.append(key)
        db.commit()
        print(f"Analytics settings default: seeded {len(filled)} of {len(FIELDS)} "
              f"values from .env" + ("" if filled else " (all already set, left untouched)"))
    finally:
        db.close()


if __name__ == "__main__":
    main()
