#!/usr/bin/env python3
"""
One-time setup: create the dqi_rule_configs table (via the DqiRuleConfig
model in models.py) and seed it with the 7 checks that used to be hardcoded
directly in routers/dashboard_kpi.py's DQI (Data Quality Index) computation
— 5 required Equipment nameplate fields, plus "has test history" and "not
overdue for a test". Every value here is exactly what was hardcoded before,
just now toggleable afterward from Threshold Config's "Data Quality" tab
without a code change.

Unlike the sibling alter_*.py scripts for this module, this one seeds fixed,
code-bound keys, not an open list an admin can add to — see DqiRuleConfig's
own docstring in models.py for why.

Re-running this script is safe: it only inserts rows that don't already
exist for a given key, so manual edits already made (e.g. an admin having
turned a check off) are never overwritten.

Usage:
    python alter_dqi_rule_config.py
"""
from sqlalchemy import text
from database import VendorSessionLocal
from models import Base, DqiRuleConfig

# Exactly the 5 Equipment nameplate fields dashboard_kpi.py's DQI nameplate
# check used to hardcode, plus the two other DQI checks it also hardcoded.
DEFAULT_RULES = [
    ("manufacturer", "Manufacturer"),
    ("factory_serial_number", "Serial Number"),
    ("year_of_manufacture", "Year of Manufacture"),
    ("voltage_class", "Voltage Class"),
    ("commissioned_date", "Commissioned Date"),
    ("test_history", "Has Test History"),
    ("overdue_test", "Not Overdue for a Test"),
]


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[DqiRuleConfig.__table__],
    )
    print("Ensured dqi_rule_configs table exists.")

    db = VendorSessionLocal()
    try:
        # create_all only creates a MISSING table — it never alters an
        # existing one, so equipment_type_ids (added after this table was
        # first created in some environments) needs its own idempotent
        # ADD COLUMN here rather than relying on the model definition alone.
        db.execute(text(
            "ALTER TABLE public.dqi_rule_configs "
            "ADD COLUMN IF NOT EXISTS equipment_type_ids INTEGER[]"
        ))
        db.commit()
        print("Ensured dqi_rule_configs.equipment_type_ids column exists.")

        inserted, skipped = 0, 0
        for key, label in DEFAULT_RULES:
            exists = (
                db.query(DqiRuleConfig)
                .filter(DqiRuleConfig.key == key)
                .first()
            )
            if exists:
                skipped += 1
                continue
            db.add(DqiRuleConfig(
                key=key,
                label=label,
                notes="Seeded from the previously hardcoded DQI check list.",
            ))
            inserted += 1

        db.commit()
        print(f"Inserted {inserted} rule row(s), skipped {skipped} already present.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
