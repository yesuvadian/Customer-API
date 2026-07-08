"""Pydantic schemas for the Test Request Configurable Workflow Engine (tr_wf_*)."""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# TrWfStatus
# ---------------------------------------------------------------------------

class TrWfStatusOut(BaseModel):
    id: UUID
    wf_definition_id: UUID
    status_code: str
    status_name: str
    sequence: int
    color: Optional[str]
    approval_required: bool
    assignment_required: bool
    is_terminal: bool
    is_active: bool

    class Config:
        from_attributes = True


class TrWfStatusCreate(BaseModel):
    status_code: str
    status_name: str
    sequence: int = 0
    color: Optional[str] = None
    approval_required: bool = False
    assignment_required: bool = False
    is_terminal: bool = False


class TrWfStatusPatch(BaseModel):
    status_name: Optional[str] = None
    sequence: Optional[int] = None
    color: Optional[str] = None
    approval_required: Optional[bool] = None
    assignment_required: Optional[bool] = None
    is_terminal: Optional[bool] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# TrWfStageRole
# ---------------------------------------------------------------------------

class TrWfStageRoleOut(BaseModel):
    role_id: UUID
    role_name: str
    can_approve: bool
    can_assign: bool
    can_edit: bool

    class Config:
        from_attributes = True


class TrWfStageRoleItem(BaseModel):
    role_id: UUID
    can_approve: bool = False
    can_assign: bool = False
    can_edit: bool = False


class TrWfStageRolesReplace(BaseModel):
    roles: List[TrWfStageRoleItem]


# ---------------------------------------------------------------------------
# TrWfStageTransition
# ---------------------------------------------------------------------------

class TrWfTransitionOut(BaseModel):
    id: UUID
    from_stage_id: UUID
    to_stage_id: Optional[UUID]          # None = terminal
    action_code: str
    requires_comment: bool
    is_rejection: bool
    terminal_status_id: Optional[UUID]   # applied when to_stage is NULL or target has no roles

    class Config:
        from_attributes = True


class TrWfTransitionItem(BaseModel):
    action_code: str
    to_stage_id: Optional[UUID] = None
    requires_comment: bool = False
    is_rejection: bool = False
    terminal_status_id: Optional[UUID] = None


class TrWfTransitionsReplace(BaseModel):
    transitions: List[TrWfTransitionItem]


# ---------------------------------------------------------------------------
# TrWfStage
# ---------------------------------------------------------------------------

class TrWfStageOut(BaseModel):
    id: UUID
    wf_definition_id: UUID
    status_id: Optional[UUID]
    status: Optional[TrWfStatusOut]
    name: str
    code: str
    sequence: int
    weight: int
    is_mandatory: bool
    is_active: bool
    default_duration_days: Optional[int]
    show_recommendation: bool = False
    is_result_stage: bool = False
    use_l2_route: bool = False
    is_role_scoped: bool = False
    roles: List[TrWfStageRoleOut] = []
    transitions: List[TrWfTransitionOut] = []

    class Config:
        from_attributes = True


class TrWfStageCreate(BaseModel):
    name: str
    code: str
    sequence: int
    weight: int = 10
    is_mandatory: bool = True
    default_duration_days: Optional[int] = None
    status_id: Optional[UUID] = None
    show_recommendation: bool = False
    is_result_stage: bool = False
    use_l2_route: bool = False
    is_role_scoped: bool = False


class TrWfStagePatch(BaseModel):
    name: Optional[str] = None
    sequence: Optional[int] = None
    weight: Optional[int] = None
    is_mandatory: Optional[bool] = None
    is_active: Optional[bool] = None
    default_duration_days: Optional[int] = None
    status_id: Optional[UUID] = None
    show_recommendation: Optional[bool] = None
    is_result_stage: Optional[bool] = None
    use_l2_route: Optional[bool] = None
    is_role_scoped: Optional[bool] = None


class TrWfStageReorderItem(BaseModel):
    stage_id: UUID
    sequence: int


class TrWfStageReorderRequest(BaseModel):
    stages: List[TrWfStageReorderItem]


# ---------------------------------------------------------------------------
# TrWfDefinition
# ---------------------------------------------------------------------------

class TrWfDefinitionOut(BaseModel):
    id: UUID
    org_id: UUID
    name: str
    request_type: Optional[str]
    is_default: bool
    is_active: bool
    stage_count: int = 0
    status_count: int = 0

    class Config:
        from_attributes = True


class TrWfDefinitionCreate(BaseModel):
    name: str
    request_type: Optional[str] = None  # normal | failure | special | None=all
    is_default: bool = False


class TrWfDefinitionPatch(BaseModel):
    name: Optional[str] = None
    request_type: Optional[str] = None
    is_default: Optional[bool] = None
    is_active: Optional[bool] = None


# ---------------------------------------------------------------------------
# TrWfInstance (runtime)
# ---------------------------------------------------------------------------

class TrWfStageInstanceOut(BaseModel):
    id: UUID
    stage_id: Optional[UUID]
    stage_name: Optional[str]
    status: str
    action_taken: Optional[str]
    assigned_user_id: Optional[UUID]
    assigned_user_name: Optional[str]
    assigned_role_id: Optional[UUID]
    assigned_role_name: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    completed_by: Optional[UUID]
    comment: Optional[str]

    class Config:
        from_attributes = True


class TrWfInstanceOut(BaseModel):
    id: UUID
    wf_definition_id: Optional[UUID]
    wf_definition_name: Optional[str]
    testing_request_id: UUID
    current_stage_id: Optional[UUID]
    current_stage_name: Optional[str]
    current_status_code: Optional[str]
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    stage_instances: List[TrWfStageInstanceOut] = []

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# TrWfAuditLog
# ---------------------------------------------------------------------------

class TrWfAuditLogOut(BaseModel):
    id: UUID
    from_stage_id: Optional[UUID]
    from_stage_name: Optional[str]
    to_stage_id: Optional[UUID]
    to_stage_name: Optional[str]
    action_code: str
    performed_by: Optional[UUID]
    performed_by_name: Optional[str]
    role_id: Optional[UUID]
    role_name: Optional[str]
    from_status_code: Optional[str]
    to_status_code: Optional[str]
    comment: Optional[str]
    is_send_back: bool
    is_terminal: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Available action (returned per-request in queue endpoints)
# ---------------------------------------------------------------------------

class TrWfAvailableAction(BaseModel):
    action_code: str
    label: str                          # human-readable: "Approve", "Return to Tester"
    requires_comment: bool
    is_rejection: bool
    to_stage_id: Optional[UUID]
    to_stage_name: Optional[str]
    to_status_code: Optional[str]


# ---------------------------------------------------------------------------
# Picker options
# ---------------------------------------------------------------------------

class TrWfRoleOption(BaseModel):
    id: UUID
    name: str

    class Config:
        from_attributes = True


class TrWfStatusOption(BaseModel):
    id: UUID
    status_code: str
    status_name: str

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Routing Rules & Defaults
# ---------------------------------------------------------------------------

class TrWfRoutingRuleOut(BaseModel):
    id: UUID
    org_id: UUID
    wf_definition_id: UUID
    wf_definition_name: Optional[str]
    override_role_id: Optional[UUID]
    override_role_name: Optional[str]
    override_tester_role_id: Optional[UUID]
    override_tester_role_name: Optional[str]
    # Many-to-many replacement for the 2 override fields above — an
    # unlimited list of roles this rule resolves to.
    role_ids: List[UUID] = []
    role_names: List[str] = []
    source_stage_id: Optional[UUID]
    source_stage_name: Optional[str]
    request_type: Optional[str]
    equipment_type_id: Optional[int]
    equipment_type_name: Optional[str]
    test_type_id: Optional[int]
    test_type_name: Optional[str]
    priority: int
    is_active: bool

    class Config:
        from_attributes = True


class TrWfRoutingRuleCreate(BaseModel):
    wf_definition_id: UUID
    override_role_id: Optional[UUID] = None
    override_tester_role_id: Optional[UUID] = None
    role_ids: Optional[List[UUID]] = None    # None = fall back to the 2 override fields above
    source_stage_id: Optional[UUID] = None   # None = entry-point rule (default)
    request_type: Optional[str] = None       # normal | failure | special | None=any
    equipment_type_id: Optional[int] = None
    test_type_id: Optional[int] = None
    priority: int = 0


class TrWfRoutingRulePatch(BaseModel):
    wf_definition_id: Optional[UUID] = None
    override_role_id: Optional[UUID] = None
    override_tester_role_id: Optional[UUID] = None
    role_ids: Optional[List[UUID]] = None
    source_stage_id: Optional[UUID] = None
    request_type: Optional[str] = None
    equipment_type_id: Optional[int] = None
    test_type_id: Optional[int] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class TrWfRoutingDefaultOut(BaseModel):
    id: UUID
    org_id: UUID
    wf_definition_id: Optional[UUID]
    wf_definition_name: Optional[str]
    updated_by: Optional[UUID]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class TrWfRoutingDefaultUpsert(BaseModel):
    wf_definition_id: UUID


# Lookup picker options for routing config UI
class EquipmentTypeOption(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True


class TestTypeOption(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True
