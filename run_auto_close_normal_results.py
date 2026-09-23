"""
run_auto_close_normal_results.py
──────────────────────────────────
Manual trigger + diagnostic for main.py's _check_auto_close_normal_results
job (KPTCL spec D.8 "Auto-close NORMAL results after review period") — the
same job APScheduler runs automatically every 30 minutes
(id="auto_close_normal_results_job").

Use this to:
  - force the auto-close sweep to run right now instead of waiting up to
    30 minutes, in dev or prod
  - see WHY a specific ticket isn't auto-closing, when --request-number is
    given: it reports which of the auto-close gates that ticket's current
    review stage instance is failing (not a result stage, no
    auto_close_normal_after_hours configured, deadline not yet reached,
    a result isn't NORMAL, or the transition config is ambiguous)

Usage
-----
    python3 run_auto_close_normal_results.py
    python3 run_auto_close_normal_results.py --request-number TR-KP-2026-1065
"""
import argparse
from datetime import datetime, timezone, timedelta

from database import get_vendor_session
from models import (
    TestingRequest,
    TrWfInstance,
    TrWfStage,
    TrWfStageInstance,
    TrWfStageTransition,
    TestResult,
)


def _aware_started_at(started_at):
    if started_at.tzinfo is None:
        # Same fix-up as main.py's job: this naive column actually holds
        # Asia/Calcutta wall-clock time (UTC+5:30), not naive UTC.
        started_at = started_at.replace(
            tzinfo=timezone(timedelta(hours=5, minutes=30))
        ).astimezone(timezone.utc)
    return started_at


def diagnose(db, request_number: str) -> None:
    tr = (
        db.query(TestingRequest)
        .filter(TestingRequest.request_number == request_number)
        .first()
    )
    if not tr:
        print(f"No TestingRequest found with request_number={request_number!r}")
        return

    wf_instance = (
        db.query(TrWfInstance)
        .filter(TrWfInstance.testing_request_id == tr.id)
        .first()
    )
    if not wf_instance:
        print(f"{request_number}: no TrWfInstance (not enrolled in the workflow engine)")
        return

    si = (
        db.query(TrWfStageInstance)
        .filter(
            TrWfStageInstance.wf_instance_id == wf_instance.id,
            TrWfStageInstance.status == "in_progress",
        )
        .order_by(TrWfStageInstance.created_at.desc())
        .first()
    )
    if not si:
        print(f"{request_number}: no in_progress stage instance right now")
        return

    stage = si.stage
    print(f"{request_number}: current stage = {stage.code!r} (stage_id={stage.id})")

    if not stage.is_result_stage:
        print("  -> BLOCKED: this stage is not a result-review stage (is_result_stage=False)")
        return

    if stage.auto_close_normal_after_hours is None:
        print("  -> BLOCKED: auto_close_normal_after_hours is not configured for this stage")
        print("     (set it via the workflow stage admin config to enable auto-close here)")
        return

    if si.started_at is None:
        print("  -> BLOCKED: stage instance has no started_at yet")
        return

    started_at = _aware_started_at(si.started_at)
    deadline = started_at + timedelta(hours=stage.auto_close_normal_after_hours)
    now = datetime.now(timezone.utc)
    print(f"  started_at (UTC) = {started_at.isoformat()}")
    print(f"  auto_close_normal_after_hours = {stage.auto_close_normal_after_hours}")
    print(f"  deadline (UTC)   = {deadline.isoformat()}")
    print(f"  now (UTC)        = {now.isoformat()}")
    if now <= deadline:
        print(f"  -> BLOCKED: deadline not yet reached ({deadline - now} remaining)")
        return

    results = db.query(TestResult).filter(TestResult.testing_request_id == tr.id).all()
    if not results:
        print("  -> BLOCKED: no TestResult rows for this request")
        return

    bad = [
        (r.id, (r.evaluation_result or {}).get("overall"))
        for r in results
        if (r.evaluation_result or {}).get("overall") != "NORMAL"
    ]
    if bad:
        print("  -> BLOCKED: not every result is NORMAL:")
        for rid, overall in bad:
            print(f"       TestResult {rid}: evaluation_result.overall = {overall!r}")
        return

    positive_transitions = (
        db.query(TrWfStageTransition)
        .filter(
            TrWfStageTransition.from_stage_id == stage.id,
            TrWfStageTransition.is_rejection.is_(False),
            TrWfStageTransition.requires_comment.is_(False),
            TrWfStageTransition.action_code != "cancel",
        )
        .all()
    )
    if len(positive_transitions) != 1:
        print(
            f"  -> BLOCKED: expected exactly 1 candidate auto-close transition "
            f"for this stage, found {len(positive_transitions)}"
        )
        return

    print("  -> All gates pass: this ticket IS a valid auto-close candidate.")
    print("     Run without --request-number (or wait for the 30-min job) to close it.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--request-number",
        help="Diagnose why this specific ticket isn't auto-closing, without changing anything",
    )
    args = parser.parse_args()

    with get_vendor_session() as db:
        if args.request_number:
            diagnose(db, args.request_number)
            return

        # Re-run the same sweep main.py's scheduled job runs, importing it
        # directly so behavior can never drift from the real cron job.
        import main as _main
        _main.BackgroundSessionLocal = lambda: db  # reuse this script's session
        _main._check_auto_close_normal_results()
        print("Auto-close sweep run — see log output above for how many were closed.")


if __name__ == "__main__":
    main()
