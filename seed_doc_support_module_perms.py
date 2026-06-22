"""
seed_doc_support_module_perms.py
=================================
Upserts document-support and document-support-queue permissions
for every relevant role. Touches NO other role or module.

Role              │ document-support          │ document-support-queue
──────────────────┼───────────────────────────┼───────────────────────
System Admin      │ FULL                      │ FULL
Dev Support Mgr   │ view + approve + assign   │ view + approve + assign
Dev Support       │ view + add + edit         │ view
"""

import sys, uuid
sys.path.insert(0, ".")

from database import VendorSessionLocal
from models import Module, OrgRole, OrgRolePermission, Organization

# (role_name, {module_path: {flag: bool, ...}})
ROLE_MODULE_PERMS = [
    (
        "System Administrator",
        {
            "analytics-dashboard":    dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "asset_dashboard":        dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "tr-wf/approval-queue":   dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "tr-wf/result-review":    dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "config/tr-workflow":     dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "config/tr-routing":      dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "test_register":          dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "/testing_kit_register":  dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "testing_schedules":      dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "maintenance_schedules":  dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "schedule_compliance":    dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "import-data":            dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "document-support":       dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
            "document-support-queue": dict(can_view=True, can_add=True, can_edit=True,
                                           can_delete=True, can_approve=True,
                                           can_assign=True, can_export=True, can_import=True),
        },
    ),
    (
        "Dev Support Manager",
        {
            "document-support":       dict(can_view=True, can_approve=True, can_assign=True),
            "document-support-queue": dict(can_view=True, can_approve=True, can_assign=True),
        },
    ),
    (
        "Dev Support",
        {
            "document-support":       dict(can_view=True, can_add=True, can_edit=True),
            "document-support-queue": dict(can_view=True),
        },
    ),
]

_ALL_FLAGS = [
    "can_view", "can_add", "can_edit", "can_delete",
    "can_approve", "can_assign", "can_export", "can_import",
]


def _upsert_perm(db, role_id, module_id, flags: dict):
    row = db.query(OrgRolePermission).filter_by(
        org_role_id=role_id, module_id=module_id
    ).first()
    full_flags = {f: flags.get(f, False) for f in _ALL_FLAGS}
    if row:
        for f, v in full_flags.items():
            setattr(row, f, v)
        return "UPDATE"
    else:
        db.add(OrgRolePermission(
            id=uuid.uuid4(),
            org_role_id=role_id,
            module_id=module_id,
            **full_flags,
        ))
        return "CREATE"


def run():
    db = VendorSessionLocal()
    try:
        org = (
            db.query(Organization).filter_by(code="KPTCL").first()
            or db.query(Organization).first()
        )
        if not org:
            raise RuntimeError("No organization found")

        # Pre-load module ids
        module_ids: dict[str, int] = {}
        all_paths = {p for _, pm in ROLE_MODULE_PERMS for p in pm}
        for path in all_paths:
            m = db.query(Module).filter_by(path=path).first()
            if m:
                module_ids[path] = m.id
            else:
                print(f"  [WARN] Module '{path}' not found — run seed_doc_support_roles_users first")

        if not module_ids:
            print("No modules found. Aborting.")
            return

        for role_name, path_perms in ROLE_MODULE_PERMS:
            role = db.query(OrgRole).filter_by(
                organization_id=org.id, name=role_name
            ).first()
            if not role:
                print(f"  [SKIP]  Role '{role_name}' not found")
                continue

            for path, flags in path_perms.items():
                mid = module_ids.get(path)
                if mid is None:
                    continue
                action = _upsert_perm(db, role.id, mid, flags)
                perms_on = [f.replace("can_", "") for f, v in flags.items() if v]
                print(f"  [{action}] {role_name} / {path} -> {', '.join(perms_on)}")

        db.commit()
        print("Done.")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
