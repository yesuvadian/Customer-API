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
import time
import traceback
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import and_, or_, func as sa_func
from sqlalchemy.orm import Session, joinedload

from models import (
    NotificationLog,
    NotificationLogRecipient,
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
            ctx.setdefault("tr.submitted_at", str(tr.cts)[:19] if tr.cts else "")
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
            # Equipment (asset register) context — load first so type fallback is available
            _resolved_eq_type_id = tr.equipment_type_id   # may be None for schedule-created TRs
            if tr.equipment_id:
                from models import Equipment as _EqModel
                from sqlalchemy.orm import joinedload as _jl
                eq = (
                    db.query(_EqModel)
                    .options(_jl(_EqModel.department))
                    .filter(_EqModel.id == tr.equipment_id)
                    .first()
                )
                if eq:
                    ctx.setdefault("equipment.ueic", getattr(eq, "ueic", "") or "")
                    ctx.setdefault("equipment.name", getattr(eq, "name", "") or "")
                    _eq_dept = getattr(eq, "department", None)
                    if _eq_dept:
                        ctx.setdefault("equipment.department", _eq_dept.name or "")
                    # Fall back to equipment's own type when TR doesn't carry it
                    if not _resolved_eq_type_id and getattr(eq, "equipment_type_id", None):
                        _resolved_eq_type_id = eq.equipment_type_id
                # Performance + last execution — set both flat key (for alias cache)
                # and dot key directly (alias resolution runs before this enrichment)
                _perf = _build_performance_html(db, tr.equipment_id)
                _last = _build_last_execution_html(db, tr.equipment_id)
                ctx.setdefault("performance_table_html", _perf)
                ctx.setdefault("table.performance",      _perf)
                ctx.setdefault("last_execution_html",    _last)
                ctx.setdefault("report.lastexecution",   _last)
                # Store last TestResult ID so attachment_vars can attach its PDF
                try:
                    from models import TestResult as _TestRes
                    _last_res = (
                        db.query(_TestRes)
                        .join(TestingRequest, _TestRes.testing_request_id == TestingRequest.id)
                        .filter(TestingRequest.equipment_id == tr.equipment_id)
                        .order_by(_TestRes.cts.desc())
                        .first()
                    )
                    if _last_res:
                        ctx.setdefault("report.lastexecution.test_result_id", str(_last_res.id))
                except Exception:
                    pass
            # CategoryMaster → equipment type display name (e.g. "Power Transformer")
            if _resolved_eq_type_id:
                eq_type = db.query(CategoryMaster).filter(
                    CategoryMaster.id == _resolved_eq_type_id
                ).first()
                if eq_type:
                    ctx.setdefault("equipment.type", eq_type.name or "")
            # Department context — TR dept first, fall back to equipment's dept
            _resolved_dept_id = tr.department_id
            if not _resolved_dept_id and tr.equipment_id:
                try:
                    from models import Equipment as _EqDept
                    _edq = db.query(_EqDept).filter(_EqDept.id == tr.equipment_id).first()
                    if _edq:
                        _resolved_dept_id = getattr(_edq, "department_id", None)
                except Exception:
                    pass
            if _resolved_dept_id:
                dept = db.query(OrgDepartment).filter(
                    OrgDepartment.id == _resolved_dept_id
                ).first()
                if dept:
                    ctx.setdefault("dept.name", dept.name or "")
                    ctx.setdefault("dept.code", dept.code or "")
            # Originator (submitted_by) context
            if tr.originator_id:
                from models import User as _User
                orig = db.query(_User).filter(_User.id == tr.originator_id).first()
                if orig:
                    _orig_name = (
                        f"{orig.firstname or ''} {orig.lastname or ''}".strip()
                        or orig.email or str(orig.id)
                    )
                    ctx.setdefault("request.submitted_by", _orig_name)
                    ctx.setdefault("originator",           _orig_name)
                    ctx.setdefault("originator.email",     orig.email or "")
            # Assigned tester — needed for {tester_name} and dot-notation aliases
            if tr.assigned_tester_id:
                from models import User as _User5
                _at = db.query(_User5).filter(_User5.id == tr.assigned_tester_id).first()
                if _at:
                    _atname = (
                        f"{_at.firstname or ''} {_at.lastname or ''}".strip()
                        or _at.email or ""
                    )
                    ctx.setdefault("tester_name",         _atname)
                    ctx.setdefault("request.assigned_to", _atname)
                    ctx.setdefault("tester.name",         _atname)
                    ctx.setdefault("tester.email",        _at.email or "")
            # Kit availability — flat key for alias cache AND dot key for direct resolution
            _kit_data = _build_kit_data(db, _resolved_eq_type_id, _resolved_dept_id)
            _kit_html  = _build_kit_html(_kit_data)
            ctx.setdefault("kit_availability_html", _kit_html)
            ctx.setdefault("table.testkit",         _kit_html)
            # Legacy flat-key compat for templates that use {request_number} / {equipment}
            ctx.setdefault("request_number", tr.request_number or str(tr.id)[:8])
            ctx.setdefault("equipment",
                           ctx.get("equipment.ueic") or ctx.get("equipment.name") or "")

        elif source_type == "test_result":
            from models import TestResult, TestingRequest, OrgDepartment, CategoryDetails, CategoryMaster
            from sqlalchemy.orm import joinedload as _jl2
            tr_res = db.query(TestResult).filter(TestResult.id == source_id).first()
            if not tr_res:
                return
            ctx.setdefault("eval.overall",      tr_res.overall_result or "")
            ctx.setdefault("eval.evaluated_at", str(tr_res.tested_at or tr_res.cts)[:19] if (tr_res.tested_at or tr_res.cts) else "")
            # Tester who submitted the result
            if getattr(tr_res, "tested_by", None):
                from models import User as _User2
                _tester = db.query(_User2).filter(_User2.id == tr_res.tested_by).first()
                if _tester:
                    _tname = f"{_tester.firstname or ''} {_tester.lastname or ''}".strip() or _tester.email or ""
                    ctx.setdefault("request.assigned_to", _tname)
                    ctx.setdefault("tester.name",         _tname)
                    ctx.setdefault("tester.email",        _tester.email or "")
            if tr_res.testing_request_id:
                tr = db.query(TestingRequest).filter(
                    TestingRequest.id == tr_res.testing_request_id
                ).first()
                if tr:
                    ctx.setdefault("request.number",   tr.request_number or str(tr.id)[:8])
                    ctx.setdefault("tr.status",        str(tr.status.value) if tr.status else "")
                    ctx.setdefault("request.status",   str(tr.status.value) if tr.status else "")
                    ctx.setdefault("request.title",    tr.title or "")
                    ctx.setdefault("request.priority", tr.priority or "normal")
                    if tr.due_date:
                        ctx.setdefault("request.due_date", str(tr.due_date)[:10])
                    # Originator / submitted_by
                    if tr.originator_id:
                        from models import User as _User3
                        _orig = db.query(_User3).filter(_User3.id == tr.originator_id).first()
                        if _orig:
                            _oname = f"{_orig.firstname or ''} {_orig.lastname or ''}".strip() or _orig.email or ""
                            ctx.setdefault("request.submitted_by", _oname)
                            ctx.setdefault("originator",           _oname)
                            ctx.setdefault("originator.email",     _orig.email or "")
                    # Assigned tester name (from TR if not already set from TestResult)
                    if tr.assigned_tester_id and not ctx.get("request.assigned_to"):
                        from models import User as _User4
                        _at = db.query(_User4).filter(_User4.id == tr.assigned_tester_id).first()
                        if _at:
                            _atname = f"{_at.firstname or ''} {_at.lastname or ''}".strip() or _at.email or ""
                            ctx.setdefault("request.assigned_to", _atname)
                    # Test type display name
                    if tr.test_type_id:
                        cat = db.query(CategoryDetails).filter(
                            CategoryDetails.id == tr.test_type_id
                        ).first()
                        if cat:
                            ctx.setdefault("eval.test_type", cat.name or "")
                            ctx.setdefault("tr.test_type",   cat.name or "")
                    # Equipment type display name
                    if tr.equipment_type_id:
                        eq_type = db.query(CategoryMaster).filter(
                            CategoryMaster.id == tr.equipment_type_id
                        ).first()
                        if eq_type:
                            ctx.setdefault("equipment.type", eq_type.name or "")
                    # Department
                    if tr.department_id:
                        dept = db.query(OrgDepartment).filter(
                            OrgDepartment.id == tr.department_id
                        ).first()
                        if dept:
                            ctx.setdefault("dept.name", dept.name or "")
                            ctx.setdefault("dept.code", dept.code or "")
                    # Equipment (asset register)
                    if tr.equipment_id:
                        from models import Equipment as _EqModel2
                        eq2 = (
                            db.query(_EqModel2)
                            .options(_jl2(_EqModel2.department))
                            .filter(_EqModel2.id == tr.equipment_id)
                            .first()
                        )
                        if eq2:
                            ctx.setdefault("equipment.ueic", getattr(eq2, "ueic", "") or "")
                            ctx.setdefault("equipment.name", getattr(eq2, "name", "") or "")
                            _eq2_dept = getattr(eq2, "department", None)
                            if _eq2_dept:
                                ctx.setdefault("equipment.department", _eq2_dept.name or "")
                        # Performance + last execution — dot keys set directly (post-alias timing)
                        _perf2 = _build_performance_html(db, tr.equipment_id)
                        _last2 = _build_last_execution_html(db, tr.equipment_id)
                        ctx.setdefault("performance_table_html", _perf2)
                        ctx.setdefault("table.performance",      _perf2)
                        ctx.setdefault("last_execution_html",    _last2)
                        ctx.setdefault("report.lastexecution",   _last2)

        elif source_type == "equipment":
            from models import Equipment, OrgDepartment, CategoryMaster
            eq = db.query(Equipment).filter(Equipment.id == source_id).first()
            if eq:
                ctx.setdefault("equipment.ueic",         getattr(eq, "ueic", "") or "")
                ctx.setdefault("equipment.name",         getattr(eq, "name", "") or "")
                ctx.setdefault("equipment.status",       str(getattr(eq, "status", "") or ""))
                ctx.setdefault("equipment.manufacturer", getattr(eq, "manufacturer", "") or "")
                # Resolve equipment type display name from CategoryMaster
                eq_type_id = getattr(eq, "equipment_type_id", None)
                if eq_type_id:
                    cat = db.query(CategoryMaster).filter(CategoryMaster.id == eq_type_id).first()
                    if cat:
                        ctx.setdefault("equipment.type", cat.name or "")
                # Resolve department name + code from OrgDepartment
                dept_id = getattr(eq, "department_id", None)
                if dept_id:
                    dept = db.query(OrgDepartment).filter(OrgDepartment.id == dept_id).first()
                    if dept:
                        ctx.setdefault("equipment.department", dept.name or "")
                        ctx.setdefault("dept.name",            dept.name or "")
                        ctx.setdefault("dept.code",            dept.code or "")
                        ctx.setdefault("department",           dept.name or "")
                # Performance + last execution — dot keys set directly (post-alias timing)
                _perf3 = _build_performance_html(db, source_id)
                _last3 = _build_last_execution_html(db, source_id)
                ctx.setdefault("performance_table_html", _perf3)
                ctx.setdefault("table.performance",      _perf3)
                ctx.setdefault("last_execution_html",    _last3)
                ctx.setdefault("report.lastexecution",   _last3)

        elif source_type == "recommendation":
            from models import Recommendation
            rec = db.query(Recommendation).filter(Recommendation.id == source_id).first()
            if rec:
                ctx.setdefault("recommendation.id",     str(rec.id))
                ctx.setdefault("recommendation.status", rec.approval_status or "")

        elif source_type == "document_request":
            from models import (
                DocumentRequest as _DocReq, User as _DocUser,
                TrWfInstance as _TrWfInst, TrWfStatus as _TrWfStat, TrWfStage as _TrWfStage,
            )
            doc = db.query(_DocReq).filter(_DocReq.id == source_id).first()
            if doc:
                # ── Core document fields ──────────────────────────────────────
                ctx.setdefault("doc.id",          str(doc.id))
                ctx.setdefault("doc.title",       doc.title or "")
                ctx.setdefault("title",           doc.title or "")   # short alias
                ctx.setdefault("doc.description", doc.description or "")
                ctx.setdefault("doc.notes",       doc.notes or "")
                ctx.setdefault("doc.priority",    doc.priority or "normal")
                ctx.setdefault("doc.file_name",   doc.file_name or "")
                ctx.setdefault("doc.file_url",    doc.file_url or "")
                ctx.setdefault("doc.mime_type",   doc.mime_type or "")
                ctx.setdefault("doc.created_at",
                    str(doc.created_at)[:19] if doc.created_at else "")
                ctx.setdefault("doc.modified_at",
                    str(doc.modified_at)[:19] if doc.modified_at else "")
                ctx.setdefault("doc.target_date",
                    str(doc.target_date)[:10] if doc.target_date else "")

                # ── Status / stage (resolved from TrWfStatus) ────────────────
                _status_display = doc.current_status_code or ""
                _stage_display  = ""
                if doc.wf_instance_id:
                    _inst = db.query(_TrWfInst).filter(
                        _TrWfInst.id == doc.wf_instance_id
                    ).first()
                    if _inst:
                        if _inst.wf_definition_id and doc.current_status_code:
                            _sr = db.query(_TrWfStat).filter(
                                _TrWfStat.wf_definition_id == _inst.wf_definition_id,
                                _TrWfStat.status_code == doc.current_status_code,
                            ).first()
                            if _sr:
                                _status_display = _sr.status_name
                        if _inst.current_stage_id:
                            _sg = db.query(_TrWfStage).filter(
                                _TrWfStage.id == _inst.current_stage_id
                            ).first()
                            if _sg:
                                _stage_display = _sg.name or ""
                ctx.setdefault("status_name",      _status_display)
                ctx.setdefault("doc.status_name",  _status_display)
                ctx.setdefault("doc.status_code",  doc.current_status_code or "")
                ctx.setdefault("stage_name",       _stage_display)
                ctx.setdefault("doc.stage_name",   _stage_display)

                # ── Originator (submitter) ────────────────────────────────────
                if doc.submitted_by:
                    _sub = db.query(_DocUser).filter(_DocUser.id == doc.submitted_by).first()
                    if _sub:
                        _sub_name = (
                            f"{_sub.firstname or ''} {_sub.lastname or ''}".strip()
                            or _sub.email or ""
                        )
                        ctx.setdefault("originator",            _sub_name)
                        ctx.setdefault("originator.name",       _sub_name)
                        ctx.setdefault("originator.email",      _sub.email or "")
                        ctx.setdefault("submitted_by",          _sub_name)
                        ctx.setdefault("doc.submitted_by",      _sub_name)
                        ctx.setdefault("doc.submitted_by.email", _sub.email or "")

                # ── Assigned manager ──────────────────────────────────────────
                if doc.assigned_manager_id:
                    _mgr = db.query(_DocUser).filter(
                        _DocUser.id == doc.assigned_manager_id
                    ).first()
                    if _mgr:
                        _mgr_name = (
                            f"{_mgr.firstname or ''} {_mgr.lastname or ''}".strip()
                            or _mgr.email or ""
                        )
                        ctx.setdefault("doc.manager",       _mgr_name)
                        ctx.setdefault("doc.manager.email", _mgr.email or "")

                # ── Assigned processor ────────────────────────────────────────
                if doc.assigned_processor_id:
                    _proc = db.query(_DocUser).filter(
                        _DocUser.id == doc.assigned_processor_id
                    ).first()
                    if _proc:
                        _proc_name = (
                            f"{_proc.firstname or ''} {_proc.lastname or ''}".strip()
                            or _proc.email or ""
                        )
                        ctx.setdefault("doc.processor",       _proc_name)
                        ctx.setdefault("doc.processor.email", _proc.email or "")

        elif source_type == "scada_reading":
            from models import ScadaReading, Equipment as _ScadaEq
            reading = db.query(ScadaReading).filter(ScadaReading.id == source_id).first()
            if reading:
                ctx.setdefault("scada.tag",        reading.scada_tag or "")
                ctx.setdefault("scada.parameter",  reading.parameter_name or "")
                ctx.setdefault("scada.value",      str(reading.value))
                ctx.setdefault("scada.unit",       reading.unit or "")
                ctx.setdefault("scada.condition",  reading.alarm_condition or "")
                ctx.setdefault("scada.timestamp",  str(reading.recorded_at)[:19] if reading.recorded_at else "")
                if reading.equipment_id:
                    from sqlalchemy.orm import joinedload as _jl_scada
                    eq = (db.query(_ScadaEq).options(_jl_scada(_ScadaEq.department))
                          .filter(_ScadaEq.id == reading.equipment_id).first())
                    if eq:
                        ctx.setdefault("equipment.name", getattr(eq, "name", "") or "")
                        ctx.setdefault("equipment.ueic", getattr(eq, "ueic", "") or "")
                        _eq_dept = getattr(eq, "department", None)
                        if _eq_dept:
                            ctx.setdefault("equipment.department", _eq_dept.name or "")

    except Exception as _exc:
        logger.warning(f"[Notif] _enrich_context_from_source({source_type}): {_exc}")

    # ── Fallback: always ensure equipment.department has a value ─────────────
    # Must be outside the try/except so it runs even when an earlier step threw.
    # Uses the TR's own department if the equipment's department wasn't resolved.
    if source_type in ("testing_request", "test_result"):
        ctx.setdefault("equipment.department", ctx.get("dept.name", "") or "")


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


# ── Variable alias cache (loaded from notification_variables.fallback_keys) ───

_alias_cache:    Optional[Dict[str, List[str]]] = None
_alias_cache_ts: float = 0.0
_ALIAS_CACHE_TTL = 300  # seconds — refresh every 5 minutes


def _load_alias_cache(db: Session) -> Dict[str, List[str]]:
    """
    Return var_key → [fallback_keys] mapping from DB, refreshed every 5 min.
    System variables (is_system=True, org=NULL) only — org-custom vars resolve
    directly from the fire() context by their var_key, no alias needed.
    """
    global _alias_cache, _alias_cache_ts
    now_ts = time.monotonic()
    if _alias_cache is not None and (now_ts - _alias_cache_ts) < _ALIAS_CACHE_TTL:
        return _alias_cache

    try:
        rows = (
            db.query(NotificationVariable)
            .filter(
                NotificationVariable.is_system.is_(True),
                NotificationVariable.is_active.is_(True),
                NotificationVariable.organization_id.is_(None),
                NotificationVariable.fallback_keys.isnot(None),
            )
            .all()
        )
        cache: Dict[str, List[str]] = {}
        for row in rows:
            fb = list(row.fallback_keys or [])
            if fb:                          # skip vars with no fallback (system.*)
                cache[row.var_key] = fb
        _alias_cache    = cache
        _alias_cache_ts = now_ts
        return cache
    except Exception as exc:
        logger.warning(f"[VariableResolver] alias cache load failed: {exc}")
        return _alias_cache or {}   # serve stale cache on DB error


# ── Variable context resolver ─────────────────────────────────────────────────

class VariableResolver:
    """
    Augments the raw context dict passed to fire() with:
      • Dot-notation aliases  ({{equipment.ueic}} from legacy "equipment" key)
        — fallback lists are stored in notification_variables.fallback_keys
          and loaded via _load_alias_cache(); no hardcoded mapping in code.
      • System-injected vars  ({{system.date}}, {{system.time}}, {{system.app_name}})
    """

    @staticmethod
    def build_context(raw: Dict[str, Any],
                      db: Optional[Session] = None) -> Dict[str, Any]:
        """
        Return a flat dict that maps every supported var_key to its resolved value.
        Safe to call with any partial context — missing keys simply won't be resolved.

        db: pass the active Session so fallback aliases are loaded from DB.
            If None (e.g. unit tests), alias resolution is skipped gracefully.
        """
        now = datetime.now(timezone.utc)
        ctx: Dict[str, Any] = {k: (str(v) if v is not None else "") for k, v in raw.items()}

        # Inject system variables (always available)
        ctx.setdefault("system.date",     now.strftime("%Y-%m-%d"))
        ctx.setdefault("system.time",     now.strftime("%H:%M UTC"))
        ctx.setdefault("system.app_name", "SEACMS")

        # Resolve dot-notation aliases from DB-backed fallback lists
        if db is not None:
            aliases = _load_alias_cache(db)
            for dot_key, sources in aliases.items():
                if not ctx.get(dot_key):
                    for src in sources:
                        if ctx.get(src):
                            ctx[dot_key] = ctx[src]
                            break

        return ctx


# ── System-token recipient resolver ──────────────────────────────────────────

def _resolve_token_user(
    db: Session,
    source_type: str,
    source_id: UUID,
    field_name: str,
) -> "Optional[User]":
    """
    Load the User whose UUID is stored in ``field_name`` on the source record.

    source_type → model mapping
    ───────────────────────────
    testing_request  → TestingRequest
    equipment        → Equipment
    recommendation   → Recommendation
    (others)         → skipped — extend here as needed

    Field-name overrides
    ────────────────────
    Different models use different field names for conceptually the same
    "owner / creator" relationship.  ``_FIELD_OVERRIDES`` maps
    (source_type, generic_field) → model_specific_field so callers can use
    the generic token names (@owner → "created_by") while still resolving
    correctly against models that use a different column name.

    Returns None on any error so a missing token never blocks delivery.
    """
    # ── Per-(source_type, generic_token_field) → model_specific_field ────────────
    #
    # Different models store the same conceptual "person" under different column
    # names.  Map the generic token field (from SYSTEM_RECIPIENT_TOKENS) to the
    # actual column on each model so @tokens work correctly across all source types.
    #
    #  Model                  @assignee                @owner          @requester
    #  ──────────────────     ──────────────────────   ─────────────   ──────────────────────
    #  TestingRequest          assigned_tester_id*      originator_id†  originator_id†
    #  Equipment               assigned_tester_id (n/a) created_by*     requested_by (n/a)
    #  TestResult              tested_by†               created_by*     → parent TR originator†
    #  Recommendation          assigned_tester_id (n/a) created_by*     submitted_by†
    #  RepairWorkflow          work_award_by†           created_by*     created_by†
    #  (surveillance_workflow) ─ same model as above ─
    #
    #  *  direct column exists on that model
    #  †  override applied here or via special navigation logic below
    #  n/a → getattr returns None → user skipped (no error)
    #
    _FIELD_OVERRIDES: dict = {
        # TestingRequest uses originator_id for both owner and requester
        ("testing_request",       "created_by"):         "originator_id",
        ("testing_request",       "requested_by"):       "originator_id",
        # TestResult: @assignee is the tester who submitted the result
        ("test_result",           "assigned_tester_id"): "tested_by",
        # Recommendation: @requester is the submitter
        ("recommendation",        "requested_by"):       "submitted_by",
        # RepairWorkflow: @assignee is the Work Award Officer; @requester same as creator
        ("repair_workflow",       "assigned_tester_id"): "work_award_by",
        ("repair_workflow",       "requested_by"):       "created_by",
        # surveillance_workflow IDs point to RepairWorkflow rows — same overrides
        ("surveillance_workflow", "assigned_tester_id"): "work_award_by",
        ("surveillance_workflow", "requested_by"):       "created_by",
        # DocumentRequest: @originator = submitted_by, @assignee = assigned_processor_id
        ("document_request",      "originator_id"):      "submitted_by",
        ("document_request",      "requested_by"):       "submitted_by",
        ("document_request",      "assigned_tester_id"): "assigned_processor_id",
    }
    actual_field = _FIELD_OVERRIDES.get((source_type, field_name), field_name)

    try:
        if source_type == "testing_request":
            from models import TestingRequest as _TR
            record = db.query(_TR).filter(_TR.id == source_id).first()

        elif source_type == "equipment":
            from models import Equipment as _EQ
            record = db.query(_EQ).filter(_EQ.id == source_id).first()

        elif source_type == "recommendation":
            from models import Recommendation as _REC
            record = db.query(_REC).filter(_REC.id == source_id).first()

        elif source_type == "test_result":
            from models import TestResult as _TR2
            record = db.query(_TR2).filter(_TR2.id == source_id).first()

            # @requester on test_result → navigate to parent testing_request's originator
            # (TestResult has no "requester" column of its own).
            if record and field_name == "requested_by":
                from models import TestingRequest as _TR_p
                parent = (
                    db.query(_TR_p)
                    .filter(_TR_p.id == record.testing_request_id)
                    .first()
                )
                user_id = getattr(parent, "originator_id", None) if parent else None
                if not user_id:
                    return None
                return db.query(User).filter(User.id == user_id).first()

        elif source_type in ("repair_workflow", "surveillance_workflow"):
            # surveillance_workflow IDs are FKs into repair_workflows (same table).
            from models import RepairWorkflow as _RW
            record = db.query(_RW).filter(_RW.id == source_id).first()

        elif source_type == "document_request":
            from models import DocumentRequest as _DR
            record = db.query(_DR).filter(_DR.id == source_id).first()

        else:
            logger.debug(
                f"[Notif] _resolve_token_user: unsupported source_type={source_type!r}"
            )
            return None

        if not record:
            return None

        user_id = getattr(record, actual_field, None)
        if not user_id:
            logger.debug(
                f"[Notif] _resolve_token_user: field {actual_field!r} is empty "
                f"on {source_type}/{source_id}"
            )
            return None

        return db.query(User).filter(User.id == user_id).first()

    except Exception as exc:
        logger.warning(
            f"[Notif] _resolve_token_user({source_type!r}, {actual_field!r}): {exc}"
        )
        return None


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

def _is_uuid_str(s: str) -> bool:
    """Return True if s is a valid UUID string (any version)."""
    try:
        UUID(str(s))
        return True
    except (ValueError, AttributeError):
        return False


def _resolve_recipients_by_roles(
    db: Session,
    role_names: List[str],
    organization_id: Optional[UUID],
    department_id: Optional[UUID] = None,
    source_type: Optional[str] = None,
    source_id: Optional[UUID] = None,
) -> List[User]:
    """
    Return unique active User objects for the given recipient identifiers.

    Accepts three identifier formats in the same list (auto-detected):
      • ``@token`` strings — system recipient tokens (e.g. ``"@assignee"``)
                             resolved from the source record at fire()-time.
                             Defined in ``services/notification_tokens.py``.
      • UUID strings       — matched against OrgRole.id  (preferred)
      • Name strings       — matched against OrgRole.name (legacy / backward compat)

    System tokens are always resolved first and deduplicated against
    the role-based results so a user is never notified twice.

    Department scoping rules (applies to role-based recipients only):
      • OrgUserRole.department_id IS NULL  → org-wide user  → always included
      • OrgUserRole.department_id == source_dept    → same leaf dept → included
      • OrgUserRole.department_id is an ANCESTOR of source_dept → included
      • OrgUserRole.department_id is a sibling / different branch → excluded
    """
    from services.notification_tokens import SYSTEM_RECIPIENT_TOKENS

    seen: set     = set()
    users: List[User] = []

    # ── 1. Resolve system tokens (@assignee, @owner, …) ──────────────────────
    sys_tokens = [r for r in (role_names or []) if isinstance(r, str) and r.startswith("@")]
    org_refs   = [r for r in (role_names or []) if not (isinstance(r, str) and r.startswith("@"))]

    if sys_tokens and source_type and source_id:
        for token in sys_tokens:
            field_name = SYSTEM_RECIPIENT_TOKENS.get(token)
            if not field_name:
                logger.debug(f"[Notif] Unknown system recipient token: {token!r}")
                continue
            user = _resolve_token_user(db, source_type, source_id, field_name)
            if user and user.id not in seen:
                seen.add(user.id)
                users.append(user)
                logger.debug(
                    f"[Notif] Token {token!r} → user={user.id} ({user.email})"
                )
    elif sys_tokens:
        logger.debug(
            f"[Notif] System tokens {sys_tokens} present but source_type/source_id "
            f"not provided — tokens skipped"
        )

    # ── 2. Resolve org roles (existing logic) ─────────────────────────────────
    if not org_refs or not organization_id:
        return users   # may already contain system-token users

    # Auto-detect whether the caller passed UUIDs or name strings.
    uuid_ids  = [UUID(r) for r in org_refs if _is_uuid_str(r)]
    name_strs = [r for r in org_refs if not _is_uuid_str(r)]

    from sqlalchemy import or_ as _or_
    role_filter = []
    if uuid_ids:
        role_filter.append(OrgRole.id.in_(uuid_ids))
    if name_strs:
        role_filter.append(OrgRole.name.in_(name_strs))
    if not role_filter:
        return users   # return any system-token users already collected

    # Build the full ancestor set once (includes source dept itself)
    ancestor_ids: set = set()
    if department_id:
        ancestor_ids = _ancestor_dept_ids(db, department_id)

    rows = (
        db.query(OrgUserRole)
        .join(OrgRole, OrgUserRole.org_role_id == OrgRole.id)
        .join(User, OrgUserRole.user_id == User.id)
        .options(joinedload(OrgUserRole.user))   # eager-load User — prevents N+1 queries
        .filter(
            OrgRole.organization_id == organization_id,
            _or_(*role_filter),
            OrgRole.is_active.is_(True),
            OrgUserRole.is_active.is_(True),
        )
        .all()
    )

    logger.debug(
        f"[Notif resolve_recipients] org_refs={org_refs} org={organization_id} "
        f"dept={department_id} ancestor_ids={ancestor_ids} rows_count={len(rows)}"
    )

    for row in rows:
        if department_id:
            row_dept = row.department_id
            # Exclude users assigned to a dept outside the ancestor chain.
            # Org-wide users (dept_id IS NULL) are always included.
            if row_dept is not None and row_dept not in ancestor_ids:
                continue
        if row.user_id not in seen:
            seen.add(row.user_id)
            users.append(row.user)
    return users


# ── Kit availability HTML renderer ────────────────────────────────────────────

def _build_kit_html(kit_data: dict) -> str:
    """
    Convert _build_kit_availability() output into a 2-column HTML table:
    Kit Type | Availability (with full ancestor list when not at station).
    Returns an empty string when no kit requirements exist.
    """
    kits = kit_data.get("required_kits", [])
    if not kits:
        return ""

    rows = ""
    for k in kits:
        kit_type       = k.get("kit_type", "")
        at_station     = k.get("available_at_station", False)
        count          = k.get("count_at_station", 0)
        avail_at_depts: list = k.get("available_at_depts", [])

        if at_station:
            avail_cell = (
                f'<span style="color:#16A34A;font-weight:600;">&#10003; Available at station</span>'
                f'<br/><span style="color:#555;font-size:12px;">{count} unit(s) at your station</span>'
            )
        elif avail_at_depts:
            dept_lines = "".join(
                f'<span style="display:inline-block;margin:1px 0;color:#555;font-size:11px;">'
                f'&#8627; {d}</span><br/>'
                for d in avail_at_depts
            )
            avail_cell = (
                '<span style="color:#D97706;font-weight:600;">&#9888; Not at station</span>'
                f'<br/><span style="color:#555;font-size:11px;">Available at:</span><br/>'
                f'{dept_lines}'
            )
        else:
            avail_cell = (
                '<span style="color:#DC2626;font-weight:600;">&#10007; Not available in hierarchy</span>'
            )

        rows += (
            "<tr>"
            f'<td style="padding:8px 12px;border-bottom:1px solid #EEF2F7;vertical-align:top;">'
            f"{kit_type}</td>"
            f'<td style="padding:8px 12px;border-bottom:1px solid #EEF2F7;vertical-align:top;">'
            f"{avail_cell}</td>"
            "</tr>"
        )

    return (
        '<h3 style="margin:24px 0 10px;font-size:15px;color:#1E3C72;">'
        "Testing Kit Availability</h3>"
        '<table width="100%" cellpadding="0" cellspacing="0" '
        'style="border-collapse:collapse;font-size:13px;'
        'border:1px solid #DDE3EE;border-radius:6px;overflow:hidden;">'
        "<thead>"
        "<tr>"
        '<th style="padding:8px 12px;background:#1E3C72;color:#fff;'
        'text-align:left;font-weight:600;">Kit Type</th>'
        '<th style="padding:8px 12px;background:#1E3C72;color:#fff;'
        'text-align:left;font-weight:600;">Availability</th>'
        "</tr>"
        "</thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
        '<p style="margin:8px 0 0;font-size:12px;color:#888;">'
        "Availability shown as of notification time. "
        "Check the app for real-time status before heading to the site.</p>"
    )


def _build_performance_html(db: Session, equipment_id) -> str:
    """HTML table of EquipmentAnalytics scores for {{table.performance}}."""
    try:
        from models import EquipmentAnalytics
        ea = db.query(EquipmentAnalytics).filter(
            EquipmentAnalytics.equipment_id == equipment_id
        ).first()
        if not ea or ea.health_score is None:
            return ""
        score    = f"{float(ea.health_score):.1f}"
        risk     = ea.risk_level or "—"
        cond     = ea.condition_summary or "—"
        assessed = str(ea.test_types_assessed or 0)
        last_test = str(ea.last_test_date)[:10] if ea.last_test_date else "—"
        calc_at   = str(ea.calculated_at)[:10] if ea.calculated_at else "—"
        rows_html = "".join(
            f'<tr><td style="padding:6px 12px;border-bottom:1px solid #EEF2F7;">'
            f"<b>{lbl}</b></td>"
            f'<td style="padding:6px 12px;border-bottom:1px solid #EEF2F7;">{val}</td></tr>'
            for lbl, val in [
                ("Health Score",      f"{score} / 100"),
                ("Risk Level",        risk),
                ("Condition",         cond),
                ("Tests Assessed",    assessed),
                ("Last Test Date",    last_test),
                ("Analytics Updated", calc_at),
            ]
        )
        return (
            '<h3 style="margin:24px 0 10px;font-size:15px;color:#1E3C72;">'
            "Equipment Performance Summary</h3>"
            '<table width="100%" cellpadding="0" cellspacing="0" '
            'style="border-collapse:collapse;font-size:13px;'
            'border:1px solid #DDE3EE;border-radius:6px;overflow:hidden;">'
            "<thead><tr>"
            '<th style="padding:8px 12px;background:#1E3C72;color:#fff;'
            'text-align:left;font-weight:600;">Metric</th>'
            '<th style="padding:8px 12px;background:#1E3C72;color:#fff;'
            'text-align:left;font-weight:600;">Value</th>'
            "</tr></thead>"
            f"<tbody>{rows_html}</tbody></table>"
        )
    except Exception:
        return ""


def _build_last_execution_html(db: Session, equipment_id) -> str:
    """HTML summary of the last completed TestingRequest for {{report.lastexecution}}."""
    try:
        from models import TestingRequest
        tr = (
            db.query(TestingRequest)
            .filter(
                TestingRequest.equipment_id == equipment_id,
                TestingRequest.status.in_([
                    "test_submitted", "under_approval", "approved",
                    "completed", "outcome_active", "commissioned",
                ]),
            )
            .order_by(TestingRequest.mts.desc())
            .first()
        )
        if not tr:
            return ""
        test_type = ""
        if tr.test_type_id:
            from models import CategoryDetails as _CD
            cat = db.query(_CD).filter(_CD.id == tr.test_type_id).first()
            if cat:
                test_type = cat.name or ""
        status_val = tr.status.value if tr.status else "—"
        due_date   = str(tr.due_date)[:10] if tr.due_date else "—"
        submitted  = str(tr.cts)[:10] if tr.cts else "—"
        rows_html = "".join(
            f'<tr><td style="padding:6px 12px;border-bottom:1px solid #EEF2F7;">'
            f"<b>{lbl}</b></td>"
            f'<td style="padding:6px 12px;border-bottom:1px solid #EEF2F7;">{val}</td></tr>'
            for lbl, val in [
                ("Request No.", tr.request_number or "—"),
                ("Title",       tr.title or "—"),
                ("Test Type",   test_type or "—"),
                ("Status",      status_val),
                ("Submitted",   submitted),
                ("Due Date",    due_date),
            ]
        )
        return (
            '<h3 style="margin:24px 0 10px;font-size:15px;color:#1E3C72;">'
            "Last Executed Test</h3>"
            '<table width="100%" cellpadding="0" cellspacing="0" '
            'style="border-collapse:collapse;font-size:13px;'
            'border:1px solid #DDE3EE;border-radius:6px;overflow:hidden;">'
            "<thead><tr>"
            '<th style="padding:8px 12px;background:#1E3C72;color:#fff;'
            'text-align:left;font-weight:600;">Field</th>'
            '<th style="padding:8px 12px;background:#1E3C72;color:#fff;'
            'text-align:left;font-weight:600;">Value</th>'
            "</tr></thead>"
            f"<tbody>{rows_html}</tbody></table>"
        )
    except Exception:
        return ""


def _build_kit_data(db: Session, equipment_type_id, department_id) -> dict:
    """Build kit availability dict from raw IDs (mirrors NotificationService._build_kit_availability)."""
    try:
        from models import CategoryMaster, Equipment, EquipmentTypeKitMapping, OrgDepartment
        if not equipment_type_id:
            return {}
        kit_master = db.query(CategoryMaster).filter(
            CategoryMaster.name == "Testing Kit",
            CategoryMaster.is_active == True,
        ).first()
        if not kit_master:
            return {}
        mappings = db.query(EquipmentTypeKitMapping).filter(
            EquipmentTypeKitMapping.equipment_type_id == equipment_type_id,
        ).all()
        if not mappings:
            return {}
        # Build ordered ancestor chain: [parent, grandparent, ...]
        ancestor_chain: list = []
        if department_id:
            _walk = department_id
            _seen: set = set()
            while _walk and _walk not in _seen:
                _seen.add(_walk)
                _d = db.query(OrgDepartment).filter(OrgDepartment.id == _walk).first()
                if not _d:
                    break
                if _d.parent_department_id and _d.parent_department_id not in _seen:
                    ancestor_chain.append(_d.parent_department_id)
                _walk = _d.parent_department_id

        kit_availability = []
        for m in mappings:
            kit_type      = m.kit_type
            kit_type_name = kit_type.name if kit_type else f"Kit #{m.kit_type_id}"
            at_station: list = []
            if department_id:
                at_station = db.query(Equipment).filter(
                    Equipment.equipment_type_id == kit_master.id,
                    Equipment.department_id == department_id,
                    Equipment.status == "active",
                ).all()
            nearest_location = None
            avail_at_depts: list = []
            if not at_station:
                for anc_id in ancestor_chain:
                    anc_kit = db.query(Equipment).filter(
                        Equipment.equipment_type_id == kit_master.id,
                        Equipment.department_id == anc_id,
                        Equipment.status == "active",
                    ).first()
                    if anc_kit:
                        anc_dept = db.query(OrgDepartment).filter(
                            OrgDepartment.id == anc_id
                        ).first()
                        avail_at_depts.append(anc_dept.name if anc_dept else str(anc_id))
            kit_availability.append({
                "kit_type":              kit_type_name,
                "is_required":           m.is_required,
                "available_at_station":  len(at_station) > 0,
                "count_at_station":      len(at_station),
                "available_at_depts":    avail_at_depts,
            })
        return {"required_kits": kit_availability}
    except Exception:
        return {}


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
        """
        Dispatch email for a batch NotificationLog.

        Loads all 'pending' NotificationLogRecipient rows attached to this log,
        resolves attachments and per-template CC/BCC addresses, then chooses:

        • BCC mode  — all rendered bodies are identical → one email, all addresses in Bcc.
        • Individual mode — bodies differ (personalised {{user.*}} vars) → one email per
          recipient using their own rendered_subject / rendered_body.

        The parent log.status is updated to reflect the overall outcome.
        """
        now = datetime.now(timezone.utc)

        # ── Load pending recipients ───────────────────────────────────────────
        pending = [
            r for r in (log.recipients or [])
            if r.delivery_status == "pending" and r.email
        ]

        # ── Resolve per-template CC / BCC addresses ───────────────────────────
        # Done BEFORE the empty-pending check so that CC/BCC addresses can act
        # as fallback primary recipients when no role-based recipients exist
        # (e.g. equipment_retired fired without a routing rule).
        cc_addrs:  List[str] = []
        bcc_addrs: List[str] = []
        tmpl_subject: str = subject
        tmpl_body:    str = body
        try:
            tmpl_row = (
                db.query(NotificationTemplate)
                .filter(
                    NotificationTemplate.event_type   == log.event_type,
                    NotificationTemplate.channel      == "email",
                    NotificationTemplate.is_active.is_(True),
                    NotificationTemplate.org_channel_disabled.is_(False),
                    or_(
                        NotificationTemplate.organization_id == log.organization_id,
                        NotificationTemplate.organization_id.is_(None),
                    ),
                )
                .order_by(NotificationTemplate.organization_id.desc().nulls_last())
                .first()
            )
            if tmpl_row:
                cc_addrs  = list(tmpl_row.cc_emails  or [])
                bcc_addrs = list(tmpl_row.bcc_emails or [])
                # Resolve role-based CC
                if tmpl_row.cc_roles:
                    for role_user in _resolve_recipients_by_roles(
                        db, list(tmpl_row.cc_roles), log.organization_id
                    ):
                        if role_user.email and role_user.email not in cc_addrs:
                            cc_addrs.append(role_user.email)
                # Resolve role-based BCC
                if tmpl_row.bcc_roles:
                    for role_user in _resolve_recipients_by_roles(
                        db, list(tmpl_row.bcc_roles), log.organization_id
                    ):
                        if role_user.email and role_user.email not in bcc_addrs:
                            bcc_addrs.append(role_user.email)
        except Exception as _cc_exc:
            logger.debug(f"[Notif] CC/BCC lookup failed for log={log.id}: {_cc_exc}")

        # ── No role-based recipients ──────────────────────────────────────────
        if not pending:
            # If ALL recipients are already sent/skipped this is a re-pickup of a
            # batch log whose status was never updated to 'sent' (scheduler bug).
            # Mark it done and return — do NOT re-send to CC/BCC.
            all_rcpt_statuses = {r.delivery_status for r in (log.recipients or [])}
            if all_rcpt_statuses and all_rcpt_statuses <= {"sent", "skipped"}:
                log.status  = "sent"
                log.sent_at = now
                logger.info(
                    f"[Notif] Batch log {log.id} had all recipients already sent — "
                    f"marking log as sent (was stuck at pending)"
                )
                return

            # When the event has no routing rule and the template has no
            # recipient_roles, pending will be empty.  If the admin set CC/BCC
            # email addresses on the template, treat them as primary recipients
            # so the notification still fires (e.g. equipment_retired).
            fallback = list(dict.fromkeys(cc_addrs + bcc_addrs))  # deduplicated, order preserved
            if fallback:
                logger.info(
                    f"[Notif] No role recipients for log={log.id} event={log.event_type!r} — "
                    f"falling back to {len(fallback)} CC/BCC address(es) as primary To"
                )
                svc = EmailService()
                attachments: List[Dict] = self._build_attachments(db, log)
                try:
                    if attachments:
                        svc.send_multi_attachment_email_starttls_bcc(
                            fallback, tmpl_subject, tmpl_body, attachments,
                        )
                    else:
                        svc.send_email_starttls_bcc(
                            fallback, tmpl_subject, tmpl_body,
                        )
                    log.status  = "sent"
                    log.sent_at = now
                except Exception as exc:
                    log.status        = "failed"
                    log.error_message = str(exc)[:500]
                    log.retry_count   = (log.retry_count or 0) + 1
                    logger.warning(f"[Notif] CC/BCC fallback send failed: {exc}")
            else:
                log.status        = "skipped"
                log.error_message = "No pending email recipients and no CC/BCC addresses"
                log.sent_at       = now
            return

        # ── Resolve shared attachments (log-level, same for all recipients) ──
        attachments: List[Dict] = self._build_attachments(db, log)

        # ── Decide BCC vs individual ─────────────────────────────────────────
        # If every pending recipient has the same rendered body and subject
        # → send one BCC email.  If any differ → send individually.
        rendered_bodies   = [r.rendered_body   or body    for r in pending]
        rendered_subjects = [r.rendered_subject or subject for r in pending]
        use_bcc = (len(set(rendered_bodies)) == 1 and len(set(rendered_subjects)) == 1)

        svc = EmailService()
        try:
            if use_bcc:
                emails    = [r.email for r in pending]
                send_subj = rendered_subjects[0]
                send_body = rendered_bodies[0]
                logger.info(
                    f"[Notif] BCC email → {len(emails)} recipient(s) "
                    f"cc={len(cc_addrs)} bcc={len(bcc_addrs)} "
                    f"log={log.id} event={log.event_type!r}"
                )
                if attachments:
                    svc.send_multi_attachment_email_starttls_bcc(
                        emails, send_subj, send_body, attachments,
                        cc=cc_addrs or None, extra_bcc=bcc_addrs or None,
                    )
                else:
                    svc.send_email_starttls_bcc(
                        emails, send_subj, send_body,
                        cc=cc_addrs or None, extra_bcc=bcc_addrs or None,
                    )

                for r in pending:
                    r.delivery_status = "sent"
                    r.sent_at         = now

            else:
                logger.info(
                    f"[Notif] Individual email → {len(pending)} recipient(s) "
                    f"cc={len(cc_addrs)} bcc={len(bcc_addrs)} "
                    f"log={log.id} event={log.event_type!r}"
                )
                for r in pending:
                    r_subj = r.rendered_subject or subject
                    r_body = r.rendered_body    or body
                    try:
                        if attachments:
                            svc.send_multi_attachment_email_starttls(
                                r.email, r_subj, r_body, attachments,
                                cc=cc_addrs or None, bcc=bcc_addrs or None,
                            )
                        else:
                            svc.send_email_starttls(
                                r.email, r_subj, r_body,
                                cc=cc_addrs or None, bcc=bcc_addrs or None,
                            )
                        r.delivery_status = "sent"
                        r.sent_at         = now
                    except Exception as exc:
                        r.delivery_status = "failed"
                        r.error_message   = str(exc)[:500]
                        logger.warning(f"[Notif] Individual email to {r.email} failed: {exc}")

            # ── Update overall log status ─────────────────────────────────────
            self._update_log_status_from_recipients(log, now)

        except Exception as exc:
            log.status      = "failed"
            log.error_message = str(exc)[:500]
            log.retry_count  = (log.retry_count or 0) + 1
            if log.retry_count < (log.max_retries or 3):
                log.next_retry_at = now + timedelta(minutes=RETRY_DELAY_MINUTES)
            for r in pending:
                if r.delivery_status == "pending":
                    r.delivery_status = "failed"
                    r.error_message   = str(exc)[:500]
            logger.warning(f"[Notif] Email batch failed log={log.id}: {exc}")

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _build_attachments(self, db: Session, log: "NotificationLog") -> List[Dict]:
        """Resolve log.attachment_urls → list of {content, filename, mime_type} dicts."""
        attachment_entries = log.attachment_urls or []
        if not attachment_entries:
            return []

        result: List[Dict] = []
        svc = EmailService()
        for entry in attachment_entries:
            url      = entry.get("url", "")
            var_key  = entry.get("var_key", "")
            att_type = (entry.get("type") or "").lower().strip()

            content: Optional[bytes] = None
            filename: str = ""
            mime_type: str = "application/octet-stream"

            if url:
                content = svc._fetch_attachment(url)
                if not content:
                    logger.warning(f"[Notif] Could not fetch attachment {url!r} for log {log.id}")
                    continue
                if att_type and att_type in self._MIME_MAP:
                    mime_type = self._MIME_MAP[att_type]
                    filename, _ = svc._guess_filename(url, var_key)
                else:
                    filename, mime_type = svc._guess_filename(url, var_key)
            elif att_type in ("pdf", "excel", "xlsx"):
                _src_type = entry.get("source_type") or log.source_type
                _src_id   = entry.get("source_id")
                _src_uuid = UUID(_src_id) if _src_id else log.source_id
                content = _generate_attachment_bytes(db, _src_type, _src_uuid, att_type)
                if not content:
                    logger.warning(
                        f"[Notif] Could not generate {att_type} for "
                        f"source={log.source_type}/{log.source_id} log={log.id}"
                    )
                    continue
                mime_type = self._MIME_MAP.get(att_type, "application/octet-stream")
                ext       = "pdf" if att_type == "pdf" else "xlsx"
                src_label = (log.source_type or "report").replace("_", "-")
                src_short = str(log.source_id)[:8] if log.source_id else "report"
                filename  = f"{src_label}-{src_short}.{ext}"
            else:
                logger.debug(f"[Notif] Skipping attachment with no url/type: {entry}")
                continue

            result.append({"content": content, "filename": filename, "mime_type": mime_type})

        return result

    @staticmethod
    def _update_log_status_from_recipients(log: "NotificationLog", now: datetime) -> None:
        """Set log.status based on the delivery_status of all its recipients."""
        statuses = {r.delivery_status for r in (log.recipients or [])}
        if not statuses or statuses <= {"skipped"}:
            log.status = "skipped"
        elif statuses <= {"sent", "skipped"}:
            log.status = "sent"
        elif "sent" in statuses:
            log.status = "sent"   # partial success — log as sent overall
        elif "failed" in statuses:
            log.status = "failed"
        else:
            log.status = "skipped"
        log.sent_at = now


class SmsDispatcher(ChannelDispatcher):
    """
    SMS channel — supports three gateways selected by SMS_PROVIDER env var:

      SMS_PROVIDER=twilio   → Twilio REST API (no SDK required — uses requests)
      SMS_PROVIDER=msg91    → MSG91 Transactional route (DLT-compliant, India)
      SMS_PROVIDER=http     → Generic HTTP POST gateway (Exotel, TextLocal, etc.)
      SMS_PROVIDER=none     → Disabled / not configured (default — logs + skips)

    Phone number normalisation
    --------------------------
    • 10-digit bare number  → +91XXXXXXXXXX  (Indian mobile)
    • Already starts with + → passed as-is  (E.164)
    • 91XXXXXXXXXX (12 dig) → +91XXXXXXXXXX

    Indian DLT compliance (MSG91)
    ------------------------------
    Indian regulations require every transactional SMS body to match a
    government-approved template registered under DLT.  Set MSG91_TEMPLATE_ID
    to your approved template ID.  If unset, the field is omitted (may cause
    delivery failure on Indian numbers).

    To add a new channel (e.g. WhatsApp):
        class WhatsAppDispatcher(ChannelDispatcher):
            channel = "whatsapp"
            def send(self, db, log, subject, body): ...
        ChannelDispatcherRegistry.register(WhatsAppDispatcher())
    """

    channel = "sms"

    # ── Config — read once at class load time ────────────────────────────────
    _provider   = _os.getenv("SMS_PROVIDER",          "none").lower().strip()
    _from       = _os.getenv("SMS_FROM_NUMBER",       "")
    # Twilio (via plain HTTP — no twilio SDK needed)
    _twilio_sid = _os.getenv("TWILIO_ACCOUNT_SID",   "")
    _twilio_tok = _os.getenv("TWILIO_AUTH_TOKEN",     "")
    # MSG91 (India — transactional / DLT route)
    _msg91_key  = _os.getenv("MSG91_AUTH_KEY",        "")
    _msg91_tmpl = _os.getenv("MSG91_TEMPLATE_ID",     "")   # DLT template ID (mandatory in IN)
    _msg91_sndr = _os.getenv("MSG91_SENDER_ID",       "SEACMS")  # 6-char DLT sender ID
    # Generic HTTP gateway
    _http_url   = _os.getenv("SMS_HTTP_URL",          "")
    _http_hdr   = _os.getenv("SMS_HTTP_AUTH_HEADER",  "Authorization")
    _http_val   = _os.getenv("SMS_HTTP_AUTH_VALUE",   "")

    # ── Public entry point ───────────────────────────────────────────────────

    def send(self, db: Session, log: "NotificationLog", subject: str, body: str) -> None:
        """
        Iterate all 'pending' NotificationLogRecipient rows for this log and
        dispatch an SMS to each phone number.
        """
        now = datetime.now(timezone.utc)

        pending = [
            r for r in (log.recipients or [])
            if r.delivery_status == "pending" and r.phone
        ]

        if not pending:
            log.status      = "skipped"
            log.error_message = "No pending SMS recipients"
            log.sent_at     = now
            return

        if self._provider in ("none", ""):
            log.status      = "skipped"
            log.error_message = "SMS_PROVIDER not configured (set SMS_PROVIDER in .env)"
            for r in pending:
                r.delivery_status = "skipped"
                r.error_message   = "SMS_PROVIDER not configured"
            return

        for r in pending:
            phone    = self._normalise_phone(r.phone)
            sms_body = self._truncate(r.rendered_body or body)
            try:
                if self._provider == "twilio":
                    self._send_twilio(phone, sms_body)
                elif self._provider == "msg91":
                    self._send_msg91(phone, sms_body)
                elif self._provider == "http":
                    self._send_http(phone, sms_body)
                else:
                    r.delivery_status = "skipped"
                    r.error_message   = f"Unknown SMS_PROVIDER={self._provider!r}"
                    logger.warning(f"[Notif] Unknown SMS_PROVIDER={self._provider!r}")
                    continue
                r.delivery_status = "sent"
                r.sent_at         = now
                logger.info(f"[Notif] SMS sent to {phone} via {self._provider}")
            except Exception as exc:
                r.delivery_status = "failed"
                r.error_message   = str(exc)[:500]
                log.retry_count   = (log.retry_count or 0) + 1
                if log.retry_count < (log.max_retries or 3):
                    log.next_retry_at = now + timedelta(minutes=RETRY_DELAY_MINUTES)
                logger.warning(f"[Notif] SMS to {phone} failed ({self._provider}): {exc}")

        EmailDispatcher._update_log_status_from_recipients(log, now)

    # ── Gateway implementations ──────────────────────────────────────────────
    # Each method raises on failure; the caller (send) handles status updates.

    def _send_twilio(self, phone: str, body: str) -> None:
        """Twilio REST API — no SDK, pure HTTP POST with Basic auth."""
        import requests as _req, base64 as _b64
        if not self._twilio_sid or not self._twilio_tok:
            raise RuntimeError("TWILIO_ACCOUNT_SID or TWILIO_AUTH_TOKEN missing in .env")
        auth = _b64.b64encode(
            f"{self._twilio_sid}:{self._twilio_tok}".encode()
        ).decode()
        url  = (
            f"https://api.twilio.com/2010-04-01/Accounts"
            f"/{self._twilio_sid}/Messages.json"
        )
        resp = _req.post(
            url,
            headers={"Authorization": f"Basic {auth}"},
            data={"From": self._from, "To": phone, "Body": body},
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"Twilio HTTP {resp.status_code}: {resp.text[:200]}")

    def _send_msg91(self, phone: str, body: str) -> None:
        """
        MSG91 transactional SMS — DLT-compliant (mandatory for Indian numbers).
        Route 4 = Transactional (OTP / alerts); Route 1 = Promotional (blocked on DND).
        """
        import requests as _req
        if not self._msg91_key:
            raise RuntimeError("MSG91_AUTH_KEY missing in .env")
        # MSG91 expects digits only (no leading +)
        to = phone.lstrip("+")
        sms_entry: Dict[str, Any] = {"message": body, "to": [to]}
        if self._msg91_tmpl:
            sms_entry["DLT_TE_ID"] = self._msg91_tmpl  # mandatory for Indian DLT
        payload = {
            "sender":  self._msg91_sndr,
            "route":   "4",     # Transactional
            "country": "91",
            "sms":     [sms_entry],
        }
        resp = _req.post(
            "https://api.msg91.com/api/v5/flow/",
            headers={"authkey": self._msg91_key, "Content-Type": "application/json"},
            json=payload,
            timeout=15,
        )
        # MSG91 returns 200 for success; body contains {"type":"success"} or error detail
        try:
            data = resp.json()
        except Exception:
            data = {}
        if not (resp.status_code == 200 and data.get("type") != "error"):
            raise RuntimeError(f"MSG91 {resp.status_code}: {resp.text[:200]}")

    def _send_http(self, phone: str, body: str) -> None:
        """
        Generic HTTP POST gateway.
        Posts JSON: {"to": "<phone>", "from": "<SMS_FROM_NUMBER>", "body": "<text>"}
        Configure SMS_HTTP_URL + optional auth header via SMS_HTTP_AUTH_HEADER / VALUE.
        """
        import requests as _req
        if not self._http_url:
            raise RuntimeError("SMS_HTTP_URL missing in .env")
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if self._http_hdr and self._http_val:
            headers[self._http_hdr] = self._http_val
        resp = _req.post(
            self._http_url,
            headers=headers,
            json={"to": phone, "from": self._from, "body": body},
            timeout=15,
        )
        if resp.status_code not in (200, 201, 202):
            raise RuntimeError(
                f"HTTP gateway {resp.status_code}: {resp.text[:200]}"
            )

    # ── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_phone(phone: str) -> str:
        """
        Normalise to E.164.
        • 10-digit bare number  → +91XXXXXXXXXX  (Indian mobile)
        • 91XXXXXXXXXX (12 dig) → +91XXXXXXXXXX
        • Already E.164 (+...)  → unchanged
        """
        p = phone.strip().replace(" ", "").replace("-", "")
        if p.startswith("+"):
            return p
        if len(p) == 10 and p.isdigit():
            return "+91" + p
        if len(p) == 12 and p.startswith("91") and p.isdigit():
            return "+" + p
        return p  # pass through; gateway will reject if malformed

    @staticmethod
    def _truncate(body: str, limit: int = 160) -> str:
        """Truncate to single-segment SMS length (160 GSM7 chars)."""
        return (body[:157] + "…") if len(body) > limit else body


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
    ueic: Optional[str] = None,
    extra_data: Optional[dict] = None,
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
        ueic=ueic or None,
        extra_data=extra_data or None,
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
    """
    Mark pending logs in window as digested and send one digest email per unique
    recipient address (collected from NotificationLogRecipient rows).
    """
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=DIGEST_WINDOW_MINUTES)
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

    # Collect unique email addresses across all log recipients
    by_email: Dict[str, List[NotificationLog]] = {}
    for log in pending:
        for rcpt in (log.recipients or []):
            if rcpt.email and rcpt.delivery_status == "pending":
                by_email.setdefault(rcpt.email, []).append(log)

    event_label = event_type.replace("_", " ").title()
    for email, logs in by_email.items():
        digest_body = (
            f"<h3>Digest: {len(logs)} {event_label} alert(s)</h3><ul>"
            + "".join(f"<li>{l.body or ''}</li>" for l in logs[:20])
            + ("</ul><p>…and more</p>" if len(logs) > 20 else "</ul>")
        )
        digest_subject = f"[Digest] {len(logs)} × {event_label}"
        try:
            EmailService().send_email_starttls(email, digest_subject, digest_body)
        except Exception as exc:
            logger.warning(f"[Notif] Digest email to {email} failed: {exc}")

    for log in pending:
        log.status  = "digested"
        log.sent_at = now
        for rcpt in (log.recipients or []):
            if rcpt.delivery_status == "pending":
                rcpt.delivery_status = "sent"
                rcpt.sent_at         = now

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
    activity_type: Optional[str] = None,
    status_from: Optional[str] = None,
    status_to: Optional[str] = None,
    require_followup: bool = False,
) -> Optional["NotificationRoutingRule"]:
    """
    Find the best-matching active routing rule for a fire() call.

    When require_followup=True, only rules whose followup_action has
    create_request=true are considered — used to find the ticket-creating rule
    independently of the channel-routing rule (an org may have a notification-only
    rule that wins channel selection while a separate rule carries the followup).

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
            # load both global (org_id IS NULL) and org-specific rows.
            # NOTE: SQL IN (NULL, ...) never matches NULL rows — must use OR + IS NULL.
            (
                NotificationRoutingRule.organization_id.is_(None)
                if organization_id is None
                else or_(
                    NotificationRoutingRule.organization_id.is_(None),
                    NotificationRoutingRule.organization_id == organization_id,
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
        if require_followup:
            _fa = rule.followup_action or {}
            if not _fa.get("create_request"):
                continue
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
        # advanced_conditions.activity_types — empty/absent = all tests for this equipment
        _adv_types = ((rule.advanced_conditions or {}).get("activity_types") or [])
        if _adv_types and activity_type not in _adv_types:
            continue
        return rule   # first match wins (already sorted: org > global, high priority first)

    return None   # no rule → permissive default (all channels fire)


# ── Follow-up action executor ─────────────────────────────────────────────────

def _execute_followup_action(
    db: Session,
    action: dict,
    source_id: Optional[UUID],
    source_type: Optional[str],
    organization_id: Optional[UUID],
    department_id: Optional[UUID],
) -> None:
    """
    Auto-create a follow-up ticket when eval_alert / eval_critical fires
    and the matched routing rule has a followup_action config.

    Ticket details come from the routing rule's followup_action JSONB (defined
    in the notification center), not from the linked Recommendation record.

    action format (from NotificationRoutingRule.followup_action):
    {
        "create_request":     true,
        "next_action":        "maintenance",   # test/maintenance/inspection/repair_cycle
        "schedule_frequency": "yearly",
        "schedule_start_date":"2026-01-01",
        "schedule_end_date":  "2026-12-31",
        "test_types":         [{"id": 5, "name": "BDV Test"}],
        "summary":            "Follow-up after CRITICAL alert"
    }
    """
    logger.info(f"[FollowupAction] action={action} source_type={source_type!r} source_id={source_id}")

    if not action.get("create_request"):
        logger.info("[FollowupAction] Skipping — create_request is not true")
        return

    next_action_str = (action.get("next_action") or "").lower()
    if not next_action_str:
        logger.info("[FollowupAction] Skipping — next_action is empty")
        return

    # ── Resolve the TestingRequest from the source ────────────────────────────
    from models import (
        TestingRequest, TestResult,
        Recommendation, NextActionType, ScheduleFrequency, RequestCategory,
    )
    tr: Optional[TestingRequest] = None

    if source_type == "test_result" and source_id:
        result_row = db.query(TestResult).filter(TestResult.id == source_id).first()
        logger.info(f"[FollowupAction] result_row={result_row} testing_request_id={getattr(result_row, 'testing_request_id', None)}")
        if result_row and result_row.testing_request_id:
            tr = db.query(TestingRequest).filter(
                TestingRequest.id == result_row.testing_request_id
            ).first()
    elif source_type == "testing_request" and source_id:
        tr = db.query(TestingRequest).filter(TestingRequest.id == source_id).first()

    if not tr:
        logger.warning(
            f"[FollowupAction] Cannot resolve TestingRequest from "
            f"source_type={source_type!r} source_id={source_id}"
        )
        return

    logger.info(f"[FollowupAction] TR={tr.request_number} equipment_id={tr.equipment_id} title={tr.title!r}")

    # ── Guard: skip if open follow-up already exists for this equipment ───────
    followup_category = next_action_str

    if tr.equipment_id:
        # Open = any non-terminal status. Generated follow-up tickets start as
        # 'draft' (then assigned/submitted), so the dedup MUST include draft —
        # otherwise a second alert fire creates a duplicate ticket because the
        # first (draft) follow-up isn't matched.
        _open_statuses = [
            "draft", "submitted", "assigned", "accepted", "in_progress",
            "test_submitted", "under_approval", "under_review",
        ]
        existing = (
            db.query(TestingRequest)
            .filter(
                TestingRequest.equipment_id     == tr.equipment_id,
                TestingRequest.organization_id  == (organization_id or tr.organization_id),
                TestingRequest.request_category == followup_category,
                TestingRequest.status.in_(_open_statuses),
                TestingRequest.is_schedule_template.is_(False),
                # Don't count the triggering test request itself — otherwise an
                # alert whose follow-up category matches the in-progress test
                # (e.g. next_action="test") is blocked by the very test that
                # fired it. Only pre-existing OTHER open follow-ups should skip.
                TestingRequest.id != tr.id,
            )
            .first()
        )
        if existing:
            logger.info(
                f"[FollowupAction] Skipping — open {followup_category} request "
                f"{existing.request_number} already exists for equipment {tr.equipment_id}"
            )
            return

    # ── Build Recommendation from notification center followup_action config ──
    try:
        _next_action = NextActionType(next_action_str)
    except ValueError:
        logger.warning(f"[FollowupAction] Invalid next_action={next_action_str!r}")
        return

    _freq_str = action.get("schedule_frequency") or "yearly"
    try:
        _freq = ScheduleFrequency(_freq_str)
    except ValueError:
        _freq = ScheduleFrequency.yearly

    _test_types = action.get("test_types") or []
    logger.info(f"[FollowupAction] next_action={next_action_str!r} freq={_freq_str!r} test_types={_test_types} tr.test_type_id={tr.test_type_id}")

    mock_rec = Recommendation(
        testing_request_id  = tr.id,
        organization_id     = organization_id or tr.organization_id,
        next_action         = _next_action,
        schedule_frequency  = _freq,
        test_types          = _test_types,
        summary             = action.get("summary") or f"Auto follow-up: {next_action_str}",
        recommendation_type = "fail",
        submitted_by        = tr.created_by,
        created_by          = tr.created_by,
        approval_status     = "approved",
    )

    # ── Dispatch via WorkflowDispatchService ──────────────────────────────────
    from services.workflow_dispatch_service import WorkflowDispatchService
    from models import RequestCategory as _RC

    _rc_map = {
        "test":        _RC.test,
        "maintenance": _RC.maintenance,
        "inspection":  _RC.inspection,
    }
    _category = _rc_map.get(next_action_str)
    logger.info(f"[FollowupAction] _category={_category}")

    svc = WorkflowDispatchService(db)

    try:
        if _category:
            # force_immediate_ticket=True → _create_schedule creates the first
            # ticket right away (single creation point). Do NOT also create the
            # ticket here, or the same schedule would yield two tickets.
            schedule_ids = svc._create_schedules_for_action(
                tr, mock_rec,
                approver_id=tr.created_by,
                category=_category,
                force_immediate_ticket=True,
            )
            db.commit()
            logger.info(
                f"[FollowupAction] Created {len(schedule_ids)} {next_action_str} "
                f"schedule(s) for TR={tr.request_number}: {schedule_ids}"
            )
        elif next_action_str == "repair_cycle":
            wf_id = svc._start_repair_workflow(tr, approver_id=tr.created_by)
            db.commit()
            logger.info(
                f"[FollowupAction] Started repair workflow {wf_id} "
                f"for TR={tr.request_number}"
            )
        else:
            logger.warning(
                f"[FollowupAction] Unhandled next_action={next_action_str!r} "
                f"for TR={tr.request_number}"
            )
    except Exception as _exc:
        import traceback as _tb
        db.rollback()
        logger.warning(f"[FollowupAction] Dispatch failed: {_exc}\n{_tb.format_exc()}")


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
        recipient_roles_override: Optional[List[str]] = None,  # overrides template roles when provided
        # ── Routing context (used by NotificationRoutingRule matching) ────────
        workflow_type: Optional[str] = None,    # "direct_test"|"failure_register"|"taqc"|"multisession"|"schedule"
        equipment_type: Optional[str] = None,   # e.g. "Power Transformer", "CT"
        test_type: Optional[str] = None,        # "test"|"inspection"|"maintenance"|"life_cycle"
        activity_type: Optional[str] = None,    # specific test name, e.g. "Short Circuit Test HV-IV"
        status_from: Optional[str] = None,      # e.g. "submitted"
        status_to: Optional[str] = None,        # e.g. "under_review"
        extra_data: Optional[dict] = None,      # arbitrary structured payload (e.g. kit availability)
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

            resolved_ctx = VariableResolver.build_context(context, db=self.db)

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
                activity_type=activity_type,
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
            logger.info(
                f"[Notif:fire] event={event_type!r} org={organization_id} "
                f"workflow={workflow_type!r} source={source_type}/{source_id} "
                f"→ rule={'NONE (permissive)' if not routing else routing.id} "
                f"org_rule={routing.organization_id if routing else 'N/A'} "
                f"channels={allowed_channels} override={roles_override}"
            )

            for tmpl in templates:
                # ── Channel filter from routing rule ─────────────────────────
                if allowed_channels is not None and tmpl.channel not in allowed_channels:
                    logger.debug(
                        f"[Notif] Skipping channel={tmpl.channel!r} for "
                        f"event={event_type!r} (routing rule blocked)"
                    )
                    continue

                # ── Recipient roles: caller override → routing rule override → template ─
                effective_roles = (
                    recipient_roles_override
                    or roles_override
                    or list(tmpl.recipient_roles or [])
                )

                # ── Recipient resolution ─────────────────────────────────────
                # Handles both @system-tokens (resolved from source record)
                # and regular OrgRole UUIDs / name strings.
                recipients = _resolve_recipients_by_roles(
                    self.db,
                    effective_roles,
                    organization_id,
                    department_id=department_id,
                    source_type=source_type,
                    source_id=source_id,
                )
                logger.debug(
                    f"[Notif] fire event={event_type!r} "
                    f"roles={effective_roles} override={roles_override} dept={department_id} "
                    f"→ {len(recipients)} recipient(s)"
                )

                # ── Caller-supplied extra User objects (e.g. test-fire) ──────
                if extra_recipients:
                    seen_ids = {u.id for u in recipients}
                    for u in extra_recipients:
                        if u.id not in seen_ids:
                            recipients.append(u)
                            seen_ids.add(u.id)

                dispatched_emails: set = {u.email for u in recipients if u.email}

                # ── Create ONE batch NotificationLog for this template+channel ─
                # Base context render (no user-specific vars yet) used as the
                # "preview" body stored on the log row.
                _base_subj = _render(tmpl.subject_template or "", resolved_ctx)
                _base_body = _render(tmpl.body_template,            resolved_ctx)

                # Resolve shared attachment URLs at log level (not per-user)
                _resolved_att_urls: List[Dict] = []
                if tmpl.channel == "email" and tmpl.attachment_vars and resolved_ctx:
                    for av in (tmpl.attachment_vars or []):
                        if isinstance(av, dict):
                            var_key      = av.get("var_key", "")
                            att_type     = (av.get("type") or "").lower()
                            av_src_type  = av.get("source_type", "")
                        else:
                            var_key      = str(av)
                            att_type     = ""
                            av_src_type  = ""
                        url = resolved_ctx.get(var_key, "")
                        if url and not _is_uuid_str(url):
                            # Real URL → fetch and attach
                            entry: Dict[str, str] = {"url": url, "var_key": var_key}
                            if att_type:
                                entry["type"] = att_type
                            _resolved_att_urls.append(entry)
                        elif url and _is_uuid_str(url) and att_type:
                            # Context held a UUID → generate from that source record
                            _resolved_att_urls.append({
                                "type":        att_type,
                                "var_key":     var_key,
                                "source_type": av_src_type or (str(source_type) if source_type else "testing_request"),
                                "source_id":   url,
                            })
                        elif att_type in ("pdf", "excel", "xlsx") and source_type and source_id:
                            _resolved_att_urls.append({
                                "type":        att_type,
                                "var_key":     var_key,
                                "source_type": str(source_type),
                                "source_id":   str(source_id),
                            })

                batch_log = NotificationLog(
                    organization_id=organization_id,
                    event_type=event_type,
                    channel=tmpl.channel,
                    subject=_base_subj,
                    body=_base_body,
                    status="pending",
                    source_id=source_id,
                    source_type=source_type,
                    attachment_urls=_resolved_att_urls,
                )
                self.db.add(batch_log)
                self.db.flush()   # get batch_log.id

                # ── Create NotificationLogRecipient per user ──────────────────
                for user in recipients:
                    # Per-user context
                    user_ctx = dict(resolved_ctx)
                    _fname = (user.firstname or "").strip()
                    _lname = (user.lastname or "").strip()
                    user_ctx["user.name"]  = f"{_fname} {_lname}".strip() or user.email or ""
                    user_ctx["user.email"] = user.email or ""
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

                    r_subj = _render(tmpl.subject_template or "", user_ctx)
                    r_body = _render(tmpl.body_template,            user_ctx)

                    self._dispatch_to_user(
                        batch_log=batch_log,
                        tmpl=tmpl, user=user,
                        subject=r_subj, body=r_body,
                        event_type=event_type, organization_id=organization_id,
                        source_id=source_id, source_type=source_type, severity=severity,
                        org_name=_org_name,
                        resolved_ctx=user_ctx,
                        extra_data=extra_data,
                    )

                # If inapp channel: mark batch log sent right away
                if tmpl.channel == "inapp":
                    batch_log.status  = "sent"
                    batch_log.sent_at = datetime.now(timezone.utc)

                # ── extra_recipient_emails → NotificationLogRecipient rows ────
                if tmpl.channel == "email":
                    for addr in (tmpl.extra_recipient_emails or []):
                        if addr and addr not in dispatched_emails:
                            dispatched_emails.add(addr)
                            # Render without user vars (no User object)
                            e_subj = _render(tmpl.subject_template or "", resolved_ctx)
                            e_body = _render(tmpl.body_template,            resolved_ctx)
                            dispatcher = ChannelDispatcherRegistry.get("email")
                            if dispatcher:
                                e_body = dispatcher.prepare_body(
                                    e_body, subject=e_subj, org_name=_org_name
                                )
                            extra_rcpt = NotificationLogRecipient(
                                log_id=batch_log.id,
                                user_id=None,
                                email=addr,
                                rendered_subject=e_subj,
                                rendered_body=e_body,
                                delivery_status="pending",
                            )
                            self.db.add(extra_rcpt)

                if not recipients and not (tmpl.extra_recipient_emails):
                    logger.debug(
                        f"[Notif] event={event_type!r} channel={tmpl.channel!r}: "
                        f"no recipients for roles {effective_roles}"
                    )

                try:
                    self.db.commit()
                except Exception as exc:
                    logger.error(f"[Notif] DB commit failed after enqueue: {exc}")
                    self.db.rollback()

            # ── Follow-up action (eval_alert / eval_critical only) ───────────
            # If the matched routing rule has a followup_action config, create
            # the downstream ticket using WorkflowDispatchService — same logic
            # as the recommendation wizard approval flow.
            if event_type in ("eval_alert", "eval_critical"):
                # The channel-routing rule may be a notification-only rule (no
                # followup_action). Resolve the ticket-creating rule independently
                # so a separate matching rule with a followup_action still fires.
                followup_rule = routing if (
                    routing and (routing.followup_action or {}).get("create_request")
                ) else _resolve_routing(
                    self.db, event_type, organization_id,
                    workflow_type=workflow_type,
                    equipment_type=equipment_type,
                    test_type=test_type,
                    activity_type=activity_type,
                    status_from=status_from,
                    status_to=status_to,
                    require_followup=True,
                )
                if followup_rule and followup_rule.followup_action:
                    try:
                        _execute_followup_action(
                            db=self.db,
                            action=followup_rule.followup_action,
                            source_id=source_id,
                            source_type=source_type,
                            organization_id=organization_id,
                            department_id=department_id,
                        )
                    except Exception as _fa_exc:
                        logger.warning(
                            f"[Notif] followup_action failed for event={event_type!r}: {_fa_exc}"
                        )
                else:
                    logger.info(
                        f"[Notif] {event_type}: no routing rule with a followup_action "
                        f"matched (org={organization_id}, equip_type={equipment_type!r}, "
                        f"workflow={workflow_type!r}) — notification sent, no ticket created"
                    )

        except Exception as exc:
            logger.error(f"[Notif] fire() failed for event_type={event_type!r}: {exc}")
            traceback.print_exc()

    def retry_failed(self) -> int:
        """
        Retry all NotificationLog batch rows in status='failed' with
        retry_count < max_retries whose next_retry_at <= now.
        Only recipients still in 'failed' status are re-sent.
        Called by APScheduler every 5 min.  Returns number of logs retried.
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
            # Reset failed recipients to pending so the dispatcher retries them
            for r in (log.recipients or []):
                if r.delivery_status == "failed":
                    r.delivery_status = "pending"
                    r.error_message   = None
            log.status = "pending"
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
        _eq = getattr(request, "equipment", None)
        if _eq:
            _eq_type = getattr(_eq, "equipment_type", None)
            if _eq_type:
                return getattr(_eq_type, "name", None)
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
        # Resolve originator display name
        _orig = getattr(request, "originator", None)
        if _orig:
            _orig_name = (
                f"{_orig.firstname or ''} {_orig.lastname or ''}".strip()
                or _orig.email or ""
            )
        else:
            _orig_name = ""
        # Resolve category as plain string (request_category is an Enum)
        _cat_raw = getattr(request, "request_category", "test")
        _category = _cat_raw.value if hasattr(_cat_raw, "value") else str(_cat_raw)
        self.fire(
            event_type="request_submitted",
            context={
                "equipment":           equipment_label,
                "request_number":      getattr(request, "request_number", ""),
                # dot-notation keys match template variables directly
                "request.number":      getattr(request, "request_number", ""),
                "request.priority":    getattr(request, "priority", "normal") or "normal",
                "request.submitted_by": _orig_name,
                "originator":          _orig_name,
                "category":            _category,
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

    def notify_request_rejected(self, request, rejected_by: str, reason: str) -> None:
        """Triggered when a testing request is rejected by an approver."""
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        self.fire(
            event_type="request_rejected",
            context={
                "equipment": equipment_label,
                "request_number": getattr(request, "request_number", ""),
                "rejected_by": rejected_by,
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
            status_to="rejected",
        )

    def notify_tr_wf_stage_changed(
        self,
        request,
        action_code: str,
        stage_name: str,
        status_code: Optional[str],
        performed_by: str,
        comment: Optional[str],
        is_terminal: bool,
        from_status_code: Optional[str],
        recipient_roles_override: Optional[list] = None,
    ) -> None:
        """
        Fired on every non-rejection TR workflow stage transition.
        Uses event_type='tr_wf_status_changed'; falls back to 'request_submitted'
        templates when no specific template exists, so notifications always fire.
        """
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        ctx = {
            "request_number":  getattr(request, "request_number", ""),
            "request.number":  getattr(request, "request_number", ""),
            "equipment":       equipment_label,
            "stage_name":      stage_name,
            "action_code":     action_code,
            "performed_by":    performed_by,
            "comment":         comment or "",
            "status_code":     status_code or "",
            "is_terminal":     str(is_terminal),
        }
        common = dict(
            context=ctx,
            organization_id=getattr(request, "organization_id", None),
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_from=from_status_code,
            status_to=status_code,
            recipient_roles_override=recipient_roles_override,
        )
        # Try the specific event type first; if no templates exist fall back to
        # request_submitted so the notification always reaches recipients.
        templates = self._get_templates("tr_wf_status_changed", getattr(request, "organization_id", None))
        if templates:
            self.fire(event_type="tr_wf_status_changed", **common)
        else:
            self.fire(event_type="request_submitted", **common)

    def notify_tester_assigned(self, request) -> None:
        """Triggered when a tester is assigned to a testing request."""
        equipment_label = (
            request.equipment.ueic if request.equipment else
            (request.equipment_type.name if request.equipment_type else "Equipment")
        )
        kit_data = self._build_kit_availability(request)
        tester_name = ""
        if request.assigned_tester:
            tester_name = (
                f"{request.assigned_tester.firstname or ''} "
                f"{request.assigned_tester.lastname or ''}".strip()
                or request.assigned_tester.email or ""
            )
        # Resolve test type display name: prefer CategoryDetails.name via relationship,
        # fall back to request_category enum value so the template never shows raw {tr.test_type}.
        _tt_rel = getattr(request, "test_type", None)
        if _tt_rel and getattr(_tt_rel, "name", None):
            _test_type_label = _tt_rel.name
        else:
            _rc = getattr(request, "request_category", None)
            _test_type_label = (_rc.value if hasattr(_rc, "value") else str(_rc or "")).capitalize()
        _eq_type_label = self._equipment_type(request) or ""
        _kit_html      = _build_kit_html(kit_data)
        _ctx: dict = {
            "equipment":      equipment_label,
            "request_number": getattr(request, "request_number", ""),
            "tester":         request.assigned_tester.email if request.assigned_tester else "",
            "tester_name":    tester_name,
            "tr.test_type":   _test_type_label,
        }
        # Only pre-seed non-empty values — empty strings would block setdefault
        # in _enrich_context_from_source from filling them in via DB lookup
        if _eq_type_label:
            _ctx["equipment.type"] = _eq_type_label
        if _kit_html:
            _ctx["kit_availability_html"] = _kit_html
        self.fire(
            event_type="tester_assigned",
            context=_ctx,
            organization_id=getattr(request, "organization_id", None),
            department_id=self._dept(request),
            source_id=request.id,
            source_type="testing_request",
            severity="info",
            workflow_type=self._workflow_type(request),
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="assigned",
            extra_data=self._build_kit_availability(request),
        )

    def _build_kit_availability(self, request) -> dict:
        """Build kit availability data for tester assignment notification."""
        try:
            from models import CategoryMaster, Equipment, EquipmentTypeKitMapping, OrgDepartment
            from sqlalchemy import and_

            kit_master = self.db.query(CategoryMaster).filter(
                CategoryMaster.name == "Testing Kit",
                CategoryMaster.is_active == True,
            ).first()
            if not kit_master:
                return {}

            # Resolve equipment type ID — fall back to equipment's own type
            eq_type_id = getattr(request.equipment_type, "id", None) if request.equipment_type else None
            if not eq_type_id:
                _eq = getattr(request, "equipment", None)
                if _eq:
                    eq_type_id = getattr(_eq, "equipment_type_id", None)
            dept_id = self._dept(request)

            # Required kit types for this equipment type
            mappings = []
            if eq_type_id:
                mappings = self.db.query(EquipmentTypeKitMapping).filter(
                    EquipmentTypeKitMapping.equipment_type_id == eq_type_id,
                ).all()

            if not mappings:
                return {}

            # Build ordered ancestor chain: [station, parent, grandparent, ...]
            ancestor_chain: list = []
            if dept_id:
                _walk = dept_id
                _seen: set = set()
                while _walk and _walk not in _seen:
                    _seen.add(_walk)
                    _d = self.db.query(OrgDepartment).filter(OrgDepartment.id == _walk).first()
                    if not _d:
                        break
                    if _d.parent_department_id and _d.parent_department_id not in _seen:
                        ancestor_chain.append(_d.parent_department_id)
                    _walk = _d.parent_department_id

            kit_availability = []
            for m in mappings:
                kit_type = m.kit_type
                kit_type_name = kit_type.name if kit_type else f"Kit #{m.kit_type_id}"

                # Check at station first
                at_station = []
                if dept_id:
                    at_station = self.db.query(Equipment).filter(
                        Equipment.equipment_type_id == kit_master.id,
                        Equipment.department_id == dept_id,
                        Equipment.status == "active",
                    ).all()

                # Walk entire ancestor chain — collect ALL depts that have this kit
                avail_at_depts: list = []
                if not at_station:
                    for anc_id in ancestor_chain:
                        anc_kit = self.db.query(Equipment).filter(
                            Equipment.equipment_type_id == kit_master.id,
                            Equipment.department_id == anc_id,
                            Equipment.status == "active",
                        ).first()
                        if anc_kit:
                            anc_dept = self.db.query(OrgDepartment).filter(
                                OrgDepartment.id == anc_id
                            ).first()
                            avail_at_depts.append(anc_dept.name if anc_dept else str(anc_id))

                kit_availability.append({
                    "kit_type": kit_type_name,
                    "is_required": m.is_required,
                    "available_at_station": len(at_station) > 0,
                    "count_at_station": len(at_station),
                    "available_at_depts": avail_at_depts,
                })

            return {"required_kits": kit_availability}
        except Exception as e:
            logger.warning(f"[kit_availability] Failed to build kit data: {e}")
            return {}

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
        # equipment.equipment_type is a SQLAlchemy relationship (CategoryMaster),
        # not a plain string — resolve .name to avoid "CategoryMaster object" repr.
        _eq_type_rel = getattr(equipment, "equipment_type", None)
        if _eq_type_rel and hasattr(_eq_type_rel, "name"):
            eq_type = _eq_type_rel.name or "Equipment"
        else:
            eq_type = getattr(equipment, "equipment_type_name", "") or "Equipment"
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
        # equipment.equipment_type is a SQLAlchemy relationship (CategoryMaster object),
        # not a plain string — resolve .name to avoid Python object repr in the subject.
        _eq_type_rel = getattr(equipment, "equipment_type", None)
        if _eq_type_rel and hasattr(_eq_type_rel, "name"):
            eq_type = _eq_type_rel.name or "Equipment"
        else:
            eq_type = getattr(equipment, "equipment_type_name", "") or "Equipment"
        # Equipment model has department_id, not department_name — look it up
        dept = getattr(equipment, "department_name", "") or ""
        if not dept:
            _dept_id = getattr(equipment, "department_id", None)
            if _dept_id:
                try:
                    from models import OrgDepartment as _OD
                    _d = self.db.query(_OD).filter(_OD.id == _dept_id).first()
                    if _d:
                        dept = _d.name or ""
                except Exception:
                    pass
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

    def notify_fr_rejected(
        self,
        request,
        rejected_by: str,
        rejection_reason: str,
    ) -> None:
        """
        Fired when a Failure Register entry is rejected by a reviewer.
        Notifies the submitter so they can revise and resubmit.

        Args:
            request:          The FailureRegister (or TestingRequest) ORM object.
            rejected_by:      Display name or email of the user who rejected it.
            rejection_reason: Free-text reason supplied by the reviewer.
        """
        equipment_label = (
            request.equipment.ueic if getattr(request, "equipment", None)
            else getattr(request, "equipment_type_name", "Equipment")
        )
        self.fire(
            event_type="fr_rejected",
            context={
                "equipment":        equipment_label,
                "request_number":   getattr(request, "request_number", ""),
                "rejected_by":      rejected_by,
                "rejection_reason": rejection_reason,
            },
            organization_id=getattr(request, "organization_id", None),
            department_id=self._dept(request),
            source_id=getattr(request, "id", None),
            source_type="testing_request",
            severity="alert",
            workflow_type="failure_registry",
            equipment_type=self._equipment_type(request),
            test_type=self._test_type(request),
            status_to="rejected",
        )

    def notify_repair_stage_changed(
        self,
        equipment,
        repair_stage: str,
        previous_stage: str = "",
        assigned_to: str = "",
        organization_id=None,
        department_id=None,
    ) -> None:
        """
        Fired when a repair lifecycle workflow advances to a new stage.
        Sends an in-app notification only (see routing rule — channels: ["inapp"]).

        Args:
            equipment:      The Equipment ORM object being repaired.
            repair_stage:   The name of the newly activated stage.
            previous_stage: The name of the stage that just completed (optional).
            assigned_to:    Display name / email of the engineer assigned to this stage.
            organization_id: Override org if not available on the equipment object.
            department_id:  Override dept for recipient scoping.
        """
        ueic    = getattr(equipment, "ueic",                 "N/A")
        eq_type = getattr(equipment, "equipment_type_name",  "Equipment")
        dept    = getattr(equipment, "department_name",      "")
        self.fire(
            event_type="repair_stage_changed",
            context={
                "equipment":      ueic,
                "equipment_type": eq_type,
                "department":     dept,
                "repair_stage":   repair_stage,
                "previous_stage": previous_stage,
                "assigned_to":    assigned_to,
            },
            organization_id=organization_id or getattr(equipment, "organization_id", None),
            department_id=department_id,
            source_id=getattr(equipment, "id", None),
            source_type="equipment",
            severity="info",
            workflow_type="repair_lifecycle",
            equipment_type=eq_type,
        )

    def notify_aggregate_summary(
        self,
        event_type: str,
        requests: list,
        organization_id,
        severity: str = "info",
    ) -> None:
        """
        Fired by the recurring scheduler job.

        Sends ONE notification per recipient with an aggregate summary of all
        matching TestingRequests — instead of one notification per request.

        This is the correct delivery model for periodic digest-style rules
        (e.g. "Weekly Open Tests Summary", "Monthly Overdue Tests Summary")
        where firing one notification per open test would be noisy.

        Context variables available in templates:
          {{count}}          — total matching requests
          {{overdue_count}}  — subset that are past due
          {{items_table}}    — HTML <table> of first 50 requests (email)
          {{items_plain}}    — plain-text bullet list (SMS / in-app)
          {{report_date}}    — today's date string
        """
        from datetime import date as _date
        today = _date.today()

        if not requests:
            return

        overdue = [
            r for r in requests
            if getattr(r, "due_date", None) and (
                (r.due_date.date() if hasattr(r.due_date, "date") else r.due_date) < today
            )
        ]

        # Plain text for SMS / in-app (capped at 30 items)
        items_plain = "\n".join(
            "• " + getattr(r, "request_number", str(r.id))
            + (f" — {r.equipment.ueic}" if getattr(r, "equipment", None) else "")
            for r in requests[:30]
        )

        # HTML table for email (capped at 50 rows)
        rows = []
        for r in requests[:50]:
            eq = (
                r.equipment.ueic if getattr(r, "equipment", None) else
                (r.equipment_type.name if getattr(r, "equipment_type", None) else "–")
            )
            due = (
                str(r.due_date.date() if hasattr(r.due_date, "date") else r.due_date)
                if getattr(r, "due_date", None) else "–"
            )
            st = r.status.value if hasattr(r.status, "value") else str(r.status or "–")
            rows.append(
                f"<tr><td>{getattr(r, 'request_number', '–')}</td>"
                f"<td>{eq}</td><td>{st}</td><td>{due}</td></tr>"
            )
        items_html = (
            "<table border='1' cellpadding='4' style='border-collapse:collapse;font-size:13px'>"
            "<tr style='background:#f0f0f0'>"
            "<th>Request #</th><th>Equipment</th><th>Status</th><th>Due Date</th>"
            "</tr>"
            + "".join(rows)
            + "</table>"
        )

        self.fire(
            event_type=event_type,
            context={
                "count":         str(len(requests)),
                "overdue_count": str(len(overdue)),
                "items_table":   items_html,
                "items_plain":   items_plain,
                "report_date":   str(today),
            },
            organization_id=organization_id,
            source_id=None,       # no single source — aggregate across many TRs
            source_type=None,
            severity=severity,
        )

    # Default columns used when digest_columns is NULL on the schedule rule.
    # Admins can override per-rule via the Notification Center UI.
    DEFAULT_DIGEST_COLUMNS: list = [
        {"field": "equipment",  "header": "Equipment"},
        {"field": "department", "header": "Department"},
        {"field": "due_date",   "header": "Due Date"},
        {"field": "days",       "header": "Days"},
        {"field": "request",    "header": "Request No."},
        {"field": "status",     "header": "Status"},
    ]

    @staticmethod
    def _resolve_digest_cell(field: str, r, due, today) -> str:
        """Resolve a single cell value from a field name."""
        if field == "equipment":
            return (
                getattr(getattr(r, "equipment", None), "ueic", "")
                or getattr(getattr(r, "equipment_type", None), "name", "")
                or ""
            )
        if field == "department":
            return getattr(getattr(r, "department", None), "name", "") or ""
        if field == "due_date":
            return str(due or "")
        if field == "days":
            if due is None:
                return ""
            return (
                str(max((today - due).days, 0)) if due < today
                else str(max((due - today).days, 0))
            )
        if field == "request":
            return r.request_number or str(r.id)[:8]
        if field == "status":
            return r.status.value if hasattr(r.status, "value") else str(r.status)
        if field == "priority":
            return getattr(r, "priority", "") or ""
        if field == "category":
            cat = getattr(r, "request_category", None)
            return cat.value if cat and hasattr(cat, "value") else str(cat or "")
        if field == "assigned_to":
            tester = getattr(r, "assigned_tester", None)
            if tester:
                return (
                    f"{getattr(tester, 'firstname', '') or ''} "
                    f"{getattr(tester, 'lastname', '') or ''}".strip()
                    or getattr(tester, "email", "") or ""
                )
            return ""
        return ""

    @staticmethod
    def build_digest_table(group: list, today, columns: list = None) -> str:
        """
        Build the HTML table injected as {{digest_table}} in scheduled digest emails.

        ``group``   — list of (TestingRequest, due_date, rule) tuples.
        ``today``   — date.today() from the scheduler.
        ``columns`` — list of {"field": ..., "header": ..., "style": ...} dicts.
                      Pass rule.digest_columns to use per-rule config,
                      or None to fall back to DEFAULT_DIGEST_COLUMNS.

        Supported field values:
            equipment, department, due_date, days, request,
            status, priority, category, assigned_to
        """
        cols = columns or NotificationService.DEFAULT_DIGEST_COLUMNS

        TD_base = "padding:6px 10px;border:1px solid #ddd;font-size:13px"
        TH_base = "padding:6px 10px;border:1px solid #ddd;background:#1E3C72;color:#fff;font-size:13px;text-align:left"

        # Header row
        headers = "".join(
            f"<th style='{TH_base};{col.get('style', '')}'>{col['header']}</th>"
            for col in cols
        )

        # Data rows
        rows_html = "".join(
            "<tr>"
            + "".join(
                f"<td style='{TD_base};{col.get('style', '')}'>"
                f"{NotificationService._resolve_digest_cell(col['field'], r, due, today)}"
                f"</td>"
                for col in cols
            )
            + "</tr>"
            for r, due, _ in group
        )

        return (
            f"<table cellspacing='0' style='border-collapse:collapse;width:100%'>"
            f"<tr>{headers}</tr>"
            f"{rows_html}"
            f"</table>"
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
        Per-(channel, variant-name) slot resolution: org-specific wins over global.

        Old behaviour (REMOVED):
          All-or-nothing — if ANY org template existed the entire global set was
          suppressed, causing unoverridden channels (e.g. sms / inapp) to silently
          stop firing once an org touched a single channel.  If fire() was also
          called without org_id the global set fired independently, producing
          duplicate notifications.

        New behaviour:
          For each (channel, name) slot independently:
            • Org template exists   → use org template; global for that slot ignored.
            • No org template       → fall back to global template for that slot.

          Examples:
            Org overrides email only → email=org, sms=global, inapp=global  (no drops)
            Org overrides all        → email=org, sms=org,    inapp=org     (no globals)
            No org templates         → all channels from global              (no change)
        """
        if not organization_id:
            # No org context — global defaults only.
            return (
                self.db.query(NotificationTemplate)
                .filter(
                    NotificationTemplate.event_type == event_type,
                    NotificationTemplate.organization_id.is_(None),
                    NotificationTemplate.is_active.is_(True),
                )
                .all()
            )

        # Fetch org-specific AND global rows in one query.
        # ORDER: within each (channel, name) slot, org row sorts before global row
        # because organization_id DESC NULLS LAST puts non-NULL values first.
        all_rows = (
            self.db.query(NotificationTemplate)
            .filter(
                NotificationTemplate.event_type == event_type,
                NotificationTemplate.is_active.is_(True),
                or_(
                    NotificationTemplate.organization_id == organization_id,
                    NotificationTemplate.organization_id.is_(None),
                ),
            )
            .order_by(
                NotificationTemplate.channel,
                NotificationTemplate.name,
                NotificationTemplate.organization_id.desc().nulls_last(),
            )
            .all()
        )

        # Take the first row per (channel, name) slot — org-specific wins over global.
        # If the winning (org) row is a disabled-marker (org_channel_disabled=True),
        # mark the slot as seen (so the global row is skipped) but do NOT add it to
        # results — the dispatcher must never fire a disabled channel.
        seen: set = set()
        result: List[NotificationTemplate] = []
        for row in all_rows:
            slot = (row.channel, row.name)
            if slot not in seen:
                seen.add(slot)
                if getattr(row, 'org_channel_disabled', False):
                    # Org explicitly disabled this channel — block global fallback
                    # but don't dispatch anything for this slot.
                    continue
                result.append(row)

        return result

    def _dispatch_to_user(
        self,
        batch_log: "NotificationLog",
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
        extra_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Create a NotificationLogRecipient row under batch_log for one user.

        Channel behaviour
        -----------------
        inapp  — UserNotification written immediately; recipient marked 'sent'.
        email  — body wrapped in HTML; recipient stays 'pending' for scheduler.
        sms    — plain body stored; recipient stays 'pending' for scheduler.
        """
        now = datetime.now(timezone.utc)
        dispatcher = ChannelDispatcherRegistry.get(tmpl.channel)

        # ── Channel-specific body transformation (e.g. HTML wrapper for email)
        final_body = body
        if dispatcher:
            final_body = dispatcher.prepare_body(body, subject=subject, org_name=org_name)

        # ── Determine initial delivery_status ────────────────────────────────
        if tmpl.channel == "inapp":
            initial_status = "sent"
        elif tmpl.channel == "email" and not user.email:
            initial_status = "skipped"
        elif tmpl.channel == "sms" and not getattr(user, "phone_number", None):
            initial_status = "skipped"
        else:
            initial_status = "pending"

        rcpt = NotificationLogRecipient(
            log_id=batch_log.id,
            user_id=user.id,
            email=user.email  if tmpl.channel == "email" else None,
            phone=getattr(user, "phone_number", None) if tmpl.channel == "sms" else None,
            rendered_subject=subject,
            rendered_body=final_body,
            delivery_status=initial_status,
            sent_at=now if initial_status == "sent" else None,
            error_message=(
                "User has no email address" if (tmpl.channel == "email" and not user.email)
                else "User has no phone number" if (tmpl.channel == "sms" and not getattr(user, "phone_number", None))
                else None
            ),
        )
        # ── Use a savepoint so that if notification_log_recipient table is
        # missing (migration 019 not applied), only this row is rolled back;
        # the outer transaction (UserNotification / NotificationLog) stays live.
        try:
            with self.db.begin_nested():
                self.db.add(rcpt)
        except Exception as _rcpt_exc:
            logger.warning(
                f"[Notif] NotificationLogRecipient insert skipped for user={user.id} "
                f"channel={tmpl.channel!r} — run migration 019 to enable recipient tracking. "
                f"Error: {_rcpt_exc}"
            )

        if tmpl.channel == "inapp":
            # Inapp: create UserNotification immediately (no network needed)
            _ctx  = resolved_ctx or {}
            _ueic = _ctx.get("equipment.ueic") or _ctx.get("equipment") or None
            # For report-ready events pass structured data so Flutter can show a download button
            _extra = None
            if source_type == "report_definition":
                _extra = {k: v for k, v in _ctx.items()
                          if k in ("download_url", "format", "report_name", "report_period")}
            if extra_data:
                _extra = {**(_extra or {}), **extra_data}
            _create_inapp(
                db=self.db,
                user_id=user.id,
                organization_id=organization_id,
                event_type=event_type,
                title=subject or event_type.replace("_", " ").title(),
                body=body,          # in-app uses plain (un-wrapped) body
                severity=severity,
                source_id=source_id,
                source_type=source_type,
                ueic=_ueic,
                extra_data=_extra,
            )

    # ── Background job: process pending email/sms logs ────────────────────────

    def process_pending_notifications(self) -> dict:
        """
        Called by APScheduler every minute.
        Picks up NotificationLog batch rows with status='pending' for email/sms
        channels and dispatches them to all their NotificationLogRecipient rows.
        Returns a summary dict.
        """
        pending = (
            self.db.query(NotificationLog)
            .filter(
                NotificationLog.status == "pending",
                NotificationLog.channel.in_(["email", "sms"]),
            )
            .order_by(NotificationLog.cts.asc())
            .limit(50)
            .with_for_update(skip_locked=True)   # prevent concurrent workers sending the same row
            .all()
        )

        # Immediately mark claimed rows as "processing" and flush so other
        # workers see them as non-pending before we start slow SMTP calls.
        for _log in pending:
            _log.status = "processing"
        try:
            self.db.flush()
        except Exception:
            self.db.rollback()
            return {"sent": 0, "failed": 0, "skipped": 0, "total": 0}

        sent = failed = skipped = 0

        for log in pending:
            # ── Check if there are any pending recipients at all ─────────────
            pending_rcpts = [
                r for r in (log.recipients or [])
                if r.delivery_status == "pending"
            ]
            if not pending_rcpts:
                # Email channel: fall through to EmailDispatcher.send() —
                # it has CC/BCC fallback logic that can send even when there
                # are no NotificationLogRecipient rows (e.g. equipment_retired
                # template with no recipient_roles but a CC email set).
                if log.channel != "email":
                    log.status    = "skipped"
                    log.error_message = "No pending recipients"
                    log.sent_at   = datetime.now(timezone.utc)
                    skipped += 1
                    continue
                # Email with no recipient rows: skip per-recipient validations
                # (has_emails check, digest) and go straight to dispatch.

            # ── Digest check / per-recipient validation (has recipients) ─────
            elif log.channel == "email":
                has_emails = any(r.email for r in pending_rcpts)
                if not has_emails:
                    log.status    = "skipped"
                    log.error_message = "No email addresses on recipients"
                    log.sent_at   = datetime.now(timezone.utc)
                    skipped += 1
                    continue
                if _should_digest(self.db, log.event_type, log.organization_id):
                    _collapse_digest(self.db, log.event_type, log.organization_id)
                    skipped += 1
                    continue

            elif log.channel == "sms":
                has_phones = any(r.phone for r in pending_rcpts)
                if not has_phones:
                    log.status    = "skipped"
                    log.error_message = "No phone numbers on recipients"
                    log.sent_at   = datetime.now(timezone.utc)
                    skipped += 1
                    continue

            # ── Dispatch via registry ────────────────────────────────────────
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
            elif log.status == "processing":
                # Dispatcher didn't update status — check recipients and resolve.
                # All recipients sent/skipped → mark sent; otherwise failed.
                _rcpt_statuses = {r.delivery_status for r in (log.recipients or [])}
                if _rcpt_statuses and _rcpt_statuses <= {"sent", "skipped"}:
                    log.status  = "sent"
                    log.sent_at = datetime.now(timezone.utc)
                    sent += 1
                else:
                    log.status = "failed"
                    failed += 1
            else:
                # Catch-all: inspect recipients directly instead of trusting
                # whatever status the dispatcher left (could be stale).
                _rcpt_statuses = {r.delivery_status for r in (log.recipients or [])}
                if _rcpt_statuses and _rcpt_statuses <= {"sent", "skipped"}:
                    log.status  = "sent"
                    log.sent_at = datetime.now(timezone.utc)
                    sent += 1
                else:
                    failed += 1

        try:
            self.db.commit()
        except Exception as exc:
            logger.error(f"[Notif] process_pending commit failed: {exc}")
            self.db.rollback()

        return {"sent": sent, "failed": failed, "skipped": skipped, "total": len(pending)}


# ── Global default template seeds (DEPRECATED) ────────────────────────────────
# All template data has been moved to seed.py::_seed_notification_templates().
# This stub is kept for backward compatibility during rolling deploys.

DEFAULT_TEMPLATES: list = []

# ── Variable registry seed (DEPRECATED) ──────────────────────────────────────
# All variable data has been moved to seed.py::_seed_notification_variables().
# This stub is kept for backward compatibility during rolling deploys.

DEFAULT_VARIABLES: list = []


def seed_default_variables(db: Session) -> int:  # pragma: no cover
    """Deprecated — seeding is now handled by seed.py::_seed_notification_variables()."""
    import warnings
    warnings.warn(
        "seed_default_variables() is deprecated. "
        "Use seed.py::_seed_notification_variables() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return 0


def seed_default_templates(db: Session) -> int:  # pragma: no cover
    """Deprecated — seeding is now handled by seed.py::_seed_notification_templates()."""
    import warnings
    warnings.warn(
        "seed_default_templates() is deprecated. "
        "Use seed.py::_seed_notification_templates() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return 0
