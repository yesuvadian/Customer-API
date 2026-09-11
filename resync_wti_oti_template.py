"""
Resync the wti_oti_functional_test and partial_discharge_test template
definitions from test_templates.py into the org_test_templates table.

This is NOT a schema change (no ALTER TABLE) -- it's a data resync. The live
app reads templates from org_test_templates, which was seeded from
test_templates.py at some earlier point; editing the .py file alone does not
change what's already in the database.

Unlike provision_global_defaults() (used by seed.py / the /provision/global
endpoint / resync_dfr_sfra_templates.py), this script touches ONLY the
template_keys listed in TARGET_KEYS below -- no other template in the system
is read or written.

IMPORTANT: if any org has a customized (org_id IS NOT NULL) copy of one of
these templates, --sync will OVERWRITE that copy's template_data with the
fresh global default, discarding whatever customization was made via the
Template Designer. Run --check first to see if that applies here.

Usage:
    python resync_wti_oti_template.py --check   # safety check only, no writes
    python resync_wti_oti_template.py --sync    # actually resync
"""
import sys

from sqlalchemy.orm.attributes import flag_modified

from database import VendorSessionLocal
from models import OrgTestTemplate, CategoryDetails
from test_templates import TEST_TEMPLATES

# template_key -> CategoryDetails.name (only needed if a fresh insert is required)
TARGET_KEYS = {
    "wti_oti_functional_test": "WTI / OTI Functional Test",
    "partial_discharge_test": "Partial Discharge Measurement",
    "circuit_breaker_contact_resistance": "Contact Resistance Test",
}


def check(db):
    rows = (
        db.query(OrgTestTemplate)
        .filter(OrgTestTemplate.template_key.in_(TARGET_KEYS.keys()))
        .all()
    )
    if not rows:
        print("No existing rows for these template keys -- sync will insert them fresh. Safe to proceed.")
        return True

    org_specific = [r for r in rows if r.org_id is not None]
    for r in rows:
        print(f"  template_key={r.template_key!r} org_id={r.org_id} is_system={r.is_system} version={r.version}")

    if org_specific:
        print(f"\n[WARNING] {len(org_specific)} org-specific row(s) found for these template keys.")
        print("Running --sync will OVERWRITE their template_data with the fresh global default,")
        print("discarding any per-org customization made via the Template Designer.")
        print("Confirm this is intended before running --sync.")
        return False

    print("\nOnly global (org_id=None) rows found -- safe to sync.")
    return True


def sync(db):
    for template_key, type_name in TARGET_KEYS.items():
        template_data = dict(TEST_TEMPLATES[template_key])
        template_data["template_type"] = "test"

        existing = (
            db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.org_id == None, OrgTestTemplate.template_key == template_key)  # noqa: E711
            .first()
        )

        if existing:
            existing.template_data = template_data
            existing.version = (existing.version or 1) + 1
            flag_modified(existing, "template_data")

            copies = (
                db.query(OrgTestTemplate)
                .filter(OrgTestTemplate.template_key == template_key, OrgTestTemplate.org_id != None)  # noqa: E711
                .all()
            )
            for copy in copies:
                copy.template_data = template_data
                copy.version = existing.version
                flag_modified(copy, "template_data")

            print(f"[{template_key}] Updated global row (version -> {existing.version}) "
                  f"and cascaded to {len(copies)} org-specific copy/copies.")
        else:
            detail = db.query(CategoryDetails).filter(CategoryDetails.name == type_name).first()
            if not detail:
                print(f"[{template_key}] No CategoryDetails row named {type_name!r} -- cannot insert fresh row. Skipping.")
                continue
            db.add(OrgTestTemplate(
                org_id=None,
                template_key=template_key,
                test_type_id=detail.id,
                template_data=template_data,
                is_system=True,
                version=1,
            ))
            print(f"[{template_key}] Inserted new global row.")

    db.commit()


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    db = VendorSessionLocal()
    try:
        if mode == "--check":
            check(db)
        elif mode == "--sync":
            sync(db)
        else:
            print(f"Unknown mode {mode!r} -- use --check or --sync")
    finally:
        db.close()
