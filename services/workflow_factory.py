"""
Generic Workflow Factory
========================
Separates entity-specific concerns (what is this thing, who submitted it,
what status field to update) from the shared workflow engine logic.

Usage:
    adapter = WorkflowFactory.get_adapter("testing_request", db)
    adapter.enroll(entity_id, performed_by_id)
    adapter.transition(entity_id, action_code, performed_by_id, comment)
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional, Type
from sqlalchemy.orm import Session


class EntityAdapter(ABC):
    """Abstract base — one concrete subclass per entity type."""

    entity_type: str  # must be set on the subclass

    def __init__(self, db: Session):
        self.db = db

    # ── required to implement ──────────────────────────────────────────────

    @abstractmethod
    def get_entity(self, entity_id: uuid.UUID) -> Any:
        """Return the ORM entity or raise 404."""

    @abstractmethod
    def get_org_id(self, entity: Any) -> uuid.UUID:
        """Return the org_id for this entity."""

    @abstractmethod
    def get_request_type(self, entity: Any) -> Optional[str]:
        """Return the routing key (e.g. 'normal', 'document_support')."""

    @abstractmethod
    def get_wf_instance_id(self, entity: Any) -> Optional[uuid.UUID]:
        """Return the wf_instance_id already set on the entity (or None)."""

    @abstractmethod
    def link_wf_instance(self, entity: Any, wf_instance_id: uuid.UUID) -> None:
        """Persist the wf_instance_id back onto the entity row."""

    @abstractmethod
    def update_status(self, entity: Any, status_code: str) -> None:
        """Denormalise the current_status_code onto the entity row."""

    @abstractmethod
    def get_submitted_by(self, entity: Any) -> Optional[uuid.UUID]:
        """User who originally submitted/created this entity."""

    # ── helpers (optional override) ────────────────────────────────────────

    def build_wf_instance_kwargs(self, entity: Any) -> dict:
        """Extra kwargs for TrWfInstance construction (e.g. testing_request_id)."""
        return {}

    def build_audit_log_kwargs(self, entity: Any) -> dict:
        """Extra kwargs for TrWfAuditLog rows."""
        return {}


_REGISTRY: dict[str, Type[EntityAdapter]] = {}


def register_adapter(cls: Type[EntityAdapter]) -> Type[EntityAdapter]:
    """Class decorator — registers an EntityAdapter subclass by entity_type."""
    _REGISTRY[cls.entity_type] = cls
    return cls


class WorkflowFactory:
    """Entry point — resolves the right adapter and delegates to the engine."""

    @staticmethod
    def get_adapter(entity_type: str, db: Session) -> EntityAdapter:
        cls = _REGISTRY.get(entity_type)
        if cls is None:
            raise ValueError(f"No workflow adapter registered for entity_type='{entity_type}'")
        return cls(db)

    @staticmethod
    def registered_types() -> list[str]:
        return list(_REGISTRY.keys())
