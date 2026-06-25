from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    CategoryDetails,
    CategoryMaster,
    Equipment,
    OrgRole,
    OrgUserRole,
    OrgTestTemplate,
    RepairAssignmentQueue,
    RepairStageAuditLog,
    RepairStageDefinition,
    RepairStageInstance,
    RepairWorkflow,
    RepairWorkflowDefinition,
    TAQCAnnualInspection,
    TAQCObservation,
    User,
)
from services.repair_workflow_service import RepairWorkflowService
from services.org_test_template_service import active_template_filter


ANNUAL_AUDIT_WORKFLOW_CODE = "ANNUAL_AUDIT"
ANNUAL_AUDIT_ENTITY_TYPE = "annual_audit_observation"

# Semantic action label per stage — used in audit log for meaningful timeline display
STAGE_ACTION_LABELS: dict[str, str] = {
    "OBSERVATION_REPORTING": "assign",
    "OBSERVATION_ASSIGNMENT": "submit",
    "COMPLIANCE_SUBMISSION": "review",
    "COMPLIANCE_REVIEW": "approve",
    "OBSERVATION_CLOSURE": "close",
}

# Stage codes in workflow order — used for DB queries only, not for seeding
ANNUAL_AUDIT_STAGE_CODES = [
    "OBSERVATION_REPORTING",
    "OBSERVATION_ASSIGNMENT",
    "COMPLIANCE_SUBMISSION",
    "COMPLIANCE_REVIEW",
    "OBSERVATION_CLOSURE",
]

ANNUAL_AUDIT_CATEGORIES = [
    ("Electrical Safety", "audit_electrical_safety"),
    ("Civil", "audit_civil"),
    ("Fire Safety", "audit_fire_safety"),
    ("Documentation", "audit_documentation"),
    ("Environmental", "audit_environmental"),
    ("General Maintenance", "audit_general_maintenance"),
]


class AnnualAuditService:
    def __init__(self, db: Session):
        self.db = db
        self.workflow = RepairWorkflowService(db)

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def ensure_configuration(self, organization_id: Optional[UUID] = None) -> None:
        """
        Verify that annual audit stages exist in DB (seeded via seed_annual_audit.py)
        and wire up org-specific role mappings for the given organization.

        Stage definitions and transitions are seeded once by seed_annual_audit_stages()
        during database setup — this method no longer owns that data.
        """
        missing = (
            self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.code.in_(ANNUAL_AUDIT_STAGE_CODES))
            .count()
        )
        if missing < len(ANNUAL_AUDIT_STAGE_CODES):
            raise ValueError(
                "Annual Audit workflow stages are not seeded. "
                "Run seed_annual_audit_stages(db) first."
            )

        # Re-run stage template seeding (idempotent) so that new templates added
        # to ANNUAL_AUDIT_STAGE_TEMPLATES.json / ANNUAL_AUDIT_STAGE_TEMPLATE_MAP.json
        # are picked up without a full seed restart.
        from seed_annual_audit import seed_annual_audit_stages
        seed_annual_audit_stages(self.db)

        if organization_id:
            from seed_annual_audit import seed_annual_audit_role_mappings
            seed_annual_audit_role_mappings(self.db, organization_id)

    def create_inspection(self, data: dict, user: User) -> dict:
        self.ensure_configuration(user.organization_id)
        dept_id = data.get("department_id") or getattr(user, "department_id", None)
        inspection = TAQCAnnualInspection(
            inspection_number=self._next_number("TR-ANU-INSP"),
            organization_id=user.organization_id,
            department_id=dept_id,
            inspection_date=data["inspection_date"],
            inspected_by=data.get("inspected_by") or user.id,
            remarks=data.get("remarks"),
            created_by=user.id,
        )
        self.db.add(inspection)
        self.db.commit()
        self.db.refresh(inspection)
        return self._inspection_to_dict(inspection)

    def list_inspections(self, user: User, skip: int = 0, limit: int = 100) -> list[dict]:
        q = self.db.query(TAQCAnnualInspection)
        if user.organization_id:
            q = q.filter(TAQCAnnualInspection.organization_id == user.organization_id)
        rows = q.order_by(TAQCAnnualInspection.cts.desc()).offset(skip).limit(limit).all()
        return [self._inspection_to_dict(row) for row in rows]

    def get_inspection(self, inspection_id: UUID, user: User) -> dict:
        inspection = self._get_inspection(inspection_id, user)
        result = self._inspection_to_dict(inspection)
        result["observations"] = [self._observation_to_dict(obs) for obs in inspection.observations]
        return result

    def create_observation(self, inspection_id: UUID, data: dict, user: User) -> dict:
        self.ensure_configuration(user.organization_id)
        inspection = self._get_inspection(inspection_id, user)
        category_id = int(data["category_detail_id"])

        # Validate that the category belongs to Annual Audit Categories and has a template
        valid_category = (
            self.db.query(CategoryDetails)
            .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
            .filter(
                CategoryDetails.id == category_id,
                CategoryDetails.category_type == "annual_audit",
                CategoryMaster.name == "Annual Audit Categories",
            )
            .first()
        )
        if not valid_category:
            raise ValueError(
                f"category_detail_id {category_id} is not a valid Annual Audit category. "
                "Use GET /category_details/details/by-master/Annual Audit Categories to list valid IDs."
            )

        template = self._resolve_template(category_id)
        if not template:
            raise ValueError(
                f"No audit template found for category '{valid_category.name}' (id={category_id}). "
                "Run POST /annual-audits/config/ensure to initialise templates."
            )

        observation = TAQCObservation(
            inspection_id=inspection.id,
            observation_number=self._next_number("TR-ANU"),
            category_detail_id=category_id,
            template_id=template.id if template else None,
            severity=data.get("severity"),
            target_compliance_date=data.get("target_compliance_date"),
            observation_description=data.get("observation_description"),
            current_stage_code="OBSERVATION_REPORTING",
            created_by=user.id,
        )
        self.db.add(observation)
        self.db.flush()

        workflow = self._create_runtime_workflow(inspection, observation, user)
        observation.workflow_id = workflow.id
        self.db.commit()
        self.db.refresh(observation)
        return self._observation_to_dict(observation)

    def list_observations(
        self,
        user: User,
        status: Optional[str] = None,
        assigned_to_me: bool = False,
        overdue: Optional[bool] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        q = self.db.query(TAQCObservation).join(TAQCAnnualInspection)
        if user.organization_id:
            q = q.filter(TAQCAnnualInspection.organization_id == user.organization_id)
        if status and status != "all":
            if status == "closed":
                q = q.filter(TAQCObservation.current_stage_code == "OBSERVATION_CLOSURE")
            elif status == "open":
                q = q.filter(TAQCObservation.current_stage_code != "OBSERVATION_CLOSURE")
            else:
                q = q.filter(TAQCObservation.current_stage_code == status)
        if assigned_to_me:
            q = q.filter(TAQCObservation.assigned_to == user.id)
        if overdue is not None:
            q = q.filter(TAQCObservation.is_overdue.is_(overdue))
        rows = q.order_by(TAQCObservation.cts.desc()).offset(skip).limit(limit).all()
        return [self._observation_to_dict(row) for row in rows]

    def get_observation(self, observation_id: UUID, user: User) -> dict:
        observation = self._get_observation(observation_id, user)
        result = self._observation_to_dict(observation)
        if observation.workflow_id:
            result["workflow"] = self.workflow.get_workflow_detail(observation.workflow_id)
            result["timeline"] = self.workflow.get_timeline(observation.workflow_id)
        return result

    def current_form(self, observation_id: UUID, user: User) -> dict:
        observation = self._get_observation(observation_id, user)
        data = self.workflow.get_current_form(observation.workflow_id)
        if not data.get("template_data") and observation.template:
            data["template_data"] = observation.template.template_data
        data["observation"] = self._observation_to_dict(observation)
        return data

    def timeline(self, observation_id: UUID, user: User) -> list:
        observation = self._get_observation(observation_id, user)
        return self.workflow.get_timeline(observation.workflow_id)

    def available_actions(self, observation_id: UUID, user: User) -> dict:
        observation = self._get_observation(observation_id, user)
        return self.workflow.get_available_transitions(observation.workflow_id, user.id)

    def assignment_queue(self, user: User) -> list[dict]:
        q = (
            self.db.query(RepairWorkflow)
            .filter(
                RepairWorkflow.workflow_code == ANNUAL_AUDIT_WORKFLOW_CODE,
                RepairWorkflow.status == "active",
                RepairWorkflow.assignment_pending.is_(True),
            )
            .order_by(RepairWorkflow.created_at.asc())
        )
        rows = q.all()
        result = []
        for workflow in rows:
            observation = (
                self.db.query(TAQCObservation)
                .filter(TAQCObservation.workflow_id == workflow.id)
                .first()
            )
            if not observation or (user.organization_id and observation.inspection.organization_id != user.organization_id):
                continue
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == workflow.current_stage_id
            ).first()
            inst = self.workflow._get_instance(workflow.id, workflow.current_stage_id)
            result.append({
                "workflow_id": str(workflow.id),
                "observation_id": str(observation.id),
                "observation_number": observation.observation_number,
                "severity": observation.severity,
                "target_compliance_date": observation.target_compliance_date.isoformat() if observation.target_compliance_date else None,
                "pending_stage": {
                    "stage_id": str(stage.id) if stage else None,
                    "stage_name": stage.name if stage else None,
                    "stage_code": stage.code if stage else None,
                    "instance_status": inst.status if inst else None,
                },
                "created_at": workflow.created_at.isoformat() if workflow.created_at else None,
            })
        return result

    def eligible_users(self, observation_id: UUID, stage_id: UUID, user: User) -> list:
        observation = self._get_observation(observation_id, user)
        return self.workflow.get_eligible_users(observation.workflow_id, stage_id, user)

    def assign_stage(self, observation_id: UUID, stage_id: UUID, assign_to_user_id: UUID, user: User) -> dict:
        observation = self._get_observation(observation_id, user)
        result = self.workflow.assign_stage_user(observation.workflow_id, stage_id, assign_to_user_id, user.id)
        observation.assigned_to = assign_to_user_id
        self._sync_stage(observation)
        self.db.commit()
        return result

    def save_stage(self, observation_id: UUID, stage_id: UUID, form_data: dict, user: User) -> dict:
        observation = self._get_observation(observation_id, user)
        return self.workflow.save_stage_data(observation.workflow_id, stage_id, form_data, user.id)

    def submit_stage(self, observation_id: UUID, stage_id: UUID, remarks: Optional[str], user: User) -> dict:
        observation = self._get_observation(observation_id, user)
        result = self.workflow.submit_stage(observation.workflow_id, stage_id, remarks, user.id)
        self._sync_stage(observation)
        self.db.commit()
        return result

    def approve_stage(self, observation_id: UUID, remarks: Optional[str], user: User) -> dict:
        observation = self._get_observation(observation_id, user)
        action_label = STAGE_ACTION_LABELS.get(observation.current_stage_code or "", "approve")
        result = self.workflow.advance_stage(observation.workflow_id, remarks, user.id, action_label=action_label)
        observation.reviewer_id = user.id
        self._sync_stage(observation)
        self.db.commit()
        return result

    def reject_stage(self, observation_id: UUID, remarks: Optional[str], user: User) -> dict:
        observation = self._get_observation(observation_id, user)
        result = self.workflow.reject_stage(observation.workflow_id, remarks, user.id)
        observation.reviewer_id = user.id
        self._sync_stage(observation)
        self.db.commit()
        return result

    # Escalation roles (design §14F) — updated to new functional role names
    _ESCALATION_ROLES = ["Reviewing Officer", "Supervisory Officer", "Senior Management Approver"]

    def _get_escalation_users(self, organization_id) -> list:
        """Return users that hold any of the three escalation roles in the org."""
        if not organization_id:
            return []
        roles = (
            self.db.query(OrgRole)
            .filter(
                OrgRole.organization_id == organization_id,
                OrgRole.name.in_(self._ESCALATION_ROLES),
            )
            .all()
        )
        role_ids = [r.id for r in roles]
        if not role_ids:
            return []
        return (
            self.db.query(User)
            .join(OrgUserRole, OrgUserRole.user_id == User.id)
            .filter(OrgUserRole.org_role_id.in_(role_ids))
            .all()
        )

    def run_overdue_check(self, user: User) -> dict:
        from services.notification_service import NotificationService

        today = date.today()
        q = self.db.query(TAQCObservation).join(TAQCAnnualInspection)
        if user.organization_id:
            q = q.filter(TAQCAnnualInspection.organization_id == user.organization_id)
        rows = q.all()
        updated = 0
        newly_overdue: list[TAQCObservation] = []

        for obs in rows:
            overdue = bool(
                obs.target_compliance_date
                and today > obs.target_compliance_date
                and obs.current_stage_code != "OBSERVATION_CLOSURE"
            )
            if obs.is_overdue != overdue:
                obs.is_overdue = overdue
                updated += 1
                if overdue:
                    newly_overdue.append(obs)

        self.db.commit()

        # ── Escalation notifications for newly-overdue observations ──────────
        for obs in newly_overdue:
            inspection = self.db.query(TAQCAnnualInspection).filter(
                TAQCAnnualInspection.id == obs.inspection_id
            ).first()
            org_id = inspection.organization_id if inspection else None
            days_overdue = (today - obs.target_compliance_date).days if obs.target_compliance_date else 0
            due_str = obs.target_compliance_date.isoformat() if obs.target_compliance_date else ""
            escalation_users = self._get_escalation_users(org_id)
            if escalation_users:
                try:
                    svc = NotificationService(self.db)
                    svc.notify_taqc_observation_overdue(
                        obs,
                        compliance_due_date=due_str,
                        days_overdue=days_overdue,
                        organization_id=org_id,
                        department_id=getattr(inspection, "department_id", None),
                    )
                except Exception:
                    pass  # Non-fatal — overdue flag already committed

        return {"updated": updated, "escalations_sent": len(newly_overdue)}

    def dashboard(self, user: User) -> dict:
        q = self.db.query(TAQCObservation).join(TAQCAnnualInspection)
        if user.organization_id:
            q = q.filter(TAQCAnnualInspection.organization_id == user.organization_id)
        rows = q.all()
        total = len(rows)
        closed = len([r for r in rows if r.current_stage_code == "OBSERVATION_CLOSURE"])
        overdue = len([r for r in rows if r.is_overdue])

        # Category-wise pending breakdown (design §14I)
        category_breakdown: dict[str, int] = {}
        severity_breakdown: dict[str, int] = {"Major": 0, "Minor": 0, "Advisory": 0}
        pending_days_list: list[int] = []
        today = date.today()

        for r in rows:
            if r.current_stage_code != "OBSERVATION_CLOSURE":
                # Category breakdown
                cat_name = r.category.name if r.category else "Unknown"
                category_breakdown[cat_name] = category_breakdown.get(cat_name, 0) + 1
                # Severity breakdown
                sev = r.severity or "Unknown"
                if sev in severity_breakdown:
                    severity_breakdown[sev] += 1
                else:
                    severity_breakdown[sev] = severity_breakdown.get(sev, 0) + 1
                # Pending days
                if r.cts:
                    days = (today - r.cts.date()).days
                    pending_days_list.append(days)

        avg_pending_days = round(sum(pending_days_list) / len(pending_days_list), 1) if pending_days_list else 0
        max_pending_days = max(pending_days_list) if pending_days_list else 0

        return {
            "total_observations": total,
            "open_observations": total - closed,
            "closed_observations": closed,
            "overdue_observations": overdue,
            "compliance_percentage": round((closed / total) * 100, 2) if total else 0,
            "category_breakdown": category_breakdown,
            "severity_breakdown": severity_breakdown,
            "avg_pending_days": avg_pending_days,
            "max_pending_days": max_pending_days,
        }

    def _create_runtime_workflow(
        self,
        inspection: TAQCAnnualInspection,
        observation: TAQCObservation,
        user: User,
    ) -> RepairWorkflow:
        wf_def = (
            self.db.query(RepairWorkflowDefinition)
            .filter_by(workflow_code=ANNUAL_AUDIT_WORKFLOW_CODE, is_active=True)
            .first()
        )
        if not wf_def:
            raise ValueError(
                "Annual Audit workflow definition not found. Run seed.py first."
            )
        stages = (
            self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.workflow_definition_id == wf_def.id)
            .order_by(RepairStageDefinition.sequence)
            .all()
        )
        if not stages:
            raise ValueError("Annual Audit workflow stages are not configured. Run seed.py first.")

        first_stage = stages[0]
        workflow = RepairWorkflow(
            workflow_number=observation.observation_number,
            workflow_code=ANNUAL_AUDIT_WORKFLOW_CODE,
            entity_type=ANNUAL_AUDIT_ENTITY_TYPE,
            entity_id=observation.id,
            equipment_id=None,
            organization_id=inspection.organization_id,
            current_stage_id=first_stage.id,
            status="active",
            assignment_pending=False,
            progress=0,
            priority="normal",
            created_by=user.id,
        )
        self.db.add(workflow)
        self.db.flush()

        first_instance = None
        for stage in stages:
            is_first = stage.id == first_stage.id
            inst = RepairStageInstance(
                workflow_id=workflow.id,
                stage_id=stage.id,
                status="not_started",
                assigned_user_id=None,
                assignment_pending=is_first,
                started_at=None,
                created_by=user.id,
            )
            self.db.add(inst)
            self.db.flush()
            if is_first:
                first_instance = inst

        workflow.current_stage_instance_id = first_instance.id if first_instance else None
        workflow.assignment_pending = True
        self.db.add(
            RepairStageAuditLog(
                workflow_id=workflow.id,
                stage_id=first_stage.id,
                action="created",
                performed_by=user.id,
                note="Annual Audit observation workflow started",
            )
        )
        return workflow

    def _sync_stage(self, observation: TAQCObservation) -> None:
        if not observation.workflow_id:
            return
        workflow = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == observation.workflow_id).first()
        if workflow and workflow.current_stage_id:
            stage = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == workflow.current_stage_id
            ).first()
            observation.current_stage_code = stage.code if stage else observation.current_stage_code
        elif workflow and workflow.status == "completed":
            observation.current_stage_code = "OBSERVATION_CLOSURE"

    def _next_number(self, prefix: str) -> str:
        today = self._utc_now().strftime("%Y%m%d")
        if prefix.endswith("INSP"):
            count = self.db.query(func.count(TAQCAnnualInspection.id)).filter(
                TAQCAnnualInspection.inspection_number.like(f"{prefix}-{today}-%")
            ).scalar()
        else:
            count = self.db.query(func.count(TAQCObservation.id)).filter(
                TAQCObservation.observation_number.like(f"{prefix}-{today}-%")
            ).scalar()
        return f"{prefix}-{today}-{(count or 0) + 1:04d}"

    def _resolve_template(self, category_detail_id: int) -> Optional[OrgTestTemplate]:
        return (
            self.db.query(OrgTestTemplate)
            .filter(
                OrgTestTemplate.test_type_id == category_detail_id,
                OrgTestTemplate.org_id.is_(None),
                active_template_filter(),
            )
            .order_by(OrgTestTemplate.version.desc())
            .first()
        )

    def _get_department(self, department_id: UUID, user: User):
        from models import OrgDepartment
        dept = self.db.query(OrgDepartment).filter(OrgDepartment.id == department_id).first()
        if not dept:
            raise ValueError("Department/substation not found.")
        return dept

    def _get_inspection(self, inspection_id: UUID, user: User) -> TAQCAnnualInspection:
        inspection = self.db.query(TAQCAnnualInspection).filter(TAQCAnnualInspection.id == inspection_id).first()
        if not inspection:
            raise ValueError("Annual inspection not found.")
        if user.organization_id and inspection.organization_id != user.organization_id:
            raise ValueError("Unauthorized inspection access.")
        return inspection

    def _get_observation(self, observation_id: UUID, user: User) -> TAQCObservation:
        observation = self.db.query(TAQCObservation).filter(TAQCObservation.id == observation_id).first()
        if not observation:
            raise ValueError("Annual audit observation not found.")
        if user.organization_id and observation.inspection.organization_id != user.organization_id:
            raise ValueError("Unauthorized observation access.")
        return observation

    def _inspection_to_dict(self, inspection: TAQCAnnualInspection) -> dict:
        return {
            "id": str(inspection.id),
            "inspection_number": inspection.inspection_number,
            "organization_id": str(inspection.organization_id),
            "department_id": str(inspection.department_id) if inspection.department_id else None,
            "department_name": inspection.department.name if inspection.department else None,
            "inspection_date": inspection.inspection_date.isoformat() if inspection.inspection_date else None,
            "inspected_by": str(inspection.inspected_by) if inspection.inspected_by else None,
            "remarks": inspection.remarks,
            "created_at": inspection.cts.isoformat() if inspection.cts else None,
        }

    def _observation_to_dict(self, observation: TAQCObservation) -> dict:
        return {
            "id": str(observation.id),
            "inspection_id": str(observation.inspection_id),
            "inspection_number": observation.inspection.inspection_number if observation.inspection else None,
            "observation_number": observation.observation_number,
            "category_detail_id": observation.category_detail_id,
            "category_name": observation.category.name if observation.category else None,
            "template_id": str(observation.template_id) if observation.template_id else None,
            "workflow_id": str(observation.workflow_id) if observation.workflow_id else None,
            "severity": observation.severity,
            "target_compliance_date": observation.target_compliance_date.isoformat() if observation.target_compliance_date else None,
            "observation_description": observation.observation_description,
            "current_stage_code": observation.current_stage_code,
            "assigned_to": str(observation.assigned_to) if observation.assigned_to else None,
            "assigned_to_name": (
                f"{observation.assignee.firstname} {observation.assignee.lastname}"
                if observation.assignee else None
            ),
            "reviewer_id": str(observation.reviewer_id) if observation.reviewer_id else None,
            "is_overdue": observation.is_overdue,
            "department_id": str(observation.inspection.department_id) if observation.inspection and observation.inspection.department_id else None,
            "department_name": observation.inspection.department.name if observation.inspection and observation.inspection.department else None,
            "created_at": observation.cts.isoformat() if observation.cts else None,
        }

    # Shared sections appended to every category template
    _COMPLIANCE_SECTION = {
        "title": "Compliance",
        "fields": [
            {"key": "corrective_action", "type": "textarea", "label": "Corrective Action", "required": False},
            {"key": "compliance_evidence", "type": "file", "label": "Compliance Evidence", "required": False},
            {"key": "review_remarks", "type": "textarea", "label": "Review Remarks", "required": False},
        ],
    }
    _ASSESSMENT_SECTION = {
        "title": "Observation Assessment",
        "fields": [
            {
                "key": "observation_description",
                "type": "textarea",
                "label": "Observation Description",
                "required": True,
            },
            {
                "key": "severity",
                "type": "dropdown",
                "label": "Severity",
                "options": ["Major", "Minor", "Advisory"],
                "required": True,
            },
            {
                "key": "target_compliance_date",
                "type": "date",
                "label": "Target Compliance Date",
                "required": True,
            },
            {
                "key": "overall_result",
                "type": "dropdown",
                "label": "Overall Result",
                "options": ["Compliant", "Non-Compliant", "Conditional"],
                "required": True,
            },
        ],
    }

    _CATEGORY_SPECIFIC_SECTIONS: dict[str, list[dict]] = {
        "Electrical Safety": [
            {
                "title": "Earthing System",
                "fields": [
                    {
                        "key": "earthing_condition",
                        "type": "dropdown",
                        "label": "Earthing Condition",
                        "options": ["Good", "Damaged", "Corroded"],
                        "required": True,
                    },
                    {"key": "earthing_resistance", "type": "number", "label": "Earthing Resistance (ohms)"},
                    {"key": "earthing_photo", "type": "file", "label": "Earthing Photograph"},
                ],
            },
            {
                "title": "Safety Protection",
                "fields": [
                    {"key": "danger_board_available", "type": "boolean", "label": "Danger Board Available"},
                    {"key": "shock_hazard_observed", "type": "boolean", "label": "Shock Hazard Observed"},
                    {"key": "safety_remarks", "type": "textarea", "label": "Safety Remarks"},
                ],
            },
        ],
        "Fire Safety": [
            {
                "title": "Fire Safety Equipment",
                "fields": [
                    {"key": "fire_extinguisher_available", "type": "boolean", "label": "Fire Extinguisher Available"},
                    {"key": "fire_extinguisher_expiry", "type": "date", "label": "Fire Extinguisher Expiry Date"},
                    {"key": "fire_alarm_operational", "type": "boolean", "label": "Fire Alarm Operational"},
                    {"key": "oil_leakage_present", "type": "boolean", "label": "Oil Leakage Present"},
                    {"key": "fire_safety_photo", "type": "file", "label": "Fire Safety Photograph"},
                ],
            },
        ],
        "Civil": [
            {
                "title": "Civil Infrastructure",
                "fields": [
                    {
                        "key": "boundary_wall_condition",
                        "type": "dropdown",
                        "label": "Boundary Wall Condition",
                        "options": ["Good", "Minor Cracks", "Major Cracks", "Damaged"],
                    },
                    {
                        "key": "floor_condition",
                        "type": "dropdown",
                        "label": "Floor Condition",
                        "options": ["Good", "Minor Damage", "Major Damage"],
                    },
                    {"key": "drainage_adequate", "type": "boolean", "label": "Drainage Adequate"},
                    {"key": "civil_photo", "type": "file", "label": "Civil Photograph"},
                    {"key": "civil_remarks", "type": "textarea", "label": "Civil Remarks"},
                ],
            },
        ],
        "Documentation": [
            {
                "title": "Documentation Compliance",
                "fields": [
                    {"key": "log_books_updated", "type": "boolean", "label": "Log Books Updated"},
                    {"key": "single_line_diagram_available", "type": "boolean", "label": "Single Line Diagram Available"},
                    {"key": "maintenance_records_updated", "type": "boolean", "label": "Maintenance Records Updated"},
                    {"key": "test_certificates_available", "type": "boolean", "label": "Test Certificates Available"},
                    {"key": "documentation_remarks", "type": "textarea", "label": "Documentation Remarks"},
                ],
            },
        ],
        "Environmental": [
            {
                "title": "Environmental Compliance",
                "fields": [
                    {"key": "oil_containment_intact", "type": "boolean", "label": "Oil Containment Intact"},
                    {"key": "waste_disposal_compliant", "type": "boolean", "label": "Waste Disposal Compliant"},
                    {"key": "vegetation_clearance_adequate", "type": "boolean", "label": "Vegetation Clearance Adequate"},
                    {"key": "environmental_photo", "type": "file", "label": "Environmental Photograph"},
                    {"key": "environmental_remarks", "type": "textarea", "label": "Environmental Remarks"},
                ],
            },
        ],
        "General Maintenance": [
            {
                "title": "General Maintenance Checks",
                "fields": [
                    {
                        "key": "equipment_cleanliness",
                        "type": "dropdown",
                        "label": "Equipment Cleanliness",
                        "options": ["Clean", "Dusty", "Dirty"],
                    },
                    {"key": "corrosion_observed", "type": "boolean", "label": "Corrosion Observed"},
                    {"key": "loose_connections_observed", "type": "boolean", "label": "Loose Connections Observed"},
                    {"key": "maintenance_photo", "type": "file", "label": "Maintenance Photograph"},
                    {"key": "maintenance_remarks", "type": "textarea", "label": "Maintenance Remarks"},
                ],
            },
        ],
    }

    def _template_for(self, category_name: str, template_key: str) -> dict:
        category_sections = self._CATEGORY_SPECIFIC_SECTIONS.get(category_name, [])
        return {
            "key": template_key,
            "name": f"{category_name} Audit",
            "description": f"{category_name} annual audit observation template",
            "sections": category_sections + [self._ASSESSMENT_SECTION, self._COMPLIANCE_SECTION],
        }
