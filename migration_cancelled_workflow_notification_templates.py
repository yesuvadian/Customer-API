"""
Add cancelled workflow notification templates.
Run: python add_cancelled_workflow_notification_templates.py
"""

from database import get_db
from models import NotificationTemplate


def add_templates():
    db = next(get_db())

    templates = [
        {
            "event_type": "repair_cancelled",
            "channel": "email",
            "subject_template": "[REPAIR] Workflow Cancelled — {equipment}",
            "body_template": "<h3>Repair workflow cancelled</h3>"
                              "<p>The repair workflow for {equipment} has been cancelled.</p>"
                              "<p>Cancelled by: {cancelled_by}</p>"
                              "<p>Reason: {cancel_reason}</p>",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "repair_cancelled",
            "channel": "sms",
            "subject_template": "",
            "body_template": "Repair workflow for {equipment} was cancelled by {cancelled_by}. Reason: {cancel_reason}.",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "repair_cancelled",
            "channel": "inapp",
            "subject_template": "Repair workflow cancelled — {equipment}",
            "body_template": "The repair workflow for {equipment} has been cancelled. Reason: {cancel_reason}.",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "overhaul_cancelled",
            "channel": "email",
            "subject_template": "[OVERHAUL] Workflow Cancelled — {equipment}",
            "body_template": "<h3>Overhaul workflow cancelled</h3>"
                              "<p>The overhaul workflow for {equipment} has been cancelled.</p>"
                              "<p>Cancelled by: {cancelled_by}</p>"
                              "<p>Reason: {cancel_reason}</p>",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "overhaul_cancelled",
            "channel": "sms",
            "subject_template": "",
            "body_template": "Overhaul workflow for {equipment} was cancelled by {cancelled_by}. Reason: {cancel_reason}.",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "overhaul_cancelled",
            "channel": "inapp",
            "subject_template": "Overhaul workflow cancelled — {equipment}",
            "body_template": "The overhaul workflow for {equipment} has been cancelled. Reason: {cancel_reason}.",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "calibration_cancelled",
            "channel": "email",
            "subject_template": "[CALIBRATION] Workflow Cancelled — {equipment}",
            "body_template": "<h3>Calibration workflow cancelled</h3>"
                              "<p>The calibration workflow for {equipment} has been cancelled.</p>"
                              "<p>Cancelled by: {cancelled_by}</p>"
                              "<p>Reason: {cancel_reason}</p>",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "calibration_cancelled",
            "channel": "sms",
            "subject_template": "",
            "body_template": "Calibration workflow for {equipment} was cancelled by {cancelled_by}. Reason: {cancel_reason}.",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "calibration_cancelled",
            "channel": "inapp",
            "subject_template": "Calibration workflow cancelled — {equipment}",
            "body_template": "The calibration workflow for {equipment} has been cancelled. Reason: {cancel_reason}.",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "surveillance_cancelled",
            "channel": "email",
            "subject_template": "[SURVEILLANCE] Workflow Cancelled — {equipment}",
            "body_template": "<h3>Surveillance workflow cancelled</h3>"
                              "<p>The surveillance workflow for {equipment} has been cancelled.</p>"
                              "<p>Cancelled by: {cancelled_by}</p>"
                              "<p>Reason: {cancel_reason}</p>",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "surveillance_cancelled",
            "channel": "sms",
            "subject_template": "",
            "body_template": "Surveillance workflow for {equipment} was cancelled by {cancelled_by}. Reason: {cancel_reason}.",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": "surveillance_cancelled",
            "channel": "inapp",
            "subject_template": "Surveillance workflow cancelled — {equipment}",
            "body_template": "The surveillance workflow for {equipment} has been cancelled. Reason: {cancel_reason}.",
            "recipient_roles": ["Maintenance Officer", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
    ]

    added = 0
    for tpl in templates:
        existing = db.query(NotificationTemplate).filter(
            NotificationTemplate.event_type == tpl["event_type"],
            NotificationTemplate.channel == tpl["channel"],
            NotificationTemplate.organization_id.is_(None),
        ).first()

        if existing:
            print(f"[SKIP] {tpl['event_type']} / {tpl['channel']} already exists")
            continue

        db.add(NotificationTemplate(**tpl))
        added += 1
        print(f"[ADD] {tpl['event_type']} / {tpl['channel']}")

    db.commit()
    print(f"\n✅ Added {added} notification templates")


if __name__ == "__main__":
    add_templates()
