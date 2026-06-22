from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException

from models import TestingRequest
from services.workflow_factory import EntityAdapter, register_adapter


@register_adapter
class TestingRequestAdapter(EntityAdapter):
    entity_type = "testing_request"

    def get_entity(self, entity_id: uuid.UUID) -> TestingRequest:
        obj = self.db.query(TestingRequest).filter(TestingRequest.id == entity_id).first()
        if obj is None:
            raise HTTPException(status_code=404, detail="TestingRequest not found")
        return obj

    def get_org_id(self, entity: TestingRequest) -> uuid.UUID:
        return entity.org_id

    def get_request_type(self, entity: TestingRequest) -> Optional[str]:
        return getattr(entity, "request_type", None)

    def get_wf_instance_id(self, entity: TestingRequest) -> Optional[uuid.UUID]:
        return getattr(entity, "wf_instance_id", None)

    def link_wf_instance(self, entity: TestingRequest, wf_instance_id: uuid.UUID) -> None:
        entity.wf_instance_id = wf_instance_id

    def update_status(self, entity: TestingRequest, status_code: str) -> None:
        entity.current_status_code = status_code

    def get_submitted_by(self, entity: TestingRequest) -> Optional[uuid.UUID]:
        return getattr(entity, "created_by", None)

    def build_wf_instance_kwargs(self, entity: TestingRequest) -> dict:
        return {"testing_request_id": entity.id}

    def build_audit_log_kwargs(self, entity: TestingRequest) -> dict:
        return {"testing_request_id": entity.id}
