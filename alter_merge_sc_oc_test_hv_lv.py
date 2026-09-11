"""
Alter: Merge Short Circuit + Open Circuit Test (HV-LV) into one form
=========================================================================
short_circuit_test_hv_lv and open_circuit_test_hv_lv_1ph/_3ph are performed
back-to-back in the same site visit with the same test kit, but previously
required two separate testing requests, approvals, and health-score
entries for one physical test event. Combined into
short_open_circuit_test_hv_lv (test_templates.py).

This script:
  1. Creates the CategoryDetails + OrgTestTemplate rows for the new merged
     type ("Short Circuit & Open Circuit Test (HV-LV)") via
     provision_global_defaults(), same as any new test type.
  2. Deactivates (is_active=False — never deletes) the three old
     CategoryDetails rows ("Short Circuit Test HV-LV", "Open Circuit Test
     HV-LV (1Ph)", "Open Circuit Test HV-LV (3Ph)") so they stop appearing
     as choices for NEW testing requests, while any existing historical
     TestResults recorded under those template_keys remain fully readable —
     nothing is deleted or migrated.

Idempotent - safe to re-run; reports "no change" once applied.

Usage:
    python alter_merge_sc_oc_test_hv_lv.py
"""
from database import VendorSessionLocal
from models import CategoryDetails, CategoryMaster
from services.org_test_template_service import OrgTestTemplateService

EQUIPMENT_NAME = "Power Transformer"
NEW_TEST_TYPE = "Short Circuit & Open Circuit Test (HV-LV)"
RETIRED_TEST_TYPES = [
    "Short Circuit Test HV-LV",
    "Open Circuit Test HV-LV (1Ph)",
    "Open Circuit Test HV-LV (3Ph)",
]


def _get_or_create_category_detail(session, *, name, category_master_id, description, category_type, is_active=True):
    existing = (
        session.query(CategoryDetails)
        .filter_by(name=name, category_master_id=category_master_id)
        .first()
    )
    if existing:
        existing.description = description
        existing.category_type = category_type
        existing.is_active = is_active
        return existing, False

    detail = CategoryDetails(
        name=name,
        description=description,
        category_master_id=category_master_id,
        category_type=category_type,
        is_active=is_active,
    )
    session.add(detail)
    session.flush()
    return detail, True


def run():
    db = VendorSessionLocal()
    try:
        master = db.query(CategoryMaster).filter_by(name=EQUIPMENT_NAME).first()
        if not master:
            print(f"[ERROR] CategoryMaster '{EQUIPMENT_NAME}' not found — run the main seed first.")
            return

        # ── 1. Create the merged test type ──────────────────────────────────
        _, was_created = _get_or_create_category_detail(
            db,
            name=NEW_TEST_TYPE,
            category_master_id=master.id,
            description=f"Test for {EQUIPMENT_NAME}",
            category_type="test",
            is_active=True,
        )
        print(f"[{'OK created' if was_created else 'OK exists '}] CategoryDetails: {NEW_TEST_TYPE}")
        db.commit()

        inserted = OrgTestTemplateService(db).provision_global_defaults()
        print(f"[DONE] provision_global_defaults(): {inserted} new OrgTestTemplate row(s) inserted "
              f"(across all test types missing a row, not just this one).")

        # ── 2. Retire the three old separate test types ─────────────────────
        retired, already_retired, missing = 0, 0, 0
        for name in RETIRED_TEST_TYPES:
            detail = (
                db.query(CategoryDetails)
                .filter_by(name=name, category_master_id=master.id)
                .first()
            )
            if not detail:
                print(f"[SKIP] CategoryDetails '{name}' not found under {EQUIPMENT_NAME}.")
                missing += 1
                continue
            if not detail.is_active:
                already_retired += 1
                continue
            detail.is_active = False
            retired += 1
            print(f"[SET]  Deactivated: {name}")

        db.commit()
        print(f"\nRetired: {retired}, already retired: {already_retired}, not found: {missing}.")
        print("Done. Existing historical test results under the old template keys are untouched.")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run()
