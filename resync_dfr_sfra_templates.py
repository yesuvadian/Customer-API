"""
Resync the dfr_idax_transformer / sfra_routine / sfra_transformer template
definitions from test_templates.py into the org_test_templates table.

This is NOT a schema change (no ALTER TABLE) -- it's a data resync. The live
app reads templates from org_test_templates, which was seeded from
test_templates.py at some earlier point; editing the .py file alone does not
change what's already in the database.

Uses the exact same code path as the app's own POST /org-test-templates/
provision/global endpoint (OrgTestTemplateService.provision_global_defaults),
so it applies the same versioning/cascade behavior as the real API.

IMPORTANT: provision_global_defaults() resyncs ALL templates, not just these
three, and cascades to every org-specific customized copy sharing the same
template_key. Run the check below FIRST in each environment (dev, prod) to
confirm no org has customized these specific templates before running the
sync -- if any do, their customization would be overwritten with the fresh
default.

Usage:
    python resync_dfr_sfra_templates.py --check   # safety check only, no writes
    python resync_dfr_sfra_templates.py --sync    # actually resync
"""
import sys

from database import VendorSessionLocal
from models import OrgTestTemplate
from services.org_test_template_service import OrgTestTemplateService

TARGET_KEYS = ["dfr_idax_transformer", "sfra_routine", "sfra_transformer"]


def check(db):
    rows = (
        db.query(OrgTestTemplate)
        .filter(OrgTestTemplate.template_key.in_(TARGET_KEYS))
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
    svc = OrgTestTemplateService(db)
    count = svc.provision_global_defaults()
    print(f"Provisioned/updated {count} newly-inserted global template row(s) "
          f"(existing rows across ALL template keys were updated in place, versions bumped).")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    db = VendorSessionLocal()
    try:
        if mode == "--check":
            check(db)
        elif mode == "--sync":
            db.commit()  # no-op, just ensures a clean session before writing
            sync(db)
        else:
            print(f"Unknown mode {mode!r} -- use --check or --sync")
    finally:
        db.close()
