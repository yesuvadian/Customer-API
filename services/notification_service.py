"""
Notification & Alert Engine
============================
Central service that resolves recipients by role, renders templates, and
dispatches via email / SMS / in-app channels.

Key design points
-----------------
* Role-driven: NotificationTemplate.recipient_roles lists OrgRole names.
  The service resolves every active OrgUserRole member with that role name
  in the same organisation and sends to their User.email.
* Channels: email (SMTP / Office 365 STARTTLS), sms (placeholder), inapp (DB row).
* Digest: if >10 same event_type rows appear within 5 min, they are batched
  into a single message and the individual rows are marked "digested".
* Retry: up to 3 attempts, 5 min apart. Runs via APScheduler (every 5 min).
* All activity is logged to notification_log for audit purposes.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, func as sa_func
from sqlalchemy.orm import Session

from models import (
    NotificationLog,
    NotificationTemplate,
    OrgRole,
    OrgUserRole,
    User,
    UserNotification,
)
from utils.email_service import EmailService

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

DIGEST_THRESHOLD = 10       # batch if >10 same-type alerts within DIGEST_WINDOW
DIGEST_WINDOW_MINUTES = 5
MAX_RETRIES = 3
RETRY_DELAY_MINUTES = 5


# ── Template rendering ────────────────────────────────────────────────────────

def _render(template: str, context: Dict[str, Any]) -> str:
    """Safe str.format_map rendering; unknown keys left as-is."""
    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"
    try:
        return template.format_map(SafeDict(context))
    except Exception:
        return template


# ── Recipient resolution ──────────────────────────────────────────────────────

def _resolve_recipients_by_roles(
    db: Session,
    role_names: List[str],
    organization_id: Optional[UUID],
) -> List[User]:
    """
    Return unique active User objects that hold any of the given OrgRole names
    within the given organisation.
    """
    if not role_names or not organization_id:
        return []

    rows = (
        db.query(OrgUserRole)
        .join(OrgRole, OrgUserRole.org_role_id == OrgRole.id)
        .join(User, OrgUserRole.user_id == User.id)
        .filter(
            OrgRole.organization_id == organization_id,
            OrgRole.name.in_(role_names),
            OrgRole.is_active.is_(True),
            OrgUserRole.is_active.is_(True),
        )
        .all()
    )

    seen: set = set()
    users: List[User] = []
    for row in rows:
        if row.user_id not in seen:
            seen.add(row.user_id)
            users.append(row.user)
    return users


# ── Channel dispatchers ───────────────────────────────────────────────────────

def _send_email(
    db: Session,
    log: NotificationLog,
    to_email: str,
    subject: str,
    body: str,
) -> None:
    try:
        EmailService().send_email_starttls(to_email, subject, body)
        log.status = "sent"
        log.sent_at = datetime.now(timezone.utc)
        log.error_message = None
    except Exception as exc:
        log.status = "failed"
        log.error_message = str(exc)[:500]
        log.retry_count += 1
        if log.retry_count < log.max_retries:
            log.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=RETRY_DELAY_MINUTES)
        logger.warning(f"[Notif] Email to {to_email} failed: {exc}")


def _send_sms(
    db: Session,
    log: NotificationLog,
    phone: str,
    body: str,
) -> None:
    """SMS channel — placeholder for REST gateway integration."""
    # TODO: Replace with real SMS gateway (e.g. Twilio, AWS SNS, Infobip)
    # Example stub:
    #   import requests
    #   resp = requests.post(SMS_GATEWAY_URL, json={"to": phone, "body": body}, ...)
    #   if resp.ok: log.status = "sent" else: log.status = "failed"
    logger.info(f"[Notif] SMS placeholder — would send to {phone}: {body[:80]}...")
    log.status = "skipped"   # change to "sent"/"failed" when gateway is wired
    log.sent_at = datetime.now(timezone.utc)


def _create_inapp(
    db: Session,
    user_id: UUID,
    organization_id: Optional[UUID],
    event_type: str,
    title: str,
    body: str,
    severity: Optional[str],
    source_id: Optional[UUID],
    source_type: Optional[str],
) -> UserNotification:
    notif = UserNotification(
        user_id=user_id,
        organization_id=organization_id,
        event_type=event_type,
        title=title,
        body=body,
        severity=severity,
        source_id=source_id,
        source_type=source_type,
    )
    db.add(notif)
    return notif


# ── Digest detection ──────────────────────────────────────────────────────────

def _should_digest(db: Session, event_type: str, organization_id: Optional[UUID]) -> bool:
    """Return True if there are >DIGEST_THRESHOLD pending logs for this event_type in the last window."""
    window_start = datetime.now(timezone.utc) - timedelta(minutes=DIGEST_WINDOW_MINUTES)
    count = (
        db.query(sa_func.count(NotificationLog.id))
        .filter(
            NotificationLog.event_type == event_type,
            NotificationLog.organization_id == organization_id,
            NotificationLog.status == "pending",
            NotificationLog.cts >= window_start,
        )
        .scalar()
    ) or 0
    return count >= DIGEST_THRESHOLD


def _collapse_digest(db: Session, event_type: str, organization_id: Optional[UUID]) -> None:
    """Mark pending logs in window as digested and send a single digest email per unique recipient."""
    window_start = datetime.now(timezone.utc) - timedelta(minutes=DIGEST_WINDOW_MINUTES)
    pending = (
        db.query(NotificationLog)
        .filter(
            NotificationLog.event_type == event_type,
            NotificationLog.organization_id == organization_id,
            NotificationLog.status == "pending",
            NotificationLog.cts >= window_start,
        )
        .all()
    )

    by_recipient: Dict[str, List[NotificationLog]] = {}
    for log in pending:
        key = log.recipient_email or str(log.recipient_id or "unknown")
        by_recipient.setdefault(key, []).append(log)

    for email, logs in by_recipient.items():
        # Send a single digest
        subjects = [l.subject or "" for l in logs]
        digest_body = (
            f"<h3>Digest: {len(logs)} {event_type.replace('_', ' ').title()} alerts</h3><ul>"
            + "".join(f"<li>{l.body or ''}</li>" for l in logs[:20])
            + ("</ul><p>…and more</p>" if len(logs) > 20 else "</ul>")
        )
        digest_subject = f"[Digest] {len(logs)} × {event_type.replace('_', ' ').title()}"
        try:
            EmailService().send_email_starttls(email, digest_subject, digest_body)
        except Exception as exc:
            logger.warning(f"[Notif] Digest email to {email} failed: {exc}")

        for log in logs:
            log.status = "digested"
            log.sent_at = datetime.now(timezone.utc)

    db.commit()


# ── Core dispatch ─────────────────────────────────────────────────────────────

class NotificationService:
    """
    Main entry-point used by all trigger hooks.

    Usage
    -----
    svc = NotificationService(db)
    svc.fire(
        event_type="eval_critical",
        context={"equipment": "TX-001", "result": "CRITICAL — IR < 50 MΩ"},
        organization_id=req.organization_id,
        source_id=result.id,
        source_type="test_result",
        severity="critical",
        # optionally override recipients:
        extra_recipients=[user_obj],
    )
    """

    def __init__(self, db: Session):
        self.db = db

    # ── Public API ────────────────────────────────────────────────────────────

    def fire(
        self,
        event_type: str,
        context: Dict[str, Any],
        organization_id: Optional[UUID] = None,
        source_id: Optional[UUID] = None,
        source_type: Optional[str] = None,
        severity: Optional[str] = None,
        extra_recipients: Optional[List[User]] = None,
    ) -> None:
        """
        Resolve templates for event_type, resolve recipients by role, and
        dispatch via all configured channels.  Never raises — all errors are
        logged.
        """
        try:
            templates = self._get_templates(event_type, organization_id)
            if not templates:
                logger.debug(f"[Notif] No active templates for event_type={event_type!r}")
                return

            for tmpl in templates:
                subject = _render(tmpl.subject_template or "", context)
                body = _render(tmpl.body_template, context)

                recipients = _resolve_recipients_by_roles(
                    self.db,
                    list(tmpl.recipient_roles or []),
                    organization_id,
                )
                if extra_recipients:
                    seen_ids = {u.id for u in recipients}
                    for u in extra_recipients:
                        if u.id not in seen_ids:
                            recipients.append(u)
                            seen_ids.add(u.id)

                if not recipients:
                    logger.debug(
                        f"[Notif] event={event_type!r} template={tmpl.id}: "
                        f"no recipients resolved for roles {tmpl.recipient_roles}"
                    )
                    continue

                for user in recipients:
                    self._dispatch_to_user(
                        tmpl=tmpl,
                        user=user,
                        subject=subject,
                        body=body,
                        event_type=event_type,
                        organization_id=organization_id,
                        source_id=source_id,
                        source_type=source_type,
                        severity=severity,
                    )

        except Exception as exc:
            logger.error(f"[Notif] fire() failed for event_type={event_type!r}: {exc}")
            traceback.print_exc()

    def retry_failed(self) -> int:
        """
        Retry all NotificationLog rows in status='failed' with retry_count < max_retries
        whose next_retry_at <= now.  Called by APScheduler every 5 min.
        Returns number of rows retried.
        """
        now = datetime.now(timezone.utc)
        due = (
            self.db.query(NotificationLog)
            .filter(
                NotificationLog.status == "failed",
                NotificationLog.retry_count < NotificationLog.max_retries,
                and_(
                    NotificationLog.next_retry_at.isnot(None),
                    NotificationLog.next_retry_at <= now,
                ),
            )
            .all()
        )

        count = 0
        for log in due:
            if log.channel == "email" and log.recipient_email:
                _send_email(self.db, log, log.recipient_email, log.subject or "", log.body or "")
                count += 1
            elif log.channel == "sms" and log.recipient_phone:
                _send_sms(self.db, log, log.recipient_phone, log.body or "")
                count += 1

        if count:
            self.db.commit()
        return count

    # ── Convenience trigger methods ───────────────────────────────────────────

    def notify_eval_critical(self, request, result, evaluation_result: dict) -> None:
        """Triggered when evaluation_result.overall == CRITICAL."""
        from services.evaluation_service import EvaluationService
        summary = EvaluationService.build_remedial_summary(evaluation_result, getattr(request, "title", "") or "")
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        self.fire(
            event_type="eval_critical",
            context={
                "equipment": equipment_label,
                "request_number": getattr(request, "request_number", ""),
                "result_summary": summary or "Critical threshold exceeded",
                "test_name": result.test_name or result.template_key or "",
                "tested_by": str(result.tested_by or ""),
                "tested_at": str(result.tested_at or ""),
            },
            organization_id=getattr(request, "organization_id", None),
            source_id=result.id,
            source_type="test_result",
            severity="critical",
        )

    def notify_eval_alert(self, request, result, evaluation_result: dict) -> None:
        """Triggered when evaluation_result.overall == ALERT."""
        from services.evaluation_service import EvaluationService
        revised = EvaluationService.get_min_revised_interval(evaluation_result)
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        self.fire(
            event_type="eval_alert",
            context={
                "equipment": equipment_label,
                "request_number": getattr(request, "request_number", ""),
                "test_name": result.test_name or result.template_key or "",
                "revised_interval": str(revised) + " days" if revised else "see report",
            },
            organization_id=getattr(request, "organization_id", None),
            source_id=result.id,
            source_type="test_result",
            severity="alert",
        )

    def notify_request_submitted(self, request) -> None:
        """Triggered when originator submits testing request."""
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        self.fire(
            event_type="request_submitted",
            context={
                "equipment": equipment_label,
                "request_number": getattr(request, "request_number", ""),
                "originator": request.originator.email if request.originator else "",
                "category": getattr(request, "request_category", "test"),
            },
            organization_id=getattr(request, "organization_id", None),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
        )

    def notify_tester_assigned(self, request) -> None:
        """Triggered when tester is assigned to a testing request."""
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        self.fire(
            event_type="tester_assigned",
            context={
                "equipment": equipment_label,
                "request_number": getattr(request, "request_number", ""),
                "tester": request.assigned_tester.email if request.assigned_tester else "",
            },
            organization_id=getattr(request, "organization_id", None),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
        )

    def notify_test_submitted(self, request) -> None:
        """Triggered when tester submits test results."""
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        self.fire(
            event_type="test_submitted",
            context={
                "equipment": equipment_label,
                "request_number": getattr(request, "request_number", ""),
            },
            organization_id=getattr(request, "organization_id", None),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
        )

    def notify_recommendation_approved(self, request, recommendation) -> None:
        """Triggered when a recommendation with replacement_products is approved."""
        self.fire(
            event_type="recommendation_approved",
            context={
                "request_number": getattr(request, "request_number", ""),
                "recommendation_type": recommendation.recommendation_type.value
                    if hasattr(recommendation.recommendation_type, "value")
                    else str(recommendation.recommendation_type),
                "product_count": len(recommendation.replacement_products or []),
            },
            organization_id=getattr(request, "organization_id", None),
            source_id=recommendation.id,
            source_type="recommendation",
            severity="info",
        )

    def notify_due_reminder(self, request) -> None:
        """Triggered by scheduler when next_run_date is approaching."""
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        self.fire(
            event_type="due_reminder",
            context={
                "equipment": equipment_label,
                "request_number": getattr(request, "request_number", ""),
                "due_date": str(getattr(request, "due_date", "") or ""),
            },
            organization_id=getattr(request, "organization_id", None),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
        )

    def notify_overdue(self, request) -> None:
        """Triggered by scheduler when due_date has passed and request is still open."""
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        self.fire(
            event_type="overdue_alert",
            context={
                "equipment": equipment_label,
                "request_number": getattr(request, "request_number", ""),
                "due_date": str(getattr(request, "due_date", "") or ""),
            },
            organization_id=getattr(request, "organization_id", None),
            source_id=request.id,
            source_type="testing_request",
            severity="alert",
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_templates(
        self, event_type: str, organization_id: Optional[UUID]
    ) -> List[NotificationTemplate]:
        """
        Prefer org-specific template; fall back to global (organization_id IS NULL).
        Returns one template per channel.
        """
        rows: List[NotificationTemplate] = []

        if organization_id:
            rows = (
                self.db.query(NotificationTemplate)
                .filter(
                    NotificationTemplate.event_type == event_type,
                    NotificationTemplate.organization_id == organization_id,
                    NotificationTemplate.is_active.is_(True),
                )
                .all()
            )

        if not rows:
            rows = (
                self.db.query(NotificationTemplate)
                .filter(
                    NotificationTemplate.event_type == event_type,
                    NotificationTemplate.organization_id.is_(None),
                    NotificationTemplate.is_active.is_(True),
                )
                .all()
            )
        return rows

    def _dispatch_to_user(
        self,
        tmpl: NotificationTemplate,
        user: User,
        subject: str,
        body: str,
        event_type: str,
        organization_id: Optional[UUID],
        source_id: Optional[UUID],
        source_type: Optional[str],
        severity: Optional[str],
    ) -> None:
        log = NotificationLog(
            organization_id=organization_id,
            event_type=event_type,
            channel=tmpl.channel,
            recipient_id=user.id,
            recipient_email=user.email if tmpl.channel == "email" else None,
            subject=subject,
            body=body,
            status="pending",
            source_id=source_id,
            source_type=source_type,
        )
        self.db.add(log)
        self.db.flush()  # get log.id

        if tmpl.channel == "email":
            # Digest check
            if _should_digest(self.db, event_type, organization_id):
                _collapse_digest(self.db, event_type, organization_id)
                return
            if not user.email:
                log.status = "skipped"
                log.error_message = "User has no email"
                self.db.commit()
                return
            _send_email(self.db, log, user.email, subject, body)

        elif tmpl.channel == "sms":
            phone = getattr(user, "phone", None) or getattr(user, "mobile", None)
            if phone:
                _send_sms(self.db, log, phone, body)
            else:
                log.status = "skipped"
                log.error_message = "User has no phone number"

        elif tmpl.channel == "inapp":
            _create_inapp(
                db=self.db,
                user_id=user.id,
                organization_id=organization_id,
                event_type=event_type,
                title=subject or event_type.replace("_", " ").title(),
                body=body,
                severity=severity,
                source_id=source_id,
                source_type=source_type,
            )
            log.status = "sent"
            log.sent_at = datetime.now(timezone.utc)

        try:
            self.db.commit()
        except Exception as exc:
            logger.error(f"[Notif] DB commit failed after dispatch: {exc}")
            self.db.rollback()


# ── Global default template seeds ─────────────────────────────────────────────

DEFAULT_TEMPLATES = [
    # ── eval_critical ────────────────────────────────────────────────────────
    {
        "event_type": "eval_critical",
        "channel": "email",
        "subject_template": "[CRITICAL] {equipment} — Test Alert",
        "body_template": (
            "<h3 style='color:red'>⚠️ Critical Test Result</h3>"
            "<p><b>Equipment:</b> {equipment}</p>"
            "<p><b>Request:</b> {request_number}</p>"
            "<p><b>Test:</b> {test_name}</p>"
            "<p><b>Finding:</b> {result_summary}</p>"
            "<p>Please review and take immediate action.</p>"
        ),
        "recipient_roles": ["Department Head", "Approver", "Originator"],
    },
    {
        "event_type": "eval_critical",
        "channel": "inapp",
        "subject_template": "⚠️ CRITICAL — {equipment}",
        "body_template": "{result_summary}",
        "recipient_roles": ["Department Head", "Approver", "Originator"],
    },
    # ── eval_alert ───────────────────────────────────────────────────────────
    {
        "event_type": "eval_alert",
        "channel": "email",
        "subject_template": "[ALERT] {equipment} — Threshold Warning",
        "body_template": (
            "<h3 style='color:orange'>⚡ Alert: Threshold Warning</h3>"
            "<p><b>Equipment:</b> {equipment}</p>"
            "<p><b>Request:</b> {request_number}</p>"
            "<p><b>Test:</b> {test_name}</p>"
            "<p><b>Revised inspection interval:</b> {revised_interval}</p>"
        ),
        "recipient_roles": ["Department Head", "Originator"],
    },
    {
        "event_type": "eval_alert",
        "channel": "inapp",
        "subject_template": "⚡ Alert — {equipment}",
        "body_template": "Threshold warning on {test_name}. Revised interval: {revised_interval}.",
        "recipient_roles": ["Department Head", "Originator"],
    },
    # ── test_submitted ───────────────────────────────────────────────────────
    {
        "event_type": "test_submitted",
        "channel": "email",
        "subject_template": "Test Results Submitted — {equipment}",
        "body_template": (
            "<h3>Test Results Ready for Review</h3>"
            "<p>Tester has submitted results for <b>{equipment}</b> "
            "(Request: {request_number}).</p>"
            "<p>Please log in to review and approve.</p>"
        ),
        "recipient_roles": ["Approver", "Department Head"],
    },
    {
        "event_type": "test_submitted",
        "channel": "inapp",
        "subject_template": "Results submitted — {equipment}",
        "body_template": "Test results for {equipment} (Req: {request_number}) await your review.",
        "recipient_roles": ["Approver", "Department Head"],
    },
    # ── due_reminder ─────────────────────────────────────────────────────────
    {
        "event_type": "due_reminder",
        "channel": "email",
        "subject_template": "Upcoming Test Due — {equipment}",
        "body_template": (
            "<h3>Test Due Soon</h3>"
            "<p>A scheduled test for <b>{equipment}</b> is due on <b>{due_date}</b>. "
            "(Request: {request_number})</p>"
        ),
        "recipient_roles": ["Tester", "Department Head"],
    },
    {
        "event_type": "due_reminder",
        "channel": "inapp",
        "subject_template": "Test due — {equipment}",
        "body_template": "Test due on {due_date} for {equipment}.",
        "recipient_roles": ["Tester", "Department Head"],
    },
    # ── overdue_alert ────────────────────────────────────────────────────────
    {
        "event_type": "overdue_alert",
        "channel": "email",
        "subject_template": "[OVERDUE] Test Overdue — {equipment}",
        "body_template": (
            "<h3 style='color:red'>⚠️ Test Overdue</h3>"
            "<p>The test for <b>{equipment}</b> was due on <b>{due_date}</b> "
            "and has not been completed. (Request: {request_number})</p>"
        ),
        "recipient_roles": ["Department Head", "Originator"],
    },
    {
        "event_type": "overdue_alert",
        "channel": "inapp",
        "subject_template": "Overdue — {equipment}",
        "body_template": "Test overdue since {due_date} for {equipment}.",
        "recipient_roles": ["Department Head", "Originator"],
    },
    # ── recommendation_approved ───────────────────────────────────────────────
    {
        "event_type": "recommendation_approved",
        "channel": "email",
        "subject_template": "Recommendation Approved — {request_number}",
        "body_template": (
            "<h3>Recommendation Approved</h3>"
            "<p>The <b>{recommendation_type}</b> recommendation for request "
            "<b>{request_number}</b> has been approved. "
            "{product_count} replacement product(s) have been flagged for procurement.</p>"
        ),
        "recipient_roles": ["Procurement", "Department Head"],
    },
    {
        "event_type": "recommendation_approved",
        "channel": "inapp",
        "subject_template": "Recommendation approved — {request_number}",
        "body_template": "{product_count} product(s) ready for procurement.",
        "recipient_roles": ["Procurement", "Department Head"],
    },
]


def seed_default_templates(db: Session) -> int:
    """
    Idempotent seed: insert global default templates (organization_id=NULL)
    only if they don't already exist.  Call once from startup or migration.
    Returns count of inserted rows.
    """
    inserted = 0
    for tpl in DEFAULT_TEMPLATES:
        existing = (
            db.query(NotificationTemplate)
            .filter(
                NotificationTemplate.event_type == tpl["event_type"],
                NotificationTemplate.channel == tpl["channel"],
                NotificationTemplate.organization_id.is_(None),
            )
            .first()
        )
        if not existing:
            db.add(NotificationTemplate(**tpl))
            inserted += 1
    if inserted:
        db.commit()
        logger.info(f"[Notif] Seeded {inserted} default notification templates.")
    return inserted
