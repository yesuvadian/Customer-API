import uuid
from datetime import datetime

from database import VendorSessionLocal
from models import OrgRole, Module, OrgRolePermission


def main():
    session = VendorSessionLocal()

    try:
        role = (
            session.query(OrgRole)
            .filter(OrgRole.name == "System Administrator")
            .first()
        )

        if not role:
            raise Exception("System Administrator role not found")

        print(f"[INFO] Found role: {role.name}")
        print(f"[INFO] Role ID: {role.id}")

        # Ensure role is Org Admin
        role.is_org_admin = True
        role.is_active = True

        modules = session.query(Module).all()

        created = 0
        updated = 0

        for module in modules:

            perm = (
                session.query(OrgRolePermission)
                .filter(
                    OrgRolePermission.org_role_id == role.id,
                    OrgRolePermission.module_id == module.id,
                )
                .first()
            )

            if perm:
                perm.can_view = True
                perm.can_add = True
                perm.can_edit = True
                perm.can_delete = True
                perm.can_approve = True
                perm.can_assign = True

                if hasattr(perm, "can_export"):
                    perm.can_export = True

                if hasattr(perm, "can_import"):
                    perm.can_import = True

                perm.mts = datetime.now()

                updated += 1

            else:
                session.add(
                    OrgRolePermission(
                        id=uuid.uuid4(),
                        org_role_id=role.id,
                        module_id=module.id,
                        can_view=True,
                        can_add=True,
                        can_edit=True,
                        can_delete=True,
                        can_approve=True,
                        can_assign=True,
                        can_export=True,
                        can_import=True,
                        cts=datetime.now(),
                        mts=datetime.now(),
                    )
                )

                created += 1

        session.commit()

        print("=" * 70)
        print(f"Modules Found      : {len(modules)}")
        print(f"Permissions Created: {created}")
        print(f"Permissions Updated: {updated}")
        print(f"Role Admin Flag    : {role.is_org_admin}")
        print("=" * 70)

    except Exception as e:
        session.rollback()
        print(f"[ERROR] {e}")
        raise

    finally:
        session.close()


if __name__ == "__main__":
    main()