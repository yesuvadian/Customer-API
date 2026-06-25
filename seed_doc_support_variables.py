"""
Seed notification_variables for Document Support workflow.
All variables match the keys injected by notification_service.py
for source_type='document_request'.
"""
import uuid
from database import SessionLocal
from sqlalchemy import text

GROUP = "Document Support"

VARIABLES = [
    # ── Core document fields ──────────────────────────────────────────────
    ("doc.id",            "Document ID",              "3fa85f64-5717-4562-b3fc-2c963f66afa6"),
    ("doc.title",         "Document Title",           "Relay Protection Drawings Update"),
    ("title",             "Document Title (alias)",   "Relay Protection Drawings Update"),
    ("doc.description",   "Description",              "Please update the relay drawings for bay 3."),
    ("doc.notes",         "Notes",                    "Refer to the attached version 2 drawings."),
    ("doc.priority",      "Priority",                 "high"),
    ("doc.file_name",     "Attached File Name",       "relay_drawing_v2.pdf"),
    ("doc.file_url",      "Attached File URL",        "https://app.cogniwatt.com/uploads/relay_drawing_v2.pdf"),
    ("doc.mime_type",     "File MIME Type",           "application/pdf"),
    ("doc.target_date",   "Target / Due Date",        "2026-07-15"),
    ("doc.created_at",    "Submitted At",             "2026-06-25 10:30"),
    ("doc.modified_at",   "Last Updated At",          "2026-06-25 14:00"),
    # ── Status / stage ────────────────────────────────────────────────────
    ("doc.status_name",   "Status (Human-Readable)",  "Pending Manager Review"),
    ("status_name",       "Status (alias)",           "Pending Manager Review"),
    ("doc.status_code",   "Status Code",              "ds_pending_manager"),
    ("doc.stage_name",    "Current Stage",            "Manager Review"),
    ("stage_name",        "Current Stage (alias)",    "Manager Review"),
    ("action_code",       "Action Performed",         "assign"),
    # ── People ────────────────────────────────────────────────────────────
    ("originator",              "Originator Name",           "Ravi Kumar"),
    ("originator.name",         "Originator Name (full)",    "Ravi Kumar"),
    ("originator.email",        "Originator Email",          "ravi.kumar@utility.com"),
    ("submitted_by",            "Submitted By (alias)",      "Ravi Kumar"),
    ("doc.submitted_by",        "Submitted By",              "Ravi Kumar"),
    ("doc.submitted_by.email",  "Submitted By Email",        "ravi.kumar@utility.com"),
    ("doc.manager",             "Assigned Manager",          "Priya Subramaniam"),
    ("doc.manager.email",       "Assigned Manager Email",    "priya@utility.com"),
    ("doc.processor",           "Assigned Processor",        "Dev Support User"),
    ("doc.processor.email",     "Assigned Processor Email",  "ds.processor@utility.com"),
]

db = SessionLocal()
try:
    existing = {
        r[0] for r in db.execute(
            text("SELECT var_key FROM notification_variables WHERE group_name = :g"),
            {"g": GROUP}
        ).fetchall()
    }

    inserted = 0
    for var_key, label, sample in VARIABLES:
        if var_key in existing:
            print(f"  skip (exists): {var_key}")
            continue
        db.execute(text("""
            INSERT INTO notification_variables
                (id, var_key, label, group_name, sample_value, is_system, is_active)
            VALUES
                (:id, :var_key, :label, :group_name, :sample_value, true, true)
        """), {
            "id":           str(uuid.uuid4()),
            "var_key":      var_key,
            "label":        label,
            "group_name":   GROUP,
            "sample_value": sample,
        })
        inserted += 1
        print(f"  inserted: {var_key}")

    db.commit()
    print(f"\nDone — {inserted} variables seeded in [{GROUP}]")
finally:
    db.close()
