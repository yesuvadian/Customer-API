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
from models import RequestCategory, User, TestingRequest, OrgRole, OrgUserRole, OrgRolePermission, TestingRequestStatus, TesterRoleModuleRequirement
from schemas import (
    TestingRequestOut,
    ApproverTesterSelection,
    BatchApproverTesterSelection,
    BatchApprovalResponse,
    BatchApprovalResult,
    RejectionRequest,
    ApprovalResponse,
    TesterInfo
)
from auth_utils import get_current_user
from services.testing_request_workflow_service import TestingRequestWorkflowService
from services.testing_request_pdf_service import TestingRequestPDFService
from sqlalchemy import text as sa_text

router = APIRouter(prefix="/testing-requests/approvals", tags=["Testing Request Approvals"])


def _get_dept_subtree_ids(db: Session, dept_id) -> list:
    """Return dept_id + all active descendant department IDs (recursive CTE)."""
    sql = sa_text("""
        WITH RECURSIVE dept_tree AS (
            SELECT id FROM org_departments
            WHERE id = :root_id AND is_active = true
            UNION ALL
            SELECT d.id FROM org_departments d
            INNER JOIN dept_tree dt ON d.parent_department_id = dt.id
            WHERE d.is_active = true
        )
        SELECT id FROM dept_tree
    """)
    rows = db.execute(sql, {"root_id": str(dept_id)}).fetchall()
    return [r[0] for r in rows]


def _caller_dept_ids(db: Session, user) -> list:
    """
    Return the department subtree IDs visible to this user.

    Strategy: use the department_id from the caller's OrgUserRole assignments
    (role scoped at a specific department). Falls back to user.department_id.
    All matching departments and their descendants are included so that a
    manager at dept X can see all requests / testers under X.
    """
    from models import OrgUserRole as _OUR
    dept_ids_raw = (
        db.query(_OUR.department_id)
        .filter(
            _OUR.user_id == user.id,
            _OUR.is_active.is_(True),
            _OUR.department_id.isnot(None),
        )
        .distinct()
        .all()
    )
    root_ids = [r[0] for r in dept_ids_raw]
    if not root_ids and user.department_id:
        root_ids = [user.department_id]
    if not root_ids:
        return []
    # Expand each root to its full subtree
    result = []
    seen = set()
    for root in root_ids:
        for did in _get_dept_subtree_ids(db, root):
            if did not in seen:
                seen.add(did)
                result.append(did)
    return result


def _enrich(req):
    """Attach computed display names to ORM object for approval workflow."""
    req.equipment_type_name = req.equipment_type.name if req.equipment_type else None
    req.test_type_name = req.test_type.name if req.test_type else None
    req.department_name = req.department.name if req.department else None

    # Equipment asset register — prefer UEIC, fall back to equipment type name
    if req.equipment:
        req.equipment_ueic = req.equipment.ueic
        req.equipment_name = req.equipment.ueic
    else:
        req.equipment_ueic = None
        req.equipment_name = req.equipment_type.name if req.equipment_type else None

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
    category: Optional[str] = None,
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
        TestingRequest.status == TestingRequestStatus.submitted,
        TestingRequest.request_category != RequestCategory.repair_lifecycle,
        TestingRequest.wf_instance_id.is_(None),  # already on new tr_wf queue if set
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

    # Filter by request category
    if category:
        query = query.filter(TestingRequest.request_category == category)

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
    wf_stage_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get all tester roles available for the testing request's organization.
    Returns ONLY roles that have FULL permissions on EXACTLY the configured modules.

    When wf_stage_id is provided (new configurable workflow path), the module
    requirement lookup prefers a stage-scoped TesterRoleModuleRequirement row
    (wf_stage_id match) before falling back to the org/global default.

    Logic:
    1. Get module requirement configuration (stage-scoped > org-specific > global default)
    2. For each role in organization, check if it has FULL permissions on those modules
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

    # Stage-scoped lookup for tr_wf_* path
    if wf_stage_id:
        config = db.query(TesterRoleModuleRequirement).filter(
            TesterRoleModuleRequirement.is_active == True,
            TesterRoleModuleRequirement.wf_stage_id == wf_stage_id,
        ).first()
        if config:
            # Use stage-scoped config directly
            pass
        else:
            # Fall through to org/global default below
            wf_stage_id = None

    if not wf_stage_id:
        # Get tester role module requirements configuration
        # Priority: org-specific config > global default
        config = db.query(TesterRoleModuleRequirement).filter(
            TesterRoleModuleRequirement.is_active == True,
            TesterRoleModuleRequirement.wf_stage_id.is_(None),
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

    # If the workflow instance has a resolved tester role, restrict to that role only
    resolved_tester_role_id = None
    if testing_request.wf_instance_id:
        from models import TrWfInstance as TrWfInstanceModel
        wf_inst = db.query(TrWfInstanceModel).filter(
            TrWfInstanceModel.id == testing_request.wf_instance_id
        ).first()
        if wf_inst:
            resolved_tester_role_id = wf_inst.resolved_tester_role_id

    # Get active roles in organization — scoped to resolved tester role if set
    roles_q = db.query(OrgRole).filter(
        OrgRole.organization_id == testing_request.organization_id,
        OrgRole.is_active == True
    )
    if resolved_tester_role_id:
        roles_q = roles_q.filter(OrgRole.id == resolved_tester_role_id)
    all_roles = roles_q.all()

    # Filter roles: must have FULL permissions on AT LEAST the required modules
    # (having additional permissions is acceptable — a role is eligible if it covers
    #  the required modules, even if it also covers other modules)
    eligible_roles = []

    for role in all_roles:
        # Get ALL permissions for this role
        permissions = db.query(OrgRolePermission).filter(
            OrgRolePermission.org_role_id == role.id
        ).all()

        # Find modules where role has FULL permissions (view, add, edit required for testers)
        full_permission_modules = set()
        for perm in permissions:
            if (perm.can_view and
                perm.can_add and
                perm.can_edit):
                full_permission_modules.add(perm.module_id)

        # Check that role has AT LEAST the required modules (subset check)
        if required_modules.issubset(full_permission_modules):
            eligible_roles.append(role)
            print(f"[DEBUG] Role '{role.name}' eligible (has modules: {full_permission_modules})")
        else:
            print(f"[DEBUG] Role '{role.name}' excluded (missing required: {required_modules - full_permission_modules})")

    print(f"[DEBUG] {len(eligible_roles)} eligible tester roles found")

    # Department subtree for caller — user counts are dept-scoped too
    caller_depts = _caller_dept_ids(db, current_user)

    # Build response with user counts
    result = []
    for role in eligible_roles:
        uq = db.query(OrgUserRole).filter(
            OrgUserRole.org_role_id == role.id,
            OrgUserRole.is_active == True,
        )
        if caller_depts:
            uq = uq.filter(OrgUserRole.department_id.in_(caller_depts))
        user_count = uq.count()

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

    # Scope tester pool to caller's department subtree
    caller_depts = _caller_dept_ids(db, current_user)

    users_q = db.query(User).join(
        OrgUserRole, OrgUserRole.user_id == User.id
    ).filter(
        OrgUserRole.org_role_id == role_id,
        OrgUserRole.is_active == True,
        User.isactive == True,
    )
    if caller_depts:
        users_q = users_q.filter(OrgUserRole.department_id.in_(caller_depts))
    users = users_q.all()

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


@router.post("/{request_id}/initial-approve", response_model=ApprovalResponse)
def initial_approve_fr(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    FR Pass 1 — Test Assigner reviews and forwards a Failure Registry ticket to
    the Technical Approver queue.

    Side effects:
    • FR status → under_approval
    • The linked Recommendation (approval_status=pending) becomes visible in
      GET /approvals/pending for the Technical Approver.

    The Technical Approver then approves via PUT /approvals/{rec_id}/approve,
    which triggers WorkflowDispatchService to create the TestRequestSchedule /
    RepairWorkflow / ProcurementRequest.
    """
    from models import RequestCategory, TestingRequestStatus

    fr = db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
    if not fr:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Testing request not found")

    if fr.request_category != RequestCategory.failure_registry:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="initial-approve is only valid for failure_registry tickets"
        )

    if fr.status != TestingRequestStatus.submitted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"FR must be in 'submitted' state, currently: {fr.status.value}"
        )

    fr.status = TestingRequestStatus.under_approval
    fr.modified_by = current_user.id
    db.commit()

    print(f"[FR initial-approve] FR {fr.request_number} → under_approval (by {current_user.id})")

    return ApprovalResponse(
        success=True,
        message="FR forwarded to Technical Approver queue.",
        testing_request_id=str(fr.id),
        assigned_tester_id=None,
        assigned_tester_email=None,
        new_status=fr.status,
        child_tr_id=None,
        child_tr_number=None,
    )


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
    if testing_request.request_category == RequestCategory.repair_lifecycle:
        raise HTTPException(
            status_code=400,
            detail="Only test requests can enter approval workflow"
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


@router.post("/batch-approve-and-assign", response_model=BatchApprovalResponse)
def batch_approve_and_assign(
    selection: BatchApproverTesterSelection,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Approve multiple testing requests and assign them all to the same tester.

    The approver selects a tester role + user once, and every request in
    request_ids is approved and assigned to that user in a single call.
    Requests that are already past the approvable state are skipped (not
    counted as failures) so the caller receives a clear per-item breakdown.
    """
    # Validate tester exists and has the role
    tester = db.query(User).filter(User.id == selection.tester_id).first()
    if not tester:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Selected tester not found")

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

    workflow_service = TestingRequestWorkflowService(db)
    results: list[BatchApprovalResult] = []

    for req_id in selection.request_ids:
        testing_request = db.query(TestingRequest).filter(
            TestingRequest.id == req_id
        ).first()

        if not testing_request:
            results.append(BatchApprovalResult(
                request_id=str(req_id),
                success=False,
                message="Request not found"
            ))
            continue

        if testing_request.request_category == RequestCategory.repair_lifecycle:
            results.append(BatchApprovalResult(
                request_id=str(req_id),
                request_number=testing_request.request_number,
                success=False,
                message="Repair lifecycle requests cannot be batch-approved"
            ))
            continue

        if testing_request.status not in [
            TestingRequestStatus.pending_approval,
            TestingRequestStatus.submitted,
        ]:
            results.append(BatchApprovalResult(
                request_id=str(req_id),
                request_number=testing_request.request_number,
                success=False,
                message=f"Cannot approve: current status is {testing_request.status.value}"
            ))
            continue

        success, message = workflow_service.approve_and_assign_tester(
            testing_request=testing_request,
            user=current_user,
            tester_id=selection.tester_id,
            tester_role_id=selection.tester_role_id,
            comment=selection.comment
        )
        results.append(BatchApprovalResult(
            request_id=str(req_id),
            request_number=testing_request.request_number,
            success=success,
            message=message
        ))

    succeeded = sum(1 for r in results if r.success)
    return BatchApprovalResponse(
        total=len(results),
        succeeded=succeeded,
        failed=len(results) - succeeded,
        results=results
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
    import traceback

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
        print(f"[DEBUG] Generating PDF for request_id: {request_id}")
        pdf_buffer = pdf_service.generate_pdf(str(request_id))
        print(f"[DEBUG] PDF generated successfully")
    except Exception as e:
        print(f"[ERROR] PDF generation failed: {str(e)}")
        print(f"[ERROR] Traceback: {traceback.format_exc()}")
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


# =============================================================================
# TR_WF_* Configurable Workflow Endpoints (new parallel engine)
# =============================================================================

@router.get("/tr-wf/debug/{request_id}")
def tr_wf_debug(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Debug: return WF instance state for a testing request."""
    from models import TrWfInstance, TrWfStage, TrWfStageInstance
    req = db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if not getattr(req, "wf_instance_id", None):
        return {"wf_instance_id": None, "msg": "No WF instance on this request"}

    inst = db.query(TrWfInstance).filter(TrWfInstance.id == req.wf_instance_id).first()
    if not inst:
        return {"wf_instance_id": str(req.wf_instance_id), "msg": "Instance row missing"}

    stage = db.query(TrWfStage).filter(TrWfStage.id == inst.current_stage_id).first() if inst.current_stage_id else None
    stage_insts = db.query(TrWfStageInstance).filter(
        TrWfStageInstance.wf_instance_id == inst.id
    ).order_by(TrWfStageInstance.created_at.desc()).all()

    return {
        "request_id": str(req.id),
        "wf_instance_id": str(inst.id),
        "instance_status": inst.status,
        "current_stage_id": str(inst.current_stage_id) if inst.current_stage_id else None,
        "current_stage_code": stage.code if stage else None,
        "current_stage_name": stage.name if stage else None,
        "current_status_code": inst.current_status_code,
        "request_department_id": str(req.department_id) if req.department_id else None,
        "stage_instances": [
            {
                "stage_id": str(si.stage_id) if si.stage_id else None,
                "status": si.status,
                "action_taken": si.action_taken,
                "created_at": si.created_at.isoformat() if si.created_at else None,
            }
            for si in stage_insts
        ],
    }


@router.get("/tr-wf/pending", response_model=List[dict])
def tr_wf_get_pending_queue(
    organization_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Stage-aware approval queue for the new configurable workflow engine.

    Returns testing requests whose active workflow stage includes one of
    the caller's org roles (can_approve or can_assign).
    Each item includes available_actions[] for UI button rendering.
    """
    from models import (
        TrWfInstance, TrWfStageRole, TrWfStage, OrgUserRole as OURModel
    )
    from services.tr_workflow_routing_service import WorkflowRoutingService
    from sqlalchemy.orm import joinedload

    org_id = current_user.organization_id or organization_id
    if not org_id:
        raise HTTPException(status_code=400, detail="organization_id required")

    # Caller's active role IDs
    caller_role_ids = [
        r.org_role_id for r in db.query(OURModel).filter(
            OURModel.user_id == current_user.id,
            OURModel.is_active.is_(True),
        ).all()
    ]
    if not caller_role_ids:
        return []

    # Stage IDs where caller has a role
    allowed_stage_ids = [
        sr.stage_id for sr in db.query(TrWfStageRole).filter(
            TrWfStageRole.role_id.in_(caller_role_ids),
        ).all()
    ]
    if not allowed_stage_ids:
        return []

    # Department subtree for this caller — scope to caller's dept + descendants
    caller_dept_ids = _caller_dept_ids(db, current_user)

    # Active instances at those stages in this org
    instances_q = (
        db.query(TrWfInstance)
        .join(TestingRequest, TestingRequest.id == TrWfInstance.testing_request_id)
        .filter(
            TrWfInstance.org_id == org_id,
            TrWfInstance.status == "active",
            TrWfInstance.current_stage_id.in_(allowed_stage_ids),
        )
    )
    if caller_dept_ids:
        instances_q = instances_q.filter(
            TestingRequest.department_id.in_(caller_dept_ids)
        )
    instances = instances_q.all()

    # Filter by resolved_l3_role_id at both l3_assign_tester and l3_review_result stages
    from models import TrWfStage as TrWfStageModel
    role_scoped_stage_codes = {"l3_assign_tester", "l3_review_result"}

    def _caller_sees_instance(inst: TrWfInstance) -> bool:
        if not inst.resolved_l3_role_id:
            return True  # no role restriction — all eligible roles see it
        current_stage = db.query(TrWfStageModel).filter(
            TrWfStageModel.id == inst.current_stage_id
        ).first()
        if not current_stage or current_stage.code not in role_scoped_stage_codes:
            return True  # role filter only applies at role-scoped stages
        # Caller must have the resolved AEE role for this stream
        return inst.resolved_l3_role_id in caller_role_ids

    instances = [inst for inst in instances if _caller_sees_instance(inst)]

    routing_svc = WorkflowRoutingService(db)
    result = []
    for inst in instances:
        req = (
            db.query(TestingRequest)
            .options(
                joinedload(TestingRequest.equipment_type),
                joinedload(TestingRequest.test_type),
                joinedload(TestingRequest.department),
                joinedload(TestingRequest.originator),
                joinedload(TestingRequest.equipment),
            )
            .filter(TestingRequest.id == inst.testing_request_id)
            .first()
        )
        if not req:
            continue

        actions = routing_svc.get_available_actions(req, caller_role_ids)

        eq = req.equipment
        result.append({
            "request_id": str(req.id),
            "request_number": req.request_number,
            "title": req.title,
            "description": req.description,
            "notes": req.notes,
            "priority": req.priority,
            "equipment_type": req.equipment_type.name if req.equipment_type else None,
            "equipment_ueic": eq.ueic if eq else None,
            "bay_number": eq.bay_number if eq else None,
            "equipment_voltage_class": eq.voltage_class if eq else None,
            "equipment_manufacturer": eq.manufacturer if eq else None,
            "equipment_serial": eq.factory_serial_number if eq else None,
            "equipment_year_of_manufacture": eq.year_of_manufacture if eq else None,
            "equipment_vector_group": eq.vector_group if eq else None,
            "equipment_rated_mva": (eq.nameplate_data or {}).get("rated_mva") if eq else None,
            "test_type": req.test_type.name if req.test_type else None,
            "test_type_id": req.test_type_id,
            "equipment_id": str(req.equipment_id) if req.equipment_id else None,
            "equipment_type_id": req.equipment_type_id,
            "department": req.department.name if req.department else None,
            "department_id": str(req.department_id) if req.department_id else None,
            "originator": (
                f"{req.originator.firstname or ''} {req.originator.lastname or ''}".strip()
                or req.originator.email
            ) if req.originator else None,
            "current_status_code": inst.current_status_code,
            "current_stage_id": str(inst.current_stage_id) if inst.current_stage_id else None,
            "stage_code": (
                db.query(TrWfStage).filter(TrWfStage.id == inst.current_stage_id).first().code
                if inst.current_stage_id else None
            ),
            "wf_instance_id": str(inst.id),
            "resolved_tester_role_id": str(inst.resolved_tester_role_id) if inst.resolved_tester_role_id else None,
            "resolved_tester_role_name": inst.resolved_tester_role.name if inst.resolved_tester_role else None,
            "request_type": req.request_type,
            "cts": req.cts.isoformat() if req.cts else None,
            "due_date": req.due_date.isoformat() if req.due_date else None,
            "scheduled_start_date": req.scheduled_start_date.isoformat() if req.scheduled_start_date else None,
            "available_actions": actions,
        })

    return result


@router.post("/{request_id}/tr-wf/l2-approve-route", response_model=ApprovalResponse)
def tr_wf_l2_approve_route(
    request_id: UUID,
    comment: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    L2 (EE_TLSS) approves and routes the request through the configurable
    workflow engine. No tester assignment at this stage — routing resolves
    the workflow definition and opens the first stage (L3 assigner queue).
    """
    req = db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Testing request not found")

    if req.status not in [TestingRequestStatus.pending_approval, TestingRequestStatus.submitted]:
        raise HTTPException(
            status_code=400,
            detail=f"Request must be pending_approval or submitted, currently: {req.status.value}",
        )

    svc = TestingRequestWorkflowService(db)
    success, message = svc.tr_wf_l2_approve_and_route(req, current_user, comment)
    if not success:
        raise HTTPException(status_code=422, detail=message)

    db.commit()
    return ApprovalResponse(
        success=True,
        message=message,
        testing_request_id=str(req.id),
        assigned_tester_id=None,
        assigned_tester_email=None,
        new_status=req.status,
    )


@router.post("/{request_id}/tr-wf/l3-assign", response_model=ApprovalResponse)
def tr_wf_l3_assign_tester(
    request_id: UUID,
    selection: "ApproverTesterSelection",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    L3 assigner (AEE R&T / AEE R&D) selects a Level-4 tester from their
    department's pool and advances the configurable workflow to the testing stage.
    """
    req = db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Testing request not found")
    if not req.wf_instance_id:
        raise HTTPException(status_code=422, detail="Request is not on the configurable workflow path")

    svc = TestingRequestWorkflowService(db)
    success, message = svc.tr_wf_l3_assign_tester(
        req, current_user,
        tester_id=selection.tester_id,
        tester_role_id=selection.tester_role_id,
        comment=selection.comment,
    )
    if not success:
        raise HTTPException(status_code=422, detail=message)

    db.commit()
    tester = db.query(User).filter(User.id == selection.tester_id).first()
    return ApprovalResponse(
        success=True,
        message=message,
        testing_request_id=str(req.id),
        assigned_tester_id=str(selection.tester_id),
        assigned_tester_email=tester.email if tester else None,
        new_status=req.status,
    )


@router.post("/{request_id}/tr-wf/advance", response_model=ApprovalResponse)
def tr_wf_advance_stage(
    request_id: UUID,
    action_code: str,
    role_id: Optional[UUID] = None,
    comment: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generic stage advance for the configurable workflow engine.
    Used by L3 reviewer (approve/reject recommendation) and any future stage actions.
    """
    req = db.query(TestingRequest).filter(TestingRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Testing request not found")
    if not req.wf_instance_id:
        raise HTTPException(status_code=422, detail="Request is not on the configurable workflow path")

    svc = TestingRequestWorkflowService(db)
    success, message = svc.tr_wf_advance(req, current_user, action_code, role_id, comment)
    if not success:
        raise HTTPException(status_code=422, detail=message)

    db.commit()
    return ApprovalResponse(
        success=True,
        message=message,
        testing_request_id=str(req.id),
        assigned_tester_id=None,
        assigned_tester_email=None,
        new_status=req.status,
    )


@router.get("/{request_id}/tr-wf/audit-log", response_model=List[dict])
def tr_wf_get_audit_log(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the full audit trail for the request's configurable workflow instance."""
    from models import TrWfAuditLog, TrWfStage, User as UserModel
    from sqlalchemy.orm import joinedload

    logs = (
        db.query(TrWfAuditLog)
        .filter(TrWfAuditLog.testing_request_id == request_id)
        .order_by(TrWfAuditLog.created_at)
        .all()
    )

    def _stage_name(stage_id):
        if not stage_id:
            return None
        s = db.query(TrWfStage).filter(TrWfStage.id == stage_id).first()
        return s.name if s else None

    def _user_name(user_id):
        if not user_id:
            return None
        u = db.query(UserModel).filter(UserModel.id == user_id).first()
        if not u:
            return None
        return f"{u.firstname or ''} {u.lastname or ''}".strip() or u.email

    return [
        {
            "id": str(log.id),
            "from_stage": _stage_name(log.from_stage_id),
            "to_stage": _stage_name(log.to_stage_id),
            "action_code": log.action_code,
            "performed_by": _user_name(log.performed_by),
            "from_status_code": log.from_status_code,
            "to_status_code": log.to_status_code,
            "comment": log.comment,
            "is_send_back": log.is_send_back,
            "is_terminal": log.is_terminal,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]
