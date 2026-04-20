"""
Add Testing Request Approval module permissions to all SRS designation roles
"""
from database import SessionLocal
from models import OrgRole, OrgRolePermission, Module
from datetime import datetime
import uuid

def add_approval_permissions():
    db = SessionLocal()

    try:
        # Get Testing Request Approvals module
        module = db.query(Module).filter(Module.name == 'Testing Request Approvals').first()

        if not module:
            print('ERROR: Testing Request Approvals module not found')
            return

        print(f'Module: {module.name} (ID: {module.id})\n')

        # Roles that should have approval permissions per SRS Section 2.3
        approval_roles = {
            'AEE Maintenance': {
                'view': True,
                'approve': True,  # Can approve at field level
                'assign': False
            },
            'EE TLSS': {
                'view': True,
                'approve': True,  # Primary reviewer and assigner
                'assign': True
            },
            'SEE W&M': {
                'view': True,
                'approve': True,  # Circle-level supervisor approval
                'assign': True
            },
            'EE RT': {
                'view': True,
                'approve': True,  # R&T division approvals
                'assign': True
            },
            'SEE RT': {
                'view': True,
                'approve': True,  # Senior R&T approvals
                'assign': False
            },
            'CEE Transmission Zone': {
                'view': True,
                'approve': True,  # Zone-level executive approval
                'assign': True
            },
            'CEE RT&R&D': {
                'view': True,
                'approve': True,  # R&D Chief approvals
                'assign': True
            },
        }

        added = 0
        skipped = 0

        for role_name, perms in approval_roles.items():
            role = db.query(OrgRole).filter(OrgRole.name == role_name).first()
            if not role:
                print(f'[SKIP] Role not found: {role_name}')
                continue

            # Check if permission already exists
            existing = db.query(OrgRolePermission).filter(
                OrgRolePermission.org_role_id == role.id,
                OrgRolePermission.module_id == module.id
            ).first()

            if existing:
                print(f'[OK] {role_name:30} Already has permissions')
                skipped += 1
            else:
                # Create new permission
                new_perm = OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=module.id,
                    can_view=perms['view'],
                    can_add=False,
                    can_edit=False,
                    can_delete=False,
                    can_approve=perms['approve'],
                    can_assign=perms['assign'],
                    can_export=False,
                    can_import=False,
                    cts=datetime.now(),
                    mts=datetime.now()
                )
                db.add(new_perm)
                print(f'[ADD] {role_name:30} view={perms["view"]}, approve={perms["approve"]}, assign={perms["assign"]}')
                added += 1

        db.commit()
        print(f'\nSummary: {added} permissions added, {skipped} already existed')
        print('All roles can now see and use the Testing Request Approvals module')

    except Exception as e:
        db.rollback()
        print(f'ERROR: {e}')
        raise
    finally:
        db.close()

if __name__ == '__main__':
    add_approval_permissions()
