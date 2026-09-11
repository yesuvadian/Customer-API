"""
ALTER: Insert the Partial Discharge Measurement template, shared across the
four equipment types the TNEB proposal lists it for that are actually
registered in the platform today — Power Transformer, Current Transformer,
Potential Transformer, and Capacitor Voltage Transformer. (The proposal also
lists Cables and GIS Substation, but neither has a CategoryMaster row in
this platform yet — out of scope here.)

One OrgTestTemplate row backs all four — `equipment_type` on a template is
descriptive only, not enforced at runtime; selection is entirely driven by
TEST_TYPE_TO_TEMPLATE + CategoryDetails, the same mechanism already used to
share "Routine Preventive Maintenance" across many equipment types.

Inserts, disabled by default (is_active=False):
  1. OrgTestTemplate row for "partial_discharge_test" — org_id=NULL
     (system/global), is_system=True.
  2. One CategoryDetails row "Partial Discharge Measurement" under each of
     the 4 equipment types' CategoryMaster, category_type="test".

Safe to run multiple times (checks for existing rows by name/key first).

Usage:
    python alter_add_partial_discharge_template.py
"""

from __future__ import annotations

import uuid

from database import SessionLocal
from models import CategoryDetails, CategoryMaster, OrgTestTemplate
from test_templates import TEST_TEMPLATES

TEMPLATE_KEY = "partial_discharge_test"
EQUIPMENT_TYPES = [
    "Power Transformer",
    "Current Transformer",
    "Potential Transformer",
    "Capacitor Voltage Transformer",
]


def run(db) -> None:
    template_data = TEST_TEMPLATES[TEMPLATE_KEY]
    test_type_name = template_data["name"]

    templates_inserted = 0
    details_inserted = 0

    existing_tpl = db.query(OrgTestTemplate).filter(
        OrgTestTemplate.org_id.is_(None),
        OrgTestTemplate.template_key == TEMPLATE_KEY,
    ).first()
    if existing_tpl:
        existing_tpl.template_data = template_data
        existing_tpl.is_system = True
    else:
        db.add(OrgTestTemplate(
            id=uuid.uuid4(), org_id=None, template_key=TEMPLATE_KEY,
            template_data=template_data, is_system=True,
        ))
        templates_inserted += 1

    for equip_name in EQUIPMENT_TYPES:
        master = db.query(CategoryMaster).filter_by(name=equip_name).first()
        if not master:
            print(f"[WARN] CategoryMaster {equip_name!r} not found — skipping")
            continue
        existing_detail = db.query(CategoryDetails).filter_by(
            category_master_id=master.id, name=test_type_name,
        ).first()
        if not existing_detail:
            db.add(CategoryDetails(
                category_master_id=master.id,
                name=test_type_name,
                category_type="test",
                is_active=False,
            ))
            details_inserted += 1
            print(f"[OK] {equip_name}: CategoryDetails row added (disabled)")
        else:
            print(f"[OK] {equip_name}: CategoryDetails row already present")

    db.commit()
    print(f"\n[DONE] {templates_inserted} OrgTestTemplate row inserted, "
          f"{details_inserted} CategoryDetails rows inserted (0/0 on a rerun).")
    print(f"{test_type_name!r} is disabled (is_active=False) — enable per equipment type once reviewed.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db)
    finally:
        db.close()
