"""
Seed a single tr_wf_status_changed notification template (sms + inapp + email).
One template covers every TR workflow stage transition — the status_name variable
is populated dynamically from the org's configured workflow statuses.

Run: python seed_tr_wf_notification_templates.py
"""
import sys
sys.path.insert(0, ".")

from database import SessionLocal
from models import NotificationTemplate
from sqlalchemy import text

EVENT_TYPE = "tr_wf_status_changed"

TEMPLATES = [
    {
        "channel": "sms",
        "subject_template": "",
        "body_template": (
            "[SEACMS] Testing Request {{request_number}} status: {{status_name}}. "
            "Login to SEACMS for details."
        ),
        "recipient_roles": ["@originator", "@assignee"],
    },
    {
        "channel": "inapp",
        "subject_template": "TR {{request_number}} — {{status_name}}",
        "body_template": (
            "Testing Request {{request_number}} for {{equipment}} has moved to: "
            "{{status_name}}."
        ),
        "recipient_roles": ["@originator", "@assignee"],
    },
    {
        "channel": "email",
        "subject_template": "Testing Request {{request_number}} — Status Update",
        "body_template": (
            "<h2 style='color:#1E3C72;margin-bottom:4px;'>Testing Request Status Update</h2>"
            "<p style='color:#555;margin-top:0;'>The status of your testing request has been updated.</p>"
            "<table width='100%' cellpadding='0' cellspacing='0' "
            "style='border-collapse:collapse;font-size:13px;margin-bottom:16px;'>"
            "<tr><td style='padding:8px 0;color:#888;width:160px;'>Request Number</td>"
            "<td style='padding:8px 0;font-weight:600;color:#0F172A;'>{{request_number}}</td></tr>"
            "<tr><td style='padding:8px 0;color:#888;'>Equipment</td>"
            "<td style='padding:8px 0;font-weight:600;color:#0F172A;'>{{equipment}}</td></tr>"
            "<tr><td style='padding:8px 0;color:#888;'>New Status</td>"
            "<td style='padding:8px 0;font-weight:600;color:#1E3C72;'>{{status_name}}</td></tr>"
            "<tr><td style='padding:8px 0;color:#888;'>Stage</td>"
            "<td style='padding:8px 0;color:#0F172A;'>{{stage_name}}</td></tr>"
            "</table>"
            "<p style='margin-top:20px;'>Please log in to SEACMS to take the required action.</p>"
        ),
        "recipient_roles": ["@originator", "@assignee"],
    },
]


def run():
    db = SessionLocal()
    try:
        # Remove any pre-existing seeds for this event to avoid duplicates
        existing = db.query(NotificationTemplate).filter(
            NotificationTemplate.event_type == EVENT_TYPE,
            NotificationTemplate.organization_id.is_(None),
        ).all()
        if existing:
            print(f"Removing {len(existing)} existing global {EVENT_TYPE} templates...")
            for t in existing:
                db.delete(t)
            db.flush()

        for tmpl in TEMPLATES:
            db.add(NotificationTemplate(
                event_type=EVENT_TYPE,
                channel=tmpl["channel"],
                subject_template=tmpl["subject_template"],
                body_template=tmpl["body_template"],
                recipient_roles=tmpl["recipient_roles"],
                organization_id=None,   # global — applies to all orgs
                is_active=True,
                org_channel_disabled=False,
            ))
        db.commit()
        print(f"Seeded {len(TEMPLATES)} templates for '{EVENT_TYPE}' (sms, inapp, email).")
    except Exception as e:
        db.rollback()
        print(f"Failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
