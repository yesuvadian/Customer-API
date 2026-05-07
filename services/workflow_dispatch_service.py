"""
Workflow Dispatch Service
=========================
Called after Technical Approver approves a recommendation.
Reads recommendation.next_action and creates the appropriate downstream ticket:

  maintenance   → TestRequestSchedule  (MN- prefix, recurring maintenance)
  inspection    → TestRequestSchedule  (IN- prefix, recurring inspection)
  repair_cycle  → RepairWorkflow       (10-stage repair lifecycle)
  replacement   → ProcurementRequest   (finance approval queue)
  none          → nothing (TR marked approved/complete)
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from models import (
    NextActionType,
    ProcurementRequest,
    Recommendation,
    RepairWorkflow,
    RequestCategory,
    ScheduleFrequency,
    TestingRequest,
    TestingRequestStatus,
    TestRequestSchedule,
    TestResult,
)


class WorkflowDispatchService:
    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # Public entry point
    # ─────────────────────────────────────────────────────────────────────────

    def dispatch(
        self,
        tr: TestingRequest,
        rec: Recommendation,
        approver_id: UUID,
    ) -> dict:
        """
        Dispatch next action after technical approval.

        Returns a dict describing what was created (for the API response).
        """
        action = rec.next_action
        result = {"next_action": action.value if action else "none", "created": None}

        if action is None or action == NextActionType.none:
            # TAQC inspections complete as 'commissioned' + auto-create Equipment + MN/IN schedules
            if tr.request_category == RequestCategory.taqc_inspection:
                tr.status = TestingRequestStatus.commissioned
                tr.completed_at = datetime.now(timezone.utc)
                tr.modified_by = approver_id
                equip_id = self._commission_equipment(tr, rec, approver_id)
                if equip_id:
                    tr.equipment_id = equip_id
                    result["equipment_id"] = str(equip_id)
                    # Auto-create MN and IN schedules for the newly commissioned equipment
                    mn_num = self._create_schedule(tr, rec, approver_id, prefix="MN",
                                                   category=RequestCategory.maintenance)
                    in_num = self._create_schedule(tr, rec, approver_id, prefix="IN",
                                                   category=RequestCategory.inspection)
                    result["mn_schedule"] = mn_num
                    result["in_schedule"] = in_num
                result["status"] = "commissioned"
                self.db.commit()
            else:
                tr.status = TestingRequestStatus.approved
                result["status"] = "approved"
                tr.completed_at = datetime.now(timezone.utc)
                tr.modified_by = approver_id
                self.db.commit()

        elif action == NextActionType.maintenance:
            number = self._create_schedule(tr, rec, approver_id, prefix="MN",
                                           category=RequestCategory.maintenance)
            tr.status = TestingRequestStatus.outcome_active
            tr.completed_at = datetime.now(timezone.utc)
            tr.modified_by = approver_id
            self.db.commit()
            result["created"] = number
            result["status"] = "outcome_active"

        elif action == NextActionType.inspection:
            number = self._create_schedule(tr, rec, approver_id, prefix="IN",
                                           category=RequestCategory.inspection)
            tr.status = TestingRequestStatus.outcome_active
            tr.completed_at = datetime.now(timezone.utc)
            tr.modified_by = approver_id
            self.db.commit()
            result["created"] = number
            result["status"] = "outcome_active"

        elif action == NextActionType.repair_cycle:
            wf_id = self._start_repair_workflow(tr, approver_id)
            tr.status = TestingRequestStatus.outcome_active
            tr.completed_at = datetime.now(timezone.utc)
            tr.modified_by = approver_id
            self.db.commit()
            result["created"] = wf_id
            result["status"] = "outcome_active"

        elif action == NextActionType.replacement:
            pr_number = self._create_procurement(tr, rec, approver_id)
            tr.status = TestingRequestStatus.finance_pending
            tr.modified_by = approver_id
            self.db.commit()
            result["created"] = pr_number
            result["status"] = "finance_pending"

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _commission_equipment(
        self,
        tr: TestingRequest,
        rec: Recommendation,
        approver_id: UUID,
    ) -> Optional[UUID]:
        """
        Auto-create an Equipment record from the E&C form data stored in the
        latest TestResult.test_data for this TAQC inspection TR.

        Returns the new Equipment.id, or None if creation fails.

        Expected test_data keys (all optional — only what the tester filled):
          voltage_class, bay_number, manufacturer, model_number,
          factory_serial_number, year_of_manufacture,
          + any other nameplate fields (stored as-is in nameplate_data JSONB).
        """
        if not tr.equipment_type_id or not tr.organization_id or not tr.department_id:
            print(
                f"[Dispatch] WARN: cannot commission equipment for TR {tr.request_number} "
                f"— missing equipment_type_id / organization_id / department_id"
            )
            return None

        # Pull E&C data from the latest test result
        latest_result = (
            self.db.query(TestResult)
            .filter(TestResult.testing_request_id == tr.id)
            .order_by(TestResult.tested_at.desc())
            .first()
        )
        test_data: dict = (latest_result.test_data or {}) if latest_result else {}

        # Well-known nameplate fields promoted to Equipment columns
        voltage_class          = test_data.get("voltage_class") or tr.voltage_class if hasattr(tr, "voltage_class") else test_data.get("voltage_class")
        bay_number             = test_data.get("bay_number")
        manufacturer           = test_data.get("manufacturer")
        model_number           = test_data.get("model_number")
        factory_serial_number  = test_data.get("factory_serial_number") or test_data.get("serial_number")
        raw_yom                = test_data.get("year_of_manufacture")
        try:
            year_of_manufacture = int(raw_yom) if raw_yom else None
        except (ValueError, TypeError):
            year_of_manufacture = None

        try:
            from services.equipment_service import EquipmentService
            equipment = EquipmentService.create_equipment(
                db=self.db,
                organization_id=tr.organization_id,
                department_id=tr.department_id,
                equipment_type_id=tr.equipment_type_id,
                voltage_class=voltage_class,
                bay_number=bay_number,
                nameplate_data=test_data,          # full E&C form → JSONB
                commissioned_date=datetime.now(timezone.utc),
                manufacturer=manufacturer,
                model_number=model_number,
                factory_serial_number=factory_serial_number,
                year_of_manufacture=year_of_manufacture,
                created_by=approver_id,
            )
            print(
                f"[Dispatch] Commissioned equipment UEIC={equipment.ueic} "
                f"id={equipment.id} for TR {tr.request_number}"
            )
            return equipment.id
        except Exception as e:
            print(f"[Dispatch] WARN: equipment commissioning failed for TR {tr.request_number}: {e}")
            return None

    def _generate_number(self, prefix: str) -> str:
        """Generate ticket number like MN-20260501-0003."""
        from sqlalchemy import func
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        count = (
            self.db.query(func.count(TestingRequest.id))
            .filter(TestingRequest.request_number.like(f"{prefix}-{today}-%"))
            .scalar()
        ) or 0
        return f"{prefix}-{today}-{(count + 1):04d}"

    def _create_schedule(
        self,
        tr: TestingRequest,
        rec: Recommendation,
        approver_id: UUID,
        prefix: str,
        category: RequestCategory,
    ) -> str:
        """Create a TestingRequest (template) + TestRequestSchedule for recurring work."""
        now = datetime.now(timezone.utc)
        number = self._generate_number(prefix)

        freq = rec.schedule_frequency or ScheduleFrequency.yearly

        # Create the template TR (is_schedule_template=True)
        sched_tr = TestingRequest(
            request_number=number,
            title=f"[{prefix}] {tr.title}",
            description=(
                f"Auto-created from approved recommendation.\n"
                f"Source TR: {tr.request_number}\n"
                f"Frequency: {freq.value}"
            ),
            request_category=category,
            equipment_id=tr.equipment_id,
            equipment_type_id=tr.equipment_type_id,
            test_type_id=tr.test_type_id,
            organization_id=tr.organization_id,
            department_id=tr.department_id,
            priority=tr.priority or "normal",
            status=TestingRequestStatus.draft,
            is_schedule_template=True,
            source_failure_id=tr.id,
            originator_id=tr.originator_id,
            created_by=approver_id,
            requested_date=now,
        )
        self.db.add(sched_tr)
        self.db.flush()

        # Create schedule
        schedule = TestRequestSchedule(
            test_request_id=sched_tr.id,
            organization_id=tr.organization_id,
            frequency=freq,
            start_date=now,
            next_run_date=now,
            advance_days=7,
            is_active=True,
            created_by=approver_id,
        )
        self.db.add(schedule)
        print(f"[Dispatch] Created {prefix} schedule {number} (freq={freq.value})")
        return number

    def _start_repair_workflow(
        self,
        tr: TestingRequest,
        approver_id: UUID,
    ) -> Optional[str]:
        """Start the 10-stage RepairWorkflow for the equipment."""
        if not tr.equipment_id:
            print(f"[Dispatch] WARN: repair_cycle dispatch skipped — TR {tr.request_number} has no equipment_id")
            return None
        try:
            from services.repair_workflow_service import RepairWorkflowService
            svc = RepairWorkflowService(self.db)
            wf_dict = svc.start_workflow(
                equipment_id=tr.equipment_id,
                user_id=approver_id,
            )
            wf = self.db.query(RepairWorkflow).filter(
                RepairWorkflow.id == UUID(wf_dict["id"])
            ).first()
            if wf:
                wf.source_failure_id = tr.id
                self.db.flush()
            print(f"[Dispatch] Started RepairWorkflow {wf_dict['id']} for equipment {tr.equipment_id}")
            return wf_dict["id"]
        except Exception as e:
            print(f"[Dispatch] WARN: repair workflow start failed: {e}")
            return None

    def _create_procurement(
        self,
        tr: TestingRequest,
        rec: Recommendation,
        approver_id: UUID,
    ) -> str:
        """Create a ProcurementRequest for replacement approval by Finance."""
        from sqlalchemy import func
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        count = (
            self.db.query(func.count(ProcurementRequest.id))
            .filter(ProcurementRequest.procurement_number.like(f"PR-{today}-%"))
            .scalar()
        ) or 0
        pr_number = f"PR-{today}-{(count + 1):04d}"

        pr = ProcurementRequest(
            procurement_number=pr_number,
            testing_request_id=tr.id,
            recommendation_id=rec.id,
            organization_id=tr.organization_id,
            title=f"[Replacement] {tr.title}",
            description=(
                f"Auto-created from approved recommendation (next_action=replacement).\n"
                f"Source TR: {tr.request_number}\n"
                f"Approver notes: {rec.approval_notes or 'N/A'}"
            ),
            status="pending_finance",
            raised_by=approver_id,
            created_by=approver_id,
        )
        self.db.add(pr)
        self.db.flush()
        print(f"[Dispatch] Created ProcurementRequest {pr_number}")

        # Notify Finance Approvers that a new procurement request is awaiting review
        try:
            from services.notification_service import NotificationService
            NotificationService(self.db).notify_procurement_pending(tr, pr_number)
        except Exception as _n:
            print(f"[Dispatch] WARN: procurement_pending notification failed: {_n}")

        return pr_number
