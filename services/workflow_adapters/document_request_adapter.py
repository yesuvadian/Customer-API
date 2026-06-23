from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException

from models import DocumentRequest
from services.workflow_factory import EntityAdapter, register_adapter


@register_adapter
class DocumentRequestAdapter(EntityAdapter):
    entity_type = "document_request"

    def get_entity(self, entity_id: uuid.UUID) -> DocumentRequest:
        obj = self.db.query(DocumentRequest).filter(DocumentRequest.id == entity_id).first()
        if obj is None:
            raise HTTPException(status_code=404, detail="DocumentRequest not found")
        return obj

    def get_org_id(self, entity: DocumentRequest) -> uuid.UUID:
        return entity.org_id

    def get_request_type(self, entity: DocumentRequest) -> Optional[str]:
        return "document_support"

    def get_wf_instance_id(self, entity: DocumentRequest) -> Optional[uuid.UUID]:
        return entity.wf_instance_id

    def link_wf_instance(self, entity: DocumentRequest, wf_instance_id: uuid.UUID) -> None:
        entity.wf_instance_id = wf_instance_id

    def update_status(self, entity: DocumentRequest, status_code: str) -> None:
        entity.current_status_code = status_code

    def get_submitted_by(self, entity: DocumentRequest) -> Optional[uuid.UUID]:
        return entity.submitted_by

    # No testing_request_id — entity_type / entity_id columns on TrWfInstance cover it
    def build_wf_instance_kwargs(self, entity: DocumentRequest) -> dict:
        return {}

    def build_audit_log_kwargs(self, entity: DocumentRequest) -> dict:
        return {}
