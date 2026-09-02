#!/usr/bin/env python3
"""
One-time setup: create the equipment_health_band_thresholds table (via the
EquipmentHealthBandThreshold model in models.py) and seed it with the same
4 bands the app already used as a hardcoded constant (_RISK_BANDS in
services/analytics_engine.py), per KPTCL spec §12.1's explicit requirement
that EHS band thresholds be admin-configurable without a code change.

This is a like-for-like seed, not a new classification — every value here
is exactly what was hardcoded before, just now editable afterward directly
in the equipment_health_band_thresholds table (an admin CRUD UI for it is a
follow-up, not part of this script). Re-running this script is safe: it
only inserts rows that don't already exist for a given label, so manual
edits already made are never overwritten.

Usage:
    python alter_equipment_health_band_threshold.py
"""
from database import VendorSessionLocal
from models import Base, EquipmentHealthBandThreshold

# Exactly services/analytics_engine.py's old _RISK_BANDS constant.
DEFAULT_BANDS = [
    ("Low",      80),
    ("Medium",   50),
    ("High",     25),
    ("Critical",  0),
]


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[EquipmentHealthBandThreshold.__table__],
    )
    print("Ensured equipment_health_band_thresholds table exists.")

    db = VendorSessionLocal()
    try:
        inserted, skipped = 0, 0
        for label, threshold in DEFAULT_BANDS:
            exists = (
                db.query(EquipmentHealthBandThreshold)
                .filter(EquipmentHealthBandThreshold.label == label)
                .first()
            )
            if exists:
                skipped += 1
                continue
            db.add(EquipmentHealthBandThreshold(
                label=label,
                threshold=threshold,
                notes="Seeded from the previously hardcoded _RISK_BANDS constant.",
            ))
            inserted += 1

        db.commit()
        print(f"Inserted {inserted} band row(s), skipped {skipped} already present.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
