"""
Testing Request Approval Endpoints
Handles approval workflow with tester role selection and assignment
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
from uuid import UUID

from database import get_db
from models import User, TestingRequest, OrgRole, OrgUserRole, OrgRolePermission, TestingRequestStatus, TesterRoleModuleRequirement
from schemas import (
    TestingRequestOut,
    ApproverTesterSelection,
    RejectionRequest,
    ApprovalResponse,
    TesterInfo
)
from auth_utils import get_current_user
from services.testing_request_workflow_service import TestingRequestWorkflowService
from services.testing_request_pdf_service import TestingRequestPDFService

router = APIRouter(prefix="/testing-requests/approvals", tags=["Testing Request Approvals"])


def _enrich(req):
    """Attach computed display names to ORM object for approval workflow."""
    req.equipment_type_name = req.equipment_type.name if req.equipment_type else None
    req.equipment_name = req.equipment_type.name if req.equipment_type else None  # Alias for Flutter
    req.test_type_name = req.test_type.name if req.test_type else None
    req.department_name = req.department.name if req.department else None
    if req.originator:
        req.originator_name = f"{req.originator.firstname or ''} {req.originator.lastname or ''}".strip() or req.originator.email
        req.requester_email = req.originator.email  # For Flutter UI
    else:
        req.originator_name = None
        req.requester_email = None
    if req.assigned_tester:
        req.assigned_tester_name = f"{req.assigned_tester.firstname or ''} {req.assigned_tester.lastname or ''}".strip() or req.assigned_tester.email
    else:
        req.assigned_tester_name = None
    return req


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
    query = db.query(TestingRequest).options(
        joinedload(TestingRequest.equipment_type),
        joinedload(TestingRequest.test_type),
        joinedload(TestingRequest.department),
        joinedload(TestingRequest.originator),
        joinedload(TestingRequest.assigned_tester),
        joinedload(TestingRequest.organization),
    ).filter(
        TestingRequest.status == TestingRequestStatus.submitted  # Using submitted for testing (pending_approval requires migration)
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
    print(f"[DEBUG] Found {len(requests)} pending approvals")

    # Enrich requests with display names for UI
    enriched_requests = [_enrich(req) for req in requests]

    for req in enriched_requests:
        print(f"[DEBUG] Request: {req.id}, Status: {req.status}, Equipment: {req.equipment_name}, Dept: {req.department_name}")

    return enriched_requests


@router.get("/{request_id}/tester-roles", response_model=List[dict])
def get_available_tester_roles(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all tester roles available for the testing request's organization.
    Returns ONLY roles that have FULL permissions on EXACTLY the configured modules.

    Logic:
    1. Get module requirement configuration (org-specific or global default)
    2. For each role in organization, check if it has FULL permissions on EXACTLY those modules
    3. Return only matching roles with user counts
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

    # Get tester role module requirements configuration
    # Priority: org-specific config > global default
    config = db.query(TesterRoleModuleRequirement).filter(
        TesterRoleModuleRequirement.is_active == True,
        or_(
            TesterRoleModuleRequirement.organization_id == testing_request.organization_id,
            TesterRoleModuleRequirement.organization_id.is_(None)  # Global default
        )
    ).order_by(
        # Org-specific first (NULL last)
        TesterRoleModuleRequirement.organization_id.desc().nullslast()
    ).first()

    if not config:
        return []

    required_modules = set(config.required_module_ids)

    # Get all active roles in organization
    all_roles = db.query(OrgRole).filter(
        OrgRole.organization_id == testing_request.organization_id,
        OrgRole.is_active == True
    ).all()

    # Filter roles: must have FULL permissions on EXACTLY the required modules
    eligible_roles = []

    for role in all_roles:
        # Get ALL permissions for this role
        permissions = db.query(OrgRolePermission).filter(
            OrgRolePermission.org_role_id == role.id
        ).all()

        # Find modules where role has FULL permissions (all 6 flags TRUE)
        full_permission_modules = set()
        for perm in permissions:
            if (perm.can_view and
                perm.can_add and
                perm.can_edit and
                perm.can_delete and
                perm.can_approve and
                perm.can_assign):
                full_permission_modules.add(perm.module_id)

        # Check for EXACT match
        if full_permission_modules == required_modules:
            eligible_roles.append(role)
            print(f"[DEBUG] Role '{role.name}' matches (modules: {full_permission_modules})")
        else:
            print(f"[DEBUG] Role '{role.name}' excluded (has modules: {full_permission_modules})")

    print(f"[DEBUG] {len(eligible_roles)} eligible tester roles found")

    # Build response with user counts
    result = []
    for role in eligible_roles:
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
    # Using submitted for testing (pending_approval requires migration)
    if testing_request.status not in [TestingRequestStatus.pending_approval, TestingRequestStatus.submitted]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request must be in 'pending_approval' or 'submitted' state, currently: {testing_request.status}"
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
    rejection: RejectionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reject a testing request during approval stage.
    Requires a rejection comment in the request body.
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
    # Using submitted for testing (pending_approval requires migration)
    if testing_request.status not in [TestingRequestStatus.pending_approval, TestingRequestStatus.submitted]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Request must be in 'pending_approval' or 'submitted' state"
        )

    if not rejection.rejection_comment or len(rejection.rejection_comment.strip()) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rejection comment is required"
        )

    # Execute rejection
    workflow_service = TestingRequestWorkflowService(db)

    success, message = workflow_service.reject_testing_request(
        testing_request=testing_request,
        user=current_user,
        comment=rejection.rejection_comment
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


@router.get("/{request_id}/pdf")
def download_testing_request_pdf(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Download testing request form as PDF.
    Provides a printable version of the testing request for approval review.
    """
    # Verify request exists
    testing_request = db.query(TestingRequest).filter(
        TestingRequest.id == request_id
    ).first()

    if not testing_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testing request not found"
        )

    # Generate PDF
    pdf_service = TestingRequestPDFService(db)
    try:
        pdf_buffer = pdf_service.generate_pdf(str(request_id))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF: {str(e)}"
        )

    # Return as downloadable file
    filename = f"testing_request_{testing_request.request_number or request_id}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
