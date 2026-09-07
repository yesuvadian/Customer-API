"""
Seed: WTI/OTI, PRV, and Buchholz relay functional-test types
==============================================================
Adds the three new Power Transformer test types defined in test_templates.py
(wti_oti_functional_test, prv_functional_test, buchholz_relay_functional_test)
to the live database, so they're selectable in the Test Type picker and get
their OrgTestTemplate rows provisioned.

Two steps, both idempotent (safe to re-run):
  1. Create/update the three CategoryDetails rows under the "Power
     Transformer" CategoryMaster (category_type="test") — mirrors what
     seed.py's seed_test_type_categories() does for every other test type,
     scoped to just these three instead of re-running the entire seed file.
  2. Call OrgTestTemplateService.provision_global_defaults(), which reads
     TEST_TYPE_TO_TEMPLATE + TEST_TEMPLATES and inserts one system
     OrgTestTemplate row (org_id=None) per new template_key, now that a
     matching CategoryDetails row exists for each.

Usage:
    python seed_transformer_auxiliary_functional_tests.py
"""
from database import VendorSessionLocal
from models import CategoryMaster, CategoryDetails
from services.org_test_template_service import OrgTestTemplateService

EQUIPMENT_NAME = "Power Transformer"

NEW_TEST_TYPES = [
    "WTI / OTI Functional Test",
    "Pressure Relief Valve (PRV) Functional Test",
    "Buchholz Relay Functional Test",
]


def _get_or_create_category_detail(session, *, name, category_master_id, description, category_type, is_active=True):
    """Same shape as seed.py's helper of the same name — kept local so this
    script has no import-order dependency on the giant seed.py module."""
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

        created, updated = 0, 0
        for type_name in NEW_TEST_TYPES:
            _, was_created = _get_or_create_category_detail(
                db,
                name=type_name,
                category_master_id=master.id,
                description=f"Test for {EQUIPMENT_NAME}",
                category_type="test",
                is_active=True,
            )
            if was_created:
                created += 1
                print(f"[OK]  CategoryDetails created: {type_name}")
            else:
                updated += 1
                print(f"[OK]  CategoryDetails already present (refreshed): {type_name}")

        db.commit()
        print(f"\nCategoryDetails: {created} created, {updated} already existed.\n")

        inserted = OrgTestTemplateService(db).provision_global_defaults()
        print(f"[DONE] provision_global_defaults(): {inserted} new OrgTestTemplate row(s) inserted "
              f"(across ALL test types missing a row — not just these three; safe, only inserts "
              f"where none exists yet).")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run()
