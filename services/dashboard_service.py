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

from sqlalchemy.orm import Session

from models import (
    Equipment, EquipmentStatus,
    ProcurementRequest,
    Recommendation,
    RequestCategory,
    TestingRequest, TestingRequestStatus,
    TestResult,
    OrgRole, OrgUserRole,
)
from services.redis_cache import RedisCacheService

logger = logging.getLogger(__name__)

CACHE_TTL = 900  # 15 minutes

# ── Role → view mapping ────────────────────────────────────────────────────

EE_KEYWORDS      = ("ee tlss", "electrical engineer", "ee ", "tlss")
SEE_CEE_KEYWORDS = ("see", "cee", "superintending", "chief electrical")
ADMIN_KEYWORDS   = ("system admin", "org admin", "administrator")

OPEN_STATUSES = (
    TestingRequestStatus.submitted,
    TestingRequestStatus.assigned,
    TestingRequestStatus.accepted,
    TestingRequestStatus.in_progress,
    TestingRequestStatus.test_submitted,
    TestingRequestStatus.under_approval,
)
CLOSED_STATUSES = (
    TestingRequestStatus.approved,
    TestingRequestStatus.rejected,
)


def resolve_dashboard_view(role_names: List[str]) -> str:
    """Return 'ee_tlss' | 'see_cee' | 'admin' | 'field'."""
    combined = " ".join(r.lower() for r in role_names)
    if any(k in combined for k in ADMIN_KEYWORDS):
        return "admin"
    if any(k in combined for k in SEE_CEE_KEYWORDS):
        return "see_cee"
    if any(k in combined for k in EE_KEYWORDS):
        return "ee_tlss"
    return "field"


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


# ── Cache helpers ──────────────────────────────────────────────────────────

def _cache_key(org_id: Optional[UUID], widget: str) -> str:
    scope = str(org_id) if org_id else "global"
    return f"dashboard::{scope}::{widget}"


def _cached(key: str, compute_fn, ttl: int = CACHE_TTL) -> Any:
    cached = RedisCacheService.get(key)
    if cached is not None:
        return cached
    result = compute_fn()
    RedisCacheService.set(key, result, ttl=ttl)
    return result


def invalidate_dashboard_cache(org_id: Optional[UUID] = None) -> None:
    scope = str(org_id) if org_id else "global"
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

    def __init__(self, db: Session, org_id: Optional[UUID] = None):
        self.db = db
        self.org_id = org_id

    def _org_filter(self, q, model=TestingRequest):
        if self.org_id:
            return q.filter(model.organization_id == self.org_id)
        return q

    # ══════════════════════════════════════════════════════════════════════════
    # KPI Cards
    # ══════════════════════════════════════════════════════════════════════════

    def all_kpi_cards(self) -> List[Dict]:
        key = _cache_key(self.org_id, "kpi_cards")
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
        ]

    def _total_active_requests_kpi(self) -> Dict:
        """Show total active requests (all statuses except rejected/cancelled)."""
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.status.in_(OPEN_STATUSES)
            )
        )
        total = q.count()

        # Breakdown by status
        submitted = q.filter(TestingRequest.status == TestingRequestStatus.submitted).count()
        assigned = q.filter(TestingRequest.status == TestingRequestStatus.assigned).count()
        in_progress = q.filter(TestingRequest.status == TestingRequestStatus.in_progress).count()

        # Breakdown by category
        test_count = q.filter(TestingRequest.request_category == RequestCategory.test).count()
        maint_count = q.filter(TestingRequest.request_category == RequestCategory.maintenance).count()
        insp_count = q.filter(TestingRequest.request_category == RequestCategory.inspection).count()

        colour = "blue" if total > 0 else "grey"
        sub_text = f"{test_count} test · {maint_count} maint · {insp_count} inspection"

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
        since = _period_start(90)
        now   = _now()
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.inspection,
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
            "display": f"{pct}%",
            "sub": f"{open_count} observations open",
            "trend": None,
            "trend_dir": "neutral",
            "colour": colour,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # Panel Widgets
    # ══════════════════════════════════════════════════════════════════════════

    # ── Overdue tests breakdown ──────────────────────────────────────────────

    def overdue_tests_breakdown(self) -> Dict:
        key = _cache_key(self.org_id, "overdue_breakdown")
        return _cached(key, self._compute_overdue_breakdown)

    def _compute_overdue_breakdown(self) -> Dict:
        now = _now()
        rows = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.test,
                TestingRequest.due_date.isnot(None),
                TestingRequest.due_date < now,
                TestingRequest.status.in_(OPEN_STATUSES),
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
        key = _cache_key(self.org_id, f"active_alerts_{limit}")
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
        key = _cache_key(self.org_id, "flagged_equipment")
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
        key = _cache_key(self.org_id, "repair_progress")
        return _cached(key, self._compute_repair_progress)

    def _compute_repair_progress(self) -> List[Dict]:
        rows = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.repair_lifecycle,
                TestingRequest.status.in_(OPEN_STATUSES),
                TestingRequest.is_multi_session.is_(True),
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
        key = _cache_key(self.org_id, "maintenance_overdue")
        return _cached(key, self._compute_maintenance_overdue)

    def _compute_maintenance_overdue(self) -> Dict:
        now = _now()
        q = self._org_filter(
            self.db.query(TestingRequest).filter(
                TestingRequest.request_category == RequestCategory.maintenance,
                TestingRequest.due_date.isnot(None),
                TestingRequest.due_date < now,
                TestingRequest.status.in_(OPEN_STATUSES),
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

    # ── Procurement pipeline ─────────────────────────────────────────────────

    def procurement_pipeline(self) -> Dict:
        key = _cache_key(self.org_id, "procurement_pipeline")
        return _cached(key, self._compute_procurement_pipeline)

    def _compute_procurement_pipeline(self) -> Dict:
        q = self.db.query(ProcurementRequest)
        if self.org_id:
            q = q.filter(ProcurementRequest.organization_id == self.org_id)

        rows = q.order_by(ProcurementRequest.cts.desc()).limit(30).all()

        STATUS_LABEL = {
            "initiated":  "Pending technical approval",
            "approved":   "RFQ issued / quotes pending",
            "rfq_issued": "RFQ issued / quotes pending",
            "po_issued":  "PO/WO issued · awaiting delivery",
            "delivered":  "Under inspection",
        }
        STATUS_COLOUR = {
            "initiated":  "blue",
            "approved":   "teal",
            "rfq_issued": "teal",
            "po_issued":  "amber",
            "delivered":  "green",
        }
        active_rows = [r for r in rows if r.status not in ("closed", "rejected")]

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
        key = _cache_key(self.org_id, "open_remediation_list")
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
        role_names = get_user_role_names(self.db, user_id, self.org_id)
        view = resolve_dashboard_view(role_names)
        WIDGETS = {
            "ee_tlss": [
                "kpi_cards", "overdue_tests", "active_alerts",
                "flagged_equipment", "repair_progress",
                "maintenance_overdue", "procurement_pipeline",
                "open_remediation",
            ],
            "see_cee": [
                "kpi_cards", "overdue_tests", "active_alerts",
                "flagged_equipment", "repair_progress",
                "procurement_pipeline", "open_remediation",
            ],
            "admin": [
                "kpi_cards", "overdue_tests", "active_alerts",
                "flagged_equipment", "repair_progress",
                "maintenance_overdue", "procurement_pipeline",
                "open_remediation",
            ],
            "field": ["overdue_tests", "maintenance_overdue", "open_remediation"],
        }
        return {
            "view": view,
            "role_names": role_names,
            "permitted_widgets": WIDGETS.get(view, WIDGETS["field"]),
        }
