#!/usr/bin/env python3
"""
One-time setup: give every Standard Test Workflow stage the 2-day default
duration.

The UI now adds the stage durations of the Standard Test Workflow up into a
new Test Request's default Due Date (TrWfProvider.standardTestWorkflowDays),
and pre-fills 2 days on any stage that has none. This brings the existing
stages in line:

  - stages with neither default_duration_days nor default_duration_hours
  - stages still on the 1-hour placeholder (hours = 1, no days)

are set to default_duration_days = 2, default_duration_hours = NULL (hours
takes precedence over days, so it has to be cleared for the 2 days to count).

Note: these durations are also each stage's SLA -- main.py's stage-overdue
job (and the Result Review SLA job for the review stage) will alert on them.

Only workflows named "Standard Test Workflow" are touched. Idempotent --
safe to re-run.

Usage:
    python backfill_standard_test_wf_stage_duration.py
"""
from database import VendorSessionLocal
from models import TrWfDefinition, TrWfStage

WORKFLOW_NAME = "Standard Test Workflow"
DEFAULT_DAYS = 2


def main():
    db = VendorSessionLocal()
    try:
        stages = (
            db.query(TrWfStage)
            .join(TrWfDefinition, TrWfStage.wf_definition_id == TrWfDefinition.id)
            .filter(TrWfDefinition.name == WORKFLOW_NAME)
            .order_by(TrWfDefinition.org_id, TrWfStage.sequence)
            .all()
        )
        changed = []
        for s in stages:
            unset = s.default_duration_days is None and s.default_duration_hours is None
            placeholder = s.default_duration_days is None and s.default_duration_hours == 1
            if not (unset or placeholder):
                continue
            before = f"days={s.default_duration_days} hours={s.default_duration_hours}"
            s.default_duration_days = DEFAULT_DAYS
            s.default_duration_hours = None
            changed.append((s, before))
        db.commit()
        print(f"Set default_duration_days={DEFAULT_DAYS} on {len(changed)} stage(s):")
        for s, before in changed:
            print(f"  workflow={s.wf_definition_id}  {s.sequence}. {s.name}  "
                  f"({before} -> days={DEFAULT_DAYS} hours=None)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
