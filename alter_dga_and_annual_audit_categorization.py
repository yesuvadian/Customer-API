"""
One-time fix: DGA category_type + Annual Audit equipment_type
=================================================================
Two independent, unrelated-looking "Other" buckets in the Template Designer
turned out to share one root cause — a missing classification field on how
the row was originally seeded:

  1. "Transformer Dissolved Gas Analysis (DGA)" CategoryDetails row has
     category_type=None (seed_dga bug: _get_or_create_category_detail() was
     called without category_type) - it renders under the catch-all "Other"
     category_type bucket on the Power Transformer Test Templates screen
     instead of "Test", even though it plainly is one. Fix: set it to "test".

  2. The six Annual Audit OrgTestTemplate rows (audit_civil,
     audit_electrical_safety, audit_fire_safety, audit_documentation,
     audit_environmental, audit_general_maintenance) never set
     template_data["equipment_type"] - the Template Designer's frontend
     equipment_type fallback then labels their whole group "Other" instead
     of correctly excluding them via _nonEquipmentMasters (which matches on
     the literal string "Annual Audit Categories"). Fix: set
     template_data["equipment_type"] = "Annual Audit Categories" so the
     existing exclusion logic actually catches them.

Both fixes are also applied at the source in seed.py, so future fresh seeds
get this right automatically - this script only backfills what's already
been seeded on this database.

Idempotent - safe to re-run; reports "no change" once applied.

Usage:
    python alter_dga_and_annual_audit_categorization.py
"""
from database import VendorSessionLocal
from models import CategoryDetails, OrgTestTemplate
from sqlalchemy.orm.attributes import flag_modified

ANNUAL_AUDIT_TEMPLATE_KEYS = [
    "audit_electrical_safety",
    "audit_civil",
    "audit_fire_safety",
    "audit_documentation",
    "audit_environmental",
    "audit_general_maintenance",
]


def run():
    db = VendorSessionLocal()
    try:
        # ── 1. DGA category_type ────────────────────────────────────────────
        dga = (
            db.query(CategoryDetails)
            .filter(CategoryDetails.name == "Transformer Dissolved Gas Analysis (DGA)")
            .first()
        )
        if not dga:
            print("[SKIP] DGA CategoryDetails row not found — nothing to fix.")
        elif dga.category_type == "test":
            print("[OK]   DGA category_type already 'test' — no change needed.")
        else:
            print(f"[SET]  DGA category_type: {dga.category_type!r} -> 'test'")
            dga.category_type = "test"

        # ── 2. Annual Audit equipment_type ──────────────────────────────────
        fixed, already_ok, missing = 0, 0, 0
        for key in ANNUAL_AUDIT_TEMPLATE_KEYS:
            row = (
                db.query(OrgTestTemplate)
                .filter(OrgTestTemplate.template_key == key, OrgTestTemplate.org_id.is_(None))
                .first()
            )
            if not row:
                print(f"[SKIP] OrgTestTemplate '{key}' not found.")
                missing += 1
                continue
            if row.template_data.get("equipment_type") == "Annual Audit Categories":
                already_ok += 1
                continue
            row.template_data["equipment_type"] = "Annual Audit Categories"
            flag_modified(row, "template_data")
            fixed += 1
            print(f"[SET]  {key}: equipment_type -> 'Annual Audit Categories'")

        db.commit()
        print(f"\nAnnual Audit: {fixed} fixed, {already_ok} already correct, {missing} not found.")
        print("Done.")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run()
