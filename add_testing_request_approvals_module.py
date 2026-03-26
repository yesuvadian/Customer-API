"""
Add "Testing Request Approvals" module and grant permissions to approval roles.
"""
import psycopg2
from datetime import datetime, timezone

def add_module_and_permissions():
    conn = psycopg2.connect(
        database='Relu_Vendor2',
        user='relu_user',
        password='StrongPassword123!',
        host='localhost',
        port=5432
    )

    cur = conn.cursor()

    try:
        now = datetime.now(timezone.utc)

        # 1. Check if module already exists
        cur.execute("SELECT id FROM modules WHERE name = 'Testing Request Approvals'")
        existing = cur.fetchone()

        if existing:
            print("[INFO] 'Testing Request Approvals' module already exists")
            module_id = existing[0]
        else:
            # Create the module (let database auto-generate ID)
            cur.execute("""
                INSERT INTO modules (
                    name, description, path, group_name, is_active, cts, mts
                ) VALUES (
                    %s, %s, %s, %s, true, %s, %s
                ) RETURNING id
            """, (
                'Testing Request Approvals',
                'Approve testing requests and assign testers',
                'testing_request_approvals',
                'Testing',
                now,
                now
            ))
            module_id = cur.fetchone()[0]
            print(f"[OK] Created 'Testing Request Approvals' module (ID: {module_id})")

        # 2. Grant permissions to KPTCL Department Head role
        cur.execute("""
            SELECT r.id, r.name
            FROM org_roles r
            JOIN organizations o ON r.organization_id = o.id
            WHERE o.code = 'KPTCL' AND r.name = 'Department Head'
        """)
        dept_head = cur.fetchone()

        if dept_head:
            role_id, role_name = dept_head

            # Check if permission already exists
            cur.execute("""
                SELECT id FROM org_role_permissions
                WHERE org_role_id = %s AND module_id = %s
            """, (role_id, module_id))

            if cur.fetchone():
                print(f"[INFO] Permission already exists for {role_name}")
            else:
                # Grant permission
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
                print(f"[OK] Granted permissions to KPTCL {role_name}")

        # 3. Grant permissions to KPTCL Organization Admin role
        cur.execute("""
            SELECT r.id, r.name
            FROM org_roles r
            JOIN organizations o ON r.organization_id = o.id
            WHERE o.code = 'KPTCL' AND r.is_org_admin = true
        """)
        org_admin = cur.fetchone()

        if org_admin:
            role_id, role_name = org_admin

            cur.execute("""
                SELECT id FROM org_role_permissions
                WHERE org_role_id = %s AND module_id = %s
            """, (role_id, module_id))

            if cur.fetchone():
                print(f"[INFO] Permission already exists for {role_name}")
            else:
                cur.execute("""
                    INSERT INTO org_role_permissions (
                        id, org_role_id, module_id,
                        can_view, can_add, can_edit, can_delete,
                        can_approve, can_assign, can_export, can_import,
                        cts, mts
                    ) VALUES (
                        gen_random_uuid(), %s, %s,
                        true, true, true, true,
                        true, true, true, true,
                        %s, %s
                    )
                """, (role_id, module_id, now, now))
                print(f"[OK] Granted full permissions to KPTCL {role_name}")

        # 4. Update global Approver role (if using approver@relu.com)
        cur.execute("SELECT id FROM roles WHERE name = 'Approver'")
        global_approver = cur.fetchone()

        if global_approver:
            role_id = global_approver[0]
            print(f"[INFO] Found global Approver role, but skipping (use org roles instead)")

        conn.commit()
        print()
        print("[SUCCESS] Module created and permissions granted!")
        print()
        print("Testing users:")
        print("  - depthead@kptcl.com / admin123 (can approve)")
        print("  - orgadmin@kptcl.com / admin123 (can approve)")
        print("  - engineer@kptcl.com / admin123 (can create requests)")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  Add Testing Request Approvals Module")
    print("=" * 60)
    print()

    add_module_and_permissions()
