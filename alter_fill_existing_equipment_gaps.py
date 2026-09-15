"""
ALTER: Fill Test/Maintenance/Inspection gaps found on equipment types that
already had SOME coverage, discovered by auditing live CategoryDetails rows
against test_templates.py's TEST_TYPE_TO_TEMPLATE map.

Two different kinds of gap, handled differently:

  1. Filling in an already-ACTIVE, already-trusted feature — inserted as
     is_active=True, no review gate needed:
       - Protection Relay / Electronic Tri-vector Meter / Surge Arrestor /
         Battery Set: missing Civil / Fire Safety / Environmental Inspection
         CategoryDetails rows (they already have some of the 6 generic
         categories active; this just completes the set, same shared
         transformer_inspection template every equipment type already uses).
     (Power Transformer's orphaned "Winding Tan-Delta & Capacitance Test"
     CategoryDetails row already exists and is active in the DB — that gap
     was purely a missing TEST_TYPE_TO_TEMPLATE alias, fixed in
     test_templates.py directly; nothing to insert here.)

  2. Genuinely new content for equipment types that had zero Maintenance
     and zero Inspection at all — inserted disabled (is_active=False), same
     as the 11 brand-new equipment types in
     alter_add_missing_equipment_templates.py:
       - Current Transformer: new current_transformer_maintenance template
         + its own Maintenance CategoryDetails row + all 6 Inspection
         category rows (it had none).
       - Capacitor Voltage Transformer: new cvt_maintenance template + same.

Safe to run multiple times (checks for existing rows by name/key first).

Usage:
    python alter_fill_existing_equipment_gaps.py
"""

from __future__ import annotations

import uuid

from database import SessionLocal
from models import CategoryDetails, CategoryMaster, OrgTestTemplate
from test_templates import TEST_TEMPLATES

INSPECTION_CATEGORIES = [
    "Electrical Safety", "Civil", "Fire Safety",
    "Documentation", "Environmental", "General Maintenance",
]

# equipment_type name -> Inspection category names missing today, to add ACTIVE
COMPLETE_ACTIVE_INSPECTION = {
    "Protection Relay":             ["Civil", "Fire Safety", "Environmental"],
    "Electronic Tri-vector Meter":  ["Civil", "Fire Safety", "Environmental"],
    "Surge Arrestor":               ["Civil", "Fire Safety", "Environmental"],
    "Battery Set":                  ["Civil", "Fire Safety"],
}

# equipment_type name -> (maintenance template key, maintenance CategoryDetails name)
NEW_DISABLED_MAINTENANCE = {
    "Current Transformer":            ("current_transformer_maintenance", "Current Transformer Preventive Maintenance"),
    "Capacitor Voltage Transformer":  ("cvt_maintenance", "Capacitor Voltage Transformer Preventive Maintenance"),
}


def _get_master(db, name: str):
    m = db.query(CategoryMaster).filter_by(name=name).first()
    if not m:
        print(f"[WARN] CategoryMaster {name!r} not found — skipping")
    return m


def _upsert_category_detail(db, category_master_id: int, name: str, category_type: str, active: bool) -> tuple[CategoryDetails, bool]:
    """Returns (row, was_inserted) — the row (existing or newly created) so
    its id can be wired onto the matching OrgTestTemplate.test_type_id."""
    existing = db.query(CategoryDetails).filter_by(
        category_master_id=category_master_id, name=name,
    ).first()
    if existing:
        return existing, False
    detail = CategoryDetails(
        category_master_id=category_master_id,
        name=name,
        category_type=category_type,
        is_active=active,
    )
    db.add(detail)
    db.flush()  # assign detail.id before the caller reads it
    return detail, True


def _upsert_template(db, template_key: str, test_type_id: int | None = None) -> bool:
    """Linked to its CategoryDetails row via test_type_id — the id the
    Template Designer's category-type grouping resolves through."""
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
        if test_type_id is not None and existing.test_type_id is None:
            existing.test_type_id = test_type_id
        return False
    db.add(OrgTestTemplate(
        id=uuid.uuid4(), org_id=None, template_key=template_key,
        test_type_id=test_type_id,
        template_data=template_data, is_system=True,
    ))
    return True


def run(db) -> None:
    details_inserted = 0
    templates_inserted = 0

    print("--- Completing already-active Inspection category sets ---")
    for equip_name, missing_cats in COMPLETE_ACTIVE_INSPECTION.items():
        master = _get_master(db, equip_name)
        if not master:
            continue
        added = 0
        for cat in missing_cats:
            _, inserted = _upsert_category_detail(db, master.id, cat, "inspection", active=True)
            if inserted:
                added += 1
                details_inserted += 1
        print(f"[OK] {equip_name}: {added} Inspection categories added (active)")

    print("\n--- New disabled Maintenance + Inspection for zero-coverage equipment ---")
    for equip_name, (tpl_key, maint_name) in NEW_DISABLED_MAINTENANCE.items():
        master = _get_master(db, equip_name)
        if not master:
            continue

        # CategoryDetails row first — its id is what the Maintenance
        # template's test_type_id needs to point at.
        maint_detail, inserted = _upsert_category_detail(db, master.id, maint_name, "maintenance", active=False)
        details_inserted += inserted

        if _upsert_template(db, tpl_key, test_type_id=maint_detail.id):
            templates_inserted += 1

        added = 0
        for cat in INSPECTION_CATEGORIES:
            _, inserted = _upsert_category_detail(db, master.id, cat, "inspection", active=False)
            if inserted:
                added += 1
                details_inserted += 1
        print(f"[OK] {equip_name}: Maintenance template + CategoryDetails ready (disabled), "
              f"{added} Inspection categories added (disabled)")

    db.commit()
    print(f"\n[DONE] {templates_inserted} OrgTestTemplate rows inserted, "
          f"{details_inserted} CategoryDetails rows inserted (0 of either on a rerun).")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db)
    finally:
        db.close()
