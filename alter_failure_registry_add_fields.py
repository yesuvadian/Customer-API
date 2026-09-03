#!/usr/bin/env python3
"""
One-time alter: add the failure_registry template fields called for by
KPTCL spec §2 that were missing from the original form —

  "The system shall support classification of failure type — Unexpected
  Breakdown, Forced Outage, Degradation Failure, Partial Discharge,
  Insulation Failure, Mechanical Failure, Protection Misoperation, and
  any other failure type defined by the utility."

  "...capturing failure date, failure mode, failure symptoms, probable
  cause, equipment status at failure, and affected substation/bay
  details."

Adds three fields to every existing failure_registry OrgTestTemplate row:
  failure_type                 — dropdown, the spec's own list above
  equipment_status_at_failure  — dropdown
  failure_symptoms             — textarea

Not touched, deliberately:
  - substation/bay — already covered transitively (the equipment record
    itself carries bay_number + department), not a new FR field
  - probable_cause / "failure mode" — the existing failure_category
    field (Electrical/Mechanical/Oil/Protection/Thermal/Other) may
    already be serving as "failure mode"; unresolved question, not
    something to guess at here

Non-destructive: reads each row's own current template_data and inserts
only whichever of the three fields it's missing, rather than replacing
the whole blob — any Template Designer customization already on a row
(extra options, a renamed section, an org-specific override) survives
untouched. Safe to run against dev/prod even if their templates have
drifted from what's in seed.py.

Idempotent per field — a row missing only one of the three is topped up
without duplicating the ones it already has. Safe to re-run.

Usage:
    python alter_failure_registry_add_fields.py
"""
from database import VendorSessionLocal
from models import OrgTestTemplate
from sqlalchemy.orm.attributes import flag_modified

# Each entry inserts right after `after_key` in whichever section already
# holds it; applied in this order so later entries can anchor off fields
# earlier entries just added.
NEW_FIELDS = [
    {
        "after_key": "failure_date",
        "field": {
            "key": "failure_type",
            "label": "Failure Type",
            "type": "dropdown",
            "required": True,
            "options": [
                "Unexpected Breakdown", "Forced Outage", "Degradation Failure",
                "Partial Discharge", "Insulation Failure", "Mechanical Failure",
                "Protection Misoperation", "Other",
            ],
        },
    },
    {
        "after_key": "failure_category",
        "field": {
            "key": "equipment_status_at_failure",
            "label": "Equipment Status at Failure",
            "type": "dropdown",
            "required": True,
            "options": [
                "In Service (Energized)", "Out of Service", "Under Maintenance",
                "Under Testing / Commissioning", "Standby / Reserve", "Other",
            ],
        },
    },
    {
        "after_key": "failure_description",
        "field": {
            "key": "failure_symptoms",
            "label": "Failure Symptoms",
            "type": "textarea",
            "required": True,
        },
    },
]


def _add_missing_fields(template_data: dict) -> list:
    """Mutates template_data in place. Returns the list of field keys
    actually added (empty if no matching section was found, or
    everything was already present)."""
    for section in template_data.get("sections", []):
        fields = section.get("fields", [])
        keys = [f.get("key") for f in fields]
        # Identify the right section by anchoring on fields we know
        # already live in it, rather than assuming section position.
        if "failure_date" not in keys and "failure_category" not in keys:
            continue

        added = []
        for spec in NEW_FIELDS:
            new_key = spec["field"]["key"]
            if new_key in keys:
                continue
            after_key = spec["after_key"]
            insert_at = keys.index(after_key) + 1 if after_key in keys else len(fields)
            fields.insert(insert_at, dict(spec["field"]))
            keys.insert(insert_at, new_key)
            added.append(new_key)
        return added
    return []


def main():
    db = VendorSessionLocal()
    try:
        rows = (
            db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.template_key == "failure_registry")
            .all()
        )
        if not rows:
            print("No failure_registry OrgTestTemplate rows found — nothing to alter.")
            return

        altered = unchanged = 0
        for row in rows:
            org_label = row.org_id if row.org_id else "GLOBAL (org_id=NULL)"
            added = _add_missing_fields(row.template_data)
            if added:
                flag_modified(row, "template_data")
                row.version = (row.version or 1) + 1
                altered += 1
                print(f"[ALTERED]   org={org_label}  id={row.id}  "
                      f"added={added}  version -> {row.version}")
            else:
                unchanged += 1
                print(f"[SKIP]      org={org_label}  id={row.id}  "
                      f"already up to date (or no matching section)")

        db.commit()
        print(f"\n{altered} row(s) altered, {unchanged} unchanged.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
