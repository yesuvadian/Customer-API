"""
Dashboard KPI Endpoints
========================
All widgets return cached data (Redis 15-min TTL).
Role is resolved from the caller's OrgUserRole rows.

Endpoints
---------
GET /dashboard/role-view          → { view, permitted_widgets, role_names }
GET /dashboard/kpi                → [ KpiCard, … ]          (8 cards)
GET /dashboard/overdue-tests      → { total, bands, items }
GET /dashboard/active-alerts      → [ Alert, … ]
GET /dashboard/flagged-equipment  → [ FlaggedEquipment, … ]
GET /dashboard/repair-progress    → [ RepairItem, … ]
GET /dashboard/maintenance-overdue → { total, items }
GET /dashboard/procurement        → { total, stages, items }
GET /dashboard/open-remediation   → { total, overdue, items }
GET /dashboard/failure-registry   → { total, items }        (NEW)
GET /dashboard/taqc-inspections   → { total, open, closed, items } (NEW)
GET /dashboard/full               → all widgets in one call (Flutter convenience)
POST /dashboard/invalidate-cache  → flush cache for org

Query params (all GET endpoints support):
  org_id   — override org scope (multi-org admins)
  dept_id  — filter to a specific department
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from services.dashboard_service import (
    DashboardService,
    invalidate_dashboard_cache,
    resolve_user_org_id,
)

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _svc(
    db: Session,
    current_user: User,
    org_id: Optional[UUID] = None,
    dept_id: Optional[UUID] = None,
) -> DashboardService:
    """Build a DashboardService scoped to the caller's org.

    Org resolution is delegated to the service layer (resolve_user_org_id).
    dept_id = None  → top-level, no department filter
    dept_id = <id>  → drill-down to that department
    """
    resolved_org = org_id or resolve_user_org_id(db, current_user.id)
    return DashboardService(db, org_id=resolved_org, dept_id=dept_id)


# ── Role view ──────────────────────────────────────────────────────────────

@router.get("/role-view")
def get_role_view(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None, description="Filter to a specific department (omit for all)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns which dashboard view type this user sees and which widgets are permitted."""
    svc = _svc(db, current_user, org_id, dept_id)
    return svc.role_view(current_user.id)


# ── KPI cards ──────────────────────────────────────────────────────────────

@router.get("/kpi")
def get_kpi_cards(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None, description="Filter to a specific department (omit for all)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all KPI cards. dept_id=None shows org-wide totals; dept_id filters to one dept."""
    return _svc(db, current_user, org_id, dept_id).all_kpi_cards()


# ── Overdue tests ──────────────────────────────────────────────────────────

@router.get("/overdue-tests")
def get_overdue_tests(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id, dept_id).overdue_tests_breakdown()


# ── Active alerts feed ─────────────────────────────────────────────────────

@router.get("/active-alerts")
def get_active_alerts(
    limit: int = Query(10, ge=1, le=50),
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id, dept_id).active_alerts(limit=limit)


# ── Flagged equipment ──────────────────────────────────────────────────────

@router.get("/flagged-equipment")
def get_flagged_equipment(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id, dept_id).flagged_equipment()


# ── Repair progress ────────────────────────────────────────────────────────

@router.get("/repair-progress")
def get_repair_progress(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id, dept_id).repair_progress()


# ── Maintenance overdue ────────────────────────────────────────────────────

@router.get("/maintenance-overdue")
def get_maintenance_overdue(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id, dept_id).maintenance_overdue()


# ── Procurement pipeline ───────────────────────────────────────────────────

@router.get("/procurement")
def get_procurement(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id, dept_id).procurement_pipeline()


# ── Open remediation ───────────────────────────────────────────────────────

@router.get("/open-remediation")
def get_open_remediation(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id, dept_id).open_remediation_list()


# ── Failure Registry ───────────────────────────────────────────────────────

@router.get("/failure-registry")
def get_failure_registry(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Open failure registry entries. dept_id=None shows all depts."""
    return _svc(db, current_user, org_id, dept_id).failure_registry_list()


# ── TA&QC Inspections ──────────────────────────────────────────────────────

@router.get("/taqc-inspections")
def get_taqc_inspections(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """TA&QC inspection entries. dept_id=None shows all depts."""
    return _svc(db, current_user, org_id, dept_id).taqc_inspections_list()


# ── Widget sets per dashboard type ────────────────────────────────────────
# These drive what each specific dashboard endpoint returns.
# Flutter reads OrgRole.default_module.path and calls the matching route.
# No role-name keyword matching needed.

_WIDGET_SETS = {
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

# Module path → widget set name (same mapping as dashboard_service.py)
_MODULE_PATH_TO_WIDGET_SET = {
    "admin_dashboard":    "admin",
    "dashboard":          "admin",
    "ee_tlss_dashboard":  "ee_tlss",
    "aee_dashboard":      "ee_tlss",
    "see_dashboard":      "see_cee",
    "cee_dashboard":      "see_cee",
}


async def _build_dashboard(svc, widget_set_name: str, dept_id: Optional[UUID]):
    """Compute all widgets for the given widget set in parallel and return a dict."""
    from concurrent.futures import ThreadPoolExecutor
    import asyncio

    widgets = _WIDGET_SETS.get(widget_set_name, _WIDGET_SETS["field"])
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=10)

    _widget_fn = {
        "kpi_cards":          svc.all_kpi_cards,
        "overdue_tests":      svc.overdue_tests_breakdown,
        "active_alerts":      svc.active_alerts,
        "flagged_equipment":  svc.flagged_equipment,
        "repair_progress":    svc.repair_progress,
        "maintenance_overdue": svc.maintenance_overdue,
        "procurement_pipeline": svc.procurement_pipeline,
        "open_remediation":   svc.open_remediation_list,
        "failure_registry":   svc.failure_registry_list,
        "taqc_inspections":   svc.taqc_inspections_list,
    }

    tasks = [
        (key, loop.run_in_executor(executor, _widget_fn[key]))
        for key in widgets
        if key in _widget_fn
    ]

    results: dict = {}
    for key, task in tasks:
        try:
            results[key] = await task
        except Exception as exc:
            import logging
            logging.warning(f"Dashboard widget '{key}' failed: {exc}")
            results[key] = None

    return {
        "dashboard_type": widget_set_name,
        "dept_id":        str(dept_id) if dept_id else None,
        **{k: results.get(k) for k in widgets},
    }


# ── Full dashboard — delegates to specific type based on default_module ───

@router.get("/full")
async def get_full_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None, description="Drill down to a department (omit for all)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns all widgets for this user's dashboard type.
    Dashboard type is resolved from OrgRole.default_module.path (same as Flutter navigation).
    dept_id=None → org-wide (no dept filter); dept_id=<id> → single dept.

    Flutter should instead call the specific typed endpoint directly:
      /dashboard/ee-tlss/full, /dashboard/see-cee/full, /dashboard/admin/full, /dashboard/field/full
    This endpoint is a convenience wrapper for cases where the type is unknown.
    """
    from services.dashboard_service import get_user_module_paths, MODULE_PATH_TO_VIEW

    svc       = _svc(db, current_user, org_id, dept_id)
    paths     = get_user_module_paths(db, current_user.id, svc.org_id)
    # Resolve widget set from module path (no keyword matching)
    view_type = "field"
    for path in paths:
        candidate = _MODULE_PATH_TO_WIDGET_SET.get(path, "")
        if candidate and _WIDGET_SETS.get(candidate):
            # Pick the "widest" set (admin > see_cee > ee_tlss > field > generic)
            _priority = {"admin": 5, "see_cee": 4, "ee_tlss": 3, "field": 2, "generic": 1}
            if _priority.get(candidate, 0) > _priority.get(view_type, 0):
                view_type = candidate

    result = await _build_dashboard(svc, view_type, dept_id)
    result["module_paths"] = paths
    return result


# ── Typed full dashboards — Flutter calls these directly ──────────────────

@router.get("/admin/full")
async def get_admin_full_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Admin full dashboard — all widgets including TA&QC and failure registry."""
    svc = _svc(db, current_user, org_id, dept_id)
    return await _build_dashboard(svc, "admin", dept_id)


@router.get("/ee-tlss/full")
async def get_ee_tlss_full_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """EE TLSS / AEE full dashboard — condition monitoring widget set."""
    svc = _svc(db, current_user, org_id, dept_id)
    return await _build_dashboard(svc, "ee_tlss", dept_id)


@router.get("/see-cee/full")
async def get_see_cee_full_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SEE / CEE full dashboard — circle/zone-level supervision widget set."""
    svc = _svc(db, current_user, org_id, dept_id)
    return await _build_dashboard(svc, "see_cee", dept_id)


@router.get("/field/full")
async def get_field_full_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Field worker full dashboard — overdue tests, maintenance, remediation."""
    svc = _svc(db, current_user, org_id, dept_id)
    return await _build_dashboard(svc, "field", dept_id)


# ── Cache invalidation ─────────────────────────────────────────────────────

@router.post("/invalidate-cache")
def invalidate_cache(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Flush ALL dashboard cache for this org (all dept sub-scopes included).
    Call after bulk imports or data corrections."""
    svc = _svc(db, current_user, org_id)
    invalidate_dashboard_cache(svc.org_id)
    return {"status": "ok", "message": "Dashboard cache invalidated"}


# ── Role-specific dashboards ───────────────────────────────────────────────
# All DB logic lives in DashboardService; routes are thin orchestration only.

@router.get("/aee")
def get_aee_dashboard(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AEE Dashboard - Field-level maintenance supervisor view."""
    return _svc(db, current_user, org_id).aee_dashboard()


@router.get("/ee-tlss")
def get_ee_tlss_dashboard(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """EE TLSS Dashboard - Condition monitoring & operational oversight."""
    return _svc(db, current_user, org_id).ee_tlss_dashboard()


@router.get("/see")
def get_see_dashboard(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SEE Dashboard - Circle-level supervision."""
    return _svc(db, current_user, org_id).see_dashboard()


@router.get("/cee")
def get_cee_dashboard(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CEE Dashboard - Zone-level executive management."""
    return _svc(db, current_user, org_id).cee_dashboard()


