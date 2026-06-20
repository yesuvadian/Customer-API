"""
Admin CRUD endpoints for the Configurable Test-Request Workflow Engine (tr_wf_*).

Prefix: /tr-workflow-config
Tags:   Workflow Config

Endpoints:
  Definitions  GET/POST /definitions
               GET/PATCH/DELETE /definitions/{id}
  Statuses     GET/POST /definitions/{def_id}/statuses
               PATCH/DELETE /statuses/{id}
  Stages       GET/POST /definitions/{def_id}/stages
               PATCH /stages/{id}
               DELETE /stages/{id}
               PUT /stages/{id}/roles          (full replace)
               PUT /stages/{id}/transitions    (full replace)
  Routing      GET/POST /routing-rules
               DELETE /routing-rules/{id}
               GET/PUT /routing-default
  Picker opts  GET /picker-options   (equip types, test types, org roles)
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from auth_utils import get_current_user
from database import get_db
from models import (
    OrgRole,
    OrgUserRole,
    TrWfDefinition,
    TrWfRoutingDefault,
    TrWfRoutingRule,
    TrWfStage,
    TrWfStageRole,
    TrWfStageTransition,
    TrWfStatus,
    User,
    CategoryMaster,
    CategoryDetails,
)

router = APIRouter(prefix="/tr-workflow-config", tags=["Workflow Config"])


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _stage_out(s: TrWfStage) -> dict:
    return {
        "id": str(s.id),
        "wf_definition_id": str(s.wf_definition_id),
        "status_id": str(s.status_id) if s.status_id else None,
        "name": s.name,
        "code": s.code,
        "sequence": s.sequence,
        "weight": s.weight,
        "is_mandatory": s.is_mandatory,
        "is_active": s.is_active,
        "default_duration_days": s.default_duration_days,
        "status": {
            "id": str(s.status.id),
            "status_code": s.status.status_code,
            "status_name": s.status.status_name,
        } if s.status else None,
        "roles": [
            {
                "id": str(r.id),
                "role_id": str(r.role_id),
                "role_name": r.role.name if r.role else None,
                "can_approve": r.can_approve,
                "can_assign": r.can_assign,
                "can_edit": r.can_edit,
            }
            for r in s.roles
        ],
        "transitions": [
            {
                "id": str(t.id),
                "from_stage_id": str(t.from_stage_id),
                "to_stage_id": str(t.to_stage_id) if t.to_stage_id else None,
                "action_code": t.action_code,
                "requires_comment": t.requires_comment,
                "is_rejection": t.is_rejection,
                "terminal_status_id": str(t.terminal_status_id) if t.terminal_status_id else None,
                "to_stage_name": t.to_stage.name if t.to_stage else None,
                "terminal_status_code": t.terminal_status.status_code if t.terminal_status else None,
            }
            for t in s.transitions
        ],
    }


def _def_out(d: TrWfDefinition, db: Session = None) -> dict:
    stage_count = len(d.stages) if hasattr(d, 'stages') and d.stages is not None else 0
    status_count = len(d.statuses) if hasattr(d, 'statuses') and d.statuses is not None else 0
    return {
        "id": str(d.id),
        "org_id": str(d.org_id),
        "name": d.name,
        "request_type": d.request_type,
        "is_default": d.is_default,
        "is_active": d.is_active,
        "stage_count": stage_count,
        "status_count": status_count,
        "default_l3_role_id": str(d.default_l3_role_id) if d.default_l3_role_id else None,
        "default_l3_role_name": d.default_l3_role.name if d.default_l3_role else None,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


def _status_out(s: TrWfStatus) -> dict:
    return {
        "id": str(s.id),
        "wf_definition_id": str(s.wf_definition_id),
        "status_code": s.status_code,
        "status_name": s.status_name,
        "sequence": s.sequence,
        "color": s.color,
        "approval_required": s.approval_required,
        "assignment_required": s.assignment_required,
        "is_terminal": s.is_terminal,
        "is_active": s.is_active,
    }


def _rule_out(r: TrWfRoutingRule) -> dict:
    return {
        "id": str(r.id),
        "org_id": str(r.org_id),
        "wf_definition_id": str(r.wf_definition_id) if r.wf_definition_id else None,
        "wf_definition_name": r.wf_definition.name if r.wf_definition else None,
        "override_role_id": str(r.override_role_id) if r.override_role_id else None,
        "override_role_name": r.override_role.name if r.override_role else None,
        "override_tester_role_id": str(r.override_tester_role_id) if r.override_tester_role_id else None,
        "override_tester_role_name": r.override_tester_role.name if r.override_tester_role else None,
        "request_type": r.request_type,
        "equipment_type_id": r.equipment_type_id,
        "equipment_type_name": r.equipment_type.name if r.equipment_type else None,
        "test_type_id": r.test_type_id,
        "test_type_name": r.test_type.name if r.test_type else None,
        "priority": r.priority,
        "is_active": r.is_active,
    }


def _get_org_id(current_user: User) -> UUID:
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="User has no organization.")
    return current_user.organization_id


# ──────────────────────────────────────────────────────────────────────────────
# Definitions
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/definitions")
def list_definitions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    defs = (
        db.query(TrWfDefinition)
        .options(joinedload(TrWfDefinition.stages), joinedload(TrWfDefinition.statuses))
        .filter(TrWfDefinition.org_id == org_id)
        .all()
    )
    return [_def_out(d) for d in defs]


@router.post("/definitions", status_code=status.HTTP_201_CREATED)
def create_definition(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    defn = TrWfDefinition(
        org_id=org_id,
        name=body["name"],
        request_type=body.get("request_type"),
        is_default=body.get("is_default", False),
        is_active=body.get("is_active", True),
        created_by=current_user.id,
    )
    db.add(defn)
    db.commit()
    db.refresh(defn)
    return _def_out(defn)


@router.get("/definitions/{def_id}")
def get_definition(
    def_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    defn = db.query(TrWfDefinition).filter(
        TrWfDefinition.id == def_id,
        TrWfDefinition.org_id == org_id,
    ).first()
    if not defn:
        raise HTTPException(status_code=404, detail="Definition not found")
    return _def_out(defn)


@router.patch("/definitions/{def_id}")
def patch_definition(
    def_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    defn = db.query(TrWfDefinition).filter(
        TrWfDefinition.id == def_id,
        TrWfDefinition.org_id == org_id,
    ).first()
    if not defn:
        raise HTTPException(status_code=404, detail="Definition not found")
    for k in ("name", "request_type", "is_default", "is_active", "default_l3_role_id"):
        if k in body:
            setattr(defn, k, body[k] or None)
    defn.modified_by = current_user.id
    db.commit()
    db.refresh(defn)
    return _def_out(defn)


@router.delete("/definitions/{def_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_definition(
    def_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    defn = db.query(TrWfDefinition).filter(
        TrWfDefinition.id == def_id,
        TrWfDefinition.org_id == org_id,
    ).first()
    if not defn:
        raise HTTPException(status_code=404, detail="Definition not found")
    db.delete(defn)
    db.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Statuses
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/definitions/{def_id}/statuses")
def list_statuses(
    def_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(TrWfStatus)
        .filter(TrWfStatus.wf_definition_id == def_id)
        .order_by(TrWfStatus.sequence)
        .all()
    )
    return [_status_out(r) for r in rows]


@router.post("/definitions/{def_id}/statuses", status_code=status.HTTP_201_CREATED)
def create_status(
    def_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = TrWfStatus(
        wf_definition_id=def_id,
        status_code=body["status_code"],
        status_name=body["status_name"],
        sequence=body.get("sequence", 0),
        color=body.get("color"),
        approval_required=body.get("approval_required", False),
        assignment_required=body.get("assignment_required", False),
        is_terminal=body.get("is_terminal", False),
        is_active=body.get("is_active", True),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _status_out(row)


def _do_patch_status(status_id: UUID, body: dict, db: Session) -> dict:
    row = db.query(TrWfStatus).filter(TrWfStatus.id == status_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Status not found")
    for k in ("status_name", "color", "sequence", "approval_required",
              "assignment_required", "is_terminal", "is_active"):
        if k in body:
            setattr(row, k, body[k])
    db.commit()
    db.refresh(row)
    return _status_out(row)


def _do_delete_status(status_id: UUID, db: Session) -> None:
    row = db.query(TrWfStatus).filter(TrWfStatus.id == status_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Status not found")
    db.delete(row)
    db.commit()


# Nested path (matches Flutter service URL pattern)
@router.patch("/definitions/{def_id}/statuses/{status_id}")
def patch_status_nested(
    def_id: UUID, status_id: UUID, body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _do_patch_status(status_id, body, db)


@router.delete("/definitions/{def_id}/statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_status_nested(
    def_id: UUID, status_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _do_delete_status(status_id, db)


# Flat path (kept for backwards compat / direct use)
@router.patch("/statuses/{status_id}")
def patch_status(
    status_id: UUID, body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _do_patch_status(status_id, body, db)


@router.delete("/statuses/{status_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_status(
    status_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _do_delete_status(status_id, db)


# ──────────────────────────────────────────────────────────────────────────────
# Stages
# ──────────────────────────────────────────────────────────────────────────────

def _load_stage(db: Session, stage_id: UUID) -> TrWfStage:
    stage = (
        db.query(TrWfStage)
        .options(
            joinedload(TrWfStage.roles).joinedload(TrWfStageRole.role),
            joinedload(TrWfStage.transitions).joinedload(TrWfStageTransition.to_stage),
            joinedload(TrWfStage.transitions).joinedload(TrWfStageTransition.terminal_status),
            joinedload(TrWfStage.status),
        )
        .filter(TrWfStage.id == stage_id)
        .first()
    )
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    return stage


@router.get("/definitions/{def_id}/stages")
def list_stages(
    def_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stages = (
        db.query(TrWfStage)
        .options(
            joinedload(TrWfStage.roles).joinedload(TrWfStageRole.role),
            joinedload(TrWfStage.transitions).joinedload(TrWfStageTransition.to_stage),
            joinedload(TrWfStage.transitions).joinedload(TrWfStageTransition.terminal_status),
            joinedload(TrWfStage.status),
        )
        .filter(TrWfStage.wf_definition_id == def_id)
        .order_by(TrWfStage.sequence)
        .all()
    )
    return [_stage_out(s) for s in stages]


@router.post("/definitions/{def_id}/stages", status_code=status.HTTP_201_CREATED)
def create_stage(
    def_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stage = TrWfStage(
        wf_definition_id=def_id,
        status_id=body.get("status_id"),
        name=body["name"],
        code=body["code"],
        sequence=body.get("sequence", 1),
        weight=body.get("weight", 10),
        is_mandatory=body.get("is_mandatory", True),
        is_active=body.get("is_active", True),
        default_duration_days=body.get("default_duration_days"),
    )
    db.add(stage)
    db.commit()
    return _stage_out(_load_stage(db, stage.id))


@router.patch("/stages/{stage_id}")
def patch_stage(
    stage_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stage = db.query(TrWfStage).filter(TrWfStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    for k in ("name", "code", "sequence", "weight", "status_id",
              "is_mandatory", "is_active", "default_duration_days"):
        if k in body:
            setattr(stage, k, body[k])
    db.commit()
    return _stage_out(_load_stage(db, stage.id))


@router.delete("/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stage(
    stage_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stage = db.query(TrWfStage).filter(TrWfStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    db.delete(stage)
    db.commit()


# ── Stage Roles (full replace) ─────────────────────────────────────────────────

@router.put("/stages/{stage_id}/roles")
def replace_stage_roles(
    stage_id: UUID,
    body: list = Body(...),  # list of {role_id, can_approve, can_assign, can_edit}
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stage = db.query(TrWfStage).filter(TrWfStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    # Delete existing
    db.query(TrWfStageRole).filter(TrWfStageRole.stage_id == stage_id).delete()
    db.flush()

    for r in body:
        db.add(TrWfStageRole(
            stage_id=stage_id,
            role_id=r["role_id"],
            can_approve=r.get("can_approve", False),
            can_assign=r.get("can_assign", False),
            can_edit=r.get("can_edit", False),
        ))
    db.commit()
    return _stage_out(_load_stage(db, stage_id))


# ── Stage Transitions (full replace) ──────────────────────────────────────────

@router.put("/stages/{stage_id}/transitions")
def replace_stage_transitions(
    stage_id: UUID,
    body: list = Body(...),  # list of {action_code, to_stage_id?, terminal_status_id?, requires_comment, is_rejection}
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stage = db.query(TrWfStage).filter(TrWfStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")

    db.query(TrWfStageTransition).filter(
        TrWfStageTransition.from_stage_id == stage_id
    ).delete()
    db.flush()

    for t in body:
        db.add(TrWfStageTransition(
            from_stage_id=stage_id,
            to_stage_id=t.get("to_stage_id"),
            action_code=t["action_code"],
            requires_comment=t.get("requires_comment", False),
            is_rejection=t.get("is_rejection", False),
            terminal_status_id=t.get("terminal_status_id"),
        ))
    db.commit()
    return _stage_out(_load_stage(db, stage_id))


# ──────────────────────────────────────────────────────────────────────────────
# Routing rules
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/routing/rules")
def list_routing_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    rules = (
        db.query(TrWfRoutingRule)
        .options(
            joinedload(TrWfRoutingRule.wf_definition),
            joinedload(TrWfRoutingRule.override_role),
            joinedload(TrWfRoutingRule.override_tester_role),
            joinedload(TrWfRoutingRule.equipment_type),
            joinedload(TrWfRoutingRule.test_type),
        )
        .filter(TrWfRoutingRule.org_id == org_id)
        .all()
    )
    return [_rule_out(r) for r in rules]


@router.post("/routing/rules", status_code=status.HTTP_201_CREATED)
def create_routing_rule(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    rule = TrWfRoutingRule(
        org_id=org_id,
        wf_definition_id=body.get("wf_definition_id") or None,
        override_role_id=body.get("override_role_id") or None,
        override_tester_role_id=body.get("override_tester_role_id") or None,
        request_type=body.get("request_type"),
        equipment_type_id=body.get("equipment_type_id"),
        test_type_id=body.get("test_type_id"),
        priority=body.get("priority", 0),
        is_active=body.get("is_active", True),
        created_by=current_user.id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_out(rule)


@router.patch("/routing/rules/{rule_id}")
def patch_routing_rule(
    rule_id: UUID,
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    rule = db.query(TrWfRoutingRule).filter(
        TrWfRoutingRule.id == rule_id,
        TrWfRoutingRule.org_id == org_id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    allowed = {
        "override_role_id", "override_tester_role_id", "wf_definition_id", "request_type",
        "equipment_type_id", "test_type_id", "priority", "is_active",
    }
    for k, v in body.items():
        if k in allowed:
            # allow explicit null to clear a field
            setattr(rule, k, v if v != "" else None)
    db.commit()
    db.refresh(rule)
    return _rule_out(rule)


@router.delete("/routing/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_routing_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    rule = db.query(TrWfRoutingRule).filter(
        TrWfRoutingRule.id == rule_id,
        TrWfRoutingRule.org_id == org_id,
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Routing rule not found")
    db.delete(rule)
    db.commit()


# ──────────────────────────────────────────────────────────────────────────────
# Routing default
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/routing/default")
def get_routing_default(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    row = db.query(TrWfRoutingDefault).filter(
        TrWfRoutingDefault.org_id == org_id
    ).first()
    if not row:
        return None
    return {
        "id": str(row.id),
        "org_id": str(row.org_id),
        "wf_definition_id": str(row.wf_definition_id) if row.wf_definition_id else None,
        "wf_definition_name": row.wf_definition.name if row.wf_definition else None,
    }


@router.put("/routing/default")
def upsert_routing_default(
    body: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    row = db.query(TrWfRoutingDefault).filter(
        TrWfRoutingDefault.org_id == org_id
    ).first()
    if row:
        row.wf_definition_id = body.get("wf_definition_id")
        row.updated_by = current_user.id
    else:
        row = TrWfRoutingDefault(
            org_id=org_id,
            wf_definition_id=body.get("wf_definition_id"),
            updated_by=current_user.id,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    defn = db.query(TrWfDefinition).filter(
        TrWfDefinition.id == row.wf_definition_id
    ).first() if row.wf_definition_id else None
    return {
        "id": str(row.id),
        "org_id": str(row.org_id),
        "wf_definition_id": str(row.wf_definition_id) if row.wf_definition_id else None,
        "wf_definition_name": defn.name if defn else None,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Picker options (for dropdowns in admin UI)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/options/equipment-types")
def get_equipment_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(CategoryMaster.id, CategoryMaster.name)
        .filter(
            CategoryMaster.description == "Testing Equipment",
            CategoryMaster.is_active.is_(True),
        )
        .order_by(CategoryMaster.name)
        .all()
    )
    return [{"id": r.id, "name": r.name} for r in rows]


@router.get("/options/test-types")
def get_test_types(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(CategoryDetails.id, CategoryDetails.name, CategoryDetails.category_master_id)
        .filter(
            CategoryDetails.category_type == "test",
            CategoryDetails.is_active.is_(True),
        )
        .order_by(CategoryDetails.name)
        .all()
    )
    return [{"id": r.id, "name": r.name, "equipment_type_id": r.category_master_id} for r in rows]


@router.get("/options/roles")
def get_org_roles(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    org_id = _get_org_id(current_user)
    rows = (
        db.query(OrgRole.id, OrgRole.name, OrgRole.description)
        .filter(OrgRole.organization_id == org_id, OrgRole.is_active.is_(True))
        .order_by(OrgRole.name)
        .all()
    )
    return [
        {"id": str(r.id), "name": r.name, "description": r.description}
        for r in rows
    ]


@router.get("/options/action-codes")
def get_action_codes(
    current_user: User = Depends(get_current_user),
):
    """Return all action codes the workflow engine supports."""
    from services.tr_workflow_routing_service import ACTION_CODE_LABELS
    return [
        {"code": code, "label": label}
        for code, label in ACTION_CODE_LABELS.items()
    ]


@router.get("/picker-options")
def get_picker_options(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Combined picker options for admin config forms."""
    from services.tr_workflow_routing_service import ACTION_CODE_LABELS
    return {
        "equipment_types": get_equipment_types(db, current_user),
        "test_types": get_test_types(db, current_user),
        "org_roles": get_org_roles(db, current_user),
        "action_codes": [
            {"code": code, "label": label}
            for code, label in ACTION_CODE_LABELS.items()
        ],
    }
