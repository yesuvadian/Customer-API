#!/usr/bin/env python3
"""
One-time setup: create the equipment_expected_life and ageing_config tables
(via the EquipmentExpectedLife / AgeingConfig models in models.py) and seed
them with exactly the values the AI Graph Dashboard used as hardcoded
constants in routers/ai_graph.py:

  - _TYPE_LIFE / _DEFAULT_LIFE            -> equipment_expected_life rows +
                                             ageing_config.default_expected_life_years
  - /grouped life-stage cutoffs 0.5/0.8/1.0 -> ageing_config.life_stage_*
  - /ageing radar benchmark polygon        -> ageing_config.benchmark_*

Like-for-like seed, not a new classification — afterward the values are
editable from the Threshold Config page ("Expected Life" / "Ageing
Settings" tabs). Re-running this script is safe: it only inserts
expected-life rows whose match_pattern doesn't already exist, and only
inserts the ageing_config row if the table is empty (never overwrites an
admin's edits).

Usage:
    python alter_ageing_config.py
"""
from database import VendorSessionLocal
from models import AgeingConfig, Base, EquipmentExpectedLife

# Exactly routers/ai_graph.py's old _TYPE_LIFE, in its original (first-match
# wins) iteration order.
DEFAULT_EXPECTED_LIFE = [
    ("power transformer",     30),
    ("current transformer",   25),
    ("potential transformer", 25),
    ("circuit breaker",       25),
    ("capacitor",             20),
    ("isolator",              30),
]

DEFAULT_AGEING_CONFIG = dict(
    default_expected_life_years=30,
    life_stage_mid=0.5,
    life_stage_near_end=0.8,
    life_stage_overdue=1.0,
    benchmark_aging_rate=30,
    benchmark_volatility=25,
    benchmark_life_left_risk=35,
    benchmark_thermal_stress=25,
    benchmark_load_factor=30,
)


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[EquipmentExpectedLife.__table__, AgeingConfig.__table__],
    )
    print("Ensured equipment_expected_life and ageing_config tables exist.")

    db = VendorSessionLocal()
    try:
        inserted, skipped = 0, 0
        # Seed only a brand-new (empty) table: re-seeding per pattern brought
        # back rules an admin had deleted or renamed.
        already_seeded = db.query(EquipmentExpectedLife.id).first() is not None
        for idx, (pattern, years) in enumerate(DEFAULT_EXPECTED_LIFE):
            if already_seeded:
                skipped += 1
                continue
            db.add(EquipmentExpectedLife(
                match_pattern=pattern,
                expected_life_years=years,
                sort_order=(idx + 1) * 10,
                notes="Seeded from the previously hardcoded _TYPE_LIFE in routers/ai_graph.py.",
            ))
            inserted += 1

        cfg_inserted = False
        if db.query(AgeingConfig).first() is None:
            db.add(AgeingConfig(
                **DEFAULT_AGEING_CONFIG,
                notes="Seeded from the previously hardcoded routers/ai_graph.py constants.",
            ))
            cfg_inserted = True

        db.commit()
        print(f"Inserted {inserted} expected-life row(s), skipped {skipped} already present.")
        print("Inserted ageing_config row." if cfg_inserted
              else "ageing_config row already present, left unchanged.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
