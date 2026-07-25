"""
Delete OrgTestTemplate system rows with wrong/duplicate template_key mappings.

Wrong mappings identified:
  transformer_maintenance  -> 13 rows (12 equipment share one key + 2 PT types share one key)
  transformer_inspection   -> all 60+ rows (6 generic names across every equipment → 1 key)
  battery_maintenance      -> 2 rows sharing one key
  surge_arrestor_maintenance -> 2 rows sharing one key

Run: python delete_wrong_mappings.py
"""

from database import SessionLocal
from models import OrgTestTemplate, CategoryDetails, CategoryMaster

db = SessionLocal()

try:
    # ── Collect test_type_ids to remove ──────────────────────────────────────

    # 1. transformer_maintenance: all 13 rows (Routine Preventive Maintenance
    #    across 12 equipment types + Power Transformer Major Maintenance)
    bad_transformer_maintenance_ids = [76, 91, 139, 144, 148, 155, 159, 163, 168, 172, 177, 184, 77]

    # 2. transformer_inspection: all 6 generic names across every equipment
    #    (Electrical Safety, Civil, Fire Safety, Documentation, Environmental,
    #    General Maintenance) including Annual Audit Categories (277-282)
    inspection_names = [
        "Electrical Safety", "Civil", "Fire Safety",
        "Documentation", "Environmental", "General Maintenance",
    ]
    bad_inspection_ids = [
        d.id for d in db.query(CategoryDetails)
        .filter(CategoryDetails.name.in_(inspection_names))
        .all()
    ]

    # 3. battery_maintenance: both Battery Set maintenance types
    bad_battery_maintenance_ids = [124, 125]

    # 4. surge_arrestor_maintenance: both Surge Arrestor types
    bad_surge_maintenance_ids = [114, 115]

    all_bad_ids = set(
        bad_transformer_maintenance_ids
        + bad_inspection_ids
        + bad_battery_maintenance_ids
        + bad_surge_maintenance_ids
    )

    # ── Preview what will be deleted ─────────────────────────────────────────
    rows = (
        db.query(OrgTestTemplate)
        .filter(
            OrgTestTemplate.org_id == None,  # noqa: E711
            OrgTestTemplate.test_type_id.in_(all_bad_ids),
        )
        .all()
    )

    print("Will delete " + str(len(rows)) + " OrgTestTemplate system rows:")
    for r in sorted(rows, key=lambda x: x.template_key):
        cd = db.query(CategoryDetails).filter(CategoryDetails.id == r.test_type_id).first()
        master = db.query(CategoryMaster).filter(CategoryMaster.id == cd.category_master_id).first() if cd else None
        cd_name = cd.name if cd else "?"
        eq_name = master.name if master else "?"
        print("  [" + r.template_key + "] id=" + str(r.test_type_id) + " " + cd_name + " / " + eq_name)

    confirm = input("\nType YES to delete: ")
    if confirm.strip() != "YES":
        print("Aborted.")
        db.close()
        exit(0)

    # ── Delete ───────────────────────────────────────────────────────────────
    deleted = (
        db.query(OrgTestTemplate)
        .filter(
            OrgTestTemplate.org_id == None,  # noqa: E711
            OrgTestTemplate.test_type_id.in_(all_bad_ids),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    print("Deleted " + str(deleted) + " rows.")

    remaining = db.query(OrgTestTemplate).filter(OrgTestTemplate.org_id == None).count()
    print("System templates remaining: " + str(remaining))

except Exception as e:
    db.rollback()
    print("Error: " + str(e))
    raise
finally:
    db.close()
