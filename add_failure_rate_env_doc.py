#!/usr/bin/env python3
"""
One-time doc update: append the FAILURE_RATE_MIN_SERVICE_YEARS entry to
.env.example, documenting the config.py constant added alongside the
per-unit failure_rate_per_year field (services/equipment_service.py).

The constant itself needs no deployment action — it has a Python-level
default (os.getenv("FAILURE_RATE_MIN_SERVICE_YEARS", 0.5)) and works with
no .env changes at all. This script only keeps .env.example's documentation
in sync with config.py, matching every other FAILURE_COHORT_* /
DESIGN_PROBLEM_CANDIDATE_* entry already listed there.

Safe to re-run: it's a no-op if the line is already present.

Usage:
    python add_failure_rate_env_doc.py
"""
from pathlib import Path

ENV_EXAMPLE = Path(__file__).parent / ".env.example"

ANCHOR = "DESIGN_PROBLEM_CANDIDATE_MIN_FAILURE_RATE=1.0"
BLOCK = (
    "# Per-unit failure rate (failures/year since commissioning). Below this many\n"
    "# years in service, failure_rate_per_year is None instead of a rate computed\n"
    "# off a window too short to mean anything.\n"
    "FAILURE_RATE_MIN_SERVICE_YEARS=0.5"
)


def main() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    if "FAILURE_RATE_MIN_SERVICE_YEARS" in text:
        print("Already present — nothing to do.")
        return

    if ANCHOR not in text:
        raise SystemExit(
            f"Anchor line not found in {ENV_EXAMPLE.name}: {ANCHOR!r}. "
            "File layout may have changed — insert the block manually."
        )

    updated = text.replace(ANCHOR, f"{ANCHOR}\n{BLOCK}", 1)
    ENV_EXAMPLE.write_text(updated, encoding="utf-8")
    print(f"Added FAILURE_RATE_MIN_SERVICE_YEARS documentation to {ENV_EXAMPLE.name}")


if __name__ == "__main__":
    main()
