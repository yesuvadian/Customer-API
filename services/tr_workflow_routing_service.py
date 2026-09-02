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
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    TestingRequest,
    TestRequestSchedule,
    TrWfDefinition,
    TrWfInstance,
    TrWfInstanceResolvedRole,
    TrWfStage,
    TrWfStageInstance,
    TrWfStageRole,
    TrWfStageTransition,
    TrWfStatus,
    TrWfRoutingDefault,
    TrWfRoutingRule,
    TrWfRoutingRuleRole,
    TrWfAuditLog,
    TestingRequestStatus,
)


def _rule_row_matches(r: TrWfRoutingRule, request_type, equipment_type_id, test_type_id) -> bool:
    if r.request_type is not None and r.request_type != request_type:
        return False
    if r.equipment_type_id is not None and r.equipment_type_id != equipment_type_id:
        return False
    if r.test_type_id is not None and r.test_type_id != test_type_id:
        return False
    return True


def _rule_row_specificity(r: TrWfRoutingRule) -> int:
    return (
        (4 if r.request_type is not None else 0)
        + (2 if r.equipment_type_id is not None else 0)
        + (1 if r.test_type_id is not None else 0)
    )


def stage_mapped_roles(
    db: Session,
    org_id,
    stage_id,
    request_type: Optional[str] = None,
    equipment_type_id: Optional[int] = None,
    test_type_id: Optional[int] = None,
) -> list:
    """
    Per-stage, stateless rule resolution at the MASTER level.

    A logical rule = TrWfRoutingRuleMaster (named) + its condition rows in
    tr_wf_routing_rules. A stage maps masters to its roles via
    tr_wf_routing_rule_roles(rule_master_id, stage_id, role_id). A master
    matches a request when ANY of its condition rows matches; the best
    master wins by (max matching row specificity, master priority). Returns
    that master's mapped role ids — or [] when nothing matches (stage stays
    open to its roles).
    """
    from models import TrWfRoutingRuleMaster
    rows = (
        db.query(TrWfRoutingRuleRole)
        .filter(TrWfRoutingRuleRole.stage_id == stage_id)
        .all()
    )
    if not rows:
        return []

    candidates = []

    # Master-level mappings (current model)
    by_master: dict = {}
    for rr in rows:
        if rr.rule_master_id:
            by_master.setdefault(rr.rule_master_id, []).append(rr.role_id)
    for master_id, role_ids in by_master.items():
        master = db.query(TrWfRoutingRuleMaster).filter(
            TrWfRoutingRuleMaster.id == master_id,
            TrWfRoutingRuleMaster.org_id == org_id,
            TrWfRoutingRuleMaster.is_active.is_(True),
        ).first()
        if not master:
            continue
        matching_specs = [
            _rule_row_specificity(row)
            for row in master.routing_rules
            if row.is_active and _rule_row_matches(row, request_type, equipment_type_id, test_type_id)
        ]
        if matching_specs:
            candidates.append((max(matching_specs), master.priority or 0, role_ids))

    # Legacy row-level mappings (pre-master data)
    for rr in rows:
        if rr.rule_master_id is None and rr.rule is not None:
            r = rr.rule
            if r.org_id == org_id and r.is_active and _rule_row_matches(
                    r, request_type, equipment_type_id, test_type_id):
                candidates.append((_rule_row_specificity(r), r.priority or 0, [rr.role_id]))

    if not candidates:
        return []
    best = max(candidates, key=lambda c: (c[0], c[1]))
    return [rid for rid in best[2] if rid]

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
        source_stage_id: Optional[UUID] = None,
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

        source_stage_id scopes which rules are even considered:
          - None (default) → only entry-point rules (source_stage_id IS NULL),
            same behavior as before this parameter existed.
          - A stage id → only rules scoped to that specific stage, so a
            deeper stage can independently bifurcate without its rules
            competing against the entry rule's matches.
        """
        rules_q = self.db.query(TrWfRoutingRule).filter(
            TrWfRoutingRule.org_id == org_id,
            TrWfRoutingRule.is_active.is_(True),
        )
        if source_stage_id is None:
            rules_q = rules_q.filter(TrWfRoutingRule.source_stage_id.is_(None))
        else:
            rules_q = rules_q.filter(TrWfRoutingRule.source_stage_id == source_stage_id)
        rules: list[TrWfRoutingRule] = rules_q.all()

        # Condition rows belong to a named master rule — a disabled master
        # disables all its rows; the master's priority is authoritative.
        rules = [
            r for r in rules
            if r.rule_master is None or r.rule_master.is_active
        ]

        def _priority(r: TrWfRoutingRule) -> int:
            if r.rule_master is not None and r.rule_master.priority is not None:
                return r.rule_master.priority
            return r.priority or 0

        _specificity = _rule_row_specificity

        def _matches(r: TrWfRoutingRule) -> bool:
            return _rule_row_matches(r, request_type, equipment_type_id, test_type_id)

        candidates = [r for r in rules if _matches(r)]
        best_rule: Optional[TrWfRoutingRule] = None
        if candidates:
            best_rule = max(candidates, key=lambda r: (_specificity(r), _priority(r)))

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

        # Legacy stored-resolution role list: only rule-GLOBAL rows
        # (stage_id NULL) participate — per-stage mapping rows are evaluated
        # statelessly at each stage (stage_mapped_roles) and must not leak
        # into the instance-level snapshot. Falls back to the 2 legacy
        # override fields for rules with no global rows.
        _global_role_ids = [
            rr.role_id for rr in (best_rule.rule_roles if best_rule else [])
            if rr.stage_id is None
        ]
        if _global_role_ids:
            resolved_role_ids = _global_role_ids
        else:
            resolved_role_ids = [
                rid for rid in (resolved_l3_role_id, resolved_tester_role_id) if rid
            ]

        return defn, resolved_l3_role_id, resolved_tester_role_id, resolved_role_ids

    def lookup_routing_rule(
        self,
        org_id: UUID,
        request_type: Optional[str],
        equipment_type_id: Optional[int],
        test_type_id: Optional[int],
    ) -> TrWfDefinition:
        """Backward-compat wrapper — returns only the definition."""
        defn, _, __, ___ = self.resolve_routing(org_id, request_type, equipment_type_id, test_type_id)
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

        defn, resolved_l3_role_id, resolved_tester_role_id, resolved_role_ids = self.resolve_routing(
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

        # Resolve status_code: prefer the stage's linked status; fall back to
        # the first active TrWfStatus for this definition (ordered by sequence).
        _stage_status_code = first_stage.status.status_code if first_stage.status else None
        if not _stage_status_code:
            _fallback_status = (
                self.db.query(TrWfStatus)
                .filter(
                    TrWfStatus.wf_definition_id == defn.id,
                    TrWfStatus.is_active.is_(True),
                )
                .order_by(TrWfStatus.sequence)
                .first()
            )
            _stage_status_code = _fallback_status.status_code if _fallback_status else None

        instance = TrWfInstance(
            wf_definition_id=defn.id,
            testing_request_id=testing_request.id,
            org_id=testing_request.organization_id,
            current_stage_id=first_stage.id,
            current_status_code=_stage_status_code,
            status="active",
            resolved_l3_role_id=resolved_l3_role_id,
            resolved_tester_role_id=resolved_tester_role_id,
            created_by=performed_by_id,
        )
        self.db.add(instance)
        self.db.flush()  # get instance.id

        for role_id in resolved_role_ids:
            self.db.add(TrWfInstanceResolvedRole(
                id=uuid.uuid4(),
                wf_instance_id=instance.id,
                role_id=role_id,
            ))

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
        overwrite_schedule_ids: Optional[list[str]] = None,
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
                is_terminal = True
                to_stage = None
        else:
            # Null to_stage → explicitly terminal
            is_terminal = True

        # Resolve terminal status code
        if is_terminal:
            if terminal_status_id:
                ts = self.db.query(TrWfStatus).filter(TrWfStatus.id == terminal_status_id).first()
                if ts:
                    terminal_status_code = ts.status_code
            if not terminal_status_code:
                # Fallback: last TrWfStatus (by sequence) for this definition
                _last = (
                    self.db.query(TrWfStatus)
                    .filter(TrWfStatus.wf_definition_id == instance.wf_definition_id)
                    .order_by(TrWfStatus.sequence.desc())
                    .first()
                )
                if _last:
                    terminal_status_code = _last.status_code

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

            # If this ticket was auto-generated from a one-off schedule (a
            # single ad-hoc test, not a recurring cadence), that schedule
            # was deliberately kept visible (deactivated but not deleted)
            # until this ticket's workflow actually closed. Retire it now.
            if testing_request.source_schedule_id:
                _src_sched = (
                    self.db.query(TestRequestSchedule)
                    .filter(
                        TestRequestSchedule.id == testing_request.source_schedule_id,
                        TestRequestSchedule.is_recurring.is_(False),
                        TestRequestSchedule.is_deleted.is_(False),
                    )
                    .first()
                )
                if _src_sched:
                    _src_sched.is_deleted = True
                    _src_sched.deleted_at = datetime.now(timezone.utc)
                    _src_sched.deleted_by = performed_by_id
        else:
            # If next stage has the @originator token role, auto-assign to the request creator
            effective_assigned_user_id = assigned_user_id
            has_originator_token = any(r.system_token == "@originator" for r in to_stage.roles)
            if has_originator_token and testing_request.originator_id:
                effective_assigned_user_id = testing_request.originator_id

            # Open next stage
            new_stage_inst = TrWfStageInstance(
                wf_instance_id=instance.id,
                stage_id=to_stage.id,
                status="in_progress",
                assigned_user_id=effective_assigned_user_id,
                assigned_role_id=assigned_role_id,
                started_at=datetime.now(timezone.utc),
            )
            self.db.add(new_stage_inst)

            next_status_code = to_stage.status.status_code if to_stage.status else None
            if not next_status_code:
                # Stage has no status linked — fall back to WF definition's next status by sequence
                _cur_seq = (
                    self.db.query(TrWfStage.sequence)
                    .filter(TrWfStage.id == current_stage_id)
                    .scalar() or 0
                )
                _next_status = (
                    self.db.query(TrWfStatus)
                    .filter(
                        TrWfStatus.wf_definition_id == instance.wf_definition_id,
                        TrWfStatus.is_active.is_(True),
                        TrWfStatus.sequence > _cur_seq,
                    )
                    .order_by(TrWfStatus.sequence)
                    .first()
                )
                next_status_code = _next_status.status_code if _next_status else None
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
                    "overwrite_schedule_ids": overwrite_schedule_ids,
                },
            )

        # ── Notification ───────────────────────────────────────────────────
        # Fire the appropriate notification for every stage transition.
        # Rejection → request_rejected (has templates, notifies originator).
        # All other transitions → notify_tr_wf_stage_changed (stage-advance event).
        try:
            from services.notification_service import NotificationService
            _notif = NotificationService(self.db)

            # Resolve performer display name for context
            _performer_name = ""
            if performed_by_id:
                from models import User as _User
                _actor = self.db.query(_User).filter(_User.id == performed_by_id).first()
                if _actor:
                    _performer_name = (
                        f"{_actor.firstname or ''} {_actor.lastname or ''}".strip()
                        or _actor.email or ""
                    )

            if transition.is_rejection:
                _notif.notify_request_rejected(
                    testing_request,
                    rejected_by=_performer_name,
                    reason=comment or "",
                )
            else:
                # Collect next-stage role names so those users are notified
                stage_role_names: list = []
                if to_stage:
                    _stage_roles = (
                        self.db.query(TrWfStageRole)
                        .filter(TrWfStageRole.stage_id == to_stage.id)
                        .all()
                    )
                    for sr in _stage_roles:
                        if sr.role and sr.role.name:
                            stage_role_names.append(sr.role.name)

                recipient_roles = ["@originator", "@assignee"] + stage_role_names

                _notif.notify_tr_wf_stage_changed(
                    testing_request,
                    action_code=action_code,
                    stage_name=to_stage.name if to_stage else "",
                    status_code=to_status_code,
                    performed_by=_performer_name,
                    comment=comment,
                    is_terminal=is_terminal,
                    from_status_code=from_status_code,
                    recipient_roles_override=recipient_roles,
                )
        except Exception as _n_err:  # never let notification failure kill the workflow
            log.warning("TR-WF notification failed (non-fatal): %s", _n_err)

        # ── Terminal: close the TestingRequest ─────────────────────────────
        # When the WF instance reaches a terminal state, sync the TR status.
        # For non-rejection terminals (complete/close) also auto-dispatch any
        # pending recommendation so that follow-up actions (schedules, etc.) fire.
        if is_terminal:
            from models import TestingRequestStatus as _TRS, Recommendation as _Rec
            from datetime import datetime as _dt, timezone as _tz
            if transition.is_rejection:
                testing_request.status = _TRS.rejected
                testing_request.completed_at = _dt.now(_tz.utc)
            else:
                # Check for pending recommendation → dispatch (handles outcome)
                rec = (
                    self.db.query(_Rec)
                    .filter(_Rec.testing_request_id == testing_request.id)
                    .order_by(_Rec.cts.desc())
                    .first()
                )
                if rec and rec.approval_status == "pending":
                    rec.approval_status = "approved"
                    rec.approved_by = performed_by_id
                    rec.approved_at = _dt.now(_tz.utc)
                    self.db.flush()
                    try:
                        from services.workflow_dispatch_service import WorkflowDispatchService
                        WorkflowDispatchService(self.db).dispatch(
                            testing_request, rec, performed_by_id,
                            overwrite_schedule_ids=overwrite_schedule_ids,
                        )
                    except Exception as _de:
                        log.warning("Dispatch after terminal action failed (non-fatal): %s", _de)
                        testing_request.status = _TRS.closed
                        testing_request.completed_at = _dt.now(_tz.utc)
                else:
                    testing_request.status = _TRS.closed
                    testing_request.completed_at = _dt.now(_tz.utc)

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
        self.instantiate_workflow(child, performed_by_id=performed_by_id)

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
        caller_user_id: Optional[UUID] = None,
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
            # Generic: if the active stage instance is assigned to this user, allow actions.
            if caller_user_id:
                active_si = (
                    self.db.query(TrWfStageInstance)
                    .filter(
                        TrWfStageInstance.wf_instance_id == instance.id,
                        TrWfStageInstance.stage_id == current_stage_id,
                        TrWfStageInstance.status == "in_progress",
                        TrWfStageInstance.assigned_user_id == caller_user_id,
                    )
                    .first()
                )
                if active_si:
                    pass  # allowed — fall through to return transitions
                else:
                    # Also allow if user has can_act_as_tester on any stage of this workflow
                    can_act = (
                        self.db.query(TrWfStageRole)
                        .join(TrWfStage, TrWfStageRole.stage_id == TrWfStage.id)
                        .filter(
                            TrWfStageRole.role_id.in_(user_role_ids),
                            TrWfStageRole.can_act_as_tester.is_(True),
                            TrWfStage.wf_definition_id == (
                                self.db.query(TrWfStage.wf_definition_id)
                                .filter(TrWfStage.id == current_stage_id)
                                .scalar_subquery()
                            ),
                        )
                        .first()
                    )
                    if not can_act:
                        return []
            else:
                # Also allow if user has can_act_as_tester on any stage of this workflow
                can_act = (
                    self.db.query(TrWfStageRole)
                    .join(TrWfStage, TrWfStageRole.stage_id == TrWfStage.id)
                    .filter(
                        TrWfStageRole.role_id.in_(user_role_ids),
                        TrWfStageRole.can_act_as_tester.is_(True),
                        TrWfStage.wf_definition_id == (
                            self.db.query(TrWfStage.wf_definition_id)
                            .filter(TrWfStage.id == current_stage_id)
                            .scalar_subquery()
                        ),
                    )
                    .first()
                )
                if not can_act:
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

            # Same terminal check advance_stage() actually uses at commit
            # time: no to_stage_id, or a to_stage with zero assignable
            # roles, both mean this action closes/dispatches the request
            # rather than moving it to another stage. Computed live from
            # the current routing config, so it stays correct as stages
            # are added or removed — never hardcode a specific stage name.
            is_terminal = True
            if t.to_stage_id and to_stage:
                active_roles = (
                    self.db.query(func.count(TrWfStageRole.id))
                    .filter(TrWfStageRole.stage_id == to_stage.id)
                    .scalar()
                )
                is_terminal = active_roles == 0

            # Prefer the transition's custom label; fall back to the action-code map.
            display_label = (
                t.label.strip()
                if t.label and t.label.strip()
                else ACTION_CODE_LABELS.get(t.action_code, t.action_code.replace("_", " ").title())
            )
            result.append({
                "action_code": t.action_code,
                "label": display_label,
                "requires_comment": t.requires_comment,
                "is_rejection": t.is_rejection,
                "to_stage_id": t.to_stage_id,
                "to_stage_name": to_stage_name,
                "to_status_code": to_status_code,
                "is_terminal": is_terminal,
            })
        return result
