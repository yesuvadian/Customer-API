from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    Equipment,
    Module,
    OrgRole,
    OrgRolePermission,
    OrgUserRole,
    PreCommissionRequest,
    RepairAssignmentQueue,
    RepairStageAuditLog,
    RepairStageDefinition,
    RepairStageInstance,
    RepairWorkflow,
    RepairWorkflowDefinition,
    User,
)
from services.repair_workflow_service import RepairWorkflowService

WORKFLOW_CODE   = "PRE_COMMISSION"
ENTITY_TYPE     = "precommission_request"
FIRST_STAGE     = "QAP_RAW_MATERIAL"

STAGE_CODES = [
    "QAP_RAW_MATERIAL",
    "QAP_CORE_ASSEMBLY",
    "QAP_WINDING",
    "QAP_ACTIVE_PART",
    "QAP_TANK_FITTINGS",
    "QAP_ACTIVE_IN_TANK",
    "QAP_ROUTINE_TESTS",
    "QAP_SPECIAL_TESTS",
    "QAP_FINAL_DISPATCH",
]


class PreCommissionService:
    def __init__(self, db: Session):
        self.db       = db
        self.workflow = RepairWorkflowService(db)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _next_number(self) -> str:
        today = self._utc_now().strftime("%Y%m%d")
        count = self.db.query(func.count(PreCommissionRequest.id)).filter(
            PreCommissionRequest.request_number.like(f"PCR-{today}-%")
        ).scalar()
        return f"PCR-{today}-{(count or 0) + 1:04d}"

    def _get_request(self, request_id: UUID, user: User) -> PreCommissionRequest:
        pcr = self.db.query(PreCommissionRequest).filter(
            PreCommissionRequest.id == request_id,
            PreCommissionRequest.organization_id == user.organization_id,
        ).first()
        if not pcr:
            raise ValueError(f"Pre-commission request {request_id} not found.")
        return pcr

    def _can_approve(self, user: User) -> bool:
        """Check can_approve on the 'Pre-Commission Requests' module via OrgRolePermission."""
        module = (
            self.db.query(Module)
            .filter(Module.name == "Pre-Commission Requests")
            .first()
        )
        if not module:
            return False
        org_role_ids = [
            r.org_role_id
            for r in self.db.query(OrgUserRole)
            .filter(OrgUserRole.user_id == user.id, OrgUserRole.is_active.is_(True))
            .all()
        ]
        if not org_role_ids:
            return False
        return (
            self.db.query(OrgRolePermission)
            .filter(
                OrgRolePermission.org_role_id.in_(org_role_ids),
                OrgRolePermission.module_id == module.id,
                OrgRolePermission.can_approve.is_(True),
            )
            .first()
        ) is not None

    def _pcr_to_dict(self, pcr: PreCommissionRequest) -> dict:
        return {
            "id":                     str(pcr.id),
            "request_number":         pcr.request_number,
            "organization_id":        str(pcr.organization_id),
            "equipment_type_id":      pcr.equipment_type_id,
            "vendor_name":            pcr.vendor_name,
            "purchase_order_number":  pcr.purchase_order_number,
            "po_date":                pcr.po_date.isoformat() if pcr.po_date else None,
            "rated_mva":              float(pcr.rated_mva) if pcr.rated_mva else None,
            "voltage_class":          pcr.voltage_class,
            "transformer_type":       pcr.transformer_type,
            "cooling_class":          pcr.cooling_class,
            "vector_group":           pcr.vector_group,
            "quantity":               pcr.quantity,
            "factory_location":       pcr.factory_location,
            "proposed_inspection_date": pcr.proposed_inspection_date.isoformat() if pcr.proposed_inspection_date else None,
            "remarks":                pcr.remarks,
            "approval_status":        pcr.approval_status,
            "approved_by":            str(pcr.approved_by) if pcr.approved_by else None,
            "approved_at":            pcr.approved_at.isoformat() if pcr.approved_at else None,
            "approval_notes":         pcr.approval_notes,
            "rejected_by":            str(pcr.rejected_by) if pcr.rejected_by else None,
            "rejected_at":            pcr.rejected_at.isoformat() if pcr.rejected_at else None,
            "workflow_id":            str(pcr.workflow_id) if pcr.workflow_id else None,
            "equipment_id":           str(pcr.equipment_id) if pcr.equipment_id else None,
            "created_by":             str(pcr.created_by) if pcr.created_by else None,
            "cts":                    pcr.cts.isoformat() if pcr.cts else None,
            "mts":                    pcr.mts.isoformat() if pcr.mts else None,
            "current_stage_code":     self._current_stage_code(pcr),
        }

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def create_request(self, data: dict, user: User) -> dict:
        pcr = PreCommissionRequest(
            request_number=self._next_number(),
            organization_id=user.organization_id,
            equipment_type_id=data.get("equipment_type_id"),
            vendor_name=data["vendor_name"],
            purchase_order_number=data["purchase_order_number"],
            po_date=data.get("po_date"),
            rated_mva=data.get("rated_mva"),
            voltage_class=data.get("voltage_class"),
            transformer_type=data.get("transformer_type"),
            cooling_class=data.get("cooling_class"),
            vector_group=data.get("vector_group"),
            quantity=data.get("quantity", 1),
            factory_location=data.get("factory_location"),
            proposed_inspection_date=data.get("proposed_inspection_date"),
            remarks=data.get("remarks"),
            approval_status="pending",
            created_by=user.id,
            modified_by=user.id,
        )
        self.db.add(pcr)
        self.db.commit()
        self.db.refresh(pcr)
        return self._pcr_to_dict(pcr)

    def list_requests(
        self,
        user: User,
        approval_status: Optional[str] = None,
        skip: int = 0,
        limit: int = 100,
    ) -> list[dict]:
        q = self.db.query(PreCommissionRequest).filter(
            PreCommissionRequest.organization_id == user.organization_id
        )
        if approval_status and approval_status != "all":
            q = q.filter(PreCommissionRequest.approval_status == approval_status)
        rows = q.order_by(PreCommissionRequest.cts.desc()).offset(skip).limit(limit).all()
        return [self._pcr_to_dict(r) for r in rows]

    def list_unlinked(self, user: User) -> list[dict]:
        """
        PCR requests eligible to be linked to an equipment on
        create/replace — for the equipment registration dropdown.

        A request appears only when ALL of the following hold:
          • belongs to the user's organization
          • approved (a QAP workflow exists)
          • its QAP workflow is COMPLETED (in-progress ones are excluded)
          • not already linked to an equipment (equipment_id IS NULL)
        """
        rows = (
            self.db.query(PreCommissionRequest)
            .join(
                RepairWorkflow,
                RepairWorkflow.id == PreCommissionRequest.workflow_id,
            )
            .filter(
                PreCommissionRequest.organization_id == user.organization_id,
                PreCommissionRequest.approval_status  == "approved",
                PreCommissionRequest.equipment_id.is_(None),
                RepairWorkflow.status == "completed",
            )
            .order_by(PreCommissionRequest.cts.desc())
            .all()
        )
        return [self._pcr_to_dict(r) for r in rows]

    def get_request(self, request_id: UUID, user: User) -> dict:
        pcr    = self._get_request(request_id, user)
        result = self._pcr_to_dict(pcr)
        if pcr.workflow_id:
            result["workflow"] = self.workflow.get_workflow_detail(pcr.workflow_id)
            result["timeline"] = self.workflow.get_timeline(pcr.workflow_id)
        return result

    # ── Approval ──────────────────────────────────────────────────────────────

    def approve_request(self, request_id: UUID, notes: Optional[str], user: User) -> dict:
        pcr = self._get_request(request_id, user)
        if pcr.approval_status != "pending":
            raise ValueError(f"Request is already {pcr.approval_status}.")
        if not self._can_approve(user):
            raise ValueError("You do not have permission to approve pre-commission requests.")

        pcr.approval_status = "approved"
        pcr.approved_by     = user.id
        pcr.approved_at     = self._utc_now()
        pcr.approval_notes  = notes
        pcr.modified_by     = user.id

        workflow = self._create_qap_workflow(pcr, user)
        pcr.workflow_id = workflow.id

        self.db.commit()
        self.db.refresh(pcr)
        return self._pcr_to_dict(pcr)

    def reject_request(self, request_id: UUID, notes: Optional[str], user: User) -> dict:
        pcr = self._get_request(request_id, user)
        if pcr.approval_status != "pending":
            raise ValueError(f"Request is already {pcr.approval_status}.")
        if not self._can_approve(user):
            raise ValueError("You do not have permission to reject pre-commission requests.")

        pcr.approval_status = "rejected"
        pcr.rejected_by     = user.id
        pcr.rejected_at     = self._utc_now()
        pcr.approval_notes  = notes
        pcr.modified_by     = user.id

        self.db.commit()
        self.db.refresh(pcr)
        return self._pcr_to_dict(pcr)

    # ── Equipment link (post-onboarding) ──────────────────────────────────────

    def link_equipment(self, request_id: UUID, equipment_id: UUID, user: User) -> dict:
        pcr = self._get_request(request_id, user)
        if pcr.approval_status != "approved":
            raise ValueError("Only approved requests can be linked to equipment.")

        equipment = self.db.query(Equipment).filter(
            Equipment.id == equipment_id,
            Equipment.organization_id == user.organization_id,
        ).first()
        if not equipment:
            raise ValueError(f"Equipment {equipment_id} not found.")

        pcr.equipment_id = equipment_id
        pcr.modified_by  = user.id

        if pcr.workflow_id:
            workflow = self.db.query(RepairWorkflow).filter(
                RepairWorkflow.id == pcr.workflow_id
            ).first()
            if workflow:
                workflow.equipment_id = equipment_id

        self.db.commit()
        self.db.refresh(pcr)
        return self._pcr_to_dict(pcr)

    # ── Stage pass-through ────────────────────────────────────────────────────

    def current_form(self, request_id: UUID, user: User) -> dict:
        pcr = self._get_request(request_id, user)
        if not pcr.workflow_id:
            raise ValueError("No QAP workflow created yet — request is pending approval.")
        data        = self.workflow.get_current_form(pcr.workflow_id)
        data["pcr"] = self._pcr_to_dict(pcr)
        return data

    def save_stage(self, request_id: UUID, stage_id: UUID, form_data: dict, user: User) -> dict:
        pcr = self._get_request(request_id, user)
        if not pcr.workflow_id:
            raise ValueError("No QAP workflow found for this request.")
        return self.workflow.save_stage_data(pcr.workflow_id, stage_id, form_data, user.id)

    def advance_stage(self, request_id: UUID, action: str, remarks: Optional[str], user: User) -> dict:
        pcr = self._get_request(request_id, user)
        if not pcr.workflow_id:
            raise ValueError("No QAP workflow found for this request.")
        result = self.workflow.advance_stage(
            pcr.workflow_id, remarks, user.id, action_label=action
        )
        return result

    def timeline(self, request_id: UUID, user: User) -> list:
        pcr = self._get_request(request_id, user)
        if not pcr.workflow_id:
            return []
        return self.workflow.get_timeline(pcr.workflow_id)

    def available_actions(self, request_id: UUID, user: User) -> dict:
        pcr = self._get_request(request_id, user)
        if not pcr.workflow_id:
            return {"actions": []}
        return self.workflow.get_available_transitions(pcr.workflow_id, user.id)

    # ── Internal workflow creation ────────────────────────────────────────────

    def _create_qap_workflow(self, pcr: PreCommissionRequest, user: User) -> RepairWorkflow:
        # Ensure org-specific role mappings are seeded (idempotent)
        try:
            from seed_precommission_workflow import seed_precommission_role_mappings
            seed_precommission_role_mappings(self.db, pcr.organization_id)
        except Exception as _e:
            print(f"[WARN] precommission role mapping seed failed (non-fatal): {_e}")

        wf_def = self.db.query(RepairWorkflowDefinition).filter_by(
            workflow_code=WORKFLOW_CODE
        ).first()
        if not wf_def:
            raise ValueError(
                "PRE_COMMISSION workflow definition not found. Run seed_precommission_workflow.py first."
            )

        stages = (
            self.db.query(RepairStageDefinition)
            .filter(
                RepairStageDefinition.workflow_definition_id == wf_def.id,
                RepairStageDefinition.is_active.is_(True),
            )
            .order_by(RepairStageDefinition.sequence)
            .all()
        )
        if not stages:
            raise ValueError("PRE_COMMISSION workflow stages not found. Run seed first.")

        first_stage = stages[0]

        workflow = RepairWorkflow(
            workflow_number=pcr.request_number,
            workflow_code=WORKFLOW_CODE,
            entity_type=ENTITY_TYPE,
            entity_id=pcr.id,
            equipment_id=None,
            organization_id=pcr.organization_id,
            current_stage_id=first_stage.id,
            status="active",
            assignment_pending=True,
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
                status="pending" if is_first else "not_started",
                assignment_pending=is_first,
                started_at=self._utc_now() if is_first else None,
                created_by=user.id,
            )
            self.db.add(inst)
            self.db.flush()
            if is_first:
                first_instance = inst

        workflow.current_stage_instance_id = first_instance.id if first_instance else None

        self.db.add(
            RepairAssignmentQueue(
                workflow_id=workflow.id,
                stage_id=first_stage.id,
                status="pending",
            )
        )

        self.db.add(
            RepairStageAuditLog(
                workflow_id=workflow.id,
                stage_id=first_stage.id,
                action="created",
                performed_by=user.id,
                note=f"Pre-commission QAP workflow created for {pcr.request_number}",
            )
        )

        return workflow

    def _current_stage_code(self, pcr: PreCommissionRequest) -> Optional[str]:
        """Return the current QAP stage code for display purposes."""
        if not pcr.workflow_id:
            return None
        from models import RepairStageDefinition
        workflow = self.db.query(RepairWorkflow).filter(
            RepairWorkflow.id == pcr.workflow_id
        ).first()
        if not workflow or not workflow.current_stage_id:
            return None
        stage = self.db.query(RepairStageDefinition).filter(
            RepairStageDefinition.id == workflow.current_stage_id
        ).first()
        return stage.code if stage else None
