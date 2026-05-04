import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from models import (
    Equipment,
    OrgRole,
    OrgUserRole,
    RepairWorkflow,
    RepairStageDefinition,
    RepairStageInstance,
    RepairStageData,
    RepairStageTemplate,
    RepairStageRole,
    RepairStageTransition,
    RepairStageDocument,
    RepairStageAuditLog,
    OrgTestTemplate,
)
from services.validation_service import ValidationService

UPLOADS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads", "repair")


class RepairWorkflowService:
    def __init__(self, db: Session):
        self.db = db

    # =========================================================================
    # RBAC helpers
    # =========================================================================

    def _user_org_role_ids(self, user_id) -> list:
        """Return list of active org_role_ids for a user."""
        return [
            ur.org_role_id
            for ur in self.db.query(OrgUserRole)
            .filter_by(user_id=user_id, is_active=True)
            .all()
        ]

    def _check_stage_rbac(self, stage_id, user_id):
        """
        Verify the user holds a role that is authorized (can_edit) for this stage.
        Raises HTTP 403 if not.
        """
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            raise HTTPException(403, "No org role assigned to this user")

        allowed = (
            self.db.query(RepairStageRole)
            .filter(
                RepairStageRole.stage_id == stage_id,
                RepairStageRole.role_id.in_(role_ids),
                RepairStageRole.can_edit == True,
            )
            .first()
        )
        if not allowed:
            raise HTTPException(403, "Your role is not authorized to act on this stage")
        return allowed

    def _check_can_approve(self, stage_id, user_id):
        """
        Verify the user holds a role that can approve/reject this stage.
        Raises HTTP 403 if not.
        """
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            raise HTTPException(403, "No org role assigned to this user")

        allowed = (
            self.db.query(RepairStageRole)
            .filter(
                RepairStageRole.stage_id == stage_id,
                RepairStageRole.role_id.in_(role_ids),
                RepairStageRole.can_approve == True,
            )
            .first()
        )
        if not allowed:
            raise HTTPException(403, "Your role cannot approve or reject this stage")
        return allowed

    def _check_is_org_admin(self, user_id):
        """
        Verify the user has an org-admin role.
        Used to gate workflow configuration endpoints.
        Raises HTTP 403 if not.
        """
        role_ids = self._user_org_role_ids(user_id)
        admin_role = (
            self.db.query(OrgRole)
            .filter(OrgRole.id.in_(role_ids), OrgRole.is_org_admin == True)
            .first()
        )
        if not admin_role:
            raise HTTPException(403, "Org-admin access required to modify workflow configuration")

    # =========================================================================
    # Admin config
    # =========================================================================

    def list_stages(self) -> list:
        stages = (
            self.db.query(RepairStageDefinition)
            .order_by(RepairStageDefinition.sequence)
            .all()
        )
        result = []
        for s in stages:
            tmpl = self.db.query(RepairStageTemplate).filter_by(stage_id=s.id).first()
            roles = self.db.query(RepairStageRole).filter_by(stage_id=s.id).all()
            transitions = (
                self.db.query(RepairStageTransition)
                .filter_by(from_stage_id=s.id)
                .all()
            )
            result.append(
                {
                    "id": str(s.id),
                    "name": s.name,
                    "code": s.code,
                    "sequence": s.sequence,
                    "weight": s.weight,
                    "is_active": s.is_active,
                    "is_mandatory": s.is_mandatory,
                    "template_id": str(tmpl.template_id) if tmpl else None,
                    "roles": [
                        {
                            "id": str(r.id),
                            "role_id": str(r.role_id),
                            "can_edit": r.can_edit,
                            "can_approve": r.can_approve,
                        }
                        for r in roles
                    ],
                    "transitions": [
                        {
                            "id": str(t.id),
                            "to_stage_id": str(t.to_stage_id) if t.to_stage_id else None,
                            "action": t.action,
                        }
                        for t in transitions
                    ],
                }
            )
        return result

    def create_stage(self, data: dict, user_id) -> RepairStageDefinition:
        self._check_is_org_admin(user_id)
        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            name=data["name"],
            code=data["code"],
            sequence=data["sequence"],
            weight=data.get("weight", 10),
            is_mandatory=data.get("is_mandatory", True),
            is_active=True,
        )
        self.db.add(stage)
        self.db.commit()
        self.db.refresh(stage)
        return stage

    def update_stage(self, stage_id, data: dict, user_id) -> RepairStageDefinition:
        self._check_is_org_admin(user_id)
        stage = self.db.query(RepairStageDefinition).filter_by(id=stage_id).first()
        if not stage:
            raise ValueError("Stage not found")
        for k, v in data.items():
            setattr(stage, k, v)
        stage.modified_at = datetime.utcnow()
        self.db.commit()
        self.db.refresh(stage)
        return stage

    def deactivate_stage(self, stage_id, user_id):
        """Soft-delete: set is_active=False."""
        self._check_is_org_admin(user_id)
        stage = self.db.query(RepairStageDefinition).filter_by(id=stage_id).first()
        if not stage:
            raise ValueError("Stage not found")
        stage.is_active = False
        stage.modified_at = datetime.utcnow()
        self.db.commit()

    def reorder_stages(self, items: list, user_id):
        """items: [{id, sequence}, ...]"""
        self._check_is_org_admin(user_id)
        for item in items:
            stage = self.db.query(RepairStageDefinition).filter_by(id=item["id"]).first()
            if stage:
                stage.sequence = item["sequence"]
                stage.modified_at = datetime.utcnow()
        self.db.commit()

    def set_stage_template(self, stage_id, template_id, user_id):
        self._check_is_org_admin(user_id)
        stage = self.db.query(RepairStageDefinition).filter_by(id=stage_id).first()
        if not stage:
            raise ValueError("Stage not found")
        existing = self.db.query(RepairStageTemplate).filter_by(stage_id=stage_id).first()
        if existing:
            existing.template_id = template_id
        else:
            self.db.add(RepairStageTemplate(stage_id=stage_id, template_id=template_id))
        self.db.commit()

    def set_stage_roles(self, stage_id, roles: list, user_id):
        """Replace all role assignments for a stage."""
        self._check_is_org_admin(user_id)
        self.db.query(RepairStageRole).filter_by(stage_id=stage_id).delete()
        for r in roles:
            self.db.add(
                RepairStageRole(
                    id=uuid.uuid4(),
                    stage_id=stage_id,
                    role_id=r["role_id"],
                    can_edit=r.get("can_edit", True),
                    can_approve=r.get("can_approve", True),
                )
            )
        self.db.commit()

    def list_transitions(self) -> list:
        transitions = self.db.query(RepairStageTransition).all()
        return [
            {
                "id": str(t.id),
                "from_stage_id": str(t.from_stage_id) if t.from_stage_id else None,
                "to_stage_id": str(t.to_stage_id) if t.to_stage_id else None,
                "action": t.action,
            }
            for t in transitions
        ]

    def upsert_transitions(self, transitions: list, user_id):
        self._check_is_org_admin(user_id)
        for t in transitions:
            existing = (
                self.db.query(RepairStageTransition)
                .filter_by(from_stage_id=t["from_stage_id"], action=t["action"])
                .first()
            )
            if existing:
                existing.to_stage_id = t.get("to_stage_id")
            else:
                self.db.add(
                    RepairStageTransition(
                        id=uuid.uuid4(),
                        from_stage_id=t["from_stage_id"],
                        to_stage_id=t.get("to_stage_id"),
                        action=t["action"],
                    )
                )
        self.db.commit()

    # =========================================================================
    # Workflow execution
    # =========================================================================

    def start_workflow(self, equipment_id, user_id) -> RepairWorkflow:
        stages = (
            self.db.query(RepairStageDefinition)
            .filter_by(is_active=True)
            .order_by(RepairStageDefinition.sequence)
            .all()
        )
        if not stages:
            raise ValueError("No active stage definitions found — run seed_workflow first")

        # --- Update equipment status to under_repair ---
        equipment = self.db.query(Equipment).filter_by(id=equipment_id).first()
        if not equipment:
            raise ValueError("Equipment not found")
        equipment.status = "under_repair"

        workflow = RepairWorkflow(
            id=uuid.uuid4(),
            equipment_id=equipment_id,
            current_stage_id=stages[0].id,
            status="active",
            progress=0,
            started_at=datetime.utcnow(),
            created_by=user_id,
            created_at=datetime.utcnow(),
        )
        self.db.add(workflow)
        self.db.flush()

        # Create stage instances — all not_started; first one opened by save_stage_data
        for stage in stages:
            self.db.add(
                RepairStageInstance(
                    id=uuid.uuid4(),
                    workflow_id=workflow.id,
                    stage_id=stage.id,
                    status="not_started",
                    created_by=user_id,
                    created_at=datetime.utcnow(),
                )
            )

        self._log_audit(workflow.id, stages[0].id, "created", user_id)
        self.db.commit()
        self.db.refresh(workflow)
        return workflow

    def list_workflows(self, equipment_id=None, status=None, skip=0, limit=20) -> list:
        q = self.db.query(RepairWorkflow)
        if equipment_id:
            q = q.filter(RepairWorkflow.equipment_id == equipment_id)
        if status:
            q = q.filter(RepairWorkflow.status == status)
        workflows = q.order_by(RepairWorkflow.created_at.desc()).offset(skip).limit(limit).all()
        return [self._workflow_to_dict(wf) for wf in workflows]

    def get_workflow_detail(self, workflow_id) -> dict:
        wf = self._get_workflow(workflow_id)
        instances = (
            self.db.query(RepairStageInstance)
            .filter_by(workflow_id=workflow_id)
            .all()
        )
        stage_ids = [inst.stage_id for inst in instances]
        stage_defs = {
            s.id: s
            for s in self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.id.in_(stage_ids))
            .all()
        }

        result = self._workflow_to_dict(wf)
        result["stages"] = [
            {
                "instance_id": str(inst.id),
                "stage_id": str(inst.stage_id),
                "name": stage_defs[inst.stage_id].name if inst.stage_id in stage_defs else None,
                "sequence": stage_defs[inst.stage_id].sequence if inst.stage_id in stage_defs else 0,
                "status": inst.status,
                "started_at": inst.started_at.isoformat() if inst.started_at else None,
                "completed_at": inst.completed_at.isoformat() if inst.completed_at else None,
                "completed_by": str(inst.completed_by) if inst.completed_by else None,
                "remarks": inst.remarks,
            }
            # Fix: use 0 as default sequence to avoid AttributeError on unresolved stage_id
            for inst in sorted(instances, key=lambda i: stage_defs.get(i.stage_id).sequence if i.stage_id in stage_defs else 0)
        ]
        return result

    def get_current_form(self, workflow_id) -> dict:
        wf = self._get_workflow(workflow_id)
        instance = (
            self.db.query(RepairStageInstance)
            .filter_by(workflow_id=workflow_id, stage_id=wf.current_stage_id)
            .first()
        )
        if not instance:
            raise ValueError("Current stage instance not found")

        tmpl_map = self.db.query(RepairStageTemplate).filter_by(stage_id=wf.current_stage_id).first()
        template_data = {}
        if tmpl_map:
            tmpl = self.db.query(OrgTestTemplate).filter_by(id=tmpl_map.template_id).first()
            if tmpl:
                template_data = tmpl.template_data or {}

        saved_data = (
            self.db.query(RepairStageData).filter_by(stage_instance_id=instance.id).first()
        )
        stage_def = self.db.query(RepairStageDefinition).filter_by(id=wf.current_stage_id).first()

        return {
            "workflow_id": str(workflow_id),
            "stage_id": str(wf.current_stage_id),
            "stage_name": stage_def.name if stage_def else None,
            "stage_code": stage_def.code if stage_def else None,
            "status": instance.status,
            "template": template_data,
            "data": saved_data.form_data if saved_data else {},
        }

    def save_stage_data(self, workflow_id, stage_id, form_data: dict, user_id) -> dict:
        wf = self._get_workflow(workflow_id)

        # --- Stage-level RBAC: user must have an authorized (can_edit) role ---
        self._check_stage_rbac(stage_id, user_id)

        instance = (
            self.db.query(RepairStageInstance)
            .filter_by(workflow_id=workflow_id, stage_id=stage_id)
            .first()
        )
        if not instance:
            raise ValueError("Stage instance not found")
        if instance.status == "completed":
            raise ValueError("Cannot modify a completed stage")
        if str(wf.current_stage_id) != str(stage_id):
            raise ValueError("Only the current active stage can be edited")

        # --- Validation: enforce required fields from template ---
        tmpl_map = self.db.query(RepairStageTemplate).filter_by(stage_id=stage_id).first()
        if tmpl_map:
            tmpl = self.db.query(OrgTestTemplate).filter_by(id=tmpl_map.template_id).first()
            if tmpl and tmpl.template_data:
                ValidationService.validate_stage(tmpl.template_data, form_data)

        # --- Persist ---
        existing = (
            self.db.query(RepairStageData).filter_by(stage_instance_id=instance.id).first()
        )
        if existing:
            existing.form_data = form_data
            existing.modified_by = user_id
            existing.modified_at = datetime.utcnow()
        else:
            self.db.add(
                RepairStageData(
                    id=uuid.uuid4(),
                    stage_instance_id=instance.id,
                    form_data=form_data,
                    created_by=user_id,
                    created_at=datetime.utcnow(),
                )
            )

        # Transition not_started → in_progress on first save
        if instance.status == "not_started":
            instance.status = "in_progress"
            instance.started_at = datetime.utcnow()

        instance.modified_by = user_id
        instance.modified_at = datetime.utcnow()
        self.db.commit()

        return {
            "message": "Saved successfully",
            "stage_id": str(stage_id),
            "status": instance.status,
        }

    def upload_stage_file(
        self, workflow_id, stage_id, field_key, file_name, file_bytes, mime_type, user_id
    ) -> dict:
        wf = self._get_workflow(workflow_id)

        # --- Stage-level RBAC ---
        self._check_stage_rbac(stage_id, user_id)

        instance = (
            self.db.query(RepairStageInstance)
            .filter_by(workflow_id=workflow_id, stage_id=stage_id)
            .first()
        )
        if not instance:
            raise ValueError("Stage instance not found")
        if str(wf.current_stage_id) != str(stage_id):
            raise ValueError("Only the current active stage can receive uploads")

        # Save file to disk
        os.makedirs(UPLOADS_DIR, exist_ok=True)
        unique_name = f"{uuid.uuid4()}_{file_name}"
        file_path = os.path.join(UPLOADS_DIR, unique_name)
        with open(file_path, "wb") as fh:
            fh.write(file_bytes)

        # Record in DB — store relative path so it's portable
        rel_path = os.path.join("uploads", "repair", unique_name)
        doc = RepairStageDocument(
            id=uuid.uuid4(),
            stage_instance_id=instance.id,
            field_key=field_key,
            file_name=file_name,
            file_path=rel_path,
            mime_type=mime_type,
            size_bytes=len(file_bytes),
            uploaded_by=user_id,
            uploaded_at=datetime.utcnow(),
        )
        self.db.add(doc)
        self.db.flush()

        # Patch form_data so the field carries the document reference
        saved_data = (
            self.db.query(RepairStageData).filter_by(stage_instance_id=instance.id).first()
        )
        file_ref = {
            "document_id": str(doc.id),
            "file_name": file_name,
            "rel_path": rel_path,
        }
        if saved_data:
            fd = dict(saved_data.form_data or {})
            fd[field_key] = file_ref
            saved_data.form_data = fd
            saved_data.modified_by = user_id
            saved_data.modified_at = datetime.utcnow()
        else:
            self.db.add(
                RepairStageData(
                    id=uuid.uuid4(),
                    stage_instance_id=instance.id,
                    form_data={field_key: file_ref},
                    created_by=user_id,
                    created_at=datetime.utcnow(),
                )
            )

        self.db.commit()
        return {"document_id": str(doc.id), "file_name": file_name, "field_key": field_key}

    def advance_stage(self, workflow_id, remarks: Optional[str], user_id) -> dict:
        wf = self._get_workflow(workflow_id)
        if wf.status == "completed":
            raise ValueError("Workflow already completed")

        # --- Stage-level RBAC: can_approve ---
        self._check_can_approve(wf.current_stage_id, user_id)

        instance = (
            self.db.query(RepairStageInstance)
            .filter_by(workflow_id=workflow_id, stage_id=wf.current_stage_id)
            .first()
        )
        if not instance:
            raise ValueError("Current stage instance not found")

        # Must have saved data before advancing
        data = self.db.query(RepairStageData).filter_by(stage_instance_id=instance.id).first()
        if not data:
            raise ValueError("Stage data must be saved before advancing")

        # Complete current instance
        instance.status = "completed"
        instance.completed_at = datetime.utcnow()
        instance.completed_by = user_id
        instance.remarks = remarks
        instance.modified_by = user_id
        instance.modified_at = datetime.utcnow()

        self._log_audit(workflow_id, wf.current_stage_id, "approve", user_id, note=remarks)

        # Determine next stage via transition table → sequential fallback
        transition = (
            self.db.query(RepairStageTransition)
            .filter_by(from_stage_id=wf.current_stage_id, action="approve")
            .first()
        )

        if transition and transition.to_stage_id:
            next_stage_id = transition.to_stage_id
        else:
            current_def = self.db.query(RepairStageDefinition).filter_by(id=wf.current_stage_id).first()
            next_def = (
                self.db.query(RepairStageDefinition)
                .filter(
                    RepairStageDefinition.is_active == True,
                    RepairStageDefinition.sequence > current_def.sequence,
                )
                .order_by(RepairStageDefinition.sequence)
                .first()
            )
            next_stage_id = next_def.id if next_def else None

        if next_stage_id:
            wf.current_stage_id = next_stage_id
            # Leave next instance as not_started — it will move to in_progress on first save
            self._log_audit(workflow_id, next_stage_id, "started", user_id)
        else:
            # No next stage → workflow complete; restore equipment to active
            wf.status = "completed"
            wf.completed_at = datetime.utcnow()
            equipment = self.db.query(Equipment).filter_by(id=wf.equipment_id).first()
            if equipment:
                equipment.status = "active"

        all_stages = self.db.query(RepairStageDefinition).filter_by(is_active=True).all()
        wf.progress = self._recalculate_progress(workflow_id, all_stages)
        wf.modified_by = user_id
        wf.modified_at = datetime.utcnow()

        self.db.commit()
        return self._workflow_to_dict(wf)

    def reject_stage(self, workflow_id, remarks: Optional[str], user_id) -> dict:
        wf = self._get_workflow(workflow_id)
        if wf.status == "completed":
            raise ValueError("Workflow already completed")

        # --- Stage-level RBAC: can_approve (reject is also an approval action) ---
        self._check_can_approve(wf.current_stage_id, user_id)

        instance = (
            self.db.query(RepairStageInstance)
            .filter_by(workflow_id=workflow_id, stage_id=wf.current_stage_id)
            .first()
        )
        if not instance:
            raise ValueError("Current stage instance not found")

        # Mark current as rejected
        instance.status = "rejected"
        instance.completed_at = datetime.utcnow()
        instance.completed_by = user_id
        instance.remarks = remarks
        instance.modified_by = user_id
        instance.modified_at = datetime.utcnow()

        self._log_audit(workflow_id, wf.current_stage_id, "reject", user_id, note=remarks)

        # Find previous stage via transition → sequential fallback
        transition = (
            self.db.query(RepairStageTransition)
            .filter_by(from_stage_id=wf.current_stage_id, action="reject")
            .first()
        )

        if transition and transition.to_stage_id:
            prev_stage_id = transition.to_stage_id
        else:
            current_def = self.db.query(RepairStageDefinition).filter_by(id=wf.current_stage_id).first()
            prev_def = (
                self.db.query(RepairStageDefinition)
                .filter(
                    RepairStageDefinition.is_active == True,
                    RepairStageDefinition.sequence < current_def.sequence,
                )
                .order_by(RepairStageDefinition.sequence.desc())
                .first()
            )
            if not prev_def:
                raise ValueError("Cannot go back — already at the first stage")
            prev_stage_id = prev_def.id

        # Reopen previous instance
        prev_inst = (
            self.db.query(RepairStageInstance)
            .filter_by(workflow_id=workflow_id, stage_id=prev_stage_id)
            .first()
        )
        if prev_inst:
            prev_inst.status = "in_progress"
            prev_inst.completed_at = None
            prev_inst.modified_by = user_id
            prev_inst.modified_at = datetime.utcnow()

        wf.current_stage_id = prev_stage_id
        wf.modified_by = user_id
        wf.modified_at = datetime.utcnow()

        all_stages = self.db.query(RepairStageDefinition).filter_by(is_active=True).all()
        wf.progress = self._recalculate_progress(workflow_id, all_stages)

        self.db.commit()
        return self._workflow_to_dict(wf)

    def get_timeline(self, workflow_id) -> list:
        logs = (
            self.db.query(RepairStageAuditLog)
            .filter_by(workflow_id=workflow_id)
            .order_by(RepairStageAuditLog.performed_at)
            .all()
        )
        stage_ids = list({log.stage_id for log in logs if log.stage_id})
        stage_defs = {
            s.id: s
            for s in self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.id.in_(stage_ids))
            .all()
        }
        return [
            {
                "id": str(log.id),
                "stage_id": str(log.stage_id) if log.stage_id else None,
                "stage_name": stage_defs[log.stage_id].name
                if log.stage_id and log.stage_id in stage_defs
                else None,
                "action": log.action,
                "performed_by": str(log.performed_by) if log.performed_by else None,
                "performed_at": log.performed_at.isoformat() if log.performed_at else None,
                "note": log.note,
            }
            for log in logs
        ]

    def get_progress(self, workflow_id) -> dict:
        wf = self._get_workflow(workflow_id)
        stage_def = self.db.query(RepairStageDefinition).filter_by(id=wf.current_stage_id).first()
        return {
            "workflow_id": str(workflow_id),
            "current_stage_id": str(wf.current_stage_id) if wf.current_stage_id else None,
            "current_stage_name": stage_def.name if stage_def else None,
            "progress": wf.progress,
            "status": wf.status,
        }

    def list_stage_documents(self, workflow_id, stage_id) -> list:
        """Return all uploaded documents for a specific stage instance."""
        instance = (
            self.db.query(RepairStageInstance)
            .filter_by(workflow_id=workflow_id, stage_id=stage_id)
            .first()
        )
        if not instance:
            raise ValueError("Stage instance not found")

        docs = (
            self.db.query(RepairStageDocument)
            .filter_by(stage_instance_id=instance.id)
            .order_by(RepairStageDocument.uploaded_at)
            .all()
        )
        return [
            {
                "id": str(d.id),
                "field_key": d.field_key,
                "file_name": d.file_name,
                "mime_type": d.mime_type,
                "size_bytes": d.size_bytes,
                "uploaded_by": str(d.uploaded_by) if d.uploaded_by else None,
                "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
            }
            for d in docs
        ]

    def get_document_file(self, doc_id) -> tuple:
        """Returns (absolute_path, file_name, mime_type) for a document download."""
        doc = self.db.query(RepairStageDocument).filter_by(id=doc_id).first()
        if not doc:
            raise ValueError("Document not found")

        # Resolve relative path to absolute
        base_dir = os.path.dirname(os.path.dirname(__file__))
        abs_path = os.path.join(base_dir, doc.file_path)
        if not os.path.exists(abs_path):
            raise ValueError("File not found on server")

        return abs_path, doc.file_name, doc.mime_type

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _get_workflow(self, workflow_id) -> RepairWorkflow:
        wf = self.db.query(RepairWorkflow).filter_by(id=workflow_id).first()
        if not wf:
            raise ValueError("Workflow not found")
        return wf

    def _log_audit(self, workflow_id, stage_id, action: str, user_id, note: Optional[str] = None):
        self.db.add(
            RepairStageAuditLog(
                id=uuid.uuid4(),
                workflow_id=workflow_id,
                stage_id=stage_id,
                action=action,
                performed_by=user_id,
                performed_at=datetime.utcnow(),
                note=note,
            )
        )

    def _recalculate_progress(self, workflow_id, stages: list) -> int:
        if not stages:
            return 0
        total_weight = sum(s.weight for s in stages)
        if total_weight == 0:
            return 0
        completed_instances = (
            self.db.query(RepairStageInstance)
            .filter_by(workflow_id=workflow_id, status="completed")
            .all()
        )
        completed_stage_ids = {inst.stage_id for inst in completed_instances}
        completed_weight = sum(s.weight for s in stages if s.id in completed_stage_ids)
        return int((completed_weight / total_weight) * 100)

    def _workflow_to_dict(self, wf: RepairWorkflow) -> dict:
        return {
            "id": str(wf.id),
            "equipment_id": str(wf.equipment_id) if wf.equipment_id else None,
            "current_stage_id": str(wf.current_stage_id) if wf.current_stage_id else None,
            "status": wf.status,
            "progress": wf.progress,
            "started_at": wf.started_at.isoformat() if wf.started_at else None,
            "completed_at": wf.completed_at.isoformat() if wf.completed_at else None,
            "created_by": str(wf.created_by) if wf.created_by else None,
            "created_at": wf.created_at.isoformat() if wf.created_at else None,
        }
