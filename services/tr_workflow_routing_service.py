"""
Test Request Configurable Workflow Routing Service (tr_wf_*)

Responsibilities:
  - lookup_routing_rule(): find the best-matching TrWfDefinition for a request
  - instantiate_workflow(): create TrWfInstance + first TrWfStageInstance on L2 approve
  - advance_stage(): move instance to next stage, write audit log, apply terminal_status
  - send-back rule: if target stage has zero active stage-roles → apply terminal_status_id
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
    TestingRequest,
    TrWfDefinition,
    TrWfInstance,
    TrWfStage,
    TrWfStageInstance,
    TrWfStageRole,
    TrWfStageTransition,
    TrWfRoutingDefault,
    TrWfRoutingRule,
    TrWfAuditLog,
    TestingRequestStatus,
)

log = logging.getLogger(__name__)

# Canonical map of all action codes the engine understands.
# Exposed via GET /tr-workflow-config/options/action-codes so the UI
# never has to hardcode this list.
ACTION_CODE_LABELS: dict[str, str] = {
    "approve":      "Approve",
    "reject":       "Reject",
    "assign":       "Assign",
    "return":       "Return",
    "cancel":       "Cancel",
    "complete":     "Complete",
    "close":        "Close",
    "create_child": "Create Sub-Request",
    "reassign":     "Reassign",
}


class WorkflowConfigError(HTTPException):
    """Raised when no workflow definition can be resolved for a request."""

    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail
        )


class WorkflowRoutingService:
    """
    Core engine for the tr_wf_* workflow system.
    All public methods are transactional — call db.commit() in the caller.
    """

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # 1. Routing lookup
    # ------------------------------------------------------------------

    def resolve_routing(
        self,
        org_id: UUID,
        request_type: Optional[str],
        equipment_type_id: Optional[int],
        test_type_id: Optional[int],
    ) -> tuple[TrWfDefinition, Optional[UUID]]:
        """
        Return (TrWfDefinition, resolved_l3_role_id) for a request.

        Role resolution:
          1. Best-matching routing rule with override_role_id set → use that role
          2. Best-matching routing rule with wf_definition_id → use that definition's default_l3_role_id
          3. Org routing default definition → use its default_l3_role_id
          If no role found at any step, resolved_l3_role_id is None (L3 shows all eligible roles).

        Definition resolution:
          1. Best-matching rule with wf_definition_id → that definition
          2. Org routing default definition
          Raises WorkflowConfigError if no definition found.

        Specificity: request_type+equip+test > equip+test > request_type > all-NULL.
        Priority breaks ties at equal specificity.
        """
        rules: list[TrWfRoutingRule] = (
            self.db.query(TrWfRoutingRule)
            .filter(
                TrWfRoutingRule.org_id == org_id,
                TrWfRoutingRule.is_active.is_(True),
            )
            .all()
        )

        def _specificity(r: TrWfRoutingRule) -> int:
            score = 0
            if r.request_type is not None:
                score += 4
            if r.equipment_type_id is not None:
                score += 2
            if r.test_type_id is not None:
                score += 1
            return score

        def _matches(r: TrWfRoutingRule) -> bool:
            if r.request_type is not None and r.request_type != request_type:
                return False
            if r.equipment_type_id is not None and r.equipment_type_id != equipment_type_id:
                return False
            if r.test_type_id is not None and r.test_type_id != test_type_id:
                return False
            return True

        candidates = [r for r in rules if _matches(r)]
        best_rule: Optional[TrWfRoutingRule] = None
        if candidates:
            best_rule = max(candidates, key=lambda r: (_specificity(r), r.priority))

        # Resolve definition
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
            raise WorkflowConfigError(
                f"No active workflow definition found for org={org_id}, "
                f"request_type={request_type}, equipment_type={equipment_type_id}, "
                f"test_type={test_type_id}. Configure routing rules or a default."
            )

        # Resolve L3 role: override_role_id on rule wins, else definition default
        resolved_l3_role_id: Optional[UUID] = None
        if best_rule and best_rule.override_role_id:
            resolved_l3_role_id = best_rule.override_role_id
        elif defn.default_l3_role_id:
            resolved_l3_role_id = defn.default_l3_role_id

        # Resolve tester role: override_tester_role_id on rule wins, else definition default
        resolved_tester_role_id: Optional[UUID] = None
        if best_rule and best_rule.override_tester_role_id:
            resolved_tester_role_id = best_rule.override_tester_role_id
        elif defn.default_tester_role_id:
            resolved_tester_role_id = defn.default_tester_role_id

        return defn, resolved_l3_role_id, resolved_tester_role_id

    def lookup_routing_rule(
        self,
        org_id: UUID,
        request_type: Optional[str],
        equipment_type_id: Optional[int],
        test_type_id: Optional[int],
    ) -> TrWfDefinition:
        """Backward-compat wrapper — returns only the definition."""
        defn, _, __ = self.resolve_routing(org_id, request_type, equipment_type_id, test_type_id)
        return defn

    # ------------------------------------------------------------------
    # 2. Instantiate workflow (called on L2 approve)
    # ------------------------------------------------------------------

    def instantiate_workflow(
        self,
        testing_request: TestingRequest,
        performed_by_id: Optional[UUID],
    ) -> TrWfInstance:
        """
        Resolve routing → create TrWfInstance → open first stage.
        Updates testing_request.wf_instance_id, current_wf_stage_id, current_status_code.
        Does NOT commit — caller commits.
        """
        if testing_request.wf_instance_id:
            raise WorkflowConfigError(
                f"Request {testing_request.id} already has a workflow instance."
            )

        defn, resolved_l3_role_id, resolved_tester_role_id = self.resolve_routing(
            org_id=testing_request.organization_id,
            request_type=testing_request.request_type,
            equipment_type_id=testing_request.equipment_type_id,
            test_type_id=testing_request.test_type_id,
        )

        # First active stage by sequence
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
            raise WorkflowConfigError(
                f"Workflow '{defn.name}' has no active stages configured."
            )

        instance = TrWfInstance(
            wf_definition_id=defn.id,
            testing_request_id=testing_request.id,
            org_id=testing_request.organization_id,
            current_stage_id=first_stage.id,
            current_status_code=first_stage.status.status_code if first_stage.status else None,
            status="active",
            resolved_l3_role_id=resolved_l3_role_id,
            resolved_tester_role_id=resolved_tester_role_id,
            created_by=performed_by_id,
        )
        self.db.add(instance)
        self.db.flush()  # get instance.id

        stage_inst = TrWfStageInstance(
            wf_instance_id=instance.id,
            stage_id=first_stage.id,
            status="in_progress",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(stage_inst)

        # Audit: workflow created / first stage opened
        self.db.add(TrWfAuditLog(
            wf_instance_id=instance.id,
            testing_request_id=testing_request.id,
            from_stage_id=None,
            to_stage_id=first_stage.id,
            action_code="create",
            performed_by=performed_by_id,
            from_status_code=None,
            to_status_code=instance.current_status_code,
            is_send_back=False,
            is_terminal=False,
        ))

        # Denormalize onto TestingRequest
        testing_request.wf_instance_id = instance.id
        testing_request.current_wf_stage_id = first_stage.id
        testing_request.current_status_code = instance.current_status_code

        log.info(
            "Workflow instantiated: request=%s wf=%s stage=%s",
            testing_request.id, defn.id, first_stage.id,
        )
        return instance

    # ------------------------------------------------------------------
    # 3. Advance stage
    # ------------------------------------------------------------------

    def advance_stage(
        self,
        testing_request: TestingRequest,
        action_code: str,
        performed_by_id: Optional[UUID],
        role_id: Optional[UUID] = None,
        comment: Optional[str] = None,
        assigned_user_id: Optional[UUID] = None,
        assigned_role_id: Optional[UUID] = None,
    ) -> TrWfInstance:
        """
        Execute an action on the current stage of a workflow instance.

        Send-back rule: if transition.to_stage_id has zero active TrWfStageRole rows
        → treat as terminal, apply transition.terminal_status_id.

        Does NOT commit — caller commits.
        """
        instance: Optional[TrWfInstance] = (
            self.db.query(TrWfInstance)
            .filter(TrWfInstance.id == testing_request.wf_instance_id)
            .first()
        )
        if not instance:
            raise WorkflowConfigError(
                f"No workflow instance found for request {testing_request.id}."
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
        terminal_status_code: Optional[str] = None

        # Resolve target
        to_stage: Optional[TrWfStage] = None
        if transition.to_stage_id:
            to_stage = (
                self.db.query(TrWfStage)
                .filter(TrWfStage.id == transition.to_stage_id)
                .first()
            )

        # Send-back / terminal check
        terminal_status_id = transition.terminal_status_id
        if to_stage:
            active_roles = (
                self.db.query(func.count(TrWfStageRole.id))
                .filter(TrWfStageRole.stage_id == to_stage.id)
                .scalar()
            )
            if active_roles == 0:
                # Send-back to a stage with no roles → terminate
                is_terminal = True
                to_stage = None
        else:
            # Null to_stage → explicitly terminal
            is_terminal = True

        # Resolve terminal status code
        if is_terminal and terminal_status_id:
            from models import TrWfStatus
            ts = self.db.query(TrWfStatus).filter(TrWfStatus.id == terminal_status_id).first()
            if ts:
                terminal_status_code = ts.status_code

        # Close current stage instance
        current_stage_inst: Optional[TrWfStageInstance] = (
            self.db.query(TrWfStageInstance)
            .filter(
                TrWfStageInstance.wf_instance_id == instance.id,
                TrWfStageInstance.stage_id == current_stage_id,
                TrWfStageInstance.status == "in_progress",
            )
            .order_by(TrWfStageInstance.created_at.desc())
            .first()
        )
        if current_stage_inst:
            current_stage_inst.status = "rejected" if transition.is_rejection else "completed"
            current_stage_inst.action_taken = action_code
            current_stage_inst.completed_at = datetime.now(timezone.utc)
            current_stage_inst.completed_by = performed_by_id
            current_stage_inst.comment = comment

        to_status_code: Optional[str] = None

        if is_terminal:
            instance.status = "terminated" if transition.is_rejection else "completed"
            instance.current_stage_id = None
            instance.current_status_code = terminal_status_code
            instance.completed_at = datetime.now(timezone.utc)
            to_status_code = terminal_status_code
        else:
            # Open next stage
            new_stage_inst = TrWfStageInstance(
                wf_instance_id=instance.id,
                stage_id=to_stage.id,
                status="in_progress",
                assigned_user_id=assigned_user_id,
                assigned_role_id=assigned_role_id,
                started_at=datetime.now(timezone.utc),
            )
            self.db.add(new_stage_inst)

            next_status_code = (
                to_stage.status.status_code if to_stage.status else None
            )
            instance.current_stage_id = to_stage.id
            instance.current_status_code = next_status_code
            to_status_code = next_status_code

        # Audit log
        is_send_back = (
            to_stage is not None
            and transition.to_stage_id is not None
            and to_stage.sequence < (
                self.db.query(TrWfStage)
                .filter(TrWfStage.id == current_stage_id)
                .first()
                .sequence
            )
        ) if not is_terminal else False

        self.db.add(TrWfAuditLog(
            wf_instance_id=instance.id,
            testing_request_id=testing_request.id,
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
        ))

        # Denormalize onto TestingRequest
        testing_request.current_wf_stage_id = instance.current_stage_id
        testing_request.current_status_code = instance.current_status_code

        log.info(
            "Stage advanced: request=%s action=%s terminal=%s to_stage=%s status=%s",
            testing_request.id, action_code, is_terminal,
            to_stage.id if to_stage else None, to_status_code,
        )

        # ── Post-transition action (reflection-discovered registry) ────────────
        if transition.post_action:
            from services.tr_wf_post_actions import dispatch as _dispatch
            _dispatch(
                transition.post_action,
                self.db,
                testing_request,
                {
                    "action_code": action_code,
                    "performed_by_id": performed_by_id,
                    "role_id": role_id,
                    "comment": comment,
                    "is_terminal": is_terminal,
                    "to_status_code": to_status_code,
                },
            )

        # ── Notification ───────────────────────────────────────────────────
        # Single tr_wf_status_changed event covers every stage transition.
        # Recipients: @originator always + @assignee if set + active stage roles.
        try:
            from services.notification_service import NotificationService

            # Resolve human-readable status name from dynamic TrWfStatus row
            status_name = (
                to_stage.status.status_name
                if to_stage and to_stage.status
                else (to_status_code or "Updated")
            )
            equipment_label = (
                getattr(testing_request.equipment, "ueic", None)
                or (testing_request.equipment_type.name if testing_request.equipment_type else "Equipment")
            )

            # Collect active stage role names for the destination stage so those
            # users are also notified (AEE R&D at L3, AE tester at L4, etc.)
            stage_role_names: list = []
            if to_stage:
                stage_roles = (
                    self.db.query(TrWfStageRole)
                    .filter(TrWfStageRole.stage_id == to_stage.id)
                    .all()
                )
                for sr in stage_roles:
                    if sr.role and sr.role.name:
                        stage_role_names.append(sr.role.name)

            recipient_roles = ["@originator", "@assignee"] + stage_role_names

            NotificationService(self.db).fire(
                event_type="tr_wf_status_changed",
                context={
                    "request_number": getattr(testing_request, "request_number", ""),
                    "equipment":      equipment_label,
                    "status_name":    status_name,
                    "stage_name":     to_stage.name if to_stage else "",
                    "action_code":    action_code,
                },
                organization_id=testing_request.organization_id,
                department_id=getattr(testing_request, "department_id", None),
                source_id=testing_request.id,
                source_type="testing_request",
                status_from=from_status_code,
                status_to=to_status_code,
                recipient_roles_override=recipient_roles,
            )
        except Exception as _n_err:  # never let notification failure kill the workflow
            log.warning("TR-WF notification failed (non-fatal): %s", _n_err)

        return instance

    # ------------------------------------------------------------------
    # 3b. Create child request (create_child action)
    # ------------------------------------------------------------------

    def create_child_request(
        self,
        parent_request: "TestingRequest",
        performed_by_id: Optional[UUID],
        comment: Optional[str] = None,
    ) -> "TestingRequest":
        """
        Spawn a child testing request from a parent, linked via parent_request_id.
        The child inherits equipment_type, test_type, organization, department,
        and request_type from the parent. Its own workflow is then instantiated
        separately (caller calls instantiate_workflow on the child).

        Does NOT commit — caller commits.
        """
        import uuid as _uuid

        child = TestingRequest(
            id=_uuid.uuid4(),
            organization_id=parent_request.organization_id,
            department_id=parent_request.department_id,
            equipment_type_id=parent_request.equipment_type_id,
            test_type_id=parent_request.test_type_id,
            request_type=parent_request.request_type,
            parent_request_id=parent_request.id,
            status=parent_request.__class__.__mro__[0].__dict__.get(
                "status", None
            ),  # will be set below
            originator_id=performed_by_id,
        )
        # Set to submitted so L2 routing picks it up
        from models import TestingRequestStatus
        child.status = TestingRequestStatus.submitted
        self.db.add(child)
        self.db.flush()

        self.db.add(TrWfAuditLog(
            wf_instance_id=None,
            testing_request_id=parent_request.id,
            from_stage_id=None,
            to_stage_id=None,
            action_code="create_child",
            performed_by=performed_by_id,
            from_status_code=parent_request.current_status_code,
            to_status_code=None,
            comment=comment or f"Child request created: {child.id}",
            is_send_back=False,
            is_terminal=False,
        ))

        return child

    # ------------------------------------------------------------------
    # 4. Available actions for current user at current stage
    # ------------------------------------------------------------------

    def get_available_actions(
        self,
        testing_request: TestingRequest,
        user_role_ids: list[UUID],
    ) -> list[dict]:
        """
        Return allowed transitions for the current stage filtered by the
        caller's roles (must have can_approve or can_assign on the stage).
        """
        if not testing_request.wf_instance_id:
            return []

        instance: Optional[TrWfInstance] = (
            self.db.query(TrWfInstance)
            .filter(TrWfInstance.id == testing_request.wf_instance_id)
            .first()
        )
        if not instance or instance.status != "active":
            return []

        current_stage_id = instance.current_stage_id
        if not current_stage_id:
            return []

        # Check caller has a role at this stage
        allowed_role = (
            self.db.query(TrWfStageRole)
            .filter(
                TrWfStageRole.stage_id == current_stage_id,
                TrWfStageRole.role_id.in_(user_role_ids),
            )
            .first()
        )
        if not allowed_role:
            return []

        transitions: list[TrWfStageTransition] = (
            self.db.query(TrWfStageTransition)
            .filter(TrWfStageTransition.from_stage_id == current_stage_id)
            .all()
        )

        result = []
        for t in transitions:
            to_stage: Optional[TrWfStage] = None
            to_stage_name: Optional[str] = None
            to_status_code: Optional[str] = None

            if t.to_stage_id:
                to_stage = (
                    self.db.query(TrWfStage)
                    .filter(TrWfStage.id == t.to_stage_id)
                    .first()
                )
                if to_stage:
                    to_stage_name = to_stage.name
                    if to_stage.status:
                        to_status_code = to_stage.status.status_code

            result.append({
                "action_code": t.action_code,
                "label": ACTION_CODE_LABELS.get(t.action_code, t.action_code.replace("_", " ").title()),
                "requires_comment": t.requires_comment,
                "is_rejection": t.is_rejection,
                "to_stage_id": t.to_stage_id,
                "to_stage_name": to_stage_name,
                "to_status_code": to_status_code,
            })
        return result
