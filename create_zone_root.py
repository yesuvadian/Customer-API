#!/usr/bin/env python3
"""
Create a single "Zone" root department and make all current zones its children
"""

import uuid
from datetime import datetime
from sqlalchemy import text
from database import VendorSessionLocal


def create_zone_root():
    """Create Zone as ultimate root"""
    session = VendorSessionLocal()

    try:
        print("\n" + "=" * 80)
        print("  CREATE ZONE ROOT DEPARTMENT")
        print("=" * 80 + "\n")

        # Get KPTCL org
        org = session.execute(
            text("SELECT id FROM organizations WHERE code = 'KPTCL'")
        ).fetchone()

        if not org:
            print("[ERROR] KPTCL organization not found!")
            exit(1)

        org_id = str(org[0])

        # Check if "Zone" root already exists
        existing_zone = session.execute(
            text("SELECT id FROM org_departments WHERE organization_id = :org_id AND name = 'Zone' AND parent_department_id IS NULL"),
            {'org_id': org_id}
        ).fetchone()

        if existing_zone:
            zone_root_id = str(existing_zone[0])
            print(f"[INFO] Zone root already exists: {zone_root_id}")
        else:
            # Create Zone root
            zone_root_id = str(uuid.uuid4())
            session.execute(
                text("""
                    INSERT INTO org_departments (id, organization_id, name, code, parent_department_id, is_active, cts, mts)
                    VALUES (:id, :org_id, 'Zone', 'ZONE_ROOT', NULL, true, :cts, :mts)
                """),
                {
                    'id': zone_root_id,
                    'org_id': org_id,
                    'cts': datetime.now(),
                    'mts': datetime.now()
                }
            )
            print(f"[OK] Created Zone root department: {zone_root_id}")

        # Get all current root zones
        current_roots = session.execute(
            text("""
                SELECT id, name FROM org_departments
                WHERE organization_id = :org_id
                AND parent_department_id IS NULL
                AND name != 'Zone'
                ORDER BY name
            """),
            {'org_id': org_id}
        ).fetchall()

        print(f"\nFound {len(current_roots)} zones to update:\n")

        # Update each zone to have Zone as parent
        for zone_id, zone_name in current_roots:
            session.execute(
                text("""
                    UPDATE org_departments
                    SET parent_department_id = :parent_id, mts = :mts
                    WHERE id = :zone_id
                """),
                {
                    'parent_id': zone_root_id,
                    'zone_id': zone_id,
                    'mts': datetime.now()
                }
            )
            print(f"[OK] Updated {zone_name} - parent = Zone")

        session.commit()

        print("\n" + "=" * 80)
        print("  [SUCCESS] Zone hierarchy created")
        print("=" * 80 + "\n")

        print("New hierarchy structure:")
        print("  Zone (ROOT)")
        for _, zone_name in current_roots:
            print(f"    └── {zone_name}")

        print("\n" + "=" * 80 + "\n")

    except Exception as e:
        session.rollback()
        print(f"\n[ERROR] Failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


if __name__ == "__main__":
    create_zone_root()
