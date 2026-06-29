"""
Document Support Service
========================
Business logic for DocumentRequest lifecycle + workflow enrollment.
All methods are transactional — caller commits.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import DocumentRequest, TrWfInstance, TrWfStatus, TrWfStage
from services.workflow_factory import WorkflowFactory
from services.generic_workflow_service import GenericWorkflowService

# Ensure adapters are registered
import services.workflow_adapters.testing_request_adapter  # noqa: F401
import services.workflow_adapters.document_request_adapter  # noqa: F401

log = logging.getLogger(__name__)

ENTITY_TYPE = "document_request"


def _resolve_wf_labels(db: Session, instance: TrWfInstance) -> tuple[str, str]:
    """Return (status_name, stage_name) from DB for the current instance state."""
    status_name = instance.current_status_code or ""
    stage_name  = ""
    if instance.current_status_code and instance.wf_definition_id:
        row = db.query(TrWfStatus).filter(
            TrWfStatus.wf_definition_id == instance.wf_definition_id,
            TrWfStatus.status_code == instance.current_status_code,
        ).first()
        if row:
            status_name = row.status_name
    if instance.current_stage_id:
        stage = db.query(TrWfStage).filter(TrWfStage.id == instance.current_stage_id).first()
        if stage:
            stage_name = stage.name or ""
    return status_name, stage_name


def _make_service(db: Session) -> GenericWorkflowService:
    adapter = WorkflowFactory.get_adapter(ENTITY_TYPE, db)
    return GenericWorkflowService(db, adapter)


class DocSupportService:
    def __init__(self, db: Session):
        self.db = db
        self._wf = _make_service(db)

    # ------------------------------------------------------------------
    # Submit a new document request
    # ------------------------------------------------------------------

    def submit(
        self,
        org_id: UUID,
        submitted_by: UUID,
        title: str,
        description: Optional[str] = None,
        notes: Optional[str] = None,
        file_url: Optional[str] = None,
        file_name: Optional[str] = None,
        file_size: Optional[int] = None,
        mime_type: Optional[str] = None,
        priority: Optional[str] = "normal",
        target_date=None,
    ) -> DocumentRequest:
        from datetime import datetime, timezone
        parsed_target = None
        if target_date:
            try:
                parsed_target = datetime.fromisoformat(target_date.replace("Z", "+00:00"))
            except Exception:
                parsed_target = None
        doc = DocumentRequest(
            id=uuid4(),
            org_id=org_id,
            submitted_by=submitted_by,
            title=title,
            description=description,
            notes=notes,
            file_url=file_url,
            file_name=file_name,
            file_size=file_size,
            mime_type=mime_type,
            priority=priority or "normal",
            target_date=parsed_target,
        )
        self.db.add(doc)
        self.db.flush()

        try:
            self._wf.instantiate_workflow(doc.id, performed_by_id=submitted_by)
        except Exception as err:
            log.warning("Doc support WF enrollment failed (non-fatal): %s", err)

        # Notify: submission confirmation to originator + alert to Dev Support Manager
        try:
            from services.notification_service import NotificationService
            _inst = self.db.query(TrWfInstance).filter(
                TrWfInstance.entity_id == doc.id
            ).first()
            _status_name, _stage_name = _resolve_wf_labels(self.db, _inst) if _inst else ("Pending", "")
            NotificationService(self.db).fire(
                event_type="ds_wf_submitted",
                context={
                    "title":       doc.title,
                    "status_name": _status_name,
                    "stage_name":  _stage_name,
                    "action_code": "create",
                },
                organization_id=org_id,
                source_id=doc.id,
                source_type="document_request",
                recipient_roles_override=["@originator", "Dev Support Manager"],
            )
        except Exception as _n_err:
            log.warning("DS submitted notification failed (non-fatal): %s", _n_err)

        log.info("DocumentRequest submitted: id=%s by=%s", doc.id, submitted_by)
        return doc

    # ------------------------------------------------------------------
    # Workflow transition (assign, process, complete, accept, reject)
    # ------------------------------------------------------------------

    def transition(
        self,
        doc_id: UUID,
        action_code: str,
        performed_by_id: UUID,
        role_id: Optional[UUID] = None,
        comment: Optional[str] = None,
        assigned_user_id: Optional[UUID] = None,
        assigned_role_id: Optional[UUID] = None,
    ) -> TrWfInstance:
        instance = self._wf.advance_stage(
            entity_id=doc_id,
            action_code=action_code,
            performed_by_id=performed_by_id,
            role_id=role_id,
            comment=comment,
            assigned_user_id=assigned_user_id,
            assigned_role_id=assigned_role_id,
        )

        doc = self.db.query(DocumentRequest).filter(DocumentRequest.id == doc_id).first()
        if instance.status in ("completed", "terminated"):
            if doc:
                doc.closed_at = datetime.now(timezone.utc)

        if doc:
            from services.notification_service import NotificationService
            _svc = NotificationService(self.db)
            _status_name, _stage_name = _resolve_wf_labels(self.db, instance)
            _ctx = {
                "title":       doc.title,
                "status_name": _status_name,
                "stage_name":  _stage_name,
                "action_code": action_code,
            }

            # Fire general status-change notification (email + SMS + inapp via template)
            try:
                _svc.fire(
                    event_type="ds_wf_status_changed",
                    context=_ctx,
                    organization_id=doc.org_id,
                    source_id=doc_id,
                    source_type="document_request",
                    status_from=None,
                    status_to=instance.current_status_code,
                )
            except Exception as _n_err:
                log.warning("DS status-changed notification failed (non-fatal): %s", _n_err)

            # Extra notification when originator review stage is reached
            if instance.current_status_code == "ds_originator_review":
                try:
                    _svc.fire(
                        event_type="ds_wf_originator_review",
                        context=_ctx,
                        organization_id=doc.org_id,
                        source_id=doc_id,
                        source_type="document_request",
                        recipient_roles_override=["@originator"],
                    )
                except Exception as _n_err:
                    log.warning("DS originator-review notification failed (non-fatal): %s", _n_err)

        return instance

    # ------------------------------------------------------------------
    # Available actions for current user
    # ------------------------------------------------------------------

    def get_available_actions(self, doc_id: UUID, user_role_ids: list[UUID], user_id=None) -> list[dict]:
        return self._wf.get_available_actions(doc_id, user_role_ids, user_id=user_id)

    # ------------------------------------------------------------------
    # Get one
    # ------------------------------------------------------------------

    def get_document_request(self, doc_id: UUID) -> DocumentRequest:
        doc = self.db.query(DocumentRequest).filter(DocumentRequest.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="DocumentRequest not found")
        return doc

    # ------------------------------------------------------------------
    # List (org-scoped, optional status filter)
    # ------------------------------------------------------------------

    def list_for_org(
        self,
        org_id: UUID,
        status_filter: Optional[str] = None,
        submitted_by: Optional[UUID] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DocumentRequest]:
        q = self.db.query(DocumentRequest).filter(DocumentRequest.org_id == org_id)
        if status_filter:
            q = q.filter(DocumentRequest.current_status_code == status_filter)
        if submitted_by:
            q = q.filter(DocumentRequest.submitted_by == submitted_by)
        return q.order_by(DocumentRequest.created_at.desc()).offset(offset).limit(limit).all()
