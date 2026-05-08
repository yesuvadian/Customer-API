"""
repair_workflow_service.py
──────────────────────────
Business logic for the 10-stage transformer repair lifecycle workflow.

Two-layer access control:
  1. Module-level  — handled by global middleware (path /repair-workflows → Module)
  2. Stage-level   — handled here via RepairStageRole (can_edit / can_approve)

Config mutations (create/update/reorder stages, transitions) require org-admin.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import (
    Equipment,
    EquipmentStatus,
    OrgRole,
    OrgUserRole,
    RepairStageAuditLog,
    RepairStageData,
    RepairStageDefinition,
    RepairStageDocument,
    RepairStageInstance,
    RepairStageRole,
    RepairStageTemplate,
    RepairStageTransition,
    RepairWorkflow,
    OrgTestTemplate,
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
        """Return list of OrgRole IDs the user holds."""
        rows = (
            self.db.query(OrgUserRole.org_role_id)
            .filter(OrgUserRole.user_id == user_id)
            .all()
        )
        return [r[0] for r in rows]

    def _check_stage_rbac(self, stage_id: UUID, user_id: UUID) -> None:
        """Raise 403 if the user does not have can_edit on this stage."""
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return  # no org roles → skip (global admin path)
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
        """Raise ValueError if the user does not have can_approve on this stage."""
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return  # global admin bypass
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
        """Raise ValueError if the user is not an org-admin."""
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return  # global admin
        admin_role = (
            self.db.query(OrgRole)
            .filter(
                OrgRole.id.in_(role_ids),
                OrgRole.is_org_admin.is_(True),
            )
            .first()
        )
        if not admin_role:
            raise ValueError("Only org-admin users can perform this configuration action.")

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
                    {
                        "role_id": str(r.role_id),
                        "can_edit": r.can_edit,
                        "can_approve": r.can_approve,
                    }
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
        """items: [{id, sequence}, ...]"""
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
        """Replace all role assignments for a stage."""
        self._check_is_org_admin(user_id)
        stage = self.db.query(RepairStageDefinition).filter(RepairStageDefinition.id == stage_id).first()
        if not stage:
            raise ValueError("Stage not found.")
        # Delete existing
        self.db.query(RepairStageRole).filter(RepairStageRole.stage_id == stage_id).delete()
        # Insert new
        for r in roles:
            self.db.add(RepairStageRole(
                stage_id=stage_id,
                role_id=UUID(str(r["role_id"])),
                can_edit=r.get("can_edit", True),
                can_approve=r.get("can_approve", True),
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
        """Bulk upsert. Each item: {from_stage_id, action, to_stage_id}."""
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

    def start_workflow(self, equipment_id: UUID, user_id: UUID) -> dict:
        """
        Start a new repair workflow for a piece of equipment.
        - Sets equipment.status = under_repair
        - Creates RepairWorkflow + one RepairStageInstance per active stage
        - Current stage = first stage (lowest sequence)
        """
        equipment = self.db.query(Equipment).filter(Equipment.id == equipment_id).first()
        if not equipment:
            raise ValueError("Equipment not found.")

        # Check no active workflow already exists
        existing = (
            self.db.query(RepairWorkflow)
            .filter(
                RepairWorkflow.equipment_id == equipment_id,
                RepairWorkflow.status == "active",
            )
            .first()
        )
        if existing:
            raise ValueError("An active repair workflow already exists for this equipment.")

        stages = (
            self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.is_active.is_(True))
            .order_by(RepairStageDefinition.sequence)
            .all()
        )
        if not stages:
            raise ValueError("No active stage definitions found. Configure stages first.")

        first_stage = stages[0]

        workflow = RepairWorkflow(
            equipment_id=equipment_id,
            current_stage_id=first_stage.id,
            status="active",
            progress=0,
        )
        self.db.add(workflow)
        self.db.flush()

        # Create stage instances for every active stage
        for s in stages:
            inst_status = "in_progress" if s.id == first_stage.id else "not_started"
            self.db.add(RepairStageInstance(
                workflow_id=workflow.id,
                stage_id=s.id,
                status=inst_status,
                started_at=self._utc_now() if s.id == first_stage.id else None,
            ))

        # Mark equipment as under_repair
        equipment.status = EquipmentStatus.under_repair

        self.db.commit()
        self.db.refresh(workflow)

        # Audit log
        self._log_audit(workflow.id, first_stage.id, "started", user_id, "Workflow started")

        return self._workflow_to_dict(workflow)

    def list_workflows(
        self,
        equipment_id: Optional[UUID] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list:
        q = self.db.query(RepairWorkflow)
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

        # Enrich with stage instances
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
            stage_details.append({
                "instance_id": str(inst.id),
                "stage_id": str(inst.stage_id),
                "stage_name": stage.name if stage else None,
                "stage_code": stage.code if stage else None,
                "sequence": stage.sequence if stage else None,
                "status": inst.status,
                "started_at": inst.started_at.isoformat() if inst.started_at else None,
                "completed_at": inst.completed_at.isoformat() if inst.completed_at else None,
                "form_data": data_row.form_data if data_row else {},
            })
        stage_details.sort(key=lambda x: x["sequence"] or 0)
        result["stages"] = stage_details
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

        # Get the template for this stage
        tmpl_link = (
            self.db.query(RepairStageTemplate)
            .filter(RepairStageTemplate.stage_id == workflow.current_stage_id)
            .first()
        )
        template_data = None
        if tmpl_link and tmpl_link.template_id:
            tmpl = self.db.query(OrgTestTemplate).filter(
                OrgTestTemplate.id == tmpl_link.template_id
            ).first()
            if tmpl:
                template_data = tmpl.template_data

        # Get any previously saved form data
        instance = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id == workflow.current_stage_id,
            )
            .first()
        )
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

        return {
            "workflow_id": str(workflow_id),
            "stage_id": str(workflow.current_stage_id),
            "stage_name": stage.name if stage else None,
            "stage_code": stage.code if stage else None,
            "template_data": template_data,
            "saved_form_data": saved_data,
        }

    def save_stage_data(
        self,
        workflow_id: UUID,
        stage_id: UUID,
        form_data: dict,
        user_id: UUID,
    ) -> dict:
        """Save form data for a stage (validated against template)."""
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if str(workflow.current_stage_id) != str(stage_id):
            raise ValueError("Cannot save data for a stage that is not currently active.")

        # RBAC check
        self._check_stage_rbac(stage_id, user_id)

        # Template validation
        tmpl_link = (
            self.db.query(RepairStageTemplate)
            .filter(RepairStageTemplate.stage_id == stage_id)
            .first()
        )
        if tmpl_link and tmpl_link.template_id:
            self._validate_form_data(tmpl_link.template_id, form_data)

        # Get or create stage instance
        instance = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id == stage_id,
            )
            .first()
        )
        if not instance:
            raise ValueError("Stage instance not found.")

        # Upsert form data
        data_row = (
            self.db.query(RepairStageData)
            .filter(RepairStageData.stage_instance_id == instance.id)
            .first()
        )
        if data_row:
            # Merge: existing data + new data (new overwrites existing keys)
            merged = {**(data_row.form_data or {}), **form_data}
            data_row.form_data = merged
        else:
            data_row = RepairStageData(
                stage_instance_id=instance.id,
                form_data=form_data,
                created_by=user_id,
            )
            self.db.add(data_row)

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
        """Upload a file for a specific field in a stage."""
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")

        self._check_stage_rbac(stage_id, user_id)

        instance = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id == stage_id,
            )
            .first()
        )
        if not instance:
            raise ValueError("Stage instance not found.")

        # Save file to disk
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        unique_name = f"{uuid.uuid4()}_{file_name}"
        rel_path = os.path.join(UPLOAD_DIR, unique_name)
        abs_path = os.path.abspath(rel_path)
        with open(abs_path, "wb") as f:
            f.write(file_bytes)

        # Create document record
        doc = RepairStageDocument(
            stage_instance_id=instance.id,
            field_key=field_key,
            file_name=file_name,
            file_path=rel_path,
            mime_type=mime_type,
            size_bytes=len(file_bytes),
        )
        self.db.add(doc)
        self.db.flush()

        # Patch form_data with document reference
        data_row = (
            self.db.query(RepairStageData)
            .filter(RepairStageData.stage_instance_id == instance.id)
            .first()
        )
        doc_ref = {
            "document_id": str(doc.id),
            "file_name": file_name,
            "mime_type": mime_type,
            "size_bytes": len(file_bytes),
        }
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

    def advance_stage(self, workflow_id: UUID, remarks: Optional[str], user_id: UUID) -> dict:
        """
        Approve current stage and advance to the next.
        Uses RepairStageTransition table; falls back to sequential order.
        On final stage, sets equipment.status back to active.
        """
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if workflow.status != "active":
            raise ValueError("Workflow is not active.")

        current_stage_id = workflow.current_stage_id
        self._check_can_approve(current_stage_id, user_id)

        # Mark current instance as completed
        current_inst = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id == current_stage_id,
            )
            .first()
        )
        if current_inst:
            current_inst.status = "completed"
            current_inst.completed_at = self._utc_now()

        self._log_audit(workflow_id, current_stage_id, "approve", user_id, remarks)

        # Find next stage via transition table
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
            # Fallback: sequential order — find next stage after current
            current_stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == current_stage_id
            ).first()
            if current_stage:
                next_stage = (
                    self.db.query(RepairStageDefinition)
                    .filter(
                        RepairStageDefinition.is_active.is_(True),
                        RepairStageDefinition.sequence > current_stage.sequence,
                    )
                    .order_by(RepairStageDefinition.sequence)
                    .first()
                )
                if next_stage:
                    next_stage_id = next_stage.id

        if not next_stage_id:
            # Terminal — workflow complete
            workflow.status = "completed"
            workflow.current_stage_id = None
            workflow.progress = 100

            equipment = self.db.query(Equipment).filter(Equipment.id == workflow.equipment_id).first()
            if equipment:
                equipment.status = EquipmentStatus.active

            self.db.commit()
            self._log_audit(workflow_id, current_stage_id, "completed", user_id, "Workflow completed")

            try:
                from services.notification_service import NotificationService
                if equipment:
                    NotificationService(self.db).notify_overhaul_recommended(
                        equipment,
                        operation_count=workflow.progress,
                        operation_threshold=100,
                        organization_id=equipment.organization_id,
                        department_id=equipment.department_id,
                    )
            except Exception as _n:
                print(f"[WARN] overhaul_recommended notification failed: {_n}")

            return {"message": "Workflow completed", "status": "completed", "progress": 100}

        # Advance to next stage
        workflow.current_stage_id = next_stage_id

        # Mark next instance as in_progress
        next_inst = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id == next_stage_id,
            )
            .first()
        )
        if next_inst:
            next_inst.status = "in_progress"
            next_inst.started_at = self._utc_now()

        # Recalculate progress
        self._recalculate_progress(workflow)
        self.db.commit()

        next_stage = self.db.query(RepairStageDefinition).filter(
            RepairStageDefinition.id == next_stage_id
        ).first()
        self._log_audit(workflow_id, next_stage_id, "started", user_id, "Moved to next stage")

        try:
            from services.notification_service import NotificationService
            equipment = self.db.query(Equipment).filter(Equipment.id == workflow.equipment_id).first()
            if equipment:
                NotificationService(self.db).fire(
                    event_type="repair_stage_changed",
                    context={
                        "equipment": equipment.ueic or str(equipment.id),
                        "equipment_type": equipment.equipment_type.name if equipment.equipment_type else "Equipment",
                        "stage": next_stage.name if next_stage else "Next Stage",
                        "progress": str(workflow.progress),
                    },
                    organization_id=equipment.organization_id,
                    department_id=equipment.department_id,
                    source_id=workflow.id,
                    source_type="repair_workflow",
                    severity="info",
                    workflow_type="repair_lifecycle",
                )
        except Exception as _n:
            print(f"[WARN] repair_stage_changed notification failed: {_n}")

        return {
            "message": "Stage advanced",
            "current_stage": next_stage.name if next_stage else None,
            "progress": workflow.progress,
        }

    def reject_stage(self, workflow_id: UUID, remarks: Optional[str], user_id: UUID) -> dict:
        """
        Reject current stage and move back to the previous.
        Uses RepairStageTransition table; falls back to sequential reverse.
        """
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not workflow:
            raise ValueError("Workflow not found.")
        if workflow.status != "active":
            raise ValueError("Workflow is not active.")

        current_stage_id = workflow.current_stage_id
        self._check_can_approve(current_stage_id, user_id)

        # Mark current instance as rejected
        current_inst = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id == current_stage_id,
            )
            .first()
        )
        if current_inst:
            current_inst.status = "rejected"

        self._log_audit(workflow_id, current_stage_id, "reject", user_id, remarks)

        # Find previous stage via transition table
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
            # Fallback: sequential reverse
            current_stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == current_stage_id
            ).first()
            if current_stage:
                prev_stage = (
                    self.db.query(RepairStageDefinition)
                    .filter(
                        RepairStageDefinition.is_active.is_(True),
                        RepairStageDefinition.sequence < current_stage.sequence,
                    )
                    .order_by(RepairStageDefinition.sequence.desc())
                    .first()
                )
                if prev_stage:
                    prev_stage_id = prev_stage.id

        if not prev_stage_id:
            raise ValueError("Cannot reject — already at the first stage.")

        # Revert previous instance to in_progress
        prev_inst = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id == prev_stage_id,
            )
            .first()
        )
        if prev_inst:
            prev_inst.status = "in_progress"
            prev_inst.completed_at = None

        workflow.current_stage_id = prev_stage_id
        self._recalculate_progress(workflow)
        self.db.commit()

        prev_stage = self.db.query(RepairStageDefinition).filter(
            RepairStageDefinition.id == prev_stage_id
        ).first()

        try:
            from services.notification_service import NotificationService
            equipment = self.db.query(Equipment).filter(Equipment.id == workflow.equipment_id).first()
            rejected_stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == current_stage_id
            ).first()
            if equipment:
                NotificationService(self.db).notify_repair_delay(
                    equipment,
                    repair_stage=rejected_stage.name if rejected_stage else "Unknown Stage",
                    stage_deadline="-",
                    days_delayed=0,
                    organization_id=equipment.organization_id,
                    department_id=equipment.department_id,
                )
        except Exception as _n:
            print(f"[WARN] repair_delay notification failed: {_n}")

        return {
            "message": "Stage rejected — returned to previous stage",
            "current_stage": prev_stage.name if prev_stage else None,
            "progress": workflow.progress,
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
            result.append({
                "id": str(log.id),
                "action": log.action,
                "stage_name": stage.name if stage else None,
                "performed_by": str(log.performed_by) if log.performed_by else None,
                "note": log.note,
                "performed_at": log.performed_at.isoformat() if log.performed_at else None,
            })
        return result

    # =========================================================================
    # Documents
    # =========================================================================

    def list_stage_documents(self, workflow_id: UUID, stage_id: UUID) -> list:
        instance = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id == stage_id,
            )
            .first()
        )
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
        """Returns (abs_path, file_name, mime_type)."""
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

    def _recalculate_progress(self, workflow: RepairWorkflow) -> None:
        """Weight-based progress: completed_weight / total_active_weight * 100."""
        stages = (
            self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.is_active.is_(True))
            .all()
        )
        stage_map = {s.id: s for s in stages}
        total_weight = sum(s.weight for s in stages)
        if total_weight == 0:
            workflow.progress = 0
            return

        instances = (
            self.db.query(RepairStageInstance)
            .filter(RepairStageInstance.workflow_id == workflow.id)
            .all()
        )
        completed_weight = sum(
            stage_map[inst.stage_id].weight
            for inst in instances
            if inst.status == "completed" and inst.stage_id in stage_map
        )
        workflow.progress = int(completed_weight / total_weight * 100)

    def _log_audit(
        self,
        workflow_id: UUID,
        stage_id: Optional[UUID],
        action: str,
        performed_by: UUID,
        note: Optional[str] = None,
    ) -> None:
        log = RepairStageAuditLog(
            workflow_id=workflow_id,
            stage_id=stage_id,
            action=action,
            performed_by=performed_by,
            note=note,
            performed_at=self._utc_now(),
        )
        self.db.add(log)
        # Don't commit here — caller commits after all changes

    def _workflow_to_dict(self, workflow: RepairWorkflow) -> dict:
        equipment = self.db.query(Equipment).filter(Equipment.id == workflow.equipment_id).first()
        current_stage = None
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
        return {
            "id": str(workflow.id),
            "equipment_id": str(workflow.equipment_id),
            "equipment_ueic": equipment.ueic if equipment else None,
            "source_failure_id": str(workflow.source_failure_id) if workflow.source_failure_id else None,
            "status": workflow.status,
            "progress": workflow.progress,
            "current_stage": current_stage,
            "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
        }

    def _validate_form_data(self, template_id: UUID, form_data: dict) -> None:
        """Validate required fields from template. Raises ValueError if invalid."""
        template = self.db.query(OrgTestTemplate).filter(OrgTestTemplate.id == template_id).first()
        if not template or not template.template_data:
            return  # No template to validate against

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
                # File fields are stored as dict references
                if field_type == "file":
                    if not val or not isinstance(val, dict):
                        errors.append(f"{label} (file upload) is required.")
                elif val is None or str(val).strip() == "":
                    errors.append(f"{label} is required.")

        if errors:
            raise ValueError("; ".join(errors))
