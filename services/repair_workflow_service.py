"""
repair_workflow_service.py
──────────────────────────
Business logic for the 10-stage transformer repair lifecycle workflow.

Status lifecycle per stage instance:
  not_started → pending → assigned → submitted → completed / rejected

Three actors:
  WORKFLOW_COORDINATOR  assigns users to stages (manages assignment queue)
  ASSIGNED USER         fills form, submits stage
  APPROVER              holds can_approve on the stage, advances or rejects
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import (
    Equipment,
    EquipmentStatus,
    OrgRole,
    OrgUserRole,
    OverhaulRecommendation,
    RepairAssignmentQueue,
    RepairStageAuditLog,
    RepairStageData,
    RepairStageDefinition,
    RepairStageDocument,
    RepairStageInstance,
    RepairStageRole,
    RepairStageTemplate,
    RepairStageTransition,
    RepairWorkflow,
    RepairWorkflowDefinition,
    OrgTestTemplate,
    TAQCObservation,
    User,
)

UPLOAD_DIR = os.path.join("uploads", "repair")


class RepairWorkflowService:

    def __init__(self, db: Session):
        self.db = db

    # =========================================================================
    # RBAC helpers
    # =========================================================================

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _user_org_role_ids(self, user_id: UUID) -> list:
        rows = (
            self.db.query(OrgUserRole.org_role_id)
            .filter(OrgUserRole.user_id == user_id, OrgUserRole.is_active.is_(True))
            .all()
        )
        return [r[0] for r in rows]

    def _check_stage_rbac(self, stage_id: UUID, user_id: UUID) -> None:
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            raise ValueError(
                "User has no active organization role."
            )
        allowed = (
            self.db.query(RepairStageRole)
            .filter(
                RepairStageRole.stage_id == stage_id,
                RepairStageRole.role_id.in_(role_ids),
                RepairStageRole.can_edit.is_(True),
            )
            .first()
        )
        if not allowed:
            raise ValueError("You do not have edit permission for this stage.")

    def _check_can_approve(self, stage_id: UUID, user_id: UUID) -> None:
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return
        allowed = (
            self.db.query(RepairStageRole)
            .filter(
                RepairStageRole.stage_id == stage_id,
                RepairStageRole.role_id.in_(role_ids),
                RepairStageRole.can_approve.is_(True),
            )
            .first()
        )
        if not allowed:
            raise ValueError("You do not have approval permission for this stage.")

    def _check_is_org_admin(self, user_id: UUID) -> None:
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return
        admin_role = (
            self.db.query(OrgRole)
            .filter(OrgRole.id.in_(role_ids), OrgRole.is_org_admin.is_(True))
            .first()
        )
        if not admin_role:
            raise ValueError("Only org-admin users can perform this configuration action.")

    def _check_can_assign_stage(self, user_id: UUID, stage_id: UUID) -> None:
        """Check caller has can_assign=True for this stage in repair_stage_roles."""
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return  # global admin bypass
        allowed = (
            self.db.query(RepairStageRole)
            .filter(
                RepairStageRole.stage_id == stage_id,
                RepairStageRole.role_id.in_(role_ids),
                RepairStageRole.can_assign.is_(True),
            )
            .first()
        )
        if not allowed:
            raise ValueError("Not authorized to assign users to this stage.")

    def _can_assign_stage(self, user_id: UUID, stage_id: UUID) -> bool:
        """Return True if caller has can_assign=True for this stage."""
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return True
        return (
            self.db.query(RepairStageRole)
            .filter(
                RepairStageRole.stage_id == stage_id,
                RepairStageRole.role_id.in_(role_ids),
                RepairStageRole.can_assign.is_(True),
            )
            .first()
        ) is not None

    # =========================================================================
    # Config — Stage Definitions
    # =========================================================================

    def list_stages(self) -> list:
        stages = (
            self.db.query(RepairStageDefinition)
            .order_by(RepairStageDefinition.sequence)
            .all()
        )
        result = []
        for s in stages:
            tmpl = (
                self.db.query(RepairStageTemplate)
                .filter(RepairStageTemplate.stage_id == s.id)
                .first()
            )
            roles = (
                self.db.query(RepairStageRole)
                .filter(RepairStageRole.stage_id == s.id)
                .all()
            )
            result.append({
                "id": str(s.id),
                "name": s.name,
                "code": s.code,
                "sequence": s.sequence,
                "weight": s.weight,
                "is_active": s.is_active,
                "is_mandatory": s.is_mandatory,
                "template_id": str(tmpl.template_id) if tmpl and tmpl.template_id else None,
                "roles": [
                    {"role_id": str(r.role_id), "can_edit": r.can_edit, "can_approve": r.can_approve, "can_assign": r.can_assign}
                    for r in roles
                ],
            })
        return result

    def create_stage(self, data: dict, user_id: UUID) -> dict:
        self._check_is_org_admin(user_id)
        existing = (
            self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.code == data.get("code"))
            .first()
        )
        if existing:
            raise ValueError(f"Stage with code '{data['code']}' already exists.")
        stage = RepairStageDefinition(
            name=data["name"],
            code=data["code"],
            sequence=data["sequence"],
            weight=data.get("weight", 10),
            is_mandatory=data.get("is_mandatory", True),
        )
        self.db.add(stage)
        self.db.commit()
        self.db.refresh(stage)
        return {"id": str(stage.id), "name": stage.name, "code": stage.code}

    def update_stage(self, stage_id: UUID, data: dict, user_id: UUID) -> dict:
        self._check_is_org_admin(user_id)
        stage = self.db.query(RepairStageDefinition).filter(RepairStageDefinition.id == stage_id).first()
        if not stage:
            raise ValueError("Stage not found.")
        for k, v in data.items():
            if hasattr(stage, k):
                setattr(stage, k, v)
        self.db.commit()
        self.db.refresh(stage)
        return {"id": str(stage.id), "name": stage.name}

    def deactivate_stage(self, stage_id: UUID, user_id: UUID) -> None:
        self._check_is_org_admin(user_id)
        stage = self.db.query(RepairStageDefinition).filter(RepairStageDefinition.id == stage_id).first()
        if not stage:
            raise ValueError("Stage not found.")
        stage.is_active = False
        self.db.commit()

    def reorder_stages(self, items: list, user_id: UUID) -> None:
        self._check_is_org_admin(user_id)
        for item in items:
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == UUID(str(item["id"]))
            ).first()
            if stage:
                stage.sequence = item["sequence"]
        self.db.commit()

    def set_stage_template(self, stage_id: UUID, template_id: UUID, user_id: UUID) -> None:
        self._check_is_org_admin(user_id)
        stage = self.db.query(RepairStageDefinition).filter(RepairStageDefinition.id == stage_id).first()
        if not stage:
            raise ValueError("Stage not found.")
        template = self.db.query(OrgTestTemplate).filter(OrgTestTemplate.id == template_id).first()
        if not template:
            raise ValueError("Template not found.")
        existing = (
            self.db.query(RepairStageTemplate)
            .filter(RepairStageTemplate.stage_id == stage_id)
            .first()
        )
        if existing:
            existing.template_id = template_id
        else:
            self.db.add(RepairStageTemplate(stage_id=stage_id, template_id=template_id))
        self.db.commit()

    def set_stage_roles(self, stage_id: UUID, roles: list, user_id: UUID) -> None:
        self._check_is_org_admin(user_id)
        stage = self.db.query(RepairStageDefinition).filter(RepairStageDefinition.id == stage_id).first()
        if not stage:
            raise ValueError("Stage not found.")
        self.db.query(RepairStageRole).filter(RepairStageRole.stage_id == stage_id).delete()
        for r in roles:
            self.db.add(RepairStageRole(
                stage_id=stage_id,
                role_id=UUID(str(r["role_id"])),
                can_edit=r.get("can_edit", False),
                can_approve=r.get("can_approve", False),
                can_assign=r.get("can_assign", False),
            ))
        self.db.commit()

    # =========================================================================
    # Config — Transitions
    # =========================================================================

    def list_transitions(self) -> list:
        transitions = self.db.query(RepairStageTransition).all()
        return [
            {
                "id": str(t.id),
                "from_stage_id": str(t.from_stage_id),
                "to_stage_id": str(t.to_stage_id) if t.to_stage_id else None,
                "action": t.action,
            }
            for t in transitions
        ]

    def upsert_transitions(self, transitions: list, user_id: UUID) -> None:
        self._check_is_org_admin(user_id)
        for t in transitions:
            existing = (
                self.db.query(RepairStageTransition)
                .filter(
                    RepairStageTransition.from_stage_id == UUID(str(t["from_stage_id"])),
                    RepairStageTransition.action == t["action"],
                )
                .first()
            )
            to_id = UUID(str(t["to_stage_id"])) if t.get("to_stage_id") else None
            if existing:
                existing.to_stage_id = to_id
            else:
                self.db.add(RepairStageTransition(
                    from_stage_id=UUID(str(t["from_stage_id"])),
                    to_stage_id=to_id,
                    action=t["action"],
                ))
        self.db.commit()

    # =========================================================================
    # Workflow Execution
    # =========================================================================

    from datetime import datetime

    def generate_workflow_number(self):

        today = datetime.utcnow().strftime("%Y%m%d")

        prefix = f"RW-REP-{today}-"

        last_workflow = (
            self.db.query(RepairWorkflow)
            .filter(
                RepairWorkflow.workflow_number.like(f"{prefix}%")
            )
            .order_by(RepairWorkflow.workflow_number.desc())
            .first()
        )

        if last_workflow and last_workflow.workflow_number:

            try:
                last_seq = int(
                    last_workflow.workflow_number.split("-")[-1]
                )
            except Exception:
                last_seq = 0

        else:
            last_seq = 0

        next_seq = last_seq + 1

        return f"{prefix}{next_seq:04d}"


    def start_workflow(
        self,
        equipment_id: UUID,
        user_id: UUID,
        source_failure_id: Optional[UUID] = None
    ) -> dict:
        """
        Start a new repair workflow.
        First stage is set to PENDING — awaiting coordinator assignment.
        """

        equipment = (
            self.db.query(Equipment)
            .filter(Equipment.id == equipment_id)
            .first()
        )

        if not equipment:
            raise ValueError("Equipment not found.")

        existing = (
            self.db.query(RepairWorkflow)
            .filter(
                RepairWorkflow.equipment_id == equipment_id,
                RepairWorkflow.status == "active",
            )
            .first()
        )

        if existing:
            raise ValueError(
                "An active repair workflow already exists for this equipment."
            )

        # GET WORKFLOW DEFINITION
        workflow_definition = (
            self.db.query(RepairWorkflowDefinition)
            .filter(
                RepairWorkflowDefinition.workflow_code
                == "BREAKDOWN"
            )
            .first()
        )

        if not workflow_definition:
            raise ValueError(
                "BREAKDOWN workflow definition not found."
            )

        # GET ONLY BREAKDOWN STAGES
        stages = (
            self.db.query(RepairStageDefinition)
            .filter(
                RepairStageDefinition.workflow_definition_id
                == workflow_definition.id,
                RepairStageDefinition.is_active.is_(True),
            )
            .order_by(RepairStageDefinition.sequence)
            .all()
        )

        if not stages:
            raise ValueError(
                "No active BREAKDOWN stages found."
            )

        first_stage = stages[0]

        # GENERATE WORKFLOW NUMBER
        workflow_number = self.generate_workflow_number()

        # CREATE WORKFLOW
        workflow = RepairWorkflow(
            workflow_number=workflow_number,
            workflow_code="BREAKDOWN",
            equipment_id=equipment_id,
            source_failure_id=source_failure_id,
            current_stage_id=first_stage.id,
            status="active",
            assignment_pending=True,
            progress=0,
            priority="normal",
            created_by=user_id,
        )

        self.db.add(workflow)
        self.db.flush()

        first_stage_instance = None

        # CREATE STAGE INSTANCES
        for s in stages:

            is_first = s.id == first_stage.id

            instance = RepairStageInstance(
                workflow_id=workflow.id,
                stage_id=s.id,
                status="pending" if is_first else "not_started",
                assignment_pending=is_first,
                started_at=self._utc_now() if is_first else None,
                created_by=user_id,
            )

            self.db.add(instance)
            self.db.flush()

            if is_first:
                first_stage_instance = instance

        # SET CURRENT STAGE INSTANCE
        workflow.current_stage_instance_id = (
            first_stage_instance.id
            if first_stage_instance
            else None
        )

        # CREATE ASSIGNMENT QUEUE
        self.db.add(
            RepairAssignmentQueue(
                workflow_id=workflow.id,
                stage_id=first_stage.id,
                status="pending",
            )
        )

        # UPDATE EQUIPMENT STATUS
        equipment.status = EquipmentStatus.under_repair

        self.db.commit()
        self.db.refresh(workflow)

        # LOG AUDIT
        self._log_audit(
            workflow.id,
            first_stage.id,
            "created",
            user_id,
            "Workflow started — awaiting coordinator assignment"
        )

        return self._workflow_to_dict(workflow)
        
    def assign_stage_user(
        self,
        workflow_id: UUID,
        stage_id: UUID,
        assign_to_user_id: UUID,
        coordinator_id: UUID,
    ) -> dict:
        """
        WORKFLOW_COORDINATOR assigns a user to the current (pending) stage.
        Transitions stage: pending → assigned
        """
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if workflow.status != "active":
            raise ValueError("Workflow is not active.")
        if str(workflow.current_stage_id) != str(stage_id):
            raise ValueError("Can only assign the current active stage.")

        self._check_can_assign_stage(coordinator_id, stage_id)

        instance = self._get_instance(workflow_id, stage_id)
        if instance.status in ("completed", "rejected"):
            raise ValueError(f"Stage is already '{instance.status}' — cannot reassign.")

        # Resolve assignee's role name for display
        assignee_role = (
            self.db.query(OrgRole)
            .join(OrgUserRole, OrgRole.id == OrgUserRole.org_role_id)
            .filter(
                OrgUserRole.user_id == assign_to_user_id,
                OrgUserRole.is_active.is_(True),
            )
            .first()
        )
        role_name = assignee_role.name if assignee_role else None

        instance.status = "assigned"
        instance.assigned_user_id = assign_to_user_id
        instance.current_role = role_name
        instance.assignment_pending = False

        workflow.assignment_pending = False

        # Update assignment queue
        queue_entry = (
            self.db.query(RepairAssignmentQueue)
            .filter(
                RepairAssignmentQueue.workflow_id == workflow_id,
                RepairAssignmentQueue.stage_id == stage_id,
                RepairAssignmentQueue.status == "pending",
            )
            .first()
        )
        if queue_entry:
            queue_entry.status = "assigned"
            queue_entry.assigned_to_user_id = assign_to_user_id
            queue_entry.assigned_at = self._utc_now()

        self.db.commit()

        assignee = self.db.query(User).filter(User.id == assign_to_user_id).first()
        self._log_audit(
            workflow_id, stage_id, "assign", coordinator_id,
            f"Assigned to {assignee.firstname} {assignee.lastname} ({role_name})" if assignee else "Assigned"
        )

        stage = self.db.query(RepairStageDefinition).filter(RepairStageDefinition.id == stage_id).first()
        return {
            "message": "User assigned successfully",
            "stage": stage.name if stage else str(stage_id),
            "assigned_to": str(assign_to_user_id),
            "role": role_name,
        }

    def submit_stage(
        self,
        workflow_id: UUID,
        stage_id: UUID,
        remarks: Optional[str],
        user_id: UUID,
    ) -> dict:
        """
        Stage actor submits the stage after filling the form.
        Status flow: assigned → submitted.
        Requires can_edit permission. Same role then calls /advance to approve.
        """
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if workflow.status != "active":
            raise ValueError("Workflow is not active.")
        if str(workflow.current_stage_id) != str(stage_id):
            raise ValueError("Can only submit the current active stage.")

        instance = self._get_instance(workflow_id, stage_id)

        if instance.status not in ("assigned", "in_progress"):
            raise ValueError(
                f"Stage must be in 'assigned' state to submit (currently '{instance.status}')."
            )

        # Submitter must be the assigned user OR have can_edit for this stage
        if instance.assigned_user_id and str(instance.assigned_user_id) != str(user_id):
            self._check_stage_rbac(stage_id, user_id)

        # Validate required fields at submit time (not at save/draft time).
        # Use the same category-aware resolution as get_current_form so that
        # ANNUAL_AUDIT workflows validate against the right template.
        category_detail_id = None
        if workflow.workflow_code == "ANNUAL_AUDIT":
            obs = (
                self.db.query(TAQCObservation)
                .filter(TAQCObservation.workflow_id == workflow_id)
                .first()
            )
            if obs:
                category_detail_id = obs.category_detail_id

        tmpl_link = None
        if category_detail_id is not None:
            tmpl_link = (
                self.db.query(RepairStageTemplate)
                .filter(
                    RepairStageTemplate.stage_id == stage_id,
                    RepairStageTemplate.category_detail_id == category_detail_id,
                )
                .first()
            )
        if tmpl_link is None:
            tmpl_link = (
                self.db.query(RepairStageTemplate)
                .filter(
                    RepairStageTemplate.stage_id == stage_id,
                    RepairStageTemplate.category_detail_id.is_(None),
                )
                .first()
            )
        if tmpl_link and tmpl_link.template_id:
            data_row = (
                self.db.query(RepairStageData)
                .filter(RepairStageData.stage_instance_id == instance.id)
                .first()
            )
            saved_data = data_row.form_data if data_row else {}
            self._validate_form_data(tmpl_link.template_id, saved_data or {})

        # Surveillance-specific validation: quarterly stages require all tests completed
        if workflow.workflow_type == 'surveillance' and instance.quarter_number:
            self._validate_surveillance_tests_completed(workflow_id, instance.quarter_number)

        instance.status = "submitted"
        if remarks:
            instance.remarks = remarks

        self.db.commit()
        self._log_audit(workflow_id, stage_id, "submit", user_id, remarks or "Stage submitted for approval")

        stage = self.db.query(RepairStageDefinition).filter(RepairStageDefinition.id == stage_id).first()

        # Fire notification so routing rules with status_from=assigned/status_to=submitted match
        self._fire_notification_safe(
            "repair_stage_changed", workflow, stage, user_id,
            status_from="assigned", status_to="submitted",
        )

        return {
            "message": "Stage submitted — awaiting approval",
            "stage": stage.name if stage else str(stage_id),
        }

    def advance_stage(self, workflow_id: UUID, remarks: Optional[str], user_id: UUID, action_label: str = "approve") -> dict:
        """
        Stage actor approves and advances to the next stage.
        Status flow: submitted → completed → next stage pending.
        Requires can_approve permission (same role as can_edit).
        action_label overrides the audit log entry (default "approve"); routing always uses "approve".
        """

        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if workflow.status != "active":
            raise ValueError("Workflow is not active.")

        current_stage_id = workflow.current_stage_id
        instance = self._get_instance(workflow_id, current_stage_id)

        # RBAC: caller must have can_approve for the current stage
        self._check_can_approve(current_stage_id, user_id)

        # Stage must be submitted before it can be approved
        if instance.status != "submitted":
            raise ValueError(
                f"Stage must be in 'submitted' state to approve (currently '{instance.status}')."
            )
        instance.remarks = remarks
        instance.status = "completed"
        instance.completed_at = self._utc_now()
        instance.completed_by = user_id

        self._log_audit(workflow_id, current_stage_id, action_label, user_id, remarks)

        transition = (
            self.db.query(RepairStageTransition)
            .filter(
                RepairStageTransition.from_stage_id == current_stage_id,
                RepairStageTransition.action == "approve",
            )
            .first()
        )
        next_stage_id = transition.to_stage_id if transition else None

        if not next_stage_id:
            workflow.status = "completed"
            workflow.current_stage_id = None
            workflow.assignment_pending = False
            workflow.progress = 100
            self._complete_queue_entry(workflow_id, current_stage_id)
            equipment = self.db.query(Equipment).filter(Equipment.id == workflow.equipment_id).first()
            if equipment:
                equipment.status = EquipmentStatus.active

            # Close associated OverhaulRecommendation if this is an OVERHAUL workflow
            if workflow.workflow_type == "OVERHAUL":
                rec = self.db.query(OverhaulRecommendation).filter(
                    OverhaulRecommendation.workflow_id == workflow_id,
                    OverhaulRecommendation.status == "OPEN"
                ).first()
                if rec:
                    rec.status = "CLOSED"
                    rec.closed_at = self._utc_now()

            self.db.commit()
            # Fire registered completion hooks (e.g. calibration schedule upsert).
            # Hooks are registered by *_hooks.py modules imported at startup.
            from workflow_hooks import fire
            fire(workflow.workflow_code or "", "completed", self.db, workflow, user_id)
            return {"message": "Workflow completed", "status": "completed", "progress": 100}

        workflow.current_stage_id = next_stage_id
       
        workflow.assignment_pending = True
        self._complete_queue_entry(workflow_id, current_stage_id)

        next_inst = self._get_instance(workflow_id, next_stage_id)
        if next_inst:
            next_inst.status = "pending"
            next_inst.assignment_pending = True
            next_inst.started_at = self._utc_now()
            next_inst.assigned_user_id = None
            next_inst.current_role = None
        if next_inst:
            workflow.current_stage_instance_id = next_inst.id
        self.db.add(RepairAssignmentQueue(workflow_id=workflow_id, stage_id=next_stage_id, status="pending"))
        self._recalculate_progress(workflow)
        self.db.commit()
        next_stage = self.db.query(RepairStageDefinition).filter(RepairStageDefinition.id == next_stage_id).first()

        self._fire_notification_safe(
            "repair_stage_changed",
            workflow,
            next_stage,
            user_id,
            status_from="submitted",
            status_to="approved",
        )
        # Fire stage_approved hook so listeners can react to specific stages
        # without touching this service (e.g. certificate upload processing).
        current_stage_def = self.db.query(RepairStageDefinition).filter(
            RepairStageDefinition.id == current_stage_id
        ).first()
        from workflow_hooks import fire
        fire(
            workflow.workflow_code or "", "stage_approved", self.db, workflow, user_id,
            stage_code=current_stage_def.code if current_stage_def else None,
        )
        if not next_stage_id:
            workflow.status = "completed"
            workflow.current_stage_id = None
            workflow.current_stage_instance_id = None
            workflow.assignment_pending = False
            workflow.progress = 100
        return {
            "message": "Stage approved and advanced",
            "current_stage": next_stage.name if next_stage else None,
            "progress": workflow.progress,
        }

    def reject_stage(self, workflow_id: UUID, remarks: Optional[str], user_id: UUID) -> dict:
        """
        Reject current stage and move back per the transition table.
        Stage must be SUBMITTED. No sequential fallback.
        """
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if workflow.status != "active":
            raise ValueError("Workflow is not active.")

        current_stage_id = workflow.current_stage_id
        self._check_can_approve(current_stage_id, user_id)

        instance = self._get_instance(workflow_id, current_stage_id)
        if instance.status != "submitted":
            raise ValueError(
                f"Stage must be in 'submitted' state to reject (currently '{instance.status}')."
            )

        instance.status = "rejected"
        self._log_audit(workflow_id, current_stage_id, "reject", user_id, remarks)

        # Find target stage via transition table only
        transition = (
            self.db.query(RepairStageTransition)
            .filter(
                RepairStageTransition.from_stage_id == current_stage_id,
                RepairStageTransition.action == "reject",
            )
            .first()
        )
        prev_stage_id = transition.to_stage_id if transition else None

        if not prev_stage_id:
            # No reject transition defined — stay at current (notify coordinator to re-assign)
            workflow.assignment_pending = True
            instance.status = "pending"
            instance.assignment_pending = True
            instance.assigned_user_id = None
            instance.current_role = None

            # Re-queue for coordinator
            existing_q = (
                self.db.query(RepairAssignmentQueue)
                .filter(
                    RepairAssignmentQueue.workflow_id == workflow_id,
                    RepairAssignmentQueue.stage_id == current_stage_id,
                    RepairAssignmentQueue.status.in_(["assigned", "completed"]),
                )
                .first()
            )
            if existing_q:
                existing_q.status = "pending"
                existing_q.assigned_to_user_id = None
                existing_q.assigned_at = None
            else:
                self.db.add(RepairAssignmentQueue(
                    workflow_id=workflow_id,
                    stage_id=current_stage_id,
                    status="pending",
                ))

            self.db.commit()
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == current_stage_id
            ).first()
            return {
                "message": "Stage rejected — re-queued for coordinator assignment",
                "current_stage": stage.name if stage else None,
                "progress": workflow.progress,
            }

        # Reset target stage to PENDING for re-assignment
        prev_inst = self._get_instance(workflow_id, prev_stage_id)
        if prev_inst:
            prev_inst.status = "pending"
            prev_inst.assignment_pending = True
            prev_inst.completed_at = None
            prev_inst.assigned_user_id = None
            prev_inst.current_role = None

        workflow.current_stage_id = prev_stage_id
        workflow.assignment_pending = True

        # Queue for coordinator
        self.db.add(RepairAssignmentQueue(
            workflow_id=workflow_id,
            stage_id=prev_stage_id,
            status="pending",
        ))

        # Load rejected stage definition BEFORE commit (for overdue computation in notification)
        rejected_stage_def = self.db.query(RepairStageDefinition).filter(
            RepairStageDefinition.id == current_stage_id
        ).first()
        # Load previous (rollback target) stage name for the API response
        prev_stage = self.db.query(RepairStageDefinition).filter(
            RepairStageDefinition.id == prev_stage_id
        ).first()

        self._recalculate_progress(workflow)
        self.db.commit()

        self._fire_notification_safe(
            "repair_delay", workflow, rejected_stage_def, user_id, stage_instance=instance
        )

        return {
            "message": "Stage rejected — returned stage pending coordinator assignment",
            "current_stage": prev_stage.name if prev_stage else None,
            "progress": workflow.progress,
        }

    def cancel_workflow(self, workflow_id: UUID, user_id: UUID, reason: Optional[str] = None) -> dict:
        """Cancel an active workflow. Only org-admin or workflow creator."""
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if workflow.status != "active":
            raise ValueError("Only active workflows can be cancelled.")

        # Allow creator or org-admin
        if str(workflow.created_by) != str(user_id):
            self._check_is_org_admin(user_id)

        workflow.status = "cancelled"
        workflow.completed_at = self._utc_now()
        workflow.assignment_pending = False

        # Mark all pending queue entries as skipped
        self.db.query(RepairAssignmentQueue).filter(
            RepairAssignmentQueue.workflow_id == workflow_id,
            RepairAssignmentQueue.status == "pending",
        ).update({"status": "skipped"})

        # Restore equipment status
        equipment = self.db.query(Equipment).filter(Equipment.id == workflow.equipment_id).first()
        if equipment:
            equipment.status = EquipmentStatus.active

        # Close associated OverhaulRecommendation if this is an OVERHAUL workflow
        if workflow.workflow_type == "OVERHAUL":
            rec = self.db.query(OverhaulRecommendation).filter(
                OverhaulRecommendation.workflow_id == workflow_id,
                OverhaulRecommendation.status == "OPEN"
            ).first()
            if rec:
                rec.status = "CLOSED"
                rec.closed_at = self._utc_now()

        self.db.commit()
        self._log_audit(workflow_id, workflow.current_stage_id, "cancel", user_id, reason or "Workflow cancelled")

        return {"message": "Workflow cancelled", "workflow_id": str(workflow_id)}

    def list_pending_assignments(self) -> list:
        """
        All active workflows where assignment_pending=True.
        Used by the Workflow Coordinator's assignment queue page.
        Returns each workflow with the pending stage details.
        """
        workflows = (
            self.db.query(RepairWorkflow)
            .filter(
                RepairWorkflow.status == "active",
                RepairWorkflow.assignment_pending.is_(True),
                or_(
                    RepairWorkflow.workflow_code.is_(None),
                    RepairWorkflow.workflow_code != "ANNUAL_AUDIT",
                ),
            )
            .order_by(RepairWorkflow.created_at.asc())
            .all()
        )
        result = []
        for wf in workflows:
            equipment = self.db.query(Equipment).filter(Equipment.id == wf.equipment_id).first()
            pending_stage = None
            if wf.current_stage_id:
                inst = self._get_instance(wf.id, wf.current_stage_id)
                stage = self.db.query(RepairStageDefinition).filter(
                    RepairStageDefinition.id == wf.current_stage_id
                ).first()
                if inst and stage:
                    pending_stage = {
                        "stage_id": str(stage.id),
                        "stage_name": stage.name,
                        "stage_code": stage.code,
                        "sequence": stage.sequence,
                        "instance_status": inst.status,
                    }

            # Eligible roles for this stage
            eligible_roles: list[str] = []
            if wf.current_stage_id:
                role_rows = (
                    self.db.query(RepairStageRole, OrgRole)
                    .join(OrgRole, OrgRole.id == RepairStageRole.role_id)
                    .filter(RepairStageRole.stage_id == wf.current_stage_id)
                    .all()
                )
                seen: set[str] = set()
                for _, role in role_rows:
                    if role.name not in seen:
                        eligible_roles.append(role.name)
                        seen.add(role.name)

            result.append({
                "workflow_id": str(wf.id),
                "equipment_id": str(wf.equipment_id),
                "equipment_ueic": equipment.ueic if equipment else None,
                "progress": wf.progress,
                "pending_stage": pending_stage,
                "eligible_roles": eligible_roles,
                "created_at": wf.created_at.isoformat() if wf.created_at else None,
            })
        return result

    def list_workflows(
        self,
        equipment_id: Optional[UUID] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list:
        q = self.db.query(RepairWorkflow)
        if status == "annual_audit":
            # Annual Audit workflows are a separate type — show only them
            q = q.filter(RepairWorkflow.workflow_code == "ANNUAL_AUDIT")
            status = None  # don't apply status filter below
        else:
            q = q.filter(or_(RepairWorkflow.workflow_code.is_(None), RepairWorkflow.workflow_code != "ANNUAL_AUDIT"))
        if equipment_id:
            q = q.filter(RepairWorkflow.equipment_id == equipment_id)
        if status:
            q = q.filter(RepairWorkflow.status == status)
        workflows = q.order_by(RepairWorkflow.created_at.desc()).offset(skip).limit(limit).all()
        return [self._workflow_to_dict(w) for w in workflows]

    def get_workflow_detail(self, workflow_id: UUID) -> dict:
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        result = self._workflow_to_dict(workflow)

        instances = (
            self.db.query(RepairStageInstance)
            .filter(RepairStageInstance.workflow_id == workflow_id)
            .all()
        )
        stage_details = []
        for inst in instances:
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == inst.stage_id
            ).first()
            data_row = (
                self.db.query(RepairStageData)
                .filter(RepairStageData.stage_instance_id == inst.id)
                .order_by(RepairStageData.created_at.desc())
                .first()
            )
            assignee = None
            if inst.assigned_user_id:
                u = self.db.query(User).filter(User.id == inst.assigned_user_id).first()
                if u:
                    assignee = {
                        "id": str(u.id),
                        "name": f"{u.firstname} {u.lastname}",
                        "email": u.email,
                    }

            stage_roles = []
            approval_roles = []
            assignment_roles = []
            edit_roles = []
            role_rows = (
                self.db.query(RepairStageRole, OrgRole)
                .join(OrgRole, RepairStageRole.role_id == OrgRole.id)
                .filter(RepairStageRole.stage_id == inst.stage_id)
                .all()
            )
            for stage_role, org_role in role_rows:
                role_name = org_role.name if org_role else None
                if not role_name:
                    continue
                stage_roles.append({
                    "role_id": str(org_role.id),
                    "role_name": role_name,
                    "can_edit": stage_role.can_edit,
                    "can_approve": stage_role.can_approve,
                    "can_assign": stage_role.can_assign,
                })
                if stage_role.can_approve:
                    approval_roles.append(role_name)
                if stage_role.can_assign:
                    assignment_roles.append(role_name)
                if stage_role.can_edit:
                    edit_roles.append(role_name)

            stage_details.append({
                "instance_id": str(inst.id),
                "stage_id": str(inst.stage_id),
                "stage_name": stage.name if stage else None,
                "stage_code": stage.code if stage else None,
                "sequence": stage.sequence if stage else None,
                "status": inst.status,
                "assignment_pending": inst.assignment_pending,
                "assigned_user": assignee,
                "current_role": inst.current_role,
                "stage_roles": stage_roles,
                "approval_roles": approval_roles,
                "assignment_roles": assignment_roles,
                "edit_roles": edit_roles,
                "started_at": inst.started_at.isoformat() if inst.started_at else None,
                "completed_at": inst.completed_at.isoformat() if inst.completed_at else None,
                "form_data": data_row.form_data if data_row else {},
            })
        stage_details.sort(key=lambda x: x["sequence"] or 0)
        result["stages"] = stage_details
        return result

    def get_assignment_queue(self, workflow_id: UUID) -> list:
        """Return all pending assignment queue entries for a workflow."""
        entries = (
            self.db.query(RepairAssignmentQueue)
            .filter(RepairAssignmentQueue.workflow_id == workflow_id)
            .order_by(RepairAssignmentQueue.created_at.desc())
            .all()
        )
        result = []
        for e in entries:
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == e.stage_id
            ).first()
            assignee = None
            if e.assigned_to_user_id:
                u = self.db.query(User).filter(User.id == e.assigned_to_user_id).first()
                if u:
                    assignee = {"id": str(u.id), "name": f"{u.firstname} {u.lastname}"}
            result.append({
                "id": str(e.id),
                "stage_id": str(e.stage_id),
                "stage_name": stage.name if stage else None,
                "stage_code": stage.code if stage else None,
                "status": e.status,
                "assigned_to": assignee,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "assigned_at": e.assigned_at.isoformat() if e.assigned_at else None,
            })
        return result

    def get_eligible_users(
    self,
    workflow_id: UUID,
    stage_id: UUID,
    current_user: User,
) -> list:
        """
        Returns users authorised for assignment
        for the given workflow stage.
        """

        # Validate workflow
        workflow = (
            self.db.query(RepairWorkflow)
            .filter(
                RepairWorkflow.id == workflow_id
            )
            .first()
        )

        if not workflow:
            raise ValueError("Workflow not found")

        # Multi-tenant security — ANNUAL_AUDIT workflows have no equipment_id
        if workflow.equipment_id:
            equipment = (
                self.db.query(Equipment)
                .filter(Equipment.id == workflow.equipment_id)
                .first()
            )
            if not equipment:
                raise ValueError("Equipment not found")
            if str(equipment.organization_id) != str(current_user.organization_id):
                raise ValueError("Unauthorized workflow access")
        elif workflow.organization_id:
            if str(workflow.organization_id) != str(current_user.organization_id):
                raise ValueError("Unauthorized workflow access")

        # Validate stage
        stage_def = (
            self.db.query(RepairStageDefinition)
            .filter(
                RepairStageDefinition.id == stage_id
            )
            .first()
        )

        if not stage_def:
            raise ValueError("Stage not found")

        # Roles allowed to receive assignments
        role_ids = [
    r.role_id
    for r in (
        self.db.query(RepairStageRole)
        .join(
            OrgRole,
            OrgRole.id == RepairStageRole.role_id,
        )
        .filter(
            RepairStageRole.stage_id == stage_id,
            RepairStageRole.can_edit.is_(True),
            OrgRole.organization_id == current_user.organization_id,
        )
        .all()
    )
]

        if not role_ids:
            raise ValueError(
                "No assignable roles configured for this stage."
            )

        # Fetch users in same organization
        users = (
            self.db.query(User)
            .join(
                OrgUserRole,
                OrgUserRole.user_id == User.id,
            )
            .filter(
                OrgUserRole.org_role_id.in_(role_ids),
                OrgUserRole.is_active.is_(True),
                User.isactive.is_(True),
                User.organization_id
                == current_user.organization_id,
            )
            .distinct()
            .all()
        )

        result = []

        for u in users:

            role = (
                self.db.query(OrgRole)
                .join(
                    OrgUserRole,
                    OrgUserRole.org_role_id == OrgRole.id,
                )
                .filter(
                    OrgUserRole.user_id == u.id,
                    OrgRole.id.in_(role_ids),
                )
                .first()
            )

            result.append({
                "id": str(u.id),
                "firstname": u.firstname,
                "lastname": u.lastname,
                "email": u.email,
                "role": role.name if role else None,
            })

        return result

    def get_available_transitions(self, workflow_id: UUID, user_id: UUID) -> dict:
        """
        Returns what actions the calling user can take on this workflow right now.
        """
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")

        result = {
            "can_assign": False,
            "can_submit": False,
            "can_approve": False,
            "can_reject": False,
            "can_cancel": False,
        }

        if workflow.status != "active":
            return result

        current_stage_id = workflow.current_stage_id
        if not current_stage_id:
            return result

        instance = self._get_instance(workflow_id, current_stage_id)
        if not instance:
            return result

        stage_status = instance.status

        # can_assign: coordinator (can_assign=True) when stage awaits assignment
        if self._can_assign_stage(user_id, instance.stage_id):
            if stage_status in ("pending", "not_started"):
                result["can_assign"] = True

        # can_submit: assigned actor with can_edit=True
        if stage_status in ("assigned", "in_progress"):

            is_assignee = (
                instance.assigned_user_id
                and str(instance.assigned_user_id) == str(user_id)
            )

            has_edit = self._has_stage_edit(
                current_stage_id,
                user_id,
            )

            if is_assignee and has_edit:
                result["can_submit"] = True

        # can_approve / can_reject: stage actor (can_approve=True) when submitted
        if stage_status == "submitted":
            if self._has_stage_approve(current_stage_id, user_id):
                result["can_approve"] = True
                result["can_reject"] = True

        # can_cancel: creator or org-admin
        if str(workflow.created_by) == str(user_id):
            result["can_cancel"] = True
        else:
            try:
                self._check_is_org_admin(user_id)
                result["can_cancel"] = True
            except ValueError:
                pass

        return result

    def get_current_form(self, workflow_id: UUID) -> dict:
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if not workflow.current_stage_id:
            raise ValueError("No current stage set on this workflow.")

        stage = self.db.query(RepairStageDefinition).filter(
            RepairStageDefinition.id == workflow.current_stage_id
        ).first()

        # For ANNUAL_AUDIT workflows resolve category-specific template first,
        # then fall back to the generic (category_detail_id IS NULL) template.
        category_detail_id = None
        if workflow.workflow_code == "ANNUAL_AUDIT":
            obs = (
                self.db.query(TAQCObservation)
                .filter(TAQCObservation.workflow_id == workflow_id)
                .first()
            )
            if obs:
                category_detail_id = obs.category_detail_id

        tmpl_link = None
        if category_detail_id is not None:
            tmpl_link = (
                self.db.query(RepairStageTemplate)
                .filter(
                    RepairStageTemplate.stage_id == workflow.current_stage_id,
                    RepairStageTemplate.category_detail_id == category_detail_id,
                )
                .first()
            )
        if tmpl_link is None:
            # Generic fallback (also used by all non-ANNUAL_AUDIT workflows)
            tmpl_link = (
                self.db.query(RepairStageTemplate)
                .filter(
                    RepairStageTemplate.stage_id == workflow.current_stage_id,
                    RepairStageTemplate.category_detail_id.is_(None),
                )
                .first()
            )

        template_data = None
        if tmpl_link and tmpl_link.template_id:
            tmpl = self.db.query(OrgTestTemplate).filter(
                OrgTestTemplate.id == tmpl_link.template_id
            ).first()
            if tmpl:
                template_data = tmpl.template_data

        instance = self._get_instance(workflow_id, workflow.current_stage_id)
        saved_data = {}
        if instance:
            data_row = (
                self.db.query(RepairStageData)
                .filter(RepairStageData.stage_instance_id == instance.id)
                .order_by(RepairStageData.created_at.desc())
                .first()
            )
            if data_row:
                saved_data = data_row.form_data or {}

        # Prefill CAL_REVIEW readonly fields from calibration service if not yet saved
        stage_code = stage.code if stage else None
        if stage_code == "CAL_REVIEW" and workflow.equipment_id and not saved_data.get("last_calibration_date"):
            try:
                from datetime import date, timezone
                from services.calibration_service import CalibrationService
                cal_svc = CalibrationService(self.db)
                reading = cal_svc._get_latest_reading(workflow.equipment_id)
                if reading:
                    cal_date = reading["calibration_date"]        # str YYYY-MM-DD
                    validity = reading["validity_months"]          # int
                    from dateutil.relativedelta import relativedelta
                    next_due = (
                        date.fromisoformat(cal_date) + relativedelta(months=int(validity))
                    )
                    today = date.today()
                    days_delta = (today - next_due).days  # positive = overdue, negative = days remaining
                    saved_data = {
                        **saved_data,
                        "last_calibration_date": cal_date,
                        "next_due_date": next_due.isoformat(),
                        "days_overdue": days_delta,
                    }
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning(
                    "[CAL_REVIEW prefill] Failed to prefill calibration data: %s", exc
                )

        return {
            "workflow_id": str(workflow_id),
            "stage_id": str(workflow.current_stage_id),
            "stage_name": stage.name if stage else None,
            "stage_code": stage_code,
            "stage_status": instance.status if instance else None,
            "assignment_pending": workflow.assignment_pending,
            "template_data": template_data,
            "saved_form_data": saved_data,
        }

    def save_stage_data(self, workflow_id: UUID, stage_id: UUID, form_data: dict, user_id: UUID) -> dict:
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if str(workflow.current_stage_id) != str(stage_id):
            raise ValueError("Cannot save data for a stage that is not currently active.")

        self._check_stage_rbac(stage_id, user_id)

        instance = self._get_instance(workflow_id, stage_id)
        if not instance:
            raise ValueError("Stage instance not found.")

        data_row = (
            self.db.query(RepairStageData)
            .filter(RepairStageData.stage_instance_id == instance.id)
            .first()
        )
        if data_row:
            merged = {**(data_row.form_data or {}), **form_data}
            data_row.form_data = merged
        else:
            merged = form_data
            data_row = RepairStageData(
                stage_instance_id=instance.id,
                form_data=form_data,
                created_by=user_id,
            )
            self.db.add(data_row)

        # Save is always a draft — required-field validation happens at submit time
        self.db.commit()
        self._log_audit(workflow_id, stage_id, "saved", user_id, "Form data saved")
        return {"message": "Stage data saved successfully", "stage_id": str(stage_id)}

    def upload_stage_file(
        self,
        workflow_id: UUID,
        stage_id: UUID,
        field_key: str,
        file_name: str,
        file_bytes: bytes,
        mime_type: str,
        user_id: UUID,
    ) -> dict:
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")

        self._check_stage_rbac(stage_id, user_id)

        instance = self._get_instance(workflow_id, stage_id)
        if not instance:
            raise ValueError("Stage instance not found.")

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        unique_name = f"{uuid.uuid4()}_{file_name}"
        rel_path = os.path.join(UPLOAD_DIR, unique_name)
        abs_path = os.path.abspath(rel_path)
        with open(abs_path, "wb") as f:
            f.write(file_bytes)

        doc = RepairStageDocument(
            stage_instance_id=instance.id,
            field_key=field_key,
            file_name=file_name,
            file_path=rel_path,
            mime_type=mime_type,
            size_bytes=len(file_bytes),
            uploaded_by=user_id,
        )
        self.db.add(doc)
        self.db.flush()

        doc_ref = {
            "document_id": str(doc.id),
            "file_name": file_name,
            "mime_type": mime_type,
            "size_bytes": len(file_bytes),
        }
        data_row = (
            self.db.query(RepairStageData)
            .filter(RepairStageData.stage_instance_id == instance.id)
            .first()
        )
        if data_row:
            merged = {**(data_row.form_data or {}), field_key: doc_ref}
            data_row.form_data = merged
        else:
            data_row = RepairStageData(
                stage_instance_id=instance.id,
                form_data={field_key: doc_ref},
                created_by=user_id,
            )
            self.db.add(data_row)

        self.db.commit()
        self._log_audit(workflow_id, stage_id, "file_uploaded", user_id, f"File uploaded: {file_name}")
        return {
            "document_id": str(doc.id),
            "field_key": field_key,
            "file_name": file_name,
            "size_bytes": len(file_bytes),
        }

    # =========================================================================
    # Progress & Timeline
    # =========================================================================

    def get_progress(self, workflow_id: UUID) -> dict:
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")

        current_stage = None
        if workflow.current_stage_id:
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == workflow.current_stage_id
            ).first()
            if stage:
                current_stage = {"id": str(stage.id), "name": stage.name, "code": stage.code}

        return {
            "workflow_id": str(workflow_id),
            "status": workflow.status,
            "assignment_pending": workflow.assignment_pending,
            "progress": workflow.progress,
            "current_stage": current_stage,
        }

    def get_timeline(self, workflow_id: UUID) -> list:
        logs = (
            self.db.query(RepairStageAuditLog)
            .filter(RepairStageAuditLog.workflow_id == workflow_id)
            .order_by(RepairStageAuditLog.performed_at)
            .all()
        )
        result = []
        for log in logs:
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == log.stage_id
            ).first()
            performer = self.db.query(User).filter(User.id == log.performed_by).first()
            result.append({
                "id": str(log.id),
                "action": log.action,
                "stage_name": stage.name if stage else None,
                "performed_by": str(log.performed_by) if log.performed_by else None,
                "performed_by_name": f"{performer.firstname} {performer.lastname}" if performer else None,
                "note": log.note,
                "performed_at": log.performed_at.isoformat() if log.performed_at else None,
            })
        return result

    # =========================================================================
    # Documents
    # =========================================================================

    def list_stage_documents(self, workflow_id: UUID, stage_id: UUID) -> list:
        instance = self._get_instance(workflow_id, stage_id)
        if not instance:
            raise ValueError("Stage instance not found.")

        docs = (
            self.db.query(RepairStageDocument)
            .filter(RepairStageDocument.stage_instance_id == instance.id)
            .all()
        )
        return [
            {
                "id": str(d.id),
                "field_key": d.field_key,
                "file_name": d.file_name,
                "mime_type": d.mime_type,
                "size_bytes": d.size_bytes,
            }
            for d in docs
        ]

    def get_document_file(self, doc_id: UUID):
        doc = self.db.query(RepairStageDocument).filter(RepairStageDocument.id == doc_id).first()
        if not doc:
            raise ValueError("Document not found.")
        abs_path = os.path.abspath(doc.file_path)
        if not os.path.exists(abs_path):
            raise ValueError("File not found on disk.")
        return abs_path, doc.file_name, doc.mime_type

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _get_instance(self, workflow_id: UUID, stage_id: UUID) -> Optional[RepairStageInstance]:
        return (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id == stage_id,
            )
            .first()
        )

    def _has_stage_edit(self, stage_id: UUID, user_id: UUID) -> bool:
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return True
        return bool(
            self.db.query(RepairStageRole)
            .filter(
                RepairStageRole.stage_id == stage_id,
                RepairStageRole.role_id.in_(role_ids),
                RepairStageRole.can_edit.is_(True),
            )
            .first()
        )

    def _has_stage_approve(self, stage_id: UUID, user_id: UUID) -> bool:
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return True
        return bool(
            self.db.query(RepairStageRole)
            .filter(
                RepairStageRole.stage_id == stage_id,
                RepairStageRole.role_id.in_(role_ids),
                RepairStageRole.can_approve.is_(True),
            )
            .first()
        )

    def _complete_queue_entry(self, workflow_id: UUID, stage_id: UUID) -> None:
        entry = (
            self.db.query(RepairAssignmentQueue)
            .filter(
                RepairAssignmentQueue.workflow_id == workflow_id,
                RepairAssignmentQueue.stage_id == stage_id,
                RepairAssignmentQueue.status.in_(["pending", "assigned"]),
            )
            .first()
        )
        if entry:
            entry.status = "completed"
            entry.completed_at = self._utc_now()

    def _recalculate_progress(self, workflow: RepairWorkflow) -> None:

        # Get workflow definition using workflow_code
        workflow_definition = (
            self.db.query(RepairWorkflowDefinition)
            .filter(
                RepairWorkflowDefinition.workflow_code
                == workflow.workflow_code
            )
            .first()
        )

        if not workflow_definition:
            workflow.progress = 0
            return

        # Get only stages belonging to this workflow
        stages = (
            self.db.query(RepairStageDefinition)
            .filter(
                RepairStageDefinition.workflow_definition_id
                == workflow_definition.id,
                RepairStageDefinition.is_active.is_(True),
            )
            .order_by(RepairStageDefinition.sequence)
            .all()
        )

        if not stages:
            workflow.progress = 0
            return

        # Create stage map
        stage_map = {
            str(stage.id): stage
            for stage in stages
        }

        # Total workflow weight
        total_weight = sum(
            stage.weight or 0
            for stage in stages
        )

        if total_weight == 0:
            workflow.progress = 0
            return

        # Fetch workflow instances
        instances = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id
                == workflow.id
            )
            .all()
        )

        # Calculate completed weight
        completed_weight = 0

        for inst in instances:

            if (
                inst.status == "completed"
                and str(inst.stage_id) in stage_map
            ):
                completed_weight += (
                    stage_map[str(inst.stage_id)].weight or 0
                )

        # Calculate percentage
        workflow.progress = int(
            (completed_weight / total_weight) * 100
        )

    def _log_audit(
        self,
        workflow_id: UUID,
        stage_id: Optional[UUID],
        action: str,
        performed_by: UUID,
        note: Optional[str] = None,
    ) -> None:
        self.db.add(RepairStageAuditLog(
            workflow_id=workflow_id,
            stage_id=stage_id,
            action=action,
            performed_by=performed_by,
            note=note,
            performed_at=self._utc_now(),
        ))

    def _workflow_to_dict(self, workflow: RepairWorkflow) -> dict:
        from datetime import timedelta

        equipment = (
            self.db.query(Equipment).filter(Equipment.id == workflow.equipment_id).first()
            if workflow.equipment_id else None
        )
        current_stage = None
        current_stage_deadline = None
        days_remaining = None
        is_overdue = False

        if workflow.current_stage_id:
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == workflow.current_stage_id
            ).first()
            if stage:
                current_stage = {
                    "id": str(stage.id),
                    "name": stage.name,
                    "code": stage.code,
                    "sequence": stage.sequence,
                }

                # Calculate deadline for current stage instance
                if workflow.current_stage_instance_id:
                    stage_instance = self.db.query(RepairStageInstance).filter(
                        RepairStageInstance.id == workflow.current_stage_instance_id
                    ).first()

                    if (stage_instance and stage_instance.started_at and
                        stage.default_duration_days is not None):
                        deadline = stage_instance.started_at + timedelta(days=stage.default_duration_days)
                        current_stage_deadline = deadline.isoformat()

                        now = datetime.utcnow()
                        days_remaining = (deadline - now).days
                        is_overdue = days_remaining < 0

        return {
            "id": str(workflow.id),
            "workflow_number": workflow.workflow_number,
            "workflow_type": workflow.workflow_type or "BREAKDOWN",  # BREAKDOWN / OVERHAUL
            "source": workflow.source,                               # manual / cumulative / scheduled
            "workflow_code": workflow.workflow_code,
            "entity_type": workflow.entity_type,
            "entity_id": str(workflow.entity_id) if workflow.entity_id else None,
            "equipment_id": str(workflow.equipment_id) if workflow.equipment_id else None,
            "equipment_ueic": equipment.ueic if equipment else None,
            "equipment_name": equipment.nameplate_data.get("name") if equipment and equipment.nameplate_data else None,
            "source_failure_id": str(workflow.source_failure_id) if workflow.source_failure_id else None,
            "status": workflow.status,
            "assignment_pending": workflow.assignment_pending,
            "progress": workflow.progress,
            "priority": workflow.priority,
            "current_stage": current_stage,
            "current_stage_deadline": current_stage_deadline,
            "days_remaining": days_remaining,
            "is_overdue": is_overdue,
            "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        }

    def _validate_form_data(self, template_id: UUID, form_data: dict) -> None:
        template = self.db.query(OrgTestTemplate).filter(OrgTestTemplate.id == template_id).first()
        if not template or not template.template_data:
            return

        sections = template.template_data.get("sections", [])
        errors = []
        for section in sections:
            for field in section.get("fields", []):
                key = field.get("key")
                is_required = field.get("required", False)
                field_type = field.get("type", "text")
                label = field.get("label", key)

                if not is_required or not key:
                    continue

                val = form_data.get(key)
                if field_type == "file":
                    if not val or not isinstance(val, dict):
                        errors.append(f"{label} (file upload) is required.")
                elif val is None or str(val).strip() == "":
                    errors.append(f"{label} is required.")

        if errors:
            raise ValueError("; ".join(errors))

    def _validate_surveillance_tests_completed(self, workflow_id: UUID, quarter_number: int) -> None:
        """
        Validate that all surveillance testing requests for this quarter are completed.
        Raises ValueError if any tests are pending/in-progress.

        Args:
            workflow_id: Surveillance workflow ID
            quarter_number: Quarter number (1-4)
        """
        from models import TestingRequest

        # Get all testing requests for this quarter
        testing_requests = (
            self.db.query(TestingRequest)
            .filter(
                TestingRequest.surveillance_workflow_id == workflow_id,
                TestingRequest.surveillance_quarter == quarter_number
            )
            .all()
        )

        if not testing_requests:
            # No tests created yet - this shouldn't happen but allow submission
            # (tests will be created by daily scheduler)
            return

        # Check for incomplete tests
        incomplete = [
            tr for tr in testing_requests
            if tr.status not in ['completed', 'cancelled']
        ]

        if incomplete:
            test_names = [tr.title or f"Test {tr.test_type.name if tr.test_type else 'Unknown'}"
                         for tr in incomplete[:3]]  # Show first 3
            count = len(incomplete)
            msg = (
                f"Cannot submit quarterly review: {count} testing request(s) still in progress. "
                f"Please complete all tests before submitting this stage. "
                f"Incomplete tests: {', '.join(test_names)}"
            )
            if count > 3:
                msg += f" and {count - 3} more"
            raise ValueError(msg)

    def _fire_notification_safe(
        self,
        event_type: str,
        workflow: RepairWorkflow,
        stage,
        user_id: UUID,
        stage_instance=None,
        status_from: Optional[str] = None,
        status_to: Optional[str] = None,
    ) -> None:
        """
        Fire a notification for a workflow stage event, routing to the correct
        event type based on workflow_code:
          CALIBRATION  → calibration_stage_changed / calibration_stage_delay
          SURVEILLANCE → surveillance_stage_changed / surveillance_stage_delay
          (else)       → repair_stage_changed       / repair_delay

        status_from / status_to are passed through to the notification engine
        so that routing rules with applicable_status_from/to filters match correctly:
          submit_stage:  status_from="assigned",  status_to="submitted"
          advance_stage: status_from="submitted", status_to="approved"

        For delay events, stage should be the REJECTED stage definition and
        stage_instance should be its RepairStageInstance so that
        default_duration_days can be used to compute the real deadline and
        days_delayed (instead of dummy zeros).
        """
        try:
            from services.notification_service import NotificationService
            equipment = self.db.query(Equipment).filter(Equipment.id == workflow.equipment_id).first()
            if not equipment:
                return
            svc = NotificationService(self.db)
            wf_code = (workflow.workflow_code or "").upper()
            eq_ueic = equipment.ueic or str(equipment.id)
            eq_type = (
                equipment.equipment_type.name
                if getattr(equipment, "equipment_type", None)
                else "Equipment"
            )
            stage_name = stage.name if stage else "Unknown Stage"

            if event_type == "repair_stage_changed":
                if wf_code == "OVERHAUL":
                    actual_event = "overhaul_stage_changed"
                elif wf_code == "CALIBRATION":
                    actual_event = "calibration_stage_changed"
                elif wf_code == "SURVEILLANCE":
                    actual_event = "surveillance_stage_changed"
                else:
                    actual_event = "repair_stage_changed"
                svc.fire(
                    event_type=actual_event,
                    context={
                        "equipment":      eq_ueic,
                        "equipment_type": eq_type,
                        "stage":          stage_name,
                        "progress":       str(workflow.progress),
                    },
                    organization_id=equipment.organization_id,
                    department_id=equipment.department_id,
                    source_id=workflow.id,
                    source_type="repair_workflow",
                    severity="info",
                    workflow_type="repair_lifecycle",
                    status_from=status_from,
                    status_to=status_to,
                )

            elif event_type == "repair_delay":
                if wf_code == "OVERHAUL":
                    actual_event = "overhaul_stage_delay"
                elif wf_code == "CALIBRATION":
                    actual_event = "calibration_stage_delay"
                elif wf_code == "SURVEILLANCE":
                    actual_event = "surveillance_stage_delay"
                else:
                    actual_event = "repair_delay"

                # ── Compute real deadline and overdue days from stage definition ──
                deadline_str = "-"
                days_overdue = 0
                duration = getattr(stage, "default_duration_days", None)
                started_at = getattr(stage_instance, "started_at", None) if stage_instance else None
                if duration is not None and started_at is not None:
                    deadline_dt = started_at + timedelta(days=duration)
                    deadline_str = deadline_dt.strftime("%Y-%m-%d")
                    days_overdue = max(0, (datetime.utcnow() - deadline_dt).days)

                if actual_event == "repair_delay":
                    svc.notify_repair_delay(
                        equipment,
                        repair_stage=stage_name,
                        stage_deadline=deadline_str,
                        days_delayed=days_overdue,
                        organization_id=equipment.organization_id,
                        department_id=equipment.department_id,
                    )
                else:
                    dept = getattr(equipment, "department_name", "") or ""
                    svc.fire(
                        event_type=actual_event,
                        context={
                            "equipment":      eq_ueic,
                            "equipment_type": eq_type,
                            "department":     dept,
                            "repair_stage":   stage_name,
                            "stage_deadline": deadline_str,
                            "days_delayed":   str(days_overdue),
                        },
                        organization_id=equipment.organization_id,
                        department_id=equipment.department_id,
                        source_id=workflow.id,
                        source_type="repair_workflow",
                        severity="alert",
                        workflow_type="repair_lifecycle",
                    )

        except Exception as _n:
            print(f"[WARN] notification failed ({event_type}): {_n}")
