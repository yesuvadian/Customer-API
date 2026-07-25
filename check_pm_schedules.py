"""Quick check: verify PM Schedules module and permissions exist in DB."""
from database import VendorSessionLocal
from models import Module, OrgRolePermission, OrgRole, Organization

db = VendorSessionLocal()
try:
    # 1. Check module exists
    mod = db.query(Module).filter_by(path='pm_schedules').first()
    if not mod:
        print("[FAIL] PM Schedules module NOT found in DB — run seed_pm_schedules_module.py")
    else:
        print(f"[OK] Module: id={mod.id}, name='{mod.name}', path='{mod.path}', is_menu={mod.is_menu}, is_active={mod.is_active}")

        # 2. Check permissions
        perms = db.query(OrgRolePermission).filter_by(module_id=mod.id).all()
        print(f"\n[INFO] OrgRolePermission rows for this module: {len(perms)}")
        for p in perms:
            role = db.query(OrgRole).filter_by(id=p.org_role_id).first()
            org = db.query(Organization).filter_by(id=role.organization_id).first() if role else None
            print(f"  Role: '{role.name if role else '?'}' | Org: '{org.display_name if org else '?'}' | can_view={p.can_view}")

        if not perms:
            print("[FAIL] No OrgRolePermission rows found — permissions were not seeded.")
finally:
    db.close()
