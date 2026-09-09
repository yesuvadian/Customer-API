#!/usr/bin/env python3
"""
One-time fix: create the missing eval_critical counterpart for every
org-specific eval_alert threshold-alert routing rule, and normalize both
rules' labels to show which severity they cover.

Root cause (see routers/notifications.py / services/notification_service.py):
an org admin configuring a "Threshold Alert" in the Notification Center picks
ONE severity (Alert Evaluation or Critical Evaluation) per rule - eval_alert
and eval_critical are saved as two entirely separate NotificationRoutingRule
rows with identical scope. Nothing in the UI or the generated label signals
that the other severity still needs its own rule, so an org that only ever
configured the Alert rule silently gets no notification at all for Critical
results routed through that same equipment/test-type scope - they fall back
to the global default rule, whose recipient roles (generic names like
"Reviewing Officer") typically don't exist in a KPTCL org's own role list,
so recipient resolution comes back empty.

This is data, not schema - it was fixed for the KPTCL org (Karnataka Power
Transmission Corporation Limited) directly against the dev database during
that investigation. This script makes the same fix reproducible in any other
environment: staging, a fresh database, or any other org that has the same
gap.

What it does, for every org-specific eval_alert rule:
  1. If no eval_critical rule exists for the same org with the same
     applicable_equipment_types + advanced_conditions scope, create one -
     cloning every scope/output column (channels, recipient override,
     follow-up action, per-channel template variants, priority, active flag).
  2. Normalize both rules' labels to end with "(Alert)" / "(Critical)" so the
     rule list and edit dialog show which severity each one covers (see
     lib/pages/organization/notification_center_page.dart's _save()).

Idempotent - safe to run more than once; already-fixed rules are left alone.

Usage:
    python backfill_eval_critical_alert_rules.py --dry-run   # report only
    python backfill_eval_critical_alert_rules.py              # apply
"""
import argparse
import copy

from database import VendorSessionLocal
from models import NotificationRoutingRule


def _label_with_severity(label: str | None, severity_word: str) -> str | None:
    """Append '(Alert)'/'(Critical)' unless the label already carries one."""
    if label is None:
        return None
    if "(Alert)" in label or "(Critical)" in label:
        return label
    return f"{label} ({severity_word})"


def run_fix(dry_run: bool):
    db = VendorSessionLocal()
    try:
        alert_rules = (
            db.query(NotificationRoutingRule)
            .filter(
                NotificationRoutingRule.event_type == "eval_alert",
                NotificationRoutingRule.organization_id.isnot(None),
            )
            .all()
        )

        created = []
        relabeled = []

        for alert_rule in alert_rules:
            # ── Normalize the alert rule's own label ───────────────────────
            new_label = _label_with_severity(alert_rule.label, "Alert")
            if new_label != alert_rule.label:
                relabeled.append((alert_rule.organization_id, alert_rule.label, new_label))
                if not dry_run:
                    alert_rule.label = new_label

            # ── Does a matching eval_critical rule already exist? ──────────
            existing_critical = (
                db.query(NotificationRoutingRule)
                .filter(
                    NotificationRoutingRule.event_type == "eval_critical",
                    NotificationRoutingRule.organization_id == alert_rule.organization_id,
                    NotificationRoutingRule.applicable_equipment_types
                        == alert_rule.applicable_equipment_types,
                    NotificationRoutingRule.advanced_conditions
                        == alert_rule.advanced_conditions,
                )
                .first()
            )

            if existing_critical:
                # Still normalize its label even if the rule itself is fine.
                new_c_label = _label_with_severity(existing_critical.label, "Critical")
                if new_c_label != existing_critical.label:
                    relabeled.append(
                        (existing_critical.organization_id, existing_critical.label, new_c_label)
                    )
                    if not dry_run:
                        existing_critical.label = new_c_label
                continue

            critical_label = _label_with_severity(
                (alert_rule.label or "").replace("(Alert)", "").strip() or alert_rule.label,
                "Critical",
            )
            created.append((alert_rule.organization_id, critical_label))

            if not dry_run:
                db.add(NotificationRoutingRule(
                    organization_id=alert_rule.organization_id,
                    event_type="eval_critical",
                    label=critical_label,
                    applicable_workflow_types=copy.deepcopy(alert_rule.applicable_workflow_types),
                    applicable_equipment_types=copy.deepcopy(alert_rule.applicable_equipment_types),
                    applicable_test_types=copy.deepcopy(alert_rule.applicable_test_types),
                    applicable_status_from=alert_rule.applicable_status_from,
                    applicable_status_to=alert_rule.applicable_status_to,
                    channels_enabled=copy.deepcopy(alert_rule.channels_enabled),
                    recipient_roles_override=copy.deepcopy(alert_rule.recipient_roles_override),
                    advanced_conditions=copy.deepcopy(alert_rule.advanced_conditions),
                    followup_action=copy.deepcopy(alert_rule.followup_action),
                    priority=alert_rule.priority,
                    email_template_id=alert_rule.email_template_id,
                    sms_template_id=alert_rule.sms_template_id,
                    inapp_template_id=alert_rule.inapp_template_id,
                    is_active=alert_rule.is_active,
                ))

        prefix = "[DRY RUN] " if dry_run else ""
        print(f"{prefix}eval_alert rules scanned: {len(alert_rules)}")
        print(f"{prefix}eval_critical rules to create: {len(created)}")
        for org_id, label in created:
            print(f"  org={org_id} | {label!r}")
        print(f"{prefix}labels to normalize: {len(relabeled)}")
        for org_id, old, new in relabeled:
            print(f"  org={org_id} | {old!r} -> {new!r}")

        if not dry_run:
            db.commit()
            print("Committed.")
        else:
            db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run_fix(dry_run=args.dry_run)
