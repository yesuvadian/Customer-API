"""
ALTER: database prerequisites for the equipment detail sheet's lifecycle
actions — Retire, Replace, Maintenance, Condemn, Decommission
(POST /equipment/{id}/retire, /replace and /status in routers/equipment.py).

equipment.status is a PostgreSQL enum ("equipmentstatus"). SQLAlchemy only
creates it with the values models.EquipmentStatus had when the table was
first created and never adds new ones, so an older dev/prod database can be
missing e.g. 'condemned' / 'decommissioned' / 'under_maintenance' — and the
action then fails with "invalid input value for enum equipmentstatus".
The retire/replace columns on equipment had no migration either.

This script only ever ADDS what is missing (enum values, columns); it never
changes or drops anything, so it is safe to run repeatedly.

The Retire/Replace notification events + templates need nothing here —
seed.seed_notification_defaults() adds them on every API startup.

Usage:
    python alter_equipment_lifecycle_actions.py --check   # report only
    python alter_equipment_lifecycle_actions.py           # apply
"""

from __future__ import annotations

import sys

from sqlalchemy import text

from database import vendor_engine
from models import EquipmentStatus

# (column, DDL) — types match models.Equipment exactly.
LIFECYCLE_COLUMNS = [
    ("retired_date", "TIMESTAMP WITH TIME ZONE"),
    ("retirement_reason", "TEXT"),
    ("replaced_by_id", "UUID REFERENCES public.equipment(id)"),
    ("replaces_equipment_id", "UUID REFERENCES public.equipment(id)"),
    ("replacement_reason_type", "VARCHAR(30)"),
    ("replacement_recommendation_id", "UUID"),
]


def main(check_only: bool) -> None:
    # ALTER TYPE ... ADD VALUE can't run inside a transaction block on older
    # PostgreSQL versions, so run everything in autocommit mode.
    with vendor_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        existing_labels = {
            r[0] for r in conn.execute(text(
                "SELECT e.enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'equipmentstatus'"
            ))
        }
        if not existing_labels:
            print("[ERROR] enum type 'equipmentstatus' not found — is this the right database?")
            sys.exit(1)

        existing_cols = {
            r[0] for r in conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'equipment'"
            ))
        }

        missing_labels = [s.value for s in EquipmentStatus if s.value not in existing_labels]
        missing_cols = [(c, ddl) for c, ddl in LIFECYCLE_COLUMNS if c not in existing_cols]

        print("=" * 70)
        print("  Equipment lifecycle actions — Retire / Replace / Maintenance /")
        print("  Condemn / Decommission")
        print("=" * 70)
        print(f"  equipmentstatus values missing : {missing_labels or 'none'}")
        print(f"  equipment columns missing      : {[c for c, _ in missing_cols] or 'none'}")

        if check_only:
            print("\n  --check: nothing changed.")
            return

        for label in missing_labels:
            conn.execute(text(f"ALTER TYPE equipmentstatus ADD VALUE IF NOT EXISTS '{label}'"))
            print(f"  [OK] enum value added: {label}")
        for col, ddl in missing_cols:
            conn.execute(text(f"ALTER TABLE public.equipment ADD COLUMN IF NOT EXISTS {col} {ddl}"))
            print(f"  [OK] column added: equipment.{col}")

        if not missing_labels and not missing_cols:
            print("\n  Already up to date — nothing to do.")
        else:
            print("\n  [SUCCESS] Done.")


if __name__ == "__main__":
    main(check_only="--check" in sys.argv)
