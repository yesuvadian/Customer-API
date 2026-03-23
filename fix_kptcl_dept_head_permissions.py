"""
Fix KPTCL Department Head role to have Testing module permissions including Approvals.
"""
import psycopg2
from datetime import datetime, timezone

def fix_dept_head_permissions():
    conn = psycopg2.connect(
        database='Relu_Vendor2',
        user='relu_user',
        password='StrongPassword123!',
        host='localhost',
        port=5432
    )

    cur = conn.cursor()

    try:
        # Get KPTCL org
        cur.execute("SELECT id FROM organizations WHERE code = 'KPTCL'")
        org_id = cur.fetchone()[0]
        print(f"[INFO] Found KPTCL organization: {org_id}")

        # Get Department Head role
        cur.execute("""
            SELECT id, name FROM org_roles
            WHERE organization_id = %s AND name = 'Department Head'
        """, (org_id,))
        role_result = cur.fetchone()

        if not role_result:
            print("[ERROR] Department Head role not found!")
            return

        role_id, role_name = role_result
        print(f"[INFO] Found role: {role_name} ({role_id})")

        # Get Testing modules
        cur.execute("""
            SELECT id, name FROM modules
            WHERE group_name = 'Testing' AND is_active = true
        """)
        testing_modules = cur.fetchall()

        print(f"[INFO] Found {len(testing_modules)} Testing modules")

        # Add permissions for each Testing module
        now = datetime.now(timezone.utc)
        added_count = 0

        for module_id, module_name in testing_modules:
            # Check if permission already exists
            cur.execute("""
                SELECT id FROM org_role_permissions
                WHERE org_role_id = %s AND module_id = %s
            """, (role_id, module_id))

            if cur.fetchone():
                print(f"  [SKIP] {module_name} - permission already exists")
                continue

            # Insert permission
            cur.execute("""
                INSERT INTO org_role_permissions (
                    id, org_role_id, module_id,
                    can_view, can_add, can_edit, can_delete,
                    can_approve, can_assign, can_export, can_import,
                    cts, mts
                ) VALUES (
                    gen_random_uuid(), %s, %s,
                    true, true, true, false,
                    true, true, true, false,
                    %s, %s
                )
            """, (role_id, module_id, now, now))

            added_count += 1
            print(f"  [ADD] {module_name} - full permissions granted")

        # Add Testing Request Approvals module (the new one for testing request approval workflow)
        cur.execute("SELECT id, name FROM modules WHERE name = 'Testing Request Approvals' AND is_active = true")
        testing_approval = cur.fetchone()
        if testing_approval:
            module_id, module_name = testing_approval
            cur.execute("""
                SELECT id FROM org_role_permissions
                WHERE org_role_id = %s AND module_id = %s
            """, (role_id, module_id))

            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO org_role_permissions (
                        id, org_role_id, module_id,
                        can_view, can_add, can_edit, can_delete,
                        can_approve, can_assign, can_export, can_import,
                        cts, mts
                    ) VALUES (
                        gen_random_uuid(), %s, %s,
                        true, false, false, false,
                        true, true, false, false,
                        %s, %s
                    )
                """, (role_id, module_id, now, now))
                added_count += 1
                print(f"  [ADD] {module_name} - approval permissions granted")

        # Also add Dashboard module
        cur.execute("SELECT id, name FROM modules WHERE name = 'Dashboard' AND is_active = true")
        dashboard = cur.fetchone()
        if dashboard:
            module_id, module_name = dashboard
            cur.execute("""
                SELECT id FROM org_role_permissions
                WHERE org_role_id = %s AND module_id = %s
            """, (role_id, module_id))

            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO org_role_permissions (
                        id, org_role_id, module_id,
                        can_view, can_add, can_edit, can_delete,
                        can_approve, can_assign, can_export, can_import,
                        cts, mts
                    ) VALUES (
                        gen_random_uuid(), %s, %s,
                        true, false, false, false,
                        false, false, false, false,
                        %s, %s
                    )
                """, (role_id, module_id, now, now))
                added_count += 1
                print(f"  [ADD] {module_name} - view permission granted")

        conn.commit()
        print()
        print(f"[OK] Added {added_count} module permissions to {role_name}")
        print()
        print("You can now login as: depthead@kptcl.com / admin123")
        print("They will have access to Testing modules including Approvals")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  Fix KPTCL Department Head Permissions")
    print("=" * 60)
    print()

    fix_dept_head_permissions()
