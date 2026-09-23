#!/usr/bin/env python3
"""
One-time setup: fix the wf_stage_overdue notification's fallback recipient
roles and documented context_vars, WITHOUT touching seed.py.

Background
----------
main.py's _check_review_sla_breaches (15-min Result Review SLA check) and
the Pass-4 daily stage-SLA digest both resolve recipients from the stage's
own TrWfStageRole configuration first, and only fall back to the
wf_stage_overdue NotificationTemplate's own hardcoded `recipient_roles` when
no stage roles are configured yet (a fresh/unconfigured deployment).

Those hardcoded fallback roles were ["AEE_MAINTENANCE", "Reviewing Officer",
"Supervisory Officer"] -- but "Reviewing Officer" and "Supervisory Officer"
are not real KPTCL OrgRole names (KPTCL uses EE_TLSS, SEE_WM,
CEE_TRANSMISSION_ZONE, etc. -- see seed.py's numbered role list). So on a
fresh deployment, an SLA breach notified at most AEE_MAINTENANCE users --
the exact "role-name mismatch" bug class the TrWfStageRole-based resolution
was itself built to avoid, just reappearing in its own fallback path.

This script updates the 3 existing NotificationTemplate rows (email/sms/
inapp, organization_id IS NULL) for event_type="wf_stage_overdue" to use
["AEE_MAINTENANCE", "EE_TLSS"] instead -- matching the event's own
NotificationEventCatalogue.default_roles, which already used real role
names. It also extends that catalogue row's context_vars to document
dept.name / digest_count / digest_table, which the template already
referenced but the catalogue never listed (those three are now actually
populated by main.py -- see the digest_table / dept.name fix in
_check_review_sla_breaches and the Pass-4 stage digest job).

Deliberately NOT edited: seed.py itself. Rerunning seed.py (or any script
that calls seed.py's _seed_notification_templates / event catalogue seeder)
will reset these rows back to the old values, since that function still
carries the original hardcoded roles -- rerun this script afterward if that
happens.

Idempotent: plain UPDATE by (event_type, channel, organization_id IS NULL)
/ (event_type, organization_id IS NULL) -- safe to re-run.

Usage:
    python alter_notification_wf_stage_overdue_roles.py
"""
from database import VendorSessionLocal
from models import NotificationTemplate, NotificationEventCatalogue

EVENT_TYPE = "wf_stage_overdue"
FIXED_ROLES = ["AEE_MAINTENANCE", "EE_TLSS"]
FIXED_CONTEXT_VARS = [
    "stage.name", "request.number", "equipment.ueic", "equipment.department",
    "dept.name", "days_overdue", "deadline", "digest_count", "digest_table",
]


def main():
    db = VendorSessionLocal()
    try:
        templates = (
            db.query(NotificationTemplate)
            .filter(
                NotificationTemplate.event_type == EVENT_TYPE,
                NotificationTemplate.organization_id.is_(None),
            )
            .all()
        )
        for tmpl in templates:
            tmpl.recipient_roles = FIXED_ROLES
        print(f"[OK] NotificationTemplate rows updated: {len(templates)} "
              f"({', '.join(t.channel for t in templates)}).")

        catalogue = (
            db.query(NotificationEventCatalogue)
            .filter(
                NotificationEventCatalogue.event_type == EVENT_TYPE,
                NotificationEventCatalogue.organization_id.is_(None),
            )
            .first()
        )
        if catalogue:
            catalogue.context_vars = FIXED_CONTEXT_VARS
            print("[OK] NotificationEventCatalogue.context_vars updated.")
        else:
            print(f"[WARN] No NotificationEventCatalogue row found for "
                  f"event_type={EVENT_TYPE!r} -- run seed.py's event "
                  f"catalogue seeder first.")

        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
