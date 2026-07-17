"""
Document Support Workflow — REST API
=====================================
POST  /doc-support/submit          — Submit a document request (any user)
GET   /doc-support/list            — List document requests for org
GET   /doc-support/{doc_id}        — Get one document request
POST  /doc-support/{doc_id}/action — Perform workflow action (assign / process / complete / accept / reject)
GET   /doc-support/{doc_id}/actions — Available actions for current user
GET   /doc-support/{doc_id}/audit  — Audit trail
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import (
    DocumentRequest, TrWfAuditLog, TrWfInstance, OrgUserRole,
    TrWfDefinition, TrWfStatus, TrWfStageTransition, TrWfStageRole, User,
)
from services.doc_support_service import DocSupportService

router = APIRouter(prefix="/doc-support", tags=["Document Support"])


def _user_role_ids(db: Session, user) -> list[UUID]:
    rows = (
        db.query(OrgUserRole.org_role_id)
        .filter(OrgUserRole.user_id == user.id, OrgUserRole.is_active.is_(True))
        .all()
    )
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Statuses (for filter dropdowns)
# ---------------------------------------------------------------------------

@router.get("/statuses")
def list_statuses(
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """Return all TrWfStatus rows for the document_support workflow definition of this org."""
    defn = (
        db.query(TrWfDefinition)
        .filter(
            TrWfDefinition.org_id == current_user.organization_id,
            TrWfDefinition.request_type == "document_support",
        )
        .first()
    )
    if not defn:
        return []
    statuses = (
        db.query(TrWfStatus)
        .filter(TrWfStatus.wf_definition_id == defn.id)
        .order_by(TrWfStatus.sequence)
        .all()
    )
    return [
        {
            "status_code": s.status_code,
            "status_name": s.status_name,
            "color":       s.color,
            "is_terminal": s.is_terminal,
            "sequence":    s.sequence,
        }
        for s in statuses
    ]


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

@router.post("/submit", status_code=201)
def submit_document_request(
    payload: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    svc = DocSupportService(db)
    doc = svc.submit(
        org_id=current_user.organization_id,
        submitted_by=current_user.id,
        title=payload.get("title", ""),
        description=payload.get("description"),
        notes=payload.get("notes"),
        file_url=payload.get("file_url"),
        file_name=payload.get("file_name"),
        file_size=payload.get("file_size"),
        mime_type=payload.get("mime_type"),
        priority=payload.get("priority", "normal"),
        target_date=payload.get("target_date"),
    )
    db.commit()
    db.refresh(doc)
    return _doc_response(doc)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

@router.get("/list")
def list_document_requests(
    status: Optional[str] = Query(None),
    submitted_by: Optional[UUID] = Query(None),
    my_requests: bool = Query(False),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    svc = DocSupportService(db)
    submitter_filter = current_user.id if my_requests else submitted_by
    docs = svc.list_for_org(
        org_id=current_user.organization_id,
        status_filter=status,
        submitted_by=submitter_filter,
        limit=limit,
        offset=offset,
    )
    return [_doc_response(d) for d in docs]


# ---------------------------------------------------------------------------
# Get one
# ---------------------------------------------------------------------------

@router.get("/{doc_id}")
def get_document_request(
    doc_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    svc = DocSupportService(db)
    return _doc_response(svc.get_document_request(doc_id))


# ---------------------------------------------------------------------------
# Available actions
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/actions")
def get_available_actions(
    doc_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    svc = DocSupportService(db)
    role_ids = _user_role_ids(db, current_user)
    return svc.get_available_actions(doc_id, role_ids, user_id=current_user.id)


# ---------------------------------------------------------------------------
# Assignable users for a given action (action_code passed as query param)
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/assignable-users")
def get_assignable_users(
    doc_id: UUID,
    action_code: str = Query(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    Return users who can be assigned for the given action on this request.
    Resolves: current stage -> transition matching action_code -> next stage
    -> roles on that stage -> users who hold those roles in the same org.
    """
    doc = db.query(DocumentRequest).filter(DocumentRequest.id == doc_id).first()
    if not doc or not doc.wf_instance_id:
        print(f"[assignable-users] doc not found or no wf_instance_id: doc={doc}")
        return []

    instance = db.query(TrWfInstance).filter(TrWfInstance.id == doc.wf_instance_id).first()
    if not instance or not instance.current_stage_id:
        print(f"[assignable-users] instance not found or no current_stage_id: instance={instance}")
        return []

    print(f"[assignable-users] current_stage_id={instance.current_stage_id}, action={action_code}")

    # Find the transition for this action
    transition = (
        db.query(TrWfStageTransition)
        .filter(
            TrWfStageTransition.from_stage_id == instance.current_stage_id,
            TrWfStageTransition.action_code == action_code,
        )
        .first()
    )
    if not transition or not transition.to_stage_id:
        print(f"[assignable-users] no transition found for action={action_code} from stage={instance.current_stage_id}")
        return []

    print(f"[assignable-users] to_stage_id={transition.to_stage_id}")

    # Roles on the destination stage
    stage_role_ids = [
        sr.role_id
        for sr in db.query(TrWfStageRole)
        .filter(TrWfStageRole.stage_id == transition.to_stage_id)
        .all()
    ]
    if not stage_role_ids:
        print(f"[assignable-users] no roles on destination stage {transition.to_stage_id}")
        return []

    print(f"[assignable-users] stage_role_ids={stage_role_ids}")

    # Users in this org who hold any of those roles
    user_ids = [
        row[0]
        for row in db.query(OrgUserRole.user_id)
        .filter(
            OrgUserRole.org_role_id.in_(stage_role_ids),
            OrgUserRole.is_active.is_(True),
        )
        .distinct()
        .all()
    ]

    users = db.query(User).filter(User.id.in_(user_ids)).all()
    return [
        {
            "id":         str(u.id),
            "name":       f"{u.firstname or ''} {u.lastname or ''}".strip() or u.email,
            "email":      u.email,
        }
        for u in users
    ]


# ---------------------------------------------------------------------------
# Perform action
# ---------------------------------------------------------------------------

@router.post("/{doc_id}/action")
def perform_action(
    doc_id: UUID,
    payload: dict,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    action_code = payload.get("action_code")
    if not action_code:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="action_code is required")

    role_ids = _user_role_ids(db, current_user)
    role_id = role_ids[0] if role_ids else None

    svc = DocSupportService(db)
    assigned_user_id = payload.get("assigned_user_id")
    # If a processor self-accepts (no user selected), auto-assign to themselves
    if action_code == "assign" and not assigned_user_id:
        assigned_user_id = str(current_user.id)

    action_code = payload.get("action_code")

    print(f"Document Support action = {action_code}")
    
    instance = svc.transition(
        doc_id=doc_id,
        action_code=action_code,
        performed_by_id=current_user.id,
        role_id=role_id,
        comment=payload.get("comment"),
        assigned_user_id=assigned_user_id,
        assigned_role_id=payload.get("assigned_role_id"),
    )
    db.commit()

    doc = svc.get_document_request(doc_id)
    return {
        **_doc_response(doc),
        "wf_status": instance.status,
        "current_status_code": instance.current_status_code,
    }


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

@router.get("/{doc_id}/audit")
def get_audit_trail(
    doc_id: UUID,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    doc = db.query(DocumentRequest).filter(DocumentRequest.id == doc_id).first()
    if not doc or not doc.wf_instance_id:
        return []

    logs = (
        db.query(TrWfAuditLog)
        .filter(TrWfAuditLog.wf_instance_id == doc.wf_instance_id)
        .order_by(TrWfAuditLog.created_at)
        .all()
    )
    user_ids = [l.performed_by for l in logs if l.performed_by]
    users = {u.id: f"{u.firstname or ''} {u.lastname or ''}".strip() or u.email
             for u in db.query(User).filter(User.id.in_(user_ids)).all()} if user_ids else {}

    return [
        {
            "id": str(l.id),
            "action_code": l.action_code,
            "from_status_code": l.from_status_code,
            "to_status_code": l.to_status_code,
            "performed_by": users.get(l.performed_by, str(l.performed_by)) if l.performed_by else None,
            "comment": l.comment,
            "is_send_back": l.is_send_back,
            "is_terminal": l.is_terminal,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in logs
    ]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _doc_response(doc: DocumentRequest) -> dict:
    return {
        "id": str(doc.id),
        "org_id": str(doc.org_id),
        "title": doc.title,
        "description": doc.description,
        "file_url": doc.file_url,
        "file_name": doc.file_name,
        "file_size": doc.file_size,
        "mime_type": doc.mime_type,
        "notes": doc.notes,
        "priority": doc.priority,
        "target_date": doc.target_date.isoformat() if doc.target_date else None,
        "current_status_code": doc.current_status_code,
        "wf_instance_id": str(doc.wf_instance_id) if doc.wf_instance_id else None,
        "submitted_by": str(doc.submitted_by) if doc.submitted_by else None,
        "assigned_manager_id": str(doc.assigned_manager_id) if doc.assigned_manager_id else None,
        "assigned_processor_id": str(doc.assigned_processor_id) if doc.assigned_processor_id else None,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "modified_at": doc.modified_at.isoformat() if doc.modified_at else None,
        "closed_at": doc.closed_at.isoformat() if doc.closed_at else None,
    }
