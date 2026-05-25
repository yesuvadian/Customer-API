"""
surveillance_workflow.py
────────────────────────
Surveillance workflow execution endpoints.

Handles post-commissioning surveillance workflow operations including:
- Quarterly review submissions
- Final evaluation
- Test tracking and completion
- Stage transitions

Uses repair_stage_roles for permission control (same as repair workflows).
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_
from sqlalchemy.orm import Session, joinedload

from auth_utils import get_current_user
from database import get_db
from models import (
    Equipment,
    RepairWorkflow,
    RepairStageInstance,
    TestingRequest,
    User,
)
from services.repair_workflow_service import RepairWorkflowService
from services.surveillance_template_service import SurveillanceTemplateService
from utils.common_service import get_user_dept_scope

router = APIRouter(
    prefix="/surveillance-workflows",
    tags=["surveillance-workflows"],
    dependencies=[Depends(get_current_user)],
)


# =============================================================================
# Helper Functions
# =============================================================================

def _check_workflow_access(db: Session, workflow_id: UUID, user: User) -> RepairWorkflow:
    """
    Verify user has access to this surveillance workflow.

    Enforces organization/department scoping based on user role.
    """
    from utils.common_service import get_user_dept_scope

    workflow = (
        db.query(RepairWorkflow)
        .filter(
            RepairWorkflow.id == workflow_id,
            RepairWorkflow.workflow_type == 'surveillance'
        )
        .first()
    )

    if not workflow:
        raise HTTPException(404, "Surveillance workflow not found")

    # Check organization match
    if workflow.organization_id != user.organization_id:
        raise HTTPException(403, "Access denied: Different organization")

    # Check department scope (if user is not org admin)
    is_org_admin, user_dept_id = get_user_dept_scope(db, user.id, None)

    if not is_org_admin and user_dept_id:
        if workflow.department_id != user_dept_id:
            raise HTTPException(403, "Access denied: Different department")

    return workflow


def _serialize_workflow(wf: RepairWorkflow, current_stage: Optional[RepairStageInstance] = None) -> dict:
    """Serialize surveillance workflow to dict."""
    return {
        'id': str(wf.id),
        'workflow_number': wf.workflow_number,
        'workflow_type': wf.workflow_type,
        'status': wf.status,
        'equipment_id': str(wf.equipment_id) if wf.equipment_id else None,
        'equipment_name': wf.equipment.name if wf.equipment else None,
        'parent_workflow_id': str(wf.parent_workflow_id) if wf.parent_workflow_id else None,
        'organization_id': str(wf.organization_id) if wf.organization_id else None,
        'department_id': str(wf.department_id) if wf.department_id else None,
        'start_date': wf.start_date.isoformat() if wf.start_date else None,
        'end_date': wf.end_date.isoformat() if wf.end_date else None,
        'current_stage': {
            'stage_number': current_stage.stage.stage_number if current_stage and current_stage.stage else None,
            'stage_name': current_stage.stage.name if current_stage and current_stage.stage else None,
            'quarter_number': current_stage.quarter_number if current_stage else None,
            'status': current_stage.status if current_stage else None,
        } if current_stage else None,
        'progress': wf.progress or 0,
        'created_at': wf.created_at.isoformat() if wf.created_at else None,
    }


def _serialize_test(test: TestingRequest) -> dict:
    """Serialize testing request to dict."""
    return {
        'id': str(test.id),
        'request_number': test.request_number,
        'title': test.title,
        'test_type_id': test.test_type_id,
        'test_type_name': test.test_type.name if test.test_type else None,
        'surveillance_quarter': test.surveillance_quarter,
        'status': test.status.value if hasattr(test.status, 'value') else test.status,
        'result_status': test.form_data.get('result_status') if test.form_data else None,
        'scheduled_start_date': test.scheduled_start_date.isoformat() if test.scheduled_start_date else None,
        'completed_at': test.completed_at.isoformat() if test.completed_at else None,
        'priority': test.priority,
    }


# =============================================================================
# Workflow Listing & Detail
# =============================================================================

@router.get("")
def list_surveillance_workflows(
    status: Optional[str] = Query(None, description="Filter by workflow status"),
    quarter: Optional[int] = Query(None, ge=1, le=4, description="Filter by current quarter"),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    List surveillance workflows for current user's organization/department.

    Automatically scoped by:
    - Organization (always filtered by user.organization_id)
    - Department (filtered if user is not org admin)

    Query params:
    - status: active, completed, on_hold, cancelled
    - quarter: 1-4 (filter by current quarter stage)
    - skip/limit: Pagination
    """
    # Get user's department scope
    is_org_admin, user_dept_id = get_user_dept_scope(db, user.id, None)

    # Base query with eager loading (avoid N+1)
    query = db.query(RepairWorkflow).options(
        joinedload(RepairWorkflow.equipment),
        joinedload(RepairWorkflow.current_stage_instance).joinedload(RepairStageInstance.stage)
    ).filter(
        RepairWorkflow.workflow_type == 'surveillance',
        RepairWorkflow.organization_id == user.organization_id,  # Org filter
    )

    # Department filter (if not org admin)
    # Note: RepairWorkflow doesn't have department_id, department info comes from Equipment
    if not is_org_admin and user_dept_id:
        query = query.join(Equipment, Equipment.id == RepairWorkflow.equipment_id).filter(
            Equipment.department_id == user_dept_id
        )

    # Apply optional filters
    if status:
        query = query.filter(RepairWorkflow.status == status)

    if quarter:
        query = query.join(
            RepairStageInstance,
            RepairStageInstance.id == RepairWorkflow.current_stage_instance_id
        ).filter(RepairStageInstance.quarter_number == quarter)

    # Get total count before pagination
    total = query.count()

    # Apply pagination
    workflows = query.order_by(RepairWorkflow.created_at.desc()).offset(skip).limit(limit).all()

    # Serialize results
    items = [
        _serialize_workflow(wf, wf.current_stage_instance)
        for wf in workflows
    ]

    return {
        'total': total,
        'skip': skip,
        'limit': limit,
        'items': items,
    }


@router.get("/{workflow_id}")
def get_surveillance_workflow(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get detailed surveillance workflow information.

    Returns:
    - Full workflow detail (all stages, timeline)
    - Surveillance-specific summary (tests, quality rating, trends)

    Permission: User must be in same org/dept as workflow.
    """
    # Check access
    workflow = _check_workflow_access(db, workflow_id, user)

    # Get workflow detail from existing service
    workflow_detail = RepairWorkflowService(db).get_workflow_detail(workflow_id)

    # Add surveillance-specific summary
    try:
        summary = SurveillanceTemplateService.get_overall_summary(db, workflow_id)
        workflow_detail['surveillance_summary'] = summary
    except Exception as e:
        # Don't fail if summary calculation fails
        workflow_detail['surveillance_summary'] = {
            'error': str(e),
            'total_tests': 0,
            'quality_rating': 'Unknown'
        }

    return workflow_detail


# =============================================================================
# Testing Requests
# =============================================================================

@router.get("/{workflow_id}/tests")
def get_surveillance_tests(
    workflow_id: UUID,
    quarter: Optional[int] = Query(None, ge=1, le=4, description="Filter by quarter"),
    status: Optional[str] = Query(None, description="Filter by test status"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get all testing requests for a surveillance workflow.

    Query params:
    - quarter: 1-4 (filter by specific quarter)
    - status: submitted, in_progress, completed, cancelled

    Permission: User must have access to the workflow.
    """
    # Check access
    workflow = _check_workflow_access(db, workflow_id, user)

    # Build query
    query = db.query(TestingRequest).options(
        joinedload(TestingRequest.test_type)
    ).filter(
        TestingRequest.surveillance_workflow_id == workflow_id
    )

    # Apply filters
    if quarter:
        query = query.filter(TestingRequest.surveillance_quarter == quarter)

    if status:
        query = query.filter(TestingRequest.status == status)

    # Execute query
    tests = query.order_by(
        TestingRequest.surveillance_quarter,
        TestingRequest.test_type_id
    ).all()

    # Serialize results
    items = [_serialize_test(test) for test in tests]

    return {
        'workflow_id': str(workflow_id),
        'quarter': quarter,
        'status': status,
        'total': len(items),
        'items': items,
    }


@router.get("/{workflow_id}/quarter/{quarter_number}/tests")
def get_quarter_tests(
    workflow_id: UUID,
    quarter_number: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get tests for a specific quarter with completion status.

    Returns test list plus summary:
    - total_tests: Expected number of tests
    - completed_tests: Number completed
    - abnormal_tests: Number with abnormal results
    - all_complete: Boolean flag

    Used by UI to show quarter progress and enable/disable submission.

    Permission: User must have access to the workflow.
    """
    if quarter_number < 1 or quarter_number > 4:
        raise HTTPException(400, "Quarter number must be between 1 and 4")

    # Check access
    workflow = _check_workflow_access(db, workflow_id, user)

    # Get tests
    tests = db.query(TestingRequest).options(
        joinedload(TestingRequest.test_type)
    ).filter(
        TestingRequest.surveillance_workflow_id == workflow_id,
        TestingRequest.surveillance_quarter == quarter_number
    ).all()

    # Calculate summary
    total_tests = len(tests)
    completed_tests = len([t for t in tests if t.status == 'completed'])
    abnormal_tests = len([
        t for t in tests
        if t.form_data and t.form_data.get('result_status') in ['FAIL', 'MARGINAL', 'CRITICAL', 'ALERT']
    ])
    all_complete = total_tests > 0 and completed_tests == total_tests

    return {
        'workflow_id': str(workflow_id),
        'quarter_number': quarter_number,
        'tests': [_serialize_test(t) for t in tests],
        'summary': {
            'total_tests': total_tests,
            'completed_tests': completed_tests,
            'abnormal_tests': abnormal_tests,
            'abnormal_rate': (abnormal_tests / completed_tests * 100) if completed_tests > 0 else 0,
            'all_complete': all_complete,
        }
    }


# =============================================================================
# Stage Forms & Data
# =============================================================================

@router.get("/{workflow_id}/quarter/{quarter_number}/review-data")
def get_quarter_review_data(
    workflow_id: UUID,
    quarter_number: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get pre-populated data for quarterly review form.

    Automatically populates:
    - Test summary table (all tests for this quarter)
    - Statistics (total tests, abnormal count, abnormal rate)
    - Equipment details
    - Parent workflow reference

    Used when officer opens the quarterly review stage form.

    Permission: User must have access to the workflow + can_edit role for current stage.
    """
    if quarter_number < 1 or quarter_number > 4:
        raise HTTPException(400, "Quarter number must be between 1 and 4")

    # Check access
    workflow = _check_workflow_access(db, workflow_id, user)

    # Get pre-populated data
    try:
        data = SurveillanceTemplateService.get_quarter_review_data(
            db, workflow_id, quarter_number
        )
        return data
    except Exception as e:
        raise HTTPException(500, f"Failed to get quarter review data: {str(e)}")


@router.get("/{workflow_id}/final-evaluation-data")
def get_final_evaluation_data(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get pre-populated data for final evaluation form.

    Automatically populates:
    - 24-month summary (total tests, abnormal rate, quality rating)
    - Quarterly breakdown table
    - Test trends (DGA, BDV, IR, Oil Quality: Improving/Stable/Deteriorating)
    - Vendor performance data

    Used when officer opens the final evaluation stage form.

    Permission: User must have access to the workflow + can_edit role for final stage.
    """
    # Check access
    workflow = _check_workflow_access(db, workflow_id, user)

    # Get pre-populated data
    try:
        data = SurveillanceTemplateService.get_final_evaluation_data(db, workflow_id)
        return data
    except Exception as e:
        raise HTTPException(500, f"Failed to get final evaluation data: {str(e)}")


# =============================================================================
# Summary & Statistics
# =============================================================================

@router.get("/{workflow_id}/summary")
def get_surveillance_summary(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get comprehensive surveillance summary.

    Returns:
    - Overall statistics (total tests, abnormal rate, quality rating)
    - Quarterly summaries (Q1-Q4 individual stats)
    - Workflow metadata (dates, equipment, status)

    Permission: User must have access to the workflow.
    """
    # Check access
    workflow = _check_workflow_access(db, workflow_id, user)

    # Get overall summary
    try:
        summary = SurveillanceTemplateService.get_overall_summary(db, workflow_id)
    except Exception as e:
        raise HTTPException(500, f"Failed to get overall summary: {str(e)}")

    # Add quarterly summaries
    quarterly_summaries = []
    for quarter in range(1, 5):
        try:
            quarter_summary = SurveillanceTemplateService.get_test_summary_for_quarter(
                db, workflow_id, quarter
            )
            quarter_summary['quarter'] = quarter
            quarterly_summaries.append(quarter_summary)
        except Exception:
            # Skip failed quarter calculation
            quarterly_summaries.append({
                'quarter': quarter,
                'total_tests': 0,
                'error': 'Calculation failed'
            })

    summary['quarters'] = quarterly_summaries

    return summary


# =============================================================================
# Stage Operations (Reuse existing repair workflow service)
# =============================================================================

@router.get("/{workflow_id}/current-form")
def get_current_form(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get current stage form template and saved data.

    Reuses RepairWorkflowService - surveillance uses same stage infrastructure.

    Permission: User must have access to the workflow.
    """
    # Check access
    workflow = _check_workflow_access(db, workflow_id, user)

    try:
        return RepairWorkflowService(db).get_current_form(workflow_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/{workflow_id}/timeline")
def get_timeline(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get full audit trail for surveillance workflow.

    Shows chronological list of all actions:
    - Stage transitions
    - Form submissions
    - Approvals/rejections
    - Document uploads

    Permission: User must have access to the workflow.
    """
    # Check access
    workflow = _check_workflow_access(db, workflow_id, user)

    return RepairWorkflowService(db).get_timeline(workflow_id)


@router.get("/{workflow_id}/progress")
def get_progress(
    workflow_id: UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Get current stage and progress percentage.

    Returns:
    - current_stage: Stage name and number
    - progress: 0-100%
    - status: active/completed/on_hold

    Permission: User must have access to the workflow.
    """
    # Check access
    workflow = _check_workflow_access(db, workflow_id, user)

    try:
        return RepairWorkflowService(db).get_progress(workflow_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
