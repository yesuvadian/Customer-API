"""
One-off script to add the Workflow Dashboard module without a full reseed.
Safe to run multiple times — skips if the module already exists.
"""
import uuid
from database import VendorSessionLocal
from models import Module, OrgRolePermission, OrgRole


def run():
    db = VendorSessionLocal()
    try:
        # 1. Insert module if not exists
        existing = db.query(Module).filter_by(path="workflow-dashboard").first()
        if existing:
            print(f"[INFO] Module already exists: {existing.id}")
            mod_id = existing.id
        else:
            mod = Module(
                id=uuid.uuid4(),
                name="Work Flow Dashboard",
                description=(
                    "Unified operations dashboard — dynamically shows counts, stage breakdown, "
                    "equipment at risk, and recent activity for all workflow types defined in "
                    "repair_workflow_definitions. New workflow types appear automatically."
                ),
                path="workflow-dashboard",
                group_name="Field Operations",
                is_active=True,
            )
            db.add(mod)
            db.flush()
            mod_id = mod.id
            print(f"[OK] Module created: {mod_id}")

        # 2. Grant can_view to all roles that have access to any workflow module
        workflow_role_names = [
            "Maintenance Officer",
            "Test Engineer",
            "Test & Work Coordinator",
            "Reviewing Officer",
            "Supervisory Officer",
            "Senior Management Approver",
            "Transformer Repair Coordinator",
            "Admin",
        ]

        roles = db.query(OrgRole).filter(OrgRole.name.in_(workflow_role_names)).all()
        granted = 0
        for role in roles:
            exists = db.query(OrgRolePermission).filter_by(
                org_role_id=role.id, module_id=mod_id
            ).first()
            if not exists:
                db.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mod_id,
                    can_view=True,
                    can_add=False,
                    can_edit=False,
                    can_delete=False,
                    can_approve=False,
                    can_assign=False,
                    can_export=False,
                    can_import=False,
                ))
                granted += 1
                print(f"[OK] Granted can_view → {role.name}")
            else:
                print(f"[INFO] Already granted → {role.name}")

        db.commit()
        print(f"\n[DONE] Workflow Dashboard module ready. Granted to {granted} role(s).")
    except Exception as e:
        db.rollback()
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    run()
