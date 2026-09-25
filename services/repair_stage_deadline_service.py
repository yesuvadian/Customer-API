"""
Proactive deadline alerts for Repair-family workflow stages (Breakdown,
Overhaul, Calibration, Surveillance, Annual Audit, Pre-Commission, ...).

Each open stage has a due_at (started_at + default_duration_days, kept in
step by models._sync_repair_stage_due_at). run_deadline_check() - run hourly
from main.py - raises up to three one-shot alerts per stage entry:

  due soon    due_at - window <= now < due_at              -> stage roles + assignee
  overdue     now >= due_at                                -> stage roles + assignee
  escalation  now >= due_at + STAGE_ESCALATION_DAYS        -> approver + override roles

The due-soon window is STAGE_DUE_SOON_HOURS, capped at half the stage's
duration so a short stage isn't warned the moment it starts. While a stage
is submitted and waiting for approval, due-soon/overdue go to its approver
roles instead of the stage roles + assignee (who has already done their part).

Only the highest level reached is sent; lower levels are marked as passed so
a stage first seen far past its deadline gets one escalation, not three
alerts at once. The *_notified_at guards are cleared when the stage
restarts, so a stage re-entered after a reject is alerted afresh.

Every uvicorn worker process runs its own scheduler, so each stage row is
locked (FOR UPDATE SKIP LOCKED) and its guards re-read before sending; a
second worker either skips the locked row or sees the guard already set.

Lead time and escalation threshold are .env tunables (config.py), not
NotificationScheduleRule rows: that engine evaluates every rule against
TestingRequest.due_date, so a rule for these events would misfire on test
requests.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

import config
from models import (
    Equipment,
    RepairStageInstance,
    RepairStageRole,
    RepairWorkflow,
    RepairWorkflowOverrideRole,
)
from utils.db_time import db_naive_to_aware

logger = logging.getLogger(__name__)

EVENT_DUE_SOON = "repair_stage_due_soon"
EVENT_OVERDUE = "repair_stage_overdue"
EVENT_ESCALATION = "repair_stage_escalation"

# Stage statuses that mean the stage is still waiting on someone.
_OPEN_STATUSES = ("pending", "not_started", "assigned", "in_progress", "submitted")


def _user_name(user) -> str:
    if not user:
        return "Unassigned"
    return f"{user.firstname or ''} {user.lastname or ''}".strip() or user.email


def _fmt_duration(delta: timedelta) -> str:
    hours = int(delta.total_seconds() // 3600)
    return f"{hours // 24} day(s)" if hours >= 24 else f"{hours} hour(s)"


class RepairStageDeadlineService:
    def __init__(self, db: Session):
        self.db = db

    def _candidate_ids(self) -> list:
        """Current stage of every active workflow that may need an alert."""
        rows = (
            self.db.query(RepairStageInstance.id)
            .join(RepairWorkflow, RepairWorkflow.current_stage_instance_id == RepairStageInstance.id)
            .filter(
                RepairWorkflow.status == "active",
                RepairStageInstance.status.in_(_OPEN_STATUSES),
                RepairStageInstance.due_at.isnot(None),
                RepairStageInstance.escalation_notified_at.is_(None),
                # Only stages inside the longest due-soon window or later.
                # due_at is stored session-local, and Postgres compares it to
                # now() in the session zone, so this needs no conversion.
                RepairStageInstance.due_at
                <= func.now() + timedelta(hours=config.STAGE_DUE_SOON_HOURS),
            )
            .all()
        )
        return [r for (r,) in rows]

    def _lock_stage(self, instance_id):
        """Lock one stage row and load fresh state, or None if another worker
        holds it or it no longer needs checking."""
        inst = (
            self.db.query(RepairStageInstance)
            .filter(RepairStageInstance.id == instance_id)
            .with_for_update(skip_locked=True)
            .populate_existing()
            .first()
        )
        if inst is None or inst.escalation_notified_at or inst.status not in _OPEN_STATUSES:
            return None
        workflow = inst.workflow
        if not workflow or workflow.status != "active" or workflow.current_stage_instance_id != inst.id:
            return None
        return inst

    def _stage_roles(self, stage_id, approvers_only: bool = False) -> list:
        q = self.db.query(RepairStageRole.role_id).filter(RepairStageRole.stage_id == stage_id)
        if approvers_only:
            q = q.filter(RepairStageRole.can_approve.is_(True))
        return [str(r) for (r,) in q.all() if r]

    def _override_roles(self, workflow_definition_id) -> list:
        if not workflow_definition_id:
            return []
        rows = (
            self.db.query(RepairWorkflowOverrideRole.role_id)
            .filter(RepairWorkflowOverrideRole.workflow_definition_id == workflow_definition_id)
            .all()
        )
        return [str(r) for (r,) in rows if r]

    def run_deadline_check(self) -> dict:
        from services.notification_service import NotificationService

        now = datetime.now(timezone.utc)
        due_soon_max = timedelta(hours=config.STAGE_DUE_SOON_HOURS)
        escalate_after = timedelta(days=config.STAGE_ESCALATION_DAYS)
        sent = {EVENT_DUE_SOON: 0, EVENT_OVERDUE: 0, EVENT_ESCALATION: 0}
        nsvc = NotificationService(self.db)

        for instance_id in self._candidate_ids():
            inst = self._lock_stage(instance_id)
            if inst is None:
                self.db.rollback()
                continue
            workflow, stage = inst.workflow, inst.stage
            equipment = self.db.get(Equipment, workflow.equipment_id) if workflow.equipment_id else None
            if stage is None or equipment is None or inst.due_at is None:
                self.db.rollback()
                continue

            due_at = db_naive_to_aware(inst.due_at, self.db)
            started_at = db_naive_to_aware(inst.started_at, self.db)
            # Cap the warning window at half the stage's duration.
            due_soon_window = (
                min(due_soon_max, (due_at - started_at) / 2) if started_at else due_soon_max
            )
            if now >= due_at + escalate_after:
                event = EVENT_ESCALATION
            elif now >= due_at:
                event = EVENT_OVERDUE
            elif due_soon_window > timedelta(0) and now >= due_at - due_soon_window:
                event = EVENT_DUE_SOON
            else:
                event = None
            if event is None or (
                (event == EVENT_OVERDUE and inst.overdue_notified_at)
                or (event == EVENT_DUE_SOON and (inst.due_soon_notified_at or inst.overdue_notified_at))
            ):
                self.db.rollback()
                continue

            awaiting_approval = inst.status == "submitted"
            if event == EVENT_ESCALATION:
                roles = (
                    self._stage_roles(stage.id, approvers_only=True)
                    + self._override_roles(stage.workflow_definition_id)
                )
                severity = "critical"
            else:
                # A submitted stage is waiting on its approvers, not on the
                # assignee who submitted it.
                roles = self._stage_roles(stage.id, approvers_only=awaiting_approval)
                severity = "alert" if event == EVENT_OVERDUE else "info"
            assignee = inst.assigned_user
            notify_assignee = assignee and event != EVENT_ESCALATION and not awaiting_approval

            # Set the guards before sending: fire() commits, and that commit
            # must carry them so another worker never re-sends this level.
            if event == EVENT_ESCALATION:
                inst.escalation_notified_at = now
            if event in (EVENT_ESCALATION, EVENT_OVERDUE):
                inst.overdue_notified_at = inst.overdue_notified_at or now
            inst.due_soon_notified_at = inst.due_soon_notified_at or now
            self.db.flush()

            late_by = now - due_at
            workflow_label = (
                stage.workflow_definition.name if stage.workflow_definition
                else (workflow.workflow_code or "Workflow")
            )
            try:
                nsvc.fire(
                    event_type=event,
                    context={
                        "workflow_number": workflow.workflow_number or "",
                        "workflow_type":   workflow_label,
                        "equipment":       equipment.ueic or "",
                        "equipment_type":  getattr(equipment, "equipment_type_name", "") or "",
                        "department":      getattr(equipment, "department_name", "") or "",
                        "stage":           stage.name,
                        "deadline":        due_at.strftime("%Y-%m-%d %H:%M"),
                        "time_left":       _fmt_duration(due_at - now) if late_by.total_seconds() < 0 else "0 hour(s)",
                        "overdue_by":      _fmt_duration(late_by) if late_by.total_seconds() > 0 else "0 hour(s)",
                        "days_overdue":    str(max(0, late_by.days)),
                        "assignee":        _user_name(assignee),
                    },
                    organization_id=equipment.organization_id,
                    department_id=equipment.department_id,
                    source_id=workflow.id,
                    source_type="repair_workflow",
                    severity=severity,
                    workflow_type="repair_lifecycle",
                    extra_recipients=[assignee] if notify_assignee else None,
                    recipient_roles_override=roles or None,
                )
                self.db.commit()
            except Exception as e:
                self.db.rollback()
                logger.error(f"[StageDeadline] {event} failed for {workflow.workflow_number}: {e}", exc_info=True)
                continue
            sent[event] += 1

        return sent
