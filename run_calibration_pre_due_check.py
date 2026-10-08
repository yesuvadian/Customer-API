"""
run_calibration_pre_due_check.py
─────────────────────────────────
Manual trigger for CalibrationService.run_pre_due_check() — the same job
main.py's APScheduler runs automatically every day at 08:00 UTC
(id="calibration_pre_due_check_job").

Use this to run the check on demand in dev (without waiting for 08:00 UTC)
or to re-run it manually in prod, against whichever DB the environment's
.env / DB_HOST etc. point to.

What it does
------------
For every equipment with is_scheduled=True whose calibration is due within
its configured lead_days window (and that doesn't already have an open
calibration request), auto-creates a new "TR-CAL-..." TestingRequest,
submits it, and enrolls it in the TR workflow engine — see
services/calibration_service.py's run_pre_due_check() for the full logic.

Safe to run more than once — equipment with an already-open calibration
request is skipped, so re-running does not create duplicates.

Usage
-----
    python3 run_calibration_pre_due_check.py
"""
import json

from database import get_vendor_session
from services.calibration_service import CalibrationService


def main() -> None:
    with get_vendor_session() as db:
        result = CalibrationService(db).run_pre_due_check()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
