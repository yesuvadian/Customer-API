"""
Add request rejected notification event and default templates.
Run: python migration_request_rejected_notification_templates.py
"""

from database import get_db
from models import NotificationEventCatalogue, NotificationTemplate, RoleTemplate


def add_event_and_templates():
    db = next(get_db())

    event_type = "request_rejected"
    default_role_names = ["Originator", "Reviewing Officer"]
    roles = (
        db.query(RoleTemplate)
        .filter(RoleTemplate.name.in_(default_role_names))
        .all()
    )
    role_ids = [str(role.id) for role in roles]

    event = (
        db.query(NotificationEventCatalogue)
        .filter(
            NotificationEventCatalogue.event_type == event_type,
            NotificationEventCatalogue.organization_id.is_(None),
        )
        .first()
    )

    if event:
        event.label = "Request Rejected"
        event.group_name = "Testing Requests"
        event.description = "Fired when a testing request is rejected by an approver."
        event.context_vars = [
            "request.number",
            "request.title",
            "equipment.ueic",
            "rejected_by",
            "reason",
        ]
        event.default_roles = role_ids
        print(f"[UPDATE] NotificationEventCatalogue: {event_type}")
    else:
        db.add(NotificationEventCatalogue(
            event_type=event_type,
            label="Request Rejected",
            group_name="Testing Requests",
            description="Fired when a testing request is rejected by an approver.",
            context_vars=[
                "request.number",
                "request.title",
                "equipment.ueic",
                "rejected_by",
                "reason",
            ],
            default_roles=role_ids,
            is_active=True,
        ))
        print(f"[ADD] NotificationEventCatalogue: {event_type}")

    templates = [
        {
            "event_type": event_type,
            "channel": "email",
            "subject_template": "[KPTCL-SEACMS] Request Rejected — {request_number}",
            "body_template": (
                "<h3>Testing Request Rejected</h3>"
                "<p><b>Request:</b> {request_number}</p>"
                "<p><b>Equipment:</b> {equipment}</p>"
                "<p><b>Rejected by:</b> {rejected_by}</p>"
                "<p><b>Reason:</b> {reason}</p>"
                "<p>Please review the request and resubmit it in SEACMS.</p>"
            ),
            "recipient_roles": ["Originator", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": event_type,
            "channel": "sms",
            "subject_template": "",
            "body_template": (
                "Request {request_number} was rejected by {rejected_by}. Reason: {reason}."
            ),
            "recipient_roles": ["Originator"],
            "organization_id": None,
            "is_active": True,
        },
        {
            "event_type": event_type,
            "channel": "inapp",
            "subject_template": "Request rejected — {request_number}",
            "body_template": "Testing request {request_number} was rejected. Reason: {reason}.",
            "recipient_roles": ["Originator", "Reviewing Officer"],
            "organization_id": None,
            "is_active": True,
        },
    ]

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
        print(f"[ADD] {tpl['event_type']} / {tpl['channel']}" )

    db.commit()
    print("\n✅ Added request_rejected event and templates")


if __name__ == "__main__":
    add_event_and_templates()
