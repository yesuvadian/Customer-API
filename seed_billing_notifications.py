"""
Seed billing notification event catalogue entries, templates, and routing rules.

Event types:
  billing_renewal_reminder   — 7 / 3 / 1 days before a dept subscription expires
  billing_subscription_expired — dept subscription has just expired
  billing_anomaly_nag         — unresolved payment anomalies exist (super-admin)
  billing_payment_confirmed   — dept or org payment successfully processed
  billing_mode_switched       — org switched between org-level / dept-level billing

Context variables:
  {{dept_name}}       — department name
  {{org_name}}        — organisation name
  {{days_remaining}}  — days until expiry (renewal_reminder only)
  {{count}}           — anomaly count (anomaly_nag only)

All templates and rules are global (organization_id=NULL).
Idempotent: existing global entries are replaced on re-run.
"""

import sys
sys.path.insert(0, ".")

from database import SessionLocal
from models import NotificationEventCatalogue, NotificationTemplate, NotificationRoutingRule

# ── Event catalogue entries ────────────────────────────────────────────────────

_CATALOGUE = [
    {
        "event_type": "billing_renewal_reminder",
        "label": "Billing Renewal Reminder",
        "group_name": "Billing",
        "description": "Sent to org admins when a department subscription is about to expire (7, 3, or 1 day before).",
        "context_vars": ["dept_name", "org_name", "days_remaining"],
        "default_roles": [],
    },
    {
        "event_type": "billing_subscription_expired",
        "label": "Subscription Expired",
        "group_name": "Billing",
        "description": "Sent to org admins when a department subscription has expired.",
        "context_vars": ["dept_name", "org_name"],
        "default_roles": [],
    },
    {
        "event_type": "billing_anomaly_nag",
        "label": "Billing Anomaly Alert",
        "group_name": "Billing",
        "description": "Sent to super-admins when billing payment anomalies remain unresolved for more than 24 hours.",
        "context_vars": ["count"],
        "default_roles": [],
    },
    {
        "event_type": "billing_payment_confirmed",
        "label": "Payment Confirmed",
        "group_name": "Billing",
        "description": "Sent to org admins when a department or org-level payment is successfully processed.",
        "context_vars": ["dept_name", "org_name", "plan_name", "amount"],
        "default_roles": [],
    },
    {
        "event_type": "billing_mode_switched",
        "label": "Billing Mode Switched",
        "group_name": "Billing",
        "description": "Sent to org admins when the billing scope is changed between org-level and department-level.",
        "context_vars": ["org_name", "new_scope"],
        "default_roles": [],
    },
]

# ── Templates ──────────────────────────────────────────────────────────────────

_CELL_LABEL = "padding:8px 0;color:#888;width:160px;font-size:13px;"
_CELL_VALUE = "padding:8px 0;font-weight:600;color:#0F172A;font-size:13px;"
_TABLE_STYLE = "border-collapse:collapse;width:100%;margin-bottom:16px;"


def _row(label, var):
    return (
        f"<tr>"
        f"<td style='{_CELL_LABEL}'>{label}</td>"
        f"<td style='{_CELL_VALUE}'>{{{{{var}}}}}</td>"
        f"</tr>"
    )


TEMPLATES = [

    # ── billing_renewal_reminder ─────────────────────────────────────────────────

    {
        "event_type": "billing_renewal_reminder",
        "channel": "inapp",
        "subject_template": "Billing Renewal Reminder — {{dept_name}}",
        "body_template": (
            "The subscription for department '{{dept_name}}' expires in "
            "{{days_remaining}} day(s). Please renew to avoid service interruption."
        ),
        "recipient_roles": [],
    },
    {
        "event_type": "billing_renewal_reminder",
        "channel": "email",
        "subject_template": "[{{org_name}}] Billing Renewal Reminder — {{dept_name}}",
        "body_template": (
            "<h2 style='color:#F59E0B;margin-bottom:4px;'>Subscription Renewal Reminder</h2>"
            "<p style='color:#555;margin-top:0;'>Action required: the following department's "
            "subscription is expiring soon.</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='{_TABLE_STYLE}'>"
            + _row("Organisation", "org_name")
            + _row("Department", "dept_name")
            + _row("Days Remaining", "days_remaining")
            + "</table>"
            "<p style='margin-top:20px;'>Please log in to <strong>CogniWatt</strong> and "
            "renew the subscription before it expires to prevent service interruption for "
            "users in this department.</p>"
        ),
        "recipient_roles": [],
    },
    {
        "event_type": "billing_renewal_reminder",
        "channel": "sms",
        "subject_template": "",
        "body_template": (
            "[CogniWatt] REMINDER: Subscription for {{dept_name}} ({{org_name}}) "
            "expires in {{days_remaining}} day(s). Renew now to avoid disruption."
        ),
        "recipient_roles": [],
    },

    # ── billing_subscription_expired ─────────────────────────────────────────────

    {
        "event_type": "billing_subscription_expired",
        "channel": "inapp",
        "subject_template": "Subscription Expired — {{dept_name}}",
        "body_template": (
            "The subscription for department '{{dept_name}}' has expired. "
            "Users in this department cannot log in. Please renew immediately."
        ),
        "recipient_roles": [],
    },
    {
        "event_type": "billing_subscription_expired",
        "channel": "email",
        "subject_template": "[{{org_name}}] URGENT: Subscription Expired — {{dept_name}}",
        "body_template": (
            "<h2 style='color:#DC2626;margin-bottom:4px;'>Subscription Expired</h2>"
            "<p style='color:#555;margin-top:0;'>The subscription for the following "
            "department has expired. Users are currently blocked from logging in.</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='{_TABLE_STYLE}'>"
            + _row("Organisation", "org_name")
            + _row("Department", "dept_name")
            + "</table>"
            "<p style='margin-top:20px;color:#DC2626;font-weight:600;'>"
            "Immediate action required.</p>"
            "<p>Please log in to <strong>CogniWatt</strong> and complete the payment "
            "to restore access for department users.</p>"
        ),
        "recipient_roles": [],
    },
    {
        "event_type": "billing_subscription_expired",
        "channel": "sms",
        "subject_template": "",
        "body_template": (
            "[CogniWatt] URGENT: Subscription for {{dept_name}} ({{org_name}}) has "
            "EXPIRED. Users cannot log in. Renew immediately."
        ),
        "recipient_roles": [],
    },

    # ── billing_anomaly_nag ───────────────────────────────────────────────────────

    {
        "event_type": "billing_anomaly_nag",
        "channel": "inapp",
        "subject_template": "Unresolved Billing Anomalies ({{count}})",
        "body_template": (
            "There are {{count}} unresolved billing anomalies requiring attention. "
            "Please review and resolve them in the admin billing panel."
        ),
        "recipient_roles": [],
    },
    {
        "event_type": "billing_anomaly_nag",
        "channel": "email",
        "subject_template": "[CogniWatt Admin] {{count}} Unresolved Billing Anomaly(ies)",
        "body_template": (
            "<h2 style='color:#7C3AED;margin-bottom:4px;'>Unresolved Billing Anomalies</h2>"
            "<p style='color:#555;margin-top:0;'>"
            "The following billing anomalies are awaiting resolution:</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='{_TABLE_STYLE}'>"
            + _row("Pending Anomalies", "count")
            + "</table>"
            "<p>Please log in to the <strong>CogniWatt Super Admin panel</strong> and "
            "resolve all outstanding anomalies to ensure accurate billing records.</p>"
        ),
        "recipient_roles": [],
    },

    # ── billing_payment_confirmed ─────────────────────────────────────────────────

    {
        "event_type": "billing_payment_confirmed",
        "channel": "inapp",
        "subject_template": "Payment Confirmed — {{dept_name or org_name}}",
        "body_template": (
            "Payment for {{plan_name}} ({{amount}}) has been confirmed. "
            "Subscription is now active."
        ),
        "recipient_roles": [],
    },
    {
        "event_type": "billing_payment_confirmed",
        "channel": "email",
        "subject_template": "[{{org_name}}] Payment Confirmed — {{plan_name}}",
        "body_template": (
            "<h2 style='color:#16A34A;margin-bottom:4px;'>Payment Confirmed</h2>"
            "<p style='color:#555;margin-top:0;'>Your subscription payment has been "
            "successfully processed.</p>"
            f"<table width='100%' cellpadding='0' cellspacing='0' style='{_TABLE_STYLE}'>"
            + _row("Organisation", "org_name")
            + _row("Department", "dept_name")
            + _row("Plan", "plan_name")
            + _row("Amount", "amount")
            + "</table>"
            "<p style='margin-top:20px;color:#16A34A;font-weight:600;'>"
            "Your subscription is now active.</p>"
        ),
        "recipient_roles": [],
    },

    # ── billing_mode_switched ─────────────────────────────────────────────────────

    {
        "event_type": "billing_mode_switched",
        "channel": "inapp",
        "subject_template": "Billing Mode Changed — {{org_name}}",
        "body_template": (
            "The billing mode for {{org_name}} has been switched to {{new_scope}}."
        ),
        "recipient_roles": [],
    },
]

# ── Routing rules ──────────────────────────────────────────────────────────────

ROUTING_RULES = [
    {
        "event_type": "billing_renewal_reminder",
        "label": "Billing — Renewal Reminder",
        "channels_enabled": ["inapp", "email"],
        "priority": 0,
    },
    {
        "event_type": "billing_subscription_expired",
        "label": "Billing — Subscription Expired",
        "channels_enabled": ["inapp", "email"],
        "priority": 0,
    },
    {
        "event_type": "billing_anomaly_nag",
        "label": "Billing — Anomaly Alert (Admin)",
        "channels_enabled": ["inapp"],
        "priority": 0,
    },
    {
        "event_type": "billing_payment_confirmed",
        "label": "Billing — Payment Confirmed",
        "channels_enabled": ["inapp", "email"],
        "priority": 0,
    },
    {
        "event_type": "billing_mode_switched",
        "label": "Billing — Mode Switched",
        "channels_enabled": ["inapp"],
        "priority": 0,
    },
]

ALL_EVENTS = {e["event_type"] for e in _CATALOGUE}


def seed_billing_notifications(session=None):
    own_session = session is None
    if own_session:
        session = SessionLocal()

    try:
        print("\n--- Billing Notification Event Catalogue ---")
        for entry in _CATALOGUE:
            existing = session.query(NotificationEventCatalogue).filter(
                NotificationEventCatalogue.event_type == entry["event_type"],
                NotificationEventCatalogue.organization_id.is_(None),
            ).first()
            if existing:
                existing.label = entry["label"]
                existing.group_name = entry["group_name"]
                existing.description = entry["description"]
                existing.context_vars = entry["context_vars"]
                existing.default_roles = entry["default_roles"]
                existing.is_active = True
                print(f"  Updated: {entry['event_type']}")
            else:
                session.add(NotificationEventCatalogue(
                    event_type=entry["event_type"],
                    label=entry["label"],
                    group_name=entry["group_name"],
                    description=entry["description"],
                    context_vars=entry["context_vars"],
                    default_roles=entry["default_roles"],
                    organization_id=None,
                    is_active=True,
                ))
                print(f"  Inserted: {entry['event_type']}")

        print("\n--- Billing Notification Templates ---")
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
        print(f"  Seeded {len(TEMPLATES)} templates")

        print("\n--- Billing Notification Routing Rules ---")
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
                applicable_test_types=[],
                applicable_status_from=None,
                applicable_status_to=None,
                priority=rule["priority"],
                organization_id=None,
                is_active=True,
            ))
        print(f"  Seeded {len(ROUTING_RULES)} routing rules")

        session.commit()
        print("\n✓ Billing notification seed complete.")

    except Exception as e:
        session.rollback()
        print(f"\n✗ Seed failed: {e}")
        raise
    finally:
        if own_session:
            session.close()


if __name__ == "__main__":
    seed_billing_notifications()
