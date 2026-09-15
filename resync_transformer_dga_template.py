"""
Resync the transformer_dga template definition from test_templates.py into
the org_test_templates table.

This is NOT a schema change (no ALTER TABLE) -- it's a data resync. The live
app reads templates from org_test_templates, which was seeded from
test_templates.py at some earlier point; editing the .py file alone does not
change what's already in the database. Without this, the "dga_results"
field's is_duval_triangle_source flag and duval_watchlist_severity config
(added for the Duval Triangle Watch-List feature) never reach the live
template -- so the Template Designer's zone-severity editor never renders,
the evaluation engine never escalates a submission on a bad Duval zone, and
the Deterioration Watch List never surfaces a Duval finding, even though
every line of code for all three is deployed and correct.

Uses the exact same code path as the app's own POST /org-test-templates/
provision/global endpoint (OrgTestTemplateService.provision_global_defaults),
so it applies the same versioning/cascade behavior as the real API.

IMPORTANT: provision_global_defaults() resyncs ALL templates, not just this
one, and cascades to every org-specific customized copy sharing the same
template_key. Run --check FIRST in each environment (dev, staging, prod) to
confirm no org has customized transformer_dga before running --sync -- if
any org has, their customization would be overwritten with the fresh
default.

Usage:
    python resync_transformer_dga_template.py --check   # safety check only, no writes
    python resync_transformer_dga_template.py --sync    # actually resync
"""
import sys

from database import VendorSessionLocal
from models import OrgTestTemplate
from services.org_test_template_service import OrgTestTemplateService

TARGET_KEY = "transformer_dga"


def check(db):
    rows = (
        db.query(OrgTestTemplate)
        .filter(OrgTestTemplate.template_key == TARGET_KEY)
        .all()
    )
    if not rows:
        print("No existing rows for transformer_dga -- sync will insert it fresh. Safe to proceed.")
        return True

    org_specific = [r for r in rows if r.org_id is not None]
    for r in rows:
        has_duval = bool(
            any(
                f.get("is_duval_triangle_source")
                for sec in (r.template_data or {}).get("sections", [])
                for f in sec.get("fields", [])
            )
        )
        print(
            f"  org_id={r.org_id} is_system={r.is_system} version={r.version} "
            f"has_duval_config={has_duval}"
        )

    if org_specific:
        print(f"\n[WARNING] {len(org_specific)} org-specific row(s) found for transformer_dga.")
        print("Running --sync will OVERWRITE their template_data with the fresh global default,")
        print("discarding any per-org customization made via the Template Designer (including")
        print("any org-specific Duval zone-severity tiers already set through that UI).")
        print("Confirm this is intended before running --sync.")
        return False

    print("\nOnly global (org_id=None) rows found -- safe to sync.")
    return True


def sync(db):
    svc = OrgTestTemplateService(db)
    count = svc.provision_global_defaults()
    print(f"Provisioned/updated {count} newly-inserted global template row(s) "
          f"(existing rows across ALL template keys were updated in place, versions bumped).")

    row = (
        db.query(OrgTestTemplate)
        .filter(OrgTestTemplate.template_key == TARGET_KEY, OrgTestTemplate.org_id.is_(None))
        .first()
    )
    has_duval = bool(
        row and any(
            f.get("is_duval_triangle_source")
            for sec in (row.template_data or {}).get("sections", [])
            for f in sec.get("fields", [])
        )
    )
    print(f"transformer_dga now at version={row.version if row else '?'} "
          f"has_duval_config={has_duval}")


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
