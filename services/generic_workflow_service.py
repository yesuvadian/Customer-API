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
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    TrWfDefinition,
    TrWfInstance,
    TrWfInstanceResolvedRole,
    TrWfStage,
    TrWfStageInstance,
    TrWfStageRole,
    TrWfStageTransition,
    TrWfRoutingDefault,
    TrWfRoutingRule,
    TrWfAuditLog,
    OrgUserRole,
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
        source_stage_id: Optional[UUID] = None,
    ) -> tuple[TrWfDefinition, Optional[UUID], Optional[UUID], list[UUID]]:
        # source_stage_id scopes which rules are considered, mirroring
        # WorkflowRoutingService.resolve_routing:
        #   None → entry-point rules only (source_stage_id IS NULL) — stage-
        #   scoped rules belong to a specific stage's re-routing and must
        #   not leak into entity-level resolution.
        #   A stage id → only that stage's own rules (deeper bifurcation).
        rules_q = self.db.query(TrWfRoutingRule).filter(
            TrWfRoutingRule.org_id == org_id,
            TrWfRoutingRule.is_active.is_(True),
        )
        if source_stage_id is None:
            rules_q = rules_q.filter(TrWfRoutingRule.source_stage_id.is_(None))
        else:
            rules_q = rules_q.filter(TrWfRoutingRule.source_stage_id == source_stage_id)
        rules = rules_q.all()
        # A disabled master rule disables all its condition rows
        rules = [r for r in rules if r.rule_master is None or r.rule_master.is_active]

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

        # Legacy stored-resolution role list: only rule-GLOBAL rows
        # (stage_id NULL) — per-stage mapping rows are evaluated statelessly
        # at each stage (stage_mapped_roles) and must not leak in here.
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

        defn, resolved_l3_role_id, resolved_tester_role_id, resolved_role_ids = self._resolve_routing(org_id, request_type)

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

        for _role_id in resolved_role_ids:
            self.db.add(TrWfInstanceResolvedRole(
                id=uuid.uuid4(),
                wf_instance_id=instance.id,
                role_id=_role_id,
            ))

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

        # Derived re-routing (mirrors the TR path): when an 'approve' fires
        # on a stage that has its own scoped rules, re-resolve and replace
        # the instance's resolved roles — a deeper bifurcation point. No
        # stage flag involved; stages without scoped rules just advance.
        if action_code == "approve" and not transition.is_rejection:
            org_id = self.adapter.get_org_id(entity)
            has_scoped_rules = (
                self.db.query(TrWfRoutingRule)
                .filter(
                    TrWfRoutingRule.org_id == org_id,
                    TrWfRoutingRule.is_active.is_(True),
                    TrWfRoutingRule.source_stage_id == current_stage_id,
                )
                .first() is not None
            )
            if has_scoped_rules:
                _defn, _l3, _tester, _role_ids = self._resolve_routing(
                    org_id,
                    self.adapter.get_request_type(entity),
                    source_stage_id=current_stage_id,
                )
                instance.resolved_l3_role_id = _l3
                instance.resolved_tester_role_id = _tester
                # Replace (not accumulate): only the latest resolution
                # grants visibility, not roles from an earlier, passed stage.
                self.db.query(TrWfInstanceResolvedRole).filter(
                    TrWfInstanceResolvedRole.wf_instance_id == instance.id
                ).delete()
                for _role_id in _role_ids:
                    self.db.add(TrWfInstanceResolvedRole(
                        id=uuid.uuid4(),
                        wf_instance_id=instance.id,
                        role_id=_role_id,
                    ))

        from_status_code = instance.current_status_code
        is_terminal = False
        to_stage: Optional[TrWfStage] = None

        if transition.to_stage_id:
            to_stage = (
                self.db.query(TrWfStage)
                .filter(TrWfStage.id == transition.to_stage_id)
                .first()
            )

        # A stage with no role rows but with outgoing transitions is an originator/open stage —
        # do NOT skip it. Only treat as terminal when transition has no to_stage_id.
        if not to_stage:
            is_terminal = True

        terminal_status_code: Optional[str] = None
        if is_terminal and transition.terminal_status_id:
            from models import TrWfStatus
            ts = self.db.query(TrWfStatus).filter(TrWfStatus.id == transition.terminal_status_id).first()
            if ts:
                terminal_status_code = ts.status_code

                # Only Reject should become Rejected.
                # Cancel should remain Cancelled.
                if (
                    self.adapter.entity_type == "document_request"
                    and action_code.lower() == "reject"
                ):
                    terminal_status_code = "ds_rejected"

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
        user_id: Optional[UUID] = None,
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

        # Overrides that always grant action visibility, evaluated BEFORE
        # routing-rule scoping below — otherwise an approver, the assigned
        # user, or a tester delegate whose role isn't the rule-resolved one
        # for this stage would get excluded before these ever run.
        # 1) Approvers/reviewers always act on their stage.
        caller_can_approve = self.db.query(TrWfStageRole).filter(
            TrWfStageRole.stage_id == instance.current_stage_id,
            TrWfStageRole.role_id.in_(user_role_ids or []),
            TrWfStageRole.can_approve.is_(True),
        ).first() is not None

        # 2) The user this stage instance is assigned to.
        assigned_to_caller = False
        if user_id:
            active_si = (
                self.db.query(TrWfStageInstance)
                .filter(
                    TrWfStageInstance.wf_instance_id == instance.id,
                    TrWfStageInstance.stage_id == instance.current_stage_id,
                    TrWfStageInstance.status == "in_progress",
                    TrWfStageInstance.assigned_user_id == user_id,
                )
                .first()
            )
            assigned_to_caller = active_si is not None

        # 3) Callers whose role has can_act_as_tester on ANY stage of this
        # workflow definition can act on behalf of the assigned user,
        # regardless of which stage their own act_as_tester flag is on.
        caller_is_workflow_tester = self.db.query(TrWfStageRole).join(
            TrWfStage, TrWfStageRole.stage_id == TrWfStage.id
        ).filter(
            TrWfStageRole.role_id.in_(user_role_ids or []),
            TrWfStageRole.can_act_as_tester.is_(True),
            TrWfStage.wf_definition_id == instance.wf_definition_id,
        ).first() is not None

        bypass_rule_scoping = caller_can_approve or assigned_to_caller or caller_is_workflow_tester

        if not bypass_rule_scoping:
            # Role scoping — per-stage, stateless: evaluate the rules MAPPED to
            # this stage against the entity's attributes; a matching mapped
            # rule's roles are the only ones who may act here. Falls back to
            # the stored instance resolution (legacy data), then open.
            from services.tr_workflow_routing_service import stage_mapped_roles
            mapped_role_ids = stage_mapped_roles(
                self.db,
                self.adapter.get_org_id(entity),
                instance.current_stage_id,
                request_type=self.adapter.get_request_type(entity),
                equipment_type_id=getattr(entity, "equipment_type_id", None),
                test_type_id=getattr(entity, "test_type_id", None),
            )
            if mapped_role_ids:
                if not (set(mapped_role_ids) & set(user_role_ids or [])):
                    return []
            else:
                resolved_role_ids = {l.role_id for l in instance.resolved_role_links}
                if not resolved_role_ids:
                    _legacy = instance.resolved_l3_role_id or instance.resolved_tester_role_id
                    if _legacy:
                        resolved_role_ids = {_legacy}
                if resolved_role_ids:
                    stage_role_ids = {
                        sr.role_id
                        for sr in self.db.query(TrWfStageRole)
                        .filter(TrWfStageRole.stage_id == instance.current_stage_id)
                        .all()
                        if sr.role_id
                    }
                    if stage_role_ids & resolved_role_ids:
                        if not (resolved_role_ids & set(user_role_ids or [])):
                            return []

        allowed_role = (
            self.db.query(TrWfStageRole)
            .filter(
                TrWfStageRole.stage_id == instance.current_stage_id,
                TrWfStageRole.role_id.in_(user_role_ids),
            )
            .first()
        ) if user_role_ids else None

        # If no role match, check if the stage is an originator-review stage
        # (no TrWfStageRole rows configured). In that case, allow anyone who
        # shares any org role with the originator — not just the exact submitter.
        # If TrWfStageRole rows exist, those take precedence (workflow config override).
        is_originator_role = False
        if not allowed_role and user_id:
            stage_has_roles = (
                self.db.query(TrWfStageRole)
                .filter(TrWfStageRole.stage_id == instance.current_stage_id)
                .first()
            )
            if not stage_has_roles:
                submitted_by = self.adapter.get_submitted_by(entity)
                if submitted_by:
                    originator_role_ids = {
                        row.org_role_id
                        for row in self.db.query(OrgUserRole).filter(
                            OrgUserRole.user_id == submitted_by,
                            OrgUserRole.is_active.is_(True),
                        ).all()
                    }
                    if originator_role_ids and set(user_role_ids or []) & originator_role_ids:
                        is_originator_role = True

        if (
            not allowed_role
            and not is_originator_role
            and not assigned_to_caller
            and not caller_is_workflow_tester
        ):
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
                "requires_user_assignment": (
                    bool(allowed_role.can_assign) and "assign" in t.action_code.lower()
                ) if allowed_role else False,
                "is_rejection": t.is_rejection,
                "to_stage_id": str(t.to_stage_id) if t.to_stage_id else None,
                "to_stage_name": to_stage_name,
                "to_status_code": to_status_code,
            })
        return result
