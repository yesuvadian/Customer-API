"""
Testing Request Approval Endpoints
Handles approval workflow with tester role selection and assignment
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID

from database import get_db
from models import User, TestingRequest, OrgRole, OrgUserRole
from schemas import (
    TestingRequestOut,
    ApproverTesterSelection,
    ApprovalResponse,
    TesterInfo
)
from auth_utils import get_current_user
from services.testing_request_workflow_service import TestingRequestWorkflowService

router = APIRouter(prefix="/testing-requests/approvals", tags=["Testing Request Approvals"])


@router.get("/pending", response_model=List[TestingRequestOut])
def get_pending_approvals(
    organization_id: Optional[UUID] = None,
    department_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all testing requests pending approval.
    Filters by organization and department based on user's permissions.
    """
    query = db.query(TestingRequest).filter(
        TestingRequest.status == 'pending_approval'
    )

    # Filter by organization if user belongs to one
    if current_user.organization_id:
        query = query.filter(TestingRequest.organization_id == current_user.organization_id)
    elif organization_id:
        query = query.filter(TestingRequest.organization_id == organization_id)

    # Filter by department hierarchy if specified
    if department_id:
        # TODO: Add department hierarchy filtering
        query = query.filter(TestingRequest.department_id == department_id)

    requests = query.order_by(TestingRequest.cts.desc()).all()
    return requests


@router.get("/{request_id}/tester-roles", response_model=List[dict])
def get_available_tester_roles(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all tester roles available for the testing request's organization.
    Returns roles that contain the word "tester" (configurable).
    """
    # Get the testing request
    testing_request = db.query(TestingRequest).filter(
        TestingRequest.id == request_id
    ).first()

    if not testing_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testing request not found"
        )

    # Get all active organization roles with "Tester" in name
    tester_roles = db.query(OrgRole).filter(
        OrgRole.organization_id == testing_request.organization_id,
        OrgRole.is_active == True,
        OrgRole.name.ilike('%tester%')  # Roles containing "tester"
    ).all()

    result = []
    for role in tester_roles:
        # Count active users with this role
        user_count = db.query(OrgUserRole).filter(
            OrgUserRole.org_role_id == role.id,
            OrgUserRole.is_active == True
        ).count()

        result.append({
            "role_id": str(role.id),
            "role_name": role.name,
            "description": role.description,
            "user_count": user_count
        })

    return result


@router.get("/{request_id}/tester-roles/{role_id}/users", response_model=List[TesterInfo])
def get_users_by_tester_role(
    request_id: UUID,
    role_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all users assigned to a specific tester role.
    Shows their current workload for informed selection.
    """
    # Get the testing request
    testing_request = db.query(TestingRequest).filter(
        TestingRequest.id == request_id
    ).first()

    if not testing_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testing request not found"
        )

    # Get all active users with this role
    users = db.query(User).join(
        OrgUserRole, OrgUserRole.user_id == User.id
    ).filter(
        OrgUserRole.org_role_id == role_id,
        OrgUserRole.is_active == True,
        User.isactive == True
    ).all()

    result = []
    for user in users:
        # Calculate current workload
        active_count = db.query(TestingRequest).filter(
            TestingRequest.assigned_tester_id == user.id,
            TestingRequest.status.in_(['assigned', 'accepted', 'in_progress'])
        ).count()

        result.append(TesterInfo(
            user_id=str(user.id),
            email=user.email,
            name=f"{user.firstname or ''} {user.lastname or ''}".strip() or user.email,
            department_id=str(user.department_id) if user.department_id else None,
            active_requests=active_count
        ))

    # Sort by workload (least loaded first)
    result.sort(key=lambda x: x.active_requests)

    return result


@router.post("/{request_id}/approve-and-assign", response_model=ApprovalResponse)
def approve_and_assign_tester(
    request_id: UUID,
    selection: ApproverTesterSelection,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Approve a testing request and assign to a specific tester.

    Workflow:
    1. Approver selects tester role → sees list of users
    2. Approver selects specific user from list
    3. System approves request and assigns to selected user
    """
    # Get the testing request
    testing_request = db.query(TestingRequest).filter(
        TestingRequest.id == request_id
    ).first()

    if not testing_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testing request not found"
        )

    # Validate state
    if testing_request.status != 'pending_approval':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request must be in 'pending_approval' state, currently: {testing_request.status}"
        )

    # Validate tester exists and has the role
    tester = db.query(User).filter(User.id == selection.tester_id).first()
    if not tester:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected tester not found"
        )

    # Verify tester has the selected role
    has_role = db.query(OrgUserRole).filter(
        OrgUserRole.user_id == selection.tester_id,
        OrgUserRole.org_role_id == selection.tester_role_id,
        OrgUserRole.is_active == True
    ).first()

    if not has_role:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Selected user does not have the specified tester role"
        )

    # Execute approval and assignment
    workflow_service = TestingRequestWorkflowService(db)

    success, message = workflow_service.approve_and_assign_tester(
        testing_request=testing_request,
        user=current_user,
        tester_id=selection.tester_id,
        tester_role_id=selection.tester_role_id,
        comment=selection.comment
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=message
        )

    return ApprovalResponse(
        success=True,
        message=message,
        testing_request_id=str(testing_request.id),
        assigned_tester_id=str(testing_request.assigned_tester_id),
        assigned_tester_email=tester.email,
        new_status=testing_request.status
    )


@router.post("/{request_id}/reject", response_model=ApprovalResponse)
def reject_testing_request(
    request_id: UUID,
    rejection_comment: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reject a testing request during approval stage.
    Requires a rejection comment.
    """
    # Get the testing request
    testing_request = db.query(TestingRequest).filter(
        TestingRequest.id == request_id
    ).first()

    if not testing_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testing request not found"
        )

    # Validate state
    if testing_request.status != 'pending_approval':
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request must be in 'pending_approval' state"
        )

    if not rejection_comment or len(rejection_comment.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rejection comment is required"
        )

    # Execute rejection
    workflow_service = TestingRequestWorkflowService(db)

    success, message = workflow_service.reject_testing_request(
        testing_request=testing_request,
        user=current_user,
        comment=rejection_comment
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=message
        )

    return ApprovalResponse(
        success=True,
        message=message,
        testing_request_id=str(testing_request.id),
        assigned_tester_id=None,
        assigned_tester_email=None,
        new_status=testing_request.status
    )
