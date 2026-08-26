from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User, RequestCategory
from services.dashboard_service import DashboardService, invalidate_dashboard_cache
from models import TestingRequestStatus

OPEN_STATUSES = (
    TestingRequestStatus.submitted,
    TestingRequestStatus.assigned,
    TestingRequestStatus.accepted,
    TestingRequestStatus.in_progress,
    TestingRequestStatus.test_submitted,
    TestingRequestStatus.under_approval,
    TestingRequestStatus.under_review,
    TestingRequestStatus.finance_pending,
)
CLOSED_STATUSES = (
    TestingRequestStatus.approved,
    TestingRequestStatus.rejected,
    TestingRequestStatus.outcome_active,
    TestingRequestStatus.commissioned,
)

router = APIRouter(
    prefix="/dashboard",
    tags=["dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _svc(db, current_user, org_id=None, dept_id=None):
    from models import OrgUserRole, OrgRole
    from utils.common_service import get_dept_subtree_ids, get_user_dept_scope
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
    resolved_dept = dept_id
    if resolved_dept is None:
        is_org_admin, scoped_dept = get_user_dept_scope(db, current_user.id, resolved_org)
        if not is_org_admin:
            resolved_dept = scoped_dept
    dept_ids = None
    if resolved_dept:
        dept_ids = get_dept_subtree_ids(db, resolved_dept)
    return DashboardService(db, org_id=resolved_org, dept_id=resolved_dept, dept_ids=dept_ids)


@router.get("/ae")
def get_ae_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """AE / JE Dashboard â€” Field officer view.

    SRS Â§8.3.1 Field Officer Dashboard:
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

    # â”€â”€ KPIs â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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

    # â”€â”€ Upcoming tests list (next 30 days) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Open remedial actions list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Maintenance overdue list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Assigned to me (as tester) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    assigned_to_me = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.assigned_tester_id == current_user.id,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # â”€â”€ Substation (dept) count in scope â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    substation_count = len(svc.dept_ids) if svc.dept_ids else (
        db.query(func.count(func.distinct(TestingRequest.department_id))).filter(
            TestingRequest.organization_id == svc.org_id,
        ).scalar() or 0
    )

    # â”€â”€ Test compliance (90-day rolling) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Maintenance compliance (90-day) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Overdue tests list + age bands â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ TA&QC pending list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Alerts feed (ALERT / CRITICAL results) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
            'title': f"{overall} â€” {req.test_type.name if req.test_type else 'Test'} Â· {eq.ueic if eq else ''}",
            'desc': ' | '.join(flagged[:2]) if flagged else 'Test result requires attention',
            'status': overall,
            'severity': 'critical' if overall == 'CRITICAL' else 'alert',
            'timestamp': result.cts.strftime('%d-%b-%Y %H:%M') if result.cts else None,
            'substation': req.department.name if req.department else '',
        })

    # â”€â”€ Remedial compliance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Substations at a glance â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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




@router.get("/ee-rt")
def get_ee_rt_dashboard(
    org_id: Optional[UUID] = Query(None),
    dept_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """EE RT Dashboard â€” Department-level relay testing & calibration oversight.

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

    # â”€â”€ K1: Calibration compliance (on-time %) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ K2: Overdue calibrations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    overdue_calibrations = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # â”€â”€ K3: Expiring soon (due in next 30 days) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    expiring_soon = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date.between(now, thirty_days_ahead),
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # â”€â”€ K4: FAIL calibrations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    fail_count = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.status == 'rejected',
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # â”€â”€ K5: Open calibration workflows â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    from models import CalibrationRepairRecommendation, Equipment as Equip
    open_cal_workflows = db.query(func.count(CalibrationRepairRecommendation.id)).join(
        Equip, CalibrationRepairRecommendation.equipment_id == Equip.id
    ).filter(
        Equip.organization_id == svc.org_id,
        CalibrationRepairRecommendation.status == 'OPEN',
    ).scalar() or 0

    # â”€â”€ K6: Relay test compliance (non-calibration RT tests) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Total relay assets in dept scope â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    from models import Equipment as EqRT
    dept_cond_eq_rt = (EqRT.department_id.in_(svc.dept_ids)) if svc.dept_ids else True
    total_relay_assets_ee = db.query(func.count(EqRT.id)).filter(
        EqRT.organization_id == svc.org_id,
        dept_cond_eq_rt,
        EqRT.status == 'active',
    ).scalar() or 0

    # â”€â”€ Pending calibration list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Overdue calibration escalations list â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Expiring calibrations (next 30 days) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ 6-month pass/fail calibration trend â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Calibration compliance by substation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
    """SEE RT Dashboard â€” Circle-level relay testing & calibration supervision.

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

    # â”€â”€ Calibrations pending SEE RT approval (test_submitted / under_approval) â”€
    from models import TestingRequestStatus as TRSSEE
    pending_approval_count = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        dept_cond,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.status.in_([TRSSEE.test_submitted, TRSSEE.under_approval]),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # â”€â”€ Dept RT compliance breakdown (single GROUP BY â€” replaces N+1 loop) â”€
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

    # â”€â”€ Overdue calibration escalations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Expiring calibrations â€” next 30 days â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ 6-month fail trend â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
    """CEE RT RD Dashboard â€” Zone-level R&D governance & calibration executive view.

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

    # â”€â”€ Zone-wide overdue calibrations â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    overdue_calibrations_zone = db.query(func.count(TestingRequest.id)).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.is_calibration.is_(True),
        TestingRequest.due_date < now,
        TestingRequest.status.in_(OPEN_STATUSES),
        TestingRequest.is_schedule_template.is_(False),
    ).scalar() or 0

    # â”€â”€ Zone calibration breakdown by dept (single GROUP BY) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Overdue calibration escalations â€” top 10 most overdue (SRS Â§5.3) â”€
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

    # â”€â”€ Expiring calibrations list â€” due in next 30 days (SRS Â§5.3) â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Monthly fail trend â€” last 6 months (SRS Â§5.3 trend tracking) â”€â”€â”€â”€â”€
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
    Test Coordinator Dashboard â€” Condition monitoring & test evaluation oversight.
    
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
    
    # ALERT/CRITICAL — count distinct EQUIPMENT (not test requests)
    # One transformer may have DGA=ALERT + BDV=NORMAL; we count the equipment once.
    alert_eq_kpi = db.query(func.count(func.distinct(TestingRequest.equipment_id))).join(
        TestResult, TestResult.testing_request_id == TestingRequest.id
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.equipment_id.isnot(None),
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'ALERT'
    ).scalar() or 0

    critical_eq_kpi = db.query(func.count(func.distinct(TestingRequest.equipment_id))).join(
        TestResult, TestResult.testing_request_id == TestingRequest.id
    ).filter(
        TestingRequest.organization_id == svc.org_id,
        TestingRequest.equipment_id.isnot(None),
        TestResult.evaluation_result.isnot(None),
        TestResult.evaluation_result['overall'].astext == 'CRITICAL'
    ).scalar() or 0

    alert_critical_total = alert_eq_kpi + critical_eq_kpi
    
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
    
    # Load templates for threshold lookup (row_id -> min acceptable value per field)
    from models import OrgTestTemplate as _OTT
    _unique_keys = list({r.template_key for r, _, _ in active_alerts if r.template_key})
    _thr_map = {}
    if _unique_keys:
        for _tmpl in db.query(_OTT).filter(_OTT.template_key.in_(_unique_keys)).all():
            _fld_map = {}
            for _fdef in (_tmpl.template_data or {}).get('fields', []):
                _fkey = _fdef.get('key')
                if not _fkey:
                    continue
                _ev = _fdef.get('evaluation') or {}
                if _ev.get('type') == 'THRESHOLD':
                    _rows = {}
                    for _rid, _bands in (_ev.get('thresholds') or {}).items():
                        if isinstance(_bands, dict):
                            _fv = next(iter(_bands.values()), None)
                            if isinstance(_fv, dict):
                                _bands = _fv
                        _good_lo = None
                        for _bn, _br in (_bands if isinstance(_bands, dict) else {}).items():
                            if _bn.lower().split()[0] in ('good', 'normal', 'pass', 'ok'):
                                if isinstance(_br, list) and len(_br) >= 1 and _br[0] is not None:
                                    _good_lo = _br[0]
                                    break
                        _rows[str(_rid).lower()] = _good_lo
                    _fld_map[_fkey] = _rows
            _thr_map[_tmpl.template_key] = _fld_map

    alerts_feed = []
    for result, req, eq in active_alerts:
        overall = result.evaluation_result.get('overall', 'ALERT')
        _f_thr  = _thr_map.get(result.template_key or '', {})

        flagged = []
        for _field in result.evaluation_result.get('fields', []):
            if _field.get('status') not in ('CRITICAL', 'ALERT'):
                continue
            _flabel = _field.get('label') or _field.get('key', '')
            _ftype  = _field.get('type', 'number')

            if _ftype == 'table':
                _agg      = _field.get('aggregate_result') or {}
                _rows_res = [r for r in (_field.get('row_results') or [])
                             if r.get('status') in ('CRITICAL', 'ALERT')]
                _cols_res = [c for c in (_field.get('column_results') or [])
                             if c.get('status') in ('CRITICAL', 'ALERT')]
                if _agg.get('value') is not None:
                    _txt = str(_agg.get('value'))
                    if _agg.get('threshold') is not None:
                        _txt = _txt + ' (limit ' + str(_agg.get('threshold')) + ')'
                    flagged.append(_flabel + ': ' + _txt)
                elif _rows_res:
                    _rthr = _f_thr.get(_field.get('key', ''), {})
                    for _r in _rows_res[:2]:
                        _rid  = _r.get('row_id') or _r.get('key') or ''
                        _val  = _r.get('value')
                        _unit = (_r.get('unit') or '').strip()
                        _name = str(_rid).replace('_', ' ').title() if _rid else _flabel
                        _part = _name + ': ' + str(_val)
                        if _unit:
                            _part = _part + ' ' + _unit
                        _thr = (_rthr or {}).get(str(_rid).lower())
                        if _thr is not None:
                            _part = _part + ' (min ' + str(_thr) + ')'
                        flagged.append(_part)
                elif _cols_res:
                    for _c in _cols_res[:2]:
                        _col    = _c.get('column', '')
                        _val    = _c.get('value')
                        _clabel = _col.replace('_', ' ').title() if _col else _flabel
                        flagged.append(_clabel + ': ' + str(_val))
                else:
                    flagged.append(_flabel + ' (' + _field.get('status', '') + ')')
            elif _ftype == 'number':
                _val  = _field.get('value')
                _unit = (_field.get('unit') or '').strip()
                _part = _flabel + ': ' + str(_val)
                if _unit:
                    _part = _part + ' ' + _unit
                flagged.append(_part)
            else:
                _fval = _field.get('value') or _field.get('selected_value', '')
                if _fval:
                    flagged.append(_flabel + ': ' + str(_fval))
                else:
                    flagged.append(_flabel + ' (' + _field.get('status', '') + ')')

        test_name = req.test_type.name if req.test_type else 'Test'
        alerts_feed.append({
            'id': str(result.id),
            'ueic': eq.ueic if eq else '',
            'title': overall + ' - ' + test_name,
            'severity': 'critical' if overall == 'CRITICAL' else 'alert',
            'timestamp': result.cts.strftime('%d-%b-%Y %H:%M') if result.cts else None,
            'message': ' | '.join(flagged[:3]) if flagged else 'Test result requires attention',
            'equipment': eq.manufacturer or eq.ueic if eq else '',
            'substation': req.department.name if req.department else '',
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
                'sub': f"{alert_eq_kpi} ALERT - {critical_eq_kpi} CRITICAL",
                'trend': None,
                'trend_dir': 'up' if critical_eq_kpi > 0 else 'neutral',
                'colour': 'red' if critical_eq_kpi > 0 else ('amber' if alert_eq_kpi > 0 else 'green')
            },
            {
                'label': 'Open Remedial Actions',
                'value': open_remediation,
                'display': str(open_remediation),
                'sub': f"{overdue_remediation} overdue Â· oldest pending",
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

