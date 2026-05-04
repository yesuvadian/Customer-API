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
    NotificationVariable,
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

import re as _re

def _render(template: str, context: Dict[str, Any]) -> str:
    """
    Render notification templates supporting two syntaxes:

      {{dot.key}}  — new-style system variables (e.g. {{report.retriepdf}})
      {flat_key}   — legacy single-brace keys   (e.g. {equipment})

    Unknown keys are left as-is so partial templates don't break.
    """
    def _sub(m: "_re.Match") -> str:
        key = m.group(1).strip()
        val = context.get(key)
        return str(val) if val is not None else m.group(0)

    # Pass 1: {{double.brace}} → supports dot-notation keys
    result = _re.sub(r"\{\{([^}]+)\}\}", _sub, template)
    # Pass 2: {single} → legacy flat keys
    result = _re.sub(r"\{([^{}]+)\}", _sub, result)
    return result


# ── Variable context resolver ─────────────────────────────────────────────────

class VariableResolver:
    """
    Augments the raw context dict passed to fire() with:
      • Dot-notation aliases  ({{equipment.ueic}} from legacy "equipment" key)
      • System-injected vars  ({{system.date}}, {{system.time}}, {{system.app_name}})

    The DB table `notification_variables` acts as the **registry** for the UI
    variable-picker only — resolution always uses this class + the fire() context.
    """

    # Maps dot-notation var_key → list of fallback raw-context keys (first match wins)
    _ALIASES: Dict[str, List[str]] = {
        "equipment.ueic":        ["equipment", "ueic", "old_ueic"],
        "equipment.type":        ["equipment_type"],
        "equipment.department":  ["department"],
        "equipment.manufacturer":["manufacturer"],
        "equipment.status":      ["equipment_status"],
        "request.number":        ["request_number"],
        "request.title":         ["request_title", "title"],
        "request.status":        ["request_status"],
        "request.priority":      ["request_priority", "priority"],
        "request.due_date":      ["due_date"],
        "request.submitted_by":  ["originator"],
        "request.assigned_to":   ["tester", "assigned_tester"],
        "eval.overall":          ["eval_overall", "overall"],
        "eval.test_type":        ["test_name"],
        "eval.evaluated_at":     ["tested_at", "evaluated_at"],
        "report.ref":            ["report_ref", "request_number"],
        "report.generated_on":   ["report_generated_on"],
        "report.retriepdf":      ["report_pdf_url", "pdf_url"],
        "report.retriexls":      ["report_xls_url", "xls_url"],
        "org.name":              ["org_name"],
        "org.id":                ["org_id"],
    }

    @staticmethod
    def build_context(raw: Dict[str, Any]) -> Dict[str, Any]:
        """
        Return a flat dict that maps every supported var_key to its resolved value.
        Safe to call with any partial context — missing keys simply won't be resolved.
        """
        now = datetime.now(timezone.utc)
        ctx: Dict[str, Any] = {k: (str(v) if v is not None else "") for k, v in raw.items()}

        # Inject system variables (always available)
        ctx.setdefault("system.date",     now.strftime("%Y-%m-%d"))
        ctx.setdefault("system.time",     now.strftime("%H:%M UTC"))
        ctx.setdefault("system.app_name", "SEACMS")

        # Resolve dot-notation aliases from legacy flat keys
        for dot_key, sources in VariableResolver._ALIASES.items():
            if dot_key not in ctx or not ctx[dot_key]:
                for src in sources:
                    if ctx.get(src):
                        ctx[dot_key] = ctx[src]
                        break

        return ctx


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

            resolved_ctx = VariableResolver.build_context(context)
            for tmpl in templates:
                subject = _render(tmpl.subject_template or "", resolved_ctx)
                body    = _render(tmpl.body_template,            resolved_ctx)

                # ── Role-based recipients ────────────────────────────────────
                recipients = _resolve_recipients_by_roles(
                    self.db,
                    list(tmpl.recipient_roles or []),
                    organization_id,
                )

                # ── Caller-supplied extra User objects (e.g. test-fire) ──────
                if extra_recipients:
                    seen_ids = {u.id for u in recipients}
                    for u in extra_recipients:
                        if u.id not in seen_ids:
                            recipients.append(u)
                            seen_ids.add(u.id)

                dispatched_emails: set = {u.email for u in recipients if u.email}

                for user in recipients:
                    self._dispatch_to_user(
                        tmpl=tmpl, user=user, subject=subject, body=body,
                        event_type=event_type, organization_id=organization_id,
                        source_id=source_id, source_type=source_type, severity=severity,
                    )

                # ── extra_recipient_emails (individual addresses on template) ─
                # Only for email channel; skip duplicates already sent via roles
                if tmpl.channel == "email":
                    for addr in (tmpl.extra_recipient_emails or []):
                        if addr and addr not in dispatched_emails:
                            dispatched_emails.add(addr)
                            log = NotificationLog(
                                organization_id=organization_id,
                                event_type=event_type,
                                channel="email",
                                recipient_email=addr,
                                subject=subject,
                                body=body,
                                status="pending",
                                source_id=source_id,
                                source_type=source_type,
                            )
                            self.db.add(log)
                            try:
                                self.db.flush()
                            except Exception:
                                pass

                if not recipients and not (tmpl.extra_recipient_emails):
                    logger.debug(
                        f"[Notif] event={event_type!r} template={tmpl.id}: "
                        f"no recipients for roles {tmpl.recipient_roles}"
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
        """
        Enqueue a notification for one user on one channel.

        - inapp:       written immediately to UserNotification (DB-only, no network I/O).
                       Log is marked 'sent' right away.
        - email / sms: log is written as 'pending' and left for the background
                       scheduler job (process_pending_notifications) to dispatch.
                       This keeps the API request fast and decouples sending.
        """
        log = NotificationLog(
            organization_id=organization_id,
            event_type=event_type,
            channel=tmpl.channel,
            recipient_id=user.id,
            recipient_email=user.email if tmpl.channel == "email" else None,
            recipient_phone=getattr(user, "phone_number", None) if tmpl.channel == "sms" else None,
            subject=subject,
            body=body,
            status="pending",
            source_id=source_id,
            source_type=source_type,
        )
        self.db.add(log)
        self.db.flush()  # get log.id

        if tmpl.channel == "inapp":
            # Inapp: instant DB write, no network — do it synchronously
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

        elif tmpl.channel in ("email", "sms"):
            # Email / SMS: leave as 'pending' — scheduler will pick up and send
            # Validate we have the required contact info before queuing
            if tmpl.channel == "email" and not user.email:
                log.status = "skipped"
                log.error_message = "User has no email address"
            elif tmpl.channel == "sms" and not getattr(user, "phone_number", None):
                log.status = "skipped"
                log.error_message = "User has no phone number"
            # else: stays 'pending', scheduler will send

        try:
            self.db.commit()
        except Exception as exc:
            logger.error(f"[Notif] DB commit failed after enqueue: {exc}")
            self.db.rollback()

    # ── Background job: process pending email/sms logs ────────────────────────

    def process_pending_notifications(self) -> dict:
        """
        Called by APScheduler every minute.
        Picks up NotificationLog rows with status='pending' for email/sms channels
        and dispatches them.  Returns a summary dict.
        """
        from sqlalchemy import and_

        pending = (
            self.db.query(NotificationLog)
            .filter(
                NotificationLog.status == "pending",
                NotificationLog.channel.in_(["email", "sms"]),
            )
            .order_by(NotificationLog.cts.asc())
            .limit(50)   # process in batches of 50
            .all()
        )

        sent = failed = skipped = 0

        for log in pending:
            if log.channel == "email":
                if not log.recipient_email:
                    log.status = "skipped"
                    log.error_message = "No email address on log row"
                    skipped += 1
                    continue
                # Digest check
                if _should_digest(self.db, log.event_type, log.organization_id):
                    _collapse_digest(self.db, log.event_type, log.organization_id)
                    skipped += 1
                    continue
                _send_email(self.db, log, log.recipient_email, log.subject or "", log.body or "")
                if log.status == "sent":
                    sent += 1
                else:
                    failed += 1

            elif log.channel == "sms":
                phone = log.recipient_phone
                if not phone:
                    # Try fetching from user record
                    if log.recipient_id:
                        u = self.db.query(User).filter(User.id == log.recipient_id).first()
                        phone = getattr(u, "phone_number", None) if u else None
                if not phone:
                    log.status = "skipped"
                    log.error_message = "No phone number found"
                    skipped += 1
                    continue
                _send_sms(self.db, log, phone, log.body or "")
                if log.status in ("sent", "skipped"):
                    sent += 1
                else:
                    failed += 1

        try:
            self.db.commit()
        except Exception as exc:
            logger.error(f"[Notif] process_pending commit failed: {exc}")
            self.db.rollback()

        return {"sent": sent, "failed": failed, "skipped": skipped, "total": len(pending)}


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
    # ── request_submitted ────────────────────────────────────────────────────
    {
        "event_type": "request_submitted",
        "channel": "inapp",
        "subject_template": "New submission — {request_number}",
        "body_template": "{equipment} submitted for approval by {originator}. Category: {category}.",
        "recipient_roles": ["Approver", "Department Head", "Super Admin"],
    },
    {
        "event_type": "request_submitted",
        "channel": "email",
        "subject_template": "New Submission Pending Approval — {request_number}",
        "body_template": (
            "<h3>New Submission Awaiting Approval</h3>"
            "<p><b>Equipment:</b> {equipment}</p>"
            "<p><b>Request:</b> {request_number}</p>"
            "<p><b>Category:</b> {category}</p>"
            "<p><b>Submitted by:</b> {originator}</p>"
            "<p>Please log in to review and approve.</p>"
        ),
        "recipient_roles": ["Approver", "Department Head"],
    },
    # ── fr_approved ───────────────────────────────────────────────────────────
    {
        "event_type": "fr_approved",
        "channel": "inapp",
        "subject_template": "Failure Report Approved — {fr_number}",
        "body_template": "Your failure report {fr_number} was approved. Outcome: {outcome}.",
        "recipient_roles": [],
    },
    # ── fr_rejected ───────────────────────────────────────────────────────────
    {
        "event_type": "fr_rejected",
        "channel": "inapp",
        "subject_template": "Failure Report Rejected — {fr_number}",
        "body_template": "Your failure report {fr_number} was rejected. Reason: {reason}.",
        "recipient_roles": [],
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
    # ── equipment_replacement (SRS §3.3.1) ───────────────────────────────────
    # All recipient_roles are configurable via Admin → Notification Templates.
    # Admins can add/remove roles without any code change.
    # Default roles follow KPTCL SRS: EE TLSS, SEE W&M, CEE Transmission Zone.
    {
        "event_type": "equipment_replacement",
        "channel": "email",
        "subject_template": "[REPLACEMENT] {equipment_type} — {old_ueic} → {new_ueic}",
        "body_template": (
            "<h3 style='color:#1E3C72'>Equipment Replacement Notification</h3>"
            "<p>A replacement event has been recorded in SEACMS.</p>"
            "<table cellpadding='6' cellspacing='0' border='1' "
            "style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td><b>Retired UEIC</b></td><td>{old_ueic}</td></tr>"
            "<tr><td><b>New UEIC</b></td><td>{new_ueic}</td></tr>"
            "<tr><td><b>Equipment Type</b></td><td>{equipment_type}</td></tr>"
            "<tr><td><b>Substation / Bay</b></td><td>{department}</td></tr>"
            "<tr><td><b>Reason Type</b></td><td>{reason_type}</td></tr>"
            "<tr><td><b>Reason</b></td><td>{reason}</td></tr>"
            "<tr><td><b>Replaced By</b></td><td>{replaced_by}</td></tr>"
            "<tr><td><b>Date</b></td><td>{replaced_on}</td></tr>"
            "</table>"
            "<p style='margin-top:12px'>Download the Replacement Report PDF from "
            "the SEACMS Equipment Register.</p>"
        ),
        "recipient_roles": ["EE TLSS", "SEE W&M", "CEE Transmission Zone", "Department Head"],
    },
    {
        "event_type": "equipment_replacement",
        "channel": "inapp",
        "subject_template": "Equipment replaced — {old_ueic} → {new_ueic}",
        "body_template": (
            "{equipment_type} at {department} replaced by {replaced_by} on {replaced_on}. "
            "Reason type: {reason_type}."
        ),
        "recipient_roles": ["EE TLSS", "SEE W&M", "CEE Transmission Zone", "Department Head"],
    },
    {
        "event_type": "equipment_replacement",
        "channel": "sms",
        "subject_template": "",
        "body_template": (
            "SEACMS: {equipment_type} at {department} replaced. "
            "Old: {old_ueic}. New: {new_ueic}. By {replaced_by} on {replaced_on}."
        ),
        "recipient_roles": ["EE TLSS", "SEE W&M", "CEE Transmission Zone"],
    },
]


# ── Variable registry seed ────────────────────────────────────────────────────

DEFAULT_VARIABLES = [
    # ── Reports ──────────────────────────────────────────────────────────────
    {
        "var_key": "report.retriexls", "label": "Report — Excel Download URL",
        "group_name": "Reports", "resolver_key": "report.retriexls",
        "description": "Signed URL for the Excel report attachment (.xlsx).",
        "sample_value": "https://app.seacms.in/reports/REQ-001.xlsx",
        "is_system": True,
    },
    {
        "var_key": "report.retriepdf", "label": "Report — PDF Download URL",
        "group_name": "Reports", "resolver_key": "report.retriepdf",
        "description": "Signed URL for the PDF report attachment.",
        "sample_value": "https://app.seacms.in/reports/REQ-001.pdf",
        "is_system": True,
    },
    {
        "var_key": "report.ref", "label": "Report Reference Number",
        "group_name": "Reports", "resolver_key": "report.ref",
        "description": "Auto-generated report reference number.",
        "sample_value": "RPT-2025-001",
        "is_system": True,
    },
    {
        "var_key": "report.generated_on", "label": "Report Generated Date/Time",
        "group_name": "Reports", "resolver_key": "report.generated_on",
        "description": "Timestamp when the report was generated.",
        "sample_value": "2025-01-15 10:30 UTC",
        "is_system": True,
    },
    # ── Equipment ─────────────────────────────────────────────────────────────
    {
        "var_key": "equipment.ueic", "label": "Equipment UEIC",
        "group_name": "Equipment", "resolver_key": "equipment",
        "description": "Unique Equipment Identity Code of the subject equipment.",
        "sample_value": "TX-001-2025",
        "is_system": True,
    },
    {
        "var_key": "equipment.type", "label": "Equipment Type",
        "group_name": "Equipment", "resolver_key": "equipment_type",
        "description": "Type/category of the equipment (e.g. Power Transformer).",
        "sample_value": "Power Transformer",
        "is_system": True,
    },
    {
        "var_key": "equipment.department", "label": "Substation / Department",
        "group_name": "Equipment", "resolver_key": "department",
        "description": "Substation, bay, or department where the equipment is installed.",
        "sample_value": "Relay Panel — Substation A",
        "is_system": True,
    },
    {
        "var_key": "equipment.status", "label": "Equipment Status",
        "group_name": "Equipment", "resolver_key": "equipment_status",
        "description": "Current operational status of the equipment.",
        "sample_value": "active",
        "is_system": True,
    },
    {
        "var_key": "equipment.manufacturer", "label": "Manufacturer",
        "group_name": "Equipment", "resolver_key": "manufacturer",
        "description": "Manufacturer / OEM of the equipment.",
        "sample_value": "ABB",
        "is_system": True,
    },
    # ── Replacement event ──────────────────────────────────────────────────────
    {
        "var_key": "old_ueic", "label": "Retired UEIC",
        "group_name": "Replacement", "resolver_key": "old_ueic",
        "description": "UEIC of the retired (replaced) equipment.",
        "sample_value": "TX-OLD-001",
        "is_system": True,
    },
    {
        "var_key": "new_ueic", "label": "New Replacement UEIC",
        "group_name": "Replacement", "resolver_key": "new_ueic",
        "description": "UEIC of the newly commissioned replacement equipment.",
        "sample_value": "TX-NEW-002",
        "is_system": True,
    },
    {
        "var_key": "replaced_by", "label": "Replaced By (User)",
        "group_name": "Replacement", "resolver_key": "replaced_by",
        "description": "Name or email of the officer who recorded the replacement.",
        "sample_value": "EE John (john@utility.com)",
        "is_system": True,
    },
    {
        "var_key": "replaced_on", "label": "Replacement Date",
        "group_name": "Replacement", "resolver_key": "replaced_on",
        "description": "Date on which the replacement event was recorded.",
        "sample_value": "2025-01-15",
        "is_system": True,
    },
    {
        "var_key": "reason", "label": "Replacement / Rejection Reason",
        "group_name": "Replacement", "resolver_key": "reason",
        "description": "Free-text reason for the replacement or rejection action.",
        "sample_value": "End of service life — IR below threshold",
        "is_system": True,
    },
    # ── Test Request workflow ──────────────────────────────────────────────────
    {
        "var_key": "request.number", "label": "Test Request Number",
        "group_name": "Test Request", "resolver_key": "request_number",
        "description": "Auto-generated test request reference number.",
        "sample_value": "REQ-2025-001",
        "is_system": True,
    },
    {
        "var_key": "request.title", "label": "Test Request Title",
        "group_name": "Test Request", "resolver_key": "request_title",
        "description": "Title/description of the test request.",
        "sample_value": "IR Test — Power Transformer TX-001",
        "is_system": True,
    },
    {
        "var_key": "request.status", "label": "Request Status",
        "group_name": "Test Request", "resolver_key": "request_status",
        "description": "Current workflow status of the test request.",
        "sample_value": "submitted",
        "is_system": True,
    },
    {
        "var_key": "request.priority", "label": "Priority",
        "group_name": "Test Request", "resolver_key": "request_priority",
        "description": "Priority level of the test request (high / medium / low).",
        "sample_value": "high",
        "is_system": True,
    },
    {
        "var_key": "request.due_date", "label": "Due Date",
        "group_name": "Test Request", "resolver_key": "due_date",
        "description": "Scheduled due date for the test to be completed.",
        "sample_value": "2025-03-31",
        "is_system": True,
    },
    {
        "var_key": "request.submitted_by", "label": "Submitted By",
        "group_name": "Test Request", "resolver_key": "originator",
        "description": "Email / name of the user who submitted the test request.",
        "sample_value": "originator@utility.com",
        "is_system": True,
    },
    {
        "var_key": "request.assigned_to", "label": "Assigned To (Tester)",
        "group_name": "Test Request", "resolver_key": "tester",
        "description": "Email / name of the tester the request was assigned to.",
        "sample_value": "tester@utility.com",
        "is_system": True,
    },
    # ── Evaluation / test result ───────────────────────────────────────────────
    {
        "var_key": "eval.overall", "label": "Overall Result (NORMAL / ALERT / CRITICAL)",
        "group_name": "Evaluation", "resolver_key": "eval_overall",
        "description": "Composite evaluation outcome from test template thresholds.",
        "sample_value": "CRITICAL",
        "is_system": True,
    },
    {
        "var_key": "eval.test_type", "label": "Test Type",
        "group_name": "Evaluation", "resolver_key": "test_name",
        "description": "Name of the test type (e.g. IR Test, PI Test).",
        "sample_value": "IR Test",
        "is_system": True,
    },
    {
        "var_key": "eval.evaluated_at", "label": "Evaluation Date/Time",
        "group_name": "Evaluation", "resolver_key": "tested_at",
        "description": "Timestamp when the test evaluation was completed.",
        "sample_value": "2025-01-15 09:00 UTC",
        "is_system": True,
    },
    # ── Organisation ──────────────────────────────────────────────────────────
    {
        "var_key": "org.name", "label": "Organisation Name",
        "group_name": "Organisation", "resolver_key": "org_name",
        "description": "Name of the organisation as registered in SEACMS.",
        "sample_value": "KPTCL",
        "is_system": True,
    },
    {
        "var_key": "org.id", "label": "Organisation ID",
        "group_name": "Organisation", "resolver_key": "org_id",
        "description": "UUID of the organisation.",
        "sample_value": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "is_system": True,
    },
    # ── System ────────────────────────────────────────────────────────────────
    {
        "var_key": "system.date", "label": "Today's Date",
        "group_name": "System", "resolver_key": "system.date",
        "description": "Current date at the time the notification is rendered (YYYY-MM-DD).",
        "sample_value": "2025-01-15",
        "is_system": True,
    },
    {
        "var_key": "system.time", "label": "Current Time (UTC)",
        "group_name": "System", "resolver_key": "system.time",
        "description": "Current time at the time the notification is rendered (HH:MM UTC).",
        "sample_value": "10:30 UTC",
        "is_system": True,
    },
    {
        "var_key": "system.app_name", "label": "Application Name (SEACMS)",
        "group_name": "System", "resolver_key": "system.app_name",
        "description": "Name of the application — always resolves to 'SEACMS'.",
        "sample_value": "SEACMS",
        "is_system": True,
    },
]


def seed_default_variables(db: Session) -> int:
    """
    Idempotent seed: insert global system variables (organization_id=NULL, is_system=True)
    only if they don't already exist (matched by var_key + org=NULL).
    Returns count of inserted rows.
    """
    inserted = 0
    for v in DEFAULT_VARIABLES:
        existing = (
            db.query(NotificationVariable)
            .filter(
                NotificationVariable.var_key == v["var_key"],
                NotificationVariable.organization_id.is_(None),
            )
            .first()
        )
        if not existing:
            db.add(NotificationVariable(**v))
            inserted += 1
    if inserted:
        db.commit()
        logger.info(f"[Notif] Seeded {inserted} default notification variable(s).")
    return inserted


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
