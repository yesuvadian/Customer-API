"""
DPR (Detailed Project Report) project service.

Thin wrapper around RepairWorkflowService — same shape as
AnnualAuditService: this file owns DprProject-specific concerns (creation,
number generation, org-scoped access, list/detail views), and delegates
every actual stage operation (save/submit/approve/reject/current-form/
timeline/available-actions) straight through to the generic engine.

No new workflow logic lives here — everything about how stages advance,
who can act on them, and what form renders per stage is data (seeded by
seed_dpr_workflow.py), not code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import RepairStageDefinition, RepairWorkflow, RepairWorkflowDefinition, User
from models_dpr import DprProject
from services.repair_workflow_service import RepairWorkflowService

DPR_WORKFLOW_CODE = "DPR_APPROVAL"
DPR_ENTITY_TYPE = "dpr_project"


class DprProjectService:
    def __init__(self, db: Session):
        self.db = db
        self.workflow = RepairWorkflowService(db)

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    # ========================================
    # CREATE
    # ========================================

    def _next_project_number(self) -> str:
        prefix = "DPR"
        today = self._utc_now().strftime("%Y%m%d")
        count = self.db.query(func.count(DprProject.id)).filter(
            DprProject.project_number.like(f"{prefix}-{today}-%")
        ).scalar()
        return f"{prefix}-{today}-{(count or 0) + 1:04d}"

    def create_project(self, data: dict, user: User) -> dict:
        project = DprProject(
            project_number=self._next_project_number(),
            title=data["title"],
            description=data.get("description"),
            project_category=data.get("project_category"),
            organization_id=user.organization_id,
            proposing_department_id=data.get("proposing_department_id"),
            equipment_id=data.get("equipment_id"),
            estimated_cost=data.get("estimated_cost"),
            status="active",
            created_by=user.id,
        )
        self.db.add(project)
        self.db.flush()

        workflow = self._create_runtime_workflow(project, user)
        project.workflow_id = workflow.id
        self._sync_stage(project)
        self.db.commit()
        self.db.refresh(project)
        return self._project_to_dict(project)

    def _create_runtime_workflow(self, project: DprProject, user: User) -> RepairWorkflow:
        wf_def = (
            self.db.query(RepairWorkflowDefinition)
            .filter_by(workflow_code=DPR_WORKFLOW_CODE, is_active=True)
            .first()
        )
        if not wf_def:
            raise ValueError(
                "DPR Approval workflow definition not found. Run seed_dpr_workflow.py first."
            )
        stages = (
            self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.workflow_definition_id == wf_def.id)
            .order_by(RepairStageDefinition.sequence)
            .all()
        )
        if not stages:
            raise ValueError("DPR Approval workflow stages are not configured. Run seed_dpr_workflow.py first.")

        first_stage = stages[0]
        workflow = RepairWorkflow(
            workflow_number=project.project_number,
            workflow_code=DPR_WORKFLOW_CODE,
            entity_type=DPR_ENTITY_TYPE,
            entity_id=project.id,
            equipment_id=project.equipment_id,
            organization_id=project.organization_id,
            current_stage_id=first_stage.id,
            status="active",
            assignment_pending=True,
            progress=0,
            priority="normal",
            created_by=user.id,
        )
        self.db.add(workflow)
        self.db.flush()

        from models import RepairStageInstance

        first_instance = None
        for stage in stages:
            is_first = stage.id == first_stage.id
            instance = RepairStageInstance(
                workflow_id=workflow.id,
                stage_id=stage.id,
                status="pending" if is_first else "not_started",
                assigned_user_id=None,
                assignment_pending=is_first,
                started_at=self._utc_now() if is_first else None,
                created_by=user.id,
            )
            self.db.add(instance)
            self.db.flush()
            if is_first:
                first_instance = instance

        workflow.current_stage_instance_id = first_instance.id if first_instance else None

        from models import RepairStageAuditLog
        self.db.add(
            RepairStageAuditLog(
                workflow_id=workflow.id,
                stage_id=first_stage.id,
                action="created",
                performed_by=user.id,
                note="DPR project workflow started",
            )
        )
        return workflow

    # ========================================
    # GET / LIST
    # ========================================

    def _get_project(self, project_id: UUID, user: User) -> DprProject:
        project = self.db.query(DprProject).filter(DprProject.id == project_id).first()
        if not project:
            raise ValueError("DPR project not found.")
        if user.organization_id and project.organization_id != user.organization_id:
            raise ValueError("Unauthorized DPR project access.")
        return project

    def get_project(self, project_id: UUID, user: User) -> dict:
        project = self._get_project(project_id, user)
        result = self._project_to_dict(project)
        if project.workflow_id:
            result["workflow"] = self.workflow.get_workflow_detail(project.workflow_id)
            result["timeline"] = self.workflow.get_timeline(project.workflow_id)
        return result

    def list_projects(
        self,
        user: User,
        status: Optional[str] = None,
        stage_code: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        q = self.db.query(DprProject)
        if user.organization_id:
            q = q.filter(DprProject.organization_id == user.organization_id)
        if status and status != "all":
            q = q.filter(DprProject.status == status)
        if stage_code:
            q = q.filter(DprProject.current_stage_code == stage_code)
        rows = q.order_by(DprProject.created_at.desc()).offset(skip).limit(limit).all()
        return [self._project_to_dict(r) for r in rows]

    # ========================================
    # STAGE ACTIONS — thin delegation to RepairWorkflowService
    # ========================================

    def current_form(self, project_id: UUID, user: User) -> dict:
        project = self._get_project(project_id, user)
        data = self.workflow.get_current_form(project.workflow_id)
        data["project"] = self._project_to_dict(project)
        return data

    def timeline(self, project_id: UUID, user: User) -> list:
        project = self._get_project(project_id, user)
        return self.workflow.get_timeline(project.workflow_id)

    def available_actions(self, project_id: UUID, user: User) -> dict:
        project = self._get_project(project_id, user)
        return self.workflow.get_available_transitions(project.workflow_id, user.id)

    def eligible_users(self, project_id: UUID, stage_id: UUID, user: User) -> list:
        project = self._get_project(project_id, user)
        return self.workflow.get_eligible_users(project.workflow_id, stage_id, user)

    def assign_stage(self, project_id: UUID, stage_id: UUID, assign_to_user_id: UUID, user: User) -> dict:
        project = self._get_project(project_id, user)
        result = self.workflow.assign_stage_user(project.workflow_id, stage_id, assign_to_user_id, user.id)
        self._sync_stage(project)
        self.db.commit()
        return result

    def save_stage(self, project_id: UUID, stage_id: UUID, form_data: dict, user: User) -> dict:
        project = self._get_project(project_id, user)
        result = self.workflow.save_stage_data(project.workflow_id, stage_id, form_data, user.id)
        self._sync_denormalized_cost(project, form_data)
        self.db.commit()
        return result

    def submit_stage(self, project_id: UUID, stage_id: UUID, remarks: Optional[str], user: User) -> dict:
        project = self._get_project(project_id, user)
        result = self.workflow.submit_stage(project.workflow_id, stage_id, remarks, user.id, form_data=None)
        self._sync_stage(project)
        self.db.commit()
        return result

    def approve_stage(self, project_id: UUID, remarks: Optional[str], user: User) -> dict:
        project = self._get_project(project_id, user)
        result = self.workflow.advance_stage(project.workflow_id, remarks, user.id, action_label="approve")
        self._sync_stage(project)
        self.db.commit()
        return result

    def reject_stage(self, project_id: UUID, remarks: Optional[str], user: User) -> dict:
        project = self._get_project(project_id, user)
        result = self.workflow.reject_stage(project.workflow_id, remarks, user.id)
        self._sync_stage(project)
        self.db.commit()
        return result

    # ========================================
    # INTERNAL HELPERS
    # ========================================

    def _sync_stage(self, project: DprProject) -> None:
        if not project.workflow_id:
            return
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == project.workflow_id).first()
        if workflow and workflow.current_stage_id:
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == workflow.current_stage_id
            ).first()
            project.current_stage_code = stage.code if stage else project.current_stage_code
        elif workflow and workflow.status == "completed":
            project.current_stage_code = "DPR_EXECUTION_TRACKING"
        if workflow and workflow.status in ("completed", "cancelled"):
            project.status = workflow.status

    def _sync_denormalized_cost(self, project: DprProject, form_data: dict) -> None:
        """Mirror total_estimated_cost / approved_amount into DprProject's
        denormalized columns as they're entered, so list/dashboard views
        don't need to reach into RepairStageData JSON. Best-effort — a
        missing/non-numeric value just leaves the existing column alone."""
        if "total_estimated_cost" in form_data:
            try:
                project.estimated_cost = float(form_data["total_estimated_cost"])
            except (TypeError, ValueError):
                pass
        if "approved_amount" in form_data:
            try:
                project.approved_cost = float(form_data["approved_amount"])
            except (TypeError, ValueError):
                pass

    def _project_to_dict(self, project: DprProject) -> dict:
        return {
            "id": str(project.id),
            "project_number": project.project_number,
            "title": project.title,
            "description": project.description,
            "project_category": project.project_category,
            "organization_id": str(project.organization_id) if project.organization_id else None,
            "proposing_department_id": str(project.proposing_department_id) if project.proposing_department_id else None,
            "equipment_id": str(project.equipment_id) if project.equipment_id else None,
            "estimated_cost": float(project.estimated_cost) if project.estimated_cost is not None else None,
            "approved_cost": float(project.approved_cost) if project.approved_cost is not None else None,
            "status": project.status,
            "workflow_id": str(project.workflow_id) if project.workflow_id else None,
            "current_stage_code": project.current_stage_code,
            "created_at": project.created_at.isoformat() if project.created_at else None,
        }
