"""
Grants 'Subscription & Billing' module access to all org admin roles.
Safe to run multiple times — skips roles that already have the permission.

Usage:
    python seed_billing_module_permissions.py
"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import uuid
from database import SessionLocal
from models import OrgRole, Module, OrgRolePermission

session = SessionLocal()
try:
    mod = session.query(Module).filter_by(name='Subscription & Billing').first()
    if not mod:
        print('[ERROR] Module "Subscription & Billing" not found. Run seed_modules_only.py first.')
        sys.exit(1)
    print(f'[OK] Module found: id={mod.id}')

    admin_roles = session.query(OrgRole).filter_by(is_org_admin=True, is_active=True).all()
    print(f'[OK] Found {len(admin_roles)} org admin role(s)')

    added = 0
    skipped = 0
    for role in admin_roles:
        existing = session.query(OrgRolePermission).filter_by(
            org_role_id=role.id, module_id=mod.id
        ).first()
        if existing:
            skipped += 1
            continue
        perm = OrgRolePermission(
            id=uuid.uuid4(),
            org_role_id=role.id,
            module_id=mod.id,
            can_view=True,
            can_add=True,
            can_edit=True,
            can_delete=True,
            can_approve=True,
            can_export=True,
            can_import=True,
        )
        session.add(perm)
        added += 1

    session.commit()
    print(f'[OK] Added: {added}  |  Already existed: {skipped}')
except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    session.close()
