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


# ── Role-specific dashboards ───────────────────────────────────────────────

@router.get("/aee")
def get_aee_dashboard(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AEE Dashboard - Field-level maintenance supervisor view."""
    from models import TestingRequest, Equipment, OrgUserRole, OrgRole
    from sqlalchemy import func, and_
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id)

    # Get user's role
    user_role = (
        db.query(OrgUserRole)
        .join(OrgRole)
        .filter(
            OrgUserRole.user_id == current_user.id,
            OrgUserRole.is_active.is_(True),
            OrgRole.organization_id == svc.org_id
        )
        .first()
    )

    # KPIs
    pending_approvals = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval'])
    ).scalar() or 0

    assigned_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['in_progress', 'assigned'])
    ).scalar() or 0

    equipment_count = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active'
    ).scalar() or 0

    # Maintenance due (equipment without recent maintenance tests)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    equipment_with_maintenance = db.query(func.distinct(TestingRequest.equipment_id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.equipment_id.isnot(None),
        TestingRequest.request_category == 'maintenance',
        TestingRequest.cts >= thirty_days_ago
    ).subquery()

    maintenance_due = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active',
        ~Equipment.id.in_(db.query(equipment_with_maintenance))
    ).scalar() or 0

    # Assignments list - recent testing requests
    assignments = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            TestingRequest.status.in_(['submitted', 'pending_approval', 'in_progress', 'assigned'])
        )
        .order_by(TestingRequest.due_date.asc().nullslast())
        .limit(10)
        .all()
    )

    from models import TestSession
    assignments_list = []
    for req in assignments:
        # Calculate due days
        due_str = "No deadline"
        color = "blue"
        if req.due_date:
            days_diff = (req.due_date.date() - datetime.now().date()).days
            if days_diff < 0:
                due_str = f"{abs(days_diff)} days"
                color = "red"
                status_text = "Overdue"
            elif days_diff == 0:
                due_str = "Today"
                color = "orange"
                status_text = req.status.value.replace('_', ' ').title()
            else:
                due_str = f"{days_diff} days"
                color = "blue" if req.status.value == 'in_progress' else "orange"
                status_text = req.status.value.replace('_', ' ').title()
        else:
            status_text = req.status.value.replace('_', ' ').title()

        test_type_name = req.test_type.name if req.test_type else 'Test'
        dept_name = req.department.name if req.department else 'Unknown Location'

        # Session trace — how many times the tester has saved results
        sess_row = (
            db.query(
                func.count(TestSession.id).label('cnt'),
                func.max(TestSession.session_date).label('last_date'),
            )
            .filter(TestSession.testing_request_id == req.id)
            .first()
        )
        session_count = sess_row.cnt or 0
        last_session_date = (
            sess_row.last_date.strftime('%d %b %Y') if sess_row.last_date else None
        )

        assignments_list.append({
            'id': str(req.id),
            'title': f"{test_type_name} - {dept_name}",
            'status': status_text,
            'due': due_str,
            'color': color,
            'session_count': session_count,
            'last_session_date': last_session_date,
        })

    # Equipment status breakdown
    operational = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active'
    ).scalar() or 0

    under_test = assigned_tests  # Equipment currently being tested

    alert_count = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'under_repair'
    ).scalar() or 0

    return {
        'kpis': {
            'pending_approvals': pending_approvals,
            'assigned_tests': assigned_tests,
            'equipment_count': equipment_count,
            'maintenance_due': maintenance_due,
        },
        'assignments': assignments_list,
        'equipment_status': {
            'operational': operational,
            'under_test': under_test,
            'alert': alert_count,
        }
    }
@router.get("/asset")
def get_asset_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Asset Data Officer Dashboard — equipment registry and data quality view."""
    svc = _svc(db, current_user, org_id, dept_id)
    return {
        "kpi_cards":          svc.all_kpi_cards(),
        "overdue_tests":      svc.overdue_tests_breakdown(),
        "failure_registry":   svc.failure_registry_list(),
        "maintenance_overdue": svc.maintenance_overdue(),
        "open_remediation":   svc.open_remediation_list(),
    }

@router.get("/ee-tlss")
def get_ee_tlss_dashboard(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """EE TLSS Dashboard - Condition monitoring & operational oversight."""
    from models import TestingRequest, Equipment, TestSession
    from sqlalchemy import func, and_
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id)

    # Test Compliance Rate
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active'
    ).scalar() or 0

    # Equipment with recent tests (within 90 days)
    ninety_days_ago = datetime.now() - timedelta(days=90)
    tested_equipment = db.query(func.count(func.distinct(TestingRequest.equipment_id))).join(
        TestSession, TestSession.testing_request_id == TestingRequest.id
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.equipment_id.isnot(None),
        TestSession.session_date >= ninety_days_ago
    ).scalar() or 0

    test_compliance = int((tested_equipment / total_equipment * 100)) if total_equipment > 0 else 0

    # Overdue Tests
    overdue_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval', 'assigned', 'scheduled']),
        TestingRequest.due_date < datetime.now()
    ).scalar() or 0

    # ALERT/CRITICAL flags (equipment with failed tests or under repair)
    alert_critical = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'under_repair'
    ).scalar() or 0

    # Open Remediation (testing requests with recommendations)
    from models import Recommendation
    open_remediation = db.query(func.count(func.distinct(Recommendation.testing_request_id))).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                TestingRequest.status != 'completed'
            )
        )
    ).scalar() or 0

    # Maintenance Compliance (equipment with recent maintenance category tests)
    maintenance_compliant = db.query(func.count(func.distinct(TestingRequest.equipment_id))).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.equipment_id.isnot(None),
        TestingRequest.request_category == 'maintenance',
        TestingRequest.completed_at >= ninety_days_ago
    ).scalar() or 0

    maintenance_compliance = int((maintenance_compliant / total_equipment * 100)) if total_equipment > 0 else 0

    # TA&QC Compliance (test approvals)
    total_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0

    approved_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status == 'approved',
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0

    taqc_compliance = int((approved_tests / total_tests * 100)) if total_tests > 0 else 0

    # AI Predictions (placeholder - no AI model yet)
    ai_predictions = 0

    # Overdue tests breakdown by age
    overdue_breakdown = []
    overdue_requests = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval', 'assigned', 'scheduled']),
        TestingRequest.due_date < datetime.now()
    ).all()

    for req in overdue_requests[:10]:  # Limit to 10
        days_overdue = (datetime.now().date() - req.due_date.date()).days if req.due_date else 0
        test_type_name = req.test_type.name if req.test_type else 'Test'
        dept_name = req.department.name if req.department else 'Unknown Location'

        overdue_breakdown.append({
            'id': str(req.id),
            'title': f"{test_type_name} - {dept_name}",
            'days_overdue': days_overdue,
            'severity': 'critical' if days_overdue > 30 else 'warning' if days_overdue > 14 else 'normal'
        })

    # Active alerts feed (equipment under repair or with recent failed tests)
    alerts_feed = []
    alert_equipment = db.query(Equipment).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status.in_(['under_repair', 'active'])
    ).limit(10).all()

    for eq in alert_equipment:
        severity = 'critical' if eq.status == 'under_repair' else 'alert'
        alerts_feed.append({
            'id': str(eq.id),
            'ueic': eq.ueic,
            'name': eq.manufacturer or eq.ueic,
            'status': eq.status.value if hasattr(eq.status, 'value') else eq.status,
            'severity': severity
        })

    return {
        'kpis': {
            'test_compliance': test_compliance,
            'overdue_tests': overdue_tests,
            'alert_critical': alert_critical,
            'open_remediation': open_remediation,
            'maintenance_compliance': maintenance_compliance,
            'taqc_compliance': taqc_compliance,
            'equipment_monitored': total_equipment,
            'ai_predictions': ai_predictions,
        },
        'overdue_breakdown': overdue_breakdown,
        'alerts_feed': alerts_feed,
    }


@router.get("/see")
def get_see_dashboard(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SEE Dashboard - Circle-level supervision."""
    from models import TestingRequest, Equipment, OrgRole
    from sqlalchemy import func
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id)

    # Total equipment
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active'
    ).scalar() or 0

    # Circle Compliance (test completion rate)
    ninety_days_ago = datetime.now() - timedelta(days=90)
    total_requests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0

    completed_requests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status == 'completed',
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0

    circle_compliance = int((completed_requests / total_requests * 100)) if total_requests > 0 else 0

    # Pending Approvals
    pending_approvals = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval'])
    ).scalar() or 0

    # Critical Issues (equipment under repair)
    critical_issues = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'under_repair'
    ).scalar() or 0

    # Pending reviews list
    pending_reviews = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval'])
    ).order_by(TestingRequest.cts.desc()).limit(10).all()

    reviews_list = []
    for req in pending_reviews:
        test_type_name = req.test_type.name if req.test_type else 'Test'
        dept_name = req.department.name if req.department else 'Unknown Location'

        reviews_list.append({
            'id': str(req.id),
            'title': f"{test_type_name} - {dept_name}",
            'status': req.status.value.replace('_', ' ').title(),
            'created': req.cts.strftime('%Y-%m-%d') if req.cts else 'N/A'
        })

    return {
        'kpis': {
            'circle_compliance': circle_compliance,
            'pending_approvals': pending_approvals,
            'critical_issues': critical_issues,
            'equipment_units': total_equipment,
        },
        'pending_reviews': reviews_list,
    }


@router.get("/cee")
def get_cee_dashboard(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CEE Dashboard - Zone-level executive management."""
    from models import TestingRequest, Equipment
    from sqlalchemy import func
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id)

    # Zone Equipment
    zone_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active'
    ).scalar() or 0

    # Zone Reliability (percentage of equipment in active status)
    healthy_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active'
    ).scalar() or 0

    zone_reliability = round((healthy_equipment / zone_equipment * 100), 1) if zone_equipment > 0 else 0.0

    # Major Decisions (pending high-value approvals)
    major_decisions = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval'])
    ).scalar() or 0

    # Pending strategic decisions
    strategic_decisions = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval'])
    ).order_by(TestingRequest.cts.desc()).limit(10).all()

    decisions_list = []
    for req in strategic_decisions:
        test_type_name = req.test_type.name if req.test_type else 'Test'
        dept_name = req.department.name if req.department else 'Unknown Location'

        decisions_list.append({
            'id': str(req.id),
            'title': f"{test_type_name} - {dept_name}",
            'status': req.status.value.replace('_', ' ').title(),
            'created': req.cts.strftime('%Y-%m-%d') if req.cts else 'N/A'
        })

    return {
        'kpis': {
            'zone_reliability': zone_reliability,
            'major_decisions': major_decisions,
            'zone_equipment': zone_equipment,
        },
        'strategic_decisions': decisions_list,
    }
@router.get("/test-coordinator")
def get_test_coordinator_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Test Coordinator Dashboard — Condition monitoring & test evaluation oversight.
    
    Based on SEACMS-AI SRS v2.0:
    - Sec 5.1: Test Schedule Management
    - Sec 5.2: Test Result Entry and Evaluation  
    - Sec 5.2.2: Automated Result Evaluation (NORMAL/ALERT/CRITICAL)
    - Sec 5.2.3: Trend Analysis and Curve Overlaying
    - Sec 5.2.4: Remedial Action Compliance Workflow
    - Sec 5.1.3: Alert and Escalation for Due / Overdue Tests
    - Sec 8.3.1: EE TLSS / Test Coordinator Dashboard Views
    
    Visible to: EE TLSS, Test Coordinator, Reviewing Officer roles
    """
    from models import TestingRequest, Equipment, TestSession, TestResult, CategoryDetails, Recommendation
    from sqlalchemy import func, and_, extract
    from datetime import datetime, timedelta
    
    svc = _svc(db, current_user, org_id, dept_id)
    
    # Date boundaries
    now = datetime.now(timezone.utc)
    ninety_days_ago = now - timedelta(days=90)
    thirty_days_ago = now - timedelta(days=30)
    
    # Department filter for queries
    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True
    
    # =========================================================================
    # 1. KPI Cards (6 cards as per SRS Sec 8.3.2)
    # =========================================================================
    
    # Total active equipment
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active'
    ).scalar() or 0
    
    # Test Compliance Rate (%)
    tested_equipment = db.query(func.count(func.distinct(TestingRequest.equipment_id))).join(
        TestSession, TestSession.testing_request_id == TestingRequest.id
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.equipment_id.isnot(None),
        TestSession.session_date >= ninety_days_ago
    ).scalar() or 0
    test_compliance = int((tested_equipment / total_equipment * 100)) if total_equipment > 0 else 0
    
    # Overdue Tests
    overdue_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.due_date < now,
        TestingRequest.is_schedule_template.is_(False)
    ).scalar() or 0
    
    # ALERT/CRITICAL Equipment (from latest test results)
    critical_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'CRITICAL'
    ).scalar() or 0
    
    alert_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'ALERT'
    ).scalar() or 0
    
    alert_critical_total = critical_count + alert_count
    
    # Open Remedial Actions
    open_remediation = db.query(func.count(func.distinct(Recommendation.testing_request_id))).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                dept_cond,
                TestingRequest.status != 'completed'
            )
        )
    ).scalar() or 0
    
    # Remedial actions overdue (>14 days old)
    overdue_remediation = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.cts < (now - timedelta(days=14))
    ).scalar() or 0
    
    # Maintenance Compliance
    maintenance_compliant = db.query(func.count(func.distinct(TestingRequest.equipment_id))).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.equipment_id.isnot(None),
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.completed_at >= ninety_days_ago
    ).scalar() or 0
    maintenance_compliance = int((maintenance_compliant / total_equipment * 100)) if total_equipment > 0 else 0
    
    # TA&QC Compliance
    total_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0
    approved_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status == 'approved',
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0
    taqc_compliance = int((approved_tests / total_tests * 100)) if total_tests > 0 else 0
    
    # =========================================================================
    # 2. Test Compliance by Type (SRS Sec 5.1.1)
    # =========================================================================
    
    test_compliance_by_type = []
    test_types = db.query(CategoryDetails).filter(CategoryDetails.is_active.is_(True)).all()
    
    for tt in test_types:
        # Total equipment that should have this test
        total_for_type = db.query(func.count(func.distinct(TestingRequest.equipment_id))).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.test_type_id == tt.id,
            TestingRequest.equipment_id.isnot(None),
            TestingRequest.is_schedule_template.is_(False)
        ).scalar() or 0
        
        # Equipment that completed this test in last 90 days
        completed_for_type = db.query(func.count(func.distinct(TestingRequest.equipment_id))).join(
            TestSession, TestSession.testing_request_id == TestingRequest.id
        ).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.test_type_id == tt.id,
            TestingRequest.equipment_id.isnot(None),
            TestSession.session_date >= ninety_days_ago
        ).scalar() or 0
        
        percentage = int((completed_for_type / total_for_type * 100)) if total_for_type > 0 else 0
        
        # Color based on percentage
        if percentage >= 80:
            color = '#16A34A'  # green
        elif percentage >= 60:
            color = '#D97706'  # orange
        else:
            color = '#DC2626'  # red
            
        test_compliance_by_type.append({
            'test_type': tt.name,
            'percentage': percentage,
            'color': color,
            'total_equipment': total_for_type,
            'completed': completed_for_type
        })
    
    # =========================================================================
    # 3. Equipment Health Summary (flagged equipment)
    # =========================================================================
    
    # Get latest test result for each equipment
    latest_results = db.query(
        TestResult.testing_request_id,
        func.max(TestResult.cts).label('latest_date')
    ).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None)
    ).group_by(TestResult.testing_request_id).subquery()
    
    flagged_counts = db.query(
        TestResult.evaluation_result['overall'].astext.label('classification'),
        func.count(func.distinct(TestResult.testing_request_id)).label('count')
    ).join(
        latest_results,
        and_(
            TestResult.testing_request_id == latest_results.c.testing_request_id,
            TestResult.cts == latest_results.c.latest_date
        )
    ).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None)
    ).group_by('classification').all()
    
    normal_count = total_equipment
    alert_count_total = 0
    critical_count_total = 0
    
    for row in flagged_counts:
        if row.classification == 'ALERT':
            alert_count_total = row.count
            normal_count -= row.count
        elif row.classification == 'CRITICAL':
            critical_count_total = row.count
            normal_count -= row.count
    
    equipment_health = {
        'normal': normal_count,
        'alert': alert_count_total,
        'critical': critical_count_total,
        'total': total_equipment
    }
    
    # =========================================================================
    # 4. Overdue Tests Breakdown with Escalation (SRS Sec 5.1.3)
    # =========================================================================
    
    overdue_requests = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.due_date < now,
        TestingRequest.is_schedule_template.is_(False)
    ).order_by(TestingRequest.due_date.asc()).limit(20).all()
    
    overdue_breakdown = []
    escalation_levels = {'YELLOW': 0, 'ORANGE': 0, 'RED': 0}
    
    for req in overdue_requests:
        days_overdue = (now.date() - req.due_date.date()).days if req.due_date else 0
        
        if days_overdue >= 30:
            escalation = 'T+30 RED'
            escalation_levels['RED'] += 1
            severity = 'critical'
        elif days_overdue >= 7:
            escalation = 'T+7 ORANGE'
            escalation_levels['ORANGE'] += 1
            severity = 'warning'
        else:
            escalation = 'T+0 YELLOW'
            escalation_levels['YELLOW'] += 1
            severity = 'normal'
        
        test_type_name = req.test_type.name if req.test_type else 'Test'
        ueic = req.equipment.ueic if req.equipment else ''
        equipment_name = req.equipment.manufacturer or ueic if req.equipment else ''
        dept_name = req.department.name if req.department else ''

        # Get last alert sent date
        # Note: last_alert_date field not implemented yet in TestingRequest model
        last_alert = None
        # if hasattr(req, 'last_alert_date') and req.last_alert_date:
        #     last_alert = req.last_alert_date.strftime('%d-%b-%Y')

        overdue_breakdown.append({
            'id': str(req.id),
            'ueic': ueic,
            'equipment': equipment_name,
            'test_type': test_type_name,
            'days_overdue': days_overdue,
            'escalation_level': escalation,
            'severity': severity,
            'last_alert_sent': last_alert,
            'original_due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else None,
            'substation': dept_name
        })
    
    # =========================================================================
    # 5. Upcoming Test Schedule (Next 30 days - SRS Sec 5.1.2)
    # =========================================================================
    
    upcoming_tests = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.status.in_(['scheduled', 'pending_approval', 'assigned']),
        TestingRequest.due_date.between(now, now + timedelta(days=30)),
        TestingRequest.is_schedule_template.is_(False)
    ).order_by(TestingRequest.due_date.asc()).limit(50).all()
    
    # Group by week
    weeks_data = []
    for week_offset in range(4):
        week_start = now.date() + timedelta(days=week_offset * 7)
        week_end = week_start + timedelta(days=6)
        
        week_tests = [t for t in upcoming_tests if t.due_date and week_start <= t.due_date.date() <= week_end]
        
        # Count by test type
        type_counts = {}
        for test in week_tests:
            test_type = test.test_type.name if test.test_type else 'Other'
            type_counts[test_type] = type_counts.get(test_type, 0) + 1
        
        weeks_data.append({
            'week': week_offset + 1,
            'label': f'Week {week_offset + 1}',
            'start_date': week_start.strftime('%d-%b'),
            'end_date': week_end.strftime('%d-%b'),
            'total': len(week_tests),
            'by_type': type_counts
        })
    
    # =========================================================================
    # 6. Recent Test Results with Classification (SRS Sec 5.2.2)
    # =========================================================================
    
    recent_results = db.query(
        TestSession, TestingRequest, Equipment, CategoryDetails, TestResult
    ).join(
        TestingRequest, TestSession.testing_request_id == TestingRequest.id
    ).join(
        Equipment, TestingRequest.equipment_id == Equipment.id
    ).join(
        CategoryDetails, TestingRequest.test_type_id == CategoryDetails.id
    ).outerjoin(
        TestResult, TestResult.test_session_id == TestSession.id
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestSession.session_date >= thirty_days_ago
    ).order_by(TestSession.session_date.desc()).limit(15).all()
    
    recent_results_list = []
    for session, req, eq, test_type, result in recent_results:
        classification = result.evaluation_result.get('overall') if result and result.evaluation_result else 'PENDING'
        
        # Determine color based on classification
        if classification == 'CRITICAL':
            result_color = '#DC2626'
            result_bg = '#FEF2F2'
        elif classification == 'ALERT':
            result_color = '#D97706'
            result_bg = '#FFFBEB'
        elif classification == 'NORMAL':
            result_color = '#16A34A'
            result_bg = '#F0FDF4'
        else:
            result_color = '#64748B'
            result_bg = '#F8FAFC'
        
        # Format result value
        result_value = None
        if result and result.result_value:
            result_value = result.result_value
        
        recent_results_list.append({
            'id': str(session.id),
            'ueic': eq.ueic if eq else '',
            'equipment': eq.manufacturer or eq.ueic if eq else '',
            'test_type': test_type.name if test_type else 'Test',
            'result': result_value,
            'classification': classification,
            'result_color': result_color,
            'result_bg': result_bg,
            'tested_on': session.session_date.strftime('%d-%b-%Y') if session.session_date else None,
            'tested_by': session.conductor.name if session.conductor else None,
            'next_due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else None
        })
    
    # =========================================================================
    # 7. Open Remedial Actions (SRS Sec 5.2.4)
    # =========================================================================
    
    open_remediations = db.query(Recommendation).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending'
    ).order_by(Recommendation.cts.asc()).limit(10).all()
    
    remedial_actions_list = []
    for rec in open_remediations:
        req = rec.testing_request
        ueic = req.equipment.ueic if req and req.equipment else ''
        
        days_open = (now - rec.cts).days if rec.cts else 0
        is_overdue = days_open > 14
        
        remedial_actions_list.append({
            'id': str(rec.id),
            'ueic': ueic,
            'description': rec.summary or rec.detailed_notes or '',
            'assigned_to': 'Unassigned',
            'due_date': req.due_date.strftime('%Y-%m-%d') if req and req.due_date else None,
            'is_critical': False,
            'is_overdue': is_overdue,
            'days_open': days_open,
            'status': 'overdue' if is_overdue else 'pending'
        })
    
    # =========================================================================
    # 8. Active Alerts Feed (SRS Sec 5.2.2)
    # =========================================================================
    
    # Get latest CRITICAL/ALERT results
    active_alerts = db.query(
        TestResult, TestingRequest, Equipment
    ).join(
        TestingRequest, TestResult.testing_request_id == TestingRequest.id
    ).join(
        Equipment, TestingRequest.equipment_id == Equipment.id
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext.in_(['CRITICAL', 'ALERT'])
    ).order_by(TestResult.cts.desc()).limit(15).all()
    
    alerts_feed = []
    for result, req, eq in active_alerts:
        overall = result.evaluation_result.get('overall', 'ALERT')
        
        # Get flagged fields
        flagged_fields = []
        for field in result.evaluation_result.get('fields', []):
            if field.get('status') in ['CRITICAL', 'ALERT']:
                flagged_fields.append(f"{field.get('label', '')}: {field.get('value', '')}{field.get('unit', '')}")
        
        alerts_feed.append({
            'id': str(result.id),
            'ueic': eq.ueic if eq else '',
            'title': f"{overall} — {req.test_type.name if req.test_type else 'Test'}",
            'severity': 'critical' if overall == 'CRITICAL' else 'alert',
            'timestamp': result.cts.strftime('%d-%b-%Y %H:%M') if result.cts else None,
            'message': ' | '.join(flagged_fields[:2]) if flagged_fields else 'Test result requires attention',
            'equipment': eq.manufacturer or eq.ueic if eq else '',
            'substation': req.department.name if req.department else ''
        })
    
    # =========================================================================
    # 9. Test Schedule Trend (for bar chart)
    # =========================================================================
    
    # Weekly test counts for next 4 weeks
    weekly_schedule = []
    for week_offset in range(4):
        week_start = now.date() + timedelta(days=week_offset * 7)
        week_end = week_start + timedelta(days=6)
        
        # Count tests due in this week by type
        dga_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(name='DGA')
        ).scalar() or 0
        
        bdv_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(name='BDV')
        ).scalar() or 0
        
        ir_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(name='Insulation Resistance')
        ).scalar() or 0
        
        sf6_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(name='SF6 Purity')
        ).scalar() or 0
        
        other_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(CategoryDetails.name.notin_(['DGA', 'BDV', 'Insulation Resistance', 'SF6 Purity']))
        ).scalar() or 0
        
        weekly_schedule.append({
            'week': week_offset + 1,
            'dga': dga_count,
            'bdv': bdv_count,
            'ir': ir_count,
            'sf6': sf6_count,
            'others': other_count,
            'total': dga_count + bdv_count + ir_count + sf6_count + other_count
        })
    
    # =========================================================================
    # 10. Monthly Compliance Trend (last 6 months)
    # =========================================================================
    
    compliance_trend = []
    for i in range(6):
        month_end = now - timedelta(days=30 * i)
        month_start = month_end - timedelta(days=30)
        
        month_total = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(month_start, month_end)
        ).scalar() or 0
        
        month_completed = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(month_start, month_end),
            TestingRequest.status.in_(CLOSED_STATUSES)
        ).scalar() or 0
        
        compliance = int((month_completed / month_total * 100)) if month_total > 0 else 0
        
        compliance_trend.insert(0, {
            'month': month_start.strftime('%b'),
            'compliance': compliance,
            'total': month_total,
            'completed': month_completed
        })
    
    # =========================================================================
    # Final Response
    # =========================================================================
    
    return {
        # KPI Cards (6 cards)
        'kpi_cards': [
            {
                'label': 'Test Compliance Rate',
                'value': test_compliance,
                'display': f"{test_compliance}%",
                'sub': f"{tested_equipment} of {total_equipment} equipment tested (90d)",
                'trend': '+2%',
                'trend_dir': 'up',
                'colour': 'green' if test_compliance >= 80 else ('amber' if test_compliance >= 60 else 'red')
            },
            {
                'label': 'Overdue Tests',
                'value': overdue_tests,
                'display': str(overdue_tests),
                'sub': f"Escalation: Y:{escalation_levels['YELLOW']} O:{escalation_levels['ORANGE']} R:{escalation_levels['RED']}",
                'trend': None,
                'trend_dir': 'up' if overdue_tests > 5 else 'neutral',
                'colour': 'red' if overdue_tests > 10 else ('amber' if overdue_tests > 0 else 'green')
            },
            {
                'label': 'ALERT / CRITICAL',
                'value': alert_critical_total,
                'display': str(alert_critical_total),
                'sub': f"{alert_count} ALERT · {critical_count_total} CRITICAL",
                'trend': None,
                'trend_dir': 'up' if critical_count_total > 0 else 'neutral',
                'colour': 'red' if critical_count_total > 0 else ('amber' if alert_count_total > 0 else 'green')
            },
            {
                'label': 'Open Remedial Actions',
                'value': open_remediation,
                'display': str(open_remediation),
                'sub': f"{overdue_remediation} overdue · oldest pending",
                'trend': None,
                'trend_dir': 'up' if overdue_remediation > 0 else 'neutral',
                'colour': 'teal'
            },
            {
                'label': 'Maintenance Compliance',
                'value': maintenance_compliance,
                'display': f"{maintenance_compliance}%",
                'sub': f"{maintenance_compliant} of {total_equipment} equipment maintained (90d)",
                'trend': '-4%',
                'trend_dir': 'down',
                'colour': 'green' if maintenance_compliance >= 80 else ('amber' if maintenance_compliance >= 60 else 'red')
            },
            {
                'label': 'TA&QC Compliance',
                'value': taqc_compliance,
                'display': f"{taqc_compliance}%",
                'sub': f"{approved_tests} of {total_tests} tests approved (90d)",
                'trend': '+5%',
                'trend_dir': 'up',
                'colour': 'purple'
            }
        ],
        
        # Test compliance by type
        'test_compliance_by_type': test_compliance_by_type,
        
        # Equipment health summary
        'equipment_health': equipment_health,
        
        # Overdue tests breakdown
        'overdue_tests': {
            'total': overdue_tests,
            'escalation_breakdown': escalation_levels,
            'items': overdue_breakdown
        },
        
        # Upcoming test schedule
        'test_schedule': {
            'weeks': weeks_data,
            'upcoming_tests': [
                {
                    'id': str(t.id),
                    'ueic': t.equipment.ueic if t.equipment else '',
                    'test_type': t.test_type.name if t.test_type else 'Test',
                    'due_date': t.due_date.strftime('%d-%b-%Y') if t.due_date else None,
                    'substation': t.department.name if t.department else ''
                }
                for t in upcoming_tests[:15]
            ]
        },
        
        # Weekly schedule for bar chart
        'weekly_schedule': weekly_schedule,
        
        # Recent test results
        'recent_test_results': recent_results_list,
        
        # Open remedial actions
        'open_remediation': {
            'total': open_remediation,
            'overdue': overdue_remediation,
            'items': remedial_actions_list
        },
        
        # Active alerts feed
        'active_alerts': alerts_feed,
        
        # Compliance trend (for line chart)
        'compliance_trend': compliance_trend,
        
        # Role view info
        'role_view': {
            'view': 'test_coordinator',
            'permitted_widgets': [
                'kpi_cards', 'test_compliance_by_type', 'equipment_health',
                'overdue_tests', 'test_schedule', 'recent_test_results',
                'open_remediation', 'active_alerts', 'compliance_trend'
            ]
        }
    }


@router.get("/asset")
def get_asset_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Asset Data Officer Dashboard — equipment registry and data quality view.
    
    Based on SEACMS-AI SRS v2.0:
    - Sec 3: Equipment Asset Database Module
    - Sec 3.3.2: Data Sorting, Filtering and Search
    - Sec 3.3.3: Equipment Failure Registry
    - Sec 3.3.4: Failed and Scrapped Equipment History
    - Sec 3.3.5: Design Problem Tracking and Alert
    - Sec 9: Reporting Module
    
    Visible to: Asset Data Officer, Equipment Registry Manager roles
    """
    from models import TestingRequest, Equipment, EquipmentStatus, TestResult, Recommendation
    from sqlalchemy import func, and_
    from datetime import datetime, timedelta
    
    svc = _svc(db, current_user, org_id, dept_id)
    
    now = datetime.now()
    ninety_days_ago = now - timedelta(days=90)
    dept_cond = (Equipment.department_id.in_(svc.dept_ids)) if svc.dept_ids else True
    
    # =========================================================================
    # 1. KPI Cards for Asset Dashboard
    # =========================================================================
    
    # Total Equipment Registry
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond
    ).scalar() or 0
    
    # Active Equipment
    active_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.status == 'active'
    ).scalar() or 0
    
    # Equipment with complete nameplate data
    complete_data_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.manufacturer.isnot(None),
        Equipment.serial_number.isnot(None),
        Equipment.year_of_manufacture.isnot(None),
        Equipment.commissioning_date.isnot(None)
    ).scalar() or 0
    data_completeness = int((complete_data_equipment / total_equipment * 100)) if total_equipment > 0 else 0
    
    # Equipment with missing mandatory fields
    missing_mandatory = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        and_(
            Equipment.manufacturer.is_(None),
            Equipment.serial_number.is_(None)
        )
    ).scalar() or 0
    
    # Failure Registry - Open entries
    open_failures = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_(OPEN_STATUSES)
    ).scalar() or 0
    
    # High priority failures
    high_priority_failures = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.priority.in_(['high', 'critical']),
        TestingRequest.status.in_(OPEN_STATUSES)
    ).scalar() or 0
    
    # Design Problem Alerts
    design_problems = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.design_problem,
        TestingRequest.status == 'open'
    ).scalar() or 0
    
    # Equipment pending replacement (age > 30 years)
    thirty_years_ago = now - timedelta(days=365 * 30)
    ageing_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.status == 'active',
        Equipment.commissioning_date < thirty_years_ago
    ).scalar() or 0
    
    # =========================================================================
    # 2. Failure Registry List
    # =========================================================================
    
    failure_registry = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_(OPEN_STATUSES)
    ).order_by(TestingRequest.priority.desc(), TestingRequest.cts.desc()).limit(20).all()
    
    failure_list = []
    for fr in failure_registry:
        ueic = fr.equipment.ueic if fr.equipment else ''
        equipment_name = fr.equipment.manufacturer or ueic if fr.equipment else ''
        dept_name = fr.department.name if fr.department else ''
        
        days_open = (now - fr.cts).days if fr.cts else 0
        
        failure_list.append({
            'id': str(fr.id),
            'request_number': fr.request_number,
            'ueic': ueic,
            'equipment': equipment_name,
            'substation': dept_name,
            'failure_date': fr.failure_date.strftime('%d-%b-%Y') if hasattr(fr, 'failure_date') and fr.failure_date else None,
            'failure_type': fr.failure_type if hasattr(fr, 'failure_type') else 'Unknown',
            'priority': fr.priority if hasattr(fr, 'priority') else 'medium',
            'status': fr.status.value if hasattr(fr.status, 'value') else str(fr.status),
            'days_open': days_open,
            'severity': 'critical' if fr.priority in ['high', 'critical'] else 'warning'
        })
    
    # =========================================================================
    # 3. Maintenance Overdue List
    # =========================================================================
    
    overdue_maintenance = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False)
    ).order_by(TestingRequest.due_date.asc()).limit(15).all()
    
    maintenance_list = []
    for maint in overdue_maintenance:
        days_overdue = (now.date() - maint.due_date.date()).days if maint.due_date else 0
        ueic = maint.equipment.ueic if maint.equipment else ''
        equipment_name = maint.equipment.manufacturer or ueic if maint.equipment else ''
        
        maintenance_list.append({
            'id': str(maint.id),
            'ueic': ueic,
            'equipment': equipment_name,
            'maintenance_type': maint.title,
            'days_overdue': days_overdue,
            'original_due_date': maint.due_date.strftime('%d-%b-%Y') if maint.due_date else None,
            'severity': 'critical' if days_overdue > 30 else ('warning' if days_overdue > 14 else 'normal'),
            'assigned_to': maint.assigned_to_name or 'Unassigned'
        })
    
    # =========================================================================
    # 4. Open Remedial Actions List
    # =========================================================================
    
    open_remediation = db.query(Recommendation).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending'
    ).order_by(Recommendation.cts.asc()).limit(15).all()
    
    remediation_list = []
    for rec in open_remediation:
        req = rec.testing_request
        ueic = req.equipment.ueic if req and req.equipment else ''
        days_open = (now - rec.cts).days if rec.cts else 0
        
        remediation_list.append({
            'id': str(rec.id),
            'ueic': ueic,
            'description': rec.summary or rec.detailed_notes or '',
            'assigned_to': 'Unassigned',
            'due_date': None,
            'days_open': days_open,
            'is_overdue': days_open > 14,
            'recommendation_type': rec.recommendation_type.value if hasattr(rec.recommendation_type, 'value') else 'General'
        })
    
    # =========================================================================
    # 5. Equipment Data Quality Summary
    # =========================================================================
    
    # Equipment by status
    equipment_by_status = db.query(
        Equipment.status,
        func.count(Equipment.id).label('count')
    ).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond
    ).group_by(Equipment.status).all()
    
    status_summary = {}
    for row in equipment_by_status:
        status_key = row.status.value if hasattr(row.status, 'value') else str(row.status)
        status_summary[status_key] = row.count
    
    # Equipment by voltage class
    equipment_by_voltage = db.query(
        Equipment.voltage_class,
        func.count(Equipment.id).label('count')
    ).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.voltage_class.isnot(None)
    ).group_by(Equipment.voltage_class).order_by(Equipment.voltage_class.desc()).all()
    
    voltage_summary = [{'voltage': row.voltage_class, 'count': row.count} for row in equipment_by_voltage]
    
    # Equipment by manufacturer
    equipment_by_manufacturer = db.query(
        Equipment.manufacturer,
        func.count(Equipment.id).label('count')
    ).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.manufacturer.isnot(None)
    ).group_by(Equipment.manufacturer).order_by(func.count(Equipment.id).desc()).limit(10).all()
    
    manufacturer_summary = [{'manufacturer': row.manufacturer, 'count': row.count} for row in equipment_by_manufacturer]
    
    # =========================================================================
    # 6. Design Problem Alerts
    # =========================================================================
    
    design_problem_alerts = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.design_problem,
        TestingRequest.status == 'open'
    ).order_by(TestingRequest.priority.desc(), TestingRequest.cts.desc()).limit(10).all()
    
    design_problem_list = []
    for dp in design_problem_alerts:
        ueic = dp.equipment.ueic if dp.equipment else ''
        equipment_name = dp.equipment.manufacturer or ueic if dp.equipment else ''
        make = dp.equipment.manufacturer if dp.equipment else 'Unknown'
        
        design_problem_list.append({
            'id': str(dp.id),
            'ueic': ueic,
            'equipment': equipment_name,
            'make': make,
            'problem_description': dp.title,
            'affected_units': dp.affected_units_count if hasattr(dp, 'affected_units_count') else 1,
            'priority': dp.priority if hasattr(dp, 'priority') else 'medium',
            'date_identified': dp.cts.strftime('%d-%b-%Y') if dp.cts else None,
            'status': 'open'
        })
    
    # =========================================================================
    # 7. Equipment Search Stats (for filtering)
    # =========================================================================
    
    # Unique substations with equipment
    substations = db.query(
        func.distinct(Equipment.department_id),
        func.count(Equipment.id).label('equipment_count')
    ).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.department_id.isnot(None)
    ).group_by(Equipment.department_id).all()
    
    substation_list = [{'dept_id': str(s[0]), 'equipment_count': s[1]} for s in substations]
    
    # =========================================================================
    # Final Response
    # =========================================================================
    
    return {
        # KPI Cards for Asset Dashboard
        'kpi_cards': [
            {
                'label': 'Total Equipment',
                'value': total_equipment,
                'display': str(total_equipment),
                'sub': f"{active_equipment} active",
                'trend': None,
                'trend_dir': 'neutral',
                'colour': 'blue'
            },
            {
                'label': 'Data Completeness',
                'value': data_completeness,
                'display': f"{data_completeness}%",
                'sub': f"{complete_data_equipment} of {total_equipment} complete",
                'trend': None,
                'trend_dir': 'up' if data_completeness > 80 else 'neutral',
                'colour': 'green' if data_completeness >= 90 else ('amber' if data_completeness >= 70 else 'red')
            },
            {
                'label': 'Missing Mandatory Data',
                'value': missing_mandatory,
                'display': str(missing_mandatory),
                'sub': "Equipment without manufacturer/serial",
                'trend': None,
                'trend_dir': 'down' if missing_mandatory == 0 else 'up',
                'colour': 'red' if missing_mandatory > 10 else ('amber' if missing_mandatory > 0 else 'green')
            },
            {
                'label': 'Failure Registry',
                'value': open_failures,
                'display': str(open_failures),
                'sub': f"{high_priority_failures} high priority",
                'trend': None,
                'trend_dir': 'up' if open_failures > 5 else 'neutral',
                'colour': 'red' if high_priority_failures > 0 else ('amber' if open_failures > 0 else 'green')
            },
            {
                'label': 'Design Problem Alerts',
                'value': design_problems,
                'display': str(design_problems),
                'sub': "Make/model issues requiring attention",
                'trend': None,
                'trend_dir': 'up' if design_problems > 0 else 'neutral',
                'colour': 'red' if design_problems > 5 else ('amber' if design_problems > 0 else 'green')
            },
            {
                'label': 'Ageing Equipment',
                'value': ageing_equipment,
                'display': str(ageing_equipment),
                'sub': ">30 years in service",
                'trend': None,
                'trend_dir': 'up' if ageing_equipment > 0 else 'neutral',
                'colour': 'red' if ageing_equipment > 20 else ('amber' if ageing_equipment > 0 else 'green')
            }
        ],
        
        # Failure Registry List
        'failure_registry': {
            'total': open_failures,
            'high_priority': high_priority_failures,
            'items': failure_list
        },
        
        # Maintenance Overdue List
        'maintenance_overdue': {
            'total': len(overdue_maintenance),
            'items': maintenance_list
        },
        
        # Open Remedial Actions
        'open_remediation': {
            'total': len(open_remediation),
            'overdue': sum(1 for r in remediation_list if r['is_overdue']),
            'items': remediation_list
        },
        
        # Equipment Data Quality Summary
        'data_quality': {
            'by_status': status_summary,
            'by_voltage': voltage_summary,
            'by_manufacturer': manufacturer_summary,
            'total_equipment': total_equipment,
            'active_equipment': active_equipment,
            'complete_data_rate': data_completeness
        },
        
        # Design Problem Alerts
        'design_problem_alerts': {
            'total': design_problems,
            'items': design_problem_list
        },
        
        # Substations with equipment
        'substations': substation_list,
        
        # Role view info
        'role_view': {
            'view': 'asset',
            'permitted_widgets': [
                'kpi_cards', 'failure_registry', 'maintenance_overdue',
                'open_remediation', 'data_quality', 'design_problem_alerts'
            ]
        }
    }


@router.get("/ae")
def get_ae_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AE / JE Dashboard — Field officer view.

    SRS §8.3.1 Field Officer Dashboard:
    - Tests due in next 30 days for my substations
    - Open remedial actions assigned to me
    - Overdue maintenance (due_date < today)
    - Pending TA&QC compliance items
    """
    from models import TestingRequest, Equipment, Recommendation
    from sqlalchemy import func
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id, dept_id)
    now = datetime.now()
    next_30 = now + timedelta(days=30)

    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True
    dept_cond_eq = (Equipment.department_id.in_(svc.dept_ids)) if svc.dept_ids else True

    # ── KPIs ──────────────────────────────────────────────────────────────

    tests_due_30 = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(now, next_30),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    overdue_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    open_remediation = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                dept_cond,
            )
        ),
    ).scalar() or 0

    maintenance_overdue = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    fr_pending = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_(OPEN_STATUSES),
    ).scalar() or 0

    # ── Upcoming tests list (next 30 days) ────────────────────────────────
    upcoming_db = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date.between(now, next_30),
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        )
        .order_by(TestingRequest.due_date.asc())
        .limit(15)
        .all()
    )

    upcoming_list = []
    for req in upcoming_db:
        days_until = (req.due_date.date() - now.date()).days if req.due_date else 0
        upcoming_list.append({
            'id': str(req.id),
            'ueic': req.equipment.ueic if req.equipment else '',
            'test_type': req.test_type.name if req.test_type else 'Test',
            'due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else None,
            'days_until': days_until,
            'substation': req.department.name if req.department else '',
            'status': req.status.value.replace('_', ' ').title(),
            'urgency': 'urgent' if days_until <= 7 else 'soon' if days_until <= 15 else 'normal',
        })

    # ── Open remedial actions list ─────────────────────────────────────────
    remedial_db = (
        db.query(Recommendation)
        .filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.testing_request_id.in_(
                db.query(TestingRequest.id).filter(
                    TestingRequest.organization_id == svc.org_id,
                    dept_cond,
                )
            ),
        )
        .order_by(Recommendation.cts.asc())
        .limit(10)
        .all()
    )

    remedial_list = []
    for rec in remedial_db:
        req = rec.testing_request
        ueic = req.equipment.ueic if req and req.equipment else ''
        days_open = (now - rec.cts).days if rec.cts else 0
        remedial_list.append({
            'id': str(rec.id),
            'ueic': ueic,
            'description': rec.summary or rec.detailed_notes or 'Remedial action required',
            'days_open': days_open,
            'is_overdue': days_open > 14,
            'substation': req.department.name if req and req.department else '',
        })

    # ── Maintenance overdue list ───────────────────────────────────────────
    maint_db = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.maintenance,
            TestingRequest.due_date < now,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        )
        .order_by(TestingRequest.due_date.asc())
        .limit(10)
        .all()
    )

    maint_list = []
    for maint in maint_db:
        days_overdue = (now.date() - maint.due_date.date()).days if maint.due_date else 0
        maint_list.append({
            'id': str(maint.id),
            'ueic': maint.equipment.ueic if maint.equipment else '',
            'title': maint.title or 'Maintenance',
            'days_overdue': days_overdue,
            'substation': maint.department.name if maint.department else '',
            'severity': 'critical' if days_overdue >= 30 else 'warning' if days_overdue >= 7 else 'normal',
        })

    # ── Assigned to me (as tester) ───────────────────────────────────────
    assigned_to_me = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.assigned_tester_id == current_user.id,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # ── Substation (dept) count in scope ─────────────────────────────────
    substation_count = len(svc.dept_ids) if svc.dept_ids else (
        db.query(func.count(func.distinct(TestingRequest.department_id))).filter(
            TestingRequest.organization_id == svc.org_id,
        ).scalar() or 0
    )

    # ── Test compliance (90-day rolling) ─────────────────────────────────
    ninety_ago = now - timedelta(days=90)
    tc_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    tc_done = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    test_compliance_pct = int(tc_done / tc_due * 100) if tc_due > 0 else 100

    # ── Maintenance compliance (90-day) ───────────────────────────────────
    mc_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    mc_done = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    maint_compliance_pct = int(mc_done / mc_due * 100) if mc_due > 0 else 100

    # ── Overdue tests list + age bands ────────────────────────────────────
    overdue_reqs_ae = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).order_by(TestingRequest.due_date.asc()).limit(15).all()

    band_lt7 = band_7_30 = band_gt30 = 0
    overdue_list_ae = []
    for r in overdue_reqs_ae:
        days_ov = (now.date() - r.due_date.date()).days if r.due_date else 0
        sev = 'critical' if days_ov >= 30 else 'warning' if days_ov >= 7 else 'normal'
        if days_ov >= 30:
            band_gt30 += 1
        elif days_ov >= 7:
            band_7_30 += 1
        else:
            band_lt7 += 1
        overdue_list_ae.append({
            'id': str(r.id),
            'ueic': r.equipment.ueic if r.equipment else '',
            'test_type': r.test_type.name if r.test_type else 'Test',
            'substation': r.department.name if r.department else '',
            'days_overdue': days_ov,
            'due_date': r.due_date.strftime('%d-%b-%Y') if r.due_date else '',
            'severity': sev,
        })
    overdue_bands_ae = [
        {'label': '< 7 days',   'count': band_lt7,   'dot': 'orange'},
        {'label': '7-30 days',  'count': band_7_30,  'dot': 'deep_orange'},
        {'label': '> 30 days',  'count': band_gt30,  'dot': 'red'},
    ]

    # ── TA&QC pending list ────────────────────────────────────────────────
    taqc_recs_ae = db.query(Recommendation).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                dept_cond,
            )
        ),
    ).order_by(Recommendation.cts.asc()).limit(10).all()

    taqc_pending_list = []
    for rec in taqc_recs_ae:
        days = (now - rec.cts).days if rec.cts else 0
        rec_type = rec.recommendation_type.value if rec.recommendation_type else ''
        severity = 'Major' if rec_type == 'fail' else ('Minor' if rec_type == 'conditional' else 'Advisory')
        ueic = ''
        try:
            if rec.testing_request and rec.testing_request.equipment:
                ueic = rec.testing_request.equipment.ueic or ''
        except Exception:
            pass
        taqc_pending_list.append({
            'id': 'OBS-' + str(rec.id)[:6].upper(),
            'summary': rec.summary or 'Observation',
            'ueic': ueic,
            'severity': severity,
            'days_open': days,
        })

    # ── Alerts feed (ALERT / CRITICAL results) ────────────────────────────
    from models import TestResult
    alert_db_ae = (
        db.query(TestResult, TestingRequest, Equipment)
        .join(TestingRequest, TestResult.testing_request_id == TestingRequest.id)
        .join(Equipment, TestingRequest.equipment_id == Equipment.id)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestResult.evaluation_result.isnot(None),
            TestResult.evaluation_result['overall'].astext.in_(['CRITICAL', 'ALERT']),
        )
        .order_by(TestResult.cts.desc())
        .limit(8)
        .all()
    )
    alerts_feed_ae = []
    for result, req, eq in alert_db_ae:
        overall = result.evaluation_result.get('overall', 'ALERT')
        flagged = []
        for field in result.evaluation_result.get('fields', []):
            if field.get('status') in ['CRITICAL', 'ALERT']:
                flagged.append(f"{field.get('label','')}: {field.get('value','')}{field.get('unit','')}")
        alerts_feed_ae.append({
            'id': str(result.id),
            'title': f"{overall} — {req.test_type.name if req.test_type else 'Test'} · {eq.ueic if eq else ''}",
            'desc': ' | '.join(flagged[:2]) if flagged else 'Test result requires attention',
            'status': overall,
            'severity': 'critical' if overall == 'CRITICAL' else 'alert',
            'timestamp': result.cts.strftime('%d-%b-%Y %H:%M') if result.cts else None,
            'substation': req.department.name if req.department else '',
        })

    # ── Remedial compliance ───────────────────────────────────────────────
    total_rem_ae = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                dept_cond,
            )
        ),
    ).scalar() or 0
    closed_rem_ae = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'approved',
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                dept_cond,
            )
        ),
    ).scalar() or 0
    remedial_compliance = {
        'total':  total_rem_ae,
        'closed': closed_rem_ae,
        'open':   total_rem_ae - closed_rem_ae,
        'pct':    int(closed_rem_ae / total_rem_ae * 100) if total_rem_ae > 0 else 100,
    }

    # ── Substations at a glance ───────────────────────────────────────────
    from models import OrgDepartment as DeptFO
    if svc.dept_ids:
        depts_fo = db.query(DeptFO).filter(DeptFO.id.in_(svc.dept_ids)).limit(5).all()
    else:
        depts_fo = db.query(DeptFO).filter(
            DeptFO.organization_id == svc.org_id).limit(5).all()
    substations_summary = []
    for dept in depts_fo:
        d_ov = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            TestingRequest.department_id == dept.id,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date < now,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        d_rem = db.query(func.count(Recommendation.id)).filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.testing_request_id.in_(
                db.query(TestingRequest.id).filter(
                    TestingRequest.department_id == dept.id,
                    TestingRequest.organization_id == svc.org_id,
                )
            ),
        ).scalar() or 0
        d_maint = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            TestingRequest.department_id == dept.id,
            TestingRequest.request_category == RequestCategory.maintenance,
            TestingRequest.due_date < now,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        substations_summary.append({
            'name': dept.name,
            'overdue_tests': d_ov,
            'open_remedials': d_rem,
            'maint_overdue': d_maint,
        })

    return {
        'kpis': {
            'tests_due_30_days': tests_due_30,
            'overdue_tests': overdue_tests,
            'open_remediation': open_remediation,
            'maintenance_overdue': maintenance_overdue,
            'fr_pending': fr_pending,
            'assigned_to_me': assigned_to_me,
            'substation_count': substation_count,
            'test_compliance': test_compliance_pct,
            'maint_compliance': maint_compliance_pct,
            'taqc_pending': len(taqc_pending_list),
        },
        'upcoming_tests': upcoming_list,
        'overdue_test_list': overdue_list_ae,
        'overdue_test_bands': overdue_bands_ae,
        'open_remediation_list': remedial_list,
        'maintenance_overdue_list': maint_list,
        'taqc_pending_list': taqc_pending_list,
        'alerts_feed': alerts_feed_ae,
        'remedial_compliance': remedial_compliance,
        'maint_compliance_pct': maint_compliance_pct,
        'substations_summary': substations_summary,
    }


@router.get("/aee")
def get_aee_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AEE Dashboard - Field-level maintenance supervisor view.

    SRS §8.3.1 Field Officer Dashboard:
    - Tests due in next 30 days for my substations
    - Open remedial actions assigned to me
    - Overdue maintenance (due_date < today)
    - Pending TA&QC compliance
    """
    from models import TestingRequest, Equipment, Recommendation, TestResult
    from sqlalchemy import func
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id, dept_id)
    now = datetime.now()
    next_30 = now + timedelta(days=30)

    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True
    dept_cond_eq = (Equipment.department_id.in_(svc.dept_ids)) if svc.dept_ids else True

    # ── KPIs ──────────────────────────────────────────────────────────────

    tests_due_30 = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(now, next_30),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # Awaiting AEE approval: submitted by field staff, not yet signed off
    from models import TestingRequestStatus as TRS
    awaiting_approval = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status.in_([TRS.submitted, TRS.pending_approval]),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # Section compliance (90-day)
    ninety_ago = now - timedelta(days=90)
    sec_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    sec_done = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    section_compliance = int(sec_done / sec_due * 100) if sec_due > 0 else 100

    equipment_count = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond_eq,
        Equipment.status == 'active',
    ).scalar() or 0

    maintenance_overdue = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    open_remediation = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                dept_cond,
            )
        ),
    ).scalar() or 0

    fr_pending = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_(OPEN_STATUSES),
    ).scalar() or 0

    # ── Assignments list ───────────────────────────────────────────────────
    from models import TestSession
    assignments_db = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.status.in_(['submitted', 'pending_approval', 'in_progress', 'assigned']),
        )
        .order_by(TestingRequest.due_date.asc().nullslast())
        .limit(10)
        .all()
    )

    assignments_list = []
    for req in assignments_db:
        due_str = 'No deadline'
        color = 'blue'
        if req.due_date:
            days_diff = (req.due_date.date() - now.date()).days
            if days_diff < 0:
                due_str = f'{abs(days_diff)} days overdue'
                color = 'red'
            elif days_diff == 0:
                due_str = 'Today'
                color = 'orange'
            else:
                due_str = f'{days_diff} days'
                color = 'blue' if req.status.value == 'in_progress' else 'orange'
        status_text = req.status.value.replace('_', ' ').title()
        test_type_name = req.test_type.name if req.test_type else 'Test'
        dept_name = req.department.name if req.department else 'Unknown Location'

        sess_row = (
            db.query(
                func.count(TestSession.id).label('cnt'),
                func.max(TestSession.session_date).label('last_date'),
            )
            .filter(TestSession.testing_request_id == req.id)
            .first()
        )
        session_count = sess_row.cnt or 0
        last_session_date = (
            sess_row.last_date.strftime('%d %b %Y') if sess_row.last_date else None
        )

        assignments_list.append({
            'id': str(req.id),
            'title': f'{test_type_name} - {dept_name}',
            'status': status_text,
            'due': due_str,
            'color': color,
            'session_count': session_count,
            'last_session_date': last_session_date,
        })

    # ── Upcoming tests list (next 30 days) ────────────────────────────────
    upcoming_db = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date.between(now, next_30),
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        )
        .order_by(TestingRequest.due_date.asc())
        .limit(15)
        .all()
    )

    upcoming_list = []
    for req in upcoming_db:
        days_until = (req.due_date.date() - now.date()).days if req.due_date else 0
        upcoming_list.append({
            'id': str(req.id),
            'ueic': req.equipment.ueic if req.equipment else '',
            'test_type': req.test_type.name if req.test_type else 'Test',
            'due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else None,
            'days_until': days_until,
            'substation': req.department.name if req.department else '',
            'status': req.status.value.replace('_', ' ').title(),
            'urgency': 'urgent' if days_until <= 7 else 'soon' if days_until <= 15 else 'normal',
        })

    # ── Open remedial actions list ─────────────────────────────────────────
    remedial_db = (
        db.query(Recommendation)
        .filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.testing_request_id.in_(
                db.query(TestingRequest.id).filter(
                    TestingRequest.organization_id == svc.org_id,
                    dept_cond,
                )
            ),
        )
        .order_by(Recommendation.cts.asc())
        .limit(10)
        .all()
    )

    remedial_list = []
    for rec in remedial_db:
        req = rec.testing_request
        ueic = req.equipment.ueic if req and req.equipment else ''
        days_open = (now - rec.cts).days if rec.cts else 0
        remedial_list.append({
            'id': str(rec.id),
            'ueic': ueic,
            'description': rec.summary or rec.detailed_notes or 'Remedial action required',
            'days_open': days_open,
            'is_overdue': days_open > 14,
            'substation': req.department.name if req and req.department else '',
        })

    # ── Maintenance overdue list ───────────────────────────────────────────
    maint_db = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.maintenance,
            TestingRequest.due_date < now,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        )
        .order_by(TestingRequest.due_date.asc())
        .limit(10)
        .all()
    )

    maint_list = []
    for maint in maint_db:
        days_overdue = (now.date() - maint.due_date.date()).days if maint.due_date else 0
        maint_list.append({
            'id': str(maint.id),
            'ueic': maint.equipment.ueic if maint.equipment else '',
            'title': maint.title or 'Maintenance',
            'days_overdue': days_overdue,
            'substation': maint.department.name if maint.department else '',
            'severity': 'critical' if days_overdue >= 30 else 'warning' if days_overdue >= 7 else 'normal',
        })

    # ── Equipment status (ALERT/CRITICAL from test results) ───────────────
    from datetime import date
    alert_eq = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext.in_(['ALERT', 'CRITICAL']),
    ).scalar() or 0

    under_repair_count = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond_eq,
        Equipment.status == 'under_repair',
    ).scalar() or 0

    # ── Section compliance (test) pct ──────────────────────────────────────
    test_compliance_pct = section_compliance  # already computed above

    # ── Maint compliance pct (90-day) ─────────────────────────────────────
    maint_due_90 = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    maint_done_90 = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    maint_compliance_pct = int(maint_done_90 / maint_due_90 * 100) if maint_due_90 > 0 else 100

    # ── Overdue test list with age bands ──────────────────────────────────
    overdue_db = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date < now,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        )
        .order_by(TestingRequest.due_date.asc())
        .limit(15)
        .all()
    )
    overdue_list_aee = []
    band_lt7 = band_7_30 = band_gt30 = 0
    for req in overdue_db:
        days_over = (now.date() - req.due_date.date()).days if req.due_date else 0
        if days_over < 7:
            band_lt7 += 1
        elif days_over <= 30:
            band_7_30 += 1
        else:
            band_gt30 += 1
        overdue_list_aee.append({
            'id': str(req.id),
            'ueic': req.equipment.ueic if req.equipment else '',
            'test_type': req.test_type.name if req.test_type else 'Test',
            'due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else '',
            'days_overdue': days_over,
            'substation': req.department.name if req.department else '',
            'severity': 'critical' if days_over >= 30 else 'warning' if days_over >= 7 else 'normal',
        })
    overdue_bands_aee = [
        {'label': '< 7 days', 'count': band_lt7, 'dot': 'orange'},
        {'label': '7-30 days', 'count': band_7_30, 'dot': 'deep_orange'},
        {'label': '> 30 days', 'count': band_gt30, 'dot': 'red'},
    ]

    # ── TA&QC pending list ────────────────────────────────────────────────
    taqc_db = (
        db.query(Recommendation)
        .filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.testing_request_id.in_(
                db.query(TestingRequest.id).filter(
                    TestingRequest.organization_id == svc.org_id,
                    dept_cond,
                )
            ),
        )
        .order_by(Recommendation.cts.asc())
        .limit(10)
        .all()
    )
    taqc_pending_list = []
    for rec in taqc_db:
        req = rec.testing_request
        rtype = rec.recommendation_type.value if rec.recommendation_type else ''
        severity = 'Major' if rtype == 'fail' else 'Minor' if rtype == 'conditional' else 'Advisory'
        days_open = (now - rec.cts).days if rec.cts else 0
        taqc_pending_list.append({
            'id': str(rec.id),
            'ueic': req.equipment.ueic if req and req.equipment else '',
            'substation': req.department.name if req and req.department else '',
            'summary': rec.summary or 'Observation pending',
            'severity': severity,
            'days_open': days_open,
            'next_action': rec.next_action or '',
        })

    # ── ALERT/CRITICAL alerts feed ────────────────────────────────────────
    from models import OrgDepartment
    alerts_db = (
        db.query(TestResult)
        .join(TestingRequest, TestResult.testing_request_id == TestingRequest.id)
        .filter(
            TestResult.organization_id == svc.org_id,
            TestResult.evaluation_result.isnot(None),
            TestResult.evaluation_result['overall'].astext.in_(['ALERT', 'CRITICAL']),
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
        )
        .order_by(TestResult.cts.desc())
        .limit(8)
        .all()
    )
    alerts_feed_aee = []
    for tr in alerts_db:
        req = tr.testing_request
        level = tr.evaluation_result.get('overall', 'ALERT') if tr.evaluation_result else 'ALERT'
        alerts_feed_aee.append({
            'ueic': req.equipment.ueic if req and req.equipment else '',
            'substation': req.department.name if req and req.department else '',
            'test_type': req.test_type.name if req and req.test_type else 'Test',
            'level': level,
            'date': tr.cts.strftime('%d-%b-%Y') if tr.cts else '',
        })

    # ── Remedial compliance ────────────────────────────────────────────────
    total_rem = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                dept_cond,
            )
        ),
    ).scalar() or 0
    closed_rem = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'approved',
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                dept_cond,
            )
        ),
    ).scalar() or 0
    remedial_compliance = {
        'total': total_rem,
        'closed': closed_rem,
        'open': total_rem - closed_rem,
        'pct': int(closed_rem / total_rem * 100) if total_rem > 0 else 100,
    }

    # ── Substations summary ───────────────────────────────────────────────
    from models import OrgDepartment
    dept_rows = db.query(OrgDepartment).filter(
        OrgDepartment.organization_id == svc.org_id,
    ).all()
    substations_summary = []
    for dept in dept_rows[:10]:
        dcond = TestingRequest.department_id == dept.id
        ot = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dcond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date < now,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        or_ = db.query(func.count(Recommendation.id)).filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.testing_request_id.in_(
                db.query(TestingRequest.id).filter(
                    TestingRequest.organization_id == svc.org_id,
                    dcond,
                )
            ),
        ).scalar() or 0
        mo = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dcond,
            TestingRequest.request_category == RequestCategory.maintenance,
            TestingRequest.due_date < now,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        substations_summary.append({
            'name': dept.name,
            'overdue_tests': ot,
            'open_remedials': or_,
            'maint_overdue': mo,
        })
    substations_summary.sort(key=lambda x: x['overdue_tests'] + x['open_remedials'], reverse=True)

    return {
        'kpis': {
            'tests_due_30_days': tests_due_30,
            'awaiting_approval': awaiting_approval,
            'section_compliance': section_compliance,
            'equipment_count': equipment_count,
            'maintenance_overdue': maintenance_overdue,
            'open_remediation': open_remediation,
            'fr_pending': fr_pending,
            'maint_compliance': maint_compliance_pct,
            'taqc_pending': len(taqc_pending_list),
            'overdue_tests': len(overdue_list_aee),
        },
        'assignments': assignments_list,
        'upcoming_tests': upcoming_list,
        'overdue_test_list': overdue_list_aee,
        'overdue_test_bands': overdue_bands_aee,
        'open_remediation_list': remedial_list,
        'maintenance_overdue_list': maint_list,
        'taqc_pending_list': taqc_pending_list,
        'alerts_feed': alerts_feed_aee,
        'remedial_compliance': remedial_compliance,
        'substations_summary': substations_summary,
        'equipment_status': {
            'operational': equipment_count,
            'under_repair': under_repair_count,
            'alert_critical': alert_eq,
        },
    }
@router.get("/asset")
def get_asset_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Asset Data Officer Dashboard — equipment registry and data quality view."""
    svc = _svc(db, current_user, org_id, dept_id)
    return {
        "kpi_cards":          svc.all_kpi_cards(),
        "overdue_tests":      svc.overdue_tests_breakdown(),
        "failure_registry":   svc.failure_registry_list(),
        "maintenance_overdue": svc.maintenance_overdue(),
        "open_remediation":   svc.open_remediation_list(),
    }

@router.get("/ee-tlss")
def get_ee_tlss_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """EE TLSS Dashboard - Condition monitoring & operational oversight.

    SRS §8.3.1 EE TLSS Dashboard:
    - Zone-level test compliance status (dept-scoped)
    - Equipment with ALERT/CRITICAL flags (from TestResult, not Equipment.status)
    - Transformer repair status (repair_progress)
    - Pending observations

    SRS §8.3.2 KPIs:
    K1 Test Compliance Rate   = completed on time / total due in period
    K2 ALERT/CRITICAL count   = from TestResult.evaluation_result['overall']
    K3 Open Remedial Actions  = by age band (0-7, 8-30, 31+)
    K4 Test Approval Rate     = test approvals (TA&QC observations in Phase 3)
    K5 Repair progress        = from RepairWorkflow
    K6 Maintenance compliance = on-time / due in period
    """
    from models import TestingRequest, Equipment, TestSession, TestResult, Recommendation
    from sqlalchemy import func, and_
    from datetime import datetime, timedelta, date

    svc = _svc(db, current_user, org_id, dept_id)
    now = datetime.now()
    ninety_days_ago = now - timedelta(days=90)

    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True

    # ── K1: Test Compliance Rate — completed on time / total due in period ──
    period_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    on_time_completed = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    test_compliance = int((on_time_completed / period_due * 100)) if period_due > 0 else 100

    # ── Overdue Tests ─────────────────────────────────────────────────────
    overdue_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # ── K2: ALERT/CRITICAL — from TestResult.evaluation_result['overall'] ─
    critical_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'CRITICAL',
    ).scalar() or 0

    alert_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'ALERT',
    ).scalar() or 0

    alert_critical = critical_count + alert_count

    # ── K3: Open Remedial Actions with age bands ──────────────────────────
    all_remedial = db.query(Recommendation).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
    ).all()

    open_remediation = len(all_remedial)
    overdue_remediation = sum(
        1 for r in all_remedial if r.cts and (now - r.cts).days > 14
    )
    age_bands = {'0_7': 0, '8_30': 0, '31_plus': 0}
    for r in all_remedial:
        days = (now - r.cts).days if r.cts else 0
        if days <= 7:
            age_bands['0_7'] += 1
        elif days <= 30:
            age_bands['8_30'] += 1
        else:
            age_bands['31_plus'] += 1

    # ── K4: Maintenance Compliance — correct denominator ─────────────────
    maint_period_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    maint_on_time = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    maintenance_compliance = int((maint_on_time / maint_period_due * 100)) if maint_period_due > 0 else 100

    # ── Test Approval Rate (TA&QC module observations in Phase 3) ─────────
    total_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.cts >= ninety_days_ago,
    ).scalar() or 0

    approved_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status == 'approved',
        TestingRequest.cts >= ninety_days_ago,
    ).scalar() or 0

    test_approval_rate = int((approved_tests / total_tests * 100)) if total_tests > 0 else 0

    # ── Equipment monitored ───────────────────────────────────────────────
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active',
    ).scalar() or 0

    # ── Failure reports pending ───────────────────────────────────────────
    fr_pending = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_(OPEN_STATUSES),
    ).scalar() or 0

    # ── Overdue tests breakdown with escalation bands ─────────────────────
    overdue_requests = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date < now,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        )
        .order_by(TestingRequest.due_date.asc())
        .limit(20)
        .all()
    )

    escalation_levels = {'YELLOW': 0, 'ORANGE': 0, 'RED': 0}
    overdue_breakdown = []
    for req in overdue_requests:
        days_overdue = (now.date() - req.due_date.date()).days if req.due_date else 0
        if days_overdue >= 30:
            escalation = 'T+30 RED'
            escalation_levels['RED'] += 1
            severity = 'critical'
        elif days_overdue >= 7:
            escalation = 'T+7 ORANGE'
            escalation_levels['ORANGE'] += 1
            severity = 'warning'
        else:
            escalation = 'T+0 YELLOW'
            escalation_levels['YELLOW'] += 1
            severity = 'normal'

        overdue_breakdown.append({
            'id': str(req.id),
            'ueic': req.equipment.ueic if req.equipment else '',
            'equipment': req.equipment.manufacturer or (req.equipment.ueic if req.equipment else ''),
            'test_type': req.test_type.name if req.test_type else 'Test',
            'days_overdue': days_overdue,
            'escalation_level': escalation,
            'severity': severity,
            'original_due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else None,
            'substation': req.department.name if req.department else '',
        })

    # ── Alerts feed — from TestResult ALERT/CRITICAL evaluations ──────────
    active_alerts_db = (
        db.query(TestResult, TestingRequest, Equipment)
        .join(TestingRequest, TestResult.testing_request_id == TestingRequest.id)
        .join(Equipment, TestingRequest.equipment_id == Equipment.id)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestResult.evaluation_result.isnot(None),
            TestResult.evaluation_result['overall'].astext.in_(['CRITICAL', 'ALERT']),
        )
        .order_by(TestResult.cts.desc())
        .limit(15)
        .all()
    )

    alerts_feed = []
    for result, req, eq in active_alerts_db:
        overall = result.evaluation_result.get('overall', 'ALERT')
        flagged_fields = []
        for field in result.evaluation_result.get('fields', []):
            if field.get('status') in ['CRITICAL', 'ALERT']:
                flagged_fields.append(
                    f"{field.get('label', '')}: {field.get('value', '')}{field.get('unit', '')}"
                )
        alerts_feed.append({
            'id': str(result.id),
            'ueic': eq.ueic if eq else '',
            'name': f"{overall} — {req.test_type.name if req.test_type else 'Test'}",
            'status': overall,
            'severity': 'critical' if overall == 'CRITICAL' else 'alert',
            'timestamp': result.cts.strftime('%d-%b-%Y %H:%M') if result.cts else None,
            'message': ' | '.join(flagged_fields[:2]) if flagged_fields else 'Test result requires attention',
            'equipment': eq.manufacturer or eq.ueic if eq else '',
            'substation': req.department.name if req.department else '',
        })

    # ── Maintenance overdue count + list ─────────────────────────────────
    maintenance_overdue_count = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    maint_overdue_reqs = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).order_by(TestingRequest.due_date.asc()).limit(10).all()

    maintenance_overdue_list = []
    for r in maint_overdue_reqs:
        days_ov = (now.date() - r.due_date.date()).days if r.due_date else 0
        maintenance_overdue_list.append({
            'id': str(r.id),
            'ueic': r.equipment.ueic if r.equipment else '',
            'substation': r.department.name if r.department else '',
            'description': r.test_type.name if r.test_type else 'Maintenance',
            'days_overdue': days_ov,
        })

    # ── TA&QC observations — from Recommendation records ─────────────────
    taqc_recs = db.query(Recommendation).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
    ).order_by(Recommendation.cts.asc()).limit(20).all()

    taqc_observations = []
    for r in taqc_recs:
        days = (now - r.cts).days if r.cts else 0
        rec_type = r.recommendation_type.value if r.recommendation_type else ''
        severity = 'Major' if rec_type == 'fail' else ('Minor' if rec_type == 'conditional' else 'Advisory')
        ueic = ''
        try:
            if r.testing_request and r.testing_request.equipment:
                ueic = r.testing_request.equipment.ueic or ''
        except Exception:
            pass
        taqc_observations.append({
            'id': str(r.id)[:8].upper(),
            'summary': r.summary or 'Observation',
            'ueic': ueic,
            'severity': severity,
            'days_open': days,
        })
    taqc_major = sum(1 for x in taqc_observations if x['severity'] == 'Major')
    taqc_minor = sum(1 for x in taqc_observations if x['severity'] == 'Minor')
    taqc_advisory = sum(1 for x in taqc_observations if x['severity'] == 'Advisory')

    # ── Repair tracker with stage info ────────────────────────────────────
    from models import RepairWorkflow as RepairWFTlss
    today_tlss = date.today()
    repair_wf_tlss = (
        db.query(RepairWFTlss)
        .filter(
            RepairWFTlss.organization_id == svc.org_id,
            RepairWFTlss.status == 'active',
        )
        .order_by(RepairWFTlss.started_at.desc())
        .limit(10)
        .all()
    )
    repair_tracker_tlss = []
    for wf in repair_wf_tlss:
        eq = wf.equipment
        stage = wf.current_stage
        contracted = wf.contracted_completion
        is_delayed = contracted is not None and wf.completed_at is None and contracted < today_tlss
        delay_days = (today_tlss - contracted).days if is_delayed and contracted else 0
        delay_type = 'vendor' if (wf.workflow_type or '').upper() in ('BREAKDOWN', 'OVERHAUL') else 'kptcl'
        repair_tracker_tlss.append({
            'id': str(wf.id),
            'workflow_number': wf.workflow_number,
            'ueic': eq.ueic if eq else '',
            'equipment_name': eq.manufacturer or eq.ueic if eq else '',
            'workflow_type': wf.workflow_type or 'BREAKDOWN',
            'repairer': wf.vendor_name or 'Unassigned',
            'started_at': wf.started_at.strftime('%d-%b-%Y') if wf.started_at else None,
            'contracted_completion': contracted.strftime('%d-%b-%Y') if contracted else None,
            'progress_pct': wf.progress or 0,
            'stage_sequence': stage.sequence if stage else 0,
            'stage_name': stage.name if stage else 'Pending',
            'is_delayed': is_delayed,
            'delay_days': delay_days,
            'delay_type': delay_type if is_delayed else None,
        })

    # ── Alert/critical equipment table ────────────────────────────────────
    alert_critical_equipment = []
    for alert in alerts_feed[:10]:
        alert_critical_equipment.append({
            'ueic': alert['ueic'],
            'equipment': alert['equipment'],
            'substation': alert['substation'],
            'status': alert['status'],
            'timestamp': alert['timestamp'],
            'message': alert['message'],
        })

    # ── Procurement pipeline ──────────────────────────────────────────────
    from models import ProcurementRequest as ProcReqTlss
    proc_stages_tlss: dict = {}
    for s in ['initiated', 'awaiting_approval', 'rfq_issued', 'comparative_review', 'po_issued', 'inspection']:
        proc_stages_tlss[s] = db.query(func.count(ProcReqTlss.id)).filter(
            ProcReqTlss.organization_id == svc.org_id,
            ProcReqTlss.status == s,
        ).scalar() or 0
    proc_total_tlss = sum(v for k, v in proc_stages_tlss.items() if k != 'inspection')
    oldest_proc_tlss = db.query(ProcReqTlss).filter(
        ProcReqTlss.organization_id == svc.org_id,
        ProcReqTlss.status.notin_(['closed', 'inspection']),
    ).order_by(ProcReqTlss.cts.asc()).first()
    oldest_days_tlss = (now.date() - oldest_proc_tlss.cts.date()).days if oldest_proc_tlss and oldest_proc_tlss.cts else 0
    procurement_pipeline_tlss = {
        'stages': proc_stages_tlss,
        'total_active': proc_total_tlss,
        'oldest_open_days': oldest_days_tlss,
    }

    # ── Open remediation list ─────────────────────────────────────────────
    open_rem_list_recs = db.query(Recommendation).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
    ).order_by(Recommendation.cts.asc()).limit(10).all()

    open_remediation_list = []
    for r in open_rem_list_recs:
        days = (now - r.cts).days if r.cts else 0
        ueic = ''
        try:
            if r.testing_request and r.testing_request.equipment:
                ueic = r.testing_request.equipment.ueic or ''
        except Exception:
            pass
        nxt = r.next_action.value.replace('_', ' ').title() if r.next_action else 'Pending'
        open_remediation_list.append({
            'id': 'REM-' + str(r.id)[:6].upper(),
            'ueic': ueic,
            'summary': r.summary or 'Action required',
            'next_action': nxt,
            'days_open': days,
            'status': 'Overdue' if days > 14 else 'Pending',
        })

    return {
        'kpis': {
            'test_compliance': test_compliance,
            'overdue_tests': overdue_tests,
            'alert_critical': alert_critical,
            'alert_count': alert_count,
            'critical_count': critical_count,
            'open_remediation': open_remediation,
            'overdue_remediation': overdue_remediation,
            'maintenance_compliance': maintenance_compliance,
            'maintenance_overdue': maintenance_overdue_count,
            'test_approval_rate': test_approval_rate,
            'taqc_compliance': test_approval_rate,
            'equipment_monitored': total_equipment,
            'fr_pending': fr_pending,
            'taqc_total': len(taqc_observations),
        },
        'remediation_age_bands': age_bands,
        'overdue_breakdown': overdue_breakdown,
        'escalation_levels': escalation_levels,
        'alerts_feed': alerts_feed,
        'alert_critical_equipment': alert_critical_equipment,
        'repair_tracker': repair_tracker_tlss,
        'maintenance_overdue_list': maintenance_overdue_list,
        'taqc_summary': {
            'major': taqc_major,
            'minor': taqc_minor,
            'advisory': taqc_advisory,
            'observations': taqc_observations[:5],
        },
        'procurement_pipeline': procurement_pipeline_tlss,
        'open_remediation_list': open_remediation_list,
    }


@router.get("/see")
def get_see_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SEE Dashboard — Circle-level supervision.

    SRS §8.3.1: Circle/zone compliance KPIs · top-10 critical equipment ·
                transformer repair zone progress · vendor snapshot placeholder
    SRS §8.3.2 KPIs:
    K1 circle_compliance    = on-time test completion % (90-day window)
    K2 alert_critical       = count from TestResult.evaluation_result['overall']
    K3 open_remediation     = age-banded remedial actions
    K4 taqc_compliance      = approved/total tests (Phase-3 TA&QC placeholder)
    K5 repair_progress      = from RepairWorkflow via DashboardService
    K6 maintenance_overdue  = maintenance requests past due_date
    """
    from models import TestingRequest, Equipment, TestResult, Recommendation
    from models import OrgDepartment as DeptTopSEE
    from sqlalchemy import func, and_
    from sqlalchemy.orm import joinedload
    from datetime import datetime, timedelta, date

    svc = _svc(db, current_user, org_id, dept_id)
    now = datetime.now()
    ninety_days_ago = now - timedelta(days=90)

    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True

    # ── K1: Circle Compliance — on-time test completion (90-day window) ──────
    period_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    on_time_completed = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    circle_compliance = int((on_time_completed / period_due * 100)) if period_due > 0 else 100

    # ── Overdue tests ─────────────────────────────────────────────────────────
    overdue_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # ── K2: ALERT/CRITICAL — from TestResult.evaluation_result['overall'] ────
    critical_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'CRITICAL',
    ).scalar() or 0

    alert_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'ALERT',
    ).scalar() or 0

    alert_critical = critical_count + alert_count

    # ── K3: Open Remedial Actions with age bands (SQL-only) ──────────────────
    cutoff_7d  = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)
    cutoff_14d = now - timedelta(days=14)

    open_remediation = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
    ).scalar() or 0

    overdue_remediation = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.cts <= cutoff_14d,
    ).scalar() or 0

    age_bands = {
        '0_7':     db.query(func.count(Recommendation.id)).filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.cts > cutoff_7d,
        ).scalar() or 0,
        '8_30':    db.query(func.count(Recommendation.id)).filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.cts.between(cutoff_30d, cutoff_7d),
        ).scalar() or 0,
        '31_plus': db.query(func.count(Recommendation.id)).filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.cts < cutoff_30d,
        ).scalar() or 0,
    }

    # ── K4: TA&QC Compliance — approved/total (Phase-3 placeholder) ──────────
    total_tests_period = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.cts >= ninety_days_ago,
    ).scalar() or 0

    approved_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status == 'approved',
        TestingRequest.cts >= ninety_days_ago,
    ).scalar() or 0

    taqc_compliance = int((approved_tests / total_tests_period * 100)) if total_tests_period > 0 else 0

    # ── K6: Maintenance overdue + compliance ─────────────────────────────────
    maintenance_overdue = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    maint_period_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    maint_on_time = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    maintenance_compliance = int((maint_on_time / maint_period_due * 100)) if maint_period_due > 0 else 100

    # ── Total equipment + FR pending ─────────────────────────────────────────
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active',
    ).scalar() or 0

    fr_pending = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_(OPEN_STATUSES),
    ).scalar() or 0

    pending_approvals = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval']),
    ).scalar() or 0

    # ── Top-10 critical equipment (SRS §8.3.1) ────────────────────────────────
    top_critical_db = (
        db.query(TestResult, TestingRequest, Equipment, DeptTopSEE)
        .join(TestingRequest, TestResult.testing_request_id == TestingRequest.id)
        .join(Equipment, TestingRequest.equipment_id == Equipment.id)
        .outerjoin(DeptTopSEE, TestingRequest.department_id == DeptTopSEE.id)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestResult.evaluation_result.isnot(None),
            TestResult.evaluation_result['overall'].astext == 'CRITICAL',
        )
        .order_by(TestResult.cts.desc())
        .limit(10)
        .all()
    )

    top_critical = []
    for result, req, eq, dept_row in top_critical_db:
        flagged_fields = []
        for field in result.evaluation_result.get('fields', []):
            if field.get('status') in ['CRITICAL', 'ALERT']:
                flagged_fields.append(
                    f"{field.get('label', '')}: {field.get('value', '')}{field.get('unit', '')}"
                )
        top_critical.append({
            'id': str(result.id),
            'ueic': eq.ueic if eq else '',
            'equipment_name': eq.manufacturer or eq.ueic if eq else '',
            'test_type': req.test_type.name if req.test_type else 'Test',
            'substation': dept_row.name if dept_row else '',
            'timestamp': result.cts.strftime('%d-%b-%Y %H:%M') if result.cts else None,
            'message': ' | '.join(flagged_fields[:2]) if flagged_fields else 'CRITICAL test result',
        })

    # ── K5: Repair progress ────────────────────────────────────────────────────
    repair_progress = svc.repair_progress()

    # ── Pending reviews list ──────────────────────────────────────────────────
    pending_reviews_db = db.query(TestingRequest).options(
        joinedload(TestingRequest.test_type),
        joinedload(TestingRequest.department),
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval']),
    ).order_by(TestingRequest.cts.desc()).limit(10).all()

    pending_reviews_list = []
    for req in pending_reviews_db:
        pending_reviews_list.append({
            'id': str(req.id),
            'title': f"{req.test_type.name if req.test_type else 'Test'} - {req.department.name if req.department else 'Unknown'}",
            'status': req.status.value.replace('_', ' ').title(),
            'created': req.cts.strftime('%Y-%m-%d') if req.cts else 'N/A',
        })

    # ── Dept compliance breakdown (single GROUP BY — replaces N+1 loop) ─────
    from models import OrgDepartment as Department
    from sqlalchemy import case as sql_case
    ninety_ago_see = now - timedelta(days=90)

    dept_id_map = {
        d.id: d.name
        for d in db.query(Department.id, Department.name).filter(
            Department.organization_id == svc.org_id,
        ).limit(20).all()
    }

    grp_rows = db.query(
        TestingRequest.department_id,
        func.count(TestingRequest.id).label('total'),
        func.count(sql_case(
            (TestingRequest.status.in_(CLOSED_STATUSES), TestingRequest.id)
        )).label('done'),
        func.count(sql_case(
            (TestingRequest.due_date < now, TestingRequest.id)
        )).label('overdue'),
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_ago_see, now),
        TestingRequest.is_schedule_template.is_(False),
        TestingRequest.department_id.in_(list(dept_id_map.keys())),
    ).group_by(TestingRequest.department_id).all()

    dept_breakdown = []
    for row in grp_rows:
        name = dept_id_map.get(row.department_id, 'Unknown')
        compliance = int(row.done / row.total * 100) if row.total > 0 else 100
        dept_breakdown.append({
            'name': name,
            'compliance': compliance,
            'total': row.total,
            'overdue': row.overdue,
        })
    dept_breakdown.sort(key=lambda x: x['compliance'])

    # ── Overdue test age bands (SQL COUNT per band — no full fetch) ───────
    overdue_test_bands_see = {
        '0_7': db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date.between(cutoff_7d, now),
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0,
        '8_30': db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date.between(cutoff_30d, cutoff_7d),
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0,
        '31_plus': db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date < cutoff_30d,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0,
    }

    # ── TA&QC summary counts ──────────────────────────────────────────────
    taqc_total_see = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.cts >= ninety_ago_see,
    ).scalar() or 0
    taqc_closed_see = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status == 'approved',
        TestingRequest.cts >= ninety_ago_see,
    ).scalar() or 0
    taqc_overdue_see = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.due_date < now,
        TestingRequest.cts >= ninety_ago_see,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    taqc_summary_see = {
        'closed': taqc_closed_see,
        'open': taqc_total_see - taqc_closed_see,
        'overdue': taqc_overdue_see,
    }

    # ── Enhanced repair tracker with stage info ───────────────────────────
    from models import RepairWorkflow as RepairWFSee
    today_see = date.today()
    repair_wf_see = (
        db.query(RepairWFSee)
        .options(
            joinedload(RepairWFSee.equipment),
            joinedload(RepairWFSee.current_stage),
        )
        .filter(
            RepairWFSee.organization_id == svc.org_id,
            RepairWFSee.status == 'active',
        )
        .order_by(RepairWFSee.started_at.desc())
        .limit(15)
        .all()
    )
    repair_tracker_see = []
    for wf in repair_wf_see:
        eq = wf.equipment
        stage = wf.current_stage
        contracted = wf.contracted_completion
        is_delayed = contracted is not None and wf.completed_at is None and contracted < today_see
        delay_days = (today_see - contracted).days if is_delayed and contracted else 0
        delay_type = 'vendor' if (wf.workflow_type or '').upper() in ('BREAKDOWN', 'OVERHAUL') else 'kptcl'
        repair_tracker_see.append({
            'id': str(wf.id),
            'workflow_number': wf.workflow_number,
            'ueic': eq.ueic if eq else '',
            'equipment_name': eq.manufacturer or eq.ueic if eq else '',
            'workflow_type': wf.workflow_type or 'BREAKDOWN',
            'repairer': wf.vendor_name or 'Unassigned',
            'started_at': wf.started_at.strftime('%d-%b-%Y') if wf.started_at else None,
            'contracted_completion': contracted.strftime('%d-%b-%Y') if contracted else None,
            'progress_pct': wf.progress or 0,
            'stage_sequence': stage.sequence if stage else 0,
            'stage_name': stage.name if stage else 'Pending',
            'is_delayed': is_delayed,
            'delay_days': delay_days,
            'delay_type': delay_type if is_delayed else None,
        })

    return {
        'kpis': {
            'circle_compliance': circle_compliance,
            'overdue_tests': overdue_tests,
            'alert_critical': alert_critical,
            'alert_count': alert_count,
            'critical_count': critical_count,
            'open_remediation': open_remediation,
            'overdue_remediation': overdue_remediation,
            'maintenance_overdue': maintenance_overdue,
            'maintenance_compliance': maintenance_compliance,
            'taqc_compliance': taqc_compliance,
            'equipment_monitored': total_equipment,
            'fr_pending': fr_pending,
            'pending_approvals': pending_approvals,
        },
        'remediation_age_bands': age_bands,
        'overdue_test_bands': overdue_test_bands_see,
        'taqc_summary': taqc_summary_see,
        'top_critical_equipment': top_critical,
        'repair_progress': repair_progress,
        'repair_tracker': repair_tracker_see,
        'pending_reviews': pending_reviews_list,
        'dept_breakdown': dept_breakdown,
    }


@router.get("/cee")
def get_cee_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CEE Dashboard — Zone-level executive management.

    SRS §8.3.1: Zone compliance KPIs · top-10 critical equipment ·
                transformer repair zone progress · repair portfolio (Appendix F for CEE RT&R&D)
    SRS §8.3.2 KPIs:
    K1 zone_compliance       = on-time test completion % (90-day window)
                               [FIXED: was always 100% — identical active-equipment queries]
    K2 alert_critical        = from TestResult.evaluation_result['overall']
    K3 open_remediation      = age-banded remedial actions
    K4 taqc_compliance       = approved/total tests (Phase-3 TA&QC placeholder)
    K5 repair_progress       = from RepairWorkflow via DashboardService
    K6 maintenance_overdue   = maintenance requests past due_date
    Appendix F repair_portfolio = repairer, contracted vs actual, delay flag (CEE RT&R&D)
    """
    from models import TestingRequest, Equipment, TestResult, Recommendation, RepairWorkflow
    from models import OrgDepartment as DeptTopCEE
    from sqlalchemy import func, and_, case as sql_case_cee
    from sqlalchemy.orm import joinedload
    from datetime import datetime, timedelta, date

    svc = _svc(db, current_user, org_id, dept_id)
    now = datetime.now()
    ninety_days_ago = now - timedelta(days=90)

    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True

    # ── K1: Zone Compliance — on-time test completion (90-day window) ─────────
    # FIXED: was always 100% due to identical `Equipment.status == 'active'` queries
    period_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    on_time_completed = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    zone_compliance = int((on_time_completed / period_due * 100)) if period_due > 0 else 100

    # ── Overdue tests ─────────────────────────────────────────────────────────
    overdue_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # ── K2: ALERT/CRITICAL — from TestResult.evaluation_result['overall'] ────
    critical_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'CRITICAL',
    ).scalar() or 0

    alert_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'ALERT',
    ).scalar() or 0

    alert_critical = critical_count + alert_count

    # ── K3: Open Remedial Actions with age bands (SQL-only, no full fetch) ──────
    cutoff_7d  = now - timedelta(days=7)
    cutoff_30d = now - timedelta(days=30)
    cutoff_14d = now - timedelta(days=14)

    open_remediation = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
    ).scalar() or 0

    overdue_remediation = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.cts <= cutoff_14d,
    ).scalar() or 0

    age_bands = {
        '0_7':     db.query(func.count(Recommendation.id)).filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.cts > cutoff_7d,
        ).scalar() or 0,
        '8_30':    db.query(func.count(Recommendation.id)).filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.cts.between(cutoff_30d, cutoff_7d),
        ).scalar() or 0,
        '31_plus': db.query(func.count(Recommendation.id)).filter(
            Recommendation.organization_id == svc.org_id,
            Recommendation.approval_status == 'pending',
            Recommendation.cts < cutoff_30d,
        ).scalar() or 0,
    }

    # ── K4: TA&QC Compliance — approved/total (Phase-3 placeholder) ──────────
    total_tests_period = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.cts >= ninety_days_ago,
    ).scalar() or 0

    approved_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status == 'approved',
        TestingRequest.cts >= ninety_days_ago,
    ).scalar() or 0

    taqc_compliance = int((approved_tests / total_tests_period * 100)) if total_tests_period > 0 else 0

    # ── K6: Maintenance overdue + compliance ─────────────────────────────────
    maintenance_overdue = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    maint_period_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    maint_on_time = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    maintenance_compliance = int((maint_on_time / maint_period_due * 100)) if maint_period_due > 0 else 100

    # ── Zone equipment total + fr_pending + pending_approvals ─────────────────
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active',
    ).scalar() or 0

    fr_pending = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_(OPEN_STATUSES),
    ).scalar() or 0

    pending_approvals = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.status.in_(['submitted', 'pending_approval']),
    ).scalar() or 0

    # ── Top-10 critical equipment (SRS §8.3.1) ────────────────────────────────
    top_critical_db = (
        db.query(TestResult, TestingRequest, Equipment, DeptTopCEE)
        .join(TestingRequest, TestResult.testing_request_id == TestingRequest.id)
        .join(Equipment, TestingRequest.equipment_id == Equipment.id)
        .outerjoin(DeptTopCEE, TestingRequest.department_id == DeptTopCEE.id)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestResult.evaluation_result.isnot(None),
            TestResult.evaluation_result['overall'].astext == 'CRITICAL',
        )
        .order_by(TestResult.cts.desc())
        .limit(10)
        .all()
    )

    top_critical = []
    for result, req, eq, dept_row in top_critical_db:
        flagged_fields = []
        for field in result.evaluation_result.get('fields', []):
            if field.get('status') in ['CRITICAL', 'ALERT']:
                flagged_fields.append(
                    f"{field.get('label', '')}: {field.get('value', '')}{field.get('unit', '')}"
                )
        top_critical.append({
            'id': str(result.id),
            'ueic': eq.ueic if eq else '',
            'equipment_name': eq.manufacturer or eq.ueic if eq else '',
            'test_type': req.test_type.name if req.test_type else 'Test',
            'substation': dept_row.name if dept_row else '',
            'timestamp': result.cts.strftime('%d-%b-%Y %H:%M') if result.cts else None,
            'message': ' | '.join(flagged_fields[:2]) if flagged_fields else 'CRITICAL test result',
        })

    # ── K5: Repair progress ────────────────────────────────────────────────────
    repair_progress = svc.repair_progress()

    # ── Repair Portfolio (SRS Appendix F — CEE RT&R&D view) ───────────────────
    # RepairWorkflow fields: vendor_name, contracted_completion (Date),
    #                        completed_at (DateTime), progress (int 0-100)
    today = date.today()
    repair_wf_rows = (
        db.query(RepairWorkflow)
        .options(
            joinedload(RepairWorkflow.equipment),
            joinedload(RepairWorkflow.current_stage),
        )
        .filter(
            RepairWorkflow.organization_id == svc.org_id,
            RepairWorkflow.status == 'active',
        )
        .order_by(RepairWorkflow.started_at.desc())
        .limit(20)
        .all()
    )

    repair_portfolio = []
    for wf in repair_wf_rows:
        eq = wf.equipment
        contracted = wf.contracted_completion  # Date or None
        is_delayed = (
            contracted is not None
            and wf.completed_at is None
            and contracted < today
        )
        delay_days = (today - contracted).days if is_delayed and contracted else 0
        repair_portfolio.append({
            'id': str(wf.id),
            'ueic': eq.ueic if eq else '',
            'equipment_name': eq.manufacturer or eq.ueic if eq else '',
            'repairer': wf.vendor_name or 'Unassigned',
            'contracted_completion': contracted.strftime('%d-%b-%Y') if contracted else None,
            'actual_completion': wf.completed_at.strftime('%d-%b-%Y') if wf.completed_at else None,
            'progress_pct': wf.progress or 0,
            'is_delayed': is_delayed,
            'delay_days': delay_days,
            'workflow_type': wf.workflow_type or 'BREAKDOWN',
        })

    # ── Escalated failure reports — pending CEE sanction ─────────────────
    from models import TestingRequestStatus as TRSCEE
    escalated_frs_db = db.query(TestingRequest).options(
        joinedload(TestingRequest.department),
        joinedload(TestingRequest.equipment),
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_([TRSCEE.under_approval, TRSCEE.under_review, TRSCEE.approved]),
    ).order_by(TestingRequest.cts.desc()).limit(10).all()

    escalated_fr_list = []
    for req in escalated_frs_db:
        escalated_fr_list.append({
            'id': str(req.id),
            'title': req.title or req.request_number or 'Failure Report',
            'substation': req.department.name if req.department else '',
            'ueic': req.equipment.ueic if req.equipment else '',
            'status': (req.status.value if hasattr(req.status, 'value') else str(req.status)).replace('_', ' ').title(),
            'created': req.cts.strftime('%d-%b-%Y') if req.cts else '',
        })

    # ── Dept compliance breakdown (single GROUP BY — replaces N+1 loop) ─────
    from models import OrgDepartment as DeptCEE
    ninety_ago_cee = now - timedelta(days=90)

    cee_dept_id_map = {
        d.id: d.name
        for d in db.query(DeptCEE.id, DeptCEE.name).filter(
            DeptCEE.organization_id == svc.org_id,
        ).limit(25).all()
    }

    cee_grp_rows = db.query(
        TestingRequest.department_id,
        func.count(TestingRequest.id).label('total'),
        func.count(sql_case_cee(
            (TestingRequest.status.in_(CLOSED_STATUSES), TestingRequest.id)
        )).label('done'),
        func.count(sql_case_cee(
            (TestingRequest.due_date < now, TestingRequest.id)
        )).label('overdue'),
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_ago_cee, now),
        TestingRequest.is_schedule_template.is_(False),
        TestingRequest.department_id.in_(list(cee_dept_id_map.keys())),
    ).group_by(TestingRequest.department_id).all()

    cee_dept_breakdown = []
    for row in cee_grp_rows:
        name = cee_dept_id_map.get(row.department_id, 'Unknown')
        d_compliance = int(row.done / row.total * 100) if row.total > 0 else 100
        cee_dept_breakdown.append({
            'name': name,
            'compliance': d_compliance,
            'total': row.total,
            'overdue': row.overdue,
        })
    cee_dept_breakdown.sort(key=lambda x: x['compliance'])

    # ── Overdue test age bands (SQL COUNT per band — no full fetch) ───────
    overdue_test_bands = {
        '0_7': db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date.between(cutoff_7d, now),
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0,
        '8_30': db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date.between(cutoff_30d, cutoff_7d),
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0,
        '31_plus': db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.request_category == RequestCategory.test,
            TestingRequest.due_date < cutoff_30d,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0,
    }

    # ── TA&QC summary counts (SRS §6.1) ──────────────────────────────────
    taqc_total = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.cts >= ninety_days_ago,
    ).scalar() or 0
    taqc_closed = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status == 'approved',
        TestingRequest.cts >= ninety_days_ago,
    ).scalar() or 0
    taqc_overdue = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.due_date < now,
        TestingRequest.cts >= ninety_days_ago,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0
    taqc_summary = {
        'closed': taqc_closed,
        'open': taqc_total - taqc_closed,
        'overdue': taqc_overdue,
    }

    # ── Maintenance compliance by dept (single GROUP BY) ─────────────────
    maint_grp_rows = db.query(
        TestingRequest.department_id,
        func.count(TestingRequest.id).label('total'),
        func.count(sql_case_cee(
            (TestingRequest.status.in_(CLOSED_STATUSES), TestingRequest.id)
        )).label('done'),
        func.count(sql_case_cee(
            (TestingRequest.due_date < now, TestingRequest.id)
        )).label('overdue'),
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date.between(ninety_ago_cee, now),
        TestingRequest.is_schedule_template.is_(False),
        TestingRequest.department_id.in_(list(cee_dept_id_map.keys())),
    ).group_by(TestingRequest.department_id).all()

    maint_by_dept = []
    for row in maint_grp_rows:
        name = cee_dept_id_map.get(row.department_id, 'Unknown')
        md_compliance = int(row.done / row.total * 100) if row.total > 0 else 100
        maint_by_dept.append({
            'name': name,
            'compliance': md_compliance,
            'total': row.total,
            'done': row.done,
            'overdue': row.overdue,
        })
    maint_by_dept.sort(key=lambda x: x['compliance'])

    # ── Enhanced repair tracker — stage number, stage name, delay attribution ─
    repair_tracker = []
    for wf in repair_wf_rows:
        eq = wf.equipment
        stage = wf.current_stage  # RepairStageDefinition (sequence, name)
        contracted = wf.contracted_completion
        is_delayed = (
            contracted is not None
            and wf.completed_at is None
            and contracted < today
        )
        delay_days_rt = (today - contracted).days if is_delayed and contracted else 0
        # Attribute delay type: BREAKDOWN workflows → likely vendor; others → KPTCL
        delay_type = 'vendor' if (wf.workflow_type or '').upper() in ('BREAKDOWN', 'OVERHAUL') else 'kptcl'
        repair_tracker.append({
            'id': str(wf.id),
            'workflow_number': wf.workflow_number,
            'ueic': eq.ueic if eq else '',
            'equipment_name': eq.manufacturer or eq.ueic if eq else '',
            'workflow_type': wf.workflow_type or 'BREAKDOWN',
            'repairer': wf.vendor_name or 'Unassigned',
            'started_at': wf.started_at.strftime('%d-%b-%Y') if wf.started_at else None,
            'contracted_completion': contracted.strftime('%d-%b-%Y') if contracted else None,
            'progress_pct': wf.progress or 0,
            'stage_sequence': stage.sequence if stage else 0,
            'stage_name': stage.name if stage else 'Pending',
            'is_delayed': is_delayed,
            'delay_days': delay_days_rt,
            'delay_type': delay_type if is_delayed else None,
        })

    # ── Procurement pipeline — stage breakdown + trigger source ──────────
    from models import ProcurementRequest
    proc_status_map = {
        'initiated': 0,
        'awaiting_approval': 0,
        'rfq_issued': 0,
        'comparative_review': 0,
        'po_issued': 0,
        'inspection': 0,
        'closed': 0,
    }
    proc_status_rows = db.query(
        ProcurementRequest.status,
        func.count(ProcurementRequest.id).label('cnt'),
    ).filter(
        ProcurementRequest.organization_id == svc.org_id,
    ).group_by(ProcurementRequest.status).all()
    for pr in proc_status_rows:
        s = (pr.status or 'initiated').lower()
        if s in proc_status_map:
            proc_status_map[s] += int(pr.cnt)
        else:
            proc_status_map['initiated'] += int(pr.cnt)

    # Oldest open procurement
    oldest_open_pr = db.query(func.min(ProcurementRequest.raised_at)).filter(
        ProcurementRequest.organization_id == svc.org_id,
        ProcurementRequest.status.notin_(['closed']),
    ).scalar()
    oldest_open_days = (now - oldest_open_pr.replace(tzinfo=None)).days if oldest_open_pr else 0

    procurement_pipeline = {
        'stages': proc_status_map,
        'total_active': sum(v for k, v in proc_status_map.items() if k != 'closed'),
        'oldest_open_days': oldest_open_days,
    }

    return {
        'kpis': {
            'zone_compliance': zone_compliance,
            'zone_equipment': total_equipment,
            'overdue_tests': overdue_tests,
            'alert_critical': alert_critical,
            'alert_count': alert_count,
            'critical_count': critical_count,
            'open_remediation': open_remediation,
            'overdue_remediation': overdue_remediation,
            'maintenance_overdue': maintenance_overdue,
            'maintenance_compliance': maintenance_compliance,
            'taqc_compliance': taqc_compliance,
            'fr_pending': fr_pending,
            'pending_approvals': pending_approvals,
        },
        'remediation_age_bands': age_bands,
        'overdue_test_bands': overdue_test_bands,
        'taqc_summary': taqc_summary,
        'top_critical_equipment': top_critical,
        'repair_progress': repair_progress,
        'repair_portfolio': repair_portfolio,
        'repair_tracker': repair_tracker,
        'maint_by_dept': maint_by_dept,
        'procurement_pipeline': procurement_pipeline,
        'escalated_frs': escalated_fr_list,
        'dept_breakdown': cee_dept_breakdown,
    }
@router.get("/ee-rt")
def get_ee_rt_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """EE RT Dashboard — Department-level relay testing & calibration oversight.

    RT Track (parallel to O&M EE TLSS):
    K1 calibration_compliance  = calibration requests completed on-time % (90-day)
    K2 overdue_calibrations    = calibration requests past due_date (open)
    K3 expiring_soon           = calibration requests due in next 30 days
    K4 fail_count              = calibration requests with result FAIL/failed
    K5 open_cal_workflows      = open calibration repair/workflow records
    K6 relay_test_compliance   = relay/RT test requests completed on-time %
    """
    from models import TestingRequest, Equipment
    from sqlalchemy import func
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id, dept_id)
    now = datetime.now()
    ninety_days_ago = now - timedelta(days=90)
    thirty_days_ahead = now + timedelta(days=30)

    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True

    # ── K1: Calibration compliance (on-time %) ────────────────────────────────
    cal_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    cal_on_time = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    calibration_compliance = int((cal_on_time / cal_due * 100)) if cal_due > 0 else 100

    # ── K2: Overdue calibrations ──────────────────────────────────────────────
    overdue_calibrations = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # ── K3: Expiring soon (due in next 30 days) ───────────────────────────────
    expiring_soon = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(now, thirty_days_ahead),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # ── K4: FAIL calibrations ─────────────────────────────────────────────────
    fail_count = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.status == 'rejected',
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # ── K5: Open calibration workflows ───────────────────────────────────────
    from models import CalibrationRepairRecommendation, Equipment as Equip
    open_cal_workflows = db.query(func.count(CalibrationRepairRecommendation.id)).join(
        Equip, CalibrationRepairRecommendation.equipment_id == Equip.id
    ).filter(
        Equip.organization_id == svc.org_id,
        CalibrationRepairRecommendation.status == 'OPEN',
    ).scalar() or 0

    # ── K6: Relay test compliance (non-calibration RT tests) ─────────────────
    rt_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(False),
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    rt_on_time = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(False),
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    relay_test_compliance = int((rt_on_time / rt_due * 100)) if rt_due > 0 else 100

    # ── Total relay assets in dept scope ─────────────────────────────────
    from models import Equipment as EqRT
    dept_cond_eq_rt = (EqRT.department_id.in_(svc.dept_ids)) if svc.dept_ids else True
    total_relay_assets_ee = db.query(func.count(EqRT.id)).filter(
        EqRT.organization_id == svc.org_id,
        dept_cond_eq_rt,
        EqRT.status == 'active',
    ).scalar() or 0

    # ── Pending calibration list ──────────────────────────────────────────────
    pending_cals = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).order_by(TestingRequest.due_date.asc()).limit(10).all()

    pending_cal_list = [{
        'id': str(r.id),
        'ueic': r.equipment.ueic if r.equipment else '',
        'substation': r.department.name if r.department else '',
        'due_date': r.due_date.strftime('%Y-%m-%d') if r.due_date else 'N/A',
        'status': (r.status or '').replace('_', ' ').title(),
    } for r in pending_cals]

    # ── Overdue calibration escalations list ─────────────────────────────
    overdue_cal_reqs = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).order_by(TestingRequest.due_date.asc()).limit(15).all()

    overdue_cal_escalations = []
    for r in overdue_cal_reqs:
        days_ov = (now.date() - r.due_date.date()).days if r.due_date else 0
        priority = 'high' if days_ov >= 30 else ('medium' if days_ov >= 7 else 'low')
        overdue_cal_escalations.append({
            'id': str(r.id),
            'ueic': r.equipment.ueic if r.equipment else '',
            'substation': r.department.name if r.department else '',
            'test_type': r.test_type.name if r.test_type else 'Calibration',
            'days_overdue': days_ov,
            'priority': priority,
        })

    # ── Expiring calibrations (next 30 days) ─────────────────────────────
    expiring_cal_list = []
    expiring_reqs = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(now, thirty_days_ahead),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).order_by(TestingRequest.due_date.asc()).limit(10).all()

    for r in expiring_reqs:
        days_left = (r.due_date.date() - now.date()).days if r.due_date else 0
        expiring_cal_list.append({
            'id': str(r.id),
            'ueic': r.equipment.ueic if r.equipment else '',
            'substation': r.department.name if r.department else '',
            'due_date': r.due_date.strftime('%d-%b-%Y') if r.due_date else '',
            'days_left': days_left,
        })

    # ── 6-month pass/fail calibration trend ──────────────────────────────
    fail_trend_ee = []
    for months_back in range(5, -1, -1):
        period_start = now - timedelta(days=30 * (months_back + 1))
        period_end   = now - timedelta(days=30 * months_back)
        m_total = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.is_calibration.is_(True),
            TestingRequest.completed_at.between(period_start, period_end),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        m_fail = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.is_calibration.is_(True),
            TestingRequest.completed_at.between(period_start, period_end),
            TestingRequest.status == 'rejected',
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        m_pass = m_total - m_fail
        pass_rate = int((m_pass / m_total * 100)) if m_total > 0 else 100
        fail_trend_ee.append({
            'month': period_end.strftime('%b %Y'),
            'total': m_total,
            'pass': m_pass,
            'fail': m_fail,
            'pass_rate': pass_rate,
        })

    # ── Calibration compliance by substation ─────────────────────────────
    from models import OrgDepartment as DeptEeRt
    depts_ee_rt = db.query(DeptEeRt).filter(
        DeptEeRt.organization_id == svc.org_id,
    ).limit(12).all()
    substation_compliance = []
    for dept in depts_ee_rt:
        d_due = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            TestingRequest.department_id == dept.id,
            TestingRequest.is_calibration.is_(True),
            TestingRequest.due_date.between(ninety_days_ago, now),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        d_done = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            TestingRequest.department_id == dept.id,
            TestingRequest.is_calibration.is_(True),
            TestingRequest.due_date.between(ninety_days_ago, now),
            TestingRequest.status.in_(CLOSED_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        d_overdue = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            TestingRequest.department_id == dept.id,
            TestingRequest.is_calibration.is_(True),
            TestingRequest.due_date < now,
            TestingRequest.status.in_(OPEN_STATUSES),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        d_comp = int(d_done / d_due * 100) if d_due > 0 else 100
        substation_compliance.append({
            'name': dept.name,
            'compliance': d_comp,
            'total': d_due,
            'overdue': d_overdue,
        })
    substation_compliance.sort(key=lambda x: x['compliance'])

    return {
        'kpis': {
            'calibration_compliance': calibration_compliance,
            'overdue_calibrations': overdue_calibrations,
            'expiring_soon': expiring_soon,
            'fail_count': fail_count,
            'open_cal_workflows': open_cal_workflows,
            'relay_test_compliance': relay_test_compliance,
            'total_relay_assets': total_relay_assets_ee,
            'cal_due_period': cal_due,
            'rt_due_period': rt_due,
        },
        'pending_calibrations': pending_cal_list,
        'overdue_cal_escalations': overdue_cal_escalations,
        'expiring_cal_list': expiring_cal_list,
        'fail_trend': fail_trend_ee,
        'substation_compliance': substation_compliance,
    }


@router.get("/see-rt")
def get_see_rt_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SEE RT Dashboard — Circle-level relay testing & calibration supervision.

    K1 circle_cal_compliance   = circle-wide calibration on-time %
    K2 overdue_calibrations    = overdue calibrations in circle
    K3 expiring_soon           = due in next 30 days (circle)
    K4 fail_count              = FAIL/rejected calibrations
    K5 open_cal_workflows      = open calibration repair workflows
    K6 relay_test_compliance   = relay test on-time % (circle)
    """
    from models import TestingRequest
    from sqlalchemy import func
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id, dept_id)
    now = datetime.now()
    ninety_days_ago = now - timedelta(days=90)
    thirty_days_ahead = now + timedelta(days=30)

    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True

    cal_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    cal_on_time = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    circle_cal_compliance = int((cal_on_time / cal_due * 100)) if cal_due > 0 else 100

    overdue_calibrations = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    expiring_soon = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(now, thirty_days_ahead),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    from models import TestingRequestStatus as TRSSEE2
    fail_count = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.status == TRSSEE2.rejected,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    from models import CalibrationRepairRecommendation, Equipment as Equip2
    open_cal_workflows = db.query(func.count(CalibrationRepairRecommendation.id)).join(
        Equip2, CalibrationRepairRecommendation.equipment_id == Equip2.id
    ).filter(
        Equip2.organization_id == svc.org_id,
        CalibrationRepairRecommendation.status == 'OPEN',
    ).scalar() or 0

    rt_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(False),
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    rt_on_time = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(False),
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    relay_test_compliance = int((rt_on_time / rt_due * 100)) if rt_due > 0 else 100

    # ── Calibrations pending SEE RT approval (test_submitted / under_approval) ─
    from models import TestingRequestStatus as TRSSEE
    pending_approval_count = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.status.in_([TRSSEE.test_submitted, TRSSEE.under_approval]),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # ── Dept RT compliance breakdown (single GROUP BY — replaces N+1 loop) ─
    from models import OrgDepartment as DeptSEERT
    from sqlalchemy import case as sql_case_seert
    ninety_ago_see_rt = now - timedelta(days=90)

    seert_dept_map = {
        d.id: d.name
        for d in db.query(DeptSEERT.id, DeptSEERT.name).filter(
            DeptSEERT.organization_id == svc.org_id,
        ).limit(20).all()
    }

    seert_grp = db.query(
        TestingRequest.department_id,
        func.count(TestingRequest.id).label('total'),
        func.count(sql_case_seert(
            (TestingRequest.status.in_(CLOSED_STATUSES), TestingRequest.id)
        )).label('done'),
        func.count(sql_case_seert(
            (TestingRequest.due_date < now, TestingRequest.id)
        )).label('overdue'),
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(ninety_ago_see_rt, now),
        TestingRequest.is_schedule_template.is_(False),
        TestingRequest.department_id.in_(list(seert_dept_map.keys())),
    ).group_by(TestingRequest.department_id).all()

    dept_rt_breakdown = []
    for row in seert_grp:
        dr_compliance = int(row.done / row.total * 100) if row.total > 0 else 100
        dept_rt_breakdown.append({
            'name': seert_dept_map.get(row.department_id, 'Unknown'),
            'compliance': dr_compliance,
            'total': row.total,
            'overdue': row.overdue,
        })
    dept_rt_breakdown.sort(key=lambda x: x['compliance'])

    # ── Overdue calibration escalations ──────────────────────────────────
    overdue_cal_see_rt = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).order_by(TestingRequest.due_date.asc()).limit(10).all()

    overdue_cal_list_see = []
    for req in overdue_cal_see_rt:
        days_ov = (now.date() - req.due_date.date()).days if req.due_date else 0
        overdue_cal_list_see.append({
            'id': str(req.id),
            'request_number': req.request_number or '',
            'ueic': req.equipment.ueic if req.equipment else '',
            'equipment_name': req.equipment.manufacturer or req.equipment.ueic if req.equipment else '',
            'substation': req.department.name if req.department else '',
            'due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else '',
            'days_overdue': days_ov,
            'priority': 'critical' if days_ov > 30 else ('high' if days_ov > 14 else 'medium'),
        })

    # ── Expiring calibrations — next 30 days ─────────────────────────────
    expiring_cal_see = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(now, now + timedelta(days=30)),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).order_by(TestingRequest.due_date.asc()).limit(10).all()

    expiring_cal_list_see = []
    for req in expiring_cal_see:
        days_until = (req.due_date.date() - now.date()).days if req.due_date else 0
        expiring_cal_list_see.append({
            'id': str(req.id),
            'request_number': req.request_number or '',
            'ueic': req.equipment.ueic if req.equipment else '',
            'equipment_name': req.equipment.manufacturer or req.equipment.ueic if req.equipment else '',
            'substation': req.department.name if req.department else '',
            'due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else '',
            'days_until_due': days_until,
        })

    # ── 6-month fail trend ────────────────────────────────────────────────
    from models import TestingRequestStatus as TRS_SEE_RT
    fail_trend_see = []
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1) if i > 0 else now
        m_total = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.is_calibration.is_(True),
            TestingRequest.status.in_(CLOSED_STATUSES),
            TestingRequest.completed_at.between(month_start, month_end),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        m_fail = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.is_calibration.is_(True),
            TestingRequest.status == TRS_SEE_RT.rejected,
            TestingRequest.completed_at.between(month_start, month_end),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        fail_trend_see.append({
            'month': month_start.strftime('%b %Y'),
            'total': m_total,
            'pass': m_total - m_fail,
            'fail': m_fail,
            'pass_rate': int((m_total - m_fail) / m_total * 100) if m_total > 0 else 100,
        })

    return {
        'kpis': {
            'circle_cal_compliance': circle_cal_compliance,
            'overdue_calibrations': overdue_calibrations,
            'expiring_soon': expiring_soon,
            'fail_count': fail_count,
            'open_cal_workflows': open_cal_workflows,
            'relay_test_compliance': relay_test_compliance,
            'pending_approval_count': pending_approval_count,
            'cal_due_period': cal_due,
        },
        'dept_rt_breakdown': dept_rt_breakdown,
        'overdue_cal_escalations': overdue_cal_list_see,
        'expiring_cal_list': expiring_cal_list_see,
        'fail_trend': fail_trend_see,
    }


@router.get("/cee-rt-rd")
def get_cee_rt_rd_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CEE RT RD Dashboard — Zone-level R&D governance & calibration executive view.

    K1 zone_cal_compliance     = zone-wide calibration on-time %
    K2 total_relay_assets      = active equipment count in zone
    K3 open_cal_workflows      = open calibration repair workflows (zone)
    K4 fail_count              = FAIL calibrations zone-wide
    K5 expiring_soon           = calibrations due in next 30 days
    K6 relay_test_compliance   = relay test on-time % (zone)
    """
    from models import TestingRequest, Equipment
    from sqlalchemy import func
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id, dept_id)
    now = datetime.now()
    ninety_days_ago = now - timedelta(days=90)
    thirty_days_ahead = now + timedelta(days=30)

    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True

    cal_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    cal_on_time = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    zone_cal_compliance = int((cal_on_time / cal_due * 100)) if cal_due > 0 else 100

    total_relay_assets = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active',
    ).scalar() or 0

    from models import CalibrationRepairRecommendation, Equipment as Equip3
    open_cal_workflows = db.query(func.count(CalibrationRepairRecommendation.id)).join(
        Equip3, CalibrationRepairRecommendation.equipment_id == Equip3.id
    ).filter(
        Equip3.organization_id == svc.org_id,
        CalibrationRepairRecommendation.status == 'OPEN',
    ).scalar() or 0

    from models import TestingRequestStatus as TRSCEE2
    fail_count = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.status == TRSCEE2.rejected,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    expiring_soon = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(now, thirty_days_ahead),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    rt_due = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(False),
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    rt_on_time = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(False),
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.status.in_(CLOSED_STATUSES),
        TestingRequest.completed_at <= TestingRequest.due_date,
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    relay_test_compliance = int((rt_on_time / rt_due * 100)) if rt_due > 0 else 100

    # ── Zone-wide overdue calibrations ────────────────────────────────────
    overdue_calibrations_zone = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # ── Zone calibration breakdown by dept (single GROUP BY) ─────────────
    from models import OrgDepartment as DeptCEERT
    from sqlalchemy import case as sql_case_ceert

    ceert_dept_map = {
        d.id: d.name
        for d in db.query(DeptCEERT.id, DeptCEERT.name).filter(
            DeptCEERT.organization_id == svc.org_id,
        ).limit(25).all()
    }

    ceert_grp = db.query(
        TestingRequest.department_id,
        func.count(TestingRequest.id).label('total'),
        func.count(sql_case_ceert(
            (TestingRequest.status.in_(CLOSED_STATUSES), TestingRequest.id)
        )).label('done'),
        func.count(sql_case_ceert(
            (TestingRequest.due_date < now, TestingRequest.id)
        )).label('overdue'),
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(ninety_days_ago, now),
        TestingRequest.is_schedule_template.is_(False),
        TestingRequest.department_id.in_(list(ceert_dept_map.keys())),
    ).group_by(TestingRequest.department_id).all()

    zone_breakdown = []
    for row in ceert_grp:
        zd_compliance = int(row.done / row.total * 100) if row.total > 0 else 100
        zone_breakdown.append({
            'name': ceert_dept_map.get(row.department_id, 'Unknown'),
            'compliance': zd_compliance,
            'total': row.total,
            'overdue': row.overdue,
        })
    zone_breakdown.sort(key=lambda x: x['compliance'])

    # ── Overdue calibration escalations — top 10 most overdue (SRS §5.3) ─
    from models import Equipment as EqCEERT2
    overdue_cal_db = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).order_by(TestingRequest.due_date.asc()).limit(10).all()

    overdue_cal_escalations = []
    for req in overdue_cal_db:
        days_overdue = (now.date() - req.due_date.date()).days if req.due_date else 0
        overdue_cal_escalations.append({
            'id': str(req.id),
            'request_number': req.request_number or '',
            'ueic': req.equipment.ueic if req.equipment else '',
            'equipment_name': req.equipment.manufacturer or req.equipment.ueic if req.equipment else '',
            'substation': req.department.name if req.department else '',
            'due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else '',
            'days_overdue': days_overdue,
            'priority': 'critical' if days_overdue > 30 else ('high' if days_overdue > 14 else 'medium'),
        })

    # ── Expiring calibrations list — due in next 30 days (SRS §5.3) ──────
    expiring_cal_db = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(now, now + timedelta(days=30)),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).order_by(TestingRequest.due_date.asc()).limit(10).all()

    expiring_cal_list = []
    for req in expiring_cal_db:
        days_until = (req.due_date.date() - now.date()).days if req.due_date else 0
        expiring_cal_list.append({
            'id': str(req.id),
            'request_number': req.request_number or '',
            'ueic': req.equipment.ueic if req.equipment else '',
            'equipment_name': req.equipment.manufacturer or req.equipment.ueic if req.equipment else '',
            'substation': req.department.name if req.department else '',
            'due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else '',
            'days_until_due': days_until,
        })

    # ── Monthly fail trend — last 6 months (SRS §5.3 trend tracking) ─────
    from sqlalchemy import extract, case
    fail_trend = []
    for i in range(5, -1, -1):
        month_start = (now.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        if i > 0:
            month_end = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            month_end = now
        m_total = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            TestingRequest.is_calibration.is_(True),
            TestingRequest.status.in_(CLOSED_STATUSES),
            TestingRequest.completed_at.between(month_start, month_end),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        from models import TestingRequestStatus as TRS_TREND
        m_fail = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            TestingRequest.is_calibration.is_(True),
            TestingRequest.status == TRS_TREND.rejected,
            TestingRequest.completed_at.between(month_start, month_end),
            TestingRequest.is_schedule_template.is_(False),
        ).scalar() or 0
        fail_trend.append({
            'month': month_start.strftime('%b %Y'),
            'total': m_total,
            'pass': m_total - m_fail,
            'fail': m_fail,
            'pass_rate': int((m_total - m_fail) / m_total * 100) if m_total > 0 else 100,
        })

    return {
        'kpis': {
            'zone_cal_compliance': zone_cal_compliance,
            'total_relay_assets': total_relay_assets,
            'open_cal_workflows': open_cal_workflows,
            'fail_count': fail_count,
            'expiring_soon': expiring_soon,
            'relay_test_compliance': relay_test_compliance,
            'overdue_calibrations': overdue_calibrations_zone,
            'cal_due_period': cal_due,
        },
        'zone_breakdown': zone_breakdown,
        'overdue_cal_escalations': overdue_cal_escalations,
        'expiring_cal_list': expiring_cal_list,
        'fail_trend': fail_trend,
    }


@router.get("/test-coordinator")
def get_test_coordinator_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Test Coordinator Dashboard — Condition monitoring & test evaluation oversight.
    
    Based on SEACMS-AI SRS v2.0:
    - Sec 5.1: Test Schedule Management
    - Sec 5.2: Test Result Entry and Evaluation  
    - Sec 5.2.2: Automated Result Evaluation (NORMAL/ALERT/CRITICAL)
    - Sec 5.2.3: Trend Analysis and Curve Overlaying
    - Sec 5.2.4: Remedial Action Compliance Workflow
    - Sec 5.1.3: Alert and Escalation for Due / Overdue Tests
    - Sec 8.3.1: EE TLSS / Test Coordinator Dashboard Views
    
    Visible to: EE TLSS, Test Coordinator, Reviewing Officer roles
    """
    from models import TestingRequest, Equipment, TestSession, TestResult, CategoryDetails, Recommendation
    from sqlalchemy import func, and_, extract
    from datetime import datetime, timedelta
    
    svc = _svc(db, current_user, org_id, dept_id)
    
    # Date boundaries
    now = datetime.now(timezone.utc)
    ninety_days_ago = now - timedelta(days=90)
    thirty_days_ago = now - timedelta(days=30)
    
    # Department filter for queries
    dept_cond = (TestingRequest.department_id.in_(svc.dept_ids)) if svc.dept_ids else True
    
    # =========================================================================
    # 1. KPI Cards (6 cards as per SRS Sec 8.3.2)
    # =========================================================================
    
    # Total active equipment
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.status == 'active'
    ).scalar() or 0
    
    # Test Compliance Rate (%)
    tested_equipment = db.query(func.count(func.distinct(TestingRequest.equipment_id))).join(
        TestSession, TestSession.testing_request_id == TestingRequest.id
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.equipment_id.isnot(None),
        TestSession.session_date >= ninety_days_ago
    ).scalar() or 0
    test_compliance = int((tested_equipment / total_equipment * 100)) if total_equipment > 0 else 0
    
    # Overdue Tests
    overdue_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.due_date < now,
        TestingRequest.is_schedule_template.is_(False)
    ).scalar() or 0
    
    # ALERT/CRITICAL Equipment (from latest test results)
    critical_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'CRITICAL'
    ).scalar() or 0
    
    alert_count = db.query(func.count(func.distinct(TestResult.testing_request_id))).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'ALERT'
    ).scalar() or 0
    
    alert_critical_total = critical_count + alert_count
    
    # Open Remedial Actions
    open_remediation = db.query(func.count(func.distinct(Recommendation.testing_request_id))).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.testing_request_id.in_(
            db.query(TestingRequest.id).filter(
                TestingRequest.organization_id == svc.org_id,
                dept_cond,
                TestingRequest.status != 'completed'
            )
        )
    ).scalar() or 0
    
    # Remedial actions overdue (>14 days old)
    overdue_remediation = db.query(func.count(Recommendation.id)).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending',
        Recommendation.cts < (now - timedelta(days=14))
    ).scalar() or 0
    
    # Maintenance Compliance
    maintenance_compliant = db.query(func.count(func.distinct(TestingRequest.equipment_id))).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.equipment_id.isnot(None),
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.completed_at >= ninety_days_ago
    ).scalar() or 0
    maintenance_compliance = int((maintenance_compliant / total_equipment * 100)) if total_equipment > 0 else 0
    
    # TA&QC Compliance
    total_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0
    approved_tests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.status == 'approved',
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0
    taqc_compliance = int((approved_tests / total_tests * 100)) if total_tests > 0 else 0
    
    # =========================================================================
    # 2. Test Compliance by Type (SRS Sec 5.1.1)
    # =========================================================================
    
    test_compliance_by_type = []
    test_types = db.query(CategoryDetails).filter(CategoryDetails.is_active.is_(True)).all()
    
    for tt in test_types:
        # Total equipment that should have this test
        total_for_type = db.query(func.count(func.distinct(TestingRequest.equipment_id))).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.test_type_id == tt.id,
            TestingRequest.equipment_id.isnot(None),
            TestingRequest.is_schedule_template.is_(False)
        ).scalar() or 0
        
        # Equipment that completed this test in last 90 days
        completed_for_type = db.query(func.count(func.distinct(TestingRequest.equipment_id))).join(
            TestSession, TestSession.testing_request_id == TestingRequest.id
        ).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.test_type_id == tt.id,
            TestingRequest.equipment_id.isnot(None),
            TestSession.session_date >= ninety_days_ago
        ).scalar() or 0
        
        percentage = int((completed_for_type / total_for_type * 100)) if total_for_type > 0 else 0
        
        # Color based on percentage
        if percentage >= 80:
            color = '#16A34A'  # green
        elif percentage >= 60:
            color = '#D97706'  # orange
        else:
            color = '#DC2626'  # red
            
        test_compliance_by_type.append({
            'test_type': tt.name,
            'percentage': percentage,
            'color': color,
            'total_equipment': total_for_type,
            'completed': completed_for_type
        })
    
    # =========================================================================
    # 3. Equipment Health Summary (flagged equipment)
    # =========================================================================
    
    # Get latest test result for each equipment
    latest_results = db.query(
        TestResult.testing_request_id,
        func.max(TestResult.cts).label('latest_date')
    ).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None)
    ).group_by(TestResult.testing_request_id).subquery()
    
    flagged_counts = db.query(
        TestResult.evaluation_result['overall'].astext.label('classification'),
        func.count(func.distinct(TestResult.testing_request_id)).label('count')
    ).join(
        latest_results,
        and_(
            TestResult.testing_request_id == latest_results.c.testing_request_id,
            TestResult.cts == latest_results.c.latest_date
        )
    ).filter(
        TestResult.organization_id == svc.org_id,
        TestResult.evaluation_result.isnot(None)
    ).group_by('classification').all()
    
    normal_count = total_equipment
    alert_count_total = 0
    critical_count_total = 0
    
    for row in flagged_counts:
        if row.classification == 'ALERT':
            alert_count_total = row.count
            normal_count -= row.count
        elif row.classification == 'CRITICAL':
            critical_count_total = row.count
            normal_count -= row.count
    
    equipment_health = {
        'normal': normal_count,
        'alert': alert_count_total,
        'critical': critical_count_total,
        'total': total_equipment
    }
    
    # =========================================================================
    # 4. Overdue Tests Breakdown with Escalation (SRS Sec 5.1.3)
    # =========================================================================
    
    overdue_requests = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.due_date < now,
        TestingRequest.is_schedule_template.is_(False)
    ).order_by(TestingRequest.due_date.asc()).limit(20).all()
    
    overdue_breakdown = []
    escalation_levels = {'YELLOW': 0, 'ORANGE': 0, 'RED': 0}
    
    for req in overdue_requests:
        days_overdue = (now.date() - req.due_date.date()).days if req.due_date else 0
        
        if days_overdue >= 30:
            escalation = 'T+30 RED'
            escalation_levels['RED'] += 1
            severity = 'critical'
        elif days_overdue >= 7:
            escalation = 'T+7 ORANGE'
            escalation_levels['ORANGE'] += 1
            severity = 'warning'
        else:
            escalation = 'T+0 YELLOW'
            escalation_levels['YELLOW'] += 1
            severity = 'normal'
        
        test_type_name = req.test_type.name if req.test_type else 'Test'
        ueic = req.equipment.ueic if req.equipment else ''
        equipment_name = req.equipment.manufacturer or ueic if req.equipment else ''
        dept_name = req.department.name if req.department else ''

        # Get last alert sent date
        # Note: last_alert_date field not implemented yet in TestingRequest model
        last_alert = None
        # if hasattr(req, 'last_alert_date') and req.last_alert_date:
        #     last_alert = req.last_alert_date.strftime('%d-%b-%Y')

        overdue_breakdown.append({
            'id': str(req.id),
            'ueic': ueic,
            'equipment': equipment_name,
            'test_type': test_type_name,
            'days_overdue': days_overdue,
            'escalation_level': escalation,
            'severity': severity,
            'last_alert_sent': last_alert,
            'original_due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else None,
            'substation': dept_name
        })
    
    # =========================================================================
    # 5. Upcoming Test Schedule (Next 30 days - SRS Sec 5.1.2)
    # =========================================================================
    
    upcoming_tests = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.request_category == RequestCategory.test,
        TestingRequest.status.in_(['scheduled', 'pending_approval', 'assigned']),
        TestingRequest.due_date.between(now, now + timedelta(days=30)),
        TestingRequest.is_schedule_template.is_(False)
    ).order_by(TestingRequest.due_date.asc()).limit(50).all()
    
    # Group by week
    weeks_data = []
    for week_offset in range(4):
        week_start = now.date() + timedelta(days=week_offset * 7)
        week_end = week_start + timedelta(days=6)
        
        week_tests = [t for t in upcoming_tests if t.due_date and week_start <= t.due_date.date() <= week_end]
        
        # Count by test type
        type_counts = {}
        for test in week_tests:
            test_type = test.test_type.name if test.test_type else 'Other'
            type_counts[test_type] = type_counts.get(test_type, 0) + 1
        
        weeks_data.append({
            'week': week_offset + 1,
            'label': f'Week {week_offset + 1}',
            'start_date': week_start.strftime('%d-%b'),
            'end_date': week_end.strftime('%d-%b'),
            'total': len(week_tests),
            'by_type': type_counts
        })
    
    # =========================================================================
    # 6. Recent Test Results with Classification (SRS Sec 5.2.2)
    # =========================================================================
    
    recent_results = db.query(
        TestSession, TestingRequest, Equipment, CategoryDetails, TestResult
    ).join(
        TestingRequest, TestSession.testing_request_id == TestingRequest.id
    ).join(
        Equipment, TestingRequest.equipment_id == Equipment.id
    ).join(
        CategoryDetails, TestingRequest.test_type_id == CategoryDetails.id
    ).outerjoin(
        TestResult, TestResult.test_session_id == TestSession.id
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestSession.session_date >= thirty_days_ago
    ).order_by(TestSession.session_date.desc()).limit(15).all()
    
    recent_results_list = []
    for session, req, eq, test_type, result in recent_results:
        classification = result.evaluation_result.get('overall') if result and result.evaluation_result else 'PENDING'
        
        # Determine color based on classification
        if classification == 'CRITICAL':
            result_color = '#DC2626'
            result_bg = '#FEF2F2'
        elif classification == 'ALERT':
            result_color = '#D97706'
            result_bg = '#FFFBEB'
        elif classification == 'NORMAL':
            result_color = '#16A34A'
            result_bg = '#F0FDF4'
        else:
            result_color = '#64748B'
            result_bg = '#F8FAFC'
        
        # Format result value
        result_value = None
        if result and result.result_value:
            result_value = result.result_value
        
        recent_results_list.append({
            'id': str(session.id),
            'ueic': eq.ueic if eq else '',
            'equipment': eq.manufacturer or eq.ueic if eq else '',
            'test_type': test_type.name if test_type else 'Test',
            'result': result_value,
            'classification': classification,
            'result_color': result_color,
            'result_bg': result_bg,
            'tested_on': session.session_date.strftime('%d-%b-%Y') if session.session_date else None,
            'tested_by': session.conductor.name if session.conductor else None,
            'next_due_date': req.due_date.strftime('%d-%b-%Y') if req.due_date else None
        })
    
    # =========================================================================
    # 7. Open Remedial Actions (SRS Sec 5.2.4)
    # =========================================================================
    
    open_remediations = db.query(Recommendation).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending'
    ).order_by(Recommendation.cts.asc()).limit(10).all()
    
    remedial_actions_list = []
    for rec in open_remediations:
        req = rec.testing_request
        ueic = req.equipment.ueic if req and req.equipment else ''
        
        days_open = (now - rec.cts).days if rec.cts else 0
        is_overdue = days_open > 14
        
        remedial_actions_list.append({
            'id': str(rec.id),
            'ueic': ueic,
            'description': rec.summary or rec.detailed_notes or '',
            'assigned_to': 'Unassigned',
            'due_date': req.due_date.strftime('%Y-%m-%d') if req and req.due_date else None,
            'is_critical': False,
            'is_overdue': is_overdue,
            'days_open': days_open,
            'status': 'overdue' if is_overdue else 'pending'
        })
    
    # =========================================================================
    # 8. Active Alerts Feed (SRS Sec 5.2.2)
    # =========================================================================
    
    # Get latest CRITICAL/ALERT results
    active_alerts = db.query(
        TestResult, TestingRequest, Equipment
    ).join(
        TestingRequest, TestResult.testing_request_id == TestingRequest.id
    ).join(
        Equipment, TestingRequest.equipment_id == Equipment.id
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext.in_(['CRITICAL', 'ALERT'])
    ).order_by(TestResult.cts.desc()).limit(15).all()
    
    alerts_feed = []
    for result, req, eq in active_alerts:
        overall = result.evaluation_result.get('overall', 'ALERT')
        
        # Get flagged fields
        flagged_fields = []
        for field in result.evaluation_result.get('fields', []):
            if field.get('status') in ['CRITICAL', 'ALERT']:
                flagged_fields.append(f"{field.get('label', '')}: {field.get('value', '')}{field.get('unit', '')}")
        
        alerts_feed.append({
            'id': str(result.id),
            'ueic': eq.ueic if eq else '',
            'title': f"{overall} — {req.test_type.name if req.test_type else 'Test'}",
            'severity': 'critical' if overall == 'CRITICAL' else 'alert',
            'timestamp': result.cts.strftime('%d-%b-%Y %H:%M') if result.cts else None,
            'message': ' | '.join(flagged_fields[:2]) if flagged_fields else 'Test result requires attention',
            'equipment': eq.manufacturer or eq.ueic if eq else '',
            'substation': req.department.name if req.department else ''
        })
    
    # =========================================================================
    # 9. Test Schedule Trend (for bar chart)
    # =========================================================================
    
    # Weekly test counts for next 4 weeks
    weekly_schedule = []
    for week_offset in range(4):
        week_start = now.date() + timedelta(days=week_offset * 7)
        week_end = week_start + timedelta(days=6)
        
        # Count tests due in this week by type
        dga_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(name='DGA')
        ).scalar() or 0
        
        bdv_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(name='BDV')
        ).scalar() or 0
        
        ir_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(name='Insulation Resistance')
        ).scalar() or 0
        
        sf6_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(name='SF6 Purity')
        ).scalar() or 0
        
        other_count = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(week_start, week_end),
            TestingRequest.test_type.has(CategoryDetails.name.notin_(['DGA', 'BDV', 'Insulation Resistance', 'SF6 Purity']))
        ).scalar() or 0
        
        weekly_schedule.append({
            'week': week_offset + 1,
            'dga': dga_count,
            'bdv': bdv_count,
            'ir': ir_count,
            'sf6': sf6_count,
            'others': other_count,
            'total': dga_count + bdv_count + ir_count + sf6_count + other_count
        })
    
    # =========================================================================
    # 10. Monthly Compliance Trend (last 6 months)
    # =========================================================================
    
    compliance_trend = []
    for i in range(6):
        month_end = now - timedelta(days=30 * i)
        month_start = month_end - timedelta(days=30)
        
        month_total = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(month_start, month_end)
        ).scalar() or 0
        
        month_completed = db.query(func.count(TestingRequest.id)).filter(
            TestingRequest.organization_id == svc.org_id,
            dept_cond,
            TestingRequest.due_date.between(month_start, month_end),
            TestingRequest.status.in_(CLOSED_STATUSES)
        ).scalar() or 0
        
        compliance = int((month_completed / month_total * 100)) if month_total > 0 else 0
        
        compliance_trend.insert(0, {
            'month': month_start.strftime('%b'),
            'compliance': compliance,
            'total': month_total,
            'completed': month_completed
        })
    
    # =========================================================================
    # Final Response
    # =========================================================================
    
    return {
        # KPI Cards (6 cards)
        'kpi_cards': [
            {
                'label': 'Test Compliance Rate',
                'value': test_compliance,
                'display': f"{test_compliance}%",
                'sub': f"{tested_equipment} of {total_equipment} equipment tested (90d)",
                'trend': '+2%',
                'trend_dir': 'up',
                'colour': 'green' if test_compliance >= 80 else ('amber' if test_compliance >= 60 else 'red')
            },
            {
                'label': 'Overdue Tests',
                'value': overdue_tests,
                'display': str(overdue_tests),
                'sub': f"Escalation: Y:{escalation_levels['YELLOW']} O:{escalation_levels['ORANGE']} R:{escalation_levels['RED']}",
                'trend': None,
                'trend_dir': 'up' if overdue_tests > 5 else 'neutral',
                'colour': 'red' if overdue_tests > 10 else ('amber' if overdue_tests > 0 else 'green')
            },
            {
                'label': 'ALERT / CRITICAL',
                'value': alert_critical_total,
                'display': str(alert_critical_total),
                'sub': f"{alert_count} ALERT · {critical_count_total} CRITICAL",
                'trend': None,
                'trend_dir': 'up' if critical_count_total > 0 else 'neutral',
                'colour': 'red' if critical_count_total > 0 else ('amber' if alert_count_total > 0 else 'green')
            },
            {
                'label': 'Open Remedial Actions',
                'value': open_remediation,
                'display': str(open_remediation),
                'sub': f"{overdue_remediation} overdue · oldest pending",
                'trend': None,
                'trend_dir': 'up' if overdue_remediation > 0 else 'neutral',
                'colour': 'teal'
            },
            {
                'label': 'Maintenance Compliance',
                'value': maintenance_compliance,
                'display': f"{maintenance_compliance}%",
                'sub': f"{maintenance_compliant} of {total_equipment} equipment maintained (90d)",
                'trend': '-4%',
                'trend_dir': 'down',
                'colour': 'green' if maintenance_compliance >= 80 else ('amber' if maintenance_compliance >= 60 else 'red')
            },
            {
                'label': 'TA&QC Compliance',
                'value': taqc_compliance,
                'display': f"{taqc_compliance}%",
                'sub': f"{approved_tests} of {total_tests} tests approved (90d)",
                'trend': '+5%',
                'trend_dir': 'up',
                'colour': 'purple'
            }
        ],
        
        # Test compliance by type
        'test_compliance_by_type': test_compliance_by_type,
        
        # Equipment health summary
        'equipment_health': equipment_health,
        
        # Overdue tests breakdown
        'overdue_tests': {
            'total': overdue_tests,
            'escalation_breakdown': escalation_levels,
            'items': overdue_breakdown
        },
        
        # Upcoming test schedule
        'test_schedule': {
            'weeks': weeks_data,
            'upcoming_tests': [
                {
                    'id': str(t.id),
                    'ueic': t.equipment.ueic if t.equipment else '',
                    'test_type': t.test_type.name if t.test_type else 'Test',
                    'due_date': t.due_date.strftime('%d-%b-%Y') if t.due_date else None,
                    'substation': t.department.name if t.department else ''
                }
                for t in upcoming_tests[:15]
            ]
        },
        
        # Weekly schedule for bar chart
        'weekly_schedule': weekly_schedule,
        
        # Recent test results
        'recent_test_results': recent_results_list,
        
        # Open remedial actions
        'open_remediation': {
            'total': open_remediation,
            'overdue': overdue_remediation,
            'items': remedial_actions_list
        },
        
        # Active alerts feed
        'active_alerts': alerts_feed,
        
        # Compliance trend (for line chart)
        'compliance_trend': compliance_trend,
        
        # Role view info
        'role_view': {
            'view': 'test_coordinator',
            'permitted_widgets': [
                'kpi_cards', 'test_compliance_by_type', 'equipment_health',
                'overdue_tests', 'test_schedule', 'recent_test_results',
                'open_remediation', 'active_alerts', 'compliance_trend'
            ]
        }
    }


@router.get("/asset")
def get_asset_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Asset Data Officer Dashboard — equipment registry and data quality view.
    
    Based on SEACMS-AI SRS v2.0:
    - Sec 3: Equipment Asset Database Module
    - Sec 3.3.2: Data Sorting, Filtering and Search
    - Sec 3.3.3: Equipment Failure Registry
    - Sec 3.3.4: Failed and Scrapped Equipment History
    - Sec 3.3.5: Design Problem Tracking and Alert
    - Sec 9: Reporting Module
    
    Visible to: Asset Data Officer, Equipment Registry Manager roles
    """
    from models import TestingRequest, Equipment, EquipmentStatus, TestResult, Recommendation
    from sqlalchemy import func, and_
    from datetime import datetime, timedelta
    
    svc = _svc(db, current_user, org_id, dept_id)
    
    now = datetime.now()
    ninety_days_ago = now - timedelta(days=90)
    dept_cond = (Equipment.department_id.in_(svc.dept_ids)) if svc.dept_ids else True
    
    # =========================================================================
    # 1. KPI Cards for Asset Dashboard
    # =========================================================================
    
    # Total Equipment Registry
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond
    ).scalar() or 0
    
    # Active Equipment
    active_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.status == 'active'
    ).scalar() or 0
    
    # Equipment with complete nameplate data
    complete_data_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.manufacturer.isnot(None),
        Equipment.serial_number.isnot(None),
        Equipment.year_of_manufacture.isnot(None),
        Equipment.commissioning_date.isnot(None)
    ).scalar() or 0
    data_completeness = int((complete_data_equipment / total_equipment * 100)) if total_equipment > 0 else 0
    
    # Equipment with missing mandatory fields
    missing_mandatory = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        and_(
            Equipment.manufacturer.is_(None),
            Equipment.serial_number.is_(None)
        )
    ).scalar() or 0
    
    # Failure Registry - Open entries
    open_failures = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_(OPEN_STATUSES)
    ).scalar() or 0
    
    # High priority failures
    high_priority_failures = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.priority.in_(['high', 'critical']),
        TestingRequest.status.in_(OPEN_STATUSES)
    ).scalar() or 0
    
    # Design Problem Alerts
    design_problems = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.design_problem,
        TestingRequest.status == 'open'
    ).scalar() or 0
    
    # Equipment pending replacement (age > 30 years)
    thirty_years_ago = now - timedelta(days=365 * 30)
    ageing_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.status == 'active',
        Equipment.commissioning_date < thirty_years_ago
    ).scalar() or 0
    
    # =========================================================================
    # 2. Failure Registry List
    # =========================================================================
    
    failure_registry = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.failure_registry,
        TestingRequest.status.in_(OPEN_STATUSES)
    ).order_by(TestingRequest.priority.desc(), TestingRequest.cts.desc()).limit(20).all()
    
    failure_list = []
    for fr in failure_registry:
        ueic = fr.equipment.ueic if fr.equipment else ''
        equipment_name = fr.equipment.manufacturer or ueic if fr.equipment else ''
        dept_name = fr.department.name if fr.department else ''
        
        days_open = (now - fr.cts).days if fr.cts else 0
        
        failure_list.append({
            'id': str(fr.id),
            'request_number': fr.request_number,
            'ueic': ueic,
            'equipment': equipment_name,
            'substation': dept_name,
            'failure_date': fr.failure_date.strftime('%d-%b-%Y') if hasattr(fr, 'failure_date') and fr.failure_date else None,
            'failure_type': fr.failure_type if hasattr(fr, 'failure_type') else 'Unknown',
            'priority': fr.priority if hasattr(fr, 'priority') else 'medium',
            'status': fr.status.value if hasattr(fr.status, 'value') else str(fr.status),
            'days_open': days_open,
            'severity': 'critical' if fr.priority in ['high', 'critical'] else 'warning'
        })
    
    # =========================================================================
    # 3. Maintenance Overdue List
    # =========================================================================
    
    overdue_maintenance = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.maintenance,
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False)
    ).order_by(TestingRequest.due_date.asc()).limit(15).all()
    
    maintenance_list = []
    for maint in overdue_maintenance:
        days_overdue = (now.date() - maint.due_date.date()).days if maint.due_date else 0
        ueic = maint.equipment.ueic if maint.equipment else ''
        equipment_name = maint.equipment.manufacturer or ueic if maint.equipment else ''
        
        maintenance_list.append({
            'id': str(maint.id),
            'ueic': ueic,
            'equipment': equipment_name,
            'maintenance_type': maint.title,
            'days_overdue': days_overdue,
            'original_due_date': maint.due_date.strftime('%d-%b-%Y') if maint.due_date else None,
            'severity': 'critical' if days_overdue > 30 else ('warning' if days_overdue > 14 else 'normal'),
            'assigned_to': maint.assigned_to_name or 'Unassigned'
        })
    
    # =========================================================================
    # 4. Open Remedial Actions List
    # =========================================================================
    
    open_remediation = db.query(Recommendation).filter(
        Recommendation.organization_id == svc.org_id,
        Recommendation.approval_status == 'pending'
    ).order_by(Recommendation.cts.asc()).limit(15).all()
    
    remediation_list = []
    for rec in open_remediation:
        req = rec.testing_request
        ueic = req.equipment.ueic if req and req.equipment else ''
        days_open = (now - rec.cts).days if rec.cts else 0
        
        remediation_list.append({
            'id': str(rec.id),
            'ueic': ueic,
            'description': rec.summary or rec.detailed_notes or '',
            'assigned_to': 'Unassigned',
            'due_date': None,
            'days_open': days_open,
            'is_overdue': days_open > 14,
            'recommendation_type': rec.recommendation_type.value if hasattr(rec.recommendation_type, 'value') else 'General'
        })
    
    # =========================================================================
    # 5. Equipment Data Quality Summary
    # =========================================================================
    
    # Equipment by status
    equipment_by_status = db.query(
        Equipment.status,
        func.count(Equipment.id).label('count')
    ).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond
    ).group_by(Equipment.status).all()
    
    status_summary = {}
    for row in equipment_by_status:
        status_key = row.status.value if hasattr(row.status, 'value') else str(row.status)
        status_summary[status_key] = row.count
    
    # Equipment by voltage class
    equipment_by_voltage = db.query(
        Equipment.voltage_class,
        func.count(Equipment.id).label('count')
    ).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.voltage_class.isnot(None)
    ).group_by(Equipment.voltage_class).order_by(Equipment.voltage_class.desc()).all()
    
    voltage_summary = [{'voltage': row.voltage_class, 'count': row.count} for row in equipment_by_voltage]
    
    # Equipment by manufacturer
    equipment_by_manufacturer = db.query(
        Equipment.manufacturer,
        func.count(Equipment.id).label('count')
    ).filter(
        Equipment.organization_id == svc.org_id,
        dept_cond,
        Equipment.manufacturer.isnot(None)
    ).group_by(Equipment.manufacturer).order_by(func.count(Equipment.id).desc()).limit(10).all()
    
    manufacturer_summary = [{'manufacturer': row.manufacturer, 'count': row.count} for row in equipment_by_manufacturer]
    
    # =========================================================================
    # 6. Design Problem Alerts
    # =========================================================================
    
    design_problem_alerts = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.request_category == RequestCategory.design_problem,
        TestingRequest.status == 'open'
    ).order_by(TestingRequest.priority.desc(), TestingRequest.cts.desc()).limit(10).all()
    
    design_problem_list = []
    for dp in design_problem_alerts:
        ueic = dp.equipment.ueic if dp.equipment else ''
        equipment_name = dp.equipment.manufacturer or ueic if dp.equipment else ''
        make = dp.equipment.manufacturer if dp.equipment else 'Unknown'
        
        design_problem_list.append({
            'id': str(dp.id),
            'ueic': ueic,
            'equipment': equipment_name,
            'make': make,
            'problem_description': dp.title,
            'affected_units': dp.affected_units_count if hasattr(dp, 'affected_units_count') else 1,
            'priority': dp.priority if hasattr(dp, 'priority') else 'medium',
            'date_identified': dp.cts.strftime('%d-%b-%Y') if dp.cts else None,
            'status': 'open'
        })
    
    # =========================================================================
    # 7. Equipment Search Stats (for filtering)
    # =========================================================================
    
    # Unique substations with equipment
    substations = db.query(
        func.distinct(Equipment.department_id),
        func.count(Equipment.id).label('equipment_count')
    ).filter(
        Equipment.organization_id == svc.org_id,
        Equipment.department_id.isnot(None)
    ).group_by(Equipment.department_id).all()
    
    substation_list = [{'dept_id': str(s[0]), 'equipment_count': s[1]} for s in substations]
    
    # =========================================================================
    # Final Response
    # =========================================================================
    
    return {
        # KPI Cards for Asset Dashboard
        'kpi_cards': [
            {
                'label': 'Total Equipment',
                'value': total_equipment,
                'display': str(total_equipment),
                'sub': f"{active_equipment} active",
                'trend': None,
                'trend_dir': 'neutral',
                'colour': 'blue'
            },
            {
                'label': 'Data Completeness',
                'value': data_completeness,
                'display': f"{data_completeness}%",
                'sub': f"{complete_data_equipment} of {total_equipment} complete",
                'trend': None,
                'trend_dir': 'up' if data_completeness > 80 else 'neutral',
                'colour': 'green' if data_completeness >= 90 else ('amber' if data_completeness >= 70 else 'red')
            },
            {
                'label': 'Missing Mandatory Data',
                'value': missing_mandatory,
                'display': str(missing_mandatory),
                'sub': "Equipment without manufacturer/serial",
                'trend': None,
                'trend_dir': 'down' if missing_mandatory == 0 else 'up',
                'colour': 'red' if missing_mandatory > 10 else ('amber' if missing_mandatory > 0 else 'green')
            },
            {
                'label': 'Failure Registry',
                'value': open_failures,
                'display': str(open_failures),
                'sub': f"{high_priority_failures} high priority",
                'trend': None,
                'trend_dir': 'up' if open_failures > 5 else 'neutral',
                'colour': 'red' if high_priority_failures > 0 else ('amber' if open_failures > 0 else 'green')
            },
            {
                'label': 'Design Problem Alerts',
                'value': design_problems,
                'display': str(design_problems),
                'sub': "Make/model issues requiring attention",
                'trend': None,
                'trend_dir': 'up' if design_problems > 0 else 'neutral',
                'colour': 'red' if design_problems > 5 else ('amber' if design_problems > 0 else 'green')
            },
            {
                'label': 'Ageing Equipment',
                'value': ageing_equipment,
                'display': str(ageing_equipment),
                'sub': ">30 years in service",
                'trend': None,
                'trend_dir': 'up' if ageing_equipment > 0 else 'neutral',
                'colour': 'red' if ageing_equipment > 20 else ('amber' if ageing_equipment > 0 else 'green')
            }
        ],
        
        # Failure Registry List
        'failure_registry': {
            'total': open_failures,
            'high_priority': high_priority_failures,
            'items': failure_list
        },
        
        # Maintenance Overdue List
        'maintenance_overdue': {
            'total': len(overdue_maintenance),
            'items': maintenance_list
        },
        
        # Open Remedial Actions
        'open_remediation': {
            'total': len(open_remediation),
            'overdue': sum(1 for r in remediation_list if r['is_overdue']),
            'items': remediation_list
        },
        
        # Equipment Data Quality Summary
        'data_quality': {
            'by_status': status_summary,
            'by_voltage': voltage_summary,
            'by_manufacturer': manufacturer_summary,
            'total_equipment': total_equipment,
            'active_equipment': active_equipment,
            'complete_data_rate': data_completeness
        },
        
        # Design Problem Alerts
        'design_problem_alerts': {
            'total': design_problems,
            'items': design_problem_list
        },
        
        # Substations with equipment
        'substations': substation_list,
        
        # Role view info
        'role_view': {
            'view': 'asset',
            'permitted_widgets': [
                'kpi_cards', 'failure_registry', 'maintenance_overdue',
                'open_remediation', 'data_quality', 'design_problem_alerts'
            ]
        }
    }
