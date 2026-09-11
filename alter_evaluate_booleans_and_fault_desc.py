"""
ALTER: Refresh template_data for 7 already-live templates whose plain
boolean health-check fields were converted to evaluated Pass/Fail/N/A
dropdowns (so a failed check actually raises severity), plus a new
conditional "Fault Description" field (depends_on overall_result == Fail)
added to each.

Templates touched (all already active, already seeded — this is an UPDATE,
not an insert):
  - relay_testing_report               (Feeder protection relays)
  - stability_bias_test                (Transformer differential relay)
  - protection_relay_functional_test   (Protection Relay)
  - ct_ratio_test                      (Current Transformer)
  - transformer_protection_commissioning (Protection system)
  - physical_inspection                (Transformer)
  - buchholz_relay_functional_test     (Power Transformer)

19 boolean fields converted total (see test_templates.py for the full
list) — 4 unrelated "action taken" booleans (top_up_done,
gas_replacement_done, water_added, gas_sample_taken) were deliberately
left as plain booleans; they record whether an action was performed, not
a pass/fail health outcome.

Backward compatibility note: existing saved TestResult rows for these
templates that stored `true`/`false` for the converted keys won't match
the new Pass/Fail/N/A options - old results simply won't re-evaluate
retroactively. New submissions going forward use the new dropdown.

Safe to run multiple times (each run just re-syncs template_data to the
current TEST_TEMPLATES content).

Usage:
    python alter_evaluate_booleans_and_fault_desc.py
"""

from __future__ import annotations

from database import SessionLocal
from models import OrgTestTemplate
from test_templates import TEST_TEMPLATES

TEMPLATE_KEYS = [
    "relay_testing_report",
    "stability_bias_test",
    "protection_relay_functional_test",
    "ct_ratio_test",
    "transformer_protection_commissioning",
    "physical_inspection",
    "buchholz_relay_functional_test",
]


def run(db) -> None:
    updated = 0
    for key in TEMPLATE_KEYS:
        template_data = TEST_TEMPLATES.get(key)
        if not template_data:
            print(f"[WARN] {key!r} not found in TEST_TEMPLATES — skipping")
            continue

        row = db.query(OrgTestTemplate).filter(
            OrgTestTemplate.org_id.is_(None),
            OrgTestTemplate.template_key == key,
        ).first()
        if not row:
            print(f"[WARN] No live OrgTestTemplate row for {key!r} — nothing to refresh")
            continue

        row.template_data = template_data
        updated += 1
        print(f"[OK] {key!r} template_data refreshed")

    db.commit()
    print(f"\n[DONE] {updated} OrgTestTemplate rows refreshed.")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db)
    finally:
        db.close()
