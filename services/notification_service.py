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
    NotificationRoutingRule,
    NotificationTemplate,
    NotificationVariable,
    OrgRole,
    OrgUserRole,
    User,
    UserNotification,
)
from utils.email_service import EmailService

logger = logging.getLogger(__name__)

# ── Constants (loaded from .env — override without code change) ───────────────

import os as _os

DIGEST_THRESHOLD      = int(_os.getenv("NOTIF_DIGEST_THRESHOLD",      "10"))
DIGEST_WINDOW_MINUTES = int(_os.getenv("NOTIF_DIGEST_WINDOW_MINUTES",  "5"))
MAX_RETRIES           = int(_os.getenv("NOTIF_MAX_RETRIES",            "3"))
RETRY_DELAY_MINUTES   = int(_os.getenv("NOTIF_RETRY_DELAY_MINUTES",    "5"))


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


# ── Source-record context enrichment ─────────────────────────────────────────

def _enrich_context_from_source(
    db: Session,
    source_type: Optional[str],
    source_id: Optional[UUID],
    ctx: Dict[str, Any],
) -> None:
    """
    Load the triggering record from DB and add its fields to ctx so templates
    can use {{tr.id}}, {{tr.status}}, {{tr.category}}, {{equipment.ueic}},
    {{equipment.name}}, {{dept.name}}, etc. without the caller having to
    pass every field manually.

    CategoryDetails is used to resolve display names for category IDs.
    """
    if not source_type or not source_id:
        return
    try:
        if source_type == "testing_request":
            from models import TestingRequest, OrgDepartment, CategoryDetails, CategoryMaster
            tr = db.query(TestingRequest).filter(TestingRequest.id == source_id).first()
            if not tr:
                return
            ctx.setdefault("tr.id",          str(tr.id))
            ctx.setdefault("tr.status",       str(tr.status.value) if tr.status else "")
            ctx.setdefault("tr.submitted_at", str(tr.created_at)[:19] if tr.created_at else "")
            ctx.setdefault("tr.category",     str(tr.request_category.value) if tr.request_category else "")
            ctx.setdefault("request.number",  tr.request_number or str(tr.id)[:8])
            ctx.setdefault("request.status",  str(tr.status.value) if tr.status else "")
            ctx.setdefault("request.title",   tr.title or "")
            ctx.setdefault("request.priority", tr.priority or "normal")
            if tr.due_date:
                ctx.setdefault("request.due_date", str(tr.due_date)[:10])
            # CategoryDetails → test type display name (e.g. "Routine Test")
            if tr.test_type_id:
                cat = db.query(CategoryDetails).filter(
                    CategoryDetails.id == tr.test_type_id
                ).first()
                if cat:
                    ctx.setdefault("eval.test_type",   cat.name or "")
                    ctx.setdefault("tr.test_type",     cat.name or "")
                    ctx.setdefault("tr.category_type", cat.category_type or "")
            # CategoryMaster → equipment type display name (e.g. "Power Transformer")
            if tr.equipment_type_id:
                eq_type = db.query(CategoryMaster).filter(
                    CategoryMaster.id == tr.equipment_type_id
                ).first()
                if eq_type:
                    ctx.setdefault("equipment.type", eq_type.name or "")
            # Department context from TR
            if tr.department_id:
                dept = db.query(OrgDepartment).filter(
                    OrgDepartment.id == tr.department_id
                ).first()
                if dept:
                    ctx.setdefault("dept.name", dept.name or "")
                    ctx.setdefault("dept.code", dept.code or "")
            # Equipment (asset register) context
            if tr.equipment_id:
                from models import Equipment
                eq = db.query(Equipment).filter(Equipment.id == tr.equipment_id).first()
                if eq:
                    ctx.setdefault("equipment.ueic", getattr(eq, "ueic", "") or "")
                    ctx.setdefault("equipment.name", getattr(eq, "name", "") or "")

        elif source_type == "test_result":
            from models import TestResult, TestingRequest, OrgDepartment
            tr_res = db.query(TestResult).filter(TestResult.id == source_id).first()
            if not tr_res:
                return
            ctx.setdefault("eval.overall",     tr_res.overall_result or "")
            ctx.setdefault("eval.evaluated_at", str(tr_res.created_at)[:19] if tr_res.created_at else "")
            if tr_res.testing_request_id:
                tr = db.query(TestingRequest).filter(
                    TestingRequest.id == tr_res.testing_request_id
                ).first()
                if tr:
                    ctx.setdefault("request.number", tr.request_number or str(tr.id)[:8])
                    ctx.setdefault("tr.status",       tr.status or "")
                    if tr.department_id:
                        dept = db.query(OrgDepartment).filter(
                            OrgDepartment.id == tr.department_id
                        ).first()
                        if dept:
                            ctx.setdefault("dept.name", dept.name or "")
                            ctx.setdefault("dept.code", dept.code or "")

        elif source_type == "recommendation":
            from models import Recommendation
            rec = db.query(Recommendation).filter(Recommendation.id == source_id).first()
            if rec:
                ctx.setdefault("recommendation.id",     str(rec.id))
                ctx.setdefault("recommendation.status", rec.status or "")

    except Exception as _exc:
        logger.debug(f"[Notif] _enrich_context_from_source({source_type}): {_exc}")


def _load_org_variables(db: Session, organization_id: Optional[UUID]) -> Dict[str, str]:
    """
    Load active custom org variables from notification_variables table.
    Returns {var_key: sample_value} for injection into the render context.
    System variables (is_system=True) are registered here for the UI picker
    but resolved by VariableResolver._ALIASES — skip them to avoid overwriting.
    """
    if not organization_id:
        return {}
    try:
        rows = (
            db.query(NotificationVariable)
            .filter(
                NotificationVariable.organization_id == organization_id,
                NotificationVariable.is_system.is_(False),
                NotificationVariable.is_active.is_(True),
            )
            .all()
        )
        return {r.var_key: (r.sample_value or "") for r in rows}
    except Exception as _exc:
        logger.debug(f"[Notif] _load_org_variables: {_exc}")
        return {}


def _generate_attachment_bytes(
    db: Session,
    source_type: Optional[str],
    source_id: Optional[UUID],
    att_type: str,
) -> Optional[bytes]:
    """
    Generate a report in-memory and return its raw bytes, or None on failure.

    source_type → PDF service mapping:
      testing_request     → TestingRequestPDFService.generate_pdf(id)
      test_result         → TestResultPDFService.generate_pdf(id)
      recommendation      → RecommendationPDFService.generate_pdf(id)
      equipment_replacement → EquipmentReplacementPDFService.generate_pdf(old_id, new_id)

    Excel: reserved for future ReportingService integration.
    """
    if not source_type or not source_id:
        return None
    try:
        att_type = att_type.lower().strip()

        if att_type == "pdf":
            if source_type == "testing_request":
                from services.testing_request_pdf_service import TestingRequestPDFService
                svc = TestingRequestPDFService(db)
                bio = svc.generate_pdf(str(source_id))
                return bio.getvalue() if bio else None

            elif source_type == "test_result":
                from services.test_result_pdf_service import TestResultPDFService
                svc = TestResultPDFService(db)
                bio = svc.generate_pdf(source_id)
                return bio.getvalue() if bio else None

            elif source_type == "recommendation":
                from services.recommendation_pdf_service import RecommendationPDFService
                svc = RecommendationPDFService(db)
                bio = svc.generate_pdf(str(source_id))
                return bio.getvalue() if bio else None

            elif source_type == "equipment_replacement":
                from services.equipment_replacement_pdf_service import EquipmentReplacementPDFService
                svc = EquipmentReplacementPDFService(db)
                bio = svc.generate_pdf(source_id, source_id)
                return bio.getvalue() if bio else None

        elif att_type in ("excel", "xlsx"):
            # Excel generation requires a ReportDefinition — not yet wired for
            # on-demand notification attachments. Return None so the email is sent
            # without the Excel file rather than blocking delivery.
            logger.info(
                f"[Notif] Excel attachment for {source_type}/{source_id} skipped "
                f"(no on-demand Excel service configured)"
            )
            return None

    except Exception as _exc:
        logger.warning(f"[Notif] _generate_attachment_bytes({source_type}, {att_type}): {_exc}")
    return None


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
        # Department / context variables — useful in subject line
        # e.g. "Subject: [{{dept.name}}] Equipment replaced"
        "dept.name":             ["currentdeptname", "department_name", "dept_name", "department"],
        "dept.code":             ["dept_code", "department_code"],
        "dept.level":            ["dept_level"],
        "user.name":             ["user_name", "recipient_name"],
        "user.email":            ["recipient_email", "user_email"],
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


# ── Department ancestry helper ────────────────────────────────────────────────

def _ancestor_dept_ids(db: Session, department_id: UUID) -> set:
    """
    Return the set of all ancestor department IDs (including department_id itself).
    Walks up parent_department_id chain — stops at root (parent_department_id IS NULL).
    Typical KPTCL depth: 3 levels (Zone → Circle → Division).
    """
    from models import OrgDepartment
    ids: set = set()
    current_id = department_id
    while current_id is not None:
        ids.add(current_id)
        dept = db.query(OrgDepartment).filter(OrgDepartment.id == current_id).first()
        if not dept:
            break
        current_id = dept.parent_department_id
    return ids


# ── Recipient resolution ──────────────────────────────────────────────────────

def _resolve_recipients_by_roles(
    db: Session,
    role_names: List[str],
    organization_id: Optional[UUID],
    department_id: Optional[UUID] = None,
) -> List[User]:
    """
    Return unique active User objects that hold any of the given OrgRole names
    within the given organisation, scoped by department when provided.

    Department scoping rules (mirrors testing_request_service.get_user_scope):
      • OrgUserRole.department_id IS NULL  → org-wide user  → always included
      • OrgUserRole.department_id == source_dept    → same leaf dept → included
      • OrgUserRole.department_id is an ANCESTOR of source_dept
        (circle/zone level above the TR's division)           → included
      • OrgUserRole.department_id is a sibling / different branch → excluded

    This ensures North-division events don't spam South/Mysuru personnel,
    but Circle EE and Zone SEE (who sit above the division) still receive them.
    """
    if not role_names or not organization_id:
        return []

    # Build the full ancestor set once (includes source dept itself)
    ancestor_ids: set = set()
    if department_id:
        ancestor_ids = _ancestor_dept_ids(db, department_id)

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
        if department_id:
            row_dept = row.department_id
            # Exclude users assigned to a dept that is NOT in the ancestor chain
            # (i.e. a sibling division or unrelated branch).
            # Org-wide users (dept_id IS NULL) are always included.
            if row_dept is not None and row_dept not in ancestor_ids:
                continue
        if row.user_id not in seen:
            seen.add(row.user_id)
            users.append(row.user)
    return users


# ── Full HTML email wrapper ───────────────────────────────────────────────────

def _wrap_email_html(body_content: str, subject: str = "", org_name: str = "SEACMS") -> str:
    """
    Wrap an HTML body fragment in a full, responsive HTML email document.

    Every email channel notification automatically receives:
      • A branded header  (org_name + SEACMS tagline)
      • A content area    (body_content injected as-is)
      • A footer          (auto-generated, copyright year)

    body_content may be any HTML fragment — tables, paragraphs, <h3> headings, etc.
    """
    from datetime import date as _d
    year = _d.today().year
    return (
        "<!DOCTYPE html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="UTF-8"/>'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0"/>'
        f"<title>{subject}</title>"
        "</head>"
        '<body style="margin:0;padding:0;background:#f4f6fb;'
        'font-family:Arial,Helvetica,sans-serif;">'
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="background:#f4f6fb;padding:24px 0;">'
        "<tr><td align=\"center\">"
        '<table width="600" cellpadding="0" cellspacing="0" '
        'style="background:#fff;border-radius:8px;overflow:hidden;'
        'box-shadow:0 2px 8px rgba(0,0,0,.1);">'

        # ── Header ──────────────────────────────────────────────────────
        "<tr>"
        '<td style="background:#1E3C72;padding:20px 32px;">'
        f'<h1 style="margin:0;color:#fff;font-size:20px;letter-spacing:1px;">{org_name}</h1>'
        '<p style="margin:4px 0 0;color:#a8c4e0;font-size:12px;">'
        "SEACMS — Smart Equipment Asset Care Management System</p>"
        "</td>"
        "</tr>"

        # ── Body ────────────────────────────────────────────────────────
        "<tr>"
        '<td style="padding:28px 32px;color:#333;font-size:14px;line-height:1.6;">'
        f"{body_content}"
        "</td>"
        "</tr>"

        # ── Footer ──────────────────────────────────────────────────────
        "<tr>"
        '<td style="background:#f0f4fa;padding:16px 32px;border-top:1px solid #dde3ee;">'
        '<p style="margin:0;font-size:11px;color:#888;text-align:center;">'
        f"This is an automated notification from <b>SEACMS</b> — {org_name}. "
        "Please do not reply to this email.<br/>"
        f"&copy; {year} {org_name}. All rights reserved."
        "</p>"
        "</td>"
        "</tr>"

        "</table>"
        "</td></tr>"
        "</table>"
        "</body>"
        "</html>"
    )


# ── Channel dispatcher factory ────────────────────────────────────────────────
#
# Design (Factory / Registry pattern)
# ------------------------------------
#   • ChannelDispatcher  — abstract base; every channel implements .send()
#   • ChannelDispatcherRegistry — maps channel-name → dispatcher instance
#
# Adding a new channel (e.g. WhatsApp) requires ZERO changes to existing code:
#
#   class WhatsAppDispatcher(ChannelDispatcher):
#       channel = "whatsapp"
#       def send(self, db, log, subject, body): ...
#
#   ChannelDispatcherRegistry.register(WhatsAppDispatcher())
#
# The NotificationTemplate.channel field drives which dispatcher is invoked.
# ─────────────────────────────────────────────────────────────────────────────

class ChannelDispatcher:
    """Abstract base for all notification channel dispatchers."""

    channel: str = ""

    def send(
        self,
        db: Session,
        log: "NotificationLog",
        subject: str,
        body: str,
    ) -> None:
        raise NotImplementedError(f"{self.__class__.__name__}.send() not implemented")

    def prepare_body(self, body: str, subject: str = "", org_name: str = "SEACMS") -> str:
        """
        Optional hook: transform body before it is stored in NotificationLog.
        Override in subclasses that need channel-specific body formatting
        (e.g. EmailDispatcher wraps in full HTML).
        """
        return body


class EmailDispatcher(ChannelDispatcher):
    """
    Email channel — sends via SMTP / Office 365 STARTTLS.
    Wraps every body_fragment in a full branded HTML email before sending.

    Attachment support
    ------------------
    When log.attachment_urls is non-empty each entry is fetched and attached:
      [{"url": "https://...", "var_key": "report.retriepdf", "type": "pdf"}, ...]

    The "type" field is optional but recommended for correct MIME detection:
      "pdf"   → application/pdf
      "excel" → application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
      "docx"  → application/vnd.openxmlformats-officedocument.wordprocessingml.document
      "json"  → application/json
    If omitted, the MIME type is auto-detected from the URL / var_key convention.
    """

    channel = "email"

    # ── Explicit type → MIME map ──────────────────────────────────────────────
    _MIME_MAP: Dict[str, str] = {
        "pdf":   "application/pdf",
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xlsx":  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "xls":   "application/vnd.ms-excel",
        "docx":  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc":   "application/msword",
        "json":  "application/json",
        "csv":   "text/csv",
        "txt":   "text/plain",
        "zip":   "application/zip",
    }

    def prepare_body(self, body: str, subject: str = "", org_name: str = "SEACMS") -> str:
        return _wrap_email_html(body, subject=subject, org_name=org_name)

    def send(self, db: Session, log: "NotificationLog", subject: str, body: str) -> None:
        to_email = log.recipient_email
        if not to_email:
            log.status = "skipped"
            log.error_message = "No recipient email address"
            return
        try:
            attachment_entries = log.attachment_urls or []
            if attachment_entries:
                # ── Build attachment list ──────────────────────────────────────
                # Strategy:
                #   1. If entry has "url" → fetch bytes from URL (legacy path).
                #   2. If no URL but type=pdf/excel → generate in-memory from
                #      log.source_type + log.source_id using the PDF/Excel service.
                attachments: List[Dict] = []
                svc = EmailService()
                for entry in attachment_entries:
                    url      = entry.get("url", "")
                    var_key  = entry.get("var_key", "")
                    att_type = (entry.get("type") or "").lower().strip()

                    content: Optional[bytes] = None
                    filename: str = ""
                    mime_type: str = "application/octet-stream"

                    if url:
                        # Path 1: fetch from URL
                        content = svc._fetch_attachment(url)
                        if not content:
                            logger.warning(
                                f"[Notif] Could not fetch attachment {url!r} for log {log.id}"
                            )
                            continue
                        if att_type and att_type in self._MIME_MAP:
                            mime_type = self._MIME_MAP[att_type]
                            filename, _ = svc._guess_filename(url, var_key)
                        else:
                            filename, mime_type = svc._guess_filename(url, var_key)

                    elif att_type in ("pdf", "excel", "xlsx"):
                        # Path 2: generate in-memory from the triggering record.
                        # Use source_type/source_id from the entry if present (set by
                        # _dispatch_to_user), otherwise fall back to the log's own fields.
                        _src_type = entry.get("source_type") or log.source_type
                        _src_id   = entry.get("source_id")
                        _src_uuid = UUID(_src_id) if _src_id else log.source_id
                        content = _generate_attachment_bytes(
                            db, _src_type, _src_uuid, att_type
                        )
                        if not content:
                            logger.warning(
                                f"[Notif] Could not generate {att_type} attachment for "
                                f"source={log.source_type}/{log.source_id} log={log.id}"
                            )
                            continue
                        mime_type = self._MIME_MAP.get(att_type, "application/octet-stream")
                        ext = "pdf" if att_type == "pdf" else "xlsx"
                        src_label = (log.source_type or "report").replace("_", "-")
                        src_short = str(log.source_id)[:8] if log.source_id else "report"
                        filename  = f"{src_label}-{src_short}.{ext}"

                    else:
                        logger.debug(
                            f"[Notif] Attachment entry has no url and no generatable type, "
                            f"skipping: {entry}"
                        )
                        continue

                    attachments.append({
                        "content":   content,
                        "filename":  filename,
                        "mime_type": mime_type,
                    })

                if attachments:
                    svc.send_multi_attachment_email_starttls(to_email, subject, body, attachments)
                else:
                    logger.warning(
                        f"[Notif] All attachments failed for log {log.id}; sending body only"
                    )
                    svc.send_email_starttls(to_email, subject, body)
            else:
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


class SmsDispatcher(ChannelDispatcher):
    """
    SMS channel — plain-text, 160-char guideline.
    Swap the stub body with your real SMS gateway call (Twilio, AWS SNS, Infobip…).

    To add WhatsApp later:
        class WhatsAppDispatcher(ChannelDispatcher):
            channel = "whatsapp"
            def send(self, db, log, subject, body):
                <call WhatsApp Business API>
        ChannelDispatcherRegistry.register(WhatsAppDispatcher())
    """

    channel = "sms"

    def send(self, db: Session, log: "NotificationLog", subject: str, body: str) -> None:
        phone = log.recipient_phone
        if not phone:
            log.status = "skipped"
            log.error_message = "No phone number"
            return
        # ── TODO: Replace stub with real SMS gateway ──────────────────────────
        # Example (Twilio):
        #   from twilio.rest import Client
        #   Client(SID, TOKEN).messages.create(to=phone, from_=FROM_NUMBER, body=body)
        # ─────────────────────────────────────────────────────────────────────
        logger.info(f"[Notif] SMS stub — would send to {phone}: {body[:80]}…")
        log.status = "skipped"   # ← change to "sent"/"failed" when gateway is wired
        log.sent_at = datetime.now(timezone.utc)


class InAppDispatcher(ChannelDispatcher):
    """
    In-app channel — writes directly to UserNotification table.
    Handled synchronously in _dispatch_to_user; send() is a no-op here.
    """

    channel = "inapp"

    def send(self, db: Session, log: "NotificationLog", subject: str, body: str) -> None:
        # In-app delivery is completed immediately inside _dispatch_to_user.
        # This method is never called from process_pending_notifications.
        pass


class ChannelDispatcherRegistry:
    """
    Central registry that maps channel names to their dispatcher instances.

    Usage
    -----
    # Get dispatcher for a channel
    dispatcher = ChannelDispatcherRegistry.get("email")

    # List all supported channels (useful for template-channel validation)
    ChannelDispatcherRegistry.channels()  →  ["email", "sms", "inapp"]

    # Register a new channel at startup (no existing code changes needed)
    ChannelDispatcherRegistry.register(WhatsAppDispatcher())
    """

    _registry: Dict[str, "ChannelDispatcher"] = {}

    @classmethod
    def register(cls, dispatcher: "ChannelDispatcher") -> None:
        cls._registry[dispatcher.channel] = dispatcher
        logger.debug(f"[Notif] Registered channel dispatcher: {dispatcher.channel!r}")

    @classmethod
    def get(cls, channel: str) -> Optional["ChannelDispatcher"]:
        return cls._registry.get(channel)

    @classmethod
    def channels(cls) -> List[str]:
        return list(cls._registry.keys())


# ── Register built-in dispatchers ─────────────────────────────────────────────
ChannelDispatcherRegistry.register(EmailDispatcher())
ChannelDispatcherRegistry.register(SmsDispatcher())
ChannelDispatcherRegistry.register(InAppDispatcher())


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


# ── Routing rule resolution ───────────────────────────────────────────────────

def _scope_matches(rule_list: Optional[list], value: Optional[str]) -> bool:
    """
    True if rule_list is empty/None (wildcard) OR value is in rule_list.
    Used for JSONB array scope filters.
    """
    if not rule_list:          # empty list or None = matches everything
        return True
    if value is None:
        return False
    return value in rule_list


def _resolve_routing(
    db: Session,
    event_type: str,
    organization_id: Optional[UUID],
    *,
    workflow_type: Optional[str] = None,
    equipment_type: Optional[str] = None,
    test_type: Optional[str] = None,
    status_from: Optional[str] = None,
    status_to: Optional[str] = None,
) -> Optional["NotificationRoutingRule"]:
    """
    Find the best-matching active routing rule for a fire() call.

    Resolution order
    ────────────────
    1. Load all active rules for event_type where org_id IN (None, organization_id).
    2. Filter to rows whose scope filters match the call context.
    3. Among matched rows, org-specific rules beat global; within same org-tier,
       highest priority wins.
    4. Returns the winning rule, or None if no rule matches.

    Caller behaviour on return value
    ──────────────────────────────────
    • None  → no routing rule configured → fire ALL channels (permissive default,
               keeps backward-compat for orgs that haven't set up rules yet).
    • Rule  → use rule.channels_enabled to filter templates;
               use rule.recipient_roles_override (if set) instead of template roles.
    """
    candidates = (
        db.query(NotificationRoutingRule)
        .filter(
            NotificationRoutingRule.event_type == event_type,
            NotificationRoutingRule.is_active.is_(True),
            # load both global and org-specific rows
            (
                NotificationRoutingRule.organization_id.is_(None)
                if organization_id is None
                else NotificationRoutingRule.organization_id.in_(
                    [None, organization_id]
                )
            ),
        )
        .order_by(
            # org-specific first (NULL org_id last)
            NotificationRoutingRule.organization_id.is_(None).asc(),
            NotificationRoutingRule.priority.desc(),
        )
        .all()
    )

    for rule in candidates:
        if not _scope_matches(rule.applicable_workflow_types,  workflow_type):
            continue
        if not _scope_matches(rule.applicable_equipment_types, equipment_type):
            continue
        if not _scope_matches(rule.applicable_test_types,      test_type):
            continue
        if rule.applicable_status_from and rule.applicable_status_from != status_from:
            continue
        if rule.applicable_status_to and rule.applicable_status_to != status_to:
            continue
        return rule   # first match wins (already sorted: org > global, high priority first)

    return None   # no rule → permissive default (all channels fire)


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
        department_id: Optional[UUID] = None,
        source_id: Optional[UUID] = None,
        source_type: Optional[str] = None,
        severity: Optional[str] = None,
        extra_recipients: Optional[List[User]] = None,
        # ── Routing context (used by NotificationRoutingRule matching) ────────
        workflow_type: Optional[str] = None,    # "direct_test"|"failure_register"|"taqc"|"multisession"|"schedule"
        equipment_type: Optional[str] = None,   # e.g. "Power Transformer", "CT"
        test_type: Optional[str] = None,        # "test"|"inspection"|"maintenance"|"life_cycle"
        status_from: Optional[str] = None,      # e.g. "submitted"
        status_to: Optional[str] = None,        # e.g. "under_review"
    ) -> None:
        """
        Resolve routing rules + templates for event_type, resolve recipients by
        role, and dispatch via the channels allowed by the routing rule.

        Routing rule resolution
        ───────────────────────
        NotificationRoutingRule rows are matched against the call's context
        (workflow_type, equipment_type, test_type, status_from/to).
        • Matching rule found  → only channels in rule.channels_enabled are sent;
                                  recipient_roles_override (if set) replaces template roles.
        • No rule found        → ALL channels fire (permissive default — backward-compat).

        department_id scoping
        ─────────────────────
        • Same dept or ancestor dept (circle/zone) → included
        • Org-wide users (dept IS NULL) → always included
        • Sibling / unrelated dept → excluded
        """
        try:
            templates = self._get_templates(event_type, organization_id)
            if not templates:
                logger.debug(f"[Notif] No active templates for event_type={event_type!r}")
                return

            resolved_ctx = VariableResolver.build_context(context)

            # ── Auto-inject org context from DB ──────────────────────────────
            _org_name = "SEACMS"
            if organization_id and not resolved_ctx.get("org_name"):
                try:
                    from models import Organization as _Org
                    _org = self.db.query(_Org).filter(_Org.id == organization_id).first()
                    if _org:
                        _org_name = _org.name
                        resolved_ctx["org_name"] = _org.name
                        resolved_ctx["org.name"] = _org.name
                        resolved_ctx["org_id"]   = str(organization_id)
                        resolved_ctx["org.id"]   = str(organization_id)
                except Exception as _org_exc:
                    logger.debug(f"[Notif] Could not auto-inject org context: {_org_exc}")
            else:
                _org_name = resolved_ctx.get("org_name", "SEACMS")

            # ── Enrich context from the triggering source record (DB lookup) ──
            # Resolves {{tr.category}}, {{equipment.ueic}}, {{dept.name}}, etc.
            # Uses CategoryDetails for category display names.
            _enrich_context_from_source(self.db, source_type, source_id, resolved_ctx)

            # ── Load custom org variables from notification_variables table ───
            # Injects {{custom.var_key}} values defined by the org admin.
            _org_vars = _load_org_variables(self.db, organization_id)
            for _k, _v in _org_vars.items():
                resolved_ctx.setdefault(_k, _v)

            # ── Routing rule: which channels are allowed for this call? ───────
            routing = _resolve_routing(
                self.db, event_type, organization_id,
                workflow_type=workflow_type,
                equipment_type=equipment_type,
                test_type=test_type,
                status_from=status_from,
                status_to=status_to,
            )
            allowed_channels: Optional[set] = (
                set(routing.channels_enabled) if routing and routing.channels_enabled
                else None   # None = all channels allowed (permissive default)
            )
            roles_override: Optional[list] = (
                list(routing.recipient_roles_override)
                if routing and routing.recipient_roles_override
                else None
            )
            if routing:
                logger.debug(
                    f"[Notif] Routing rule {routing.id} matched for "
                    f"event={event_type!r} workflow={workflow_type!r} "
                    f"channels={allowed_channels}"
                )

            for tmpl in templates:
                # ── Channel filter from routing rule ─────────────────────────
                if allowed_channels is not None and tmpl.channel not in allowed_channels:
                    logger.debug(
                        f"[Notif] Skipping channel={tmpl.channel!r} for "
                        f"event={event_type!r} (routing rule blocked)"
                    )
                    continue

                # ── Recipient roles: routing override wins if set ─────────────
                effective_roles = roles_override or list(tmpl.recipient_roles or [])

                # ── Role-based recipients (dept-scoped) ──────────────────────
                recipients = _resolve_recipients_by_roles(
                    self.db,
                    effective_roles,
                    organization_id,
                    department_id=department_id,
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
                    # ── Per-recipient context: personalise {{user.*}} vars ────
                    user_ctx = dict(resolved_ctx)
                    _fname = (user.firstname or "").strip()
                    _lname = (user.lastname or "").strip()
                    user_ctx["user.name"]  = f"{_fname} {_lname}".strip() or user.email or ""
                    user_ctx["user.email"] = user.email or ""
                    # Inject dept context from the user's active role assignment
                    try:
                        from models import OrgDepartment
                        _uur = (
                            self.db.query(OrgUserRole)
                            .filter(
                                OrgUserRole.user_id == user.id,
                                OrgUserRole.is_active.is_(True),
                                OrgUserRole.department_id.isnot(None),
                            )
                            .first()
                        )
                        if _uur and _uur.department_id and not user_ctx.get("dept.name"):
                            _udept = self.db.query(OrgDepartment).filter(
                                OrgDepartment.id == _uur.department_id
                            ).first()
                            if _udept:
                                user_ctx["dept.name"] = _udept.name or ""
                                user_ctx["dept.code"] = _udept.code or ""
                    except Exception:
                        pass

                    subject = _render(tmpl.subject_template or "", user_ctx)
                    body    = _render(tmpl.body_template,            user_ctx)

                    self._dispatch_to_user(
                        tmpl=tmpl, user=user, subject=subject, body=body,
                        event_type=event_type, organization_id=organization_id,
                        source_id=source_id, source_type=source_type, severity=severity,
                        org_name=_org_name,
                        resolved_ctx=user_ctx,
                    )

                # ── extra_recipient_emails (individual addresses on template) ─
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
                        f"[Notif] event={event_type!r} channel={tmpl.channel!r}: "
                        f"no recipients for roles {effective_roles}"
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
            dispatcher = ChannelDispatcherRegistry.get(log.channel)
            if not dispatcher:
                continue
            # email needs recipient_email; sms needs recipient_phone
            if log.channel == "email" and not log.recipient_email:
                continue
            if log.channel == "sms" and not log.recipient_phone:
                continue
            dispatcher.send(self.db, log, log.subject or "", log.body or "")
            count += 1

        if count:
            self.db.commit()
        return count

    # ── Convenience trigger methods ───────────────────────────────────────────
    # All methods extract department_id from the TR and pass it to fire()
    # so recipient resolution is automatically dept-scoped.

    # ── Context extractors (shortcuts over TestingRequest attributes) ─────────

    def _dept(self, request) -> Optional[UUID]:
        """Return department_id from a TestingRequest (or None)."""
        return getattr(request, "department_id", None)

    def _test_type(self, request) -> Optional[str]:
        """
        Return the test category type for routing rule matching.
        Reads CategoryDetails.category_type via the test_type relationship first
        (most specific), then falls back to request_category enum value.
        Values: "test" | "maintenance" | "inspection" | "repair_lifecycle"
        """
        tt = getattr(request, "test_type", None)
        if tt is not None:
            cat = getattr(tt, "category_type", None)
            if cat:
                return cat
        rc = getattr(request, "request_category", None)
        if rc is None:
            return None
        return rc.value if hasattr(rc, "value") else str(rc)

    def _workflow_type(self, request) -> Optional[str]:
        """
        Derive the workflow type from the test category — no extra column needed.
        test / maintenance / inspection → "testing_request"
        repair_lifecycle               → "repair_lifecycle"
        failure_registry               → "failure_registry"
        taqc_inspection                → "taqc_inspection"
        """
        cat = self._test_type(request)
        return {
            "test":             "testing_request",
            "maintenance":      "testing_request",
            "inspection":       "testing_request",
            "nameplate":        "testing_request",
            "repair_lifecycle": "repair_lifecycle",
            "failure_registry": "failure_registry",
            "taqc_inspection":  "taqc_inspection",
        }.get(cat or "")

    def _equipment_type(self, request) -> Optional[str]:
        """Return the equipment type name from a TestingRequest (or None)."""
        if getattr(request, "equipment_type", None):
            return getattr(request.equipment_type, "name", None)
        if getattr(request, "equipment", None):
            return getattr(getattr(request, "equipment", None), "equipment_type", None)
        return None

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
            department_id=self._dept(request),
            source_id=result.id,
            source_type="test_result",
            severity="critical",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
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
            department_id=self._dept(request),
            source_id=result.id,
            source_type="test_result",
            severity="alert",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
        )

    def notify_request_submitted(self, request) -> None:
        """Triggered when originator submits a testing request."""
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
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="submitted",
        )

    def notify_tester_assigned(self, request) -> None:
        """Triggered when a tester is assigned to a testing request."""
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
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="assigned",
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
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="results_submitted",
        )

    def notify_recommendation_approved(self, request, recommendation) -> None:
        """Triggered when a recommendation is approved."""
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
            department_id=self._dept(request),
            source_id=recommendation.id,
            source_type="recommendation",
            severity="info",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="recommendation_approved",
        )

    def notify_recommendation_rejected(self, request, rec) -> None:
        """Triggered when a Technical Approver rejects a recommendation."""
        self.fire(
            event_type="recommendation_rejected",
            context={
                "request_number": getattr(request, "request_number", ""),
                "reason": rec.approval_notes or "No reason provided",
            },
            organization_id=getattr(request, "organization_id", None),
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="alert",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="recommendation_rejected",
        )

    def notify_tester_declined(self, request, tester_name: str, reason: str) -> None:
        """Triggered when a tester declines an assignment — notifies Test Assigner."""
        self.fire(
            event_type="tester_declined",
            context={
                "request_number": getattr(request, "request_number", ""),
                "tester_name": tester_name,
                "reason": reason,
            },
            organization_id=getattr(request, "organization_id", None),
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="alert",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="tester_declined",
        )

    def notify_procurement_pending(self, request, pr_number: str) -> None:
        """Triggered when a ProcurementRequest is created — notifies Finance Approvers."""
        self.fire(
            event_type="procurement_pending",
            context={
                "request_number": getattr(request, "request_number", ""),
                "pr_number": pr_number,
                "title": getattr(request, "title", ""),
            },
            organization_id=getattr(request, "organization_id", None),
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="procurement_pending",
        )

    def notify_procurement_decision(self, request, pr_number: str, decision: str, notes: str = "") -> None:
        """Triggered when Finance Approver approves or rejects a procurement."""
        self.fire(
            event_type="procurement_decision",
            context={
                "request_number": getattr(request, "request_number", ""),
                "pr_number": pr_number,
                "decision": decision,
                "notes": notes or "",
            },
            organization_id=getattr(request, "organization_id", None),
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="info" if decision == "approved" else "alert",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="procurement_decision",
        )

    def notify_due_reminder(self, request) -> None:
        """15-day early reminder (SRS §8.2 #1) — fired by scheduler."""
        self._fire_schedule_notification(request, event_type="due_reminder", severity="info")

    def notify_due_reminder_final(self, request) -> None:
        """7-day final reminder (SRS §8.2 #2) — fired by scheduler when due within 7 days."""
        self._fire_schedule_notification(request, event_type="due_reminder_final", severity="alert")

    def notify_overdue(self, request) -> None:
        """Triggered by scheduler when due_date has passed (SRS §8.2 #3)."""
        self._fire_schedule_notification(request, event_type="overdue_alert", severity="alert")

    def notify_overdue_escalation(self, request) -> None:
        """Escalation fired when request is more than 7 days overdue (SRS §8.2 #4)."""
        self._fire_schedule_notification(request, event_type="overdue_escalation", severity="critical")

    def notify_maintenance_due(self, request) -> None:
        """15-day reminder for maintenance-type requests (SRS Notification Table)."""
        self._fire_schedule_notification(request, event_type="maintenance_due", severity="info")

    def notify_remedial_action_due(
        self, request, compliance_due_date: str, days_overdue: int,
        organization_id=None, department_id=None,
    ) -> None:
        """
        Fired when a remedial action compliance document has not been uploaded
        by the due date (SRS — Remedial Action Due).
        """
        equipment_label = (
            request.equipment.ueic if getattr(request, "equipment", None)
            else getattr(request, "equipment_type_name", "Equipment")
        )
        self.fire(
            event_type="remedial_action_due",
            context={
                "equipment":           equipment_label,
                "request_number":      getattr(request, "request_number", ""),
                "compliance_due_date": compliance_due_date,
                "days_overdue":        str(days_overdue),
            },
            organization_id=organization_id or getattr(request, "organization_id", None),
            department_id=department_id or self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="alert",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
        )

    def notify_taqc_observation_overdue(
        self, request, compliance_due_date: str, days_overdue: int,
        organization_id=None, department_id=None,
    ) -> None:
        """
        Fired when a TA&QC observation compliance upload passes its target date
        (SRS — TA&QC Observation Overdue).
        """
        equipment_label = (
            request.equipment.ueic if getattr(request, "equipment", None)
            else getattr(request, "equipment_type_name", "Equipment")
        )
        self.fire(
            event_type="taqc_observation_overdue",
            context={
                "equipment":           equipment_label,
                "request_number":      getattr(request, "request_number", ""),
                "compliance_due_date": compliance_due_date,
                "days_overdue":        str(days_overdue),
            },
            organization_id=organization_id or getattr(request, "organization_id", None),
            department_id=department_id or self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="alert",
            workflow_type="taqc",
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
        )

    def notify_overhaul_recommended(
        self, equipment, operation_count: int, operation_threshold: int,
        organization_id=None, department_id=None,
    ) -> None:
        """
        Fired when equipment operation count exceeds overhaul threshold
        (SRS — Overhaul Recommendation).
        """
        from models import Equipment as _Eq
        ueic     = getattr(equipment, "ueic",         "N/A")
        eq_type  = getattr(equipment, "equipment_type_name", "Equipment")
        dept     = getattr(equipment, "department_name", "")
        self.fire(
            event_type="overhaul_recommended",
            context={
                "equipment":           ueic,
                "equipment_type":      eq_type,
                "department":          dept,
                "operation_count":     str(operation_count),
                "operation_threshold": str(operation_threshold),
            },
            organization_id=organization_id or getattr(equipment, "organization_id", None),
            department_id=department_id,
            source_id=getattr(equipment, "id", None),
            source_type="equipment",
            severity="alert",
            workflow_type="repair_cycle",
            equipment_type=eq_type,
        )

    def notify_equipment_registered(
        self, equipment, commissioned_by: str,
        organization_id=None, department_id=None,
    ) -> None:
        """
        Fired when a new equipment record is created in the Equipment Register
        (SRS — Equipment Register: New).
        """
        ueic    = getattr(equipment, "ueic", "N/A")
        eq_type = getattr(equipment, "equipment_type_name", "Equipment")
        dept    = getattr(equipment, "department_name", "")
        mfr     = getattr(equipment, "manufacturer", "")
        self.fire(
            event_type="equipment_registered",
            context={
                "equipment":       ueic,
                "equipment_type":  eq_type,
                "department":      dept,
                "manufacturer":    mfr,
                "commissioned_by": commissioned_by,
            },
            organization_id=organization_id or getattr(equipment, "organization_id", None),
            department_id=department_id,
            source_id=getattr(equipment, "id", None),
            source_type="equipment",
            severity="info",
        )

    def notify_equipment_retired(
        self, equipment, retired_by: str, reason: str,
        organization_id=None, department_id=None,
    ) -> None:
        """
        Fired when equipment is decommissioned/retired from the register
        (SRS — Equipment Register: Retired).
        """
        ueic    = getattr(equipment, "ueic", "N/A")
        eq_type = getattr(equipment, "equipment_type_name", "Equipment")
        dept    = getattr(equipment, "department_name", "")
        self.fire(
            event_type="equipment_retired",
            context={
                "equipment":      ueic,
                "equipment_type": eq_type,
                "department":     dept,
                "reason":         reason,
                "retired_by":     retired_by,
            },
            organization_id=organization_id or getattr(equipment, "organization_id", None),
            department_id=department_id,
            source_id=getattr(equipment, "id", None),
            source_type="equipment",
            severity="info",
        )

    def notify_design_problem_alert(
        self, manufacturer: str, equipment_type: str,
        problem_description: str, affected_count: int,
        organization_id=None,
    ) -> None:
        """
        Fired when a systemic design problem is identified for a make/model
        (SRS — Design Problem Alert). Broadcasts org-wide (no dept scoping).
        """
        self.fire(
            event_type="design_problem_alert",
            context={
                "manufacturer":        manufacturer,
                "equipment_type":      equipment_type,
                "problem_description": problem_description,
                "affected_count":      str(affected_count),
            },
            organization_id=organization_id,
            severity="critical",
            equipment_type=equipment_type,
        )

    def notify_repair_delay(
        self, equipment, repair_stage: str, stage_deadline: str, days_delayed: int,
        organization_id=None, department_id=None,
    ) -> None:
        """
        Fired when a repair stage timeline is exceeded (SRS — Transformer Repair Delay).
        """
        ueic    = getattr(equipment, "ueic", "N/A")
        eq_type = getattr(equipment, "equipment_type_name", "Equipment")
        dept    = getattr(equipment, "department_name", "")
        self.fire(
            event_type="repair_delay",
            context={
                "equipment":      ueic,
                "equipment_type": eq_type,
                "department":     dept,
                "repair_stage":   repair_stage,
                "stage_deadline": stage_deadline,
                "days_delayed":   str(days_delayed),
            },
            organization_id=organization_id or getattr(equipment, "organization_id", None),
            department_id=department_id,
            source_id=getattr(equipment, "id", None),
            source_type="equipment",
            severity="alert",
            workflow_type="repair_cycle",
            equipment_type=eq_type,
        )

    def notify_monthly_mis_report(
        self, report_month: str, tests_completed: int,
        critical_count: int, overdue_count: int,
        report_pdf_url: str = "", report_xls_url: str = "",
        organization_id=None,
    ) -> None:
        """
        Fired on the first working day of each month — generates and sends the
        Monthly MIS Report to senior management (SRS — Monthly MIS Reports).
        """
        from datetime import date as _d
        self.fire(
            event_type="monthly_mis_report",
            context={
                "report_month":     report_month,
                "tests_completed":  str(tests_completed),
                "critical_count":   str(critical_count),
                "overdue_count":    str(overdue_count),
                "report_pdf_url":   report_pdf_url,
                "pdf_url":          report_pdf_url,
                "report_xls_url":   report_xls_url,
                "xls_url":          report_xls_url,
                "report_generated_on": str(_d.today()),
            },
            organization_id=organization_id,
            severity="info",
        )

    def _fire_schedule_notification(self, request, event_type: str, severity: str) -> None:
        """
        Shared helper for all scheduler-fired notifications.
        Builds standard context from the TR's due_date and fires dept + workflow scoped.
        """
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        from datetime import date as _date
        due = getattr(request, "due_date", None)
        today = _date.today()
        if due:
            due_date = due.date() if hasattr(due, "date") else due
            days_diff = (today - due_date).days   # positive = overdue, negative = remaining
        else:
            days_diff = 0
        self.fire(
            event_type=event_type,
            context={
                "equipment": equipment_label,
                "request_number": getattr(request, "request_number", ""),
                "due_date": str(due or ""),
                "days_remaining": str(-days_diff) if days_diff < 0 else "0",
                "days_overdue":   str(days_diff)  if days_diff > 0 else "0",
            },
            organization_id=getattr(request, "organization_id", None),
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity=severity,
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
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
        org_name: str = "SEACMS",
        resolved_ctx: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Enqueue a notification for one user on one channel using the
        ChannelDispatcherRegistry factory.

        Channel behaviour
        -----------------
        inapp  — written immediately to UserNotification (DB-only, instant).
                 Log is marked 'sent' right away.
        email  — body is wrapped in full HTML email template via EmailDispatcher.
                 Log written as 'pending'; background scheduler sends.
                 If tmpl.attachment_vars is set, URLs resolved from context are
                 stored in log.attachment_urls for the dispatcher to fetch + attach.
        sms    — plain-text body stored as-is.
                 Log written as 'pending'; background scheduler sends.
        <any>  — any future channel (e.g. whatsapp) registered in
                 ChannelDispatcherRegistry is automatically picked up here
                 without changes to this method.

        attachment_vars format (per entry — supports both simple and typed):
          Simple : "report.retriepdf"           — type auto-detected from URL/key
          Typed  : {"var_key": "report.retriepdf", "type": "pdf"}
                   Supported types: pdf | excel | xlsx | docx | json | csv | txt | zip
        """
        dispatcher = ChannelDispatcherRegistry.get(tmpl.channel)

        # ── Channel-specific body transformation (e.g. full HTML wrap for email)
        final_body = body
        if dispatcher:
            final_body = dispatcher.prepare_body(body, subject=subject, org_name=org_name)

        # ── Resolve attachment_vars → attachment_urls (email channel only) ─────
        # Strategy:
        #   • If var_key resolves to a URL in context → store {url, type}  (legacy)
        #   • If no URL but type=pdf/excel → store {type, source_type, source_id}
        #     so the EmailDispatcher scheduler generates the file in-memory at send time.
        resolved_attachment_urls: List[Dict] = []
        if tmpl.channel == "email" and tmpl.attachment_vars and resolved_ctx:
            for av in (tmpl.attachment_vars or []):
                if isinstance(av, dict):
                    var_key  = av.get("var_key", "")
                    att_type = (av.get("type") or "").lower()
                else:
                    var_key  = str(av)
                    att_type = ""
                url = resolved_ctx.get(var_key, "")
                if url:
                    entry: Dict[str, str] = {"url": url, "var_key": var_key}
                    if att_type:
                        entry["type"] = att_type
                    resolved_attachment_urls.append(entry)
                elif att_type in ("pdf", "excel", "xlsx") and source_type and source_id:
                    # No URL — schedule in-memory generation at send time
                    resolved_attachment_urls.append({
                        "type":        att_type,
                        "var_key":     var_key,
                        "source_type": str(source_type),
                        "source_id":   str(source_id),
                    })
                else:
                    logger.debug(
                        f"[Notif] attachment_var {var_key!r} resolved to empty for "
                        f"event={event_type!r} user={user.id}"
                    )

        log = NotificationLog(
            organization_id=organization_id,
            event_type=event_type,
            channel=tmpl.channel,
            recipient_id=user.id,
            recipient_email=user.email if tmpl.channel == "email" else None,
            recipient_phone=getattr(user, "phone_number", None) if tmpl.channel == "sms" else None,
            subject=subject,
            body=final_body,
            status="pending",
            source_id=source_id,
            source_type=source_type,
            attachment_urls=resolved_attachment_urls if resolved_attachment_urls else [],
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
                body=body,          # in-app uses plain body (no HTML wrapper)
                severity=severity,
                source_id=source_id,
                source_type=source_type,
            )
            log.status = "sent"
            log.sent_at = datetime.now(timezone.utc)

        elif tmpl.channel in ChannelDispatcherRegistry.channels():
            # Async channels (email, sms, whatsapp, …): leave as 'pending'
            # Validate contact info; skip immediately if missing
            if tmpl.channel == "email" and not user.email:
                log.status = "skipped"
                log.error_message = "User has no email address"
            elif tmpl.channel == "sms" and not getattr(user, "phone_number", None):
                log.status = "skipped"
                log.error_message = "User has no phone number"
            # else: stays 'pending' — scheduler picks up and calls dispatcher.send()

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
            # ── Digest check (email only) ────────────────────────────────────
            if log.channel == "email":
                if not log.recipient_email:
                    log.status = "skipped"
                    log.error_message = "No email address on log row"
                    skipped += 1
                    continue
                if _should_digest(self.db, log.event_type, log.organization_id):
                    _collapse_digest(self.db, log.event_type, log.organization_id)
                    skipped += 1
                    continue

            elif log.channel == "sms":
                # Backfill phone from user record if missing on log row
                if not log.recipient_phone and log.recipient_id:
                    u = self.db.query(User).filter(User.id == log.recipient_id).first()
                    if u:
                        log.recipient_phone = getattr(u, "phone_number", None)
                if not log.recipient_phone:
                    log.status = "skipped"
                    log.error_message = "No phone number found"
                    skipped += 1
                    continue

            # ── Dispatch via registry (works for any registered channel) ─────
            dispatcher = ChannelDispatcherRegistry.get(log.channel)
            if not dispatcher:
                log.status = "skipped"
                log.error_message = f"No dispatcher registered for channel={log.channel!r}"
                skipped += 1
                continue

            dispatcher.send(self.db, log, log.subject or "", log.body or "")

            if log.status == "sent":
                sent += 1
            elif log.status in ("skipped",):
                skipped += 1
            else:
                failed += 1

        try:
            self.db.commit()
        except Exception as exc:
            logger.error(f"[Notif] process_pending commit failed: {exc}")
            self.db.rollback()

        return {"sent": sent, "failed": failed, "skipped": skipped, "total": len(pending)}


# ── Global default template seeds ─────────────────────────────────────────────

def _e(subject: str, body_html: str, roles: list) -> dict:
    """Helper: email channel entry."""
    return {"channel": "email", "subject_template": subject,
            "body_template": body_html, "recipient_roles": roles,
            "attachment_vars": []}

def _ea(subject: str, body_html: str, roles: list, attachment_vars: list) -> dict:
    """
    Helper: email channel entry WITH attachment variables.

    attachment_vars — list of variable entries whose resolved values are file URLs
    to attach to the outgoing email.  Each entry is either:
      • a simple string  : "report.retriepdf"
                           (MIME type auto-detected from URL / key convention)
      • a typed dict     : {"var_key": "report.retriepdf", "type": "pdf"}
                           Supported types: pdf | excel | xlsx | docx | json | csv

    Example:
        _ea(
            "Monthly MIS Report — {{report.ref}}",
            body_html,
            ["SEE W&M", "CEE Transmission Zone"],
            [
                {"var_key": "report.retriepdf",  "type": "pdf"},
                {"var_key": "report.retriexls",  "type": "excel"},
            ],
        )
    """
    return {"channel": "email", "subject_template": subject,
            "body_template": body_html, "recipient_roles": roles,
            "attachment_vars": attachment_vars}

def _s(body: str, roles: list) -> dict:
    """Helper: SMS channel entry (160-char guideline)."""
    return {"channel": "sms", "subject_template": "",
            "body_template": body, "recipient_roles": roles}

def _i(title: str, body: str, roles: list) -> dict:
    """Helper: in-app channel entry."""
    return {"channel": "inapp", "subject_template": title,
            "body_template": body, "recipient_roles": roles}

def _html(rows: list) -> str:
    """
    Build a compact HTML table from [(label, var_key), ...] pairs.
    var_key is wrapped in {{double_braces}} so the render engine resolves it.
    Example: _html([("Equipment", "equipment.ueic")]) →
             <tr>…<td>{{equipment.ueic}}</td>…</tr>
    """
    trs = "".join(
        "<tr>"
        "<td style='padding:4px 8px;border:1px solid #ddd'><b>" + str(k) + "</b></td>"
        "<td style='padding:4px 8px;border:1px solid #ddd'>{{" + str(v) + "}}</td>"
        "</tr>"
        for k, v in rows
    )
    return (
        "<table cellspacing='0' style='border-collapse:collapse;"
        "font-size:13px;width:100%'>"
        + trs
        + "</table>"
    )


# All 15 catalogue event types — 3 channels each (email + SMS + in-app).
# subject_template / body_template use {{var_key}} syntax (double-brace).
# Org admins can override any of these via the Flutter Template Config page.
DEFAULT_TEMPLATES = []

def _tmpl(event_type: str, *channel_dicts) -> None:
    for d in channel_dicts:
        DEFAULT_TEMPLATES.append({"event_type": event_type, **d})

# ── Equipment ─────────────────────────────────────────────────────────────────
_tmpl("equipment_replacement",
    _e(
        "[REPLACEMENT] {{equipment.type}} — {{old_ueic}} → {{new_ueic}}",
        "<h3 style='color:#1E3C72'>Equipment Replacement Notification</h3>"
        "<p>A replacement event has been recorded in SEACMS on {{system.date}}.</p>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Retired UEIC</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{old_ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>New UEIC</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{new_ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Substation / Bay</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{reason_type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{reason}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Replaced By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{replaced_by}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{replaced_on}}</td></tr>"
        "</table>"
        "<p>Log in to SEACMS Equipment Register to download the Replacement Report PDF.</p>",
        ["EE TLSS", "SEE W&M", "CEE Transmission Zone", "Department Head"],
    ),
    _s(
        "[KPTCL-SEACMS] {{equipment.type}} at {{equipment.department}} replaced."
        " Old:{{old_ueic}} New:{{new_ueic}}. By {{replaced_by}} on {{replaced_on}}.",
        ["EE TLSS", "SEE W&M", "CEE Transmission Zone"],
    ),
    _i(
        "Equipment replaced — {{old_ueic}} → {{new_ueic}}",
        "{{equipment.type}} at {{equipment.department}} replaced by {{replaced_by}} on {{replaced_on}}."
        " Reason: {{reason_type}}.",
        ["EE TLSS", "SEE W&M", "CEE Transmission Zone", "Department Head"],
    ),
)

# ── Evaluation ────────────────────────────────────────────────────────────────
_tmpl("eval_critical",
    _ea(
        "[CRITICAL] {{equipment.ueic}} — {{eval.test_type}} Threshold Exceeded",
        "<h3 style='color:red'>Critical Test Result — Immediate Action Required</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.test_type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Overall Result</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.overall}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Evaluated At</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.evaluated_at}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Finding</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{result_summary}}</td></tr>"
        "</table>"
        "<p>The evaluation report is attached to this email.</p>",
        ["EE TLSS", "SEE W&M", "CEE Transmission Zone", "AEE Maintenance"],
        [{"var_key": "report.retriepdf", "type": "pdf"}],
    ),
    _s(
        "[KPTCL-SEACMS] CRITICAL: {{equipment.ueic}} — {{eval.test_type}}."
        " Req:{{request.number}}. Login SEACMS for details.",
        ["EE TLSS", "AEE Maintenance"],
    ),
    _i(
        "CRITICAL — {{equipment.ueic}}",
        "{{eval.test_type}} result CRITICAL for {{equipment.ueic}} ({{request.number}})."
        " Evaluated: {{eval.evaluated_at}}.",
        ["EE TLSS", "SEE W&M", "CEE Transmission Zone", "AEE Maintenance"],
    ),
)

_tmpl("eval_alert",
    _e(
        "[ALERT] {{equipment.ueic}} — {{eval.test_type}} Warning",
        "<h3 style='color:orange'>Alert: Test Result Warning</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.test_type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Overall Result</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.overall}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Revised Interval</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{revised_interval}}</td></tr>"
        "</table>"
        "<p><a href='{{report.retriepdf}}'>Download PDF Report</a></p>",
        ["EE TLSS", "AEE Maintenance"],
    ),
    _s(
        "[KPTCL-SEACMS] ALERT: {{equipment.ueic}} — {{eval.test_type}}."
        " Revised interval: {{revised_interval}}. Req:{{request.number}}.",
        ["EE TLSS", "AEE Maintenance"],
    ),
    _i(
        "Alert — {{equipment.ueic}}",
        "{{eval.test_type}} threshold warning for {{equipment.ueic}}."
        " Revised interval: {{revised_interval}}.",
        ["EE TLSS", "AEE Maintenance"],
    ),
)

# ── Test Workflow ─────────────────────────────────────────────────────────────
_tmpl("request_submitted",
    _e(
        "New Test Request Submitted — {{request.number}}",
        "<h3>New Test Request Awaiting Approval</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Category</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{category}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Priority</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.priority}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Submitted By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.submitted_by}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "</table>"
        "<p>Log in to SEACMS to review and approve this request.</p>",
        ["EE TLSS", "Department Head"],
    ),
    _s(
        "[KPTCL-SEACMS] New {{category}} request {{request.number}} submitted"
        " by {{request.submitted_by}} for {{equipment.ueic}}. Login to approve.",
        ["EE TLSS"],
    ),
    _i(
        "New submission — {{request.number}}",
        "{{equipment.ueic}} submitted for {{category}} by {{request.submitted_by}}. Priority: {{request.priority}}.",
        ["EE TLSS", "Department Head"],
    ),
)

_tmpl("tester_assigned",
    _e(
        "Test Request Assigned to You — {{request.number}}",
        "<h3>You Have Been Assigned a Test Request</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Due Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.due_date}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Assigned To</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.assigned_to}}</td></tr>"
        "</table>"
        "<p>Please log in to SEACMS to accept or decline this assignment.</p>",
        ["Tester", "AEE Maintenance"],
    ),
    _s(
        "[KPTCL-SEACMS] You are assigned test req {{request.number}}"
        " for {{equipment.ueic}}. Due: {{request.due_date}}. Login SEACMS.",
        ["Tester"],
    ),
    _i(
        "Assigned — {{request.number}}",
        "You have been assigned {{request.number}} for {{equipment.ueic}}. Due: {{request.due_date}}.",
        ["Tester", "AEE Maintenance"],
    ),
)

_tmpl("tester_declined",
    _e(
        "Tester Declined Assignment — {{request.number}}",
        "<h3>Tester Declined — Reassignment Required</h3>"
        "<p><b>Request:</b> {{request.number}}</p>"
        "<p><b>Declined by:</b> {{tester_name}}</p>"
        "<p><b>Reason:</b> {{reason}}</p>"
        "<p>Please reassign this request in SEACMS.</p>",
        ["TestAssigner", "EE TLSS"],
    ),
    _s(
        "[KPTCL-SEACMS] {{tester_name}} declined req {{request.number}}."
        " Reason: {{reason}}. Please reassign.",
        ["TestAssigner"],
    ),
    _i(
        "Tester declined — {{request.number}}",
        "{{tester_name}} declined {{request.number}}. Reason: {{reason}}.",
        ["TestAssigner", "EE TLSS"],
    ),
)

_tmpl("test_submitted",
    _ea(
        "Test Results Ready for Review — {{request.number}}",
        "<h3>Test Results Submitted — Awaiting Your Review</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Overall Result</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.overall}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Submitted By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.submitted_by}}</td></tr>"
        "</table>"
        "<p>The test report is attached to this email.</p>"
        "<p>Log in to SEACMS to approve or reject these results.</p>",
        ["EE TLSS", "Department Head"],
        [{"var_key": "report.retriepdf", "type": "pdf"}],
    ),
    _s(
        "[KPTCL-SEACMS] Results submitted for {{request.number}} ({{equipment.ueic}})."
        " Result: {{eval.overall}}. Login SEACMS to review.",
        ["EE TLSS"],
    ),
    _i(
        "Results submitted — {{request.number}}",
        "Test results for {{equipment.ueic}} ({{request.number}}) await review. Result: {{eval.overall}}.",
        ["EE TLSS", "Department Head"],
    ),
)

_tmpl("recommendation_approved",
    _e(
        "Recommendation Approved — {{request.number}}",
        "<h3>Equipment Recommendation Approved</h3>"
        "<p><b>Request:</b> {{request.number}}</p>"
        "<p><b>Recommendation Type:</b> {{recommendation_type}}</p>"
        "<p><b>Replacement Products:</b> {{product_count}}</p>"
        "<p>Log in to SEACMS to proceed with procurement.</p>",
        ["Originator", "AEE Maintenance"],
    ),
    _s(
        "[KPTCL-SEACMS] Recommendation approved for {{request.number}}."
        " Type: {{recommendation_type}}. Login SEACMS.",
        ["Originator"],
    ),
    _i(
        "Recommendation approved — {{request.number}}",
        "{{recommendation_type}} recommendation approved. {{product_count}} product(s) for procurement.",
        ["Originator", "AEE Maintenance"],
    ),
)

_tmpl("recommendation_rejected",
    _e(
        "Recommendation Rejected — {{request.number}}",
        "<h3>Recommendation Rejected — Action Required</h3>"
        "<p><b>Request:</b> {{request.number}}</p>"
        "<p><b>Reason:</b> {{reason}}</p>"
        "<p>Please revise and resubmit your recommendation in SEACMS.</p>",
        ["Tester", "Originator"],
    ),
    _s(
        "[KPTCL-SEACMS] Recommendation for {{request.number}} rejected."
        " Reason: {{reason}}. Please revise.",
        ["Tester"],
    ),
    _i(
        "Recommendation rejected — {{request.number}}",
        "Recommendation rejected. Reason: {{reason}}.",
        ["Tester", "Originator"],
    ),
)

# ── Scheduling ────────────────────────────────────────────────────────────────
_tmpl("due_reminder",
    _e(
        "Test Due in {{days_remaining}} Days — {{equipment.ueic}}",
        "<h3>Upcoming Test Due — 15-Day Reminder</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Due Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.due_date}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Remaining</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_remaining}}</td></tr>"
        "</table>"
        "<p>Please ensure the test is scheduled and resources are allocated.</p>",
        ["AEE Maintenance", "EE TLSS"],
    ),
    _s(
        "[KPTCL-SEACMS] Test due in {{days_remaining}} days for {{equipment.ueic}}"
        " ({{equipment.department}}). Due: {{request.due_date}}.",
        ["AEE Maintenance"],
    ),
    _i(
        "Test due in {{days_remaining}} days — {{equipment.ueic}}",
        "Request {{request.number}} for {{equipment.ueic}} is due on {{request.due_date}}.",
        ["AEE Maintenance", "EE TLSS"],
    ),
)

_tmpl("due_reminder_final",
    _e(
        "FINAL REMINDER: Test Due in {{days_remaining}} Days — {{equipment.ueic}}",
        "<h3 style='color:orange'>Final Reminder — Test Due in {{days_remaining}} Days</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Due Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.due_date}}</td></tr>"
        "</table>"
        "<p><b>Action required:</b> Test must be completed by {{request.due_date}}.</p>",
        ["AEE Maintenance", "EE TLSS", "Department Head"],
    ),
    _s(
        "[KPTCL-SEACMS] FINAL REMINDER: Test for {{equipment.ueic}} due {{request.due_date}}"
        " ({{days_remaining}} days). Dept: {{equipment.department}}.",
        ["AEE Maintenance", "EE TLSS"],
    ),
    _i(
        "Final reminder — {{equipment.ueic}} due {{request.due_date}}",
        "Only {{days_remaining}} days left. Request {{request.number}} must be completed by {{request.due_date}}.",
        ["AEE Maintenance", "EE TLSS", "Department Head"],
    ),
)

_tmpl("overdue_alert",
    _e(
        "[OVERDUE] Test Not Completed — {{equipment.ueic}} ({{days_overdue}} days)",
        "<h3 style='color:red'>Test Overdue — Immediate Action Required</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Was Due</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.due_date}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Overdue</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_overdue}}</td></tr>"
        "</table>"
        "<p>Please take immediate action to complete or reschedule this test.</p>",
        ["EE TLSS", "AEE Maintenance", "SEE W&M"],
    ),
    _s(
        "[KPTCL-SEACMS] OVERDUE: Test for {{equipment.ueic}} ({{equipment.department}})"
        " is {{days_overdue}} days overdue. Req: {{request.number}}.",
        ["EE TLSS", "AEE Maintenance"],
    ),
    _i(
        "Overdue {{days_overdue}} days — {{equipment.ueic}}",
        "Test {{request.number}} for {{equipment.ueic}} is overdue by {{days_overdue}} days (was due {{request.due_date}}).",
        ["EE TLSS", "AEE Maintenance", "SEE W&M"],
    ),
)

_tmpl("overdue_escalation",
    _e(
        "[ESCALATION] Test {{days_overdue}} Days Overdue — {{equipment.ueic}}",
        "<h3 style='color:darkred'>Escalation: Test Critically Overdue</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Overdue</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_overdue}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "</table>"
        "<p>This has been escalated to zone/circle management.</p>",
        ["SEE W&M", "CEE Transmission Zone"],
    ),
    _s(
        "[KPTCL-SEACMS] ESCALATION: {{equipment.ueic}} test {{days_overdue}}d overdue."
        " Dept: {{equipment.department}}. Req: {{request.number}}.",
        ["SEE W&M", "CEE Transmission Zone"],
    ),
    _i(
        "Escalation — {{equipment.ueic}} {{days_overdue}}d overdue",
        "Critical: {{request.number}} for {{equipment.ueic}} is {{days_overdue}} days overdue.",
        ["SEE W&M", "CEE Transmission Zone"],
    ),
)

# ── Procurement ───────────────────────────────────────────────────────────────
_tmpl("procurement_pending",
    _e(
        "Procurement Request Raised — {{pr_number}}",
        "<h3>New Procurement Request Awaiting Finance Approval</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>PR Number</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{pr_number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Title</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{title}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
        "</table>"
        "<p>Log in to SEACMS to approve or reject this procurement request.</p>",
        ["FinanceApprover", "Department Head"],
    ),
    _s(
        "[KPTCL-SEACMS] Procurement {{pr_number}} raised for {{request.number}}."
        " Awaiting your finance approval. Login SEACMS.",
        ["FinanceApprover"],
    ),
    _i(
        "Procurement raised — {{pr_number}}",
        "PR {{pr_number}} for test request {{request.number}} is awaiting finance approval.",
        ["FinanceApprover", "Department Head"],
    ),
)

_tmpl("procurement_decision",
    _e(
        "Procurement {{decision|upper}} — {{pr_number}}",
        "<h3>Procurement Decision: {{decision|upper}}</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>PR Number</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{pr_number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Decision</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{decision}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Notes</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{notes}}</td></tr>"
        "</table>",
        ["Originator", "TechApprover", "EE TLSS"],
    ),
    _s(
        "[KPTCL-SEACMS] Procurement {{pr_number}} {{decision}}."
        " Req: {{request.number}}. Notes: {{notes}}.",
        ["Originator"],
    ),
    _i(
        "Procurement {{decision}} — {{pr_number}}",
        "PR {{pr_number}} ({{request.number}}) has been {{decision}} by Finance. Notes: {{notes}}.",
        ["Originator", "TechApprover", "EE TLSS"],
    ),
)


# ── Equipment Lifecycle ───────────────────────────────────────────────────────
_tmpl("equipment_registered",
    _e(
        "[NEW EQUIPMENT] {{equipment.ueic}} Commissioned — {{equipment.type}}",
        "<h3 style='color:#1E3C72'>New Equipment Registered in SEACMS</h3>"
        "<p>A new equipment record has been created on {{system.date}}.</p>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>UEIC</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Manufacturer</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.manufacturer}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Substation / Bay</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Commissioned By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{commissioned_by}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
        "</table>"
        "<p>Log in to SEACMS to review the equipment details and configure test schedules.</p>",
        ["AEE Maintenance", "EE TLSS", "Department Head"],
    ),
    _s(
        "[KPTCL-SEACMS] New equipment registered: {{equipment.ueic}} ({{equipment.type}})"
        " at {{equipment.department}} on {{system.date}} by {{commissioned_by}}.",
        ["AEE Maintenance", "EE TLSS"],
    ),
    _i(
        "New equipment — {{equipment.ueic}}",
        "{{equipment.type}} ({{equipment.ueic}}) commissioned at {{equipment.department}} by {{commissioned_by}}.",
        ["AEE Maintenance", "EE TLSS", "Department Head"],
    ),
)

_tmpl("equipment_retired",
    _e(
        "[RETIRED] {{equipment.ueic}} — {{equipment.type}} Decommissioned",
        "<h3 style='color:#555'>Equipment Retired from Service</h3>"
        "<p>The following equipment has been decommissioned on {{system.date}}.</p>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>UEIC</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Substation / Bay</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{reason}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Retired By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{retired_by}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
        "</table>"
        "<p>All pending test schedules for this equipment have been cancelled. Log in to SEACMS to confirm.</p>",
        ["AEE Maintenance", "EE TLSS", "SEE W&M", "Department Head"],
    ),
    _s(
        "[KPTCL-SEACMS] Equipment {{equipment.ueic}} ({{equipment.type}}) at"
        " {{equipment.department}} RETIRED on {{system.date}}. Reason: {{reason}}.",
        ["AEE Maintenance", "EE TLSS"],
    ),
    _i(
        "Equipment retired — {{equipment.ueic}}",
        "{{equipment.type}} ({{equipment.ueic}}) at {{equipment.department}} has been decommissioned. Reason: {{reason}}.",
        ["AEE Maintenance", "EE TLSS", "SEE W&M", "Department Head"],
    ),
)

# ── Remedial / Compliance ─────────────────────────────────────────────────────
_tmpl("remedial_action_due",
    _e(
        "[ACTION REQUIRED] Remedial Compliance Not Uploaded — {{request.number}}",
        "<h3 style='color:red'>Remedial Action Compliance Overdue</h3>"
        "<p>The remedial action compliance document for the following request has not been uploaded by the due date.</p>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Compliance Due</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{compliance_due_date}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Overdue</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_overdue}}</td></tr>"
        "</table>"
        "<p>Please upload the compliance proof immediately in SEACMS.</p>",
        ["Field Officer", "EE TLSS"],
    ),
    _s(
        "[KPTCL-SEACMS] Remedial compliance NOT uploaded for {{request.number}}"
        " ({{equipment.ueic}}). Due: {{compliance_due_date}}. Upload in SEACMS.",
        ["Field Officer", "EE TLSS"],
    ),
    _i(
        "Remedial compliance overdue — {{request.number}}",
        "Compliance for {{request.number}} ({{equipment.ueic}}) was due {{compliance_due_date}} and is now {{days_overdue}} day(s) overdue.",
        ["Field Officer", "EE TLSS"],
    ),
)

_tmpl("taqc_observation_overdue",
    _e(
        "[TAQC] Observation Compliance Not Uploaded — {{request.number}}",
        "<h3 style='color:orange'>TA&amp;QC Observation Compliance Overdue</h3>"
        "<p>The compliance document for a TA&amp;QC observation has not been uploaded by the target date.</p>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Target Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{compliance_due_date}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Overdue</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_overdue}}</td></tr>"
        "</table>"
        "<p>Please upload the compliance document in SEACMS immediately.</p>",
        ["EE TLSS", "SEE W&M", "CEE Transmission Zone"],
    ),
    _s(
        "[KPTCL-SEACMS] TA&QC compliance NOT uploaded. Req:{{request.number}}"
        " ({{equipment.ueic}}). Target: {{compliance_due_date}}. Upload in SEACMS.",
        ["EE TLSS", "SEE W&M"],
    ),
    _i(
        "TA&QC compliance overdue — {{request.number}}",
        "Observation compliance for {{request.number}} ({{equipment.ueic}}) is {{days_overdue}} day(s) past target {{compliance_due_date}}.",
        ["EE TLSS", "SEE W&M", "CEE Transmission Zone"],
    ),
)

# ── Maintenance ───────────────────────────────────────────────────────────────
_tmpl("maintenance_due",
    _e(
        "Maintenance Due in {{days_remaining}} Days — {{equipment.ueic}}",
        "<h3 style='color:#1E3C72'>Upcoming Maintenance Due — 15-Day Reminder</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Due Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.due_date}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Remaining</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_remaining}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
        "</table>"
        "<p>Please ensure maintenance resources and outage window are scheduled.</p>",
        ["AEE Maintenance", "Nodal Officer"],
    ),
    _s(
        "[KPTCL-SEACMS] Maintenance due in {{days_remaining}} days for {{equipment.ueic}}"
        " at {{equipment.department}}. Due: {{request.due_date}}.",
        ["AEE Maintenance", "Nodal Officer"],
    ),
    _i(
        "Maintenance due in {{days_remaining}} days — {{equipment.ueic}}",
        "Request {{request.number}} for {{equipment.ueic}} maintenance is due on {{request.due_date}}.",
        ["AEE Maintenance", "Nodal Officer"],
    ),
)

_tmpl("overhaul_recommended",
    _e(
        "[OVERHAUL] Operation Count Threshold Reached — {{equipment.ueic}}",
        "<h3 style='color:darkorange'>Overhaul Recommendation — Operation Threshold Exceeded</h3>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Operations Count</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{operation_count}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Threshold</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{operation_threshold}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Recommendation Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
        "</table>"
        "<p>An overhaul is recommended. Please raise a maintenance request in SEACMS.</p>",
        ["AEE Maintenance", "EE TLSS", "SEE W&M"],
    ),
    _s(
        "[KPTCL-SEACMS] Overhaul needed: {{equipment.ueic}} ({{equipment.type}}) at"
        " {{equipment.department}}. Operations: {{operation_count}}/{{operation_threshold}}.",
        ["AEE Maintenance", "EE TLSS"],
    ),
    _i(
        "Overhaul recommended — {{equipment.ueic}}",
        "{{equipment.type}} ({{equipment.ueic}}) has reached {{operation_count}} operations (threshold: {{operation_threshold}}). Overhaul recommended.",
        ["AEE Maintenance", "EE TLSS", "SEE W&M"],
    ),
)

# ── Design / Systemic Issues ──────────────────────────────────────────────────
_tmpl("design_problem_alert",
    _e(
        "[DESIGN ALERT] Problem Detected on {{equipment.manufacturer}} {{equipment.type}}",
        "<h3 style='color:darkred'>Design Problem Alert — All Affected Equipment</h3>"
        "<p>A systemic design problem has been identified linked to a specific make/model.</p>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Manufacturer</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.manufacturer}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Problem Description</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{problem_description}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Affected Count</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{affected_count}} units</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Identified On</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
        "</table>"
        "<p>Inspect all {{equipment.type}} units of this make immediately. Log in to SEACMS for the affected equipment list.</p>",
        ["AEE Maintenance", "EE TLSS", "SEE W&M", "Department Head"],
    ),
    _s(
        "[KPTCL-SEACMS] DESIGN ALERT: {{equipment.manufacturer}} {{equipment.type}}."
        " {{affected_count}} units affected. Problem: {{problem_description}}. Login SEACMS.",
        ["AEE Maintenance", "EE TLSS"],
    ),
    _i(
        "Design problem — {{equipment.manufacturer}} {{equipment.type}}",
        "Systemic problem detected on {{equipment.manufacturer}} {{equipment.type}}: {{problem_description}}. {{affected_count}} unit(s) affected.",
        ["AEE Maintenance", "EE TLSS", "SEE W&M", "Department Head"],
    ),
)

# ── Repair Cycle ──────────────────────────────────────────────────────────────
_tmpl("repair_delay",
    _e(
        "[REPAIR DELAY] Stage Timeline Exceeded — {{equipment.ueic}}",
        "<h3 style='color:darkorange'>Transformer Repair Delay Alert</h3>"
        "<p>A repair stage has exceeded its scheduled timeline.</p>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Repair Stage</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{repair_stage}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Stage Deadline</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{stage_deadline}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Delayed</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_delayed}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
        "</table>"
        "<p>Please review and update the repair timeline in SEACMS.</p>",
        ["EE TLSS", "CEE Transmission Zone", "CEE RT&R&D"],
    ),
    _s(
        "[KPTCL-SEACMS] REPAIR DELAY: {{equipment.ueic}} stage '{{repair_stage}}'"
        " is {{days_delayed}} days overdue (deadline: {{stage_deadline}}).",
        ["EE TLSS", "CEE Transmission Zone"],
    ),
    _i(
        "Repair delay — {{equipment.ueic}} ({{repair_stage}})",
        "Repair stage '{{repair_stage}}' for {{equipment.ueic}} is {{days_delayed}} day(s) past deadline {{stage_deadline}}.",
        ["EE TLSS", "CEE Transmission Zone", "CEE RT&R&D"],
    ),
)

# ── Reports ───────────────────────────────────────────────────────────────────
_tmpl("monthly_mis_report",
    _ea(
        "[MONTHLY MIS] SEACMS Monthly Report — {{report_month}}",
        "<h3 style='color:#1E3C72'>Monthly MIS Report — {{report_month}}</h3>"
        "<p>Your monthly equipment management report is ready for {{report_month}}.</p>"
        "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Report Period</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{report_month}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Generated On</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{report.generated_on}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Tests Completed</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{tests_completed}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Critical Findings</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{critical_count}}</td></tr>"
        "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Overdue Tests</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{overdue_count}}</td></tr>"
        "</table>"
        "<p>The PDF and Excel reports are attached to this email.</p>",
        ["SEE W&M", "CEE Transmission Zone"],
        [
            {"var_key": "report.retriepdf", "type": "pdf"},
            {"var_key": "report.retriexls", "type": "excel"},
        ],
    ),
    _i(
        "Monthly MIS Report — {{report_month}} ready",
        "The SEACMS MIS report for {{report_month}} is available. Tests: {{tests_completed}}, Critical: {{critical_count}}, Overdue: {{overdue_count}}.",
        ["SEE W&M", "CEE Transmission Zone"],
    ),
)

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
    # ── Department / Context ──────────────────────────────────────────────────
    {
        "var_key": "dept.name", "label": "Department Name",
        "group_name": "Context", "resolver_key": "currentdeptname",
        "description": "Name of the department associated with the event (e.g. North Division).",
        "sample_value": "North Division",
        "is_system": True,
    },
    {
        "var_key": "dept.code", "label": "Department Code",
        "group_name": "Context", "resolver_key": "dept_code",
        "description": "Short code for the department.",
        "sample_value": "NB-DIV",
        "is_system": True,
    },
    {
        "var_key": "user.name", "label": "Recipient Name",
        "group_name": "Context", "resolver_key": "user_name",
        "description": "Full name of the notification recipient (resolved at dispatch time).",
        "sample_value": "Jane Smith",
        "is_system": True,
    },
    {
        "var_key": "user.email", "label": "Recipient Email",
        "group_name": "Context", "resolver_key": "recipient_email",
        "description": "Email address of the notification recipient.",
        "sample_value": "jane.smith@utility.com",
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
    Idempotent upsert: insert or update global default templates (organization_id=NULL).

    On first run  → inserts all rows.
    On re-run     → updates subject_template + body_template + recipient_roles
                    so new DEFAULT_TEMPLATES content is always reflected in the DB.
    Org-specific overrides (organization_id IS NOT NULL) are never touched.

    Returns count of inserted rows (updates are not counted).
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
        if existing:
            # Refresh body/subject/roles/attachment_vars from DEFAULT_TEMPLATES
            # (org-specific overrides are never touched)
            existing.subject_template  = tpl.get("subject_template", existing.subject_template)
            existing.body_template     = tpl["body_template"]
            existing.recipient_roles   = tpl.get("recipient_roles", existing.recipient_roles)
            existing.attachment_vars   = tpl.get("attachment_vars", existing.attachment_vars or [])
        else:
            db.add(NotificationTemplate(**tpl))
            inserted += 1
    db.commit()
    logger.info(f"[Notif] Seeded/refreshed default notification templates ({inserted} new).")
    return inserted
