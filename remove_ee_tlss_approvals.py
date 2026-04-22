"""
Remove Testing Request Approvals module permissions for EE TLSS role
"""
from database import SessionLocal
from models import OrgRole, OrgRolePermission, Module, Organization

db = SessionLocal()

try:
    print("=" * 80)
    print("REMOVING TESTING REQUEST APPROVALS FOR EE TLSS")
    print("=" * 80)

    # Get KPTCL org
    kptcl = db.query(Organization).filter(Organization.name.like('%Karnataka%')).first()

    if not kptcl:
        print("[ERROR] KPTCL organization not found")
        exit(1)

    print(f"[OK] Found organization: {kptcl.name}")

    # Get Testing Request Approvals module
    module = db.query(Module).filter(Module.name == 'Testing Request Approvals').first()

    if not module:
        print("[ERROR] Testing Request Approvals module not found")
        exit(1)

    print(f"[OK] Found module: {module.name} (id: {module.id})")

    # Get EE TLSS role
    ee_tlss_role = db.query(OrgRole).filter(
        OrgRole.organization_id == kptcl.id,
        OrgRole.name == 'EE TLSS',
        OrgRole.is_active == True
    ).first()

    if not ee_tlss_role:
        print("[ERROR] EE TLSS role not found")
        exit(1)

    print(f"[OK] Found role: {ee_tlss_role.name} (id: {ee_tlss_role.id})")

    # Find and delete the permission
    perm = db.query(OrgRolePermission).filter(
        OrgRolePermission.org_role_id == ee_tlss_role.id,
        OrgRolePermission.module_id == module.id
    ).first()

    if perm:
        print(f"\n[INFO] Current permissions:")
        print(f"  can_view: {perm.can_view}")
        print(f"  can_approve: {perm.can_approve}")
        print(f"  can_assign: {perm.can_assign}")

        db.delete(perm)
        db.commit()
        print(f"\n[OK] Removed Testing Request Approvals permissions for EE TLSS")
    else:
        print(f"\n[INFO] EE TLSS role already has no permissions for Testing Request Approvals")

    print("\n" + "=" * 80)
    print("SUCCESS: EE TLSS no longer has access to Testing Request Approvals module")
    print("=" * 80)

except Exception as e:
    print(f"\nERROR: {e}")
    db.rollback()
    raise
finally:
    db.close()

if __name__ == "__main__":
    pass
