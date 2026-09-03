"""
Idempotent seeder for the direct-submission OrgTestTemplate rows:
  - taqc_inspection  (TA&QC Inspection form)
  - failure_registry (Equipment Failure Registry form)

Both are seeded as GLOBAL system templates (org_id=NULL, is_system=True) so
every organization shares the same form definition — mirrors
seed_direct_submission_templates() in seed.py, extracted here so it can be
run on its own without re-running the full seed.py.

Safe to run multiple times: existing rows (matched by template_key +
org_id IS NULL) have their template_data refreshed and version bumped;
missing rows are inserted.

Usage:
    python seed_direct_submission_templates.py
"""
from database import SessionLocal
from models import OrgTestTemplate

TEMPLATES = {
    "taqc_inspection": {
        "key": "taqc_inspection",
        "name": "TA&QC Inspection",
        "template_type": "ta_qc",
        "description": "Substation Inspection — record observations and compliance actions.",
        "sections": [
            {
                "title": "Inspection Details",
                "fields": [
                    {"key": "substation",          "label": "Substation Name / Area",  "type": "text",     "required": True},
                    {"key": "inspection_date",     "label": "Date of Inspection",       "type": "date",     "required": True},
                    {"key": "inspection_category", "label": "Inspection Category",      "type": "dropdown", "required": True,
                     "options": ["Electrical Safety", "Civil", "Fire Safety", "Documentation", "Environmental", "General Maintenance"]},
                ],
            },
            {
                "title": "Observation",
                "fields": [
                    {"key": "observation_description", "label": "Description of Observation", "type": "textarea", "required": True},
                    {"key": "severity",                "label": "Severity",                   "type": "dropdown", "required": True,
                     "options": ["Major", "Minor", "Advisory"]},
                ],
            },
            {
                "title": "Compliance",
                "fields": [
                    {"key": "target_compliance_date", "label": "Target Compliance Date", "type": "date",     "required": False},
                    {"key": "remarks",                "label": "Remarks",                "type": "textarea", "required": False},
                ],
            },
        ],
    },
    "failure_registry": {
        "key": "failure_registry",
        "name": "Equipment Failure Registry",
        "template_type": "failure_registry",
        "description": "Record equipment failures for tracking and root-cause analysis.",
        "sections": [
            {
                "title": "Failure Information",
                "fields": [
                    {"key": "failure_date",        "label": "Date of Failure",       "type": "date",     "required": True},
                    # KPTCL spec §2: "classification of failure type — Unexpected
                    # Breakdown, Forced Outage, Degradation Failure, Partial
                    # Discharge, Insulation Failure, Mechanical Failure, Protection
                    # Misoperation, and any other failure type defined by the
                    # utility." A distinct axis from failure_category below (that
                    # one is which subsystem — Electrical/Oil/Protection/etc — this
                    # is the nature of the failure event itself). "any other ...
                    # defined by the utility" is already satisfied by this being a
                    # normal dropdown field — an admin can add more options via
                    # Template Designer without a code change.
                    {"key": "failure_type",        "label": "Failure Type",          "type": "dropdown", "required": True,
                     "options": ["Unexpected Breakdown", "Forced Outage", "Degradation Failure",
                                 "Partial Discharge", "Insulation Failure", "Mechanical Failure",
                                 "Protection Misoperation", "Other"]},
                    {"key": "failure_category",    "label": "Failure Category",      "type": "dropdown", "required": True,
                     "options": ["Electrical", "Mechanical", "Oil", "Protection", "Thermal", "Other"]},
                    # KPTCL spec §2: "...capturing failure date, failure mode,
                    # failure symptoms, probable cause, equipment status at
                    # failure, and affected substation/bay details."
                    # Substation/bay is already covered transitively (the
                    # equipment record itself carries bay_number + department);
                    # these two were the genuinely missing capture fields.
                    {"key": "equipment_status_at_failure", "label": "Equipment Status at Failure", "type": "dropdown", "required": True,
                     "options": ["In Service (Energized)", "Out of Service", "Under Maintenance",
                                 "Under Testing / Commissioning", "Standby / Reserve", "Other"]},
                    {"key": "failure_description", "label": "Description of Failure","type": "textarea", "required": True},
                    {"key": "failure_symptoms",    "label": "Failure Symptoms",      "type": "textarea", "required": True},
                    {"key": "root_cause_analysis", "label": "Root Cause Analysis",   "type": "textarea", "required": False},
                ],
            },
            {
                "title": "Outage Impact",
                "fields": [
                    {"key": "outage_duration_hours", "label": "Outage Duration (hours)",      "type": "number",   "required": False},
                    {"key": "affected_consumers",    "label": "Affected Consumers (count)",   "type": "number",   "required": False},
                    {"key": "outage_impact",         "label": "Outage Impact Description",    "type": "textarea", "required": False},
                ],
            },
            # NOTE: "Outcome" section removed — the API appends "Outcome & Scheduling"
            # from the overall_assessment template for failure_registry forms,
            # which covers next_action, schedule, summary and notes.
        ],
    },
}


def seed_direct_submission_templates(session) -> int:
    """Upsert both templates as global (org_id=NULL) system templates. Returns count of newly inserted rows."""
    count = 0
    for key, data in TEMPLATES.items():
        existing = session.query(OrgTestTemplate).filter(
            OrgTestTemplate.template_key == key,
            OrgTestTemplate.org_id == None,  # noqa: E711
        ).first()
        if existing:
            # Always update template_data so changes to sections/fields are picked up
            existing.template_data = data
            existing.version = (existing.version or 1) + 1
        else:
            session.add(OrgTestTemplate(
                template_key=key,
                org_id=None,
                test_type_id=None,
                template_data=data,
                is_system=True,
                version=1,
            ))
            count += 1
    session.commit()
    return count


if __name__ == "__main__":
    db = SessionLocal()
    try:
        n = seed_direct_submission_templates(db)
        print(f"[OK] Direct-submission templates (taqc_inspection, failure_registry): {n} newly inserted, existing rows refreshed.")
    finally:
        db.close()
