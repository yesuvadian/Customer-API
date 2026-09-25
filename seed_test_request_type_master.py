"""
Seed: Test Request Type master + details (ORIGINAL / FOLLOW_UP / RETEST)
=============================================================================
Mirrors the existing "Testing Priority" pattern exactly (see
seed_test_type_categories() in seed.py): a small CategoryMaster with plain
CategoryDetails rows as the admin-visible/editable pick-list, while the
actual TestingRequest.request_type column stores the matching plain string
directly (not a FK) — same as TestingRequest.priority does today.

Kept as a plain string on TestingRequest (not a FK to CategoryDetails.id) on
purpose: request_type drives real branching logic in car_service.py (RETEST
-> look for an open CAR in this TR's lineage and attach to it), so the code
needs a stable string to match against. The CategoryDetails rows exist so
the valid options are visible/manageable through the same admin screens as
every other picklist in the system, without making that business logic
depend on an admin-renamable display label.

Idempotent — safe to re-run.

Usage:
    python seed_test_request_type_master.py
"""
from database import VendorSessionLocal
from models import CategoryMaster, CategoryDetails

MASTER_NAME = "Test Request Type"
REQUEST_TYPES = ["ORIGINAL", "FOLLOW_UP", "RETEST"]


def _get_or_create_category_detail(session, *, name, category_master_id, description, is_active=True):
    existing = (
        session.query(CategoryDetails)
        .filter_by(name=name, category_master_id=category_master_id)
        .first()
    )
    if existing:
        existing.description = description
        existing.is_active = is_active
        return existing, False

    detail = CategoryDetails(
        name=name,
        description=description,
        category_master_id=category_master_id,
        is_active=is_active,
    )
    session.add(detail)
    session.flush()
    return detail, True


def run():
    db = VendorSessionLocal()
    try:
        master = db.query(CategoryMaster).filter_by(name=MASTER_NAME).first()
        if not master:
            master = CategoryMaster(
                name=MASTER_NAME,
                description="Test Request lineage type — ORIGINAL, FOLLOW_UP, or RETEST",
                is_active=True,
            )
            db.add(master)
            db.flush()
            print(f"[OK created] CategoryMaster: {MASTER_NAME}")
        else:
            print(f"[OK exists ] CategoryMaster: {MASTER_NAME}")

        created, updated = 0, 0
        for rt in REQUEST_TYPES:
            _, was_created = _get_or_create_category_detail(
                db,
                name=rt,
                category_master_id=master.id,
                description=f"{rt.replace('_', ' ').title()} test request",
                is_active=True,
            )
            if was_created:
                created += 1
                print(f"[OK created] CategoryDetails: {rt}")
            else:
                updated += 1
                print(f"[OK exists ] CategoryDetails: {rt}")

        db.commit()
        print(f"\nDone. {created} created, {updated} already existed.")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run()
