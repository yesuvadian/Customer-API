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
    now = datetime.now()
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