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
from category_labels import TrWfOutcomeColors

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _svc(db: Session, current_user: User, org_id: Optional[UUID] = None,
         dept_id: Optional[UUID] = None) -> DashboardService:
    """Build service scoped to the caller's org (or explicit org_id for multi-org
    admins) and department subtree — mirrors dashboard_role_kpi.py's _svc() exactly,
    so this router's widgets stop silently ignoring department scope (Flutter was
    already sending dept_id on some calls; it was accepted by FastAPI as an unused
    query param and never reached DashboardService)."""
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
    from utils.common_service import get_dept_subtree_ids, get_user_dept_scope
    resolved_dept = dept_id
    if resolved_dept is None:
        is_org_admin, scoped_dept = get_user_dept_scope(db, current_user.id, resolved_org)
        if not is_org_admin:
            resolved_dept = scoped_dept
    dept_ids = None
    if resolved_dept:
        dept_ids = get_dept_subtree_ids(db, resolved_dept)
    return DashboardService(db, org_id=resolved_org, dept_id=resolved_dept, dept_ids=dept_ids)


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
    Optimized to run all widget methods in parallel for better performance.
    """
    from concurrent.futures import ThreadPoolExecutor
    import asyncio
    
    svc = _svc(db, current_user, org_id, dept_id)
    role_info = svc.role_view(current_user.id)
    permitted = set(role_info["permitted_widgets"])

    # Run all widget computations in parallel using a thread pool
    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=8)
    
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
    if "maintenance_overdue" in permitted:
        tasks.append(("maintenance_overdue", loop.run_in_executor(executor, svc.maintenance_overdue)))
    if "procurement_pipeline" in permitted:
        tasks.append(("procurement", loop.run_in_executor(executor, svc.procurement_pipeline)))
    if "open_remediation" in permitted:
        tasks.append(("open_remediation", loop.run_in_executor(executor, svc.open_remediation_list)))
    
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
        "repair_progress":   results.get("repair_progress", []),
        "maintenance_overdue": results.get("maintenance_overdue", None),
        "procurement":       results.get("procurement", None),
        "open_remediation":  results.get("open_remediation", None),
    }


# ── Cache invalidation ─────────────────────────────────────────────────────

@router.post("/invalidate-cache")
def invalidate_cache(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Flush the dashboard cache. Call after bulk imports or data corrections."""
    svc = _svc(db, current_user, org_id, dept_id)
    invalidate_dashboard_cache(svc.org_id)
    return {"status": "ok", "message": "Dashboard cache invalidated"}


# ── Role-specific dashboards ───────────────────────────────────────────────

@router.get("/aee")
def get_aee_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AEE Dashboard - Field-level maintenance supervisor view."""
    from models import TestingRequest, Equipment, OrgUserRole, OrgRole
    from sqlalchemy import func, and_
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id, dept_id)

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
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """EE TLSS Dashboard - Condition monitoring & operational oversight."""
    from models import TestingRequest, Equipment, TestSession
    from sqlalchemy import func, and_
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id, dept_id)

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


# ── Department rollup — leaf/branch adaptive, shared by /see and /cee ───────
#
# No children under the resolved scope -> "leaf" shape: task-level counts for
# that one department, same metric definitions this file already uses (equipment
# under_repair = critical, 90-day due-vs-completed = compliance). Has children ->
# "branch" shape: one row per child department, same metrics computed per child
# and ranked worst-first by compliance, plus who's assigned to it (AE_JE role
# holder for that department — see routers/dashboard_kpi.py's role audit).
#
# This is the one piece that makes /see and /cee genuinely adaptive by scope
# instead of hardcoded to "circle" / "zone" framing: an AE_JE-scoped user hitting
# either endpoint gets the leaf shape, a SEE/CEE-scoped user gets the branch shape,
# decided at request time from svc.dept_id's actual children — not from role name.
#
# KNOWN SCOPE LIMIT: overdue_count/critical_count/compliance_pct are computed
# from TestingRequest only (covers request_category test/maintenance/inspection/
# failure_registry/taqc_inspection). Corrective-maintenance/repair work tracked
# via RepairWorkflow + RepairStageInstance (models.py:293-452 — a separate table,
# scoped through Equipment rather than TestingRequest.department_id, with its own
# per-stage due dates) is NOT included. Deliberately left out for now — this org
# has zero RepairWorkflow rows to verify correctness against; folding it in is a
# real, explicitly flagged follow-up, not an oversight.
def _build_department_rollup(db: Session, svc: DashboardService,
                              current_user: Optional[User] = None) -> dict:
    from models import OrgDepartment, TestingRequest, OrgRole, OrgUserRole, User, HierarchyAnalytics, EquipmentAnalytics, TrWfStageRole
    from utils.common_service import get_dept_subtree_ids
    from sqlalchemy import func
    from datetime import datetime, timedelta
    # mts/due_date aren't consistently stored tz-aware across rows (confirmed
    # live — some naive, some UTC-aware); normalize both sides of any Python-
    # side comparison with these, same helpers dashboard_service.py already
    # uses for exactly this reason. (SQL-level filters below don't need this —
    # only in-memory comparisons against fetched datetime values do.)
    from services.dashboard_service import _make_tz, _now

    # Current department's own name/level — lets the frontend build a real
    # title ("BMAZ North · Substation", "Bangalore Zone · Zone") instead of a
    # role name, since this widget no longer knows or cares what role is
    # asking. None dept_id (org admin / root scope) reads as "Organisation".
    if svc.dept_id:
        own_dept = db.query(OrgDepartment).filter(OrgDepartment.id == svc.dept_id).first()
        own_ha = db.query(HierarchyAnalytics).filter(
            HierarchyAnalytics.department_id == svc.dept_id).first()
        scope_name = own_dept.name if own_dept else "Unknown"
        scope_level = own_ha.level_type if own_ha else None
    else:
        scope_name = "Organisation"
        scope_level = "Organisation"

    if svc.dept_id:
        children = (
            db.query(OrgDepartment)
            .filter(OrgDepartment.parent_department_id == svc.dept_id)
            .all()
        )
    elif svc.org_id:
        children = (
            db.query(OrgDepartment)
            .filter(
                OrgDepartment.parent_department_id.is_(None),
                OrgDepartment.organization_id == svc.org_id,
            )
            .all()
        )
    else:
        children = []

    ninety_days_ago = datetime.now() - timedelta(days=90)

    def _weekly_trend(dept_ids_for_scope, weeks=13):
        """Opened/closed/overdue per ISO week for the last `weeks` weeks
        (13 ~= 3 months). Opened = TestingRequest.cts in that week. Closed =
        same closed-expression as _scope_counts' closed_this_week_count,
        bucketed by mts instead of a fixed 7-day window. Overdue = requests
        due that week that are (as of now, not as of that week — there's no
        historical status-snapshot table to reconstruct a true point-in-time
        count from) still open and past due; a real, if retrospective,
        reading of the backlog, not a fabricated trend line.
        """
        from sqlalchemy import or_ as _or_trend, func as _func_trend

        # Anchored from THIS week backward, not from "now - weeks" forward —
        # those aren't the same thing. now - 13 weeks lands exactly 13 weeks
        # before now (91 days, an exact multiple of 7, so same weekday), and
        # rounding that down to its own Monday, then stepping forward `weeks`
        # buckets, produces a range whose LAST bucket is one week short of
        # today's actual week — confirmed live (today Mon-anchor 2026-08-24,
        # old logic's last bucket landed on 2026-08-17). Today's own week
        # must always be the last bucket, or anything created today never
        # shows up at all.
        now = _now()
        first_monday = (now - timedelta(days=now.weekday())).date() - timedelta(weeks=weeks - 1)
        cutoff = datetime.combine(first_monday, datetime.min.time(), tzinfo=now.tzinfo)
        base_filter = [TestingRequest.organization_id == svc.org_id]
        if dept_ids_for_scope:
            base_filter.append(TestingRequest.department_id.in_(dept_ids_for_scope))

        week_col_cts = _func_trend.date_trunc('week', TestingRequest.cts)
        opened_rows = (
            db.query(week_col_cts.label('wk'), _func_trend.count(TestingRequest.id))
            .filter(*base_filter, TestingRequest.cts >= cutoff)
            .group_by('wk').all()
        )

        closed_expr = _or_trend(
            TestingRequest.status == 'closed',
            TestingRequest.current_status_code.in_(terminal_status_codes),
        )
        week_col_mts = _func_trend.date_trunc('week', TestingRequest.mts)
        closed_rows = (
            db.query(week_col_mts.label('wk'), _func_trend.count(TestingRequest.id))
            .filter(*base_filter, closed_expr, TestingRequest.mts >= cutoff)
            .group_by('wk').all()
        )

        # Overdue is plotted as a running backlog, not "became due in exactly
        # this week": bucketing by which week due_date itself fell in made
        # the CURRENT week's point read 0 whenever nothing happened to be
        # due in the last 7 days, even though something overdue since
        # earlier (e.g. 2+ weeks ago) is still sitting open right now —
        # confirmed live: FR-KP-2026-0001, overdue since an earlier week,
        # made the chart peak around Wk11-12 then drop to 0 at Wk13, while
        # the Overdue Tests KPI tile right next to it correctly still read 1.
        # Instead, each week's point = count of still-open requests whose
        # due_date had already passed by that week's end — cumulative, so
        # the LAST (current) point always equals "overdue right now",
        # matching the KPI tile it's plotted alongside.
        overdue_due_dates = [
            d for (d,) in db.query(TestingRequest.due_date).filter(
                *base_filter, ~closed_expr,
                TestingRequest.due_date.isnot(None),
                TestingRequest.due_date < _now(),
            ).all() if d is not None
        ]

        opened_by_week = {w.date().isoformat(): c for w, c in opened_rows if w}
        closed_by_week = {w.date().isoformat(): c for w, c in closed_rows if w}

        # Fill every week in range, including zero-count ones, so the chart
        # doesn't silently skip gaps. (first_monday already computed above —
        # not re-derived from cutoff here, since cutoff is already exactly
        # that Monday.)
        out = []
        for i in range(weeks):
            week_start = first_monday + timedelta(weeks=i)
            wk = week_start.isoformat()
            week_end = datetime.combine(
                week_start + timedelta(weeks=1), datetime.min.time(), tzinfo=now.tzinfo)
            overdue_count_for_week = sum(1 for d in overdue_due_dates if d < week_end)
            out.append({
                "week_start": wk,
                "opened": opened_by_week.get(wk, 0),
                "closed": closed_by_week.get(wk, 0),
                "overdue": overdue_count_for_week,
            })
        return out

    # "Awaiting approval" isn't one thing — a tr_wf stage flagged
    # A non-result stage ("Pending L2 Approval", "L3 Tester Assignment", …)
    # or a result-review stage ("Under L3 Review"), and different roles hold
    # rights on each (EE_TLSS approves L2 routing; AEE_R&T/AEE_R&D review L3
    # results — a confirmed AEE-R&D row has can_approve=True on
    # l3_review_result only, nothing on l2_pending_approval). Lumping them
    # into one count/button would show a "review" action to a routing-only
    # approver and vice versa, so split them here by which stages each
    # represents (for checking which of the two the CALLER's role actually
    # holds). Deliberately NOT filtered by TrWfStatus.approval_required —
    # that flag means "this status needs an approval-type action", which is
    # False for l3_pending_assignment (it needs an ASSIGNMENT, not an
    # approval) and would silently drop that stage from approval_stage_ids
    # entirely; confirmed live: AEE-R&D holds can_assign (not can_approve)
    # on L3 Tester Assignment, and the real CM Test Request Approval queue
    # (testing_request_approvals.py) shows those 6 pending assignments to
    # them regardless of approval_required — it matches by TrWfStageRole
    # presence on the stage, not that status flag. Computed once since
    # _scope_counts runs per-row, not per query.
    from models import TrWfStatus, TrWfDefinition, TrWfStage, TrWfInstance
    stage_rows = (
        db.query(TrWfStage.id, TrWfStage.is_result_stage)
        .join(TrWfStatus, TrWfStatus.id == TrWfStage.status_id)
        .join(TrWfDefinition, TrWfDefinition.id == TrWfStatus.wf_definition_id)
        .filter(
            TrWfDefinition.org_id == svc.org_id,
            TrWfStatus.is_active.is_(True),
            TrWfStage.is_active.is_(True),
        )
        .all()
    )
    review_stage_ids = {r.id for r in stage_rows if r.is_result_stage}
    approval_stage_ids = {r.id for r in stage_rows if not r.is_result_stage}

    # "Closed" status codes, derived from TrWfStatus.is_terminal for THIS
    # org's own workflow definitions — not the hardcoded 3-tuple
    # (TR_WF_CLOSED_STATUS_CODES = "wf_completed"/"wf_rejected"/
    # "wf_cancelled") used elsewhere in the codebase. That tuple assumes
    # every workflow definition, in every org, names its terminal statuses
    # with those exact three codes — the same hardcoded-name assumption
    # already ruled out for roles and stages earlier in this function
    # (workflows and their stage/status codes are configured per org, not
    # fixed). A custom workflow with differently-named terminal statuses
    # (or more than three) would silently be miscounted as "still open" by
    # the fixed tuple; is_terminal is the actual per-status flag the
    # workflow config itself sets, so it generalizes to any of them.
    terminal_status_rows = (
        db.query(TrWfStatus.status_code, TrWfStatus.status_name)
        .join(TrWfDefinition, TrWfDefinition.id == TrWfStatus.wf_definition_id)
        .filter(
            TrWfDefinition.org_id == svc.org_id,
            TrWfStatus.is_terminal.is_(True),
        ).all()
    )
    terminal_status_codes = list({row[0] for row in terminal_status_rows})
    # Rejected vs Cancelled — deliberately NOT read off current_status_code/
    # its status_name, even though that's what "closed" itself is derived
    # from above. Confirmed live: TR-KP-2026-0013 was rejected via the L2
    # Approval & Route stage's "reject" action (its own workflow timeline
    # shows a red "Rejected" terminal card), yet current_status_code
    # denormalized onto the request as "wf_cancelled" instead of
    # "wf_rejected" — tr_workflow_routing_service.py's terminal-status
    # resolution can fall back to "last TrWfStatus by sequence for this
    # definition" when a transition's own terminal_status_id doesn't
    # resolve, which silently picks whichever terminal status happens to
    # sort last, not the one that actually fired. routers/testing_requests.py
    # hit this same bug already (see its wf_terminal_action_code comment)
    # and tr_kanban_board.dart's own Rejected/Cancelled split works around
    # it the same way used here: the LAST TrWfAuditLog row for a request's
    # workflow instance (is_terminal=True — one such row per instance) is
    # the actual button that closed it, so its action_code is ground truth.
    from models import TrWfAuditLog as _TrWfAuditLog
    terminal_audit_rows = (
        db.query(_TrWfAuditLog.testing_request_id, _TrWfAuditLog.action_code)
        .join(TestingRequest, TestingRequest.id == _TrWfAuditLog.testing_request_id)
        .filter(
            TestingRequest.organization_id == svc.org_id,
            _TrWfAuditLog.is_terminal.is_(True),
        ).all()
    )
    rejected_request_ids = {
        rid for rid, code in terminal_audit_rows if 'reject' in (code or '').lower()
    }
    cancelled_request_ids = {
        rid for rid, code in terminal_audit_rows if 'cancel' in (code or '').lower()
    }
    rejected_cancelled_request_ids = rejected_request_ids | cancelled_request_ids

    # Which SPECIFIC stages (within the two categories above) the CALLING
    # viewer's own role(s) actually hold can_approve/can_assign on.
    # approval_stage_ids/review_stage_ids span every TrWfDefinition in the
    # org, not just Standard Test Workflow — a request sitting in a totally
    # different workflow (e.g. a Failure Registry ticket on "PM Workflow")
    # can carry a status that lands in that same set even though the viewer
    # has zero TrWfStageRole permission on it. Confirmed live once already:
    # matching on current_status_code alone (an earlier version of this
    # code) let a PM Workflow status leak into an unrelated org admin's
    # approval count. Intersecting the viewer's own stage_ids against
    # approval_stage_ids/review_stage_ids ties both the COUNTS and the
    # approvals LIST below to the exact stage instance each request is
    # actually sitting at, matching what the real approval queue shows.
    user_role_ids = []
    viewer_approve_only_stage_ids = set()
    viewer_assign_only_stage_ids = set()
    viewer_approval_stage_ids = set()
    viewer_review_stage_ids = set()
    if current_user is not None:
        user_role_ids = [
            r[0] for r in db.query(OrgUserRole.org_role_id)
            .filter(OrgUserRole.user_id == current_user.id, OrgUserRole.is_active.is_(True))
            .all()
        ]
        if user_role_ids:
            user_approve_stage_ids = {
                row[0] for row in db.query(TrWfStageRole.stage_id).filter(
                    TrWfStageRole.role_id.in_(user_role_ids),
                    TrWfStageRole.can_approve.is_(True),
                ).all()
            }
            # Non-result stages are actionable via can_assign too, not just
            # can_approve — the real CM Test Request Approval queue
            # (testing_request_approvals.py's tr_wf_get_pending_queue) shows
            # a request to any role with ANY TrWfStageRole row on its current
            # stage, not can_approve specifically. Confirmed live:
            # AEE-R&D has can_assign=True (not can_approve) on L3 Tester
            # Assignment, and the real queue correctly shows their pending
            # assignments there — the dashboard's can_approve-only version
            # showed 0 for the same user while the real page showed 6.
            # Result Review stays can_approve-only: "assign" has no meaning
            # there (nobody gets assigned at a review/finalization stage).
            user_assign_stage_ids = {
                row[0] for row in db.query(TrWfStageRole.stage_id).filter(
                    TrWfStageRole.role_id.in_(user_role_ids),
                    TrWfStageRole.can_assign.is_(True),
                ).all()
            }
            viewer_approve_only_stage_ids = user_approve_stage_ids & approval_stage_ids
            viewer_assign_only_stage_ids = user_assign_stage_ids & approval_stage_ids
            # Union of both — feeds the combined "Needs Your Approval" panel
            # (_approval_queue below), which lists everything actionable on
            # this viewer's own non-result stages regardless of which of the
            # two actions applies to a given row.
            viewer_approval_stage_ids = (
                viewer_approve_only_stage_ids | viewer_assign_only_stage_ids
            )
            viewer_review_stage_ids = user_approve_stage_ids & review_stage_ids
    # System Administrator isn't a participant in this workflow at all, so it
    # must not see either just because it can see every department's rollup.
    # can_approve_requests/can_assign_requests are separate capabilities —
    # confirmed live: AEE-R&D holds can_assign (not can_approve) on L3
    # Tester Assignment, so a single combined "Approve Requests" button
    # would mislabel what they can actually do there; the Quick Action
    # button routes to the same tr-wf/approval-queue page either way, but
    # shows "Assign Requests" instead when that's the real permission.
    can_approve_requests = bool(viewer_approve_only_stage_ids)
    can_assign_requests = bool(viewer_assign_only_stage_ids)
    can_review = bool(viewer_review_stage_ids)

    # Which roles can actually act as the tester for a department — driven by
    # TrWfStageRole.can_edit (real execution rights), not a hardcoded role
    # name. This org alone has three separate "AE-equivalent" roles (AE_JE,
    # AE-R&D, presumably AE-R&T too) with real department assignments — a
    # single hardcoded ae_role_name default would silently show no assigned
    # officer for every department whose tester isn't in that one exact role,
    # and any org can name/split its tester roles differently again. Same
    # capability check as can_test below (can_edit only, not
    # can_act_as_tester — that flag on an earlier stage means "eligible to
    # self-assign," not "currently holds execution rights"; a confirmed AEE-
    # R&D row has can_act_as_tester=True on L3 Tester Assignment yet
    # can_edit=False everywhere), just resolved for every role in the org up
    # front instead of just the caller's own.
    tester_capable_role_ids = {
        row[0] for row in db.query(TrWfStageRole.role_id)
        .join(OrgRole, OrgRole.id == TrWfStageRole.role_id)
        .filter(
            OrgRole.organization_id == svc.org_id,
            TrWfStageRole.can_edit.is_(True),
        )
        .distinct()
        .all()
    }

    def _scope_counts(dept_ids_for_scope):
        # Deliberately includes Failure Registry / TAQC Inspection direct
        # submissions alongside regular testing requests — "Open Requests"/
        # "Overdue Tests"/etc. mean everything open at this substation the
        # viewer needs to act on, not just Standard-Test-Workflow tickets.
        # (An earlier version excluded them to match the Kanban board's own
        # count, but that inverted the real intent: Kanban is TR-only by
        # design — FR follows a different workflow definition with its own
        # stages, so it wouldn't render sensibly as Standard Test Workflow
        # columns anyway — while these summary counts are meant to be
        # everything, so the two are expected to disagree, not forced to match.)
        tr_filters = [TestingRequest.organization_id == svc.org_id]
        if dept_ids_for_scope:
            tr_filters.append(TestingRequest.department_id.in_(dept_ids_for_scope))

        total_requests = db.query(func.count(TestingRequest.id)).filter(
            *tr_filters, TestingRequest.cts >= ninety_days_ago,
        ).scalar() or 0
        # 'completed' isn't an actual TestingRequestStatus value in this data
        # (verified against live DB — the real terminal status is 'closed').
        # A request can also be functionally done via the tr_wf workflow while
        # its legacy .status field lags behind — use terminal_status_codes
        # (derived from TrWfStatus.is_terminal above, not a hardcoded tuple)
        # rather than re-deriving "closed" from just one of the two status
        # fields.
        from sqlalchemy import or_ as _or
        completed_requests = db.query(func.count(TestingRequest.id)).filter(
            *tr_filters,
            _or(
                TestingRequest.status == 'closed',
                TestingRequest.current_status_code.in_(terminal_status_codes),
            ),
            TestingRequest.cts >= ninety_days_ago,
        ).scalar() or 0
        # "closed" itself is the exact same OR used for completed_requests
        # above — legacy .status=='closed' for pre-tr_wf requests (which have
        # no current_status_code at all — confirmed live, all 651 of them),
        # OR the tr_wf terminal codes for anything closed through the newer
        # system. open_count is defined as this expression's exact negation
        # (De Morgan, via ~), so open + closed always reconciles to the total
        # — no separate hand-derived "not closed" condition to drift out of
        # sync with it.
        _closed_expr = _or(
            TestingRequest.status == 'closed',
            TestingRequest.current_status_code.in_(terminal_status_codes),
        )
        # Subset of _closed_expr whose terminal audit-log action was
        # specifically a rejection/cancellation, not a normal completion —
        # sourced from rejected_cancelled_request_ids (audit-log ground
        # truth, see comment above), not current_status_code. Legacy
        # status=='closed' rows never land here (no wf_instance to have
        # fired a terminal audit log at all), so only tr_wf-tracked requests
        # can match.
        _rejected_cancelled_expr = TestingRequest.id.in_(
            rejected_cancelled_request_ids)
        # Same "still open" definition as open_count (~_closed_expr), not a
        # hardcoded legacy-status allowlist — that list ('submitted',
        # 'pending_approval', 'assigned', 'scheduled') silently missed real
        # active states like 'pending_assignment' (confirmed live:
        # TR-KP-2026-0650, due 2026-08-20 and still sitting at L3 Tester
        # Assignment, was excluded from this tile while genuinely overdue).
        overdue_count = db.query(func.count(TestingRequest.id)).filter(
            *tr_filters,
            ~_closed_expr,
            TestingRequest.due_date < _now(),
        ).scalar() or 0
        # Open = not closed, no age limit (unlike total_requests/completed_requests
        # above, which are both bounded to the last 90 days) — a request that's
        # been sitting open longer than that should still count as open.
        open_count = db.query(func.count(TestingRequest.id)).filter(
            *tr_filters,
            ~_closed_expr,
        ).scalar() or 0
        # mts is the best available proxy for "when it closed" — there's no
        # separate closed_at/completed_at column on TestingRequest.
        # Excludes rejected/cancelled — those get their own card (below)
        # instead of being folded into "Closed This Week", which is meant to
        # read as genuine completions.
        closed_this_week_count = db.query(func.count(TestingRequest.id)).filter(
            *tr_filters,
            _closed_expr,
            ~_rejected_cancelled_expr,
            TestingRequest.mts >= _now() - timedelta(days=7),
        ).scalar() or 0
        # All-time, not windowed to this week — same convention as
        # open_count above (a rejected/cancelled ticket from months ago is
        # still worth surfacing here, not just ones from the last 7 days).
        rejected_cancelled_count = db.query(func.count(TestingRequest.id)).filter(
            *tr_filters,
            _rejected_cancelled_expr,
        ).scalar() or 0
        # Scoped to the CALLING viewer's own can_approve/can_assign
        # stage_ids (see viewer_approve_only_stage_ids/
        # viewer_assign_only_stage_ids/viewer_review_stage_ids above), via
        # the actual TrWfInstance each request is sitting at — not a
        # current_status_code string match, which can't tell one workflow
        # definition's stage apart from another's coincidentally-similar
        # one. Kept as two separate counts (not one combined "awaiting
        # approval" number) so a role that only holds can_assign somewhere
        # — AEE-R&D on L3 Tester Assignment, confirmed live — gets an
        # accurate "Pending Assignment" count instead of being silently
        # folded into "Pending Approval", which they hold zero of there.
        pending_approval_count = db.query(func.count(TrWfInstance.id)).join(
            TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id,
        ).filter(
            *tr_filters,
            TrWfInstance.status == 'active',
            TrWfInstance.current_stage_id.in_(viewer_approve_only_stage_ids),
        ).scalar() or 0 if viewer_approve_only_stage_ids else 0
        pending_assign_count = db.query(func.count(TrWfInstance.id)).join(
            TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id,
        ).filter(
            *tr_filters,
            TrWfInstance.status == 'active',
            TrWfInstance.current_stage_id.in_(viewer_assign_only_stage_ids),
        ).scalar() or 0 if viewer_assign_only_stage_ids else 0
        pending_review_count = db.query(func.count(TrWfInstance.id)).join(
            TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id,
        ).filter(
            *tr_filters,
            TrWfInstance.status == 'active',
            TrWfInstance.current_stage_id.in_(viewer_review_stage_ids),
        ).scalar() or 0 if viewer_review_stage_ids else 0
        # "Critical" here means the same thing it means on the AI Analytics
        # Dashboard — EquipmentAnalytics.risk_level == 'Critical' (a computed
        # health-score classification), NOT Equipment.status == 'under_repair'
        # (a separate, manually-set workflow status). Using the wrong one
        # made this dashboard's critical count silently disagree with the
        # analytics dashboard's for the exact same scope.
        critical_eq_filters = [EquipmentAnalytics.organization_id == svc.org_id,
                                EquipmentAnalytics.risk_level == 'Critical']
        if dept_ids_for_scope:
            critical_eq_filters.append(EquipmentAnalytics.department_id.in_(dept_ids_for_scope))
        critical_count = db.query(func.count(EquipmentAnalytics.id)).filter(
            *critical_eq_filters,
        ).scalar() or 0
        # Compliance = closure rate over the last 90 days (completed /
        # total), not an on-time SLA rate — an on-time version was tried and
        # reverted: due_date is only ever populated on currently-open
        # requests (confirmed live, org-wide: 652/652 closed requests have
        # due_date=NULL, all 18 open ones have it set — it looks like a
        # live/computed field tied to the current workflow stage rather than
        # a deadline captured at creation and preserved after closing), so a
        # "closed on/before due_date" check can never be true and on-time
        # compliance degenerates to "is anything currently open and
        # overdue" rather than a real historical rate. Revisit this once
        # due_date (or a dedicated deadline column) is actually preserved
        # through closure.
        compliance_pct = int((completed_requests / total_requests * 100)) if total_requests > 0 else 0

        # Data Quality Index (DQI) — % of active equipment in this scope
        # meeting all three data-readiness checks: nameplate completeness
        # (key fields filled), has at least one test result ever, and not
        # currently overdue for its next scheduled test. Pure computation
        # over existing tables (Equipment/TestAnalytics/TestingRequest) —
        # no new column or table. TestAnalytics (not EquipmentAnalytics) is
        # used for "has test history" because it's one row per test result,
        # so equipment with old-but-real test history still counts as
        # having history even if EquipmentAnalytics' own live snapshot were
        # ever cleared.
        from models import Equipment as _DqiEquipment, TestAnalytics as _DqiTestAnalytics
        dqi_eq_filters = [_DqiEquipment.organization_id == svc.org_id, _DqiEquipment.status == 'active']
        if dept_ids_for_scope:
            dqi_eq_filters.append(_DqiEquipment.department_id.in_(dept_ids_for_scope))
        dqi_equipment_rows = db.query(_DqiEquipment).filter(*dqi_eq_filters).all()
        dqi_total = len(dqi_equipment_rows)
        dqi_ready = 0
        if dqi_total > 0:
            dqi_eq_ids = [e.id for e in dqi_equipment_rows]
            dqi_has_test_ids = {
                row[0] for row in db.query(_DqiTestAnalytics.equipment_id)
                .filter(_DqiTestAnalytics.equipment_id.in_(dqi_eq_ids))
                .distinct().all()
            }
            dqi_overdue_ids = {
                row[0] for row in db.query(TestingRequest.equipment_id).filter(
                    TestingRequest.equipment_id.in_(dqi_eq_ids),
                    TestingRequest.request_category == 'test',
                    ~_closed_expr,
                    TestingRequest.due_date < _now(),
                ).distinct().all()
            }
            for e in dqi_equipment_rows:
                nameplate_ok = bool(
                    e.manufacturer and e.factory_serial_number
                    and e.year_of_manufacture and e.voltage_class
                    and e.commissioned_date
                )
                if nameplate_ok and e.id in dqi_has_test_ids and e.id not in dqi_overdue_ids:
                    dqi_ready += 1
        # No active equipment yet isn't a data-quality failure — default to
        # fully ready rather than 0, matching compliance_pct's own "no
        # evidence of a problem" convention elsewhere in this function.
        dqi_pct = int((dqi_ready / dqi_total) * 100) if dqi_total > 0 else 100

        return {
            "total_tests": total_requests,
            "overdue_count": overdue_count,
            "critical_count": critical_count,
            "pending_approval_count": pending_approval_count,
            "pending_assign_count": pending_assign_count,
            "pending_review_count": pending_review_count,
            "open_count": open_count,
            "closed_this_week_count": closed_this_week_count,
            "rejected_cancelled_count": rejected_cancelled_count,
            "compliance_pct": compliance_pct,
            "dqi_pct": dqi_pct,
            "dqi_ready_count": dqi_ready,
            "dqi_total_count": dqi_total,
        }

    def _calibration_summary(dept_ids_for_scope):
        """Zone-wide relay/ETV calibration KPIs (KPTCL spec §14.6's CEE
        RT & R&D Wing Dashboard) — compliance, T+0/T+7/T+15
        overdue-escalation buckets, and 30/60-day expiring-soon counts.
        Scoped once at the top level (not per rollup-table row, unlike
        _scope_counts) since these are whole-zone KPIs in the spec, not a
        per-substation breakdown — the old dashboard_role_kpi.py /cee-rt-rd
        endpoint (still live, unrelated to this consolidated dashboard) had
        a narrower version of this same idea (compliance/fail_count/one
        30-day expiring bucket only, no T+0/7/15 split).
        """
        from sqlalchemy import or_ as _or_cal

        cal_filters = [TestingRequest.organization_id == svc.org_id,
                        TestingRequest.is_calibration.is_(True)]
        if dept_ids_for_scope:
            cal_filters.append(TestingRequest.department_id.in_(dept_ids_for_scope))

        # Same closed-expression shape as _scope_counts' own _closed_expr —
        # not reused directly since that's local to _scope_counts' own
        # closure, not reachable from here.
        cal_closed_expr = _or_cal(
            TestingRequest.status == 'closed',
            TestingRequest.current_status_code.in_(terminal_status_codes),
        )

        now = _now()
        ninety_days = now - timedelta(days=90)
        cal_due_90 = db.query(func.count(TestingRequest.id)).filter(
            *cal_filters, TestingRequest.due_date.between(ninety_days, now),
        ).scalar() or 0
        cal_on_time_90 = db.query(func.count(TestingRequest.id)).filter(
            *cal_filters, TestingRequest.due_date.between(ninety_days, now), cal_closed_expr,
        ).scalar() or 0
        cal_compliance_pct = int((cal_on_time_90 / cal_due_90) * 100) if cal_due_90 > 0 else 100

        # T+0 / T+7 / T+15 — currently-open calibration requests bucketed by
        # how many days overdue they are, matching the spec's own
        # escalation-tier naming (an org's real escalation cadence — e.g.
        # notify at 0 days, escalate to next authority at 7, again at 15 —
        # isn't itself stored anywhere; this buckets by elapsed time, the
        # same information those escalation rules would act on).
        overdue_cal_rows = db.query(TestingRequest.due_date).filter(
            *cal_filters, ~cal_closed_expr, TestingRequest.due_date < now,
        ).all()
        cal_t0 = cal_t7 = cal_t15 = 0
        for (due_date,) in overdue_cal_rows:
            days_over = (now - due_date).days
            if days_over >= 15:
                cal_t15 += 1
            elif days_over >= 7:
                cal_t7 += 1
            else:
                cal_t0 += 1

        # The real pass/fail signal lives on the certificate's own TestResult
        # (test_data.recommendation_type, or test_data.overall_result as a
        # fallback — same priority order calibration_service.py's own
        # _get_latest_reading() already uses), NOT TestingRequest.status.
        # Confirmed live: calibration_hooks.py's _record_certificate_as_
        # test_result() hardcodes the TestResult.overall_result COLUMN to
        # "pass" unconditionally at creation — only test_data carries the
        # real value — and status=='rejected' reflects whether the workflow
        # itself was rejected (e.g. a malformed certificate upload), not
        # whether the calibration the certificate describes actually
        # passed. An officer can approve/verify a certificate that itself
        # says "Fail" or "Conditional" — workflow status stays 'completed',
        # not 'rejected' — so counting by status alone silently missed
        # those.
        from models import TestResult
        _cal_result = func.lower(func.coalesce(
            TestResult.test_data["recommendation_type"].astext,
            TestResult.test_data["overall_result"].astext,
        ))
        cal_fail_count = db.query(func.count(func.distinct(TestingRequest.id))).join(
            TestResult, TestResult.testing_request_id == TestingRequest.id,
        ).filter(*cal_filters, _cal_result == 'fail').scalar() or 0

        cal_expiring_30 = db.query(func.count(TestingRequest.id)).filter(
            *cal_filters, ~cal_closed_expr,
            TestingRequest.due_date.between(now, now + timedelta(days=30)),
        ).scalar() or 0
        cal_expiring_60 = db.query(func.count(TestingRequest.id)).filter(
            *cal_filters, ~cal_closed_expr,
            TestingRequest.due_date.between(now, now + timedelta(days=60)),
        ).scalar() or 0

        # 12-month FAIL-rate trend — "Calibration failure trend" (§14.6),
        # previously only ever a current-snapshot count with no history.
        # mts is the best available proxy for "when it closed/failed" —
        # same convention _scope_counts' closed_this_week_count already
        # uses, there's no dedicated closed_at/completed_at column.
        trend_cutoff = now - timedelta(days=365)
        month_col = func.date_trunc('month', TestingRequest.mts)
        trend_rows = db.query(
            month_col.label('month'), _cal_result, func.count(func.distinct(TestingRequest.id)),
        ).join(
            TestResult, TestResult.testing_request_id == TestingRequest.id,
        ).filter(
            *cal_filters, TestingRequest.mts >= trend_cutoff,
            TestingRequest.status.in_(['closed', 'rejected']),
        ).group_by('month', _cal_result).all()
        by_month: dict = {}
        for month, cal_result, count in trend_rows:
            key = month.strftime('%Y-%m') if month else 'unknown'
            entry = by_month.setdefault(key, {'total': 0, 'fail': 0})
            entry['total'] += count
            if cal_result == 'fail':
                entry['fail'] += count
        fail_rate_trend = [
            {
                "month": key,
                "total": v['total'],
                "fail": v['fail'],
                "fail_rate_pct": round(v['fail'] / v['total'] * 100, 1) if v['total'] > 0 else 0,
            }
            for key, v in sorted(by_month.items())
        ]

        # AI calibration-interval optimisation advisories (§14.6) — org-wide,
        # not re-scoped to dept_ids_for_scope: a cohort is (test type, make,
        # model), which spans departments by nature, and narrowing it to one
        # department would usually starve every cohort below
        # CALIBRATION_INTERVAL_MIN_CYCLES for no real reason (the same relay
        # model calibrated across several substations is still one real
        # reliability signal).
        from services.calibration_service import compute_interval_advisories
        try:
            interval_advisories = compute_interval_advisories(db, svc.org_id)
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "calibration interval advisory computation failed", exc_info=True
            )
            interval_advisories = []

        return {
            # Lets the frontend tell "no calibration activity at all in this
            # scope" apart from "100% compliant" — both leave compliance_pct
            # at 100, only one of them is worth showing a tile for.
            "due_90d": cal_due_90,
            "compliance_pct": cal_compliance_pct,
            "fail_count": cal_fail_count,
            "overdue_t0": cal_t0,
            "overdue_t7": cal_t7,
            "overdue_t15": cal_t15,
            "expiring_30d": cal_expiring_30,
            "expiring_60d": cal_expiring_60,
            "fail_rate_trend": fail_rate_trend,
            "interval_advisories": interval_advisories,
        }

    # Pending-approval TestingRequests in the given scope, most-recently-
    # submitted first — real, verifiable data (no invented "escalation"
    # duration; HierarchyAnalytics has no trend/history to compute one from,
    # see KNOWN SCOPE LIMIT note above this function).
    def _approval_queue(dept_ids_for_scope, limit=5):
        # Both kinds together — this raw list feeds a generic "here's what's
        # pending" panel. Scoped the same way pending_approval_count/
        # pending_review_count are above: only requests whose current
        # TrWfInstance stage is one the CALLING viewer's own role can_approve
        # on, not any request whose status code merely matches across the
        # org's other, unrelated workflow definitions too.
        viewer_stage_ids = viewer_approval_stage_ids | viewer_review_stage_ids
        if not viewer_stage_ids:
            return []
        q = db.query(TestingRequest).join(
            TrWfInstance, TrWfInstance.testing_request_id == TestingRequest.id,
        ).filter(
            TestingRequest.organization_id == svc.org_id,
            TrWfInstance.status == 'active',
            TrWfInstance.current_stage_id.in_(viewer_stage_ids),
        )
        if dept_ids_for_scope:
            q = q.filter(TestingRequest.department_id.in_(dept_ids_for_scope))
        rows = q.order_by(TestingRequest.mts.desc()).limit(limit).all()
        now = _now()
        out = []
        for r in rows:
            ueic = r.equipment.ueic if r.equipment else (
                r.equipment_type.name if r.equipment_type else "Unknown equipment")
            # Same equipment can carry several distinct pending requests (a
            # confirmed live case: 5 different test types requested on one
            # transformer, all at l2_pending_approval) — without the test
            # type, those rows are visually indistinguishable in the panel.
            test_type_name = r.test_type.name if r.test_type else None
            dept = db.query(OrgDepartment).filter(OrgDepartment.id == r.department_id).first()
            age_days = (now - _make_tz(r.mts)).days if r.mts else None
            out.append({
                "request_id": str(r.id),
                "request_number": r.request_number,
                "equipment_id": str(r.equipment_id) if r.equipment_id else None,
                "equipment_label": ueic,
                "test_type": test_type_name,
                "department_name": dept.name if dept else None,
                "originator": r.originator.firstname if getattr(r, "originator", None) else None,
                "age_days": age_days,
            })
        return out

    # can_approve_requests/can_review are already computed above, alongside
    # viewer_approval_stage_ids/viewer_review_stage_ids.

    # "Start Test" — can_edit is the right flag (confirmed live: for every
    # tester role in every workflow/org in this data, can_act_as_tester is
    # False everywhere; can_edit is the only permission ever True for them,
    # and always on the stage carrying the "complete" transition), but it
    # must be scoped to that SPECIFIC stage, not "does this role have
    # can_edit=True somewhere" — the "complete" action isn't reserved for a
    # fixed stage/level (e.g. "L4"); a workflow can put it anywhere. So:
    # can_edit on the current stage AND that stage has an outgoing
    # TrWfStageTransition with action_code='complete', found dynamically
    # per workflow rather than assuming a stage name/sequence number.
    from models import TrWfStageTransition
    can_test = False
    assigned_test_count = 0
    if current_user is not None and user_role_ids:
        viewer_edit_stage_ids = {
            row[0] for row in db.query(TrWfStageRole.stage_id).filter(
                TrWfStageRole.role_id.in_(user_role_ids),
                TrWfStageRole.can_edit.is_(True),
            ).all()
        }
        complete_stage_ids = {
            row[0] for row in db.query(TrWfStageTransition.from_stage_id).filter(
                TrWfStageTransition.from_stage_id.in_(viewer_edit_stage_ids),
                TrWfStageTransition.action_code == 'complete',
            ).distinct().all()
        } if viewer_edit_stage_ids else set()
        can_test = bool(complete_stage_ids)
        if complete_stage_ids:
            # Same "a capability with nothing behind it isn't worth a tile"
            # gate as pending_approval_count/pending_review_count — can_test
            # says the role COULD complete a test somewhere; this counts
            # requests actually assigned to THIS user, sitting right now at
            # one of those completable stages.
            assigned_test_count = db.query(func.count(TrWfInstance.id)).join(
                TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id,
            ).filter(
                TestingRequest.organization_id == svc.org_id,
                TestingRequest.department_id.in_(svc.dept_ids) if svc.dept_ids else True,
                TestingRequest.assigned_tester_id == current_user.id,
                TrWfInstance.status == 'active',
                TrWfInstance.current_stage_id.in_(complete_stage_ids),
            ).scalar() or 0

    from sqlalchemy import or_ as _or_tl

    def _ticket_lists(dept_ids_for_scope, limit=10):
        """This-week / open / closed-this-week / rejected-cancelled ticket
        rows, scoped exactly like _scope_counts' matching counts above —
        shared by both the leaf and branch shapes so a branch-scope KPI
        tile (e.g. "Rejected / Cancelled: 4" on a multi-substation zone)
        can actually expand into its own tickets, not just show a number.
        Previously this list-building only ran inside the leaf branch
        below, so any role whose own department has children (a branch
        view) got real counts on every tile but an empty, un-clickable
        list behind every one of them — confirmed live: AEE-R&D-level
        roles sitting on a branch department saw this; a role scoped to a
        single leaf station didn't, purely because of which shape their
        own department happened to resolve to, not a permissions
        difference between the two.
        """
        tl_filter = (TestingRequest.department_id.in_(dept_ids_for_scope)
                     if dept_ids_for_scope else TestingRequest.organization_id == svc.org_id)
        tl_closed_expr = _or_tl(
            TestingRequest.status == 'closed',
            TestingRequest.current_status_code.in_(terminal_status_codes),
        )
        tl_rejected_cancelled_expr = TestingRequest.id.in_(rejected_cancelled_request_ids)

        this_week_cutoff = _now() + timedelta(days=7)
        this_week_rows = (
            db.query(TestingRequest)
            .filter(
                TestingRequest.organization_id == svc.org_id,
                TestingRequest.department_id.in_(dept_ids_for_scope) if dept_ids_for_scope else True,
                TestingRequest.due_date.isnot(None),
                TestingRequest.due_date < this_week_cutoff,
                ~tl_closed_expr,
            )
            .order_by(TestingRequest.due_date.asc())
            .limit(limit)
            .all()
        )
        this_week = []
        for r in this_week_rows:
            ueic = r.equipment.ueic if r.equipment else (
                r.equipment_type.name if r.equipment_type else "Unknown equipment")
            this_week.append({
                "equipment_label": ueic,
                "equipment_id": str(r.equipment_id) if r.equipment_id else None,
                "request_id": str(r.id),
                "request_number": r.request_number,
                "test_type": r.test_type.name if r.test_type else None,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "overdue": _make_tz(r.due_date) < _now() if r.due_date else False,
            })

        def _rows(query_rows):
            out = []
            for r in query_rows:
                ueic = r.equipment.ueic if r.equipment else (
                    r.equipment_type.name if r.equipment_type else "Unknown equipment")
                # Which of the two outcomes THIS specific request actually
                # hit — rejected_cancelled_rows mixes both, so the badge
                # shown per-row must say which one, not a blanket combined
                # label. None for every other ticket list (open/closed),
                # where the distinction doesn't apply.
                outcome = None
                outcome_color = None
                if r.id in rejected_request_ids:
                    outcome = "REJECTED"
                    outcome_color = TrWfOutcomeColors.get("rejected")
                elif r.id in cancelled_request_ids:
                    outcome = "CANCELLED"
                    outcome_color = TrWfOutcomeColors.get("cancelled")
                out.append({
                    "equipment_label": ueic,
                    "equipment_id": str(r.equipment_id) if r.equipment_id else None,
                    "request_id": str(r.id),
                    "request_number": r.request_number,
                    "test_type": r.test_type.name if r.test_type else None,
                    "due_date": r.due_date.isoformat() if r.due_date else None,
                    "outcome": outcome,
                    # Canonical color for that outcome (category_labels.py's
                    # TrWfOutcomeColors), served here so the frontend badge
                    # doesn't hardcode it separately.
                    "outcome_color": outcome_color,
                })
            return out

        open_rows = (
            db.query(TestingRequest)
            .filter(tl_filter, ~tl_closed_expr)
            .order_by(TestingRequest.mts.desc())
            .limit(limit)
            .all()
        )
        # Excludes rejected/cancelled — those get their own card/list
        # (rejected_cancelled_tickets below) rather than counting toward
        # "Closed This Week", which is meant to read as genuine completions.
        closed_this_week_rows = (
            db.query(TestingRequest)
            .filter(tl_filter, tl_closed_expr, ~tl_rejected_cancelled_expr,
                    TestingRequest.mts >= _now() - timedelta(days=7))
            .order_by(TestingRequest.mts.desc())
            .limit(limit)
            .all()
        )
        rejected_cancelled_rows = (
            db.query(TestingRequest)
            .filter(tl_filter, tl_rejected_cancelled_expr)
            .order_by(TestingRequest.mts.desc())
            .limit(limit)
            .all()
        )

        return {
            "this_week": this_week,
            "open_tickets": _rows(open_rows),
            "closed_this_week_tickets": _rows(closed_this_week_rows),
            "rejected_cancelled_tickets": _rows(rejected_cancelled_rows),
        }

    if not children:
        # Same TestResult evaluation query flagged_equipment() (dashboard_service.py)
        # already uses org-wide — reimplemented dept-scoped here since that
        # widget doesn't filter by dept_ids at all (a pre-existing gap there,
        # not something to inherit into a single-substation leaf view).
        from models import TestResult
        flagged_rows = (
            db.query(TestResult)
            .join(TestingRequest, TestingRequest.id == TestResult.testing_request_id)
            .filter(
                TestResult.organization_id == svc.org_id,
                TestResult.evaluation_result.isnot(None),
                TestResult.evaluation_result["overall"].astext.in_(["CRITICAL", "ALERT"]),
                TestingRequest.department_id.in_(svc.dept_ids) if svc.dept_ids else True,
            )
            .order_by(TestResult.cts.desc())
            .limit(10)
            .all()
        )
        flagged = []
        seen_eq = set()
        for r in flagged_rows:
            req = r.testing_request
            if not req:
                continue
            eq_key = str(req.equipment_id or req.equipment_type_id or r.id)
            if eq_key in seen_eq:
                continue
            seen_eq.add(eq_key)
            ueic = req.equipment.ueic if req.equipment else (
                req.equipment_type.name if req.equipment_type else "Unknown equipment")
            ev = r.evaluation_result or {}
            flagged.append({
                "equipment_label": ueic,
                "equipment_id": str(req.equipment_id) if req.equipment_id else None,
                "overall": ev.get("overall", "ALERT"),
                "test_result_id": str(r.id),
                "request_id": str(req.id),
                "request_number": req.request_number,
            })

        # Shared with the branch shape below — see _ticket_lists' docstring.
        ticket_lists = _ticket_lists(svc.dept_ids)

        # Same closed-expression definition as _scope_counts'/_ticket_lists'
        # closed_this_week_count (legacy .status=='closed' OR tr_wf terminal
        # current_status_code, via terminal_status_codes) — only needed here
        # for the DQI overdue-equipment check below.
        leaf_closed_expr = _or_tl(
            TestingRequest.status == 'closed',
            TestingRequest.current_status_code.in_(terminal_status_codes),
        )

        # Total equipment at this one station — the mockup's 4th leaf KPI
        # tile is "Equipment", not "Awaiting Approval" (an individual tester
        # doesn't approve anything; that's a supervisor-level concept, see
        # _scope_counts' pending_approval_count for the branch-scope version).
        from models import Equipment, TestAnalytics
        equipment_count = db.query(func.count(Equipment.id)).filter(
            Equipment.organization_id == svc.org_id,
            Equipment.department_id.in_(svc.dept_ids) if svc.dept_ids else True,
        ).scalar() or 0

        # Equipment failing at least one DQI check (routers/dashboard_kpi.py's
        # _scope_counts computes the same three checks for the dqi_pct
        # number — this is the per-equipment remediation list behind it,
        # leaf-scope only since a task list is only actionable at a single
        # substation, matching open_tickets/closed_this_week_tickets below).
        dqi_all_eq = db.query(Equipment).filter(
            Equipment.organization_id == svc.org_id,
            Equipment.status == 'active',
            Equipment.department_id.in_(svc.dept_ids) if svc.dept_ids else True,
        ).all()
        dqi_issues = []
        if dqi_all_eq:
            _dqi_eq_ids = [e.id for e in dqi_all_eq]
            _dqi_has_test = {
                row[0] for row in db.query(TestAnalytics.equipment_id)
                .filter(TestAnalytics.equipment_id.in_(_dqi_eq_ids))
                .distinct().all()
            }
            _dqi_overdue = {
                row[0] for row in db.query(TestingRequest.equipment_id).filter(
                    TestingRequest.equipment_id.in_(_dqi_eq_ids),
                    TestingRequest.request_category == 'test',
                    ~leaf_closed_expr,
                    TestingRequest.due_date < _now(),
                ).distinct().all()
            }
            for e in dqi_all_eq:
                # Each missing nameplate field gets its own issue code
                # instead of one blanket "incomplete_nameplate" flag, so
                # the remediation list says exactly what to go fill in.
                issues = []
                if not e.manufacturer:
                    issues.append('missing_manufacturer')
                if not e.factory_serial_number:
                    issues.append('missing_serial_number')
                if not e.year_of_manufacture:
                    issues.append('missing_year_of_manufacture')
                if not e.voltage_class:
                    issues.append('missing_voltage_class')
                if not e.commissioned_date:
                    issues.append('missing_commissioned_date')
                if e.id not in _dqi_has_test:
                    issues.append('no_test_history')
                if e.id in _dqi_overdue:
                    issues.append('overdue_test')
                if issues:
                    dqi_issues.append({
                        "equipment_id": str(e.id),
                        "equipment_label": e.ueic,
                        "issues": issues,
                    })

        return {
            "shape": "leaf",
            "scope_name": scope_name,
            "scope_level": scope_level,
            "flagged_equipment": flagged,
            "equipment_count": equipment_count,
            "dqi_issues": dqi_issues,
            "can_test": can_test,
            "assigned_test_count": assigned_test_count,
            "can_approve_requests": can_approve_requests,
            "can_assign_requests": can_assign_requests,
            "can_review": can_review,
            "weekly_trend": _weekly_trend(svc.dept_ids),
            "calibration": _calibration_summary(svc.dept_ids),
            **ticket_lists,
            **_scope_counts(svc.dept_ids),
        }

    def _failure_cohort_summary():
        # Per make/model reliability (§2) — org-wide like the calibration
        # interval advisories above, and for the same reason: a cohort is
        # (equipment type, manufacturer, model_number), which spans
        # departments by nature, so scoping it to one branch would starve
        # most cohorts below FAILURE_COHORT_MIN_UNITS for no real reason.
        from services.equipment_service import EquipmentService
        try:
            return EquipmentService.compute_failure_cohort_stats(db, svc.org_id)
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "failure cohort reliability computation failed", exc_info=True
            )
            return []

    rows = []
    for child in children:
        subtree_ids = get_dept_subtree_ids(db, child.id)
        own_child_count = db.query(func.count(OrgDepartment.id)).filter(
            OrgDepartment.parent_department_id == child.id,
        ).scalar() or 0
        child_ha = db.query(HierarchyAnalytics).filter(
            HierarchyAnalytics.department_id == child.id).first()
        assigned_name = None
        if own_child_count == 0:
            # This child is itself a leaf — show who's assigned to it, same
            # as the mockup's substation rows ("Suresh Patil").
            assigned = (
                db.query(User.firstname, User.lastname)
                .join(OrgUserRole, OrgUserRole.user_id == User.id)
                .filter(
                    OrgUserRole.org_role_id.in_(tester_capable_role_ids) if tester_capable_role_ids
                    else OrgUserRole.org_role_id.in_([]),
                    OrgUserRole.department_id == child.id,
                    OrgUserRole.is_active.is_(True),
                    User.isactive.is_(True),
                )
                .first()
            )
            assigned_name = f"{assigned.firstname} {assigned.lastname}".strip() if assigned else None
        rows.append({
            "department_id": str(child.id),
            "department_name": child.name,
            "level_type": child_ha.level_type if child_ha else None,
            "assigned_user": assigned_name,
            # >0 only when this child is itself a branch — the mockup's zone
            # rows show "3 circles" instead of a person for exactly this case.
            "child_count": own_child_count,
            **_scope_counts(subtree_ids),
        })

    rows.sort(key=lambda r: r["compliance_pct"])
    return {
        "shape": "branch",
        "scope_name": scope_name,
        "scope_level": scope_level,
        # Full-subtree totals computed the same way as every row below (not a
        # separately-tracked figure), so the top-line numbers can't drift out
        # of sync with what the rollup rows say they should add up to.
        "summary": _scope_counts(svc.dept_ids),
        "approvals": _approval_queue(svc.dept_ids),
        "can_approve_requests": can_approve_requests,
        "can_review": can_review,
        "weekly_trend": _weekly_trend(svc.dept_ids),
        "calibration": _calibration_summary(svc.dept_ids),
        "failure_reliability": _failure_cohort_summary(),
        "rows": rows,
        # Full-subtree ticket lists behind the summary counts above — see
        # _ticket_lists' docstring for why a branch shape needs these too,
        # not just a leaf.
        **_ticket_lists(svc.dept_ids),
    }


# ── Unified overview — one endpoint for the whole org-hierarchy role chain ──
#
# Deliberately role-agnostic: the response shape is decided entirely by
# _build_department_rollup's leaf/branch check on the caller's own resolved
# department, not by which role or module asked. Any of AE_JE/AEE/EE-TLSS/
# SEE/CEE/the RT variants can point default_module_id at the same Module and
# get a correctly-scoped view — enabling a new role on this dashboard is a
# database change (repoint default_module_id), never a code change.
@router.get("/overview")
def get_overview_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = _svc(db, current_user, org_id, dept_id)
    result = _build_department_rollup(db, svc, current_user=current_user)
    # Full department-subtree id list this rollup's own KPI counts were
    # computed over (svc.dept_ids) — NOT just the single scope id already in
    # _dept_id. The CM Kanban Board button needs this: confirmed live, a
    # branch-scoped user (e.g. AEE_MAINTENANCE assigned to "Bagalkot", which
    # has 29 child substations) has ZERO TestingRequests filed directly
    # against that branch department id itself — every real request sits
    # under one of its children. testing_requests.py's list endpoint uses
    # its department_ids filter AS GIVEN with no subtree expansion (by
    # design, for callers that already know their exact set), so passing
    # only the single _dept_id there silently showed 0 tickets for every
    # branch-scoped role, while an org admin (no department filter applied
    # at all) saw everything. This exposes the already-resolved subtree list
    # so the Kanban board can pass the same scope this page's own counts use.
    result['_dept_ids'] = (
        [str(d) for d in svc.dept_ids] if svc.dept_ids
        else [str(svc.dept_id)] if svc.dept_id
        else None
    )
    return result


@router.get("/see")
def get_see_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """SEE Dashboard - Circle-level supervision."""
    from models import TestingRequest, Equipment, OrgRole
    from sqlalchemy import func
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id, dept_id)
    dept_ids = svc.dept_ids
    tr_scope = [TestingRequest.department_id.in_(dept_ids)] if dept_ids else []
    eq_scope = [Equipment.department_id.in_(dept_ids)] if dept_ids else []

    # Total equipment
    total_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id, *eq_scope,
        Equipment.status == 'active'
    ).scalar() or 0

    # Circle Compliance (test completion rate)
    ninety_days_ago = datetime.now() - timedelta(days=90)
    total_requests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id, *tr_scope,
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0

    from services.dashboard_service import TR_WF_CLOSED_STATUS_CODES
    from sqlalchemy import or_ as _or
    completed_requests = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id, *tr_scope,
        _or(
            TestingRequest.status == 'closed',  # 'completed' isn't a real status value in this data
            TestingRequest.current_status_code.in_(TR_WF_CLOSED_STATUS_CODES),
        ),
        TestingRequest.cts >= ninety_days_ago
    ).scalar() or 0

    circle_compliance = int((completed_requests / total_requests * 100)) if total_requests > 0 else 0

    # Pending Approvals
    pending_approvals = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id, *tr_scope,
        TestingRequest.status.in_(['submitted', 'pending_approval'])
    ).scalar() or 0

    # Critical Issues (equipment under repair)
    critical_issues = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id, *eq_scope,
        Equipment.status == 'under_repair'
    ).scalar() or 0

    # Pending reviews list
    pending_reviews = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id, *tr_scope,
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
        'department_rollup': _build_department_rollup(db, svc, current_user=current_user),
    }


@router.get("/cee")
def get_cee_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """CEE Dashboard - Zone-level executive management."""
    from models import TestingRequest, Equipment
    from sqlalchemy import func
    from datetime import datetime, timedelta

    svc = _svc(db, current_user, org_id, dept_id)
    dept_ids = svc.dept_ids
    tr_scope = [TestingRequest.department_id.in_(dept_ids)] if dept_ids else []
    eq_scope = [Equipment.department_id.in_(dept_ids)] if dept_ids else []

    # Zone Equipment
    zone_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id, *eq_scope,
        Equipment.status == 'active'
    ).scalar() or 0

    # Zone Reliability (percentage of equipment in active status)
    healthy_equipment = db.query(func.count(Equipment.id)).filter(
        Equipment.organization_id == svc.org_id, *eq_scope,
        Equipment.status == 'active'
    ).scalar() or 0

    zone_reliability = round((healthy_equipment / zone_equipment * 100), 1) if zone_equipment > 0 else 0.0

    # Major Decisions (pending high-value approvals)
    major_decisions = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id, *tr_scope,
        TestingRequest.status.in_(['submitted', 'pending_approval'])
    ).scalar() or 0

    # Pending strategic decisions
    strategic_decisions = db.query(TestingRequest).filter(
        TestingRequest.organization_id == svc.org_id, *tr_scope,
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
        'department_rollup': _build_department_rollup(db, svc, current_user=current_user),
    }
