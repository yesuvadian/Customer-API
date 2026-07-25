"""
One-time cleanup: remove duplicate system OrgTestTemplate rows.

The provision_global_defaults bug created multiple rows per template_key
(one per CategoryDetail whose name matched the key). This script deletes
all but the winner — the row with the lowest `id` for each key — then
re-runs provision_global_defaults so the DB is consistent with the seed.

Run once:  python cleanup_duplicate_templates.py
"""

from database import SessionLocal
from models import OrgTestTemplate

db = SessionLocal()

try:
    # Load all system templates grouped by template_key
    all_system = (
        db.query(OrgTestTemplate)
        .filter(OrgTestTemplate.org_id == None)  # noqa: E711
        .order_by(OrgTestTemplate.template_key, OrgTestTemplate.id)
        .all()
    )

    # Keep lowest-id row per key; delete the rest
    seen: dict = {}
    to_delete = []
    for row in all_system:
        if row.template_key not in seen:
            seen[row.template_key] = row
        else:
            to_delete.append(row)

    if to_delete:
        print(f"Deleting {len(to_delete)} duplicate system template rows...")
        for row in to_delete:
            db.delete(row)
        db.flush()
        print("Done deleting duplicates.")
    else:
        print("No duplicates found.")

    # Re-run provision so every template_key gets the correct test_type_id
    # and latest template_data
    from services.org_test_template_service import OrgTestTemplateService
    svc = OrgTestTemplateService(db)
    svc.provision_global_defaults()

    db.commit()
    print("Cleanup and re-provision complete.")
    print(f"System templates remaining: {db.query(OrgTestTemplate).filter(OrgTestTemplate.org_id == None).count()}")

except Exception as e:
    db.rollback()
    print(f"Error: {e}")
    raise
finally:
    db.close()
