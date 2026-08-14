#!/usr/bin/env python3
"""
One-time setup for the remedial_action_text feature on ParameterAnalytics.

Run this once per environment (dev/prod) after deploying the code from:
  - migrations/043_parameter_analytics_remedial_action.sql
  - models.py (ParameterAnalytics.remedial_action_text)
  - services/evaluation_service.py (per-cell remedial text + DGA row_results)
  - services/analytics_engine.py (persists remedial_action_text; wires
    _eval_threshold_table's row_results into ParameterAnalytics status,
    which DGA tables never got before this feature)
  - routers/analytics.py (exposes remedial_action_text in the API)
  - test_templates.py (adds per-gas DGA remedial guidance)

Does two things, both idempotent / safe to re-run:

1. DDL: ALTER TABLE parameter_analytics ADD COLUMN IF NOT EXISTS
   remedial_action_text TEXT.

2. Data: patches existing OrgTestTemplate rows for transformer_oil_test /
   transformer_dga to add the per-gas DGA remedial_action_text config -
   OrgTestTemplate rows are seeded once from test_templates.py and never
   auto-synced afterward (provision_global_defaults() skips rows that
   already exist), so editing test_templates.py alone does not reach an
   already-seeded row. Live evaluation reads the DB row, not the Python
   file (EvaluationService.get_template_data is DB-first).

Usage:
    python apply_remedial_action_text_feature.py --dry-run   # report only
    python apply_remedial_action_text_feature.py              # apply, then
                                                                # run
                                                                # run_recompute_all_analytics.py
"""
import argparse

from database import VendorSessionLocal
from models import OrgTestTemplate
from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified

_DDL = """
ALTER TABLE public.parameter_analytics
    ADD COLUMN IF NOT EXISTS remedial_action_text TEXT;
"""

_DGA_TEMPLATE_KEYS = ("transformer_oil_test", "transformer_dga")

_DGA_REMEDIAL_TEXT = {
    "Methane":         "Elevated methane indicates a low-temperature thermal fault - investigate for local overheating (e.g. bad connections, circulating currents).",
    "Ethane":          "Elevated ethane indicates a thermal fault - investigate oil/paper overheating; correlate with methane and ethylene trends.",
    "Ethylene":        "Elevated ethylene indicates a higher-temperature thermal fault - investigate hot spots, core faults, or circulating currents.",
    "Acetylene":       "Acetylene indicates arcing / high-energy electrical discharge - the most severe DGA finding; schedule urgent inspection for possible internal arcing.",
    "Hydrogen":        "Elevated hydrogen indicates partial discharge / corona activity - check for low-energy electrical discharge and elevated oil moisture.",
    "Carbon Dioxide":  "Elevated CO2 indicates thermal aging of cellulose (paper) insulation - review loading history and consider a follow-up DGA trend.",
    "Carbon Monoxide": "Elevated CO indicates overheating of solid (paper) insulation - review loading history and consider a follow-up DGA trend.",
    "TGC":             "Elevated total combustible gas indicates an overall active fault condition - schedule a follow-up DGA sample to confirm the trend and identify the dominant gas.",
}


def _apply_ddl(db, dry_run: bool):
    print(f"{'[DRY RUN] Would apply' if dry_run else 'Applying'} DDL: add parameter_analytics.remedial_action_text")
    if not dry_run:
        db.execute(text(_DDL))
        db.commit()


def _patch_dga_templates(db, dry_run: bool):
    changed = []
    for tkey in _DGA_TEMPLATE_KEYS:
        for row in db.query(OrgTestTemplate).filter(OrgTestTemplate.template_key == tkey).all():
            row_changed = False
            for section in row.template_data.get("sections", []):
                for field in section.get("fields", []):
                    if field.get("key") != "dga_results":
                        continue
                    for col in field.get("columns", []):
                        if col.get("type") != "calculated":
                            continue
                        cfg = col.get("rule", {}).get("config", {})
                        if "remedial_action_text" not in cfg:
                            cfg["remedial_action_text"] = dict(_DGA_REMEDIAL_TEXT)
                            row_changed = True
            if row_changed:
                changed.append((tkey, row.org_id))
                if not dry_run:
                    flag_modified(row, "template_data")

    print(f"{'[DRY RUN] ' if dry_run else ''}DGA template rows to patch: {len(changed)}")
    for tkey, org_id in changed:
        print(f"  {tkey} | org_id={org_id}")

    if not dry_run and changed:
        db.commit()


def run(dry_run: bool):
    db = VendorSessionLocal()
    try:
        _apply_ddl(db, dry_run)
        _patch_dga_templates(db, dry_run)
        if not dry_run:
            print("Done.")
            print("Now run: python run_recompute_all_analytics.py")
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(dry_run=args.dry_run)
