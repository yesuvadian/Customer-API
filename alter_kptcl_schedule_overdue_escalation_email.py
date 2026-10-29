#!/usr/bin/env python3
"""
One-time setup: let KPTCL's schedule_overdue_escalation notification send
email, not just in-app.

Background
----------
main.py Pass 3 fires schedule_missed for a CM/PM schedule overdue 1-6 days
and schedule_overdue_escalation once it is 7+ days overdue. The only
routing rule for schedule_overdue_escalation is seed.py's global one with
channels_enabled=["inapp"], so the (active) email template never fired --
once a schedule crossed 7 days overdue, the email alerts stopped entirely.
KPTCL already has an org-specific schedule_missed rule with
["inapp", "email"]; this adds the matching org rule for the escalation
event, so the org rule wins over the global in-app-only one.

Deliberately NOT edited: seed.py's global rule (other orgs keep in-app only).

Idempotent: updates the KPTCL rule if one already exists, else inserts it.

Usage:
    python alter_kptcl_schedule_overdue_escalation_email.py
"""
from database import VendorSessionLocal
from models import NotificationRoutingRule, Organization

ORG_NAME = "Karnataka Power Transmission Corporation Limited"
EVENT_TYPE = "schedule_overdue_escalation"
CHANNELS = ["inapp", "email"]
LABEL = "Schedule Overdue Escalation — In-app + Email"


def main():
    db = VendorSessionLocal()
    try:
        org = db.query(Organization).filter(Organization.name == ORG_NAME).first()
        if not org:
            print(f"[SKIP] Organization {ORG_NAME!r} not found.")
            return

        rule = (
            db.query(NotificationRoutingRule)
            .filter(
                NotificationRoutingRule.event_type == EVENT_TYPE,
                NotificationRoutingRule.organization_id == org.id,
            )
            .first()
        )
        if rule:
            rule.channels_enabled = CHANNELS
            rule.is_active = True
            print(f"[OK] Updated existing KPTCL {EVENT_TYPE} rule -> {CHANNELS}.")
        else:
            db.add(NotificationRoutingRule(
                organization_id=org.id,
                event_type=EVENT_TYPE,
                label=LABEL,
                applicable_workflow_types=[],
                applicable_equipment_types=[],
                applicable_test_types=[],
                channels_enabled=CHANNELS,
                priority=0,
                is_active=True,
            ))
            print(f"[OK] Inserted KPTCL {EVENT_TYPE} rule -> {CHANNELS}.")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
