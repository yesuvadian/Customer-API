"""
repair_timeliness_service.py
────────────────────────────
Contractual timeline tracking, delay computation, and delay attribution
for the transformer repair workflow.

Flow:
  1. contracted_date set on stage instance (via dynamic form / external process)
  2. Stage completes  → delay_days auto-computed (advance_stage hook calls compute_delay)
  3. Officer attributes delay → delay_attribution = 'vendor' | 'kptcl'
  4. Timeliness summary       → per-stage + workflow-level aggregation
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from models import (
    OrgUserRole,
    RepairStageAuditLog,
    RepairStageDefinition,
    RepairStageInstance,
    RepairStageRole,
    RepairWorkflow,
)


class RepairTimelinessService:

    def __init__(self, db: Session):
        self.db = db

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _user_org_role_ids(self, user_id: UUID) -> list:
        rows = (
            self.db.query(OrgUserRole.org_role_id)
            .filter(OrgUserRole.user_id == user_id)
            .all()
        )
        return [r[0] for r in rows]

    def _is_org_admin(self, user_id: UUID) -> bool:
        # Delegates to the single shared org-admin check (auth_utils.
        # has_org_admin_role). The previous version here queried
        # OrgUserRole/OrgRole directly without filtering either row's
        # is_active flag — a deactivated org-admin role assignment would
        # still pass this check, which gates the 403 on
        # record_delay_attribution below.
        from auth_utils import has_org_admin_role
        return has_org_admin_role(user_id, self.db)

    def _can_approve_stage(self, user_id: UUID, stage_id: UUID) -> bool:
        role_ids = self._user_org_role_ids(user_id)
        if not role_ids:
            return False
        return bool(
            self.db.query(RepairStageRole)
            .filter(
                RepairStageRole.stage_id == stage_id,
                RepairStageRole.role_id.in_(role_ids),
                RepairStageRole.can_approve.is_(True),
            )
            .first()
        )

    def _get_workflow(self, workflow_id: UUID) -> RepairWorkflow:
        wf = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not wf:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Repair workflow not found.")
        return wf

    def _get_stage_instance(self, workflow_id: UUID, stage_instance_id: UUID) -> RepairStageInstance:
        inst = (
            self.db.query(RepairStageInstance)
            .filter(
                RepairStageInstance.id == stage_instance_id,
                RepairStageInstance.workflow_id == workflow_id,
            )
            .first()
        )
        if not inst:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Stage instance not found.")
        return inst

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

    # =========================================================================
    # Delay computation (called by repair_workflow_service on stage completion)
    # =========================================================================

    def compute_delay(self, stage_instance: RepairStageInstance) -> None:
        """
        Auto-compute delay_days when a stage completes.
        Call this immediately after setting stage_instance.completed_at.
        """
        if stage_instance.contracted_date is None or stage_instance.completed_at is None:
            return

        actual = stage_instance.completed_at.date()
        contracted = stage_instance.contracted_date
        delay = (actual - contracted).days
        stage_instance.delay_days = delay

        # On-time or early: clear any stale attribution
        if delay <= 0:
            stage_instance.delay_attribution = None
            stage_instance.delay_reason = None
            stage_instance.delay_attributed_by = None
            stage_instance.delay_attributed_at = None

    # =========================================================================
    # Delay attribution
    # =========================================================================

    def record_delay_attribution(
        self,
        workflow_id: UUID,
        stage_instance_id: UUID,
        payload: dict,
        current_user_id: UUID,
    ) -> dict:
        """
        Officer records whether a delay is vendor-attributable or KPTCL-attributable.

        payload = {"attribution": "vendor" | "kptcl", "reason": str}
        """
        wf = self._get_workflow(workflow_id)
        inst = self._get_stage_instance(workflow_id, stage_instance_id)

        if inst.completed_at is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot attribute delay on a stage that has not completed."
            )

        if inst.delay_days is None or inst.delay_days <= 0:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "This stage has no delay (completed on time or early). Attribution not required."
            )

        attribution = payload.get("attribution", "").strip().lower()
        if attribution not in ("vendor", "kptcl"):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "attribution must be 'vendor' or 'kptcl'."
            )

        reason = payload.get("reason", "").strip()
        if not reason:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "reason is required.")

        if not self._is_org_admin(current_user_id) and not self._can_approve_stage(current_user_id, inst.stage_id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Only approvers or org-admin can record delay attribution."
            )

        inst.delay_attribution = attribution
        inst.delay_reason = reason
        inst.delay_attributed_by = current_user_id
        inst.delay_attributed_at = self._utc_now()

        self._log_audit(
            workflow_id=wf.id,
            stage_id=inst.stage_id,
            action="delay_attributed",
            performed_by=current_user_id,
            note=f"{attribution.upper()}: {reason} ({inst.delay_days} days late)",
        )

        self.db.commit()
        return self._stage_timeliness_dict(inst)

    # =========================================================================
    # Timeliness summary
    # =========================================================================

    def get_timeliness_summary(self, workflow_id: UUID) -> dict:
        wf = self._get_workflow(workflow_id)

        instances = (
            self.db.query(RepairStageInstance)
            .filter(RepairStageInstance.workflow_id == workflow_id)
            .all()
        )

        # Build stage name lookup
        stage_ids = [i.stage_id for i in instances]
        defns = (
            self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.id.in_(stage_ids))
            .all()
        )
        defn_map = {d.id: d for d in defns}

        stage_rows = []
        total_vendor_delay = 0
        pending_attribution_count = 0

        for inst in sorted(instances, key=lambda i: defn_map[i.stage_id].sequence if i.stage_id in defn_map else 999):
            defn = defn_map.get(inst.stage_id)
            row = self._stage_timeliness_dict(inst, defn)
            stage_rows.append(row)

            if inst.delay_attribution == "vendor" and inst.delay_days:
                total_vendor_delay += inst.delay_days

            if inst.delay_days is not None and inst.delay_days > 0 and inst.delay_attribution is None:
                pending_attribution_count += 1

        return {
            "workflow_id": str(wf.id),
            "workflow_number": wf.workflow_number,
            "vendor_name": wf.vendor_name,
            "work_award_at": wf.work_award_at.isoformat() if wf.work_award_at else None,
            "contracted_completion": wf.contracted_completion.isoformat() if wf.contracted_completion else None,
            "total_vendor_delay_days": total_vendor_delay,
            "stages_pending_attribution": pending_attribution_count,
            "stages": stage_rows,
        }

    # =========================================================================
    # Internal serialiser
    # =========================================================================

    def _stage_timeliness_dict(
        self,
        inst: RepairStageInstance,
        defn: Optional[RepairStageDefinition] = None,
    ) -> dict:
        if defn is None:
            defn = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.id == inst.stage_id
            ).first()

        delay = inst.delay_days
        status_label = None
        if delay is None:
            status_label = "not_completed"
        elif delay > 0:
            status_label = "delayed"
        elif delay < 0:
            status_label = "early"
        else:
            status_label = "on_time"

        return {
            "stage_instance_id": str(inst.id),
            "stage_id": str(inst.stage_id),
            "stage_name": defn.name if defn else "Unknown",
            "sequence": defn.sequence if defn else None,
            "stage_status": inst.status,
            "contracted_date": inst.contracted_date.isoformat() if inst.contracted_date else None,
            "actual_date": inst.completed_at.date().isoformat() if inst.completed_at else None,
            "delay_days": delay,
            "timeliness_status": status_label,
            "delay_attribution": inst.delay_attribution,
            "delay_reason": inst.delay_reason,
            "delay_attributed_by": str(inst.delay_attributed_by) if inst.delay_attributed_by else None,
            "delay_attributed_at": inst.delay_attributed_at.isoformat() if inst.delay_attributed_at else None,
            "attribution_required": delay is not None and delay > 0 and inst.delay_attribution is None,
        }
