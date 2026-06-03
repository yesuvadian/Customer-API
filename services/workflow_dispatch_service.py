"""
Workflow Dispatch Service
=========================
Called after Technical Approver approves a recommendation.
Reads recommendation.next_action and creates the appropriate downstream ticket:

  test          → TestRequestSchedule  (recurring test schedule via TestRequestScheduleService)
  maintenance   → TestRequestSchedule  (recurring maintenance schedule)
  inspection    → TestRequestSchedule  (recurring inspection schedule)
  repair_cycle  → RepairWorkflow       (10-stage repair lifecycle)
  replacement   → ProcurementRequest   (finance approval queue)
  none          → nothing (TR marked approved/complete)

Schedules require a registered equipment (equipment_id).
Type-only TRs (equipment_id=None) skip schedule/ticket creation — by design.
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
                # Equipment commissioning only applies when the TQ captured an
                # equipment_type_id (i.e. the tester was inspecting a specific asset class).
                # Pure site-level TAQC inspections have no equipment_type_id — skip silently.
                equip_id = self._commission_equipment(tr, rec, approver_id) if tr.equipment_type_id else None
                if equip_id:
                    tr.equipment_id = equip_id
                    result["equipment_id"] = str(equip_id)
                    mn_num = self._create_schedule(tr, rec, approver_id,
                                                   category=RequestCategory.maintenance)
                    in_num = self._create_schedule(tr, rec, approver_id,
                                                   category=RequestCategory.inspection)
                    result["mn_schedule"] = mn_num
                    result["in_schedule"] = in_num
                # Commit commissioned status FIRST — schedule creation must never
                # block the status update even if it fails (e.g. migration pending).
                self.db.commit()
                result["status"] = "commissioned"
                # Auto-create TAQCAnnualInspection linked to this TQ
                audit_id = self._create_annual_inspection(tr, approver_id)
                if audit_id:
                    result["annual_inspection_id"] = str(audit_id)
                # Create taqc_inspection recurrence schedule using chosen frequency
                taqc_sched = self._create_taqc_schedule(tr, rec, approver_id)
                result["taqc_schedule"] = taqc_sched
                # Commit schedule + annual inspection inserts (auto-begun after first commit)
                self.db.commit()
            else:
                tr.status = TestingRequestStatus.closed
                result["status"] = "closed"
                tr.completed_at = datetime.now(timezone.utc)
                tr.modified_by = approver_id
                self.db.commit()

        elif action == NextActionType.maintenance:
            numbers = self._create_schedules_for_action(
                tr, rec, approver_id, category=RequestCategory.maintenance
            )
            tr.status = TestingRequestStatus.outcome_active
            tr.completed_at = datetime.now(timezone.utc)
            tr.modified_by = approver_id
            self.db.commit()
            result["created"] = numbers
            result["status"] = "outcome_active"

        elif action == NextActionType.inspection:
            numbers = self._create_schedules_for_action(
                tr, rec, approver_id, category=RequestCategory.inspection
            )
            tr.status = TestingRequestStatus.outcome_active
            tr.completed_at = datetime.now(timezone.utc)
            tr.modified_by = approver_id
            self.db.commit()
            result["created"] = numbers
            result["status"] = "outcome_active"

        elif action == NextActionType.test:
            numbers = self._create_schedules_for_action(
                tr, rec, approver_id, category=RequestCategory.test
            )
            tr.status = TestingRequestStatus.outcome_active
            tr.completed_at = datetime.now(timezone.utc)
            tr.modified_by = approver_id
            self.db.commit()
            result["created"] = numbers
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

        # ── Calibration workflow auto-trigger ─────────────────────────────────
        # Fires on result approval when any test result for this TR has a
        # template containing a DATE_ADD rule AND overall_result == "fail".
        # This is independent of next_action — calibration workflow is always
        # auto-triggered by the template rule, not by the tester's recommendation.
        self._maybe_trigger_calibration_workflow(tr, approver_id, result)

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _create_annual_inspection(self, tr, approver_id: UUID):
        """Auto-create TAQCAnnualInspection + observation workflow from a commissioned TAQC TQ."""
        from models import TAQCAnnualInspection
        from services.annual_audit_service import AnnualAuditService
        from services.testing_request_service import TestingRequestService
        try:
            if not tr.department_id or not tr.organization_id:
                return None

            # Pull form data submitted by the tester
            test_data: dict = {}
            latest = (
                self.db.query(__import__("models", fromlist=["TestResult"]).TestResult)
                .filter_by(testing_request_id=tr.id)
                .order_by(__import__("models", fromlist=["TestResult"]).TestResult.tested_at.desc())
                .first()
            )
            if latest and latest.test_data:
                test_data = latest.test_data

            svc = AnnualAuditService(self.db)
            number = svc._next_number("TR-ANU-INSP")
            inspection_date = test_data.get("inspection_date") or datetime.now(timezone.utc).date()
            if isinstance(inspection_date, str):
                from datetime import date as _date
                try:
                    inspection_date = _date.fromisoformat(inspection_date)
                except Exception:
                    inspection_date = datetime.now(timezone.utc).date()

            inspection = TAQCAnnualInspection(
                inspection_number=number,
                organization_id=tr.organization_id,
                department_id=tr.department_id,
                inspection_date=inspection_date,
                inspected_by=tr.originator_id or approver_id,
                remarks=test_data.get("remarks") or f"Auto-created from {tr.request_number}",
                created_by=approver_id,
            )
            self.db.add(inspection)
            self.db.flush()
            print(f"[Dispatch] Created TAQCAnnualInspection {number} for TQ {tr.request_number}")

            # Auto-create observation + workflow from form data if tester filled it in
            cat_name = test_data.get("inspection_category")
            obs_desc = test_data.get("observation_description")
            severity  = test_data.get("severity")
            compliance_date = test_data.get("target_compliance_date")
            if cat_name and obs_desc:
                obs_sp = self.db.begin_nested()
                try:
                    from models import CategoryDetails, CategoryMaster, TAQCObservation
                    cat_detail = (
                        self.db.query(CategoryDetails)
                        .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                        .filter(
                            CategoryMaster.name == "Annual Audit Categories",
                            CategoryDetails.name == cat_name,
                        )
                        .first()
                    )
                    if cat_detail:
                        obs_number = svc._next_number("TR-ANU")
                        from datetime import date as _date
                        parsed_compliance = None
                        if compliance_date:
                            try:
                                parsed_compliance = _date.fromisoformat(str(compliance_date))
                            except Exception:
                                pass
                        observation = TAQCObservation(
                            inspection_id=inspection.id,
                            observation_number=obs_number,
                            category_detail_id=cat_detail.id,
                            severity=severity,
                            target_compliance_date=parsed_compliance,
                            observation_description=obs_desc,
                            current_stage_code="OBSERVATION_REPORTING",
                            created_by=approver_id,
                        )
                        self.db.add(observation)
                        self.db.flush()

                        # Create the observation compliance workflow
                        approver_user = self.db.query(__import__("models", fromlist=["User"]).User).filter_by(id=approver_id).first()
                        if approver_user:
                            workflow = svc._create_runtime_workflow(inspection, observation, approver_user)
                            observation.workflow_id = workflow.id
                            self.db.flush()
                            print(f"[Dispatch] Created observation workflow {workflow.id} for {obs_number}")
                    obs_sp.commit()
                except Exception as obs_err:
                    obs_sp.rollback()
                    print(f"[Dispatch] WARN: could not create observation workflow for {tr.request_number}: {obs_err}")

            return inspection.id
        except Exception as e:
            print(f"[Dispatch] WARN: could not create TAQCAnnualInspection for {tr.request_number}: {e}")
            return None

    def _create_taqc_schedule(self, tr, rec, approver_id: UUID) -> str:
        """Create a taqc_inspection recurrence schedule so the next TQ is auto-generated.

        TAQC inspections are site-level (substation). test_type_id is set to the
        seeded 'Annual TA&QC Inspection' CategoryDetails row; equipment_type_id is NULL.
        Schedule is keyed by (organization_id, department_id, request_category).
        """
        from services.test_request_schedule_service import _advance_date
        from models import CategoryDetails as _CD, TestRequestSchedule
        try:
            if not tr.organization_id:
                return ""

            # Resolve the seeded test type for TAQC schedules
            taqc_detail = self.db.query(_CD).filter_by(
                name="Annual TA&QC Inspection"
            ).first()
            if not taqc_detail:
                print("[Dispatch] WARN: 'Annual TA&QC Inspection' CategoryDetails not found — run seed first")
                return ""

            freq    = rec.schedule_frequency or ScheduleFrequency.yearly
            now     = datetime.now(timezone.utc)
            dept_id = tr.department_id  # submitter's department (substation/site)

            # Use the compliance date as next_run_date directly.
            # If it is within the advance window (15 days), the scheduler creates
            # the inspection workflow ticket immediately on its next run.
            # After each completed cycle, next_run is advanced by frequency.
            next_run = tr.due_date if tr.due_date else _advance_date(now, freq)

            existing = self.db.query(TestRequestSchedule).filter(
                TestRequestSchedule.organization_id == tr.organization_id,
                TestRequestSchedule.department_id == dept_id,
                TestRequestSchedule.request_category == RequestCategory.taqc_inspection,
                TestRequestSchedule.is_deleted == False,
            ).first()
            if existing:
                existing.frequency      = freq
                existing.next_run_date  = next_run
                existing.is_active      = True
                self.db.flush()
                print(f"[Dispatch] Updated taqc_inspection schedule id={existing.id} next={next_run.date()}")
                return str(existing.id)

            schedule = TestRequestSchedule(
                organization_id=tr.organization_id,
                department_id=dept_id,
                equipment_id=None,
                equipment_type_id=None,
                test_type_id=taqc_detail.id,
                title=tr.title,
                request_category=RequestCategory.taqc_inspection,
                frequency=freq,
                start_date=now,
                next_run_date=next_run,
                advance_days=15,
                is_active=True,
                created_by=approver_id,
            )
            # Use a savepoint so a flush failure only rolls back the schedule
            # insert, not the entire dispatch transaction (commissioned status, etc.)
            savepoint = self.db.begin_nested()
            self.db.add(schedule)
            try:
                savepoint.commit()
            except Exception as flush_err:
                savepoint.rollback()
                print(f"[Dispatch] WARN: taqc_inspection schedule flush failed for {tr.request_number}: {flush_err}")
                return ""
            print(f"[Dispatch] Created taqc_inspection schedule id={schedule.id} freq={freq.value} dept={dept_id}")
            return str(schedule.id)
        except Exception as e:
            print(f"[Dispatch] WARN: could not create taqc_inspection schedule for {tr.request_number}: {e}")
            return ""

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

    def _create_schedules_for_action(
        self,
        tr: TestingRequest,
        rec: Recommendation,
        approver_id: UUID,
        category: RequestCategory,
    ) -> list[str]:
        """
        Create one operational schedule per recommended test type.
        Falls back to tr.test_type_id (single) when no test_types list is present.
        Returns list of schedule ids/numbers created.
        """
        test_types: list[dict] = rec.test_types or []
        if test_types:
            def _safe_int(val):
                """Convert test_type id to int regardless of whether it arrived as int or str."""
                try:
                    return int(val) if val is not None else None
                except (ValueError, TypeError):
                    return None

            return [
                self._create_schedule(tr, rec, approver_id, category=category,
                                      test_type_id=_safe_int(t.get("id")))
                for t in test_types
            ]
        # Legacy / TAQC path — single test_type_id on the TR
        return [self._create_schedule(tr, rec, approver_id, category=category,
                                      test_type_id=tr.test_type_id)]

    def _create_schedule(
        self,
        tr: TestingRequest,
        rec: Recommendation,
        approver_id: UUID,
        category: RequestCategory,
        test_type_id: Optional[int] = None,
    ) -> str:
        """
        Create an operational TestRequestSchedule for recurring work triggered by
        an approved FR/TR recommendation.  Uses the same flow as equipment onboarding
        (equipment_id-based operational schedule + immediate trigger check).

        Returns the schedule UUID as a string.
        """
        from services.test_request_schedule_service import (
            TestRequestScheduleService,
            _advance_date,
        )

        now = datetime.now(timezone.utc)
        freq = rec.schedule_frequency or ScheduleFrequency.yearly
        effective_start = tr.scheduled_start_date or now

        # If the original TR start date is in the past, anchor next_run_date to
        # now so the first ticket is always one full period in the future.
        # (A past start_date would cause _advance_date to return a date already
        # within — or past — the 15-day window, triggering an unwanted immediate
        # ticket at approval time.)
        schedule_base = effective_start if effective_start > now else now

        # Guard: equipment_id is required for operational schedules.
        # Tickets are only meaningful for a specific registered equipment asset.
        # Type-only TRs (equipment_id=None) cannot produce a recurring schedule.
        if not tr.equipment_id:
            print(
                f"[Dispatch] SKIP: no equipment_id on TR {tr.request_number} "
                f"— recommendation noted but no schedule/ticket created"
            )
            return ""

        # Guard: test_type_id is NOT NULL in test_request_schedules
        if test_type_id is None:
            print(
                f"[Dispatch] WARN: cannot create operational schedule for TR "
                f"{tr.request_number} — test_type_id is None (no test type on rec.test_types or TR)"
            )
            return ""

        # Resolve equipment_type_id — FR TRs don't carry this directly; load from Equipment
        equipment_type_id = tr.equipment_type_id
        if not equipment_type_id:
            from models import Equipment as _Equip
            eq = self.db.query(_Equip).filter(_Equip.id == tr.equipment_id).first()
            equipment_type_id = eq.equipment_type_id if eq else None

        if not equipment_type_id:
            print(
                f"[Dispatch] WARN: cannot create operational schedule for TR "
                f"{tr.request_number} — equipment_type_id is None"
            )
            return ""

        # Idempotency: don't create duplicate schedule for same equipment + test type
        existing = (
            self.db.query(TestRequestSchedule)
            .filter(
                TestRequestSchedule.equipment_id == tr.equipment_id,
                TestRequestSchedule.test_type_id == test_type_id,
                TestRequestSchedule.is_deleted == False,
            )
            .first()
        )
        if existing:
            print(
                f"[Dispatch] Operational schedule already exists "
                f"(id={existing.id}) for equipment {tr.equipment_id} "
                f"test_type {test_type_id} — skipping create"
            )
            return str(existing.id)

        try:
            from config import SCHEDULE_ADVANCE_DAYS as _adv
        except Exception:
            _adv = 15

        schedule = TestRequestSchedule(
            equipment_id=tr.equipment_id,
            equipment_type_id=equipment_type_id,
            test_type_id=test_type_id,
            organization_id=tr.organization_id,
            title=tr.title,
            request_category=category,
            frequency=freq,
            start_date=effective_start,
            next_run_date=_advance_date(schedule_base, freq),
            advance_days=_adv,
            is_active=True,
            created_by=approver_id,
        )
        self.db.add(schedule)
        self.db.flush()   # populate schedule.id

        print(
            f"[Dispatch] Created operational schedule id={schedule.id} "
            f"(category={category.value}, freq={freq.value}, "
            f"start={effective_start.date()}, "
            f"next_run={schedule.next_run_date.date()})"
        )

        # Immediate first-ticket trigger (same logic as onboarding).
        # The scheduler daemon creates subsequent tickets on each next_run_date.
        try:
            self.db.refresh(schedule)
            created = TestRequestScheduleService.create_one_ticket(
                db=self.db,
                schedule=schedule,
                now=now,
            )
            if created:
                print(f"[Dispatch] First ticket created immediately for schedule {schedule.id}")
            else:
                print(f"[Dispatch] First ticket deferred (outside advance window) for schedule {schedule.id}")
        except Exception as _e:
            print(f"[Dispatch] WARN: immediate ticket creation raised: {_e}")

        return str(schedule.id)


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

    def _maybe_trigger_calibration_workflow(
        self,
        tr: TestingRequest,
        approver_id: UUID,
        result: dict,
    ) -> None:
        """
        After result approval, handle calibration lifecycle based on outcome:
          - Fail + DATE_ADD template → trigger CALIBRATION RepairWorkflow + stop scheduler
          - Pass + DATE_ADD template → resume scheduler so pre-due check auto-creates
                                       the next calibration ticket near next_due_date

        Fire-and-forget — never blocks the approval transaction.
        """
        if not tr.equipment_id:
            return
        try:
            results = (
                self.db.query(TestResult)
                .filter(TestResult.testing_request_id == tr.id)
                .all()
            )

            fail_template = None
            pass_template = None

            for r in results:
                outcome = (r.overall_result or "").strip().lower()
                if not r.template_key:
                    continue
                # Resolve template: static dict first, then OrgTestTemplate
                from test_templates import get_template_by_key as _get_tpl
                tmpl = _get_tpl(r.template_key)
                if tmpl is None:
                    try:
                        from models import OrgTestTemplate
                        ot = (
                            self.db.query(OrgTestTemplate)
                            .filter(OrgTestTemplate.template_key == r.template_key)
                            .first()
                        )
                        tmpl = ot.template_data if ot else None
                    except Exception:
                        tmpl = None
                has_date_add = any(
                    (rule.get("type") or "").upper() == "DATE_ADD"
                    for rule in (tmpl or {}).get("rules", [])
                )
                if not has_date_add:
                    continue
                if outcome == "fail" and fail_template is None:
                    fail_template = r.template_key
                elif outcome == "pass" and pass_template is None:
                    pass_template = r.template_key

            from services.calibration_service import CalibrationService
            cal_svc = CalibrationService(self.db)

            if fail_template:
                # Fail: stop scheduling + create calibration repair workflow
                cal_svc._handle_fail(equipment_id=tr.equipment_id, user_id=approver_id)
                result["calibration_workflow"] = "triggered"
                result["calibration_triggered_by_template"] = fail_template
                print(
                    f"[CALIBRATION] Workflow triggered at result approval — "
                    f"equipment={tr.equipment_id} template={fail_template}"
                )
            elif pass_template:
                # Pass: re-enable scheduling flag + upsert test_request_schedules
                # entry so the existing scheduler creates the next ticket
                # automatically at next_due_date - lead_days.
                cal_svc.resume_schedule(equipment_id=tr.equipment_id, user_id=approver_id)
                schedule_id = cal_svc.upsert_calibration_schedule(tr=tr, user_id=approver_id)
                result["calibration_scheduling"] = "resumed"
                result["calibration_schedule_id"] = schedule_id
                result["calibration_pass_template"] = pass_template
                print(
                    f"[CALIBRATION] Scheduling resumed + schedule upserted "
                    f"(id={schedule_id}) — equipment={tr.equipment_id} template={pass_template}"
                )

        except Exception as _err:
            import traceback
            print(f"[WARN] Calibration workflow trigger failed at approval: {_err}")
            traceback.print_exc()

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
            replacement_products=rec.replacement_products or [],
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
