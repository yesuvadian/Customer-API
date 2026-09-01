#!/usr/bin/env python3
"""
One-time setup: create the equipment_condition_band_thresholds table (via
the EquipmentConditionBandThreshold model in models.py) and seed it with
the same 5 bands the AI Graph Dashboard already used as a hardcoded
constant (_condition_from_score's 88/75/65/50 cutoffs in
routers/ai_graph.py).

This is a separate, 5-tier scale (Excellent/Good/Fair/Poor/Critical) from
EquipmentHealthBandThreshold's 4-tier one (Low/Medium/High/Critical) — not
a duplicate of it. Both classify the same composite health score, just at
different granularity for different dashboards.

Like-for-like seed, not a new classification — every value here is exactly
what was hardcoded before, just now editable afterward directly in the
equipment_condition_band_thresholds table. Re-running this script is safe:
it only inserts rows that don't already exist for a given label.

Usage:
    python alter_equipment_condition_band_threshold.py
"""
from database import VendorSessionLocal
from models import Base, EquipmentConditionBandThreshold

# Exactly routers/ai_graph.py's old _condition_from_score cutoffs.
DEFAULT_BANDS = [
    ("Excellent", 88),
    ("Good",      75),
    ("Fair",      65),
    ("Poor",      50),
    ("Critical",   0),
]


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[EquipmentConditionBandThreshold.__table__],
    )
    print("Ensured equipment_condition_band_thresholds table exists.")

    db = VendorSessionLocal()
    try:
        inserted, skipped = 0, 0
        for label, threshold in DEFAULT_BANDS:
            exists = (
                db.query(EquipmentConditionBandThreshold)
                .filter(EquipmentConditionBandThreshold.label == label)
                .first()
            )
            if exists:
                skipped += 1
                continue
            db.add(EquipmentConditionBandThreshold(
                label=label,
                threshold=threshold,
                notes="Seeded from the previously hardcoded _condition_from_score cutoffs.",
            ))
            inserted += 1

        db.commit()
        print(f"Inserted {inserted} band row(s), skipped {skipped} already present.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
