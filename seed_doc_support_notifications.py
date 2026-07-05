"""
Seed notification templates for the Document Support Workflow.

Three event types:
  ds_wf_submitted       — fired when user submits a document request
                          Recipients: @originator (confirmation) + Dev Support Manager role
  ds_wf_status_changed  — fired on every stage transition
                          Recipients: @originator + @assignee + active stage roles
  ds_wf_originator_review — fired when request reaches originator review stage
                            Recipients: @originator (action required)

Context variables available in all DS WF templates:
  {{title}}          — document request title
  {{status_name}}    — human-readable status label
  {{stage_name}}     — current stage name
  {{action_code}}    — action that triggered the transition
  {{submitted_by}}   — name/email of submitter (populated by notification service)

All templates are global (organization_id=NULL) — apply to every org.
Idempotent: existing global templates for these events are replaced on re-run.
"""

import sys
sys.path.insert(0, ".")

from database import SessionLocal
from models import NotificationTemplate, NotificationRoutingRule

EVENT_SUBMITTED       = "ds_wf_submitted"
EVENT_STATUS_CHANGED  = "ds_wf_status_changed"
EVENT_ORIG_REVIEW     = "ds_wf_originator_review"

_TABLE_STYLE = (
    "border-collapse:collapse;font-size:13px;margin-bottom:16px;"
)
_CELL_LABEL = "padding:8px 0;color:#888;width:160px;"
_CELL_VALUE = "padding:8px 0;font-weight:600;color:#0F172A;"


def _row(label, var):
    return (
        f"<tr>"
        f"<td style='{_CELL_LABEL}'>{label}</td>"
        f"<td style='{_CELL_VALUE}'>{{{{{var}}}}}</td>"
        f"</tr>"
    )


ROUTING_RULES = [
    {
        "event_type": EVENT_SUBMITTED,
        "label": "Document Support — Request Submitted",
        "channels_enabled": ["email", "inapp"],
        "priority": 0,
        "is_active": True,
    },
    {
        "event_type": EVENT_STATUS_CHANGED,
        "label": "Document Support — Status Changed",
        "channels_enabled": ["email", "sms", "inapp"],
        "priority": 0,
        "is_active": True,
    },
    {
        "event_type": EVENT_ORIG_REVIEW,
        "label": "Document Support — Originator Review Required",
        "channels_enabled": ["email", "sms", "inapp"],
        "priority": 10,
        "is_active": True,
    },
]

TEMPLATES = [

    # ── ds_wf_submitted ────────────────────────────────────────────────────────

    {
        "event_type": EVENT_SUBMITTED,
        "channel": "inapp",
        "subject_template": "Document request received — {{title}}",
        "body_template": (
            "Your document request \"{{title}}\" has been submitted successfully. "
            "The Dev Support Manager will review and assign it shortly."
        ),
        "recipient_roles": ["@originator"],
    },
    {
        "event_type": EVENT_SUBMITTED,
        "channel": "inapp",
        "subject_template": "New document request: {{title}}",
        "body_template": (
            "A new document support request \"{{title}}\" has been submitted and is "
            "awaiting your review."
        ),
        "recipient_roles": ["Dev Support Manager"],
    },
    {
        "event_type": EVENT_SUBMITTED,
        "channel": "email",
        "subject_template": "Document Request Submitted — {{title}}",
        "body_template": (
            "<h2 style='color:#7C3AED;margin-bottom:4px;'>Document Request Received</h2>"
            "<p style='color:#555;margin-top:0;'>Your request has been submitted and will be reviewed shortly.</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='{_TABLE_STYLE}'>"
            + _row("Request Title", "title")
            + _row("Status", "status_name")
            + "</table>"
            "<p style='margin-top:20px;'>We will notify you when it has been assigned for processing.</p>"
        ),
        "recipient_roles": ["@originator"],
    },
    {
        "event_type": EVENT_SUBMITTED,
        "channel": "sms",
        "subject_template": "",
        "body_template": (
            "[SEACMS] New document request \"{{title}}\" submitted. "
            "Login to review."
        ),
        "recipient_roles": ["Dev Support Manager"],
    },

    # ── ds_wf_status_changed ───────────────────────────────────────────────────

    {
        "event_type": EVENT_STATUS_CHANGED,
        "channel": "inapp",
        "subject_template": "Document request — {{status_name}}",
        "body_template": (
            "Your document request \"{{title}}\" has moved to: {{status_name}}."
        ),
        "recipient_roles": ["@originator"],
    },
    {
        "event_type": EVENT_STATUS_CHANGED,
        "channel": "inapp",
        "subject_template": "Document request assigned — {{title}}",
        "body_template": (
            "A document support request \"{{title}}\" has been assigned to you. "
            "Current stage: {{stage_name}}."
        ),
        "recipient_roles": ["@assignee"],
    },
    {
        "event_type": EVENT_STATUS_CHANGED,
        "channel": "email",
        "subject_template": "Document Request Status Update — {{title}}",
        "body_template": (
            "<h2 style='color:#7C3AED;margin-bottom:4px;'>Document Request Status Update</h2>"
            "<p style='color:#555;margin-top:0;'>The status of your document support request has changed.</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='{_TABLE_STYLE}'>"
            + _row("Request Title", "title")
            + _row("New Status", "status_name")
            + _row("Stage", "stage_name")
            + "</table>"
            "<p style='margin-top:20px;'>Please log in to SEACMS to view the details or take any required action.</p>"
        ),
        "recipient_roles": ["@originator", "@assignee"],
    },
    {
        "event_type": EVENT_STATUS_CHANGED,
        "channel": "sms",
        "subject_template": "",
        "body_template": (
            "[SEACMS] Document request \"{{title}}\" status: {{status_name}}. "
            "Login for details."
        ),
        "recipient_roles": ["@originator", "@assignee"],
    },

    # ── ds_wf_originator_review ────────────────────────────────────────────────

    {
        "event_type": EVENT_ORIG_REVIEW,
        "channel": "inapp",
        "subject_template": "Action required — review your document request",
        "body_template": (
            "Your document request \"{{title}}\" has been processed and is ready for "
            "your review. Please accept or reject it."
        ),
        "recipient_roles": ["@originator"],
    },
    {
        "event_type": EVENT_ORIG_REVIEW,
        "channel": "email",
        "subject_template": "Action Required — Review Your Document Request",
        "body_template": (
            "<h2 style='color:#D97706;margin-bottom:4px;'>Your Review Required</h2>"
            "<p style='color:#555;margin-top:0;'>Your document request has been processed "
            "and is awaiting your acceptance.</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='{_TABLE_STYLE}'>"
            + _row("Request Title", "title")
            + _row("Status", "status_name")
            + "</table>"
            "<p>Please log in to <strong>SEACMS</strong> and <strong>Accept</strong> or "
            "<strong>Reject</strong> the processed result.</p>"
        ),
        "recipient_roles": ["@originator"],
    },
    {
        "event_type": EVENT_ORIG_REVIEW,
        "channel": "sms",
        "subject_template": "",
        "body_template": (
            "[SEACMS] Your document request \"{{title}}\" is ready for review. "
            "Accept or reject via SEACMS."
        ),
        "recipient_roles": ["@originator"],
    },
]


def seed_doc_support_notifications(session=None):
    own_session = session is None
    if own_session:
        session = SessionLocal()

    try:
        print("\n--- Doc Support Notification Templates ---")
        all_event_types = {EVENT_SUBMITTED, EVENT_STATUS_CHANGED, EVENT_ORIG_REVIEW}

        # Remove existing global templates for these events (idempotent)
        removed = 0
        for ev in all_event_types:
            rows = session.query(NotificationTemplate).filter(
                NotificationTemplate.event_type == ev,
                NotificationTemplate.organization_id.is_(None),
            ).all()
            for r in rows:
                session.delete(r)
                removed += 1
        if removed:
            session.flush()
            print(f"  Removed {removed} existing templates")

        # Insert new templates
        for tmpl in TEMPLATES:
            session.add(NotificationTemplate(
                event_type=tmpl["event_type"],
                channel=tmpl["channel"],
                subject_template=tmpl["subject_template"],
                body_template=tmpl["body_template"],
                recipient_roles=tmpl["recipient_roles"],
                organization_id=None,
                is_active=True,
                org_channel_disabled=False,
            ))

        # ── Routing Rules ──────────────────────────────────────────────────────
        print("\n--- Doc Support Notification Routing Rules ---")
        rules_removed = 0
        for ev in all_event_types:
            rows = session.query(NotificationRoutingRule).filter(
                NotificationRoutingRule.event_type == ev,
                NotificationRoutingRule.organization_id.is_(None),
            ).all()
            for r in rows:
                session.delete(r)
                rules_removed += 1
        if rules_removed:
            session.flush()
            print(f"  Removed {rules_removed} existing routing rules")

        for rule in ROUTING_RULES:
            session.add(NotificationRoutingRule(
                event_type=rule["event_type"],
                label=rule["label"],
                channels_enabled=rule["channels_enabled"],
                recipient_roles_override=None,
                applicable_workflow_types=[],
                applicable_equipment_types=[],
                organization_id=None,
                priority=rule["priority"],
                is_active=rule["is_active"],
            ))

        if own_session:
            session.commit()

        print(f"  Seeded {len(ROUTING_RULES)} routing rules:")
        for rule in ROUTING_RULES:
            print(f"    {rule['event_type']}: {rule['label']}")

        print(f"\n  Seeded {len(TEMPLATES)} templates for {len(all_event_types)} event types:")
        for ev in sorted(all_event_types):
            count = sum(1 for t in TEMPLATES if t["event_type"] == ev)
            print(f"    {ev}: {count} channels")

    except Exception as e:
        if own_session:
            session.rollback()
        print(f"  [ERROR] {e}")
        raise
    finally:
        if own_session:
            session.close()


if __name__ == "__main__":
    seed_doc_support_notifications()
