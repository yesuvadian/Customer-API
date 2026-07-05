from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import Recommendation, User
from schemas import ApprovalAction, RecommendationResponse
from services.approval_service import ApprovalService
from services.report_service import ReportService
from sqlalchemy import text as sa_text


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
    """Collect dept subtree IDs visible to caller based on their OrgUserRole department assignments."""
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
    result = []
    seen = set()
    for root in root_ids:
        for did in _get_dept_subtree_ids(db, root):
            if did not in seen:
                seen.add(did)
                result.append(did)
    return result

router = APIRouter(
    prefix="/approvals",
    tags=["approvals"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/stats")
def get_approval_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return approval counts: pending, approved, rejected, total_reviewed."""
    service = ApprovalService(db)
    return service.get_approval_stats(approver_id=current_user.id)


@router.get("/pending")
def get_pending_approvals(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ApprovalService(db)
    return service.get_pending_approvals(skip=skip, limit=limit)


@router.get("/{recommendation_id}/detail")
def get_approval_detail(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns recommendation + testing request info + test results for approver review."""
    service = ApprovalService(db)
    return service.get_approval_detail(recommendation_id)


@router.get("/{recommendation_id}/report")
def get_approval_report(
    recommendation_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate and return a PDF test report for approval review."""
    service = ReportService(db)
    pdf_bytes = service.generate_approval_report(recommendation_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="test_report_{recommendation_id}.pdf"',
        },
    )


@router.get("/by-request/{testing_request_id}")
def get_recommendation_by_request(
    testing_request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns the recommendation (with replacement_products) for a given testing request."""
    rec = (
        db.query(Recommendation)
        .filter(Recommendation.testing_request_id == testing_request_id)
        .order_by(Recommendation.cts.desc())
        .first()
    )
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No recommendation found for this testing request",
        )
    service = ApprovalService(db)
    return service.get_approval_detail(rec.id)


@router.put("/{recommendation_id}/approve")
def approve_recommendation(
    recommendation_id: UUID,
    data: ApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Approve a recommendation.

    For Failure Registry (FR-) records the response includes extra fields:
      fr_outcome            — "repair" | "replacement" | "under_investigation" | …
      fr_number             — the FR- request number
      fr_equipment_ueic     — UEIC of the failed equipment
      fr_failure_category   — e.g. "Electrical"
      fr_failure_date       — ISO date string from test_data
      auto_created_repair_tr — RL- request number if a repair TR was auto-created
    """
    service = ApprovalService(db)
    return service.approve_recommendation(
        recommendation_id=recommendation_id,
        approver_id=current_user.id,
        notes=data.notes,
        schedule_start_date=data.schedule_start_date,
        schedule_end_date=data.schedule_end_date,
        schedule_frequency=data.schedule_frequency,
    )


@router.get("/tr-wf/pending")
def tr_wf_get_pending_result_reviews(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    L3 reviewer result-review queue for the configurable workflow engine.

    Returns pending recommendations whose linked testing request has an active
    tr_wf_* instance AND the caller's role is assigned as can_approve on the
    current stage of that instance.

    The existing GET /approvals/pending is untouched — this is additive.
    """
    from models import TrWfInstance, TrWfStageRole, OrgUserRole, TestingRequest as TR
    from sqlalchemy.orm import joinedload

    # Caller's active role IDs
    caller_role_ids = [
        r.org_role_id for r in db.query(OrgUserRole).filter(
            OrgUserRole.user_id == current_user.id,
            OrgUserRole.is_active.is_(True),
        ).all()
    ]
    if not caller_role_ids:
        return []

    # Stage IDs where caller can_approve
    approvable_stage_ids = [
        sr.stage_id for sr in db.query(TrWfStageRole).filter(
            TrWfStageRole.role_id.in_(caller_role_ids),
            TrWfStageRole.can_approve.is_(True),
        ).all()
    ]
    if not approvable_stage_ids:
        return []

    # Department subtree for this reviewer
    caller_depts = _caller_dept_ids(db, current_user)

    # Active wf instances at those stages — scoped to caller's department subtree
    wf_q = (
        db.query(TrWfInstance)
        .join(TR, TR.id == TrWfInstance.testing_request_id)
        .filter(
            TrWfInstance.status == "active",
            TrWfInstance.current_stage_id.in_(approvable_stage_ids),
        )
    )
    if caller_depts:
        wf_q = wf_q.filter(TR.department_id.in_(caller_depts))
    tr_ids_with_wf = [i.testing_request_id for i in wf_q.all()]
    if not tr_ids_with_wf:
        return []

    # Pending recommendations for those requests
    from models import Recommendation
    recs = (
        db.query(Recommendation)
        .options(
            joinedload(Recommendation.testing_request).joinedload(TR.equipment),
            joinedload(Recommendation.testing_request).joinedload(TR.department),
            joinedload(Recommendation.testing_request).joinedload(TR.originator),
            joinedload(Recommendation.submitter),
        )
        .filter(
            Recommendation.approval_status == "pending",
            Recommendation.testing_request_id.in_(tr_ids_with_wf),
        )
        .order_by(Recommendation.cts.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    service = ApprovalService(db)

    def _name(u):
        if not u:
            return None
        return f"{u.firstname or ''} {u.lastname or ''}".strip() or u.email

    result = []
    for rec in recs:
        tr = rec.testing_request
        result.append({
            "id": str(rec.id),
            "testing_request_id": str(rec.testing_request_id),
            "recommendation_type": rec.recommendation_type.value if rec.recommendation_type else None,
            "summary": rec.summary,
            "next_action": rec.next_action.value if rec.next_action else None,
            "approval_status": rec.approval_status,
            "submitted_by_name": _name(rec.submitter),
            "submitted_at": rec.submitted_at.isoformat() if rec.submitted_at else None,
            "request_number": tr.request_number if tr else None,
            "title": tr.title if tr else None,
            "equipment_ueic": tr.equipment.ueic if (tr and tr.equipment) else None,
            "bay_number": tr.equipment.bay_number if (tr and tr.equipment) else None,
            "department_name": tr.department.name if (tr and tr.department) else None,
            "current_status_code": tr.current_status_code if tr else None,
        })
    return result


@router.put("/{recommendation_id}/reject", response_model=RecommendationResponse)
def reject_recommendation(
    recommendation_id: UUID,
    data: ApprovalAction,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ApprovalService(db)
    return service.reject_recommendation(
        recommendation_id=recommendation_id,
        approver_id=current_user.id,
        notes=data.notes,
    )
