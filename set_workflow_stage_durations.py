#!/usr/bin/env python3
"""
Generic: set default_duration_hours (or _days) on every stage of a named
TrWfDefinition, across every organization that has one -- works for any
workflow name regardless of how many stages it has, since it always reads
the stage list live instead of hardcoding stage codes.

Edit STAGE_HOURS below: {stage_code: hours}. Any stage of the target
workflow whose code isn't listed falls back to DEFAULT_HOURS (set to None
to leave unlisted stages untouched instead of applying a fallback).

Setting an hours value clears that stage's default_duration_days (hours
takes precedence anyway per the app's own rule, but this keeps the two
fields from disagreeing in the DB). To configure a stage in DAYS instead,
put its code in STAGE_DAYS instead of STAGE_HOURS.

Usage:
    python set_workflow_stage_durations.py "Standard Test Workflow"
    python set_workflow_stage_durations.py "PM Workflow"
"""
import sys
from database import VendorSessionLocal
from models import TrWfDefinition, TrWfStage

# Per-stage-code duration in HOURS. Fill in real values before running.
STAGE_HOURS: dict[str, int] = {
    "l2_approve_route":  24,
    "l3_assign_tester":  24,
    "l4_test_execution": 168,   # 7 days for actual field testing
    "l3_review_result":  24,
}

# Per-stage-code duration in DAYS, for stages you'd rather express that way.
STAGE_DAYS: dict[str, int] = {
}

# Fallback applied to any stage of the target workflow not listed in
# either map above. None = leave those stages untouched.
DEFAULT_HOURS: int | None = None


def main():
    if len(sys.argv) < 2:
        print('Usage: python set_workflow_stage_durations.py "<Workflow Name>"')
        sys.exit(1)
    workflow_name = sys.argv[1]

    db = VendorSessionLocal()
    try:
        definitions = (
            db.query(TrWfDefinition)
            .filter(TrWfDefinition.name == workflow_name)
            .all()
        )
        if not definitions:
            print(f"No workflow definition named {workflow_name!r} found.")
            return

        updated, skipped = 0, 0
        for defn in definitions:
            stages = (
                db.query(TrWfStage)
                .filter(TrWfStage.wf_definition_id == defn.id)
                .order_by(TrWfStage.sequence)
                .all()
            )
            for stage in stages:
                if stage.code in STAGE_HOURS:
                    stage.default_duration_hours = STAGE_HOURS[stage.code]
                    stage.default_duration_days = None
                elif stage.code in STAGE_DAYS:
                    stage.default_duration_days = STAGE_DAYS[stage.code]
                    stage.default_duration_hours = None
                elif DEFAULT_HOURS is not None:
                    stage.default_duration_hours = DEFAULT_HOURS
                    stage.default_duration_days = None
                else:
                    skipped += 1
                    continue
                updated += 1
                print(
                    f"  org={defn.org_id} stage={stage.name!r} (code={stage.code!r}) "
                    f"-> hours={stage.default_duration_hours} days={stage.default_duration_days}"
                )
        db.commit()
        print(
            f"Updated {updated} stage(s), left {skipped} unconfigured "
            f"across {len(definitions)} definition(s) named {workflow_name!r}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
