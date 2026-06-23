"""
Generic Workflow Service
========================
Engine logic (instantiate, advance, available actions) decoupled from any
specific entity type via EntityAdapter.

Entity-specific callers (doc_support_service, etc.) instantiate this with
the appropriate adapter, not directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    TrWfDefinition,
    TrWfInstance,
    TrWfStage,
    TrWfStageInstance,
    TrWfStageRole,
    TrWfStageTransition,
    TrWfRoutingDefault,
    TrWfRoutingRule,
    TrWfAuditLog,
)
from services.workflow_factory import EntityAdapter

log = logging.getLogger(__name__)


class GenericWorkflowService:
    """
    Workflow engine operating on any entity via EntityAdapter.
    All public methods are transactional — caller commits.
    """

    def __init__(self, db: Session, adapter: EntityAdapter):
        self.db = db
        self.adapter = adapter

    # ------------------------------------------------------------------
    # Routing lookup (same logic as WorkflowRoutingService.resolve_routing)
    # ------------------------------------------------------------------

    def _resolve_routing(
        self,
        org_id: UUID,
        request_type: Optional[str],
    ) -> tuple[TrWfDefinition, Optional[UUID], Optional[UUID]]:
        rules = (
            self.db.query(TrWfRoutingRule)
            .filter(
                TrWfRoutingRule.org_id == org_id,
                TrWfRoutingRule.is_active.is_(True),
            )
            .all()
        )

        def _matches(r: TrWfRoutingRule) -> bool:
            if r.request_type is not None and r.request_type != request_type:
                return False
            if r.equipment_type_id is not None:
                return False  # doc requests have no equipment_type
            if r.test_type_id is not None:
                return False
            return True

        def _specificity(r: TrWfRoutingRule) -> int:
            score = 0
            if r.request_type is not None:
                score += 4
            return score

        candidates = [r for r in rules if _matches(r)]
        best_rule = max(candidates, key=lambda r: (_specificity(r), r.priority)) if candidates else None

        defn: Optional[TrWfDefinition] = None
        if best_rule and best_rule.wf_definition_id:
            defn = (
                self.db.query(TrWfDefinition)
                .filter(
                    TrWfDefinition.id == best_rule.wf_definition_id,
                    TrWfDefinition.is_active.is_(True),
                )
                .first()
            )

        if not defn:
            # Also check definitions by request_type field directly
            defn = (
                self.db.query(TrWfDefinition)
                .filter(
                    TrWfDefinition.org_id == org_id,
                    TrWfDefinition.request_type == request_type,
                    TrWfDefinition.is_active.is_(True),
                )
                .first()
            )

        if not defn:
            default = (
                self.db.query(TrWfRoutingDefault)
                .filter(TrWfRoutingDefault.org_id == org_id)
                .first()
            )
            if default and default.wf_definition_id:
                defn = (
                    self.db.query(TrWfDefinition)
                    .filter(
                        TrWfDefinition.id == default.wf_definition_id,
                        TrWfDefinition.is_active.is_(True),
                    )
                    .first()
                )

        if not defn:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"No active workflow definition found for request_type='{request_type}' in org={org_id}.",
            )

        resolved_l3_role_id = (
            best_rule.override_role_id if (best_rule and best_rule.override_role_id)
            else defn.default_l3_role_id
        )
        resolved_tester_role_id = (
            best_rule.override_tester_role_id if (best_rule and best_rule.override_tester_role_id)
            else defn.default_tester_role_id
        )
        return defn, resolved_l3_role_id, resolved_tester_role_id

    # ------------------------------------------------------------------
    # Instantiate workflow
    # ------------------------------------------------------------------

    def instantiate_workflow(
        self,
        entity_id: UUID,
        performed_by_id: Optional[UUID],
    ) -> TrWfInstance:
        """
        Resolve routing → create TrWfInstance → open first stage.
        Updates entity.wf_instance_id and entity.current_status_code via adapter.
        Does NOT commit.
        """
        entity = self.adapter.get_entity(entity_id)

        if self.adapter.get_wf_instance_id(entity):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Entity {entity_id} already has a workflow instance.",
            )

        org_id = self.adapter.get_org_id(entity)
        request_type = self.adapter.get_request_type(entity)

        defn, resolved_l3_role_id, resolved_tester_role_id = self._resolve_routing(org_id, request_type)

        first_stage: Optional[TrWfStage] = (
            self.db.query(TrWfStage)
            .filter(
                TrWfStage.wf_definition_id == defn.id,
                TrWfStage.is_active.is_(True),
            )
            .order_by(TrWfStage.sequence)
            .first()
        )
        if not first_stage:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Workflow '{defn.name}' has no active stages configured.",
            )

        first_status_code = first_stage.status.status_code if first_stage.status else None

        instance = TrWfInstance(
            wf_definition_id=defn.id,
            entity_type=self.adapter.entity_type,
            entity_id=entity_id,
            org_id=org_id,
            current_stage_id=first_stage.id,
            current_status_code=first_status_code,
            status="active",
            resolved_l3_role_id=resolved_l3_role_id,
            resolved_tester_role_id=resolved_tester_role_id,
            created_by=performed_by_id,
            **self.adapter.build_wf_instance_kwargs(entity),
        )
        self.db.add(instance)
        self.db.flush()

        self.db.add(TrWfStageInstance(
            wf_instance_id=instance.id,
            stage_id=first_stage.id,
            status="in_progress",
            started_at=datetime.now(timezone.utc),
        ))

        self.db.add(TrWfAuditLog(
            wf_instance_id=instance.id,
            from_stage_id=None,
            to_stage_id=first_stage.id,
            action_code="create",
            performed_by=performed_by_id,
            from_status_code=None,
            to_status_code=first_status_code,
            is_send_back=False,
            is_terminal=False,
            **self.adapter.build_audit_log_kwargs(entity),
        ))

        self.adapter.link_wf_instance(entity, instance.id)
        self.adapter.update_status(entity, first_status_code)

        log.info("Workflow instantiated: entity_type=%s entity=%s wf=%s stage=%s",
                 self.adapter.entity_type, entity_id, defn.id, first_stage.id)
        return instance

    # ------------------------------------------------------------------
    # Advance stage
    # ------------------------------------------------------------------

    def advance_stage(
        self,
        entity_id: UUID,
        action_code: str,
        performed_by_id: Optional[UUID],
        role_id: Optional[UUID] = None,
        comment: Optional[str] = None,
        assigned_user_id: Optional[UUID] = None,
        assigned_role_id: Optional[UUID] = None,
    ) -> TrWfInstance:
        """Execute an action on the current stage. Does NOT commit."""
        entity = self.adapter.get_entity(entity_id)
        wf_instance_id = self.adapter.get_wf_instance_id(entity)

        instance: Optional[TrWfInstance] = (
            self.db.query(TrWfInstance).filter(TrWfInstance.id == wf_instance_id).first()
        )
        if not instance:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"No workflow instance found for entity {entity_id}.",
            )
        if instance.status != "active":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Workflow instance is already {instance.status}.",
            )

        current_stage_id = instance.current_stage_id
        transition: Optional[TrWfStageTransition] = (
            self.db.query(TrWfStageTransition)
            .filter(
                TrWfStageTransition.from_stage_id == current_stage_id,
                TrWfStageTransition.action_code == action_code,
            )
            .first()
        )
        if not transition:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Action '{action_code}' is not valid at the current stage.",
            )
        if transition.requires_comment and not comment:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Action '{action_code}' requires a comment.",
            )

        from_status_code = instance.current_status_code
        is_terminal = False
        to_stage: Optional[TrWfStage] = None

        if transition.to_stage_id:
            to_stage = (
                self.db.query(TrWfStage)
                .filter(TrWfStage.id == transition.to_stage_id)
                .first()
            )

        # Send-back rule: target stage with no roles → terminal
        if to_stage:
            active_roles = (
                self.db.query(func.count(TrWfStageRole.id))
                .filter(TrWfStageRole.stage_id == to_stage.id)
                .scalar()
            )
            if active_roles == 0:
                is_terminal = True
                to_stage = None
        else:
            is_terminal = True

        terminal_status_code: Optional[str] = None
        if is_terminal and transition.terminal_status_id:
            from models import TrWfStatus
            ts = self.db.query(TrWfStatus).filter(TrWfStatus.id == transition.terminal_status_id).first()
            if ts:
                terminal_status_code = ts.status_code

        # Close current stage instance
        cur_stage_inst: Optional[TrWfStageInstance] = (
            self.db.query(TrWfStageInstance)
            .filter(
                TrWfStageInstance.wf_instance_id == instance.id,
                TrWfStageInstance.stage_id == current_stage_id,
                TrWfStageInstance.status == "in_progress",
            )
            .order_by(TrWfStageInstance.created_at.desc())
            .first()
        )
        if cur_stage_inst:
            cur_stage_inst.status = "rejected" if transition.is_rejection else "completed"
            cur_stage_inst.action_taken = action_code
            cur_stage_inst.completed_at = datetime.now(timezone.utc)
            cur_stage_inst.completed_by = performed_by_id
            cur_stage_inst.comment = comment

        to_status_code: Optional[str] = None

        if is_terminal:
            instance.status = "terminated" if transition.is_rejection else "completed"
            instance.current_stage_id = None
            instance.current_status_code = terminal_status_code
            instance.completed_at = datetime.now(timezone.utc)
            to_status_code = terminal_status_code
        else:
            self.db.add(TrWfStageInstance(
                wf_instance_id=instance.id,
                stage_id=to_stage.id,
                status="in_progress",
                assigned_user_id=assigned_user_id,
                assigned_role_id=assigned_role_id,
                started_at=datetime.now(timezone.utc),
            ))
            next_status_code = to_stage.status.status_code if to_stage.status else None
            instance.current_stage_id = to_stage.id
            instance.current_status_code = next_status_code
            to_status_code = next_status_code

        cur_seq = (
            self.db.query(TrWfStage)
            .filter(TrWfStage.id == current_stage_id)
            .first()
        )
        is_send_back = (
            not is_terminal
            and to_stage is not None
            and cur_seq is not None
            and to_stage.sequence < cur_seq.sequence
        )

        self.db.add(TrWfAuditLog(
            wf_instance_id=instance.id,
            from_stage_id=current_stage_id,
            to_stage_id=to_stage.id if to_stage else None,
            action_code=action_code,
            performed_by=performed_by_id,
            role_id=role_id,
            from_status_code=from_status_code,
            to_status_code=to_status_code,
            comment=comment,
            is_send_back=is_send_back,
            is_terminal=is_terminal,
            **self.adapter.build_audit_log_kwargs(entity),
        ))

        self.adapter.update_status(entity, to_status_code)

        log.info(
            "Stage advanced: entity_type=%s entity=%s action=%s terminal=%s status=%s",
            self.adapter.entity_type, entity_id, action_code, is_terminal, to_status_code,
        )

        # ── Notification (entity_type-specific event prefix) ───────────────────
        try:
            from services.notification_service import NotificationService
            event_type = f"{self.adapter.entity_type.replace('_request', '')}_wf_status_changed"
            # e.g. "document_wf_status_changed" → normalise to "ds_wf_status_changed"
            _EVENT_MAP = {
                "document_wf_status_changed": "ds_wf_status_changed",
                "testing_wf_status_changed":  "tr_wf_status_changed",
            }
            event_type = _EVENT_MAP.get(event_type, event_type)

            status_name = (
                to_stage.status.status_name if to_stage and to_stage.status
                else (to_status_code or "Updated")
            )
            stage_name = to_stage.name if to_stage else ""
            title = getattr(entity, "title", None) or getattr(entity, "request_number", str(entity_id))

            # Collect stage role names for recipient targeting
            stage_role_names: list = []
            if to_stage:
                from models import TrWfStageRole as _SR
                for sr in self.db.query(_SR).filter(_SR.stage_id == to_stage.id).all():
                    if sr.role and sr.role.name:
                        stage_role_names.append(sr.role.name)

            NotificationService(self.db).fire(
                event_type=event_type,
                context={
                    "title":       title,
                    "status_name": status_name,
                    "stage_name":  stage_name,
                    "action_code": action_code,
                },
                organization_id=self.adapter.get_org_id(entity),
                source_id=entity_id,
                source_type=self.adapter.entity_type,
                status_from=from_status_code,
                status_to=to_status_code,
                recipient_roles_override=["@originator", "@assignee"] + stage_role_names,
            )
        except Exception as _n_err:
            log.warning("Generic WF notification failed (non-fatal): %s", _n_err)

        return instance

    # ------------------------------------------------------------------
    # Available actions
    # ------------------------------------------------------------------

    def get_available_actions(
        self,
        entity_id: UUID,
        user_role_ids: list[UUID],
    ) -> list[dict]:
        entity = self.adapter.get_entity(entity_id)
        wf_instance_id = self.adapter.get_wf_instance_id(entity)
        if not wf_instance_id:
            return []

        instance: Optional[TrWfInstance] = (
            self.db.query(TrWfInstance).filter(TrWfInstance.id == wf_instance_id).first()
        )
        if not instance or instance.status != "active" or not instance.current_stage_id:
            return []

        allowed_role = (
            self.db.query(TrWfStageRole)
            .filter(
                TrWfStageRole.stage_id == instance.current_stage_id,
                TrWfStageRole.role_id.in_(user_role_ids),
            )
            .first()
        )
        if not allowed_role:
            return []

        transitions = (
            self.db.query(TrWfStageTransition)
            .filter(TrWfStageTransition.from_stage_id == instance.current_stage_id)
            .all()
        )

        result = []
        for t in transitions:
            to_stage_name = None
            to_status_code = None
            if t.to_stage_id:
                ts = self.db.query(TrWfStage).filter(TrWfStage.id == t.to_stage_id).first()
                if ts:
                    to_stage_name = ts.name
                    if ts.status:
                        to_status_code = ts.status.status_code
            label = (t.label if hasattr(t, "label") and t.label else None) or \
                    t.action_code.replace("_", " ").title()
            result.append({
                "action_code": t.action_code,
                "label": label,
                "requires_comment": t.requires_comment,
                "is_rejection": t.is_rejection,
                "to_stage_id": str(t.to_stage_id) if t.to_stage_id else None,
                "to_stage_name": to_stage_name,
                "to_status_code": to_status_code,
            })
        return result
