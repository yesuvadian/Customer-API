"""Pydantic schemas for the Workflow Configuration API."""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Workflow definition
# ---------------------------------------------------------------------------

class WorkflowOut(BaseModel):
    id: UUID
    workflow_code: Optional[str]
    name: str
    is_active: bool
    stage_count: int = 0

    class Config:
        from_attributes = True


class WorkflowCreate(BaseModel):
    workflow_code: str
    name: str


class WorkflowPatch(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# Stage roles
# ---------------------------------------------------------------------------

class StageRoleOut(BaseModel):
    role_id: UUID
    role_name: str
    can_edit: bool
    can_approve: bool
    can_assign: bool

    class Config:
        from_attributes = True


class StageRoleItem(BaseModel):
    role_id: UUID
    can_edit: bool = False
    can_approve: bool = False
    can_assign: bool = False


class StageRolesReplace(BaseModel):
    roles: List[StageRoleItem]


# ---------------------------------------------------------------------------
# Stage transitions
# ---------------------------------------------------------------------------

class TransitionOut(BaseModel):
    approve_to_stage_id: Optional[UUID]   # None = terminal
    reject_to_stage_id: Optional[UUID]    # None = no reject path


class TransitionUpsert(BaseModel):
    approve_to_stage_id: Optional[UUID] = None
    reject_to_stage_id: Optional[UUID] = None


# ---------------------------------------------------------------------------
# Stage definition
# ---------------------------------------------------------------------------

class StageOut(BaseModel):
    id: UUID
    name: str
    code: str
    sequence: int
    weight: int
    is_active: bool
    is_mandatory: bool
    default_duration_days: Optional[int]
    workflow_definition_id: Optional[UUID]
    template_id: Optional[UUID]
    template_key: Optional[str]
    roles: List[StageRoleOut] = []
    transitions: TransitionOut = TransitionOut(
        approve_to_stage_id=None, reject_to_stage_id=None
    )

    class Config:
        from_attributes = True


class StageCreate(BaseModel):
    name: str
    code: str
    sequence: int
    weight: int = 10
    is_mandatory: bool = True
    default_duration_days: Optional[int] = None
    template_id: Optional[UUID] = None


class StagePatch(BaseModel):
    name: Optional[str] = None
    sequence: Optional[int] = None
    weight: Optional[int] = None
    is_active: Optional[bool] = None
    is_mandatory: Optional[bool] = None
    default_duration_days: Optional[int] = None
    template_id: Optional[UUID] = None


class ReorderItem(BaseModel):
    stage_id: UUID
    sequence: int


class ReorderRequest(BaseModel):
    stages: List[ReorderItem]


# ---------------------------------------------------------------------------
# Lookup pickers
# ---------------------------------------------------------------------------

class RoleOption(BaseModel):
    id: UUID
    name: str

    class Config:
        from_attributes = True


class TemplateOption(BaseModel):
    id: UUID
    template_key: str

    class Config:
        from_attributes = True
