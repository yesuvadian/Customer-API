#!/usr/bin/env python3
"""
One-time setup: create the test_status_conditions table (via the
TestStatusCondition model in models.py) and seed it with the same mapping
the app already used as a hardcoded constant (_CONDITION in
services/analytics_engine.py) — the third and last piece of the §12.1
configurability chain, alongside alter_equipment_health_band_threshold.py
(score -> band) and alter_parameter_condition_score.py (condition ->
point value). This one is the middle step: status -> condition_label.

Like-for-like seed, not a new mapping — every value here is exactly what
was hardcoded before, just now editable afterward directly in the
test_status_conditions table. Re-running this script is safe: it only
inserts rows that don't already exist for a given status, so manual edits
already made are never overwritten.

Usage:
    python alter_test_status_condition.py
"""
from database import VendorSessionLocal
from models import Base, TestStatusCondition

# Exactly services/analytics_engine.py's old _CONDITION constant.
DEFAULT_CONDITIONS = [
    ("NORMAL",   "Good"),
    ("ALERT",    "Fair"),
    ("CRITICAL", "Poor"),
]


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[TestStatusCondition.__table__],
    )
    print("Ensured test_status_conditions table exists.")

    db = VendorSessionLocal()
    try:
        inserted, skipped = 0, 0
        for status, condition_label in DEFAULT_CONDITIONS:
            exists = (
                db.query(TestStatusCondition)
                .filter(TestStatusCondition.status == status)
                .first()
            )
            if exists:
                skipped += 1
                continue
            db.add(TestStatusCondition(
                status=status,
                condition_label=condition_label,
                notes="Seeded from the previously hardcoded _CONDITION constant.",
            ))
            inserted += 1

        db.commit()
        print(f"Inserted {inserted} status row(s), skipped {skipped} already present.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
