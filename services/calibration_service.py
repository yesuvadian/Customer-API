"""
calibration_service.py
──────────────────────
Calibration Lifecycle engine using the cumulative pattern.

Data flow:
  TestingRequest (equipment_id, is_calibration=True)
    └─ TestResult.test_data = {
           "calibration_date": "2025-01-01",
           "validity_months": 12,
           "overall_result": "Pass" | "Fail",
           "calibrated_by": "...",       (optional)
           "certificate_number": "...",  (optional)
           "notes": "...",               (optional)
       }
  Written by TestResultForm → POST /testing/{id}/results/structured
  template_key = "calibration"

Rule: DATE_ADD
  next_due = calibration_date + validity_months (months)

State logic:
  "Fail"  → CRITICAL  (stop scheduling, trigger repair recommendation)
  "Pass"  → NORMAL

Scheduler (pre-due check):
  if today >= next_due - lead_days → auto-create new calibration TestingRequest
  lead_days is stored in EquipmentCalibrationConfig (default 30)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone, date
from typing import Optional
from uuid import UUID

from dateutil.relativedelta import relativedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import (
    CalibrationRepairRecommendation,
    CategoryDetails,
    CategoryMaster,
    Equipment,
    EquipmentCalibrationConfig,
    OrgTestTemplate,
    TestingRequest,
    TestingRequestStatus,
    TestResult,
)

CALIBRATION_KEY = "calibration"
CALIBRATION_NAME = "Calibration"

CALIBRATION_TEMPLATE: dict = {
    "name": CALIBRATION_NAME,
    "key": CALIBRATION_KEY,
    "description": "Equipment calibration lifecycle tracking. Computes next due date and triggers repair on failure.",
    "enable_calibration": True,
    "multi_session": True,
    "sections": [
        {
            "title": "Calibration Record",
            "fields": [
                {"key": "calibration_date", "label": "Calibration Date", "type": "date", "required": True},
                {"key": "validity_months", "label": "Validity (Months)", "type": "number", "required": True, "unit": "months"},
                {"key": "overall_result", "label": "Result", "type": "dropdown", "options": ["Pass", "Fail"], "required": True},
                {"key": "calibrated_by", "label": "Calibrated By (Agency / Lab)", "type": "text", "required": False},
                {"key": "certificate_number", "label": "Certificate Number", "type": "text", "required": False},
                {"key": "notes", "label": "Notes", "type": "textarea", "required": False},
            ],
        }
    ],
    "rules": [
        {
            "field": "calibration_date",
            "type": "DATE_ADD",
            "config": {
                "validity_field": "validity_months",
                "result_field": "overall_result",
                "order_by": "calibration_date",
                "group_by": "equipment_id",
                "requires_multi_session": True,
            },
        }
    ],
}


# ─── Pure rule function ───────────────────────────────────────────────────────

def date_add(calibration_date_str: str, validity_months: int) -> date:
    """
    Returns next_due = calibration_date + validity_months.
    calibration_date_str: ISO date string "YYYY-MM-DD"
    """
    cal_date = datetime.strptime(calibration_date_str[:10], "%Y-%m-%d").date()
    return cal_date + relativedelta(months=validity_months)


# ─── Service ─────────────────────────────────────────────────────────────────

class CalibrationService:

    def __init__(self, db: Session):
        self.db = db

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _today(self) -> date:
        return datetime.now(timezone.utc).date()

    # ── Configuration ─────────────────────────────────────────────────────────

    def ensure_config(self) -> dict:
        """
        Idempotent: ensure CategoryDetails "Calibration" and OrgTestTemplate exist.
        """
        created = []

        master = (
            self.db.query(CategoryMaster)
            .filter(func.lower(CategoryMaster.name) == "repair lifecycle")
            .first()
        )
        if not master:
            master = CategoryMaster(
                name="Repair Lifecycle",
                description="Repair and Lifecycle workflow test types",
            )
            self.db.add(master)
            self.db.flush()
            created.append("CategoryMaster: Repair Lifecycle")

        detail = (
            self.db.query(CategoryDetails)
            .filter(
                CategoryDetails.category_master_id == master.id,
                func.lower(CategoryDetails.name) == func.lower(CALIBRATION_NAME),
            )
            .first()
        )
        if not detail:
            detail = CategoryDetails(
                name=CALIBRATION_NAME,
                category_master_id=master.id,
                description="Equipment calibration lifecycle — DATE_ADD rule, pre-due scheduling, FAIL → repair trigger.",
            )
            self.db.add(detail)
            self.db.flush()
            created.append(f"CategoryDetails: {CALIBRATION_NAME}")

        tpl = (
            self.db.query(OrgTestTemplate)
            .filter(OrgTestTemplate.template_key == CALIBRATION_KEY)
            .first()
        )
        if not tpl:
            tpl = OrgTestTemplate(
                id=uuid.uuid4(),
                template_key=CALIBRATION_KEY,
                test_type_id=detail.id,
                template_data=CALIBRATION_TEMPLATE,
                is_system=True,
                version=1,
            )
            self.db.add(tpl)
            created.append(f"OrgTestTemplate: {CALIBRATION_KEY}")
        else:
            tpl.template_data = CALIBRATION_TEMPLATE
            tpl.version = (tpl.version or 1) + 1

        self.db.commit()
        return {"status": "ok", "created": created, "template_id": str(tpl.id)}

    # ── Lead-days config ──────────────────────────────────────────────────────

    def get_config(self, equipment_id: UUID) -> dict:
        cfg = (
            self.db.query(EquipmentCalibrationConfig)
            .filter(EquipmentCalibrationConfig.equipment_id == equipment_id)
            .first()
        )
        return {
            "equipment_id": str(equipment_id),
            "lead_days": cfg.lead_days if cfg else 30,
            "is_scheduled": cfg.is_scheduled if cfg else True,
        }

    def set_config(
        self,
        equipment_id: UUID,
        lead_days: int,
        is_scheduled: Optional[bool] = None,
        user_id: Optional[UUID] = None,
    ) -> dict:
        cfg = (
            self.db.query(EquipmentCalibrationConfig)
            .filter(EquipmentCalibrationConfig.equipment_id == equipment_id)
            .first()
        )
        if cfg:
            cfg.lead_days = lead_days
            if is_scheduled is not None:
                cfg.is_scheduled = is_scheduled
        else:
            cfg = EquipmentCalibrationConfig(
                id=uuid.uuid4(),
                equipment_id=equipment_id,
                lead_days=lead_days,
                is_scheduled=True if is_scheduled is None else is_scheduled,
                created_by=user_id,
            )
            self.db.add(cfg)
        self.db.commit()
        return {
            "equipment_id": str(equipment_id),
            "lead_days": cfg.lead_days,
            "is_scheduled": cfg.is_scheduled,
        }

    # ── Latest calibration result (from TestResult.test_data) ────────────────

    def _get_latest_reading(self, equipment_id: UUID) -> Optional[dict]:
        """
        Returns the most recent calibration TestResult.test_data for the equipment.
        Submitted by TestResultForm → POST /testing/{id}/results/structured
        with template_key='calibration'.
        """
        request_ids = [
            r[0]
            for r in self.db.query(TestingRequest.id)
            .filter(
                TestingRequest.equipment_id == equipment_id,
                TestingRequest.is_calibration == True,  # noqa: E712
            )
            .all()
        ]
        if not request_ids:
            return None

        result = (
            self.db.query(TestResult)
            .filter(
                TestResult.testing_request_id.in_(request_ids),
            )
            .order_by(TestResult.cts.desc())
            .first()
        )
        if not result:
            return None

        data = result.test_data or {}
        if "calibration_date" not in data or "validity_months" not in data:
            return None

        return {
            "result_id": str(result.id),
            "submitted_at": result.cts,
            "calibration_date": data["calibration_date"],
            "validity_months": int(data["validity_months"]),
            # overall_result: prefer test_data field, fall back to top-level column
            "overall_result": (data.get("overall_result") or result.overall_result or "").strip() or None,
            "calibrated_by": data.get("calibrated_by"),
            "certificate_number": data.get("certificate_number"),
            "notes": data.get("notes"),
        }

    def _get_all_readings(self, equipment_id: UUID) -> list[dict]:
        """
        Return all calibration TestResults sorted by submission time (newest first).
        """
        request_ids = [
            r[0]
            for r in self.db.query(TestingRequest.id)
            .filter(
                TestingRequest.equipment_id == equipment_id,
                TestingRequest.is_calibration == True,  # noqa: E712
            )
            .all()
        ]
        if not request_ids:
            return []

        results = (
            self.db.query(TestResult)
            .filter(
                TestResult.testing_request_id.in_(request_ids),
            )
            .order_by(TestResult.cts.desc())
            .all()
        )

        records = []
        for r in results:
            data = r.test_data or {}
            if "calibration_date" not in data:
                continue
            records.append({
                "result_id": str(r.id),
                "submitted_at": r.cts.isoformat() if r.cts else None,
                "calibration_date": data.get("calibration_date"),
                "validity_months": data.get("validity_months"),
                "overall_result": data.get("overall_result") or r.overall_result,
                "calibrated_by": data.get("calibrated_by"),
                "certificate_number": data.get("certificate_number"),
                "notes": data.get("notes"),
            })
        return records

    # ── Status computation ────────────────────────────────────────────────────

    def _get_open_repair_recommendation(self, equipment_id: UUID) -> Optional["CalibrationRepairRecommendation"]:
        return (
            self.db.query(CalibrationRepairRecommendation)
            .filter(
                CalibrationRepairRecommendation.equipment_id == equipment_id,
                CalibrationRepairRecommendation.status == "OPEN",
            )
            .first()
        )

    def get_calibration_status(self, equipment_id: UUID) -> dict:
        """
        Compute current calibration state for the equipment.
        State: NORMAL | CRITICAL | NOT_CALIBRATED | DUE_SOON | OVERDUE
        """
        latest = self._get_latest_reading(equipment_id)
        cfg = (
            self.db.query(EquipmentCalibrationConfig)
            .filter(EquipmentCalibrationConfig.equipment_id == equipment_id)
            .first()
        )

        if not latest:
            return {
                "equipment_id": str(equipment_id),
                "state": "NOT_CALIBRATED",
                "last_calibration_date": None,
                "next_due_date": None,
                "days_until_due": None,
                "overall_result": None,
                "lead_days": cfg.lead_days if cfg else 30,
                "is_scheduled": cfg.is_scheduled if cfg else True,
            }

        cal_date_str = latest["calibration_date"]
        validity_months = latest["validity_months"]
        overall_result = latest["overall_result"]

        next_due = date_add(cal_date_str, validity_months)
        today = self._today()
        days_until_due = (next_due - today).days

        if overall_result == "Fail":
            state = "CRITICAL"
        elif days_until_due < 0:
            state = "OVERDUE"
        elif days_until_due <= (cfg.lead_days if cfg else 30):
            state = "DUE_SOON"
        else:
            state = "NORMAL"

        result: dict = {
            "equipment_id": str(equipment_id),
            "state": state,
            "last_calibration_date": cal_date_str,
            "next_due_date": next_due.isoformat(),
            "days_until_due": days_until_due,
            "overall_result": overall_result,
            "calibrated_by": latest.get("calibrated_by"),
            "certificate_number": latest.get("certificate_number"),
            "lead_days": cfg.lead_days if cfg else 30,
            "is_scheduled": cfg.is_scheduled if cfg else True,
        }

        # Attach open repair recommendation when CRITICAL
        open_rec = self._get_open_repair_recommendation(equipment_id)
        if open_rec:
            result["recommendation"] = {
                "recommendation_id": str(open_rec.id),
                "status": open_rec.status,
                "triggered_at": open_rec.triggered_at.isoformat() if open_rec.triggered_at else None,
            }

        return result

    # ── Evaluate (rule engine + failure action) ───────────────────────────────

    def evaluate_calibration(
        self, equipment_id: UUID, user_id: Optional[UUID] = None
    ) -> dict:
        """
        Run the DATE_ADD rule engine on the latest reading.
        If overall_result == "Fail":
          - Stop scheduling (is_scheduled = False)
          - Create a CalibrationRepairRecommendation if none open
        Returns the up-to-date status dict (re-read after any state change).
        """
        status = self.get_calibration_status(equipment_id)

        if status["state"] == "CRITICAL":
            self._handle_fail(equipment_id, user_id)
            # Re-read so response reflects is_scheduled=False + new recommendation
            status = self.get_calibration_status(equipment_id)

        return status

    def _handle_fail(self, equipment_id: UUID, user_id: Optional[UUID]) -> None:
        """Stop schedule + create CalibrationRepairRecommendation if none open."""
        # Stop scheduling
        cfg = (
            self.db.query(EquipmentCalibrationConfig)
            .filter(EquipmentCalibrationConfig.equipment_id == equipment_id)
            .first()
        )
        if cfg:
            cfg.is_scheduled = False
        else:
            cfg = EquipmentCalibrationConfig(
                id=uuid.uuid4(),
                equipment_id=equipment_id,
                lead_days=30,
                is_scheduled=False,
                created_by=user_id,
            )
            self.db.add(cfg)
        self.db.flush()

        # Create repair recommendation if none open for this equipment
        open_rec = self._get_open_repair_recommendation(equipment_id)
        if not open_rec:
            rec = CalibrationRepairRecommendation(
                id=uuid.uuid4(),
                equipment_id=equipment_id,
                status="OPEN",
                created_by=user_id,
            )
            self.db.add(rec)

        self.db.commit()

    # ── Recovery (resume after repair) ───────────────────────────────────────

    def resume_schedule(
        self, equipment_id: UUID, user_id: Optional[UUID] = None
    ) -> dict:
        """
        Called after a repair is completed and a new calibration passes.
        Re-enables scheduling for the equipment.
        """
        cfg = (
            self.db.query(EquipmentCalibrationConfig)
            .filter(EquipmentCalibrationConfig.equipment_id == equipment_id)
            .first()
        )
        if cfg:
            cfg.is_scheduled = True
        else:
            cfg = EquipmentCalibrationConfig(
                id=uuid.uuid4(),
                equipment_id=equipment_id,
                lead_days=30,
                is_scheduled=True,
                created_by=user_id,
            )
            self.db.add(cfg)
        self.db.commit()
        return {"equipment_id": str(equipment_id), "is_scheduled": True}

    # ── History ───────────────────────────────────────────────────────────────

    def get_history(self, equipment_id: UUID) -> dict:
        readings = self._get_all_readings(equipment_id)
        return {
            "equipment_id": str(equipment_id),
            "total": len(readings),
            "records": readings,
        }

    # ── Pre-due scheduler ─────────────────────────────────────────────────────

    def run_pre_due_check(self) -> dict:
        """
        Scheduler job: for every equipment with is_scheduled=True,
        check if today >= next_due - lead_days.
        If so, auto-create a new calibration TestingRequest (if one isn't already open).

        Returns a summary dict.
        """
        today = self._today()
        created = []
        skipped = []

        # All equipment that have calibration configs with scheduling enabled
        configs = (
            self.db.query(EquipmentCalibrationConfig)
            .filter(EquipmentCalibrationConfig.is_scheduled == True)  # noqa: E712
            .all()
        )

        for cfg in configs:
            equipment_id = cfg.equipment_id
            status = self.get_calibration_status(equipment_id)

            if status["state"] == "NOT_CALIBRATED":
                skipped.append(str(equipment_id))
                continue

            next_due_str = status.get("next_due_date")
            if not next_due_str:
                skipped.append(str(equipment_id))
                continue

            next_due = date.fromisoformat(next_due_str)
            trigger_date = next_due - __import__("datetime").timedelta(days=cfg.lead_days)

            if today < trigger_date:
                skipped.append(str(equipment_id))
                continue

            # Check if an open calibration request already exists
            open_req = (
                self.db.query(TestingRequest)
                .filter(
                    TestingRequest.equipment_id == equipment_id,
                    TestingRequest.is_calibration == True,  # noqa: E712
                    TestingRequest.status.in_([
                        TestingRequestStatus.draft,
                        TestingRequestStatus.submitted,
                        TestingRequestStatus.assigned,
                        TestingRequestStatus.accepted,
                        TestingRequestStatus.in_progress,
                    ]),
                )
                .first()
            )
            if open_req:
                skipped.append(str(equipment_id))
                continue

            # Create a new calibration request
            equipment = self.db.query(Equipment).filter(Equipment.id == equipment_id).first()
            if not equipment:
                skipped.append(str(equipment_id))
                continue

            cal_type_id = self._get_calibration_type_id()
            count = (
                self.db.query(func.count(TestingRequest.id))
                .filter(TestingRequest.request_number.like(
                    f"TR-CAL-{today.strftime('%Y%m%d')}-%"
                ))
                .scalar()
            )
            request_number = f"TR-CAL-{today.strftime('%Y%m%d')}-{(count + 1):04d}"

            new_req = TestingRequest(
                request_number=request_number,
                title=f"Calibration — {equipment.name or str(equipment_id)}",
                description=f"Auto-created pre-due calibration. Next due: {next_due_str}",
                equipment_id=equipment_id,
                organization_id=equipment.organization_id,
                test_type_id=cal_type_id,
                request_category="test",
                status=TestingRequestStatus.draft,
                is_multi_session=True,
                is_calibration=True,
                priority="normal",
            )
            self.db.add(new_req)
            created.append(str(equipment_id))

        self.db.commit()
        return {
            "date": today.isoformat(),
            "created": len(created),
            "skipped": len(skipped),
            "created_equipment_ids": created,
        }

    def _get_calibration_type_id(self) -> Optional[int]:
        return (
            self.db.query(CategoryDetails.id)
            .filter(func.lower(CategoryDetails.name) == func.lower(CALIBRATION_NAME))
            .scalar()
        )
