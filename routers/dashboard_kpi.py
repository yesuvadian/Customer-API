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

import config
from auth_utils import get_current_user
from database import get_db
from models import User
from services.dashboard_service import DashboardService, invalidate_dashboard_cache
from category_labels import TrWfOutcomeColors
from utils.business_days import business_days_between, add_business_hours

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


def _testkit_type_ids(db: Session) -> list:
    """CategoryMaster IDs for the 'Testing Kit' equipment type. Testing kits
    aren't real substation assets — routers/analytics.py's AI Analytics
    Dashboard already excludes them from its equipment totals via this exact
    lookup; this router's own equipment_count/total_equipment metrics didn't,
    so the two dashboards' headline equipment counts silently disagreed by
    exactly the org's testing-kit count. Not org-scoped: the type itself is a
    global CategoryMaster row, shared across orgs."""
    from models import CategoryMaster
    return [c.id for c in db.query(CategoryMaster.id).filter(
        CategoryMaster.name.ilike("%testing kit%")).all()]


def _equipment_scope_filters(db: Session, org_id, dept_ids=None) -> list:
    """Shared equipment-scope filters for a headline equipment count:
    excludes retired equipment and Testing Kits, matching the AI Analytics
    Dashboard's definition (routers/analytics.py's real_total_equipment) so
    this dashboard's equipment totals stop disagreeing with it."""
    from models import Equipment
    filters = [Equipment.organization_id == org_id, Equipment.status != 'retired']
    testkit_ids = _testkit_type_ids(db)
    if testkit_ids:
        filters.append(~Equipment.equipment_type_id.in_(testkit_ids))
    if dept_ids:
        filters.append(Equipment.department_id.in_(dept_ids))
    return filters


def _critical_equipment_count(db: Session, org_id, dept_ids=None) -> int:
    """Shared 'Critical' equipment count: EquipmentAnalytics.risk_level ==
    'Critical' (the AnalyticsEngine's health-score-driven classification) —
    NOT Equipment.status == 'under_repair', which this router's per-role
    endpoints used to check instead. That flag is a manual repair marker set
    independently of test results, so it silently missed every equipment
    whose Critical health score never triggered a repair ticket — confirmed
    live: 16 equipment sit at risk_level='Critical' org-wide while 0 are
    status='under_repair', so the old logic always showed 0. Matches the AI
    Analytics Dashboard's and _build_department_rollup's own critical_count
    definition."""
    from models import EquipmentAnalytics
    from sqlalchemy import func
    filters = [EquipmentAnalytics.organization_id == org_id, EquipmentAnalytics.risk_level == 'Critical']
    if dept_ids:
        filters.append(EquipmentAnalytics.department_id.in_(dept_ids))
    return db.query(func.count(EquipmentAnalytics.id)).filter(*filters).scalar() or 0


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

    # dept_ids intentionally omitted: every other metric in this endpoint
    # (pending_approvals, assigned_tests, maintenance_due below) is org-wide
    # only, with no department scoping — matching that instead of scoping
    # just this one count keeps the endpoint internally consistent.
    equipment_count = db.query(func.count(Equipment.id)).filter(
        *_equipment_scope_filters(db, svc.org_id)
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

    alert_count = _critical_equipment_count(db, svc.org_id)

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

    # Test Compliance Rate — dept_ids omitted: the rest of this endpoint's
    # metrics (overdue_tests, open_remediation, etc.) are org-wide only too.
    total_equipment = db.query(func.count(Equipment.id)).filter(
        *_equipment_scope_filters(db, svc.org_id)
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

    # ALERT/CRITICAL flags — health-score-driven (EquipmentAnalytics.risk_level),
    # not Equipment.status == 'under_repair' (a manual repair marker set
    # independently of test results, so it missed every equipment whose
    # Critical score never triggered a repair ticket).
    alert_critical = _critical_equipment_count(db, svc.org_id)

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
# The 7 DQI (Data Quality Index) checks — 5 Equipment nameplate-field names
# plus the two other checks ('test_history'/'overdue_test') — mirrored by
# DqiRuleConfig's seed data (alter_dqi_rule_config.py). Used only as the
# fallback when that table hasn't been seeded yet; the live source of truth
# for which of these are actually active is always the DB table itself.
_DQI_ALL_KEYS = (
    "manufacturer", "factory_serial_number", "year_of_manufacture",
    "voltage_class", "commissioned_date", "test_history", "overdue_test",
)

# Historical exception: this key's remediation-list issue code was
# 'missing_serial_number', not 'missing_factory_serial_number', from before
# per-field checks became data-driven — kept as-is so the existing
# 'MISSING SERIAL NO.' badge label (base_role_dashboard.dart's
# _dqiIssueLabels) keeps matching for this specific key. Any other/new key
# just gets 'missing_<key>'.
_DQI_ISSUE_CODE_OVERRIDES = {"factory_serial_number": "missing_serial_number"}


def _dqi_missing_issue_code(key: str) -> str:
    return _DQI_ISSUE_CODE_OVERRIDES.get(key, f"missing_{key}")


def _dqi_active_key_scopes(db: Session) -> dict:
    """{key: None-or-set-of-equipment_type_ids} for every currently active
    DQI rule — the single source of truth for both the aggregate dqi_pct
    (_build_department_rollup, via _dqi_compute_scope below) and the
    standalone GET /dashboard/dqi-issues pagination endpoint, so a rule
    toggle/scope edit is honored identically everywhere the moment it's
    saved — this is a fresh DB query every call, nothing cached.

    None scope = the check applies to every equipment type (the original
    global behavior, and what every row got before per-type scoping
    existed); a non-empty set restricts it to just those CategoryMaster
    ids (Equipment.equipment_type_id) — see DqiRuleConfig's own docstring
    in models.py for why this exists (a CT/PT/transformer-specific field
    would otherwise incorrectly flag every OTHER equipment type too).
    """
    from models import DqiRuleConfig
    rows = db.query(
        DqiRuleConfig.key, DqiRuleConfig.is_active, DqiRuleConfig.equipment_type_ids,
    ).all()
    if not rows:
        # Table not seeded yet (alter_dqi_rule_config.py never run) — fall
        # back to every check active and unscoped, matching the original
        # hardcoded behavior, rather than silently scoring everything 100%.
        return {k: None for k in _DQI_ALL_KEYS}
    return {
        key: (set(type_ids) if type_ids else None)
        for key, active, type_ids in rows if active
    }


def _dqi_compute_scope(db: Session, org_id, dept_ids_for_scope, key_scopes: dict, closed_expr) -> dict:
    """Core DQI evaluation for one department scope: for every active
    check in `key_scopes`, applies it only to equipment whose
    equipment_type_id falls within that check's own scope (None = every
    type) — then returns BOTH the aggregate ready-count (dqi_pct's
    numerator) and the full per-equipment issue list (the remediation
    panel) from a SINGLE pass over the same equipment/checks, so the two
    numbers can never independently drift out of sync the way two
    separately-written computations could.

    Returns {"total": int, "ready": int, "issues": [...]}. `issues` is
    NOT paginated here — callers slice/offset it themselves (see
    _build_department_rollup's leaf/branch return blocks, and the
    standalone GET /dashboard/dqi-issues "Load More" endpoint).
    """
    from models import (
        Equipment as _DqiEquipment, TestAnalytics as _DqiTestAnalytics, TestingRequest,
        DQI_SPECIAL_KEY_LABELS, get_dqi_live_only_field_keys, dqi_fetch_raw_field_values,
    )
    from services.dashboard_service import _now

    eq_filters = [_DqiEquipment.organization_id == org_id, _DqiEquipment.status == 'active']
    if dept_ids_for_scope:
        eq_filters.append(_DqiEquipment.department_id.in_(dept_ids_for_scope))
    equipment_rows = db.query(_DqiEquipment).filter(*eq_filters).all()
    total = len(equipment_rows)
    if total == 0:
        return {"total": 0, "ready": 0, "issues": []}

    eq_ids = [e.id for e in equipment_rows]
    special_keys = set(DQI_SPECIAL_KEY_LABELS)
    field_keys = [k for k in key_scopes if k not in special_keys]

    has_test_ids = set()
    if 'test_history' in key_scopes:
        has_test_ids = {
            row[0] for row in db.query(_DqiTestAnalytics.equipment_id)
            .filter(_DqiTestAnalytics.equipment_id.in_(eq_ids)).distinct().all()
        }
    overdue_ids = set()
    if 'overdue_test' in key_scopes:
        overdue_ids = {
            row[0] for row in db.query(TestingRequest.equipment_id).filter(
                TestingRequest.equipment_id.in_(eq_ids),
                TestingRequest.request_category == 'test',
                ~closed_expr,
                TestingRequest.due_date < _now(),
            ).distinct().all()
        }

    # ORM-mapped keys read via plain getattr (no extra query — the rows are
    # already loaded); anything else is a live-only raw Postgres column
    # (models.py's get_dqi_live_only_field_keys/dqi_fetch_raw_field_values)
    # — one batched query per request for those, not one per row/key.
    orm_mapped = {c.name for c in _DqiEquipment.__table__.columns}
    raw_candidates = [k for k in field_keys if k not in orm_mapped]
    safe_raw_keys = (
        [k for k in raw_candidates if k in get_dqi_live_only_field_keys(db)]
        if raw_candidates else []
    )
    raw_values = dqi_fetch_raw_field_values(db, safe_raw_keys, eq_ids) if safe_raw_keys else {}

    def field_value(e, key):
        if key in orm_mapped:
            return getattr(e, key, None)
        return raw_values.get(key, {}).get(e.id)

    def key_applies(key, equipment_type_id):
        scope = key_scopes.get(key)
        return scope is None or equipment_type_id in scope

    ready = 0
    issues_out = []
    for e in equipment_rows:
        # not in (None, '') / in (None, '') rather than plain truthiness —
        # a real 0/0.0 (e.g. latitude/longitude/impedance_pct at the
        # equator, or a genuine zero reading) counts as present, only an
        # actual empty value doesn't.
        issues = []
        for key in sorted(field_keys):
            if not key_applies(key, e.equipment_type_id):
                continue
            if field_value(e, key) in (None, ''):
                issues.append(_dqi_missing_issue_code(key))
        if ('test_history' in key_scopes and key_applies('test_history', e.equipment_type_id)
                and e.id not in has_test_ids):
            issues.append('no_test_history')
        if ('overdue_test' in key_scopes and key_applies('overdue_test', e.equipment_type_id)
                and e.id in overdue_ids):
            issues.append('overdue_test')
        if issues:
            issues_out.append({
                "equipment_id": str(e.id),
                "equipment_label": e.ueic,
                "issues": issues,
            })
        else:
            ready += 1

    return {"total": total, "ready": ready, "issues": issues_out}


def _dqi_closed_expr_for_org(db: Session, org_id):
    """Same 'closed' definition used throughout this file's ticket/DQI
    counts — legacy TestingRequest.status=='closed' OR whatever this org's
    OWN tr_wf terminal status codes are (per-org workflow config, not a
    fixed set — a custom workflow can name/count its terminal statuses
    differently). Standalone version of the computation
    _build_department_rollup does inline, for GET /dashboard/dqi-issues
    (the "Load More" pagination endpoint) to call without needing the
    whole rollup around it.
    """
    from sqlalchemy import or_ as _or_dqi_closed
    from models import TrWfStatus, TrWfDefinition, TestingRequest
    terminal_status_rows = (
        db.query(TrWfStatus.status_code)
        .join(TrWfDefinition, TrWfDefinition.id == TrWfStatus.wf_definition_id)
        .filter(TrWfDefinition.org_id == org_id, TrWfStatus.is_terminal.is_(True))
        .all()
    )
    terminal_status_codes = list({row[0] for row in terminal_status_rows})
    return _or_dqi_closed(
        TestingRequest.status == 'closed',
        TestingRequest.current_status_code.in_(terminal_status_codes),
    )


def _overdue_tickets_list(db: Session, org_id, dept_ids_for_scope, limit=None, offset=0):
    """Every currently-open, non-calibration TestingRequest past its
    due_date — the actionable full list behind _scope_counts'
    overdue_count (same "not closed AND due_date < now" filter, via the
    shared _dqi_closed_expr_for_org so both agree on what "closed" means
    for this org). NOT the same set as _build_department_rollup's old
    `this_week` source for this panel: that list is a 7-day due-date
    WINDOW (today through +7 days) which happens to flag some of its
    rows `overdue: true`, capped at its own limit=10 default — confirmed
    live, overdue_count said 23 but the drill-down only ever showed up
    to 10, and only the ones due within a week of each other, not the
    true full overdue set. Standalone module-level function (not nested
    in _build_department_rollup) the same way _dqi_closed_expr_for_org
    is, so GET /dashboard/overdue-tickets (the "Load More" pagination
    endpoint) can call it without needing the whole rollup around it.

    is_calibration excluded: calibration requests get their own Overdue
    T+0/T+7/T+15 buckets in the Calibration section (validity-expiry
    based, not this ticket due_date) — counting them here too would
    double them into both places on the same dashboard.
    """
    from models import TestingRequest
    from services.dashboard_service import _now
    closed_expr = _dqi_closed_expr_for_org(db, org_id)
    tr_filters = [TestingRequest.organization_id == org_id]
    if dept_ids_for_scope:
        tr_filters.append(TestingRequest.department_id.in_(dept_ids_for_scope))

    rows = (
        db.query(TestingRequest)
        .filter(
            *tr_filters,
            ~closed_expr,
            TestingRequest.is_calibration.is_(False),
            TestingRequest.due_date.isnot(None),
            TestingRequest.due_date < _now(),
        )
        .order_by(TestingRequest.due_date.asc())
        .all()
    )
    out = []
    for r in rows:
        ueic = r.equipment.ueic if r.equipment else (
            r.equipment_type.name if r.equipment_type else "Unknown equipment")
        out.append({
            "equipment_label": ueic,
            "equipment_id": str(r.equipment_id) if r.equipment_id else None,
            "request_id": str(r.id),
            "request_number": r.request_number,
            "test_type": r.test_type.name if r.test_type else None,
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "overdue": True,
        })
    total = len(out)
    page = out[offset:offset + limit] if limit is not None else out[offset:]
    return page, total


def _rejected_cancelled_ids(db: Session, org_id):
    """(rejected_request_ids, cancelled_request_ids) for this org —
    standalone version of the computation _build_department_rollup does
    inline, for the panel "Load More" endpoints below to call without
    needing the whole rollup around them. Deliberately NOT read off
    current_status_code (see _build_department_rollup's own comment on
    this — a terminal transition's own terminal_status_id can fail to
    resolve and fall back to "last TrWfStatus by sequence", silently
    mislabeling a rejection as a cancellation there). The LAST
    is_terminal=True TrWfAuditLog row for a request's workflow instance is
    the actual button that closed it, so its action_code is ground truth.
    """
    from models import TrWfAuditLog as _TrWfAuditLog, TestingRequest
    terminal_audit_rows = (
        db.query(_TrWfAuditLog.testing_request_id, _TrWfAuditLog.action_code)
        .join(TestingRequest, TestingRequest.id == _TrWfAuditLog.testing_request_id)
        .filter(
            TestingRequest.organization_id == org_id,
            _TrWfAuditLog.is_terminal.is_(True),
        ).all()
    )
    rejected_request_ids = {
        rid for rid, code in terminal_audit_rows if 'reject' in (code or '').lower()
    }
    cancelled_request_ids = {
        rid for rid, code in terminal_audit_rows if 'cancel' in (code or '').lower()
    }
    return rejected_request_ids, cancelled_request_ids


def _open_tickets_list(db: Session, org_id, dept_ids_for_scope, limit=None, offset=0):
    """Every currently-open TestingRequest — the actionable full list
    behind _scope_counts' open_count, not capped at _ticket_lists' old
    fixed 10-row limit (confirmed live: open_count said 26, the drill-down
    only ever showed 10). Standalone module-level function (like
    _overdue_tickets_list above) so GET /dashboard/open-tickets' "Load
    More" pagination can call it without the whole rollup around it.
    """
    from models import TestingRequest
    closed_expr = _dqi_closed_expr_for_org(db, org_id)
    tr_filters = [TestingRequest.organization_id == org_id]
    if dept_ids_for_scope:
        tr_filters.append(TestingRequest.department_id.in_(dept_ids_for_scope))
    rows = (
        db.query(TestingRequest)
        .filter(*tr_filters, ~closed_expr)
        .order_by(TestingRequest.mts.desc())
        .all()
    )
    out = []
    for r in rows:
        ueic = r.equipment.ueic if r.equipment else (
            r.equipment_type.name if r.equipment_type else "Unknown equipment")
        out.append({
            "equipment_label": ueic,
            "equipment_id": str(r.equipment_id) if r.equipment_id else None,
            "request_id": str(r.id),
            "request_number": r.request_number,
            "test_type": r.test_type.name if r.test_type else None,
            "due_date": r.due_date.isoformat() if r.due_date else None,
        })
    total = len(out)
    page = out[offset:offset + limit] if limit is not None else out[offset:]
    return page, total


def _closed_this_week_tickets_list(db: Session, org_id, dept_ids_for_scope, limit=None, offset=0):
    """Every TestingRequest closed in the last 7 days, excluding rejected/
    cancelled (those get their own list below — this one is meant to read
    as genuine completions, same as _scope_counts' closed_this_week_count
    it's the actionable list behind). Standalone module-level function for
    GET /dashboard/closed-tickets' "Load More" pagination.
    """
    from datetime import timedelta
    from models import TestingRequest
    from services.dashboard_service import _now
    closed_expr = _dqi_closed_expr_for_org(db, org_id)
    rejected_ids, cancelled_ids = _rejected_cancelled_ids(db, org_id)
    rejected_cancelled_expr = TestingRequest.id.in_(rejected_ids | cancelled_ids)
    tr_filters = [TestingRequest.organization_id == org_id]
    if dept_ids_for_scope:
        tr_filters.append(TestingRequest.department_id.in_(dept_ids_for_scope))
    rows = (
        db.query(TestingRequest)
        .filter(
            *tr_filters,
            closed_expr,
            ~rejected_cancelled_expr,
            TestingRequest.mts >= _now() - timedelta(days=7),
        )
        .order_by(TestingRequest.mts.desc())
        .all()
    )
    out = []
    for r in rows:
        ueic = r.equipment.ueic if r.equipment else (
            r.equipment_type.name if r.equipment_type else "Unknown equipment")
        out.append({
            "equipment_label": ueic,
            "equipment_id": str(r.equipment_id) if r.equipment_id else None,
            "request_id": str(r.id),
            "request_number": r.request_number,
            "test_type": r.test_type.name if r.test_type else None,
            "due_date": r.due_date.isoformat() if r.due_date else None,
        })
    total = len(out)
    page = out[offset:offset + limit] if limit is not None else out[offset:]
    return page, total


def _rejected_cancelled_tickets_list(db: Session, org_id, dept_ids_for_scope, limit=None, offset=0):
    """Every rejected or cancelled TestingRequest — the actionable full
    list behind _scope_counts' rejected_cancelled_count. Standalone
    module-level function for GET /dashboard/rejected-cancelled-tickets'
    "Load More" pagination.
    """
    from models import TestingRequest
    from category_labels import TrWfOutcomeColors
    rejected_ids, cancelled_ids = _rejected_cancelled_ids(db, org_id)
    rejected_cancelled_expr = TestingRequest.id.in_(rejected_ids | cancelled_ids)
    tr_filters = [TestingRequest.organization_id == org_id]
    if dept_ids_for_scope:
        tr_filters.append(TestingRequest.department_id.in_(dept_ids_for_scope))
    rows = (
        db.query(TestingRequest)
        .filter(*tr_filters, rejected_cancelled_expr)
        .order_by(TestingRequest.mts.desc())
        .all()
    )
    out = []
    for r in rows:
        ueic = r.equipment.ueic if r.equipment else (
            r.equipment_type.name if r.equipment_type else "Unknown equipment")
        outcome = None
        outcome_color = None
        if r.id in rejected_ids:
            outcome = "REJECTED"
            outcome_color = TrWfOutcomeColors.get("rejected")
        elif r.id in cancelled_ids:
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
            "outcome_color": outcome_color,
        })
    total = len(out)
    page = out[offset:offset + limit] if limit is not None else out[offset:]
    return page, total


def _critical_equipment_list(db: Session, org_id, dept_ids_for_scope, limit=None, offset=0):
    """Every equipment unit whose EquipmentAnalytics.risk_level is
    'Critical' — the actionable full list behind _scope_counts'
    critical_count (same definition the AI Analytics Dashboard uses).
    Standalone module-level function for
    GET /dashboard/critical-equipment' "Load More" pagination.
    """
    from models import EquipmentAnalytics as _CritEA
    crit_filters = [_CritEA.organization_id == org_id, _CritEA.risk_level == 'Critical']
    if dept_ids_for_scope:
        crit_filters.append(_CritEA.department_id.in_(dept_ids_for_scope))
    rows = (
        db.query(_CritEA)
        .filter(*crit_filters)
        .order_by(_CritEA.health_score.asc().nulls_last())
        .all()
    )
    out = []
    for row in rows:
        eq = row.equipment
        out.append({
            "equipment_id": str(row.equipment_id),
            "equipment_label": eq.ueic if eq else "Unknown equipment",
            "health_score": float(row.health_score) if row.health_score is not None else None,
            "condition_summary": row.condition_summary,
        })
    total = len(out)
    page = out[offset:offset + limit] if limit is not None else out[offset:]
    return page, total


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

    # Which of the DQI (Data Quality Index) checks currently count toward
    # the score/remediation list, and which equipment types each applies
    # to — admin-configurable via Threshold Config's "Data Quality" tab
    # (DqiRuleConfig, /threshold-config/dqi-rules). Read once here so
    # _scope_counts (below) and the leaf/branch dqi_issues blocks agree on
    # the same active/scoped set for every row/summary in this response.
    _dqi_key_scopes = _dqi_active_key_scopes(db)

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
        # Excludes calibration requests — those get their own Overdue
        # T+0/T+7/T+15 buckets in the Calibration section, now based on
        # actual validity expiry (calibration_date + validity_months) via
        # _calibration_summary/_calibration_overdue_equipment, not this
        # generic ticket due_date. Counting them here too would double
        # them into both places, and worse, this generic due_date is often
        # just a short task SLA on a follow-up ticket — unrelated to
        # whether the equipment's calibration has actually expired
        # (confirmed live: 4 relays flagged "3-11 days overdue" here whose
        # real calibration validity doesn't expire until mid/late 2027).
        overdue_count = db.query(func.count(TestingRequest.id)).filter(
            *tr_filters,
            ~_closed_expr,
            TestingRequest.is_calibration.is_(False),
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
        # meeting every active, type-applicable check (see
        # _dqi_active_key_scopes/_dqi_compute_scope above _build_department_
        # rollup — nameplate fields, has-test-history, not-overdue, each
        # optionally scoped to specific equipment types).
        _dqi_result = _dqi_compute_scope(db, svc.org_id, dept_ids_for_scope, _dqi_key_scopes, _closed_expr)
        dqi_total = _dqi_result["total"]
        dqi_ready = _dqi_result["ready"]
        # No active equipment yet means there's nothing to score — not the
        # same as "fully ready". Reporting 100% here reads as a genuine pass
        # and made empty departments look better than departments that
        # actually have equipment with real data gaps, which is what an
        # empty dept_ids scope (e.g. no equipment assigned) always did to
        # this — so leave it unscored (None) instead, and let callers render
        # "no equipment" rather than a misleading 100%.
        dqi_pct = int((dqi_ready / dqi_total) * 100) if dqi_total > 0 else None

        # Result Review SLA compliance — % of closed Result Review stage
        # instances (TrWfStage.is_result_stage) that finished within their
        # configured stage duration. Blended across severities, not the
        # spec's 24h-ALERT/2h-CRITICAL split: severity is only captured on
        # fired Notification rows (models.py:4561), not as a stable field
        # on TestingRequest/TrWfStageInstance a historical report can join
        # against, so a single stage-level duration is all that's available
        # today. Only counts stages an admin has actually given a duration
        # to (tr_workflow_config.py's create/patch validation) — every
        # stage predating that feature is excluded, not treated as 0%.
        from models import TrWfStageInstance
        review_rows = (
            db.query(
                TrWfStageInstance.started_at,
                TrWfStageInstance.completed_at,
                TrWfStage.default_duration_hours,
                TrWfStage.default_duration_days,
            )
            .join(TrWfStage, TrWfStage.id == TrWfStageInstance.stage_id)
            .join(TrWfInstance, TrWfInstance.id == TrWfStageInstance.wf_instance_id)
            .join(TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id)
            .filter(
                *tr_filters,
                TrWfStage.is_result_stage.is_(True),
                TrWfStageInstance.status.in_(("completed", "rejected")),
                TrWfStageInstance.started_at.isnot(None),
                TrWfStageInstance.completed_at.isnot(None),
                _or(
                    TrWfStage.default_duration_hours.isnot(None),
                    TrWfStage.default_duration_days.isnot(None),
                ),
            )
            .all()
        )
        review_sla_total = len(review_rows)
        review_sla_compliant = 0
        for started_at, completed_at, dur_hours, dur_days in review_rows:
            # Weekends don't count against the SLA clock -- same
            # add_business_hours the escalation-matrix notification job and
            # the Monthly Result Review Compliance Report use, so this tile
            # agrees with what actually got flagged as overdue.
            deadline = add_business_hours(
                started_at, dur_hours if dur_hours is not None else dur_days * 24
            )
            if completed_at <= deadline:
                review_sla_compliant += 1
        review_sla_pct = (
            int((review_sla_compliant / review_sla_total) * 100)
            if review_sla_total > 0 else None
        )

        # Severity-split SLA (the spec's actual 24h-ALERT/2h-CRITICAL
        # requirement) — additive to review_sla_pct above, not a
        # replacement: that one stays exactly as it was for any existing
        # caller. Severity is resolved per closed review from the worst
        # (CRITICAL beats ALERT) evaluation_result['overall'] among that
        # review's TestingRequest's TestResults — a review with only
        # NORMAL results has nothing to hold to an ALERT/CRITICAL SLA and
        # is excluded, not counted as compliant. Unlike review_sla_pct,
        # this does NOT require TrWfStage.default_duration_hours/days to
        # be set — the deadline comes from the fixed severity thresholds
        # below, not a per-stage admin config, so a result stage nobody
        # has configured a duration for yet still gets scored here.
        from models import TestResult as _TestResult
        _severity_rows = (
            db.query(
                TrWfStageInstance.started_at,
                TrWfStageInstance.completed_at,
                TestingRequest.id,
            )
            .join(TrWfStage, TrWfStage.id == TrWfStageInstance.stage_id)
            .join(TrWfInstance, TrWfInstance.id == TrWfStageInstance.wf_instance_id)
            .join(TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id)
            .filter(
                *tr_filters,
                TrWfStage.is_result_stage.is_(True),
                TrWfStageInstance.status.in_(("completed", "rejected")),
                TrWfStageInstance.started_at.isnot(None),
                TrWfStageInstance.completed_at.isnot(None),
            )
            .all()
        )
        _req_ids = {req_id for _, _, req_id in _severity_rows}
        _worst_severity_by_req: dict = {}
        if _req_ids:
            _sev_rank = {"CRITICAL": 2, "ALERT": 1}
            for req_id, overall in (
                db.query(_TestResult.testing_request_id, _TestResult.evaluation_result["overall"].astext)
                .filter(_TestResult.testing_request_id.in_(_req_ids))
                .all()
            ):
                rank = _sev_rank.get(overall)
                if rank is None:
                    continue
                cur_rank = _sev_rank.get(_worst_severity_by_req.get(req_id))
                if cur_rank is None or rank > cur_rank:
                    _worst_severity_by_req[req_id] = overall

        _sla_hours = {
            "ALERT": config.REVIEW_SLA_HOURS_ALERT,
            "CRITICAL": config.REVIEW_SLA_HOURS_CRITICAL,
        }
        _sla_counts = {
            "ALERT": {"total": 0, "compliant": 0},
            "CRITICAL": {"total": 0, "compliant": 0},
        }
        for started_at, completed_at, req_id in _severity_rows:
            severity = _worst_severity_by_req.get(req_id)
            if severity not in _sla_hours:
                continue
            bucket = _sla_counts[severity]
            bucket["total"] += 1
            deadline = started_at + timedelta(hours=_sla_hours[severity])
            if completed_at <= deadline:
                bucket["compliant"] += 1

        def _pct(bucket):
            return (
                int((bucket["compliant"] / bucket["total"]) * 100)
                if bucket["total"] > 0 else None
            )

        review_sla_pct_alert = _pct(_sla_counts["ALERT"])
        review_sla_total_alert = _sla_counts["ALERT"]["total"]
        review_sla_pct_critical = _pct(_sla_counts["CRITICAL"])
        review_sla_total_critical = _sla_counts["CRITICAL"]["total"]

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
            "review_sla_pct": review_sla_pct,
            "review_sla_total": review_sla_total,
            "review_sla_pct_alert": review_sla_pct_alert,
            "review_sla_total_alert": review_sla_total_alert,
            "review_sla_pct_critical": review_sla_pct_critical,
            "review_sla_total_critical": review_sla_total_critical,
            "dqi_pct": dqi_pct,
            "dqi_ready_count": dqi_ready,
            "dqi_total_count": dqi_total,
        }

    def _dqi_issues_list(dept_ids_for_scope, limit=None, offset=0):
        """Per-equipment DQI remediation list — same checks as
        _scope_counts' dqi_pct above (via the same shared
        _dqi_compute_scope), extracted so both the leaf shape and the
        branch shape (its "summary", scoped the same as _scope_counts' own
        dqi_pct there) can surface an actionable list, not just the
        aggregate percentage. Previously leaf-scope only; branch scopes can
        span hundreds of substations' worth of equipment, so `limit`/
        `offset` page through it (offset used by GET /dashboard/dqi-issues'
        "Load More", never by the initial /overview response itself) — the
        caller gets the true total (count of equipment with at least one
        issue, not the scope's total equipment count) so it can say
        "showing N of TOTAL".
        """
        from sqlalchemy import or_ as _or_dqi
        dqi_closed_expr = _or_dqi(
            TestingRequest.status == 'closed',
            TestingRequest.current_status_code.in_(terminal_status_codes),
        )
        result = _dqi_compute_scope(db, svc.org_id, dept_ids_for_scope, _dqi_key_scopes, dqi_closed_expr)
        issues_out = result["issues"]
        total = len(issues_out)
        page = issues_out[offset:offset + limit] if limit is not None else issues_out[offset:]
        return page, total

    def _review_sla_breaches_list(dept_ids_for_scope, limit=None):
        """Closed Result Review stage instances that missed their
        configured SLA -- the actionable detail behind _scope_counts'
        review_sla_pct, same reasoning as _dqi_issues_list above: the
        aggregate percentage alone doesn't tell you which ticket to act on.
        Shares _review_sla_judged_rows with GET /dashboard/review-sla-breaches
        ("Load More") and GET /dashboard/review-sla-summary (the card's
        charts), so all three agree on what counts as a breach.
        """
        breaches = [_review_sla_public(r)
                    for r in _review_sla_judged_rows(db, svc.org_id, dept_ids_for_scope)
                    if r["breached"]]
        total = len(breaches)
        page = breaches[:limit] if limit is not None else breaches
        return page, total

    def _review_sla_reviews_list_by_severity(dept_ids_for_scope, severity, limit=None):
        """Every closed Result Review stage instance counted in this
        severity's SLA bucket — routers/dashboard_kpi.py's own
        review_sla_pct_alert/review_sla_pct_critical -- not breaches only.
        A pure breach list (see _review_sla_breaches_list above, which the
        blended card behind it uses) would leave this drill-down with
        nothing to show whenever the severity is currently at 100%
        compliance, and then the ALERT/CRITICAL tiles could never be
        opened at all even though real judged reviews exist behind that
        percentage — so each row carries its own `breached` flag instead,
        letting the frontend badge "on time" reviews too. Same
        severity-resolution rule as _scope_counts' severity-split block
        (worst of CRITICAL/ALERT among the review's TestResults; a review
        with only NORMAL results isn't judged under either SLA and is
        excluded here too).
        """
        from models import TrWfStageInstance as _TrWfStageInstance, TestResult as _TestResult
        _tr_filters = [TestingRequest.organization_id == svc.org_id]
        if dept_ids_for_scope:
            _tr_filters.append(TestingRequest.department_id.in_(dept_ids_for_scope))

        rows = (
            db.query(_TrWfStageInstance, TestingRequest)
            .join(TrWfStage, TrWfStage.id == _TrWfStageInstance.stage_id)
            .join(TrWfInstance, TrWfInstance.id == _TrWfStageInstance.wf_instance_id)
            .join(TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id)
            .filter(
                *_tr_filters,
                TrWfStage.is_result_stage.is_(True),
                _TrWfStageInstance.status.in_(("completed", "rejected")),
                _TrWfStageInstance.started_at.isnot(None),
                _TrWfStageInstance.completed_at.isnot(None),
            )
            .all()
        )

        req_ids = {tr.id for _, tr in rows}
        worst_severity_by_req = {}
        if req_ids:
            sev_rank = {"CRITICAL": 2, "ALERT": 1}
            for req_id, overall in (
                db.query(_TestResult.testing_request_id, _TestResult.evaluation_result["overall"].astext)
                .filter(_TestResult.testing_request_id.in_(req_ids))
                .all()
            ):
                rank = sev_rank.get(overall)
                if rank is None:
                    continue
                cur_rank = sev_rank.get(worst_severity_by_req.get(req_id))
                if cur_rank is None or rank > cur_rank:
                    worst_severity_by_req[req_id] = overall

        sla_hours = {
            "ALERT": config.REVIEW_SLA_HOURS_ALERT,
            "CRITICAL": config.REVIEW_SLA_HOURS_CRITICAL,
        }[severity]

        reviewed = []
        for si, tr in rows:
            if worst_severity_by_req.get(tr.id) != severity:
                continue
            deadline = si.started_at + timedelta(hours=sla_hours)
            breached = si.completed_at > deadline
            eq = getattr(tr, "equipment", None)
            reviewed.append({
                "stage_instance_id": str(si.id),
                "request_id": str(tr.id),
                "request_number": tr.request_number,
                "stage_name": f"{severity.title()} Review",
                "test_type": f"{severity.title()} Review",
                "equipment_id": str(eq.id) if eq else None,
                "equipment_label": eq.ueic if eq else (
                    tr.equipment_type.name if tr.equipment_type else "Equipment"),
                "started_at": si.started_at.isoformat(),
                "completed_at": si.completed_at.isoformat(),
                "deadline": deadline.isoformat(),
                "breached": breached,
                "hours_over": round((si.completed_at - deadline).total_seconds() / 3600, 1)
                              if breached else 0,
            })

        # Breaches first (worst overrun first), then on-time reviews —
        # whatever needs attention should surface above what doesn't.
        reviewed.sort(key=lambda r: (not r["breached"], -r["hours_over"]))
        total = len(reviewed)
        page = reviewed[:limit] if limit is not None else reviewed
        return page, total

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
        # Fetched as rows (not just count) so the Cal. Compliance tile has
        # an actual drill-down list, same as every other KPI tile on this
        # dashboard — each row says whether it was closed, and on time.
        due_90_rows = (
            db.query(TestingRequest)
            .filter(*cal_filters, TestingRequest.due_date.between(ninety_days, now))
            .order_by(TestingRequest.due_date.desc())
            .all()
        )
        cal_due_90 = len(due_90_rows)
        # mts is the best available proxy for "when it closed" (no dedicated
        # closed_at column — same convention closed_this_week_count already
        # uses). Requiring mts <= due_date is the actual "on time" check —
        # previously this only checked cal_closed_expr (closed at all), so a
        # calibration finished months after its due date would still count
        # as on-time here as long as it was eventually closed.
        cal_due_90_list = []
        cal_on_time_90 = 0
        for r in due_90_rows:
            # r.status is a TestingRequestStatus enum instance here (not a
            # plain string) — .value is what actually compares equal to
            # the literal 'closed' the SQL-level cal_closed_expr checks.
            is_closed = (
                (r.status.value if r.status else None) == 'closed'
                or r.current_status_code in terminal_status_codes
            )
            on_time = is_closed and r.mts is not None and r.due_date is not None and r.mts <= r.due_date
            if on_time:
                cal_on_time_90 += 1
            ueic = r.equipment.ueic if r.equipment else (
                r.equipment_type.name if r.equipment_type else "Unknown equipment")
            cal_due_90_list.append({
                "equipment_id": str(r.equipment_id) if r.equipment_id else None,
                "equipment_label": ueic,
                "request_id": str(r.id),
                "request_number": r.request_number,
                "due_date": r.due_date.isoformat() if r.due_date else None,
                "closed": is_closed,
                "on_time": on_time,
            })
        cal_compliance_pct = int((cal_on_time_90 / cal_due_90) * 100) if cal_due_90 > 0 else 100

        # T+0 / T+7 / T+15 — EQUIPMENT whose calibration validity has
        # actually expired (calibration_date + validity_months from its
        # latest genuine reading), bucketed by how many business days past
        # that expiry — matching the spec's own escalation-tier naming (an
        # org's real escalation cadence isn't itself stored anywhere; this
        # buckets by elapsed time, the same information those escalation
        # rules would act on). Deliberately NOT open tickets past their own
        # due_date (the previous version of this code) — that due_date is
        # frequently just a short task SLA on a follow-up ticket, unrelated
        # to whether the equipment's calibration has actually expired
        # (confirmed live: relays flagged "3-11 days overdue" this way
        # whose real calibration validity doesn't expire until mid/late
        # 2027), and it double-counted the same tickets that already count
        # toward the org-wide "Overdue Tests" tile above (which now
        # excludes is_calibration requests specifically because this
        # section is the intended home for them).
        from models import Equipment as _CalEquipment
        from services.calibration_service import CalibrationService as _CalSvcForOverdue, date_add as _cal_date_add
        cal_equipment_ids = {
            r[0] for r in db.query(TestingRequest.equipment_id).filter(
                *cal_filters, TestingRequest.equipment_id.isnot(None),
            ).distinct().all()
        }
        _cal_svc_overdue = _CalSvcForOverdue(db)
        cal_t0 = cal_t7 = cal_t15 = 0
        cal_expiring_30 = cal_expiring_60 = 0
        # Each bucket also collects the actual equipment behind it — same
        # "aggregate number alone isn't actionable" reasoning as every other
        # KPI tile's own drill-down list on this dashboard.
        cal_t0_equipment: list = []
        cal_t7_equipment: list = []
        cal_t15_equipment: list = []
        cal_expiring_30_equipment: list = []
        cal_expiring_60_equipment: list = []
        for eq_id in cal_equipment_ids:
            latest = _cal_svc_overdue._get_latest_reading(eq_id)
            if not latest:
                continue
            next_due = _cal_date_add(latest["calibration_date"], latest["validity_months"])
            eq = db.query(_CalEquipment).filter(_CalEquipment.id == eq_id).first()
            ueic = eq.ueic if eq else str(eq_id)
            if next_due >= now.date():
                # Same equipment-level validity-expiry basis as the overdue
                # buckets above — Expiring Soon previously counted open
                # calibration TICKETS due within 30/60 days (the same task
                # due_date the overdue buckets used to before that got
                # fixed), not equipment actually approaching its real
                # calibration expiry. Kept in this same loop rather than a
                # separate query since it needs the identical per-equipment
                # next_due this loop already computes.
                days_until = (next_due - now.date()).days
                row = {
                    "equipment_id": str(eq_id),
                    "equipment_label": ueic,
                    "next_due_date": next_due.isoformat(),
                    "days_until": days_until,
                }
                if days_until <= 60:
                    cal_expiring_60 += 1
                    cal_expiring_60_equipment.append(row)
                if days_until <= 30:
                    cal_expiring_30 += 1
                    cal_expiring_30_equipment.append(row)
                continue
            days_over = business_days_between(next_due, now.date())
            row = {
                "equipment_id": str(eq_id),
                "equipment_label": ueic,
                "next_due_date": next_due.isoformat(),
                "days_over": days_over,
            }
            if days_over >= 15:
                cal_t15 += 1
                cal_t15_equipment.append(row)
            elif days_over >= 7:
                cal_t7 += 1
                cal_t7_equipment.append(row)
            else:
                cal_t0 += 1
                cal_t0_equipment.append(row)

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
        # created_by IS NOT NULL excludes TestResults that never went
        # through the real result form (calibration_hooks.py's certificate
        # recording, and the test result wizard, both always set it to the
        # submitting user) — confirmed live: a batch of synthetic/seeded
        # TestResults with nothing but a bare {"overall_result": "fail",
        # "validity_months": ...} and no calibration_date/calibrated_by/
        # certificate_number at all, all created_by=NULL, was inflating
        # this count with failures nobody ever actually observed.
        _cal_has_real_submission = TestingRequest.created_by.isnot(None)
        _cal_fail_rows = (
            db.query(TestingRequest, TestResult.tested_at)
            .join(TestResult, TestResult.testing_request_id == TestingRequest.id)
            .filter(*cal_filters, _cal_has_real_submission, _cal_result == 'fail')
            .order_by(TestResult.tested_at.desc())
            .all()
        )
        # De-duped by request id in Python (not a SQL DISTINCT) now that the
        # query also needs to return each request's own detail for the
        # drill-down list below, not just a count.
        _seen_fail_request_ids: set = set()
        cal_fail_equipment: list = []
        for tr_row, tested_at in _cal_fail_rows:
            if tr_row.id in _seen_fail_request_ids:
                continue
            _seen_fail_request_ids.add(tr_row.id)
            ueic = tr_row.equipment.ueic if tr_row.equipment else (
                tr_row.equipment_type.name if tr_row.equipment_type else "Unknown equipment")
            cal_fail_equipment.append({
                "equipment_id": str(tr_row.equipment_id) if tr_row.equipment_id else None,
                "equipment_label": ueic,
                "request_id": str(tr_row.id),
                "request_number": tr_row.request_number,
                "tested_at": tested_at.isoformat() if tested_at else None,
            })
        cal_fail_count = len(_seen_fail_request_ids)

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
            *cal_filters, _cal_has_real_submission, TestingRequest.mts >= trend_cutoff,
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

        # AI calibration-interval optimisation advisories (§14.6), scoped to
        # this dashboard's own department + descendants (svc.dept_ids) —
        # org root (svc.dept_ids is None) still gets the org-wide view. A
        # cohort is (test type, make, model), which spans departments by
        # nature, so a narrow scope will often have fewer (or no)
        # advisories than the org-wide view — that's
        # CALIBRATION_INTERVAL_MIN_CYCLES materiality gate doing its job,
        # not a bug, and the panel already self-hides when the list is empty.
        from services.calibration_service import compute_interval_advisories
        try:
            interval_advisories = compute_interval_advisories(db, svc.org_id, department_ids=svc.dept_ids)
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
            "compliance_list": cal_due_90_list,
            "fail_count": cal_fail_count,
            "fail_equipment": cal_fail_equipment,
            "overdue_t0": cal_t0,
            "overdue_t0_equipment": cal_t0_equipment,
            "overdue_t7": cal_t7,
            "overdue_t7_equipment": cal_t7_equipment,
            "overdue_t15": cal_t15,
            "overdue_t15_equipment": cal_t15_equipment,
            "expiring_30d": cal_expiring_30,
            "expiring_30d_equipment": cal_expiring_30_equipment,
            "expiring_60d": cal_expiring_60,
            "expiring_60d_equipment": cal_expiring_60_equipment,
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

    def _ticket_lists(dept_ids_for_scope, limit=config.DASHBOARD_PANEL_PAGE_SIZE):
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

        # Open/Closed/Rejected-Cancelled/Critical Equipment each moved to
        # their own standalone module-level function (same shape as
        # _overdue_tickets_list above) so their own "Load More" endpoints
        # can page through the REAL full list — this local `limit` now
        # only bounds the page returned here, with the true total alongside
        # so the UI can say "showing N of TOTAL" instead of silently
        # truncating (confirmed live: open_count said 26, critical_count
        # said 19, both drill-downs only ever showed up to 10 — the same
        # class of bug _overdue_tickets_list already fixed for Overdue).
        open_tickets, open_tickets_total = _open_tickets_list(
            db, svc.org_id, dept_ids_for_scope, limit=limit)
        closed_this_week_tickets, closed_this_week_tickets_total = \
            _closed_this_week_tickets_list(db, svc.org_id, dept_ids_for_scope, limit=limit)
        rejected_cancelled_tickets, rejected_cancelled_tickets_total = \
            _rejected_cancelled_tickets_list(db, svc.org_id, dept_ids_for_scope, limit=limit)
        critical_equipment, critical_equipment_total = _critical_equipment_list(
            db, svc.org_id, dept_ids_for_scope, limit=limit)

        # Per-ticket breakdown behind _scope_counts' "Awaiting Approval" tile
        # (pending_approval_count + pending_review_count — deliberately NOT
        # pending_assign_count, which is its own separate queue, see that
        # tile's comment above). Built directly off the same two stage-id
        # sets rather than reusing _approval_queue()'s broader
        # viewer_approval_stage_ids (which also folds in assign-only
        # stages) — that would make this list's rows disagree with what
        # the tile's own number is actually counting.
        awaiting_stage_ids = viewer_approve_only_stage_ids | viewer_review_stage_ids
        awaiting_approval = []
        if awaiting_stage_ids:
            aw_q = db.query(TestingRequest, TrWfInstance.current_stage_id).join(
                TrWfInstance, TrWfInstance.testing_request_id == TestingRequest.id,
            ).filter(
                TestingRequest.organization_id == svc.org_id,
                TrWfInstance.status == 'active',
                TrWfInstance.current_stage_id.in_(awaiting_stage_ids),
            )
            if dept_ids_for_scope:
                aw_q = aw_q.filter(TestingRequest.department_id.in_(dept_ids_for_scope))
            aw_rows = aw_q.order_by(TestingRequest.mts.desc()).limit(limit).all()
            for r, current_stage_id in aw_rows:
                ueic = r.equipment.ueic if r.equipment else (
                    r.equipment_type.name if r.equipment_type else "Unknown equipment")
                dept = db.query(OrgDepartment).filter(OrgDepartment.id == r.department_id).first()
                stage = "review" if current_stage_id in viewer_review_stage_ids else "approval"
                awaiting_approval.append({
                    "request_id": str(r.id),
                    "request_number": r.request_number,
                    "equipment_id": str(r.equipment_id) if r.equipment_id else None,
                    "equipment_label": ueic,
                    "test_type": r.test_type.name if r.test_type else None,
                    "department_name": dept.name if dept else None,
                    "stage": stage,
                })

        return {
            "this_week": this_week,
            "open_tickets": open_tickets,
            "open_tickets_total_count": open_tickets_total,
            "closed_this_week_tickets": closed_this_week_tickets,
            "closed_this_week_tickets_total_count": closed_this_week_tickets_total,
            "awaiting_approval": awaiting_approval,
            "rejected_cancelled_tickets": rejected_cancelled_tickets,
            "rejected_cancelled_tickets_total_count": rejected_cancelled_tickets_total,
            "critical_equipment": critical_equipment,
            "critical_equipment_total_count": critical_equipment_total,
        }

    def _failure_cohort_summary():
        # Per make/model reliability (§2), scoped like the calibration
        # interval advisories above — svc.dept_ids narrows to this
        # dashboard's own department + descendants, org root
        # (svc.dept_ids is None) still gets the org-wide view. A narrow
        # scope may fall below FAILURE_COHORT_MIN_UNITS for some or all
        # cohorts; the panel already self-hides when the list is empty
        # rather than showing a diluted or misleading cohort. Defined
        # before the leaf/branch split below (not after it, where it
        # used to live) — the leaf return is an early return, so a
        # nested function defined only after that point would never be
        # bound yet when the leaf branch tried to call it.
        from services.equipment_service import EquipmentService
        try:
            return EquipmentService.compute_failure_cohort_stats(db, svc.org_id, department_ids=svc.dept_ids)
        except Exception:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "failure cohort reliability computation failed", exc_info=True
            )
            # A DB-level error (e.g. a missing table/column) leaves this
            # session's transaction aborted in Postgres — every later query
            # on the same `db` in this request would raise
            # InFailedSqlTransaction otherwise, cascading this one caught
            # failure into unrelated widgets computed further down in
            # _build_department_rollup (confirmed live: _ticket_lists failed
            # right after this swallowed exception, same request).
            db.rollback()
            return []

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

        # Total equipment at this one station — the mockup's 4th leaf KPI
        # tile is "Equipment", not "Awaiting Approval" (an individual tester
        # doesn't approve anything; that's a supervisor-level concept, see
        # _scope_counts' pending_approval_count for the branch-scope version).
        from models import Equipment
        equipment_count = db.query(func.count(Equipment.id)).filter(
            *_equipment_scope_filters(db, svc.org_id, svc.dept_ids)
        ).scalar() or 0

        # Equipment failing at least one DQI check — see _dqi_issues_list's
        # own docstring above. Unlimited here: a single substation's
        # equipment count is small enough to return in full (unlike the
        # branch shape below, which caps it).
        dqi_issues, _dqi_issues_total = _dqi_issues_list(svc.dept_ids)
        overdue_tickets, _overdue_tickets_total = _overdue_tickets_list(db, svc.org_id, svc.dept_ids)
        review_sla_breaches, _review_sla_breaches_total = _review_sla_breaches_list(svc.dept_ids)
        review_sla_reviews_alert, _review_sla_reviews_alert_total = \
            _review_sla_reviews_list_by_severity(svc.dept_ids, "ALERT")
        review_sla_reviews_critical, _review_sla_reviews_critical_total = \
            _review_sla_reviews_list_by_severity(svc.dept_ids, "CRITICAL")

        return {
            "shape": "leaf",
            "scope_name": scope_name,
            "scope_level": scope_level,
            "flagged_equipment": flagged,
            "equipment_count": equipment_count,
            "dqi_issues": dqi_issues,
            "dqi_issues_total_count": _dqi_issues_total,
            "overdue_tickets": overdue_tickets,
            "overdue_tickets_total_count": _overdue_tickets_total,
            "review_sla_breaches": review_sla_breaches,
            "review_sla_breaches_total_count": _review_sla_breaches_total,
            "review_sla_reviews_alert": review_sla_reviews_alert,
            "review_sla_reviews_alert_total_count": _review_sla_reviews_alert_total,
            "review_sla_reviews_critical": review_sla_reviews_critical,
            "review_sla_reviews_critical_total_count": _review_sla_reviews_critical_total,
            "can_test": can_test,
            "assigned_test_count": assigned_test_count,
            "can_approve_requests": can_approve_requests,
            "can_assign_requests": can_assign_requests,
            "can_review": can_review,
            "weekly_trend": _weekly_trend(svc.dept_ids),
            "calibration": _calibration_summary(svc.dept_ids),
            "failure_reliability": _failure_cohort_summary(),
            **ticket_lists,
            **_scope_counts(svc.dept_ids),
        }

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
    # Full-subtree DQI remediation list — same scope as "summary" above, so
    # its dqi_pct isn't just an unreachable aggregate: capped to keep the
    # response bounded at a zone/org scope (potentially hundreds of
    # substations' worth of equipment), with the true total alongside so the
    # UI can say "showing N of TOTAL" rather than imply the list is complete.
    _branch_dqi_issues, _branch_dqi_issues_total = _dqi_issues_list(svc.dept_ids, limit=config.DASHBOARD_PANEL_PAGE_SIZE)
    _branch_overdue_tickets, _branch_overdue_tickets_total = _overdue_tickets_list(
        db, svc.org_id, svc.dept_ids, limit=config.DASHBOARD_PANEL_PAGE_SIZE)
    _branch_review_sla_breaches, _branch_review_sla_breaches_total = _review_sla_breaches_list(svc.dept_ids, limit=config.DASHBOARD_PANEL_PAGE_SIZE)
    _branch_review_sla_reviews_alert, _branch_review_sla_reviews_alert_total = \
        _review_sla_reviews_list_by_severity(svc.dept_ids, "ALERT", limit=config.DASHBOARD_PANEL_PAGE_SIZE)
    _branch_review_sla_reviews_critical, _branch_review_sla_reviews_critical_total = \
        _review_sla_reviews_list_by_severity(svc.dept_ids, "CRITICAL", limit=config.DASHBOARD_PANEL_PAGE_SIZE)
    return {
        "shape": "branch",
        "scope_name": scope_name,
        "scope_level": scope_level,
        # Full-subtree totals computed the same way as every row below (not a
        # separately-tracked figure), so the top-line numbers can't drift out
        # of sync with what the rollup rows say they should add up to.
        "summary": _scope_counts(svc.dept_ids),
        "dqi_issues": _branch_dqi_issues,
        "dqi_issues_total_count": _branch_dqi_issues_total,
        "overdue_tickets": _branch_overdue_tickets,
        "overdue_tickets_total_count": _branch_overdue_tickets_total,
        "review_sla_breaches": _branch_review_sla_breaches,
        "review_sla_breaches_total_count": _branch_review_sla_breaches_total,
        "review_sla_reviews_alert": _branch_review_sla_reviews_alert,
        "review_sla_reviews_alert_total_count": _branch_review_sla_reviews_alert_total,
        "review_sla_reviews_critical": _branch_review_sla_reviews_critical,
        "review_sla_reviews_critical_total_count": _branch_review_sla_reviews_critical_total,
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


@router.get("/dqi-issues")
def get_dqi_issues_page(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(config.DASHBOARD_PANEL_PAGE_SIZE, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated continuation of the Data Quality remediation list embedded
    in GET /dashboard/overview (whose own `dqi_issues` is capped at 50 for
    a branch scope) — powers the Overall Dashboard's "Load More" button
    without re-running the whole rollup (compliance/ticket lists/
    calibration/etc — all already fetched once by /overview and still held
    by the frontend). Same scope resolution (_svc) and the same
    _dqi_active_key_scopes/_dqi_compute_scope machinery
    _build_department_rollup itself uses, just invoked directly so this
    can be a lightweight, independently-cacheable call.
    """
    svc = _svc(db, current_user, org_id, dept_id)
    key_scopes = _dqi_active_key_scopes(db)
    closed_expr = _dqi_closed_expr_for_org(db, svc.org_id)
    result = _dqi_compute_scope(db, svc.org_id, svc.dept_ids, key_scopes, closed_expr)
    issues = result["issues"]
    total = len(issues)
    page = issues[offset:offset + limit]
    return {
        "issues": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/overdue-tickets")
def get_overdue_tickets_page(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(config.DASHBOARD_PANEL_PAGE_SIZE, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated continuation of the Overdue Tickets list embedded in
    GET /dashboard/overview (whose own `overdue_tickets` is capped at
    config.DASHBOARD_PANEL_PAGE_SIZE for a branch scope) —
    powers the Overall Dashboard's "Load More" button the same way
    GET /dashboard/dqi-issues does for the DQI panel, without re-running
    the whole rollup.
    """
    svc = _svc(db, current_user, org_id, dept_id)
    tickets, total = _overdue_tickets_list(db, svc.org_id, svc.dept_ids, limit=limit, offset=offset)
    return {
        "tickets": tickets,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/open-tickets")
def get_open_tickets_page(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(config.DASHBOARD_PANEL_PAGE_SIZE, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated continuation of the Open Requests list — same "Load
    More" shape as GET /dashboard/overdue-tickets, for the Open Requests
    KPI tile's own drill-down.
    """
    svc = _svc(db, current_user, org_id, dept_id)
    tickets, total = _open_tickets_list(db, svc.org_id, svc.dept_ids, limit=limit, offset=offset)
    return {
        "tickets": tickets,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/closed-tickets")
def get_closed_tickets_page(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(config.DASHBOARD_PANEL_PAGE_SIZE, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated continuation of the Closed This Week list — same "Load
    More" shape as GET /dashboard/overdue-tickets, for the Closed This
    Week KPI tile's own drill-down.
    """
    svc = _svc(db, current_user, org_id, dept_id)
    tickets, total = _closed_this_week_tickets_list(db, svc.org_id, svc.dept_ids, limit=limit, offset=offset)
    return {
        "tickets": tickets,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/rejected-cancelled-tickets")
def get_rejected_cancelled_tickets_page(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(config.DASHBOARD_PANEL_PAGE_SIZE, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated continuation of the Rejected/Cancelled list — same "Load
    More" shape as GET /dashboard/overdue-tickets, for the Rejected /
    Cancelled KPI tile's own drill-down.
    """
    svc = _svc(db, current_user, org_id, dept_id)
    tickets, total = _rejected_cancelled_tickets_list(db, svc.org_id, svc.dept_ids, limit=limit, offset=offset)
    return {
        "tickets": tickets,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/critical-equipment")
def get_critical_equipment_page(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(config.DASHBOARD_PANEL_PAGE_SIZE, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated continuation of the Critical Equipment list — same "Load
    More" shape as GET /dashboard/overdue-tickets, for the Critical
    Equipment KPI tile's own drill-down.
    """
    svc = _svc(db, current_user, org_id, dept_id)
    tickets, total = _critical_equipment_list(db, svc.org_id, svc.dept_ids, limit=limit, offset=offset)
    return {
        "tickets": tickets,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


def _review_sla_judged_rows(db: Session, org_id, dept_ids):
    """Every closed Result Review stage instance judged against its
    configured stage duration (the blended review_sla_pct basis), newest
    first, each flagged `breached` or not. Same filters and the same
    weekend-aware add_business_hours deadline as _scope_counts'
    review_sla_pct, so the breach list, its "Load More" pages and the
    card's charts all count the same rows.

    `severity` is the worst ALERT/CRITICAL evaluation_result['overall']
    among the request's TestResults (same rule as the severity-split
    tiles), or None when every result was NORMAL -- only used to colour
    the compliance donut, never to change the deadline.
    """
    from sqlalchemy import or_
    from models import (TrWfStageInstance as _TrWfStageInstance, TrWfStage,
                        TrWfInstance, TestingRequest, TestResult as _TestResult)
    _tr_filters = [TestingRequest.organization_id == org_id]
    if dept_ids:
        _tr_filters.append(TestingRequest.department_id.in_(dept_ids))
    rows = (
        db.query(_TrWfStageInstance, TrWfStage, TestingRequest)
        .join(TrWfStage, TrWfStage.id == _TrWfStageInstance.stage_id)
        .join(TrWfInstance, TrWfInstance.id == _TrWfStageInstance.wf_instance_id)
        .join(TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id)
        .filter(
            *_tr_filters,
            TrWfStage.is_result_stage.is_(True),
            _TrWfStageInstance.status.in_(("completed", "rejected")),
            _TrWfStageInstance.started_at.isnot(None),
            _TrWfStageInstance.completed_at.isnot(None),
            or_(
                TrWfStage.default_duration_hours.isnot(None),
                TrWfStage.default_duration_days.isnot(None),
            ),
        )
        .order_by(_TrWfStageInstance.completed_at.desc())
        .all()
    )

    worst_severity_by_req = {}
    req_ids = {tr.id for _, _, tr in rows}
    if req_ids:
        sev_rank = {"CRITICAL": 2, "ALERT": 1}
        for req_id, overall in (
            db.query(_TestResult.testing_request_id, _TestResult.evaluation_result["overall"].astext)
            .filter(_TestResult.testing_request_id.in_(req_ids))
            .all()
        ):
            rank = sev_rank.get(overall)
            if rank is None:
                continue
            if rank > sev_rank.get(worst_severity_by_req.get(req_id), 0):
                worst_severity_by_req[req_id] = overall

    out = []
    for si, stage, tr in rows:
        sla_hours = (stage.default_duration_hours if stage.default_duration_hours is not None
                     else stage.default_duration_days * 24)
        # Weekends don't count against the SLA clock -- same as
        # review_sla_pct and the escalation-matrix job.
        deadline = add_business_hours(si.started_at, sla_hours)
        eq = getattr(tr, "equipment", None)
        out.append({
            "stage_instance_id": str(si.id),
            "request_id": str(tr.id),
            "request_number": tr.request_number,
            "stage_name": stage.name,
            # Reuses TicketsPanel's generic "test_type" display slot to show
            # which stage breached, next to the request number.
            "test_type": stage.name,
            "equipment_id": str(eq.id) if eq else None,
            "equipment_label": eq.ueic if eq else (
                tr.equipment_type.name if tr.equipment_type else "Equipment"),
            "started_at": si.started_at.isoformat(),
            "completed_at": si.completed_at.isoformat(),
            "deadline": deadline.isoformat(),
            "sla_hours": float(sla_hours),
            "hours_taken": round((si.completed_at - si.started_at).total_seconds() / 3600, 1),
            "hours_over": round((si.completed_at - deadline).total_seconds() / 3600, 1),
            "breached": si.completed_at > deadline,
            "severity": worst_severity_by_req.get(tr.id),
            "_completed_at": si.completed_at,
        })
    return out


def _review_sla_public(row):
    """_review_sla_judged_rows row minus its internal (underscored) keys."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


# Aging buckets for the SLA card's bar chart, by hours past the deadline.
_REVIEW_SLA_AGING_BUCKETS = (
    ("< 1 day", 24),
    ("1–3 days", 72),
    ("3–7 days", 168),
    ("7+ days", None),
)


@router.get("/review-sla-summary")
def get_review_sla_summary(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    period: str = Query("30d", alias="range", pattern="^(30d|90d)$"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Chart data for the Result Review SLA Breaches card: a compliance
    donut (on time vs breached, breaches split by result severity), an
    aging bar chart (breaches by how late they finished, stacked by
    stage) and a breach trend. `range` filters the donut, aging chart
    AND the weekly trend by completed_at — the trend's week count scales
    with the selected range (~5wk for 30d, ~13wk for 90d) so the chart
    never implies a longer lookback than the range selector above it
    actually covers.
    """
    from datetime import datetime, timedelta
    svc = _svc(db, current_user, org_id, dept_id)
    rows = _review_sla_judged_rows(db, svc.org_id, svc.dept_ids)

    now = datetime.now()
    since = {
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
    }[period]
    in_range = [r for r in rows if r["_completed_at"] >= since]
    breaches = [r for r in in_range if r["breached"]]

    by_severity = {"CRITICAL": 0, "ALERT": 0, "OTHER": 0}
    for r in breaches:
        by_severity[r["severity"] if r["severity"] in by_severity else "OTHER"] += 1
    judged = len(in_range)
    on_time = judged - len(breaches)

    # Stage names in first-seen order so colours stay stable between loads.
    stages = []
    counts = {}
    for r in breaches:
        stage = r["stage_name"] or "Result Review"
        if stage not in counts:
            stages.append(stage)
            counts[stage] = [0] * len(_REVIEW_SLA_AGING_BUCKETS)
        for i, (_, upper) in enumerate(_REVIEW_SLA_AGING_BUCKETS):
            if upper is None or r["hours_over"] < upper:
                counts[stage][i] += 1
                break

    # Weekly trend window scales with the selected range (see docstring).
    weeks = {"30d": 5, "90d": 13}[period]

    this_monday = datetime.combine((now - timedelta(days=now.weekday())).date(), datetime.min.time())
    week_starts = [this_monday - timedelta(weeks=weeks - 1 - i) for i in range(weeks)]
    weekly = [0] * weeks
    for r in rows:
        if not r["breached"] or r["_completed_at"] < week_starts[0]:
            continue
        idx = (r["_completed_at"] - week_starts[0]).days // 7
        weekly[min(weeks - 1, idx)] += 1

    # Trend = second half of the window vs first half (the middle week is
    # dropped for an odd-length window rather than double-counted).
    half = weeks // 2
    prev_half = sum(weekly[:half])
    last_half = sum(weekly[weeks - half:]) if half else 0

    def _week_label(ws: datetime) -> str:
        we = ws + timedelta(days=6)
        if ws.month == we.month:
            return f"{ws.strftime('%b')} {ws.day}-{we.day}"
        return f"{ws.strftime('%b')} {ws.day}-{we.strftime('%b')} {we.day}"

    return {
        "range": period,
        "since": since.isoformat(),
        "compliance": {
            "judged": judged,
            "on_time": on_time,
            "breached": len(breaches),
            "breached_critical": by_severity["CRITICAL"],
            "breached_alert": by_severity["ALERT"],
            "breached_other": by_severity["OTHER"],
            "pct": int(on_time / judged * 100) if judged else None,
        },
        "aging": {
            "buckets": [label for label, _ in _REVIEW_SLA_AGING_BUCKETS],
            "stages": [{"name": s, "counts": counts[s]} for s in stages],
            "total": len(breaches),
        },
        "weekly": [
            {"week_start": ws.date().isoformat(),
             "label": _week_label(ws),
             "count": c}
            for ws, c in zip(week_starts, weekly)
        ],
        "trend_pct": round((last_half - prev_half) / prev_half * 100) if prev_half else None,
        "trend_window_weeks": half,
    }


@router.get("/review-sla-breaches")
def get_review_sla_breaches_page(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(config.DASHBOARD_PANEL_PAGE_SIZE, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated continuation of the blended Result Review SLA Breaches
    list behind the "Result Review SLA" tile. The rollup's own
    _review_sla_breaches_list is nested inside _build_department_rollup
    (a closure over several rollup-local values not worth threading
    through a standalone signature just for this), so this reimplements
    the same query directly instead — it only needs org/dept scope plus
    TrWfStage.is_result_stage + default_duration_hours/days, none of
    which has any viewer/session dependency, so re-deriving it here is
    safe and gives an identical result set.
    """
    svc = _svc(db, current_user, org_id, dept_id)
    breaches = [_review_sla_public(r)
                for r in _review_sla_judged_rows(db, svc.org_id, svc.dept_ids)
                if r["breached"]]
    total = len(breaches)
    page = breaches[offset:offset + limit]
    return {
        "tickets": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/review-sla-reviews")
def get_review_sla_reviews_page(
    severity: str = Query(..., pattern="^(ALERT|CRITICAL)$"),
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    offset: int = Query(0, ge=0),
    limit: int = Query(config.DASHBOARD_PANEL_PAGE_SIZE, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Paginated continuation of the severity-split Review SLA · ALERT /
    CRITICAL reviews list. Same reasoning as get_review_sla_breaches_page
    above for reimplementing the query directly rather than reaching into
    _build_department_rollup's nested _review_sla_reviews_list_by_severity.
    """
    from models import TrWfStageInstance as _TrWfStageInstance, TrWfStage, TrWfInstance, TestingRequest, TestResult as _TestResult
    svc = _svc(db, current_user, org_id, dept_id)
    _tr_filters = [TestingRequest.organization_id == svc.org_id]
    if svc.dept_ids:
        _tr_filters.append(TestingRequest.department_id.in_(svc.dept_ids))
    rows = (
        db.query(_TrWfStageInstance, TestingRequest)
        .join(TrWfStage, TrWfStage.id == _TrWfStageInstance.stage_id)
        .join(TrWfInstance, TrWfInstance.id == _TrWfStageInstance.wf_instance_id)
        .join(TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id)
        .filter(
            *_tr_filters,
            TrWfStage.is_result_stage.is_(True),
            _TrWfStageInstance.status.in_(("completed", "rejected")),
            _TrWfStageInstance.started_at.isnot(None),
            _TrWfStageInstance.completed_at.isnot(None),
        )
        .all()
    )
    req_ids = {tr.id for _, tr in rows}
    worst_severity_by_req = {}
    if req_ids:
        sev_rank = {"CRITICAL": 2, "ALERT": 1}
        for req_id, overall in (
            db.query(_TestResult.testing_request_id, _TestResult.evaluation_result["overall"].astext)
            .filter(_TestResult.testing_request_id.in_(req_ids))
            .all()
        ):
            rank = sev_rank.get(overall)
            if rank is None:
                continue
            cur_rank = sev_rank.get(worst_severity_by_req.get(req_id))
            if cur_rank is None or rank > cur_rank:
                worst_severity_by_req[req_id] = overall
    sla_hours = {
        "ALERT": config.REVIEW_SLA_HOURS_ALERT,
        "CRITICAL": config.REVIEW_SLA_HOURS_CRITICAL,
    }[severity]
    reviewed = []
    for si, tr in rows:
        if worst_severity_by_req.get(tr.id) != severity:
            continue
        deadline = si.started_at + timedelta(hours=sla_hours)
        breached = si.completed_at > deadline
        eq = getattr(tr, "equipment", None)
        reviewed.append({
            "stage_instance_id": str(si.id),
            "request_id": str(tr.id),
            "request_number": tr.request_number,
            "stage_name": f"{severity.title()} Review",
            "test_type": f"{severity.title()} Review",
            "equipment_id": str(eq.id) if eq else None,
            "equipment_label": eq.ueic if eq else (
                tr.equipment_type.name if tr.equipment_type else "Equipment"),
            "started_at": si.started_at.isoformat(),
            "completed_at": si.completed_at.isoformat(),
            "deadline": deadline.isoformat(),
            "breached": breached,
            "hours_over": round((si.completed_at - deadline).total_seconds() / 3600, 1)
                          if breached else 0,
        })
    reviewed.sort(key=lambda r: (not r["breached"], -r["hours_over"]))
    total = len(reviewed)
    page = reviewed[offset:offset + limit]
    return {
        "tickets": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


@router.get("/calibration-interval-advisories/export")
def export_calibration_interval_advisories(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    One row per actual equipment unit behind a Calibration Interval
    Advisory (the "AI ADVISORY" panel on the Overview Dashboard) — not one
    row per cohort, since the whole point of this export is answering "so
    which relays/meters actually drove this number," the same thing the
    panel's own expandable equipment list answers on-screen. Scoped
    identically to GET /dashboard/overview (same _svc/dept_ids), so the
    export always matches whatever the caller is currently looking at.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from services.calibration_service import compute_interval_advisories

    svc = _svc(db, current_user, org_id, dept_id)
    advisories = compute_interval_advisories(db, svc.org_id, department_ids=svc.dept_ids)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calibration Advisories"

    headers = [
        "Test Type", "Manufacturer", "Model", "Direction",
        "Current Validity (mo)", "Suggested Validity (mo)",
        "Cohort Fail Rate %", "Equipment UEIC",
        "Unit Cycles", "Unit Fails",
    ]
    hdr_fill = PatternFill("solid", fgColor="1E3A8A")
    hdr_font = Font(bold=True, color="FFFFFF")
    for ci, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=ci, value=h)
        cell.fill = hdr_fill
        cell.font = hdr_font

    row_idx = 2
    for a in advisories:
        equipment = a.get("equipment") or [{}]  # at least one row even if empty
        for u in equipment:
            ws.cell(row=row_idx, column=1, value=a["test_type_name"])
            ws.cell(row=row_idx, column=2, value=a["manufacturer"])
            ws.cell(row=row_idx, column=3, value=a["model_number"])
            ws.cell(row=row_idx, column=4, value=a["direction"])
            ws.cell(row=row_idx, column=5, value=a["current_validity_months"])
            ws.cell(row=row_idx, column=6, value=a["suggested_validity_months"])
            ws.cell(row=row_idx, column=7, value=a["fail_rate_pct"])
            ws.cell(row=row_idx, column=8, value=u.get("ueic"))
            ws.cell(row=row_idx, column=9, value=u.get("cycle_count"))
            ws.cell(row=row_idx, column=10, value=u.get("fail_count"))
            row_idx += 1

    for ci, h in enumerate(headers, start=1):
        ws.column_dimensions[get_column_letter(ci)].width = max(14, len(h) + 2)

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="calibration_interval_advisories.xlsx"'},
    )


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

    # Total equipment
    total_equipment = db.query(func.count(Equipment.id)).filter(
        *_equipment_scope_filters(db, svc.org_id, dept_ids)
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

    # Critical Issues — health-score-driven (EquipmentAnalytics.risk_level),
    # not Equipment.status == 'under_repair'; see _critical_equipment_count.
    critical_issues = _critical_equipment_count(db, svc.org_id, dept_ids)

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
        *_equipment_scope_filters(db, svc.org_id, dept_ids)
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
