#!/usr/bin/env python3
"""
One-time setup: create the parameter_condition_scores table (via the
ParameterConditionScore model in models.py) and seed it with the same 3
values the app already used as a hardcoded constant (_SCORE in
services/analytics_engine.py), completing the same §12.1 configurability
fix as alter_equipment_health_band_threshold.py — that script covers the
score-to-band OUTPUT step (EquipmentHealthBandThreshold); this one covers
the condition-to-point-value INPUT step that feeds the composite health
score in the first place.

Like-for-like seed, not a new set of weights — every value here is exactly
what was hardcoded before, just now editable afterward directly in the
parameter_condition_scores table. Re-running this script is safe: it only
inserts rows that don't already exist for a given condition, so manual
edits already made are never overwritten.

Usage:
    python alter_parameter_condition_score.py
"""
from database import VendorSessionLocal
from models import Base, ParameterConditionScore

# Exactly services/analytics_engine.py's old _SCORE constant.
DEFAULT_SCORES = [
    ("Good", 100.0),
    ("Fair",  50.0),
    ("Poor", -100.0),
]


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[ParameterConditionScore.__table__],
    )
    print("Ensured parameter_condition_scores table exists.")

    db = VendorSessionLocal()
    try:
        inserted, skipped = 0, 0
        for condition, score in DEFAULT_SCORES:
            exists = (
                db.query(ParameterConditionScore)
                .filter(ParameterConditionScore.condition == condition)
                .first()
            )
            if exists:
                skipped += 1
                continue
            db.add(ParameterConditionScore(
                condition=condition,
                score=score,
                notes="Seeded from the previously hardcoded _SCORE constant.",
            ))
            inserted += 1

        db.commit()
        print(f"Inserted {inserted} score row(s), skipped {skipped} already present.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
