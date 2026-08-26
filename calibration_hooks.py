"""
calibration_hooks.py
────────────────────
Registers lifecycle hooks for the CALIBRATION repair workflow.

Imported once at app startup (main.py) — the import is the registration.
No other file needs to know about CalibrationService.

Hooks
-----
  completed  — CAL_VERIFY approved (terminal):
               • re-enable equipment scheduling (is_scheduled = True)
               • upsert test_request_schedules so the existing scheduler
                 auto-creates the next calibration ticket near next_due - lead_days

  stage_approved (CAL_CERTIFICATE) — certificate uploaded and approved:
               • read calibration_date + validity_months from stage form data
               • write a new TestResult so _get_latest_reading() picks up the
                 new calibration data for schedule computation
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from workflow_hooks import register

logger = logging.getLogger(__name__)

CALIBRATION_WORKFLOW_CODE = "CALIBRATION"
CAL_CERTIFICATE_CODE      = "CAL_CERTIFICATE"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: read CAL_CERTIFICATE stage form_data from repair_stage_data
# ─────────────────────────────────────────────────────────────────────────────

def _get_certificate_stage_data(db, workflow_id: UUID) -> Optional[dict]:
    """
    Return the form_data dict from the completed CAL_CERTIFICATE stage instance,
    or None if not found.
    """
    from models import RepairStageDefinition, RepairStageInstance

    # Find CAL_CERTIFICATE stage definition
    cert_stage = (
        db.query(RepairStageDefinition)
        .filter_by(code=CAL_CERTIFICATE_CODE)
        .first()
    )
    if not cert_stage:
        return None

    # Find the completed instance for this workflow
    instance = (
        db.query(RepairStageInstance)
        .filter_by(workflow_id=workflow_id, stage_id=cert_stage.id, status="completed")
        .first()
    )
    if not instance:
        return None

    # Read form_data from repair_stage_data
    from models import Base
    from sqlalchemy import text
    row = db.execute(
        text("SELECT form_data FROM repair_stage_data WHERE stage_instance_id = :sid LIMIT 1"),
        {"sid": str(instance.id)},
    ).fetchone()

    return dict(row[0]) if row and row[0] else None


# ─────────────────────────────────────────────────────────────────────────────
# Helper: create / upsert TestResult from certificate stage data
# ─────────────────────────────────────────────────────────────────────────────

def _record_certificate_as_test_result(db, workflow, user_id: UUID, cert_data: dict) -> None:
    """
    Persist the lab certificate data (calibration_date, validity_months, etc.)
    as a TestResult so CalibrationService._get_latest_reading() picks it up.
    Idempotent — skips if a result with this calibration_date already exists.
    """
    from models import TestingRequest, TestingRequestStatus, TestResult

    cal_date    = cert_data.get("calibration_date")
    val_months  = cert_data.get("validity_months")
    if not cal_date or not val_months:
        logger.warning("[CalibrationHook] certificate stage missing calibration_date/validity_months")
        return

    # Find the latest calibration TestingRequest for this equipment
    tr = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.equipment_id == workflow.equipment_id,
            TestingRequest.is_calibration.is_(True),
        )
        .order_by(TestingRequest.cts.desc())
        .first()
    )
    if not tr:
        logger.warning("[CalibrationHook] no calibration TestingRequest found for equipment %s", workflow.equipment_id)
        return

    # Idempotency: skip if a result with this calibration_date already exists
    existing = (
        db.query(TestResult)
        .filter(TestResult.testing_request_id == tr.id)
        .all()
    )
    for r in existing:
        if (r.test_data or {}).get("calibration_date") == cal_date:
            logger.info("[CalibrationHook] TestResult for cal_date %s already exists — skipping", cal_date)
            return

    result = TestResult(
        id=uuid.uuid4(),
        testing_request_id=tr.id,
        overall_result="pass",
        template_key=tr.test_type_id and "calibration",
        test_data={
            "calibration_date":    cal_date,
            "validity_months":     val_months,
            "overall_result":      cert_data.get("overall_result", "pass"),
            "calibrated_by":       cert_data.get("calibrated_by"),
            "certificate_number":  cert_data.get("certificate_number"),
            "notes":               cert_data.get("notes"),
            "source":              "calibration_workflow",
        },
        tested_at=datetime.now(timezone.utc),
        created_by=user_id,
    )
    db.add(result)
    db.flush()
    logger.info("[CalibrationHook] TestResult created from CAL_CERTIFICATE data for TR %s", tr.request_number)


# ─────────────────────────────────────────────────────────────────────────────
# Hook: workflow completed (CAL_VERIFY approved → terminal)
# ─────────────────────────────────────────────────────────────────────────────

def _on_calibration_completed(db, workflow, user_id, **_kwargs) -> None:
    """
    Called when the CALIBRATION workflow reaches its terminal state.
    1. Read certificate data from CAL_CERTIFICATE stage
    2. Record it as a TestResult (so _get_latest_reading finds it)
    3. Resume scheduling flag
    4. Upsert test_request_schedules with next_run_date = next_due - lead_days
    """
    from services.calibration_service import CalibrationService

    if not workflow.equipment_id:
        return

    svc = CalibrationService(db)

    # Step 1 — read certificate stage form data
    cert_data = _get_certificate_stage_data(db, workflow.id)
    if cert_data:
        _record_certificate_as_test_result(db, workflow, user_id, cert_data)
    else:
        logger.warning(
            "[CalibrationHook] CAL_CERTIFICATE form data not found for workflow %s "
            "— schedule will use last known calibration reading",
            workflow.id,
        )

    # Step 2 — re-enable scheduling flag
    svc.resume_schedule(equipment_id=workflow.equipment_id, user_id=user_id)

    # Step 2b — close the OPEN recommendation that gated re-triggering.
    # Without this, _get_open_repair_recommendation() keeps finding it forever
    # and every future Fail on this equipment silently creates no new workflow.
    svc.close_open_recommendation(equipment_id=workflow.equipment_id, user_id=user_id)

    # Step 3 — upsert test_request_schedules from latest reading
    # Build a minimal TR-like object from the workflow so upsert_calibration_schedule
    # doesn't need an actual TestingRequest.
    from models import TestingRequest
    tr = (
        db.query(TestingRequest)
        .filter(
            TestingRequest.equipment_id == workflow.equipment_id,
            TestingRequest.is_calibration.is_(True),
        )
        .order_by(TestingRequest.cts.desc())
        .first()
    )
    if tr:
        schedule_id = svc.upsert_calibration_schedule(tr=tr, user_id=user_id)
        logger.info(
            "[CalibrationHook] schedule upserted (id=%s) after CALIBRATION workflow %s completed",
            schedule_id, workflow.id,
        )
    else:
        logger.warning(
            "[CalibrationHook] no calibration TR found for equipment %s — schedule not upserted",
            workflow.equipment_id,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Registration — runs on import
# ─────────────────────────────────────────────────────────────────────────────

register(CALIBRATION_WORKFLOW_CODE, "completed", _on_calibration_completed)

logger.info("[CalibrationHook] registered CALIBRATION.completed hook")
