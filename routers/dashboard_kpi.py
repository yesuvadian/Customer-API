"""
Dashboard KPI Endpoints
========================
All widgets return cached data (Redis 15-min TTL).
Role is resolved from the caller's OrgUserRole rows.

Endpoints
---------
GET /dashboard/role-view          → { view, permitted_widgets, role_names }
GET /dashboard/kpi                → [ KpiCard, … ]          (6 cards)
GET /dashboard/overdue-tests      → { total, bands, items }
GET /dashboard/active-alerts      → [ Alert, … ]
GET /dashboard/flagged-equipment  → [ FlaggedEquipment, … ]
GET /dashboard/repair-progress    → [ RepairItem, … ]
GET /dashboard/maintenance-overdue → { total, items }
GET /dashboard/procurement        → { total, stages, items }
GET /dashboard/open-remediation   → { total, overdue, items }
GET /dashboard/full               → all widgets in one call (Flutter convenience)
POST /dashboard/invalidate-cache  → flush cache for org
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User, RequestCategory
from services.dashboard_service import OPEN_STATUSES, CLOSED_STATUSES
from services.dashboard_service import DashboardService, invalidate_dashboard_cache

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
    """
    Build a DashboardService scoped to:
      - org_id  : resolved from user's OrgUserRole if not explicitly supplied
      - dept_id : resolved from user's OrgUserRole.department_id or User.department_id
                  then expanded to the full subtree (dept + all descendants)

    Passing dept_id explicitly (e.g. from a query param) overrides the auto-resolved value,
    allowing admin overrides.
    """
    from models import OrgUserRole, OrgRole
    from utils.common_service import get_dept_subtree_ids, get_user_dept_scope

    # ── Resolve org ────────────────────────────────────────────────────────
    resolved_org = org_id
    row = (
        db.query(OrgUserRole)
        .filter(OrgUserRole.user_id == current_user.id,
                OrgUserRole.is_active.is_(True))
        .first()
    )
    if resolved_org is None and row:
        role = db.query(OrgRole).filter(OrgRole.id == row.org_role_id).first()
        if role:
            resolved_org = role.organization_id

    # ── Resolve dept via shared utility ───────────────────────────────────
    # Explicit ?dept_id= param wins (admin override).
    # Otherwise: get_user_dept_scope resolves OrgUserRole.department_id →
    # User.department_id → None (org-wide for org admins).
    resolved_dept = dept_id
    if resolved_dept is None:
        is_org_admin, scoped_dept = get_user_dept_scope(db, current_user.id, resolved_org)
        if not is_org_admin:
            resolved_dept = scoped_dept

    # ── Expand root dept to full subtree via recursive CTE ────────────────
    dept_ids = None
    if resolved_dept:
        dept_ids = get_dept_subtree_ids(db, resolved_dept)

    return DashboardService(
        db,
        org_id=resolved_org,
        dept_id=resolved_dept,
        dept_ids=dept_ids,
    )


# ── Role view ──────────────────────────────────────────────────────────────

@router.get("/role-view")
def get_role_view(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
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
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all 6 KPI cards for the current user's role."""
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

@router.get("/repair-timeliness")
def get_repair_timeliness(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Vendor delay summary across all active repair workflows.
    Returns aggregate counts (total, on_time, delayed, pending_attribution)
    plus total vendor / KPTCL delay days and a list of problem workflows.
    Visible to: admin, see_cee.
    """
    return _svc(db, current_user, org_id, dept_id).repair_timeliness()


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


# ── Full dashboard (all widgets in one call) ───────────────────────────────

@router.get("/full")
async def get_full_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Single endpoint that returns every widget.
    Flutter calls this once on load — role_view controls which sections to render.
    dept_id is auto-resolved from the user's OrgUserRole / User profile;
    pass ?dept_id= explicitly only for admin overrides.
    Optimized to run all widget methods in parallel for better performance.
    """
    from concurrent.futures import ThreadPoolExecutor
    import asyncio

    svc = _svc(db, current_user, org_id, dept_id)
    role_info = svc.role_view(current_user.id)
    permitted = set(role_info["permitted_widgets"])

    # Run all widget computations in parallel using a thread pool
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=12)
    
    tasks = []
    
    # Only add tasks for permitted widgets
    if "kpi_cards" in permitted:
        tasks.append(("kpi_cards", loop.run_in_executor(executor, svc.all_kpi_cards)))
    if "overdue_tests" in permitted:
        tasks.append(("overdue_tests", loop.run_in_executor(executor, svc.overdue_tests_breakdown)))
    if "active_alerts" in permitted:
        tasks.append(("active_alerts", loop.run_in_executor(executor, svc.active_alerts)))
    if "flagged_equipment" in permitted:
        tasks.append(("flagged_equipment", loop.run_in_executor(executor, svc.flagged_equipment)))
    if "repair_progress" in permitted:
        tasks.append(("repair_progress", loop.run_in_executor(executor, svc.repair_progress)))
    if "repair_timeliness" in permitted:
        tasks.append(("repair_timeliness", loop.run_in_executor(executor, svc.repair_timeliness)))
    if "maintenance_overdue" in permitted:
        tasks.append(("maintenance_overdue", loop.run_in_executor(executor, svc.maintenance_overdue)))
    if "procurement_pipeline" in permitted:
        tasks.append(("procurement", loop.run_in_executor(executor, svc.procurement_pipeline)))
    if "open_remediation" in permitted:
        tasks.append(("open_remediation", loop.run_in_executor(executor, svc.open_remediation_list)))
    if "failure_registry" in permitted:
        tasks.append(("failure_registry", loop.run_in_executor(executor, svc.failure_registry_list)))
    if "taqc_inspections" in permitted:
        tasks.append(("taqc_inspections", loop.run_in_executor(executor, svc.taqc_inspections_list)))
    # Chart widgets — always included regardless of role
    tasks.append(("projected_tickets", loop.run_in_executor(executor, svc.projected_tickets_by_month)))
    tasks.append(("tickets_trend", loop.run_in_executor(executor, svc.tickets_created_vs_completed)))
    
    # Await all tasks in parallel
    results = {}
    for key, task in tasks:
        try:
            results[key] = await task
        except Exception as e:
            # Log error but don't fail the entire request
            import logging
            logging.warning(f"Failed to compute {key} widget: {e}")
            results[key] = None
    
    # Build response with computed or default values
    return {
        "role_view":   role_info,
        "kpi_cards":   results.get("kpi_cards", []),
        "overdue_tests": results.get("overdue_tests", None),
        "active_alerts": results.get("active_alerts", []),
        "flagged_equipment": results.get("flagged_equipment", []),
        "repair_progress":    results.get("repair_progress", []),
        "repair_timeliness":  results.get("repair_timeliness", None),
        "maintenance_overdue": results.get("maintenance_overdue", None),
        "procurement":       results.get("procurement", None),
        "open_remediation":  results.get("open_remediation", None),
        "failure_registry":  results.get("failure_registry", None),
        "taqc_inspections":  results.get("taqc_inspections", None),
        "projected_tickets": results.get("projected_tickets", None),
        "tickets_trend":     results.get("tickets_trend", None),
    }


# ── Projected tickets by month ─────────────────────────────────────────────

@router.get("/projected-tickets")
def get_projected_tickets(
    year: Optional[int] = Query(None, description="4-digit year, defaults to current year"),
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Project how many operational schedule tickets will fire each month of the year.

    Uses every active operational schedule (equipment_id IS NOT NULL) and walks
    their frequency forward from next_run_date to count projected tickets per month.

    Response shape:
    ```json
    {
      "year": 2026,
      "total": 84,
      "months": [
        {"month": 1, "label": "Jan", "count": 12, "by_category": {"maintenance": 8, "test": 4}},
        ...
      ]
    }
    ```
    """
    return _svc(db, current_user, org_id, dept_id).projected_tickets_by_month(year=year)


# ── Created vs Completed month-wise ────────────────────────────────────────

@router.get("/tickets-trend")
def get_tickets_trend(
    year: Optional[int] = Query(None, description="4-digit year, defaults to current year"),
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Month-by-month bar chart data: tickets created vs tickets completed.

    Response shape:
    ```json
    {
      "year": 2026,
      "months": [
        {"month": 1, "label": "Jan", "created": 8, "completed": 5},
        ...
      ]
    }
    ```
    """
    return _svc(db, current_user, org_id, dept_id).tickets_created_vs_completed(year=year)


# ── Operations charts — combined endpoint (single round-trip) ─────────────

@router.get("/operations-charts")
def get_operations_charts(
    year: Optional[int] = Query(None, description="4-digit year, defaults to current year"),
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Returns both projected-tickets and tickets-trend in a single call so
    the Flutter client only needs one round-trip to render both charts.

    Response shape:
    ```json
    {
      "projected_tickets": { "year": 2026, "total": 84, "months": [...] },
      "tickets_trend":     { "year": 2026, "months": [...] }
    }
    ```
    """
    svc = _svc(db, current_user, org_id, dept_id)
    return {
        "projected_tickets": svc.projected_tickets_by_month(year=year),
        "tickets_trend":     svc.tickets_created_vs_completed(year=year),
    }


# ── Cache invalidation ─────────────────────────────────────────────────────

@router.post("/invalidate-cache")
def invalidate_cache(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Flush the dashboard cache. Call after bulk imports or data corrections."""
    svc = _svc(db, current_user, org_id)
    invalidate_dashboard_cache(svc.org_id)
    return {"status": "ok", "message": "Dashboard cache invalidated"}
