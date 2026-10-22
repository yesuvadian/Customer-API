#!/usr/bin/env python3
"""
One-time fix: exempt nameplate / inspection templates from the
no-threshold CRITICAL rule.

The template sync tags every TEST_TYPE_TO_TEMPLATE entry template_type
"test", and the CategoryDetails rows "Power Transformer Nameplate Details"
and "Transformer Physical Inspection" are typed "test" - so a submitted
nameplate or inspection form was evaluated CRITICAL "no_threshold_values"
and turned its equipment Critical. test_templates.py now gives these
templates a non-test category_type, which EvaluationService.requires_thresholds
(and the app's RuleEngine.requiresThresholds) treats as exempt. This script
copies that category_type into the stored global and org template rows.

Results already evaluated CRITICAL "no_threshold_values" for these templates
are listed; re-run the analytics for them (POST /test-results/{id}/run or
run_recompute_all_analytics.py) to re-evaluate.

Re-running this script is safe: rows already carrying the value are skipped.

Usage:
    python alter_exempt_nameplate_inspection_templates.py
"""
from sqlalchemy import text
from database import VendorSessionLocal

CATEGORY_TYPES = {
    "power_transformer_nameplate":     "nameplate",
    "transformer_physical_inspection": "inspection",
    "transformer_inspection":          "inspection",
}


def main():
    db = VendorSessionLocal()
    try:
        for key, ctype in CATEGORY_TYPES.items():
            n = db.execute(text(
                "UPDATE public.org_test_templates "
                "SET template_data = jsonb_set(template_data::jsonb, '{category_type}', to_jsonb(CAST(:ctype AS text))) "
                "WHERE template_key = :key "
                "AND coalesce(template_data->>'category_type', '') <> :ctype"
            ), {"key": key, "ctype": ctype}).rowcount
            print(f"{key}: category_type={ctype} on {n} template row(s)")

        stale = db.execute(text(
            "SELECT id, template_key FROM public.test_results "
            "WHERE template_key = ANY(:keys) "
            "AND evaluation_result->>'unassessed_reason' IS NOT NULL"
        ), {"keys": list(CATEGORY_TYPES)}).fetchall()
        db.commit()
        print(f"{len(stale)} stored result(s) need re-evaluation"
              + "".join(f"\n  {r.id} ({r.template_key})" for r in stale))
    finally:
        db.close()


if __name__ == "__main__":
    main()
