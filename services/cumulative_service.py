"""
cumulative_service.py
─────────────────────
CUMULATIVE_DIFF rule engine + overhaul trigger logic.

Data flow:
  TestingRequest (equipment_id, is_cumulative=True)
    └─ TestResult.test_data = {"reading": <float>, "reading_date": "YYYY-MM-DD", ...}
  Written by TestResultForm → POST /testing/{id}/results/structured
  template_key = "operations_tracking"

Rule: CUMULATIVE_DIFF
  Sums up positive increments between consecutive readings.
  Drops (decreases) are skipped when reset_on_drop=true.

Overhaul trigger:
  cumulative >= threshold → create OverhaulRecommendation (OPEN) + RepairWorkflow (OVERHAUL)
  Only one OPEN recommendation allowed per equipment.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    CategoryDetails,
    CategoryMaster,
    Equipment,
    EquipmentOverhaulConfig,
    OrgTestTemplate,
    OverhaulRecommendation,
    RepairAssignmentQueue,
    RepairStageAuditLog,
    RepairStageDefinition,
    RepairStageInstance,
    RepairWorkflow,
    RepairWorkflowDefinition,
    TestingRequest,
    TestResult,
)

OPERATIONS_TRACKING_KEY = "operations_tracking"
OPERATIONS_TRACKING_NAME = "Operations Tracking"
OVERHAUL_WORKFLOW_CODE = "OVERHAUL"

OPERATIONS_TRACKING_TEMPLATE: dict = {
    "name": OPERATIONS_TRACKING_NAME,
    "key": OPERATIONS_TRACKING_KEY,
    "description": "Multi-session operations tracking with cumulative difference calculation for overhaul triggering.",
    "enable_cumulative": True,
    "multi_session": True,
    "sections": [
        {
            "title": "Session Reading",
            "fields": [
                {
                    "key": "reading",
                    "label": "Operations Reading",
                    "type": "number",
                    "required": True,
                    "unit": "ops",
                },
                {
                    "key": "reading_date",
                    "label": "Reading Date",
                    "type": "date",
                    "required": True,
                },
                {
                    "key": "notes",
                    "label": "Notes",
                    "type": "textarea",
                    "required": False,
                },
            ],
        }
    ],
    "rules": [
        {
            "field": "reading",
            "type": "CUMULATIVE_DIFF",
            "config": {
                "order_by": "reading_date",
                "group_by": "equipment_id",
                "requires_multi_session": True,
                "reset_on_drop": True,
            },
        }
    ],
}


# ─── Pure rule function ───────────────────────────────────────────────────────

def cumulative_diff(readings: list[dict], field: str, reset_on_drop: bool = True) -> float:
    """
    Given a list of {'reading_time': datetime, field: float} dicts sorted by time,
    returns the sum of positive increments between consecutive readings.
    Drops are skipped when reset_on_drop=True.
    """
    if len(readings) < 2:
        return 0.0

    rows = sorted(readings, key=lambda r: r["reading_time"])
    total = 0.0
    for i in range(1, len(rows)):
        prev = float(rows[i - 1].get(field) or 0)
        curr = float(rows[i].get(field) or 0)
        if curr < prev and reset_on_drop:
            continue
        diff = curr - prev
        if diff > 0:
            total += diff
    return total


# ─── Service ─────────────────────────────────────────────────────────────────

class CumulativeService:

    def __init__(self, db: Session):
        self.db = db

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    # ── Configuration ─────────────────────────────────────────────────────────

    def ensure_config(self) -> dict:
        """
        Idempotent: ensures the Operations Tracking CategoryDetails entry and
        OrgTestTemplate with rules[] exist.  Returns a status dict.
        """
        created = []

        # 1. Find or create CategoryMaster "Repair Lifecycle"
        master = (
            self.db.query(CategoryMaster)
            .filter(func.lower(CategoryMaster.name) == "repair lifecycle")
            .first()
        )
        if not master:
            master = CategoryMaster(name="Repair Lifecycle", description="Repair and Lifecycle workflow test types")
            self.db.add(master)
            self.db.flush()
            created.append("CategoryMaster: Repair / Lifecycle")

        # 2. Find or create CategoryDetails "Operations Tracking"
        detail = (
            self.db.query(CategoryDetails)
            .filter(
                CategoryDetails.category_master_id == master.id,
                func.lower(CategoryDetails.name) == func.lower(OPERATIONS_TRACKING_NAME),
            )
            .first()
        )
        if not detail:
            detail = CategoryDetails(
                name=OPERATIONS_TRACKING_NAME,
                category_master_id=master.id,
                description="Cumulative operations tracking — triggers overhaul when threshold crossed.",
            )
            self.db.add(detail)
            self.db.flush()
            created.append(f"CategoryDetails: {OPERATIONS_TRACKING_NAME}")

        # 3. Find or create OrgTestTemplate
        tpl = (
            self.db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.template_key == OPERATIONS_TRACKING_KEY)
            .first()
        )
        if not tpl:
            tpl = OrgTestTemplate(
                id=uuid.uuid4(),
                template_key=OPERATIONS_TRACKING_KEY,
                test_type_id=detail.id,
                template_data=OPERATIONS_TRACKING_TEMPLATE,
                is_system=True,
                version=1,
            )
            self.db.add(tpl)
            created.append(f"OrgTestTemplate: {OPERATIONS_TRACKING_KEY}")
        else:
            # Always update rules to latest definition
            tpl.template_data = OPERATIONS_TRACKING_TEMPLATE
            tpl.version = (tpl.version or 1) + 1

        self.db.commit()
        return {"status": "ok", "created": created, "template_id": str(tpl.id)}

    # ── Threshold config ──────────────────────────────────────────────────────

    def set_threshold(self, equipment_id: UUID, threshold: float, user_id: Optional[UUID] = None) -> dict:
        cfg = (
            self.db.query(EquipmentOverhaulConfig)
            .filter(EquipmentOverhaulConfig.equipment_id == equipment_id)
            .first()
        )
        if cfg:
            cfg.threshold_value = threshold
        else:
            cfg = EquipmentOverhaulConfig(
                id=uuid.uuid4(),
                equipment_id=equipment_id,
                threshold_value=threshold,
                created_by=user_id,
            )
            self.db.add(cfg)
        self.db.commit()
        return {"equipment_id": str(equipment_id), "threshold_value": threshold}

    def get_threshold(self, equipment_id: UUID) -> Optional[dict]:
        cfg = (
            self.db.query(EquipmentOverhaulConfig)
            .filter(EquipmentOverhaulConfig.equipment_id == equipment_id)
            .first()
        )
        if not cfg:
            return None
        return {"equipment_id": str(equipment_id), "threshold_value": cfg.threshold_value}

    # ── Cumulative calculation ────────────────────────────────────────────────

    def _get_operations_test_type_id(self) -> Optional[int]:
        detail = (
            self.db.query(CategoryDetails.id)
            .filter(func.lower(CategoryDetails.name) == func.lower(OPERATIONS_TRACKING_NAME))
            .scalar()
        )
        return detail

    def calculate_cumulative(self, equipment_id: UUID) -> float:
        """
        Sum CUMULATIVE_DIFF across all TestResult rows for this equipment
        where is_cumulative=True and template_key='operations_tracking'.
        Ordered by reading_date from test_data (falls back to cts).
        """
        request_ids = [
            r[0]
            for r in self.db.query(TestingRequest.id)
            .filter(
                TestingRequest.equipment_id == equipment_id,
                TestingRequest.is_cumulative == True,  # noqa: E712
            )
            .all()
        ]
        if not request_ids:
            return 0.0

        results = (
            self.db.query(TestResult)
            .filter(
                TestResult.testing_request_id.in_(request_ids),
            )
            .order_by(TestResult.cts)
            .all()
        )

        rows = []
        for r in results:
            data = r.test_data or {}
            if "reading" not in data:
                continue
            # Order by reading_date from test_data when available, else fall back to cts
            reading_date_str = data.get("reading_date")
            if reading_date_str:
                try:
                    reading_time = datetime.strptime(
                        str(reading_date_str)[:10], "%Y-%m-%d"
                    ).replace(tzinfo=timezone.utc)
                except Exception:
                    reading_time = r.cts or self._utc_now()
            else:
                reading_time = r.cts or self._utc_now()
            rows.append({
                "reading_time": reading_time,
                "reading": float(data.get("reading") or 0),
            })

        return cumulative_diff(rows, "reading", reset_on_drop=True)

    # ── Overhaul trigger ──────────────────────────────────────────────────────

    def _open_recommendation(self, equipment_id: UUID) -> Optional[OverhaulRecommendation]:
        return (
            self.db.query(OverhaulRecommendation)
            .filter(
                OverhaulRecommendation.equipment_id == equipment_id,
                OverhaulRecommendation.status == "OPEN",
            )
            .first()
        )

    def _get_effective_threshold(self, equipment_id: UUID) -> Optional[float]:
        """
        Returns the effective overhaul threshold for an equipment:
        1. Equipment-specific config (EquipmentOverhaulConfig) — takes priority
        2. Template default_threshold from the test template rules
        3. None if neither is configured
        """
        cfg = (
            self.db.query(EquipmentOverhaulConfig)
            .filter(EquipmentOverhaulConfig.equipment_id == equipment_id)
            .first()
        )
        if cfg and cfg.threshold_value is not None:
            return float(cfg.threshold_value)

        # Fall back to template default_threshold
        try:
            from test_templates import TEST_TEMPLATES
            for tpl in TEST_TEMPLATES.values():
                if not tpl.get("enable_cumulative"):
                    continue
                for rule in tpl.get("rules", []):
                    default = rule.get("config", {}).get("default_threshold")
                    if default is not None:
                        # Use the first cumulative template's default
                        # (equipment type matching could be added later)
                        return float(default)
        except Exception:
            pass
        return None

    def evaluate_overhaul_trigger(
        self, equipment_id: UUID, user_id: Optional[UUID] = None
    ) -> dict:
        """
        Calculate cumulative, compare to threshold.
        1. Uses equipment-specific threshold if set (EquipmentOverhaulConfig)
        2. Falls back to template default_threshold
        If threshold crossed and no open recommendation exists → create recommendation + workflow.
        Returns lifecycle status dict.
        """
        cumulative = self.calculate_cumulative(equipment_id)
        threshold = self._get_effective_threshold(equipment_id)

        open_rec = self._open_recommendation(equipment_id)

        if threshold is not None and cumulative >= threshold and not open_rec:
            rec = self._trigger_overhaul(equipment_id, cumulative, threshold, user_id)
            open_rec = rec

        return self._lifecycle_status(equipment_id, cumulative, threshold, open_rec)

    def _trigger_overhaul(
        self,
        equipment_id: UUID,
        cumulative: float,
        threshold: float,
        user_id: Optional[UUID],
    ) -> OverhaulRecommendation:
        """
        Create an OVERHAUL RepairWorkflow with all stage instances initialised,
        exactly mirroring how start_workflow() works for BREAKDOWN.
        """
        # ── 1. Resolve OVERHAUL workflow definition ───────────────────────────
        wf_def = (
            self.db.query(RepairWorkflowDefinition)
            .filter(RepairWorkflowDefinition.workflow_code == OVERHAUL_WORKFLOW_CODE)
            .first()
        )
        if not wf_def:
            raise ValueError(
                "OVERHAUL workflow definition not found — run seed_overhaul_stages first."
            )

        # ── 2. Get ordered OVERHAUL stage definitions ─────────────────────────
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
            raise ValueError("No active OVERHAUL stages found.")

        first_stage = stages[0]

        # ── 3. Generate a unique workflow number ──────────────────────────────
        count = self.db.query(func.count(RepairWorkflow.id)).scalar() or 0
        workflow_number = (
            f"OVH-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{count + 1:04d}"
        )

        # ── 4. Create the RepairWorkflow row ──────────────────────────────────
        workflow = RepairWorkflow(
            workflow_number=workflow_number,
            workflow_code=OVERHAUL_WORKFLOW_CODE,
            equipment_id=equipment_id,
            workflow_type="OVERHAUL",
            source="cumulative",
            current_stage_id=first_stage.id,
            status="active",
            assignment_pending=True,
            progress=0,
            priority="normal",
            created_by=user_id,
        )
        self.db.add(workflow)
        self.db.flush()  # need workflow.id for stage instances

        # ── 5. Create RepairStageInstance for every stage ─────────────────────
        _now = datetime.now(timezone.utc)
        first_instance = None
        for stage in stages:
            is_first = stage.id == first_stage.id
            instance = RepairStageInstance(
                workflow_id=workflow.id,
                stage_id=stage.id,
                status="pending" if is_first else "not_started",
                assignment_pending=is_first,
                started_at=_now if is_first else None,
                created_by=user_id,
            )
            self.db.add(instance)
            self.db.flush()
            if is_first:
                first_instance = instance

        # ── 6. Point workflow at the first stage instance ─────────────────────
        if first_instance:
            workflow.current_stage_instance_id = first_instance.id

        # ── 7. Create the coordinator assignment queue entry ──────────────────
        self.db.add(RepairAssignmentQueue(
            workflow_id=workflow.id,
            stage_id=first_stage.id,
            status="pending",
        ))

        # ── 8. Audit log ──────────────────────────────────────────────────────
        self.db.add(RepairStageAuditLog(
            workflow_id=workflow.id,
            stage_id=first_stage.id,
            action="created",
            performed_by=user_id,
            note=(
                f"Overhaul workflow auto-triggered — cumulative {cumulative:.0f} "
                f"≥ threshold {threshold:.0f}"
            ),
            performed_at=_now,
        ))

        # ── 9. Create the OverhaulRecommendation linked to the workflow ────────
        rec = OverhaulRecommendation(
            id=uuid.uuid4(),
            equipment_id=equipment_id,
            workflow_id=workflow.id,
            cumulative_value=cumulative,
            threshold_value=threshold,
            status="OPEN",
            created_by=user_id,
        )
        self.db.add(rec)
        self.db.commit()

        print(
            f"[OVERHAUL] Workflow {workflow_number} created for equipment {equipment_id} "
            f"— first stage: {first_stage.name} (pending coordinator assignment)"
        )
        return rec

    # ── Lifecycle status ──────────────────────────────────────────────────────

    def get_lifecycle_status(self, equipment_id: UUID) -> dict:
        cumulative = self.calculate_cumulative(equipment_id)
        threshold = self._get_effective_threshold(equipment_id)
        open_rec = self._open_recommendation(equipment_id)
        return self._lifecycle_status(equipment_id, cumulative, threshold, open_rec)

    @staticmethod
    def _lifecycle_status(
        equipment_id: UUID,
        cumulative: float,
        threshold: Optional[float],
        open_rec: Optional[OverhaulRecommendation],
    ) -> dict:
        if open_rec:
            status = "OVERHAUL_DUE"
        elif threshold and cumulative >= threshold * 0.8:
            status = "WARNING"
        else:
            status = "NORMAL"

        result: dict = {
            "equipment_id": str(equipment_id),
            "cumulative_value": cumulative,
            "threshold_value": threshold,
            "status": status,
        }
        if open_rec:
            result["overhaul"] = {
                "recommendation_id": str(open_rec.id),
                "workflow_id": str(open_rec.workflow_id) if open_rec.workflow_id else None,
                "cumulative": open_rec.cumulative_value,
                "threshold": open_rec.threshold_value,
                "triggered_at": open_rec.triggered_at.isoformat() if open_rec.triggered_at else None,
                "status": open_rec.status,
            }
        return result

    def close_recommendation(self, recommendation_id: UUID) -> dict:
        rec = self.db.query(OverhaulRecommendation).filter(OverhaulRecommendation.id == recommendation_id).first()
        if not rec:
            raise ValueError("Recommendation not found")
        rec.status = "CLOSED"
        rec.closed_at = self._utc_now()
        self.db.commit()
        return {"id": str(rec.id), "status": "CLOSED"}
