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
from models import User
from services.dashboard_service import DashboardService, invalidate_dashboard_cache

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _svc(db: Session, current_user: User, org_id: Optional[UUID] = None) -> DashboardService:
    """Build service scoped to the caller's org (or explicit org_id for multi-org admins)."""
    resolved_org = org_id
    if resolved_org is None:
        # Use the organisation from the user's first active OrgUserRole
        from models import OrgUserRole, OrgRole
        row = (
            db.query(OrgUserRole)
            .filter(OrgUserRole.user_id == current_user.id,
                    OrgUserRole.is_active.is_(True))
            .first()
        )
        if row:
            role = db.query(OrgRole).filter(OrgRole.id == row.org_role_id).first()
            if role:
                resolved_org = role.organization_id
    return DashboardService(db, org_id=resolved_org)


# ── Role view ──────────────────────────────────────────────────────────────

@router.get("/role-view")
def get_role_view(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns which dashboard view type this user sees and which widgets are permitted."""
    svc = _svc(db, current_user, org_id)
    return svc.role_view(current_user.id)


# ── KPI cards ──────────────────────────────────────────────────────────────

@router.get("/kpi")
def get_kpi_cards(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all 6 KPI cards for the current user's role."""
    return _svc(db, current_user, org_id).all_kpi_cards()


# ── Overdue tests ──────────────────────────────────────────────────────────

@router.get("/overdue-tests")
def get_overdue_tests(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id).overdue_tests_breakdown()


# ── Active alerts feed ─────────────────────────────────────────────────────

@router.get("/active-alerts")
def get_active_alerts(
    limit: int = Query(10, ge=1, le=50),
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id).active_alerts(limit=limit)


# ── Flagged equipment ──────────────────────────────────────────────────────

@router.get("/flagged-equipment")
def get_flagged_equipment(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id).flagged_equipment()


# ── Repair progress ────────────────────────────────────────────────────────

@router.get("/repair-timeliness")
def get_repair_timeliness(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Vendor delay summary across all active repair workflows.
    Returns aggregate counts (total, on_time, delayed, pending_attribution)
    plus total vendor / KPTCL delay days and a list of problem workflows.
    Visible to: admin, see_cee.
    """
    return _svc(db, current_user, org_id).repair_timeliness()


@router.get("/repair-progress")
def get_repair_progress(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id).repair_progress()


# ── Maintenance overdue ────────────────────────────────────────────────────

@router.get("/maintenance-overdue")
def get_maintenance_overdue(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id).maintenance_overdue()


# ── Procurement pipeline ───────────────────────────────────────────────────

@router.get("/procurement")
def get_procurement(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id).procurement_pipeline()


# ── Open remediation ───────────────────────────────────────────────────────

@router.get("/open-remediation")
def get_open_remediation(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _svc(db, current_user, org_id).open_remediation_list()


# ── Full dashboard (all widgets in one call) ───────────────────────────────

@router.get("/full")
async def get_full_dashboard(
    org_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Single endpoint that returns every widget.
    Flutter calls this once on load — role_view controls which sections to render.
    Optimized to run all widget methods in parallel for better performance.
    """
    from concurrent.futures import ThreadPoolExecutor
    import asyncio
    
    svc = _svc(db, current_user, org_id)
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
    return _svc(db, current_user, org_id).projected_tickets_by_month(year=year)


# ── Created vs Completed month-wise ────────────────────────────────────────

@router.get("/tickets-trend")
def get_tickets_trend(
    year: Optional[int] = Query(None, description="4-digit year, defaults to current year"),
    org_id: Optional[UUID] = Query(None),
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
    return _svc(db, current_user, org_id).tickets_created_vs_completed(year=year)


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
