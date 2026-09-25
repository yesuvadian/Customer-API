"""
surveillance_dashboard.py
─────────────────────────
Surveillance workflow dashboard and analytics endpoints.

Provides organization-wide surveillance metrics:
- Active surveillance workflows by status
- Quality ratings distribution
- Abnormal test rates
- Quarterly completion rates
- Equipment health trends

Uses organization/department scoping for data security.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    Equipment,
    RepairStageDefinition,
    RepairStageInstance,
    RepairSurveillanceTest,
    RepairWorkflow,
    TestingRequest,
    User,
)
from services.surveillance_config_service import SurveillanceConfigService
from utils.common_service import get_user_dept_scope

router = APIRouter(
    prefix="/surveillance-dashboard",
    tags=["surveillance-dashboard"],
    dependencies=[Depends(get_current_user)],
)


# =============================================================================
# Main Dashboard
# =============================================================================

@router.get("/")
def get_surveillance_dashboard(
    department_id: Optional[UUID] = Query(None, description="Filter by department"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get comprehensive surveillance dashboard for organization.

    Returns:
    - workflow_summary: Active/completed workflow counts by quarter
    - quality_metrics: Overall quality ratings distribution
    - test_statistics: Total tests, abnormal rates, completion rates
    - recent_activities: Latest workflow actions
    - alerts: Workflows needing attention (failed tests, overdue reviews)

    Scoping:
    - Organization: Always filtered by user.organization_id
    - Department: Optionally filter by department_id (if user has permission)
    """
    org_id = user.organization_id
    is_org_admin, user_dept_id = get_user_dept_scope(db, user.id, None)

    # Apply department filter
    if department_id:
        # Check if user has permission to view this department
        if not is_org_admin and user_dept_id != department_id:
            raise HTTPException(403, "Access denied to this department")
        dept_filter = department_id
    elif not is_org_admin and user_dept_id:
        # Non-admin users see only their department
        dept_filter = user_dept_id
    else:
        # Org admins see all departments
        dept_filter = None

    # ── 1. Workflow Summary ──────────────────────────────────────────────────
    workflow_query = db.query(RepairWorkflow).outerjoin(
        Equipment, Equipment.id == RepairWorkflow.equipment_id
    ).filter(
        RepairWorkflow.workflow_type == 'surveillance',
        or_(
            Equipment.organization_id == org_id,
            RepairWorkflow.organization_id == org_id,
        )
    )

    if dept_filter:
        workflow_query = workflow_query.filter(
            Equipment.department_id == dept_filter
        )

    # Count by status
    status_counts_raw = (
        workflow_query
        .with_entities(
            RepairWorkflow.status,
            func.count(RepairWorkflow.id).label('count')
        )
        .group_by(RepairWorkflow.status)
        .all()
    )
    status_counts = {status: count for status, count in status_counts_raw}

    # Count by current quarter
    quarter_counts_raw = (
        workflow_query
        .join(
            RepairStageInstance,
            RepairStageInstance.id == RepairWorkflow.current_stage_instance_id
        )
        .filter(RepairWorkflow.status == 'active')
        .with_entities(
            RepairStageInstance.quarter_number,
            func.count(RepairWorkflow.id).label('count')
        )
        .group_by(RepairStageInstance.quarter_number)
        .all()
    )
    quarter_counts = {
        f'Q{quarter}' if quarter else 'Final': count
        for quarter, count in quarter_counts_raw
    }

    workflow_summary = {
        'by_status': {
            'active': status_counts.get('active', 0),
            'completed': status_counts.get('completed', 0),
            'on_hold': status_counts.get('on_hold', 0),
            'cancelled': status_counts.get('cancelled', 0),
        },
        'by_quarter': {
            'Q1': quarter_counts.get('Q1', 0),
            'Q2': quarter_counts.get('Q2', 0),
            'Q3': quarter_counts.get('Q3', 0),
            'Q4': quarter_counts.get('Q4', 0),
            'Final': quarter_counts.get('Final', 0),
        },
        'total': sum(status_counts.values()),
    }

    # ── 2. Quality Metrics ───────────────────────────────────────────────────
    # Get all completed surveillance workflows
    completed_workflows = workflow_query.filter(
        RepairWorkflow.status == 'completed'
    ).all()

    quality_distribution = {
        'Excellent': 0,  # 0% abnormal
        'Good': 0,       # <20% abnormal
        'Fair': 0,       # 20-50% abnormal
        'Poor': 0,       # ≥50% abnormal
    }

    for wf in completed_workflows:
        # Get all tests for this workflow
        all_tests = db.query(RepairSurveillanceTest).filter(
            RepairSurveillanceTest.surveillance_workflow_id == wf.id
        ).all()

        completed_tests = [t for t in all_tests if t.test_status == 'completed']
        abnormal_tests = [t for t in all_tests if t.is_abnormal]

        # Calculate quality rating
        quality_rating = SurveillanceConfigService.calculate_quality_rating(
            db,
            total_tests=len(completed_tests),
            abnormal_tests=len(abnormal_tests),
            organization_id=org_id,
            department_id=dept_filter
        )

        quality_distribution[quality_rating] = quality_distribution.get(quality_rating, 0) + 1

    quality_metrics = {
        'distribution': quality_distribution,
        'total_evaluated': len(completed_workflows),
    }

    # ── 3. Test Statistics ───────────────────────────────────────────────────
    # Get all tests for active and completed workflows
    workflow_ids = [wf.id for wf in workflow_query.all()]

    if workflow_ids:
        test_stats_raw = (
            db.query(
                func.count(RepairSurveillanceTest.id).label('total_tests'),
                func.count(
                    func.nullif(RepairSurveillanceTest.test_status == 'completed', False)
                ).label('completed_tests'),
                func.count(
                    func.nullif(RepairSurveillanceTest.is_abnormal, False)
                ).label('abnormal_tests'),
            )
            .filter(RepairSurveillanceTest.surveillance_workflow_id.in_(workflow_ids))
            .first()
        )

        total_tests = test_stats_raw.total_tests or 0
        completed_tests = test_stats_raw.completed_tests or 0
        abnormal_tests = test_stats_raw.abnormal_tests or 0

        test_statistics = {
            'total_tests': total_tests,
            'completed_tests': completed_tests,
            'pending_tests': total_tests - completed_tests,
            'abnormal_tests': abnormal_tests,
            'abnormal_rate': (abnormal_tests / completed_tests * 100) if completed_tests > 0 else 0,
            'completion_rate': (completed_tests / total_tests * 100) if total_tests > 0 else 0,
        }
    else:
        test_statistics = {
            'total_tests': 0,
            'completed_tests': 0,
            'pending_tests': 0,
            'abnormal_tests': 0,
            'abnormal_rate': 0,
            'completion_rate': 0,
        }

    # ── 4. Recent Activities ─────────────────────────────────────────────────
    # Get latest 10 surveillance workflows (active or recently completed)
    recent_workflows = (
        workflow_query
        .filter(
            or_(
                RepairWorkflow.status == 'active',
                and_(
                    RepairWorkflow.status == 'completed',
                    RepairWorkflow.completed_at >= datetime.now(timezone.utc) - timedelta(days=30)
                )
            )
        )
        .order_by(RepairWorkflow.modified_at.desc())
        .limit(10)
        .all()
    )

    recent_activities = []
    for wf in recent_workflows:
        current_stage = None
        if wf.current_stage_instance_id:
            current_stage = db.query(RepairStageInstance).filter(
                RepairStageInstance.id == wf.current_stage_instance_id
            ).first()

        recent_activities.append({
            'workflow_id': str(wf.id),
            'equipment_name': wf.equipment.ueic if wf.equipment else 'Unknown',
            'status': wf.status,
            'current_stage': current_stage.stage.name if current_stage and current_stage.stage else 'N/A',
            'quarter': current_stage.quarter_number if current_stage else None,
            'progress': wf.progress or 0,
            'last_updated': wf.modified_at.isoformat() if wf.modified_at else None,
        })

    # ── 5. Alerts & Attention Needed ─────────────────────────────────────────
    alerts = []

    # Alert 1: Workflows with failed tests
    workflows_with_failures = (
        db.query(RepairWorkflow.id, Equipment.ueic, func.count(RepairSurveillanceTest.id))
        .join(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .join(
            RepairSurveillanceTest,
            RepairSurveillanceTest.surveillance_workflow_id == RepairWorkflow.id
        )
        .filter(
            RepairWorkflow.workflow_type == 'surveillance',
            RepairWorkflow.status == 'active',
            RepairSurveillanceTest.is_abnormal.is_(True),
            Equipment.organization_id == org_id
        )
        .group_by(RepairWorkflow.id, Equipment.ueic)
        .all()
    )

    for wf_id, equipment_name, failed_count in workflows_with_failures:
        alerts.append({
            'type': 'failed_tests',
            'severity': 'warning',
            'workflow_id': str(wf_id),
            'equipment': equipment_name,
            'message': f'{failed_count} test(s) failed - requires attention',
        })

    # Alert 2: Workflows with incomplete tests (pending submission)
    workflows_with_pending = (
        db.query(RepairWorkflow.id, Equipment.ueic, RepairStageInstance.quarter_number)
        .join(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .join(
            RepairStageInstance,
            RepairStageInstance.id == RepairWorkflow.current_stage_instance_id
        )
        .join(
            TestingRequest,
            and_(
                TestingRequest.surveillance_workflow_id == RepairWorkflow.id,
                TestingRequest.surveillance_quarter == RepairStageInstance.quarter_number
            )
        )
        .filter(
            RepairWorkflow.workflow_type == 'surveillance',
            RepairWorkflow.status == 'active',
            RepairStageInstance.quarter_number.isnot(None),  # Only quarterly stages
            TestingRequest.status.in_(['submitted', 'in_progress']),
            Equipment.organization_id == org_id
        )
        .group_by(RepairWorkflow.id, Equipment.ueic, RepairStageInstance.quarter_number)
        .all()
    )

    for wf_id, equipment_name, quarter in workflows_with_pending:
        alerts.append({
            'type': 'incomplete_tests',
            'severity': 'info',
            'workflow_id': str(wf_id),
            'equipment': equipment_name,
            'message': f'Q{quarter} has incomplete tests',
        })

    # Alert 3: Overdue quarterly reviews (missed SLA deadlines)
    now = datetime.now(timezone.utc)
    overdue_stages = (
        db.query(
            RepairWorkflow.id,
            Equipment.ueic,
            RepairStageInstance.quarter_number,
            RepairStageInstance.started_at,
            RepairStageDefinition.default_duration_days
        )
        .join(Equipment, Equipment.id == RepairWorkflow.equipment_id)
        .join(
            RepairStageInstance,
            RepairStageInstance.id == RepairWorkflow.current_stage_instance_id
        )
        .join(
            RepairStageDefinition,
            RepairStageDefinition.id == RepairStageInstance.stage_id
        )
        .filter(
            RepairWorkflow.workflow_type == 'surveillance',
            RepairWorkflow.status == 'active',
            RepairStageInstance.started_at.isnot(None),
            RepairStageDefinition.default_duration_days.isnot(None),
            Equipment.organization_id == org_id
        )
        .all()
    )

    for wf_id, equipment_name, quarter, started_at, duration_days in overdue_stages:
        # Make started_at timezone-aware if it's naive (database timestamps are usually naive)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        deadline = started_at + timedelta(days=duration_days)
        days_overdue = (now - deadline).days

        if days_overdue > 0:
            alerts.append({
                'type': 'overdue_stage',
                'severity': 'high',
                'workflow_id': str(wf_id),
                'equipment': equipment_name,
                'message': f'Q{quarter} review overdue by {days_overdue} day(s)',
                'days_overdue': days_overdue,
            })

    # ── Response ─────────────────────────────────────────────────────────────
    return {
        'organization_id': str(org_id),
        'department_id': str(dept_filter) if dept_filter else None,
        'workflow_summary': workflow_summary,
        'quality_metrics': quality_metrics,
        'test_statistics': test_statistics,
        'recent_activities': recent_activities,
        'alerts': alerts[:10],  # Limit to 10 most critical
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }


# =============================================================================
# Analytics & Trends
# =============================================================================

@router.get("/trends")
def get_surveillance_trends(
    period_days: int = Query(90, ge=30, le=365, description="Analysis period in days"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get surveillance quality trends over time.

    Shows how abnormal test rates have changed over the specified period.

    Returns:
    - monthly_abnormal_rates: Abnormal rate per month
    - quality_rating_changes: How quality ratings evolved
    - equipment_health_trend: Overall equipment health direction

    Scoping: Organization-wide (filtered by user.organization_id)
    """
    org_id = user.organization_id
    is_org_admin, user_dept_id = get_user_dept_scope(db, user.id, None)

    # Date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=period_days)

    # Get workflows in period
    workflow_query = db.query(RepairWorkflow).outerjoin(
        Equipment, Equipment.id == RepairWorkflow.equipment_id
    ).filter(
        RepairWorkflow.workflow_type == 'surveillance',
        RepairWorkflow.created_at >= start_date,
        or_(
            Equipment.organization_id == org_id,
            RepairWorkflow.organization_id == org_id,
        )
    )

    if not is_org_admin and user_dept_id:
        workflow_query = workflow_query.filter(
            Equipment.department_id == user_dept_id
        )

    workflows = workflow_query.all()
    workflow_ids = [wf.id for wf in workflows]

    if not workflow_ids:
        return {
            'period_days': period_days,
            'monthly_abnormal_rates': [],
            'equipment_health_trend': 'stable',
            'message': 'No surveillance data in this period'
        }

    # Group tests by month
    monthly_stats = {}

    for wf in workflows:
        tests = db.query(RepairSurveillanceTest).filter(
            RepairSurveillanceTest.surveillance_workflow_id == wf.id,
            RepairSurveillanceTest.tested_at.isnot(None),
            RepairSurveillanceTest.tested_at >= start_date
        ).all()

        for test in tests:
            if test.tested_at:
                month_key = test.tested_at.strftime('%Y-%m')

                if month_key not in monthly_stats:
                    monthly_stats[month_key] = {
                        'total': 0,
                        'completed': 0,
                        'abnormal': 0,
                    }

                monthly_stats[month_key]['total'] += 1
                if test.test_status == 'completed':
                    monthly_stats[month_key]['completed'] += 1
                if test.is_abnormal:
                    monthly_stats[month_key]['abnormal'] += 1

    # Calculate monthly abnormal rates
    monthly_abnormal_rates = []
    for month, stats in sorted(monthly_stats.items()):
        rate = (stats['abnormal'] / stats['completed'] * 100) if stats['completed'] > 0 else 0
        monthly_abnormal_rates.append({
            'month': month,
            'abnormal_rate': round(rate, 1),
            'total_tests': stats['total'],
            'abnormal_tests': stats['abnormal'],
        })

    # Determine trend
    if len(monthly_abnormal_rates) >= 2:
        first_rate = monthly_abnormal_rates[0]['abnormal_rate']
        last_rate = monthly_abnormal_rates[-1]['abnormal_rate']

        if last_rate < first_rate - 5:
            trend = 'improving'
        elif last_rate > first_rate + 5:
            trend = 'deteriorating'
        else:
            trend = 'stable'
    else:
        trend = 'insufficient_data'

    return {
        'period_days': period_days,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'monthly_abnormal_rates': monthly_abnormal_rates,
        'equipment_health_trend': trend,
        'total_workflows_analyzed': len(workflows),
    }


# =============================================================================
# Equipment-Specific Analytics
# =============================================================================

@router.get("/equipment/{equipment_id}")
def get_equipment_surveillance_history(
    equipment_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get surveillance history for a specific equipment.

    Shows all surveillance workflows (past and current) for this equipment.

    Returns:
    - workflows: List of all surveillance workflows
    - overall_quality: Average quality rating across all workflows
    - test_history: All tests performed on this equipment

    Permission: User must have access to equipment's organization/department.
    """
    # Get equipment
    equipment = db.query(Equipment).filter(
        Equipment.id == equipment_id,
        Equipment.organization_id == user.organization_id
    ).first()

    if not equipment:
        raise HTTPException(404, "Equipment not found or access denied")

    # Check department access
    is_org_admin, user_dept_id = get_user_dept_scope(db, user.id, None)
    if not is_org_admin and user_dept_id and equipment.department_id != user_dept_id:
        raise HTTPException(403, "Access denied to this equipment's department")

    # Get all surveillance workflows for this equipment
    workflows = db.query(RepairWorkflow).filter(
        RepairWorkflow.equipment_id == equipment_id,
        RepairWorkflow.workflow_type == 'surveillance'
    ).order_by(RepairWorkflow.started_at.desc()).all()

    # Calculate overall quality
    quality_ratings = []
    for wf in workflows:
        if wf.status == 'completed':
            all_tests = db.query(RepairSurveillanceTest).filter(
                RepairSurveillanceTest.surveillance_workflow_id == wf.id
            ).all()

            completed = [t for t in all_tests if t.test_status == 'completed']
            abnormal = [t for t in all_tests if t.is_abnormal]

            rating = SurveillanceConfigService.calculate_quality_rating(
                db,
                total_tests=len(completed),
                abnormal_tests=len(abnormal),
                organization_id=equipment.organization_id,
                department_id=equipment.department_id
            )
            quality_ratings.append(rating)

    # Serialize workflows
    workflow_list = []
    for wf in workflows:
        workflow_list.append({
            'id': str(wf.id),
            'status': wf.status,
            'start_date': wf.start_date.isoformat() if wf.start_date else None,
            'end_date': wf.end_date.isoformat() if wf.end_date else None,
            'progress': wf.progress or 0,
        })

    return {
        'equipment_id': str(equipment_id),
        'equipment_name': equipment.ueic,
        'equipment_type': equipment.equipment_type.name if equipment.equipment_type else None,
        'workflows': workflow_list,
        'total_workflows': len(workflows),
        'overall_quality_ratings': quality_ratings,
        'current_workflow': workflow_list[0] if workflow_list else None,
    }
