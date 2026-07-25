"""
Grants 'Subscription & Billing' module to ALL active org roles in the KPTCL org.
Safe to run multiple times.

Usage:
    python grant_billing_module_kptcl.py
"""
import sys
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

import uuid
from database import SessionLocal
from models import Organization, OrgRole, OrgRolePermission, Module

session = SessionLocal()
try:
    # Find the module
    mod = session.query(Module).filter_by(name='Subscription & Billing').first()
    if not mod:
        print('[ERROR] Module not found. Run seed_modules_only.py first.')
        sys.exit(1)
    print(f'[OK] Module id={mod.id}')

    # Find KPTCL org
    org = session.query(Organization).filter(
        Organization.name.ilike('%karnataka%power%')
    ).first()
    if not org:
        # fallback: list all orgs
        orgs = session.query(Organization).filter_by(is_active=True).all()
        print('Available orgs:')
        for o in orgs:
            print(f'  {o.id}  {o.name}')
        sys.exit(1)
    print(f'[OK] Org: {org.name}  id={org.id}')

    # Get ALL active org roles for this org
    roles = session.query(OrgRole).filter_by(
        organization_id=org.id, is_active=True
    ).all()
    print(f'[OK] Found {len(roles)} org role(s):')
    for r in roles:
        print(f'     - {r.name}  (is_org_admin={r.is_org_admin})')

    added = 0
    skipped = 0
    for role in roles:
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
    print(f'\n[OK] Added: {added}  |  Already existed: {skipped}')
    print('[OK] Logout and log back in to see the module.')

except Exception as e:
    import traceback
    traceback.print_exc()
    sys.exit(1)
finally:
    session.close()
