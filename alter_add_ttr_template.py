"""
ALTER: Insert the Transformer Turns Ratio (TTR) template for Power
Transformer — a gap flagged directly by the user, also the first procedure
on the TNEB proposal's own CM matrix. The app already has per-winding-pair
ratio tests ("Ratio Test HV-IV" / "Ratio Test HV-LV") and a differently-
scoped tap-wise ratio template filed under the legacy generic "Transformer"
equipment type — this is a proper standalone TTR procedure for the real
Power Transformer registry.

Inserts, disabled by default (is_active=False):
  1. OrgTestTemplate row for "transformer_ttr_test" (test_templates.py) —
     org_id=NULL (system/global), is_system=True.
  2. CategoryDetails row "Transformer Turns Ratio (TTR)" under Power
     Transformer's CategoryMaster, category_type="test".

Safe to run multiple times (checks for existing rows by name/key first).

Usage:
    python alter_add_ttr_template.py
"""

from __future__ import annotations

import uuid

from database import SessionLocal
from models import CategoryDetails, CategoryMaster, OrgTestTemplate
from test_templates import TEST_TEMPLATES

TEMPLATE_KEY = "transformer_ttr_test"
EQUIPMENT_TYPE = "Power Transformer"


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

    master = db.query(CategoryMaster).filter_by(name=EQUIPMENT_TYPE).first()
    if not master:
        print(f"[WARN] CategoryMaster {EQUIPMENT_TYPE!r} not found — CategoryDetails not inserted")
    else:
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

    db.commit()
    print(f"[DONE] {templates_inserted} OrgTestTemplate row inserted, "
          f"{details_inserted} CategoryDetails row inserted (0/0 on a rerun).")
    print(f"{test_type_name!r} is disabled (is_active=False) — enable once reviewed.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db)
    finally:
        db.close()
