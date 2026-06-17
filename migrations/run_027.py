"""
Incremental data seed for Testing Kit feature.
Run once on the server after deploying this branch:
    python migrations/run_027.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from database import SessionLocal
from seed_testing_kit import (
    run as seed_kit_types,
    seed_kit_mappings,
    seed_kit_equipment_records,
    seed_module_and_privileges,
    update_tester_assigned_email_template,
)

if __name__ == "__main__":
    db = SessionLocal()
    try:
        print("=== Step 1: Kit types & subcategories ===")
        seed_kit_types(db)

        print("\n=== Step 2: Equipment-type → kit-type mappings ===")
        seed_kit_mappings(db)

        print("\n=== Step 3: Sample kit equipment records ===")
        seed_kit_equipment_records(db)

        print("\n=== Step 4: Module & role permissions ===")
        seed_module_and_privileges()

        print("\n=== Step 5: Tester notification email template ===")
        update_tester_assigned_email_template()

        print("\n[DONE] All data seeds applied.")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()
