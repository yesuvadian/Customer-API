"""
Tester Assignment API Router

Provides endpoints for:
- Manual tester assignment
- Auto-assignment configuration
- Tester workload statistics
- Reassignment
"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel

from database import get_db
from models import TestingRequest, User, TestingRequestStatus
from services.tester_auto_assignment_service import TesterAutoAssignmentService
from services.testing_request_workflow_service import TestingRequestWorkflowService
from auth_utils import get_current_user

router = APIRouter(prefix="/tester-assignment", tags=["Tester Assignment"])


# ========================================
# SCHEMAS
# ========================================

class AssignTesterRequest(BaseModel):
    """Request to manually assign a tester"""
    testing_request_id: UUID
    tester_id: UUID
    comment: Optional[str] = None


class AutoAssignRequest(BaseModel):
    """Request to auto-assign a tester"""
    testing_request_id: UUID
    strategy: str = 'least_loaded'  # 'least_loaded', 'round_robin', 'random', 'priority'
    comment: Optional[str] = None


class ReassignRequest(BaseModel):
    """Request to reassign a testing request"""
    testing_request_id: UUID
    new_tester_id: Optional[UUID] = None  # If None, auto-assign
    strategy: str = 'least_loaded'
    comment: Optional[str] = None


class TesterWorkloadResponse(BaseModel):
    """Response with tester workload statistics"""
    user_id: str
    name: str
    email: str
    department_name: str
    assigned_count: int
    accepted_count: int
    in_progress_count: int
    total_active: int


class AvailabilityResponse(BaseModel):
    """Response for tester availability check"""
    is_available: bool
    reason: str
    active_requests: Optional[int] = None


# ========================================
# MANUAL ASSIGNMENT
# ========================================

@router.post("/assign")
def assign_tester_manually(
    request: AssignTesterRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Manually assign a tester to a testing request.

    Requires 'assign_tester' permission via workflow.
    """
    # Get testing request
    testing_request = db.query(TestingRequest).filter(
        TestingRequest.id == request.testing_request_id
    ).first()

    if not testing_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testing request not found"
        )

    # Verify request is in 'submitted' state
    if testing_request.status != TestingRequestStatus.submitted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot assign tester. Request status is '{testing_request.status.value}', must be 'submitted'"
        )

    # Use workflow service to assign
    workflow_service = TestingRequestWorkflowService(db)
    success, message = workflow_service.assign_tester(
        testing_request=testing_request,
        user=current_user,
        tester_id=request.tester_id,
        comment=request.comment
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=message
        )

    return {
        "success": True,
        "message": message,
        "testing_request_id": str(testing_request.id),
        "assigned_tester_id": str(request.tester_id),
        "status": testing_request.status.value
    }


# ========================================
# AUTO-ASSIGNMENT
# ========================================

@router.post("/auto-assign")
def auto_assign_tester(
    request: AutoAssignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Automatically assign a tester using the specified strategy.

    Strategies:
    - least_loaded: Assign to tester with fewest active requests
    - round_robin: Assign to tester who was assigned longest ago
    - random: Randomly assign from eligible testers
    - priority: Score-based assignment considering workload and proximity
    """
    # Get testing request
    testing_request = db.query(TestingRequest).filter(
        TestingRequest.id == request.testing_request_id
    ).first()

    if not testing_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testing request not found"
        )

    # Verify request is in 'submitted' state
    if testing_request.status != TestingRequestStatus.submitted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot assign tester. Request status is '{testing_request.status.value}', must be 'submitted'"
        )

    # Auto-assign
    auto_service = TesterAutoAssignmentService(db)
    success, tester_id, assign_message = auto_service.auto_assign_tester(
        testing_request=testing_request,
        strategy=request.strategy
    )

    if not success or not tester_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=assign_message
        )

    # Use workflow service to perform the assignment transition
    workflow_service = TestingRequestWorkflowService(db)
    transition_success, transition_message = workflow_service.assign_tester(
        testing_request=testing_request,
        user=current_user,
        tester_id=tester_id,
        comment=request.comment or f"Auto-assigned using {request.strategy} strategy: {assign_message}"
    )

    if not transition_success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=transition_message
        )

    return {
        "success": True,
        "message": assign_message,
        "testing_request_id": str(testing_request.id),
        "assigned_tester_id": str(tester_id),
        "strategy": request.strategy,
        "status": testing_request.status.value
    }


# ========================================
# REASSIGNMENT
# ========================================

@router.post("/reassign")
def reassign_tester(
    request: ReassignRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Reassign a testing request to a different tester.

    Can specify a new tester or use auto-assignment.
    """
    # Get testing request
    testing_request = db.query(TestingRequest).filter(
        TestingRequest.id == request.testing_request_id
    ).first()

    if not testing_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testing request not found"
        )

    # Store old tester
    old_tester_id = testing_request.assigned_tester_id

    auto_service = TesterAutoAssignmentService(db)

    if request.new_tester_id:
        # Manual reassignment
        new_tester_id = request.new_tester_id
        message = "Manually reassigned to new tester"
    else:
        # Auto reassignment
        success, new_tester_id, message = auto_service.reassign_tester(
            testing_request=testing_request,
            strategy=request.strategy
        )
        if not success or not new_tester_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=message
            )

    # Update assignment
    testing_request.assigned_tester_id = new_tester_id
    db.commit()

    return {
        "success": True,
        "message": message,
        "testing_request_id": str(testing_request.id),
        "old_tester_id": str(old_tester_id) if old_tester_id else None,
        "new_tester_id": str(new_tester_id),
        "status": testing_request.status.value
    }


# ========================================
# WORKLOAD STATISTICS
# ========================================

@router.get("/workload-stats", response_model=List[TesterWorkloadResponse])
def get_tester_workload_stats(
    organization_id: UUID,
    department_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get workload statistics for all testers in an organization/department.

    Shows current active requests for each tester.
    """
    auto_service = TesterAutoAssignmentService(db)
    stats = auto_service.get_tester_workload_stats(
        organization_id=organization_id,
        department_id=department_id
    )

    return stats


@router.get("/availability/{tester_id}", response_model=AvailabilityResponse)
def check_tester_availability(
    tester_id: UUID,
    max_concurrent: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Check if a tester is available for new assignments.

    Considers:
    - User active status
    - Current workload vs max concurrent requests
    """
    auto_service = TesterAutoAssignmentService(db)
    is_available, reason = auto_service.is_tester_available(
        tester_id=tester_id,
        max_concurrent=max_concurrent
    )

    # Get active request count
    active_count = None
    if not is_available:
        from sqlalchemy import func, and_
        active_count = db.query(func.count(TestingRequest.id)).filter(
            and_(
                TestingRequest.assigned_tester_id == tester_id,
                TestingRequest.status.in_([
                    TestingRequestStatus.assigned,
                    TestingRequestStatus.accepted,
                    TestingRequestStatus.in_progress
                ])
            )
        ).scalar() or 0

    return {
        "is_available": is_available,
        "reason": reason,
        "active_requests": active_count
    }


# ========================================
# ELIGIBLE TESTERS
# ========================================

@router.get("/eligible-testers/{testing_request_id}")
def get_eligible_testers(
    testing_request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get list of eligible testers for a testing request.

    Returns testers who:
    - Have tester role
    - Are in same organization
    - Are in appropriate department (same or parent)
    - Are active
    """
    # Get testing request
    testing_request = db.query(TestingRequest).filter(
        TestingRequest.id == testing_request_id
    ).first()

    if not testing_request:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Testing request not found"
        )

    auto_service = TesterAutoAssignmentService(db)
    eligible = auto_service._find_eligible_testers(testing_request)

    return {
        "testing_request_id": str(testing_request_id),
        "eligible_testers": eligible,
        "count": len(eligible)
    }
