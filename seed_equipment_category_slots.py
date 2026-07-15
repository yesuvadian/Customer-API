"""
seed_equipment_category_slots.py

Ensures every real equipment master has a CategoryDetails placeholder row
for each of the four template categories: test, maintenance, inspection, repair.

These placeholder rows make all four categories available in the
"New Template" dialog regardless of whether any named test types exist.

Safe to run multiple times (idempotent — skips rows that already exist).

Usage:
    python seed_equipment_category_slots.py
"""

from __future__ import annotations
from sqlalchemy.orm import Session

# Equipment masters that represent physical assets (excludes lifecycle /
# audit / generic pseudo-masters that are not real equipment types).
EQUIPMENT_MASTERS = [
    "Power Transformer",
    "Circuit Breaker",
    "Protection Relay",
    "Electronic Tri-vector Meter",
    "Surge Arrestor",
    "Battery Set",
    "Current Transformer",
    "Capacitor Voltage Transformer",
    "Potential Transformer",
    "Station Auxiliary Transformer",
    "Diesel Generator Set",
    "Digital Communication Panel",
    "LTAC Panel",
    "PLCC Panel",
    "Wave Trap",
    "Control & Relay Panel",
    "Fire Fighting System",
    "Battery Charger",
    "Isolator / Disconnector",
]

REQUIRED_CATEGORY_TYPES = ["test", "maintenance", "inspection", "repair"]

CATEGORY_LABELS = {
    "test":        "Test",
    "maintenance": "Maintenance",
    "inspection":  "Inspection",
    "repair":      "Repair",
}


def seed_equipment_category_slots(session: Session) -> None:
    """
    Insert missing (equipment_master, category_type) placeholder rows.
    Skips any combination that already exists.
    """
    from models import CategoryMaster, CategoryDetails

    added = 0
    skipped = 0

    for master_name in EQUIPMENT_MASTERS:
        master = session.query(CategoryMaster).filter_by(name=master_name).first()
        if not master:
            print(f"  [SKIP] CategoryMaster not found: {master_name!r}")
            continue

        for ct in REQUIRED_CATEGORY_TYPES:
            existing = (
                session.query(CategoryDetails)
                .filter_by(category_master_id=master.id, category_type=ct)
                .first()
            )
            if existing:
                skipped += 1
                continue

            session.add(CategoryDetails(
                name=CATEGORY_LABELS[ct],
                category_master_id=master.id,
                category_type=ct,
                is_active=True,
            ))
            added += 1
            print(f"  [ADD]  {master_name} → {ct}")

    session.commit()
    print(f"[OK] seed_equipment_category_slots: {added} added, {skipped} already existed.")


if __name__ == "__main__":
    from database import VendorSessionLocal
    db = VendorSessionLocal()
    try:
        seed_equipment_category_slots(db)
    finally:
        db.close()
