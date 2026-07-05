"""
seed_doc_support_roles_users.py
================================
Creates the Document Support module, two new OrgRoles, their permissions,
and two demo users for KPTCL.

New roles:
  Dev Support Manager  — receives uploaded docs, assigns to a processor
  Dev Support          — processes the document, marks complete

New module:
  path: "document-support"  group: "Support"

Demo users (password: Kptcl@2026):
  ds.manager@utility.local   → Dev Support Manager
  ds.processor@utility.local → Dev Support

Idempotent — safe to run multiple times.
"""

import uuid
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from database import VendorSessionLocal
from models import (
    Module,
    OrgDepartment,
    OrgRole,
    OrgRolePermission,
    OrgUserRole,
    Organization,
    User,
)
from security_utils import get_password_hash

PASSWORD = "Kptcl@2026"

READ   = dict(can_view=True)
RW     = dict(can_view=True, can_add=True, can_edit=True)
ASSIGN = dict(can_view=True, can_assign=True)
FULL   = dict(can_view=True, can_add=True, can_edit=True, can_delete=True,
              can_approve=True, can_assign=True, can_export=True, can_import=True)
RW_APPROVE_ASSIGN = dict(can_view=True, can_add=True, can_edit=True,
                         can_approve=True, can_assign=True)


_VALID_COLS = {
    'can_view', 'can_add', 'can_edit', 'can_delete',
    'can_approve', 'can_assign', 'can_export', 'can_import',
}


def _apply_perms(session, role_id, module_map, perm_list):
    """Upsert permissions — never wipes unrelated modules."""
    for path, flags in perm_list:
        mid = module_map.get(path)
        if mid is None:
            print(f"  [WARN] Module '{path}' not found — skipping permission")
            continue
        base = {c: False for c in _VALID_COLS}
        base.update({k: v for k, v in flags.items() if k in _VALID_COLS})
        row = session.query(OrgRolePermission).filter_by(
            org_role_id=role_id, module_id=mid
        ).first()
        if row:
            for k, v in base.items():
                setattr(row, k, v)
        else:
            session.add(OrgRolePermission(
                id=uuid.uuid4(), org_role_id=role_id, module_id=mid, **base
            ))
    session.flush()


def _get_or_create_module(session, name, path, description, group_name):
    m = session.query(Module).filter_by(path=path).first()
    if not m:
        m = Module(
            name=name,
            path=path,
            description=description,
            group_name=group_name,
            is_active=True,
            is_menu=True,
        )
        session.add(m)
        session.flush()
        print(f"  [CREATE] Module: {path}")
    else:
        print(f"  [FOUND]  Module: {path} ({m.id})")
    return m


def _get_or_create_role(session, org_id, name, description, default_module_id, module_map, perms):
    role = session.query(OrgRole).filter_by(organization_id=org_id, name=name).first()
    if role:
        role.description = description
        role.default_module_id = default_module_id
        role.is_active = True
        role.mts = datetime.now()
        action = "UPDATE"
    else:
        role = OrgRole(
            id=uuid.uuid4(),
            organization_id=org_id,
            name=name,
            description=description,
            is_org_admin=False,
            is_dept_admin=False,
            is_active=True,
            default_module_id=default_module_id,
            cts=datetime.now(),
            mts=datetime.now(),
        )
        session.add(role)
        session.flush()
        action = "CREATE"
    _apply_perms(session, role.id, module_map, perms)
    print(f"  [{action}] Role: {name} ({len(perms)} permissions)")
    return role


def _get_or_create_user(session, email, firstname, lastname, phone,
                         org_id, dept_id, role_id, password_hash):
    user = session.query(User).filter_by(email=email).first()
    if user:
        user.organization_id = org_id
        user.department_id   = dept_id
        user.password_hash   = password_hash
        user.isactive        = True
        user.email_confirmed = True
        user.mts             = datetime.now()
        action = "UPDATED"
    else:
        user = User(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            firstname=firstname,
            lastname=lastname,
            phone_number=phone,
            organization_id=org_id,
            department_id=dept_id,
            isactive=True,
            email_confirmed=True,
            phone_confirmed=True,
            cts=datetime.now(),
            mts=datetime.now(),
        )
        session.add(user)
        session.flush()
        action = "CREATED"

    ur = session.query(OrgUserRole).filter_by(
        user_id=user.id, org_role_id=role_id
    ).first()
    if ur:
        ur.department_id = dept_id
        ur.is_active = True
    else:
        session.add(OrgUserRole(
            id=uuid.uuid4(),
            user_id=user.id,
            org_role_id=role_id,
            department_id=dept_id,
            is_active=True,
            assigned_at=datetime.now(),
        ))
    session.flush()
    print(f"  [{action}] {email}")
    return user


def seed_doc_support_roles_users(session=None):
    own_session = session is None
    if own_session:
        session = VendorSessionLocal()

    try:
        print("\n" + "=" * 70)
        print("  Doc Support — Seed Module, Roles & Users")
        print("=" * 70 + "\n")

        # ── Org ────────────────────────────────────────────────────────────
        org = session.query(Organization).filter_by(code="KPTCL").first()
        if not org:
            org = session.query(Organization).first()
        if not org:
            raise RuntimeError("No organization found — run base seed first.")
        print(f"[OK] Org: {org.name} ({org.id})\n")

        # ── Module map ─────────────────────────────────────────────────────
        all_modules = session.query(Module).all()
        module_map = {m.path: m.id for m in all_modules}

        # ── Create doc-support module ──────────────────────────────────────
        print("Modules:")
        ds_module    = _get_or_create_module(
            session,
            name="Document Support",
            path="document-support",
            description="Submit and process document support requests through a managed workflow.",
            group_name="Support",
        )
        ds_mgr_module = _get_or_create_module(
            session,
            name="Document Support Queue",
            path="document-support-queue",
            description="Manager and processor queue for Document Support Workflow.",
            group_name="Support",
        )
        # Refresh module_map with newly created modules
        module_map["document-support"] = ds_module.id
        module_map["document-support-queue"] = ds_mgr_module.id

        # ── Roles ──────────────────────────────────────────────────────────
        print("\nRoles:")
        mgr_role = _get_or_create_role(
            session, org.id,
            name="Dev Support Manager",
            description="Receives document support requests, reviews and assigns to a Dev Support team member.",
            default_module_id=ds_mgr_module.id,
            module_map=module_map,
            perms=[
                ("document-support",        RW_APPROVE_ASSIGN),
                ("document-support-queue",  RW_APPROVE_ASSIGN),
                ("notifications",           READ),
            ],
        )

        proc_role = _get_or_create_role(
            session, org.id,
            name="Dev Support",
            description="Processes document support requests assigned by the Dev Support Manager.",
            default_module_id=ds_mgr_module.id,
            module_map=module_map,
            perms=[
                ("document-support-queue",  RW_APPROVE_ASSIGN),
                ("notifications",           READ),
            ],
        )

        # ── Demo users ─────────────────────────────────────────────────────
        print("\nDemo users (password: Kptcl@2026):")
        password_hash = get_password_hash(PASSWORD)

        # Use BLR_CIRCLE dept if available
        all_depts = session.query(OrgDepartment).filter_by(
            organization_id=org.id, is_active=True
        ).all()
        dept_map = {d.code: d.id for d in all_depts}

        def _dept(code):
            if code in dept_map:
                return dept_map[code]
            for k, v in dept_map.items():
                if code in k:
                    return v
            return all_depts[0].id if all_depts else None

        _get_or_create_user(
            session,
            email="ds.manager@utility.local",
            firstname="Priya",
            lastname="Subramaniam",
            phone="9900001021",
            org_id=org.id,
            dept_id=_dept("BLR_CIRCLE"),
            role_id=mgr_role.id,
            password_hash=password_hash,
        )

        _get_or_create_user(
            session,
            email="ds.processor@utility.local",
            firstname="Arun",
            lastname="Krishnan",
            phone="9900001022",
            org_id=org.id,
            dept_id=_dept("BLR_CIRCLE"),
            role_id=proc_role.id,
            password_hash=password_hash,
        )

        # ── Grant org admin roles full access to doc support modules ──────────
        print("\nOrg admin permissions:")
        admin_roles = session.query(OrgRole).filter_by(
            organization_id=org.id, is_org_admin=True, is_active=True
        ).all()
        for ar in admin_roles:
            for mod in [ds_module, ds_mgr_module]:
                existing = session.query(OrgRolePermission).filter_by(
                    org_role_id=ar.id, module_id=mod.id
                ).first()
                if existing:
                    existing.can_view = existing.can_add = existing.can_edit = True
                    existing.can_delete = existing.can_approve = existing.can_assign = True
                else:
                    session.add(OrgRolePermission(
                        id=uuid.uuid4(),
                        org_role_id=ar.id,
                        module_id=mod.id,
                        can_view=True, can_add=True, can_edit=True,
                        can_delete=True, can_approve=True, can_assign=True,
                    ))
                print(f"  [GRANT] {ar.name} -> {mod.path}")
        session.flush()

        session.commit()

        print("\n" + "=" * 70)
        print("  [OK] DONE")
        print("=" * 70)
        print("\nDoc Support login credentials:")
        print(f"  ds.manager@utility.local    ->  Dev Support Manager  (pw: {PASSWORD})")
        print(f"  ds.processor@utility.local  ->  Dev Support          (pw: {PASSWORD})")
        print()

    finally:
        if own_session:
            session.close()


if __name__ == "__main__":
    seed_doc_support_roles_users()
