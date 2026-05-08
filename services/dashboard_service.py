"""
Dashboard & KPI Service
========================
Queries existing data (no new tables) and caches results in Redis
with a 15-minute TTL.

Cache key pattern:  dashboard::{org_id or 'global'}::{widget}
TTL: 900 seconds (15 min)

Role view mapping (checked against OrgRole.name, case-insensitive):
  ee_tlss  ← roles containing "EE", "EE TLSS", "Electrical Engineer"
  see_cee  ← roles containing "SEE", "CEE", "Superintending", "Chief"
  admin    ← "System Admin", "Org Admin"
  field    ← everything else (AEE, Tester, Field Officer…)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func, true
from sqlalchemy.orm import Session

from models import (
    Equipment, EquipmentStatus,
    Module,
    ProcurementRequest,
    Recommendation,
    RequestCategory,
    TestingRequest, TestingRequestStatus,
    TestResult,
    OrgRole, OrgUserRole,
    TestSession,
)
from services.redis_cache import RedisCacheService

logger = logging.getLogger(__name__)

CACHE_TTL = 900  # 15 minutes

# ── Dashboard view type resolution ────────────────────────────────────────
# View type is driven ENTIRELY by OrgRole.default_module.path.
# Flutter navigates to the same module path on login — dashboard service mirrors it.
# No keyword matching on role names anywhere.
#
#   Module path        → Dashboard view type → Widget set
#   admin_dashboard    → "admin"    → all widgets
#   dashboard          → "admin"    → all widgets (legacy generic admin module)
#   ee_tlss_dashboard  → "ee_tlss"  → EE TLSS widgets
#   aee_dashboard      → "ee_tlss"  → AEE = field supervisor, same widget set
#   see_dashboard      → "see_cee"  → SEE/CEE widgets
#   cee_dashboard      → "see_cee"  → CEE widgets
#   <anything else>    → "field"    → minimal field widgets
#
# To add a new dashboard type:
#   1. Add a Module record with a new path in seed.py (seed_modules)
#   2. Add an entry in MODULE_PATH_TO_VIEW below
#   3. Add a widget set in _WIDGET_SETS in dashboard_kpi.py
#   4. Add a typed GET route in dashboard_kpi.py

def resolve_user_org_id(db: Session, user_id: UUID) -> Optional[UUID]:
    """Return the organisation_id from the user's first active OrgUserRole.

    Called by the router _svc() helper so no DB access leaks into route handlers.
    """
    row = (
        db.query(OrgUserRole)
        .filter(OrgUserRole.user_id == user_id, OrgUserRole.is_active.is_(True))
        .first()
    )
    if row:
        role = db.query(OrgRole).filter(OrgRole.id == row.org_role_id).first()
        if role:
            return role.organization_id
    return None


MODULE_PATH_TO_VIEW: Dict[str, str] = {
    "admin_dashboard":   "admin",
    "dashboard":         "admin",
    "ee_tlss_dashboard": "ee_tlss",
    "aee_dashboard":     "ee_tlss",
    "see_dashboard":     "see_cee",
    "cee_dashboard":     "see_cee",
}

OPEN_STATUSES = (
    TestingRequestStatus.submitted,
    TestingRequestStatus.assigned,
    TestingRequestStatus.accepted,
    TestingRequestStatus.in_progress,
    TestingRequestStatus.test_submitted,
    TestingRequestStatus.under_approval,
    TestingRequestStatus.under_review,     # sent back to tester for revision
    TestingRequestStatus.finance_pending,  # awaiting finance approval
)
CLOSED_STATUSES = (
    TestingRequestStatus.approved,
    TestingRequestStatus.rejected,
    TestingRequestStatus.outcome_active,   # approved + downstream ticket created
    TestingRequestStatus.commissioned,     # equipment commissioned (TAQC terminal)
)


def resolve_dashboard_view(role_names: Optional[List[str]] = None, module_paths: Optional[List[str]] = None) -> str:
    """Return 'admin' | 'see_cee' | 'ee_tlss' | 'field' | 'generic'.

    View type is resolved EXCLUSIVELY from OrgRole.default_module.path via MODULE_PATH_TO_VIEW.
    If the user holds multiple roles, the widest view wins (admin > see_cee > ee_tlss > field).
    If no module path resolves to a known view → "field" (safe default).
    No role-name keyword matching.
    """
    _priority = {"admin": 5, "see_cee": 4, "ee_tlss": 3, "field": 2, "generic": 1}

    best = "field"
    if module_paths:
        for path in module_paths:
            view = MODULE_PATH_TO_VIEW.get(path or "", "")
            if view and _priority.get(view, 0) > _priority.get(best, 0):
                best = view
    return best


def get_user_role_names(db: Session, user_id: UUID, org_id: Optional[UUID]) -> List[str]:
    q = (
        db.query(OrgRole.name)
        .join(OrgUserRole, OrgUserRole.org_role_id == OrgRole.id)
        .filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.is_active.is_(True),
        )
    )
    if org_id:
        q = q.filter(OrgRole.organization_id == org_id)
    return [r[0] for r in q.all()]


def get_user_module_paths(db: Session, user_id: UUID, org_id: Optional[UUID]) -> List[str]:
    """Return the default_module.path for every active OrgRole the user holds.

    This mirrors what Flutter uses on login to navigate to the correct dashboard.
    """
    q = (
        db.query(Module.path)
        .join(OrgRole, OrgRole.default_module_id == Module.id)
        .join(OrgUserRole, OrgUserRole.org_role_id == OrgRole.id)
        .filter(
            OrgUserRole.user_id == user_id,
            OrgUserRole.is_active.is_(True),
            OrgRole.default_module_id.isnot(None),
            Module.is_active.is_(True),
        )
    )
    if org_id:
        q = q.filter(OrgRole.organization_id == org_id)
    return [r[0] for r in q.all() if r[0]]


# ── Cache helpers ──────────────────────────────────────────────────────────

def _cache_key(org_id: Optional[UUID], widget: str = "", dept_id: Optional[UUID] = None) -> str:
    scope = str(org_id) if org_id else "global"
    dept  = str(dept_id) if dept_id else "all"
    return f"dashboard::{scope}::dept_{dept}::{widget}"


def _cached(key: str, compute_fn, ttl: int = CACHE_TTL) -> Any:
    cached = RedisCacheService.get(key)
    if cached is not None:
        return cached
    result = compute_fn()
    RedisCacheService.set(key, result, ttl=ttl)
    return result


def invalidate_dashboard_cache(org_id: Optional[UUID] = None) -> None:
    scope = str(org_id) if org_id else "global"
    # Invalidate all cached keys for this org (including all dept sub-scopes)
    RedisCacheService.delete_pattern(f"dashboard::{scope}::*")
    RedisCacheService.delete_pattern("dashboard::global::*")


# ── Utility ────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _period_start(days: int = 90) -> datetime:
    return _now() - timedelta(days=days)


def _make_tz(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


# ══════════════════════════════════════════════════════════════════════════════
# Dashboard Service
# ══════════════════════════════════════════════════════════════════════════════

class DashboardService:

    def __init__(
        self,
        db: Session,
        org_id: Optional[UUID] = None,
        dept_id: Optional[UUID] = None,
    ):
        self.db = db
        self.org_id = org_id
        # dept_id is optional: when None → show all departments (org-wide view)
        # when provided → narrow results to that department only
        self.dept_id = dept_id

    def _org_filter(self, q, model=TestingRequest):
        """Apply org-level filter. When dept_id is also set, narrows to that dept."""
        if self.org_id:
            q = q.filter(model.organization_id == self.org_id)
        if self.dept_id and hasattr(model, "department_id"):
            q = q.filter(model.department_id == self.dept_id)
        return q

    # ══════════════════════════════════════════════════════════════════════════
    # KPI Cards
    # ══════════════════════════════════════════════════════════════════════════

    def all_kpi_cards(self) -> List[Dict]:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget="kpi_cards")
        return _cached(key, self._compute_all_kpis)

    def _compute_all_kpis(self) -> List[Dict]:
        return [
            self._total_active_requests_kpi(),
            self._compliance(RequestCategory.test, 90,
                             "Test compliance rate", "blue"),
            self._overdue_kpi(),
            self._alert_critical_kpi(),
            self._remediation_kpi(),
            self._compliance(RequestCategory.maintenance, 90,
                             "Maintenance compliance", "green"),
            self._taqc_kpi(),
            self._failure_registry_kpi(),
        ]

    def _total_active_requests_kpi(self) -> Dict:
        """Show total active requests (all statuses except rejected/cancelled)."""
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.status.in_(OPEN_STATUSES),
                TestingRequest.is_schedule_template.is_(False),  # exclude register templates
            )
        )
        total = q.count()

        # Breakdown by category
        test_count   = q.filter(TestingRequest.request_category == RequestCategory.test).count()
        maint_count  = q.filter(TestingRequest.request_category == RequestCategory.maintenance).count()
        insp_count   = q.filter(TestingRequest.request_category == RequestCategory.inspection).count()
        repair_count = q.filter(TestingRequest.request_category == RequestCategory.repair_lifecycle).count()
        fr_count     = q.filter(TestingRequest.request_category == RequestCategory.failure_registry).count()
        taqc_count   = q.filter(TestingRequest.request_category == RequestCategory.taqc_inspection).count()

        colour = "blue" if total > 0 else "grey"
        parts = []
        if test_count:   parts.append(f"{test_count} test")
        if maint_count:  parts.append(f"{maint_count} maint")
        if insp_count:   parts.append(f"{insp_count} insp")
        if repair_count: parts.append(f"{repair_count} repair")
        if fr_count:     parts.append(f"{fr_count} FR")
        if taqc_count:   parts.append(f"{taqc_count} TA&QC")
        sub_text = " · ".join(parts) if parts else "No active requests"

        return {
            "label": "Active Requests",
            "value": total,
            "display": str(total),
            "sub": sub_text,
            "trend": None,
            "trend_dir": "neutral",
            "colour": colour,
        }

    def _compliance(self, category: RequestCategory, period_days: int,
                    label: str, colour: str) -> Dict:
        since = _period_start(period_days)
        now   = _now()
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == category,
                TestingRequest.due_date.isnot(None),
                TestingRequest.due_date >= since,
                TestingRequest.due_date <= now,
                TestingRequest.is_schedule_template.is_(False),  # exclude register templates
            )
        )
        total = q.count()
        if total == 0:
            return {"label": label, "value": 0, "display": "0%",
                    "sub": "No records in period", "trend": None,
                    "trend_dir": "neutral", "colour": colour}
        completed = q.filter(
            TestingRequest.status.in_(CLOSED_STATUSES),
            TestingRequest.completed_at.isnot(None),
            TestingRequest.completed_at <= TestingRequest.due_date,
        ).count()
        pct = round(completed / total * 100, 1)
        colour_actual = "green" if pct >= 80 else ("amber" if pct >= 60 else "red")
        return {
            "label": label,
            "value": pct,
            "display": f"{pct}%",
            "sub": f"{completed} of {total} on time (last {period_days}d)",
            "trend": None,
            "trend_dir": "neutral",
            "colour": colour_actual,
        }

    def _overdue_kpi(self) -> Dict:
        now = _now()
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.test,
                TestingRequest.due_date.isnot(None),
                TestingRequest.due_date < now,
                TestingRequest.status.in_(OPEN_STATUSES),
                TestingRequest.is_schedule_template.is_(False),  # exclude register templates
            )
        )
        total = q.count()
        dept_count = q.with_entities(
            TestingRequest.department_id).distinct().count()
        return {
            "label": "Overdue tests",
            "value": total,
            "display": str(total),
            "sub": f"Across {dept_count} substations",
            "trend": None,
            "trend_dir": "up" if total > 0 else "neutral",
            "colour": "red" if total > 5 else ("amber" if total > 0 else "green"),
        }

    def _alert_critical_kpi(self) -> Dict:
        q = self.db.query(TestResult).filter(
            TestResult.evaluation_result.isnot(None),
            TestResult.evaluation_result["overall"].astext.in_(["CRITICAL", "ALERT"]),
        )
        if self.org_id:
            q = q.filter(TestResult.organization_id == self.org_id)
        rows = q.all()
        critical = sum(1 for r in rows
                       if (r.evaluation_result or {}).get("overall") == "CRITICAL")
        alert    = len(rows) - critical
        total    = len(rows)
        return {
            "label": "ALERT / CRITICAL flags",
            "value": total,
            "display": str(total),
            "sub": f"{alert} ALERT · {critical} CRITICAL",
            "trend": None,
            "trend_dir": "up" if critical > 0 else "neutral",
            "colour": "red" if critical > 0 else ("amber" if total > 0 else "green"),
        }

    def _remediation_kpi(self) -> Dict:
        now = _now()
        q = self.db.query(Recommendation).filter(
            Recommendation.approval_status == "pending"
        )
        if self.org_id:
            q = q.filter(Recommendation.organization_id == self.org_id)
        total   = q.count()
        cutoff  = now - timedelta(days=14)
        overdue = q.filter(Recommendation.cts < cutoff).count()
        oldest  = q.order_by(Recommendation.cts.asc()).first()
        oldest_days = (now - _make_tz(oldest.cts)).days if oldest else 0
        return {
            "label": "Open remediation records",
            "value": total,
            "display": str(total),
            "sub": f"{overdue} overdue · oldest {oldest_days} days",
            "trend": None,
            "trend_dir": "up" if overdue > 0 else "neutral",
            "colour": "teal",
        }

    def _taqc_kpi(self) -> Dict:
        """TA&QC Inspection KPI — uses request_category=taqc_inspection (direct submissions)."""
        since = _period_start(90)
        now   = _now()
        # TAQC inspections are stored as TestingRequests with request_category=taqc_inspection
        # and is_direct_submission=True (no tester assignment step)
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.taqc_inspection,
                TestingRequest.is_schedule_template.is_(False),
            )
        )
        open_count = q.filter(TestingRequest.status.in_(OPEN_STATUSES)).count()
        total_due  = q.filter(
            TestingRequest.due_date.isnot(None),
            TestingRequest.due_date >= since,
            TestingRequest.due_date <= now,
        ).count()
        done = q.filter(
            TestingRequest.due_date.isnot(None),
            TestingRequest.due_date >= since,
            TestingRequest.due_date <= now,
            TestingRequest.status.in_(CLOSED_STATUSES),
        ).count()
        pct = round(done / total_due * 100, 1) if total_due else 0
        colour = "green" if pct >= 80 else ("purple" if pct >= 60 else "amber")
        return {
            "label": "TA&QC compliance",
            "value": pct,
            "display": f"{pct}%" if total_due else "N/A",
            "sub": f"{open_count} open · {done}/{total_due} done (90d)",
            "trend": None,
            "trend_dir": "neutral",
            "colour": colour,
        }

    def _failure_registry_kpi(self) -> Dict:
        """Failure Registry KPI — count of open FR entries and high-priority items."""
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.failure_registry,
                TestingRequest.is_schedule_template.is_(False),
            )
        )
        total_open = q.filter(TestingRequest.status.in_(OPEN_STATUSES)).count()
        # High priority failures (priority = 'high' or 'critical')
        high_priority = q.filter(
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.priority.in_(["high", "critical"]),
        ).count()
        # Resolved in last 30 days
        resolved_since = _now() - timedelta(days=30)
        resolved = q.filter(
            TestingRequest.status.in_(CLOSED_STATUSES),
            TestingRequest.completed_at.isnot(None),
            TestingRequest.completed_at >= resolved_since,
        ).count()
        colour = "red" if high_priority > 0 else ("amber" if total_open > 0 else "green")
        return {
            "label": "Failure Registry",
            "value": total_open,
            "display": str(total_open),
            "sub": f"{high_priority} high-priority · {resolved} resolved (30d)",
            "trend": None,
            "trend_dir": "up" if high_priority > 0 else "neutral",
            "colour": colour,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # Panel Widgets
    # ══════════════════════════════════════════════════════════════════════════

    # ── Overdue tests breakdown ──────────────────────────────────────────────

    def overdue_tests_breakdown(self) -> Dict:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget="overdue_breakdown")
        return _cached(key, self._compute_overdue_breakdown)

    def _compute_overdue_breakdown(self) -> Dict:
        now = _now()
        rows = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.test,
                TestingRequest.due_date.isnot(None),
                TestingRequest.due_date < now,
                TestingRequest.status.in_(OPEN_STATUSES),
                TestingRequest.is_schedule_template.is_(False),  # exclude register templates
            )
        ).order_by(TestingRequest.due_date.asc()).all()

        band_0_7 = band_8_30 = band_30_plus = 0
        items = []
        for r in rows:
            due = _make_tz(r.due_date)
            days_over = (now - due).days
            if days_over <= 7:
                band_0_7 += 1
                severity = "amber"
            elif days_over <= 30:
                band_8_30 += 1
                severity = "red"
            else:
                band_30_plus += 1
                severity = "dark_red"

            ueic = (r.equipment.ueic if r.equipment
                    else (r.equipment_type.name if r.equipment_type else ""))
            test_type = r.test_type.name if r.test_type else ""
            substation = r.zone or r.ee_subdivision or r.aee_section or ""
            items.append({
                "id": str(r.id),
                "request_number": r.request_number,
                "substation": substation,
                "equipment": ueic,
                "test_type": test_type,
                "days_overdue": days_over,
                "severity": severity,
                "due_date": due.isoformat(),
            })

        total = len(rows)
        return {
            "total": total,
            "bands": [
                {"label": "0 – 7 days",              "count": band_0_7,
                 "pct": round(band_0_7 / total * 100) if total else 0,   "colour": "amber"},
                {"label": "8 – 30 days",             "count": band_8_30,
                 "pct": round(band_8_30 / total * 100) if total else 0,  "colour": "red"},
                {"label": "> 30 days — escalated",   "count": band_30_plus,
                 "pct": round(band_30_plus / total * 100) if total else 0, "colour": "dark_red"},
            ],
            "items": items[:10],
        }

    # ── Active alerts feed ───────────────────────────────────────────────────

    def active_alerts(self, limit: int = 10) -> List[Dict]:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget=f"active_alerts_{limit}")
        return _cached(key, lambda: self._compute_active_alerts(limit))

    def _compute_active_alerts(self, limit: int) -> List[Dict]:
        q = self.db.query(TestResult).filter(
            TestResult.evaluation_result.isnot(None),
            TestResult.evaluation_result["overall"].astext.in_(["CRITICAL", "ALERT"]),
        )
        if self.org_id:
            q = q.filter(TestResult.organization_id == self.org_id)

        rows = q.order_by(TestResult.cts.desc()).limit(limit).all()
        result = []
        for r in rows:
            ev      = r.evaluation_result or {}
            overall = ev.get("overall", "ALERT")
            req     = r.testing_request
            ueic    = ""
            substation = ""
            if req:
                ueic = (req.equipment.ueic if req.equipment
                        else (req.equipment_type.name if req.equipment_type else ""))
                substation = req.zone or req.ee_subdivision or ""

            # Build description from flagged fields
            field_parts = []
            for f in (ev.get("fields") or []):
                if f.get("status") in ("CRITICAL", "ALERT"):
                    lbl = f.get("label") or f.get("key", "")
                    val = f.get("value", "")
                    unit = f.get("unit", "")
                    field_parts.append(f"{lbl}: {val}{unit}")

            remedial = next(
                (f["remedial_action_text"]
                 for f in (ev.get("fields") or [])
                 if f.get("remedial_action_text")), ""
            )

            tested_at = _make_tz(r.tested_at or r.cts)
            result.append({
                "id": str(r.id),
                "overall": overall,
                "severity": "critical" if overall == "CRITICAL" else "alert",
                "title": f"{overall} — {r.test_name or r.template_key or 'Test'} · {ueic}",
                "description": " · ".join(field_parts[:3]),
                "remedial": remedial,
                "substation": substation,
                "equipment": ueic,
                "tested_at": tested_at.isoformat() if tested_at else None,
            })
        return result

    # ── Equipment flagged ALERT / CRITICAL ───────────────────────────────────

    def flagged_equipment(self) -> List[Dict]:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget="flagged_equipment")
        return _cached(key, self._compute_flagged_equipment)

    def _compute_flagged_equipment(self) -> List[Dict]:
        q = self.db.query(TestResult).filter(
            TestResult.evaluation_result.isnot(None),
            TestResult.evaluation_result["overall"].astext.in_(["CRITICAL", "ALERT"]),
        )
        if self.org_id:
            q = q.filter(TestResult.organization_id == self.org_id)

        rows = q.order_by(TestResult.cts.desc()).all()
        seen: set = set()
        result = []
        for r in rows:
            req = r.testing_request
            if not req:
                continue
            eq_key = str(req.equipment_id or req.equipment_type_id or r.id)
            if eq_key in seen:
                continue
            seen.add(eq_key)

            ev = r.evaluation_result or {}
            overall = ev.get("overall", "ALERT")
            ueic    = (req.equipment.ueic if req.equipment
                       else (req.equipment_type.name if req.equipment_type else ""))
            eq_type = (req.equipment.equipment_type.name
                       if req.equipment and req.equipment.equipment_type
                       else (req.equipment_type.name if req.equipment_type else ""))
            substation = req.zone or req.ee_subdivision or req.aee_section or ""

            action = ("Procurement open" if overall == "CRITICAL" and r.replacement_products
                      else "Remediation open" if overall == "CRITICAL"
                      else "Under observation")

            result.append({
                "ueic": ueic,
                "substation": substation,
                "equipment_type": eq_type,
                "overall": overall,
                "action": action,
                "test_result_id": str(r.id),
                "request_id": str(req.id),
            })
        return result[:15]

    # ── Repair lifecycle progress ────────────────────────────────────────────

    def repair_progress(self) -> List[Dict]:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget="repair_progress")
        return _cached(key, self._compute_repair_progress)

    def _compute_repair_progress(self) -> List[Dict]:
        rows = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.repair_lifecycle,
                TestingRequest.status.in_(OPEN_STATUSES),
                TestingRequest.is_multi_session.is_(True),
                TestingRequest.is_schedule_template.is_(False),  # exclude register templates
            )
        ).order_by(TestingRequest.cts.desc()).limit(10).all()

        result = []
        now = _now()
        for req in rows:
            sessions       = req.test_sessions or []
            total_planned  = req.total_sessions_planned or max(len(sessions), 1)
            completed_sess = sum(1 for s in sessions if s.status == "completed")
            pct            = round(completed_sess / total_planned * 100)

            # Current / latest active session
            active = next((s for s in sorted(sessions, key=lambda s: s.session_number, reverse=True)
                           if s.status in ("in_progress", "completed")), None)
            current_stage = active.session_number if active else 0
            current_name  = active.session_name  if active else "Not started"

            delay_text = ""
            if active and active.scheduled_date:
                sd = _make_tz(active.scheduled_date)
                if sd < now and active.status != "completed":
                    delay_text = f"Vendor delay: +{(now - sd).days} days attributable"
            if not delay_text and active:
                delay_text = "On schedule"

            ueic = (req.equipment.ueic if req.equipment
                    else (req.equipment_type.name if req.equipment_type else req.title))

            failure_date = _make_tz(req.requested_date or req.cts)
            result.append({
                "id": str(req.id),
                "ueic": ueic,
                "title": req.title,
                "request_number": req.request_number,
                "current_stage": current_stage,
                "current_stage_name": current_name,
                "total_stages": total_planned,
                "completed_stages": completed_sess,
                "pct": pct,
                "delay_text": delay_text,
                "failure_date": failure_date.isoformat() if failure_date else None,
            })
        return result

    # ── Maintenance overdue list ─────────────────────────────────────────────

    def maintenance_overdue(self) -> Dict:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget="maintenance_overdue")
        return _cached(key, self._compute_maintenance_overdue)

    def _compute_maintenance_overdue(self) -> Dict:
        now = _now()
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.maintenance,
                TestingRequest.due_date.isnot(None),
                TestingRequest.due_date < now,
                TestingRequest.status.in_(OPEN_STATUSES),
                TestingRequest.is_schedule_template.is_(False),  # exclude register templates
            )
        ).order_by(TestingRequest.due_date.asc())

        total = q.count()
        rows  = q.limit(10).all()
        items = []
        for r in rows:
            due = _make_tz(r.due_date)
            days_over = (now - due).days
            severity = "red" if days_over > 20 else ("amber" if days_over > 7 else "gray")
            ueic = (r.equipment.ueic if r.equipment
                    else (r.equipment_type.name if r.equipment_type else ""))
            substation = r.zone or r.ee_subdivision or r.aee_section or ""
            items.append({
                "id": str(r.id),
                "substation": substation,
                "equipment": ueic,
                "title": r.title,
                "days_overdue": days_over,
                "severity": severity,
            })
        return {"total": total, "items": items}

    # ── Failure Registry list ────────────────────────────────────────────────

    def failure_registry_list(self) -> Dict:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget="failure_registry")
        return _cached(key, self._compute_failure_registry)

    def _compute_failure_registry(self) -> Dict:
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.failure_registry,
                TestingRequest.status.in_(OPEN_STATUSES),
                TestingRequest.is_schedule_template.is_(False),
            )
        ).order_by(TestingRequest.cts.desc())

        total = q.count()
        rows  = q.limit(10).all()
        items = []
        now   = _now()
        for r in rows:
            created = _make_tz(r.cts)
            days_open = (now - created).days
            ueic = (r.equipment.ueic if r.equipment
                    else (r.equipment_type.name if r.equipment_type else ""))
            substation = r.zone or r.ee_subdivision or r.aee_section or ""
            items.append({
                "id": str(r.id),
                "request_number": r.request_number,
                "title": r.title,
                "substation": substation,
                "equipment": ueic,
                "priority": r.priority,
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "days_open": days_open,
                "severity": "red" if r.priority in ("high", "critical") else "amber",
            })
        return {"total": total, "items": items}

    # ── TA&QC Inspections list ───────────────────────────────────────────────

    def taqc_inspections_list(self) -> Dict:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget="taqc_inspections")
        return _cached(key, self._compute_taqc_inspections)

    def _compute_taqc_inspections(self) -> Dict:
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.taqc_inspection,
                TestingRequest.is_schedule_template.is_(False),
            )
        ).order_by(TestingRequest.cts.desc())

        total      = q.count()
        open_count = q.filter(TestingRequest.status.in_(OPEN_STATUSES)).count()
        closed_count = q.filter(TestingRequest.status.in_(CLOSED_STATUSES)).count()
        rows = q.limit(10).all()
        now  = _now()
        items = []
        for r in rows:
            ueic = (r.equipment.ueic if r.equipment
                    else (r.equipment_type.name if r.equipment_type else ""))
            substation = r.zone or r.ee_subdivision or r.aee_section or ""
            status_val = r.status.value if hasattr(r.status, "value") else str(r.status)
            items.append({
                "id": str(r.id),
                "request_number": r.request_number,
                "title": r.title,
                "substation": substation,
                "equipment": ueic,
                "status": status_val,
                "is_open": r.status in OPEN_STATUSES,
                "cts": _make_tz(r.cts).isoformat() if r.cts else None,
            })
        return {
            "total": total,
            "open": open_count,
            "closed": closed_count,
            "items": items,
        }

    # ── Procurement pipeline ─────────────────────────────────────────────────

    def procurement_pipeline(self) -> Dict:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget="procurement_pipeline")
        return _cached(key, self._compute_procurement_pipeline)

    def _compute_procurement_pipeline(self) -> Dict:
        q = self.db.query(ProcurementRequest)
        if self.org_id:
            q = q.filter(ProcurementRequest.organization_id == self.org_id)

        rows = q.order_by(ProcurementRequest.cts.desc()).limit(30).all()

        STATUS_LABEL = {
            "initiated":        "Pending technical approval",
            "approved":         "Technically approved",
            "finance_pending":  "Awaiting finance approval",
            "finance_approved": "Finance approved · RFQ pending",
            "finance_rejected": "Finance rejected",
            "rfq_issued":       "RFQ issued / quotes pending",
            "po_issued":        "PO/WO issued · awaiting delivery",
            "delivered":        "Under inspection",
            "closed":           "Closed",
            "rejected":         "Rejected",
        }
        STATUS_COLOUR = {
            "initiated":        "blue",
            "approved":         "teal",
            "finance_pending":  "amber",
            "finance_approved": "green",
            "finance_rejected": "red",
            "rfq_issued":       "teal",
            "po_issued":        "amber",
            "delivered":        "green",
            "closed":           "grey",
            "rejected":         "red",
        }
        active_rows = [r for r in rows if r.status not in ("closed", "rejected", "finance_rejected")]

        stage_counts: Dict[str, int] = {}
        for r in active_rows:
            stage_counts[r.status] = stage_counts.get(r.status, 0) + 1

        stages = []
        for status, count in stage_counts.items():
            total_active = len(active_rows) or 1
            stages.append({
                "status":  status,
                "label":   STATUS_LABEL.get(status, status.replace("_", " ").title()),
                "count":   count,
                "colour":  STATUS_COLOUR.get(status, "gray"),
                "pct":     round(count / total_active * 100),
            })

        items = []
        for r in active_rows[:5]:
            # Derive trigger from linked recommendation eval
            trigger = "Manual"
            if r.recommendation:
                recs_ev = getattr(r.recommendation.testing_request or object(), "recommendations", [])
                # Simple heuristic: use recommendation_type
                trigger = (r.recommendation.recommendation_type.value.upper()
                           if hasattr(r.recommendation.recommendation_type, "value")
                           else "Recommendation")
            items.append({
                "id": str(r.id),
                "procurement_number": r.procurement_number,
                "title": r.title,
                "status": r.status,
                "status_label": STATUS_LABEL.get(r.status, r.status),
                "trigger": trigger,
            })

        return {"total": len(active_rows), "stages": stages, "items": items}

    # ── Open remediation list ────────────────────────────────────────────────

    def open_remediation_list(self) -> Dict:
        key = _cache_key(self.org_id, dept_id=self.dept_id, widget="open_remediation_list")
        return _cached(key, self._compute_open_remediation)

    def _compute_open_remediation(self) -> Dict:
        now = _now()
        q = self.db.query(Recommendation).filter(
            Recommendation.approval_status == "pending"
        )
        if self.org_id:
            q = q.filter(Recommendation.organization_id == self.org_id)

        total   = q.count()
        rows    = q.order_by(Recommendation.cts.asc()).limit(15).all()
        overdue = 0
        items   = []
        for rec in rows:
            created = _make_tz(rec.cts)
            days_open = (now - created).days
            is_overdue = days_open > 14
            if is_overdue:
                overdue += 1
            req  = rec.testing_request
            ueic = ""
            if req:
                ueic = (req.equipment.ueic if req.equipment
                        else (req.equipment_type.name if req.equipment_type else ""))
            items.append({
                "id": str(rec.id),
                "request_number": req.request_number if req else "",
                "ueic": ueic,
                "action": (rec.summary or "")[:60],
                "recommendation_type": (rec.recommendation_type.value
                                        if hasattr(rec.recommendation_type, "value")
                                        else str(rec.recommendation_type)),
                "days_open": days_open,
                "is_overdue": is_overdue,
                "due_date": req.due_date.isoformat() if req and req.due_date else None,
                "status": "overdue" if is_overdue else "pending",
            })
        return {"total": total, "overdue": overdue, "items": items}

    # ── Role view metadata ───────────────────────────────────────────────────

    def role_view(self, user_id: UUID) -> Dict:
        role_names   = get_user_role_names(self.db, user_id, self.org_id)
        module_paths = get_user_module_paths(self.db, user_id, self.org_id)

        # View type resolved from OrgRole.default_module.path (same source as Flutter nav)
        view = resolve_dashboard_view(module_paths=module_paths)

        # Widget sets per view — widgets are the dashboard panel components
        WIDGETS: Dict[str, List[str]] = {
            "admin": [
                "kpi_cards", "overdue_tests", "active_alerts",
                "flagged_equipment", "repair_progress",
                "maintenance_overdue", "procurement_pipeline",
                "open_remediation", "failure_registry", "taqc_inspections",
            ],
            "see_cee": [
                "kpi_cards", "overdue_tests", "active_alerts",
                "flagged_equipment", "repair_progress",
                "procurement_pipeline", "open_remediation",
                "failure_registry", "taqc_inspections",
            ],
            "ee_tlss": [
                "kpi_cards", "overdue_tests", "active_alerts",
                "flagged_equipment", "repair_progress",
                "maintenance_overdue", "procurement_pipeline",
                "open_remediation", "failure_registry",
            ],
            "field": [
                "overdue_tests", "maintenance_overdue",
                "open_remediation", "failure_registry",
            ],
            "generic": [
                "overdue_tests", "open_remediation",
            ],
        }
        return {
            "view":              view,
            "role_names":        role_names,
            "module_paths":      module_paths,   # Flutter uses same paths for navigation
            "permitted_widgets": WIDGETS.get(view, WIDGETS["field"]),
        }

    # ── Role-specific full dashboards (legacy convenience endpoints) ─────────

    def aee_dashboard(self) -> Dict:
        """AEE / field-supervisor dashboard data — all DB access centralised here."""
        org_id = self.org_id
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
        dept_id = self.dept_id
        dept_cond_tr = (TestingRequest.department_id == dept_id) if dept_id else true()
        dept_cond_eq = (Equipment.department_id == dept_id) if dept_id else true()

        pending_approvals = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status.in_(["submitted", "pending_approval"]))
            .scalar() or 0
        )
        assigned_tests = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status.in_(["in_progress", "assigned"]))
            .scalar() or 0
        )
        equipment_count = (
            self.db.query(func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id,
                    dept_cond_eq,
                    Equipment.status == "active")
            .scalar() or 0
        )
        # Equipment that had a maintenance TR in the last 30 days
        recently_maintained_sq = (
            self.db.query(func.distinct(TestingRequest.equipment_id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.equipment_id.isnot(None),
                    TestingRequest.request_category == "maintenance",
                    TestingRequest.cts >= thirty_days_ago)
            .subquery()
        )
        maintenance_due = (
            self.db.query(func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id,
                    dept_cond_eq,
                    Equipment.status == "active",
                    ~Equipment.id.in_(self.db.query(recently_maintained_sq)))
            .scalar() or 0
        )
        fr_pending = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.request_category == "failure_registry",
                    TestingRequest.status == "under_approval")
            .scalar() or 0
        )
        alert_count = (
            self.db.query(func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id,
                    dept_cond_eq,
                    Equipment.status == "under_repair")
            .scalar() or 0
        )
        # Recent open assignments
        raw_assignments = (
            self.db.query(TestingRequest)
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status.in_(
                        ["submitted", "pending_approval", "in_progress", "assigned"]))
            .order_by(TestingRequest.due_date.asc().nullslast())
            .limit(10).all()
        )
        assignments_list = []
        for req in raw_assignments:
            due_str, color, status_text = "No deadline", "blue", ""
            if req.due_date:
                days_diff = (req.due_date.date() - datetime.now().date()).days
                if days_diff < 0:
                    due_str, color, status_text = f"{abs(days_diff)} days", "red", "Overdue"
                elif days_diff == 0:
                    due_str, color = "Today", "orange"
                    status_text = req.status.value.replace("_", " ").title()
                else:
                    due_str = f"{days_diff} days"
                    color = "blue" if req.status.value == "in_progress" else "orange"
                    status_text = req.status.value.replace("_", " ").title()
            else:
                status_text = req.status.value.replace("_", " ").title()

            sess = (
                self.db.query(
                    func.count(TestSession.id).label("cnt"),
                    func.max(TestSession.session_date).label("last_date"),
                )
                .filter(TestSession.testing_request_id == req.id)
                .first()
            )
            assignments_list.append({
                "id": str(req.id),
                "title": f"{req.test_type.name if req.test_type else 'Test'}"
                         f" - {req.department.name if req.department else 'Unknown'}",
                "status": status_text,
                "due": due_str,
                "color": color,
                "session_count": sess.cnt or 0,
                "last_session_date": (
                    sess.last_date.strftime("%d %b %Y") if sess and sess.last_date else None
                ),
            })
        return {
            "kpis": {
                "pending_approvals": pending_approvals,
                "assigned_tests": assigned_tests,
                "equipment_count": equipment_count,
                "maintenance_due": maintenance_due,
                "fr_pending": fr_pending,
            },
            "assignments": assignments_list,
            "equipment_status": {
                "operational": equipment_count,
                "under_test": assigned_tests,
                "alert": alert_count,
            },
        }

    def ee_tlss_dashboard(self) -> Dict:
        """EE TLSS condition-monitoring dashboard."""
        org_id = self.org_id
        ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
        dept_id = self.dept_id
        dept_cond_tr = (TestingRequest.department_id == dept_id) if dept_id else true()
        dept_cond_eq = (Equipment.department_id == dept_id) if dept_id else true()

        total_equipment = (
            self.db.query(func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id,
                    dept_cond_eq,
                    Equipment.status == "active")
            .scalar() or 0
        )
        tested_equipment = (
            self.db.query(func.count(func.distinct(TestingRequest.equipment_id)))
            .join(TestSession, TestSession.testing_request_id == TestingRequest.id)
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.equipment_id.isnot(None),
                    TestSession.session_date >= ninety_days_ago)
            .scalar() or 0
        )
        test_compliance = int(tested_equipment / total_equipment * 100) if total_equipment else 0

        overdue_tests = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status.in_(
                        ["submitted", "pending_approval", "assigned", "scheduled"]),
                    TestingRequest.due_date < datetime.now())
            .scalar() or 0
        )
        alert_critical = (
            self.db.query(func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id,
                    dept_cond_eq,
                    Equipment.status == "under_repair")
            .scalar() or 0
        )
        open_remediation = (
            self.db.query(func.count(func.distinct(Recommendation.testing_request_id)))
            .filter(Recommendation.organization_id == org_id,
                    Recommendation.approval_status == "pending",
                    Recommendation.testing_request_id.in_(
                        self.db.query(TestingRequest.id)
                        .filter(TestingRequest.organization_id == org_id,
                                dept_cond_tr,
                                TestingRequest.status != "completed")
                    ))
            .scalar() or 0
        )
        maintenance_compliant = (
            self.db.query(func.count(func.distinct(TestingRequest.equipment_id)))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.equipment_id.isnot(None),
                    TestingRequest.request_category == "maintenance",
                    TestingRequest.completed_at >= ninety_days_ago)
            .scalar() or 0
        )
        maintenance_compliance = (
            int(maintenance_compliant / total_equipment * 100) if total_equipment else 0
        )
        total_tests = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.cts >= ninety_days_ago)
            .scalar() or 0
        )
        approved_tests = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status == "approved",
                    TestingRequest.cts >= ninety_days_ago)
            .scalar() or 0
        )
        taqc_compliance = int(approved_tests / total_tests * 100) if total_tests else 0
        fr_pending = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.request_category == "failure_registry",
                    TestingRequest.status == "under_approval")
            .scalar() or 0
        )
        overdue_requests = (
            self.db.query(TestingRequest)
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status.in_(
                        ["submitted", "pending_approval", "assigned", "scheduled"]),
                    TestingRequest.due_date < datetime.now())
            .limit(10).all()
        )
        overdue_breakdown = [
            {
                "id": str(r.id),
                "title": f"{r.test_type.name if r.test_type else 'Test'}"
                         f" - {r.department.name if r.department else 'Unknown'}",
                "days_overdue": (
                    (datetime.now().date() - r.due_date.date()).days if r.due_date else 0
                ),
                "severity": (
                    "critical" if r.due_date and
                    (datetime.now().date() - r.due_date.date()).days > 30 else
                    "warning" if r.due_date and
                    (datetime.now().date() - r.due_date.date()).days > 14 else "normal"
                ),
            }
            for r in overdue_requests
        ]
        alert_equipment = (
            self.db.query(Equipment)
            .filter(Equipment.organization_id == org_id,
                    dept_cond_eq,
                    Equipment.status.in_(["under_repair", "active"]))
            .limit(10).all()
        )
        alerts_feed = [
            {
                "id": str(eq.id),
                "ueic": eq.ueic,
                "name": eq.manufacturer or eq.ueic,
                "status": eq.status.value if hasattr(eq.status, "value") else eq.status,
                "severity": "critical" if eq.status == "under_repair" else "alert",
            }
            for eq in alert_equipment
        ]
        return {
            "kpis": {
                "test_compliance": test_compliance,
                "overdue_tests": overdue_tests,
                "alert_critical": alert_critical,
                "open_remediation": open_remediation,
                "maintenance_compliance": maintenance_compliance,
                "taqc_compliance": taqc_compliance,
                "equipment_monitored": total_equipment,
                "ai_predictions": 0,
                "fr_pending": fr_pending,
            },
            "overdue_breakdown": overdue_breakdown,
            "alerts_feed": alerts_feed,
        }

    def see_dashboard(self) -> Dict:
        """SEE circle-level supervision dashboard."""
        org_id = self.org_id
        ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
        dept_id = self.dept_id
        dept_cond_tr = (TestingRequest.department_id == dept_id) if dept_id else true()
        dept_cond_eq = (Equipment.department_id == dept_id) if dept_id else true()

        total_equipment = (
            self.db.query(func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id,
                    dept_cond_eq,
                    Equipment.status == "active")
            .scalar() or 0
        )
        total_requests = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.cts >= ninety_days_ago)
            .scalar() or 0
        )
        completed_requests = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status == "completed",
                    TestingRequest.cts >= ninety_days_ago)
            .scalar() or 0
        )
        circle_compliance = int(completed_requests / total_requests * 100) if total_requests else 0
        pending_approvals = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status.in_(["submitted", "pending_approval"]))
            .scalar() or 0
        )
        critical_issues = (
            self.db.query(func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id,
                    dept_cond_eq,
                    Equipment.status == "under_repair")
            .scalar() or 0
        )
        fr_pending = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.request_category == "failure_registry",
                    TestingRequest.status == "under_approval")
            .scalar() or 0
        )
        pending_trs = (
            self.db.query(TestingRequest)
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status.in_(["submitted", "pending_approval"]))
            .order_by(TestingRequest.cts.desc()).limit(10).all()
        )
        reviews_list = [
            {
                "id": str(r.id),
                "title": f"{r.test_type.name if r.test_type else 'Test'}"
                         f" - {r.department.name if r.department else 'Unknown'}",
                "status": r.status.value.replace("_", " ").title(),
                "created": r.cts.strftime("%Y-%m-%d") if r.cts else "N/A",
            }
            for r in pending_trs
        ]
        return {
            "kpis": {
                "circle_compliance": circle_compliance,
                "pending_approvals": pending_approvals,
                "critical_issues": critical_issues,
                "equipment_units": total_equipment,
                "fr_pending": fr_pending,
            },
            "pending_reviews": reviews_list,
        }

    def cee_dashboard(self) -> Dict:
        """CEE zone-level executive dashboard."""
        org_id = self.org_id
        dept_id = self.dept_id
        dept_cond_tr = (TestingRequest.department_id == dept_id) if dept_id else true()
        dept_cond_eq = (Equipment.department_id == dept_id) if dept_id else true()

        zone_equipment = (
            self.db.query(func.count(Equipment.id))
            .filter(Equipment.organization_id == org_id,
                    dept_cond_eq,
                    Equipment.status == "active")
            .scalar() or 0
        )
        zone_reliability = round(
            (zone_equipment / zone_equipment * 100) if zone_equipment else 0.0, 1
        )
        major_decisions = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status.in_(["submitted", "pending_approval"]))
            .scalar() or 0
        )
        fr_pending = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.request_category == "failure_registry",
                    TestingRequest.status == "under_approval")
            .scalar() or 0
        )
        strategic_trs = (
            self.db.query(TestingRequest)
            .filter(TestingRequest.organization_id == org_id,
                    dept_cond_tr,
                    TestingRequest.status.in_(["submitted", "pending_approval"]))
            .order_by(TestingRequest.cts.desc()).limit(10).all()
        )
        decisions_list = [
            {
                "id": str(r.id),
                "title": f"{r.test_type.name if r.test_type else 'Test'}"
                         f" - {r.department.name if r.department else 'Unknown'}",
                "status": r.status.value.replace("_", " ").title(),
                "created": r.cts.strftime("%Y-%m-%d") if r.cts else "N/A",
            }
            for r in strategic_trs
        ]
        return {
            "kpis": {
                "zone_reliability": zone_reliability,
                "major_decisions": major_decisions,
                "zone_equipment": zone_equipment,
                "fr_pending": fr_pending,
            },
            "strategic_decisions": decisions_list,
        }
