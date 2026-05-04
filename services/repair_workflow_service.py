import uuid
from datetime import datetime
from fastapi import HTTPException
from services.validation_service import ValidationService
from models import (
    RepairWorkflow,
    RepairStageDefinition,
    RepairStageInstance,
    RepairStageData,
    RepairStageTemplate,
    OrgTestTemplate,
    TestingRequest
)
class RepairWorkflowService:
    def __init__(self, db):
        self.db = db

    def create_workflow(self, testing_request_id, user_id):

        request = self.db.query(TestingRequest).filter_by(
            id=testing_request_id
        ).first()

        if not request:
            raise ValueError("TestingRequest not found")

        # Get workflow definition (assuming single active)
        stages = self.db.query(RepairStageDefinition).filter_by(
            is_active=True
        ).order_by(RepairStageDefinition.sequence).all()

        if not stages:
            raise ValueError("No stage definitions found")

        workflow = RepairWorkflow(
            id=uuid.uuid4(),
            testing_request_id=testing_request_id,
            current_stage=stages[0].id,
            status="active",
            progress=0,
            created_by=user_id,
            created_at=datetime.utcnow()
        )

        self.db.add(workflow)
        self.db.flush()

        # Create stage instances dynamically
        for stage in stages:
            self.db.add(RepairStageInstance(
                id=uuid.uuid4(),
                workflow_id=workflow.id,
                stage_id=stage.id,
                status="not_started",
                created_by=user_id,
                created_at=datetime.utcnow()
            ))

        self.db.commit()
        return workflow

    def get_workflow(self, workflow_id):
        wf = self.db.query(RepairWorkflow).filter_by(id=workflow_id).first()
        if not wf:
            raise ValueError("Workflow not found")
        return wf

    def get_current_form(self, workflow_id):

        workflow = self.get_workflow(workflow_id)

        stage = self.db.query(RepairStageInstance).filter_by(
            workflow_id=workflow_id,
            stage_id=workflow.current_stage
        ).first()

        # Fetch template mapped to stage
        mapping = self.db.query(RepairStageTemplate).filter_by(
            stage_id=stage.stage_id
        ).first()

        template = None
        if mapping:
            template = self.db.query(OrgTestTemplate).filter_by(
                id=mapping.template_id
            ).first()

        data = self.db.query(RepairStageData).filter_by(
            stage_instance_id=stage.id
        ).first()

        return {
            "stage_id": stage.stage_id,
            "status": stage.status,
            "template": template.template_data if template else {},
            "data": data.form_data if data else {}
        }

    def save_stage_data(self, workflow_id, stage_id, form_data, user_id):

     # 1. Fetch stage instance
        stage = self.db.query(RepairStageInstance).filter_by(
            workflow_id=workflow_id,
            stage_id=stage_id
        ).first()

        if not stage:
            raise ValueError("Stage not found")

        # 2. Prevent editing completed stages
        if stage.status == "completed":
            raise ValueError("Cannot modify a completed stage")

        # 3. Fetch workflow (for current stage check)
        workflow = self.db.query(RepairWorkflow).filter_by(
            id=workflow_id
        ).first()

        if not workflow:
            raise ValueError("Workflow not found")

        # Optional: enforce only current stage editable
        if stage.stage_id != workflow.current_stage:
            raise ValueError("Only current stage can be edited")

        # 4. Fetch template mapped to stage
        mapping = self.db.query(RepairStageTemplate).filter_by(
            stage_id=stage_id
        ).first()

        if not mapping:
            raise ValueError("Template not mapped to stage")

        template = self.db.query(OrgTestTemplate).filter_by(
            id=mapping.template_id
        ).first()

        if not template:
            raise ValueError("Template not found")

        template_data = template.template_data or {}

        # 5. 🔥 VALIDATION (CORE ADDITION)
        from services.validation_service import ValidationService

        ValidationService.validate_stage(template_data, form_data)

        # 6. Save / Update stage data
        existing = self.db.query(RepairStageData).filter_by(
            stage_instance_id=stage.id
        ).first()

        if existing:
            existing.form_data = form_data
            existing.modified_by = user_id
            existing.modified_at = datetime.utcnow()
        else:
            new_data = RepairStageData(
                id=uuid.uuid4(),
                stage_instance_id=stage.id,
                form_data=form_data,
                created_by=user_id,
                created_at=datetime.utcnow()
            )
            self.db.add(new_data)

        # 7. Update stage status
        if stage.status == "not_started":
            stage.status = "in_progress"

        stage.modified_by = user_id
        stage.modified_at = datetime.utcnow()

        # 8. Commit
        self.db.commit()

        return {
            "message": "Saved successfully",
            "stage_id": stage.stage_id,
            "status": stage.status
        }

    def advance_stage(self, workflow_id, user_id):

        workflow = self.get_workflow(workflow_id)

        stages = self.db.query(RepairStageDefinition).filter_by(
            is_active=True
        ).order_by(RepairStageDefinition.sequence).all()

        stage_ids = [s.id for s in stages]

        current_index = stage_ids.index(workflow.current_stage)

        stage_instance = self.db.query(RepairStageInstance).filter_by(
            workflow_id=workflow_id,
            stage_id=workflow.current_stage
        ).first()

        # Validate data exists
        data = self.db.query(RepairStageData).filter_by(
            stage_instance_id=stage_instance.id
        ).first()

        if not data:
            raise ValueError("Fill stage data first")

        # Complete current
        stage_instance.status = "completed"
        stage_instance.completed_at = datetime.utcnow()
        stage_instance.completed_by = user_id

        # Move to next
        if current_index < len(stage_ids) - 1:
            workflow.current_stage = stage_ids[current_index + 1]
        else:
            workflow.status = "completed"

        # Dynamic progress
        completed = self.db.query(RepairStageInstance).filter_by(
            workflow_id=workflow_id,
            status="completed"
        ).count()

        workflow.progress = int((completed / len(stage_ids)) * 100)

        workflow.modified_by = user_id
        workflow.modified_at = datetime.utcnow()

        self.db.commit()

        return workflow

    def reject_stage(self, workflow_id, user_id):

        workflow = self.get_workflow(workflow_id)

        stages = self.db.query(RepairStageDefinition).filter_by(
            is_active=True
        ).order_by(RepairStageDefinition.sequence).all()

        stage_ids = [s.id for s in stages]
        current_index = stage_ids.index(workflow.current_stage)

        if current_index == 0:
            raise ValueError("Cannot go back further")

        workflow.current_stage = stage_ids[current_index - 1]

        workflow.modified_by = user_id
        workflow.modified_at = datetime.utcnow()

        self.db.commit()

        return workflow

    def get_timeline(self, workflow_id):
        stages = self.db.query(RepairStageInstance).filter_by(
            workflow_id=workflow_id
        ).order_by(RepairStageInstance.stage_id).all()

        return [
            {
                "stage_id": s.stage_id,
                "status": s.status,
                "completed_at": s.completed_at,
                "completed_by": s.completed_by
            }
            for s in stages
        ]

    def get_progress(self, workflow_id):
        workflow = self.get_workflow(workflow_id)

        return {
            "current_stage": workflow.current_stage,
            "progress": workflow.progress,
            "status": workflow.status
        }