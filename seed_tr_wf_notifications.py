"""
Seed notification templates + routing rules for the TR Workflow Engine.

One event type fired by the engine:
  tr_wf_status_changed  — fired on every stage transition in the configurable
                          TR workflow (submitted -> L2 approval -> L3 assign ->
                          L4 test -> result review -> closed, etc.)
                          Recipients: @originator always + @assignee if set +
                          active stage role names (resolved at fire-time via
                          recipient_roles_override in the service call)

Context variables available in all TR WF templates:
  {{request_number}}  — TR request number
  {{equipment}}       — equipment UEIC or type name
  {{status_name}}     — human-readable destination status label
  {{stage_name}}      — destination stage name
  {{action_code}}     — action that triggered the transition
  {{originator}}      — full name of the request originator (from @originator token)

All templates are global (organization_id=NULL).
Idempotent: existing global templates/rules for tr_wf_* are replaced on re-run.
"""

import sys
sys.path.insert(0, ".")

from database import SessionLocal
from models import NotificationTemplate, NotificationRoutingRule

EVENT_STATUS_CHANGED = "tr_wf_status_changed"

_TABLE_STYLE = "border-collapse:collapse;font-size:13px;margin-bottom:16px;"
_CELL_LABEL  = "padding:8px 0;color:#888;width:160px;"
_CELL_VALUE  = "padding:8px 0;font-weight:600;color:#0F172A;"


def _row(label, var):
    return (
        f"<tr>"
        f"<td style='{_CELL_LABEL}'>{label}</td>"
        f"<td style='{_CELL_VALUE}'>{{{{{var}}}}}</td>"
        f"</tr>"
    )


TEMPLATES = [

    # ── tr_wf_status_changed — inapp (originator) ──────────────────────────────
    {
        "event_type": EVENT_STATUS_CHANGED,
        "channel": "inapp",
        "subject_template": "Test request {{request_number}} — {{status_name}}",
        "body_template": (
            "Your test request {{request_number}} for {{equipment}} has moved to: "
            "{{status_name}} ({{stage_name}})."
        ),
        "recipient_roles": ["@originator"],
    },

    # ── tr_wf_status_changed — inapp (assignee / stage roles) ─────────────────
    {
        "event_type": EVENT_STATUS_CHANGED,
        "channel": "inapp",
        "subject_template": "Action required — {{request_number}} reached {{stage_name}}",
        "body_template": (
            "Test request {{request_number}} ({{equipment}}) has been routed to your "
            "stage: {{stage_name}}. Current status: {{status_name}}."
        ),
        "recipient_roles": ["@assignee"],
    },

    # ── tr_wf_status_changed — email ───────────────────────────────────────────
    {
        "event_type": EVENT_STATUS_CHANGED,
        "channel": "email",
        "subject_template": "Test Request Status Update — {{request_number}}",
        "body_template": (
            "<h2 style='color:#3FA9F5;margin-bottom:4px;'>Test Request Status Update</h2>"
            "<p style='color:#555;margin-top:0;'>The status of your test request has changed.</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='{_TABLE_STYLE}'>"
            + _row("Request No.", "request_number")
            + _row("Equipment", "equipment")
            + _row("New Status", "status_name")
            + _row("Stage", "stage_name")
            + "</table>"
            "<p style='margin-top:20px;'>Please log in to <strong>SEACMS</strong> to "
            "view the request details or take any required action.</p>"
        ),
        "recipient_roles": ["@originator", "@assignee"],
    },

    # ── tr_wf_status_changed — sms ────────────────────────────────────────────
    {
        "event_type": EVENT_STATUS_CHANGED,
        "channel": "sms",
        "subject_template": "",
        "body_template": (
            "[SEACMS] Test request {{request_number}} ({{equipment}}) status: "
            "{{status_name}}. Login for details."
        ),
        "recipient_roles": ["@originator", "@assignee"],
    },
]

ROUTING_RULES = [
    {
        "event_type": EVENT_STATUS_CHANGED,
        "label": "TR Workflow — Status Changed",
        "channels_enabled": ["inapp"],
        "priority": 0,
        "is_active": True,
    },
]

ALL_EVENTS = {EVENT_STATUS_CHANGED}


def seed_tr_wf_notifications(session=None):
    own_session = session is None
    if own_session:
        session = SessionLocal()

    try:
        print("\n--- TR Workflow Notification Templates ---")

        # Remove existing global templates for these events
        removed = 0
        for ev in ALL_EVENTS:
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

        print(f"  Seeded {len(TEMPLATES)} templates for {len(ALL_EVENTS)} event type(s):")
        for ev in sorted(ALL_EVENTS):
            count = sum(1 for t in TEMPLATES if t["event_type"] == ev)
            print(f"    {ev}: {count} channels")

        # ── Routing Rules ──────────────────────────────────────────────────────
        print("\n--- TR Workflow Notification Routing Rules ---")
        rules_removed = 0
        for ev in ALL_EVENTS:
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

        print(f"  Seeded {len(ROUTING_RULES)} routing rule(s):")
        for rule in ROUTING_RULES:
            print(f"    {rule['event_type']}: {rule['label']}")

    except Exception as e:
        if own_session:
            session.rollback()
        print(f"  [ERROR] {e}")
        raise
    finally:
        if own_session:
            session.close()


if __name__ == "__main__":
    seed_tr_wf_notifications()
