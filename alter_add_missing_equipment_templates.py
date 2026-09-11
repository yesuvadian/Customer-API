"""
ALTER: Insert Test/Maintenance/Inspection coverage for the 11 equipment
types that had CategoryMaster rows but zero templates — Potential
Transformer, Isolator / Disconnector, Control & Relay Panel, Battery
Charger, Station Auxiliary Transformer, Diesel Generator Set, Digital
Communication Panel, LTAC Panel, PLCC Panel, Wave Trap, Fire Fighting
System.

Inserts, all disabled by default (is_active=False):
  1. OrgTestTemplate rows for the 33 new template_keys added to
     test_templates.py's TEST_TEMPLATES (3 per equipment type: Test,
     Maintenance, Inspection) — org_id=NULL (system/global), is_system=True.
  2. CategoryDetails rows under each equipment type's CategoryMaster —
     its own Test-type name, its own Maintenance-type name, and its own
     copies of the 6 generic Annual Audit inspection category names
     (Electrical Safety / Civil / Fire Safety / Documentation /
     Environmental / General Maintenance), matching the exact pattern
     already used by Circuit Breaker / Battery Set / Surge Arrestor.

Does NOT call seed_category_active_flags.sync_category_details_active_flags()
— that function matches CategoryDetails purely by `name`, so running it here
would also touch every OTHER equipment type's identically-named rows (e.g.
every equipment's own "Electrical Safety" row) via its "re-enable everything
not explicitly disabled" branch. Each row this script inserts is created
with is_active=False directly instead, which is safe and self-contained.

Safe to run multiple times (checks for existing rows by name/key first).

Usage:
    python alter_add_missing_equipment_templates.py
"""

from __future__ import annotations

import uuid

from database import SessionLocal
from models import CategoryDetails, CategoryMaster, OrgTestTemplate
from test_templates import TEST_TEMPLATES

# equipment_type name (must match CategoryMaster.name exactly) -> template key prefix
EQUIPMENT_TYPES = {
    "Potential Transformer":          "potential_transformer",
    "Isolator / Disconnector":        "isolator",
    "Control & Relay Panel":          "cr_panel",
    "Battery Charger":                "battery_charger",
    "Station Auxiliary Transformer":  "station_aux_transformer",
    "Diesel Generator Set":           "dg_set",
    "Digital Communication Panel":    "comm_panel",
    "LTAC Panel":                     "ltac_panel",
    "PLCC Panel":                     "plcc_panel",
    "Wave Trap":                      "wave_trap",
    "Fire Fighting System":           "fire_fighting",
}

INSPECTION_CATEGORIES = [
    "Electrical Safety", "Civil", "Fire Safety",
    "Documentation", "Environmental", "General Maintenance",
]


def _upsert_template(db, template_key: str) -> bool:
    """Idempotently insert the OrgTestTemplate row for template_key. Returns True if inserted."""
    template_data = TEST_TEMPLATES.get(template_key)
    if not template_data:
        print(f"[WARN] {template_key!r} not found in TEST_TEMPLATES — skipping")
        return False

    existing = db.query(OrgTestTemplate).filter(
        OrgTestTemplate.org_id.is_(None),
        OrgTestTemplate.template_key == template_key,
    ).first()
    if existing:
        existing.template_data = template_data
        existing.is_system = True
        return False

    db.add(OrgTestTemplate(
        id=uuid.uuid4(),
        org_id=None,
        template_key=template_key,
        template_data=template_data,
        is_system=True,
    ))
    return True


def _upsert_category_detail(db, category_master_id: int, name: str, category_type: str) -> bool:
    """Idempotently insert a disabled CategoryDetails row. Returns True if inserted."""
    existing = db.query(CategoryDetails).filter_by(
        category_master_id=category_master_id, name=name,
    ).first()
    if existing:
        # Leave an already-active row alone (e.g. the 6 generic inspection
        # names may already exist and be active for a type touched by an
        # earlier run) — only fill in category_type if it was blank.
        if not existing.category_type:
            existing.category_type = category_type
        return False

    db.add(CategoryDetails(
        category_master_id=category_master_id,
        name=name,
        category_type=category_type,
        is_active=False,
    ))
    return True


def run(db) -> None:
    templates_inserted = 0
    details_inserted = 0

    for equip_name, prefix in EQUIPMENT_TYPES.items():
        master = db.query(CategoryMaster).filter_by(name=equip_name).first()
        if not master:
            print(f"[WARN] CategoryMaster {equip_name!r} not found — skipping")
            continue

        test_key        = f"{prefix}_test"
        maintenance_key = f"{prefix}_maintenance"
        inspection_key  = f"{prefix}_inspection"

        for key in (test_key, maintenance_key, inspection_key):
            if _upsert_template(db, key):
                templates_inserted += 1

        test_name = TEST_TEMPLATES[test_key]["name"]
        maint_name = TEST_TEMPLATES[maintenance_key]["name"]

        if _upsert_category_detail(db, master.id, test_name, "test"):
            details_inserted += 1
        if _upsert_category_detail(db, master.id, maint_name, "maintenance"):
            details_inserted += 1
        for cat in INSPECTION_CATEGORIES:
            if _upsert_category_detail(db, master.id, cat, "inspection"):
                details_inserted += 1

        db.flush()
        print(f"[OK] {equip_name}: templates ready, CategoryDetails ready (all disabled)")

    db.commit()
    print(f"\n[DONE] {templates_inserted} OrgTestTemplate rows inserted, "
          f"{details_inserted} CategoryDetails rows inserted (0 of either on a rerun).")
    print("All new rows are is_active=False — enable per equipment type once its "
          "form content is reviewed against real site procedures.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db)
    finally:
        db.close()
