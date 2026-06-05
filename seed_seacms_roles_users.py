"""
seed_seacms_roles_users.py
==========================
SOURCE OF TRUTH for all KPTCL OrgRoles and demo users.
Creates 12 OrgRoles with per-module OrgRolePermissions, then one demo user per role.

Engineering designation roles:
  AE_JE                     → ae_dashboard
  AEE_MAINTENANCE            → aee_dashboard
  EE_TLSS                   → ee_tlss_dashboard
  SEE_WM                    → see_dashboard
  EE_RT                     → ee_rt_dashboard
  SEE_RT                    → see_rt_dashboard
  CEE_TRANSMISSION_ZONE     → cee_dashboard
  CEE_RT_RD                 → cee_rt_dashboard

Admin / system roles:
  System Administrator       → admin_dashboard

Operational / support roles:
  Asset Data Officer         → asset_dashboard
  Transformer Repair Coordinator → ee_tlss_dashboard
  TA&QC Inspector            → ee_tlss_dashboard
  Procurement Officer        → aee_dashboard

All demo users password: Kptcl@2026
"""

import uuid
from datetime import datetime
from database import VendorSessionLocal
from models import Organization, OrgRole, OrgRolePermission, OrgUserRole, User, OrgDepartment, Module
from security_utils import get_password_hash

# ─────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────

def _perm(role_id, module_id, **flags):
    """Build an OrgRolePermission dict."""
    base = dict(
        can_view=False, can_add=False, can_edit=False,
        can_delete=False, can_approve=False, can_assign=False,
        can_export=False, can_import=False, can_search=True,
    )
    base.update(flags)
    return dict(org_role_id=role_id, module_id=module_id, **base)

def _apply_perms(session, role_id, module_map, perm_list):
    """Upsert permission rows from a list of (module_path, **flags) tuples."""
    for path, flags in perm_list:
        mid = module_map.get(path)
        if mid is None:
            print(f"  [WARN] Module not found: {path} — skipping")
            continue
        existing = session.query(OrgRolePermission).filter_by(
            org_role_id=role_id, module_id=mid
        ).first()
        valid_cols = {'can_view','can_add','can_edit','can_delete',
                      'can_approve','can_assign','can_export','can_import'}
        if existing:
            for k, v in flags.items():
                if k in valid_cols:
                    setattr(existing, k, v)
        else:
            base = dict(
                can_view=False, can_add=False, can_edit=False,
                can_delete=False, can_approve=False, can_assign=False,
                can_export=False, can_import=False,
            )
            base.update({k: v for k, v in flags.items() if k in valid_cols})
            session.add(OrgRolePermission(
                id=uuid.uuid4(), org_role_id=role_id, module_id=mid, **base
            ))


# ─────────────────────────────────────────────────────────────
# permission shorthand sets
# ─────────────────────────────────────────────────────────────

READ        = dict(can_view=True)
V_A         = dict(can_view=True, can_add=True)
RW          = dict(can_view=True, can_add=True, can_edit=True)
RW_APPROVE  = dict(can_view=True, can_add=True, can_edit=True, can_approve=True)
READ_APPROVE= dict(can_view=True, can_approve=True)
APPROVE     = dict(can_view=True, can_approve=True)
ASSIGN      = dict(can_view=True, can_assign=True)
EXPORT      = dict(can_view=True, can_export=True)
FULL        = dict(can_view=True, can_add=True, can_edit=True, can_delete=True,
                   can_approve=True, can_assign=True, can_export=True, can_import=True)


# ─────────────────────────────────────────────────────────────
# role definitions
# ─────────────────────────────────────────────────────────────

ROLE_DEFS = [
    {
        "name":        "AE_JE",
        "description": "Assistant Engineer / Junior Engineer / Substation Operator — Field",
        "dashboard_path": "ae_dashboard",
        "permissions": [
            ("equipment",                  RW),
            ("testing_requests",           READ),
            ("testing",                    RW),
            ("repair-workflows",           RW),
            ("overhaul-workflows",         RW),
            ("notifications",              READ),
            ("ae_dashboard",               READ),
        ],
    },
    {
        "name":        "AEE_MAINTENANCE",
        "description": "Assistant Executive Engineer – Maintenance / Nodal Officer — Field Supervisor",
        "dashboard_path": "aee_dashboard",
        "permissions": [
            ("equipment",                  RW),
            ("failure_registry",           RW),
            ("testing_requests",           RW_APPROVE),
            ("testing",                    RW),
            ("recommendations",            READ_APPROVE),
            ("approvals",                  READ_APPROVE),
            ("testing_request_approvals",  READ_APPROVE),
            ("maintenance_schedules",      READ),
            ("schedule_compliance",        READ),
            ("repair-workflows",           RW_APPROVE),
            ("overhaul-workflows",         RW_APPROVE),
            ("calibration-workflows",      RW_APPROVE),
            ("surveillance-workflows",     RW_APPROVE),
            ("surveillance-dashboard",     EXPORT),
            ("taqc_inspections",           RW),
            ("annual_audits",              RW),
            ("annual-audit-workflows",     RW_APPROVE),
            ("notifications",              READ),
            ("reports",                    EXPORT),
            ("aee_dashboard",              READ),
            ("workflow-dashboard",         READ),
        ],
    },
    {
        "name":        "EE_TLSS",
        "description": "Executive Engineer – Transmission Line Sub-Station — Zone Officer",
        "dashboard_path": "ee_tlss_dashboard",
        "permissions": [
            ("equipment",                  RW),
            ("failure_registry",           RW),
            ("testing_requests",           RW_APPROVE),
            ("testing",                    RW),
            ("recommendations",            READ_APPROVE),
            ("approvals",                  READ_APPROVE),
            ("maintenance_schedules",      READ),
            ("schedule_compliance",        READ),
            ("repair-workflows",           RW_APPROVE),
            ("overhaul-workflows",         RW_APPROVE),
            ("calibration-workflows",      RW_APPROVE),
            ("surveillance-workflows",     RW_APPROVE),
            ("surveillance-dashboard",     EXPORT),
            ("taqc_inspections",           RW),
            ("annual_audits",              RW),
            ("annual-audit-workflows",     RW_APPROVE),
            ("notifications",              READ),
            ("reports",                    EXPORT),
            ("ee_tlss_dashboard",          READ),
            ("workflow-dashboard",         READ),
        ],
    },
    {
        "name":        "SEE_WM",
        "description": "Superintending Electrical Engineer – Works & Maintenance — Supervisory",
        "dashboard_path": "see_dashboard",
        "permissions": [
            # ASSETS
            ("equipment",                  READ),
            ("failure_registry",           READ),
            # CONDITION MONITORING
            ("testing_requests",           READ_APPROVE),
            ("testing",                    READ),
            ("testing_request_approvals",  READ_APPROVE),
            ("maintenance_schedules",      READ),
            # REPAIR & LIFECYCLE
            ("repair-workflows",           RW_APPROVE),
            ("overhaul-workflows",         RW_APPROVE),
            ("surveillance-workflows",     RW_APPROVE),
            ("surveillance-dashboard",     EXPORT),
            # TA&QC
            ("taqc_inspections",           RW),
            ("annual_audits",              RW),
            ("annual-audit-workflows",     RW_APPROVE),
            # TEST TEMPLATES
            ("test_templates",             READ),
            # OUTPUT
            ("notifications",              READ),
            ("reports",                    EXPORT),
            # DASHBOARDS
            ("see_dashboard",              READ),
            ("workflow-dashboard",         READ),
        ],
    },
    {
        "name":        "EE_RT",
        "description": "Executive Engineer – Relay & Testing — RT Wing",
        "dashboard_path": "ee_rt_dashboard",
        "permissions": [
            ("equipment",                  RW),
            ("testing",                    RW),
            ("test_register",              READ),
            ("calibration-workflows",      RW_APPROVE),
            ("ee_rt_dashboard",            READ),
            ("ee_tlss_dashboard",          READ),
            ("workflow-dashboard",         READ),
            ("notifications",              READ),
            ("reports",                    EXPORT),
        ],
    },
    {
        "name":        "SEE_RT",
        "description": "Superintending Electrical Engineer – Relay & Testing — RT Wing",
        "dashboard_path": "see_rt_dashboard",
        "permissions": [
            ("equipment",                  READ),
            ("testing",                    RW),
            ("test_register",              READ),
            ("calibration-workflows",      RW_APPROVE),
            ("see_rt_dashboard",           READ),
            ("see_dashboard",              READ),
            ("workflow-dashboard",         READ),
            ("notifications",              READ),
            ("reports",                    EXPORT),
        ],
    },
    {
        "name":        "CEE_TRANSMISSION_ZONE",
        "description": "Chief Electrical Engineer – Transmission Zone — Senior Management",
        "dashboard_path": "cee_dashboard",
        "permissions": [
            # ASSETS
            ("equipment",                  READ),
            ("failure_registry",           READ),
            # CONDITION MONITORING
            ("testing_requests",           READ_APPROVE),
            ("testing",                    READ),
            ("testing_request_approvals",  READ_APPROVE),
            # REPAIR & LIFECYCLE
            ("repair-workflows",           RW_APPROVE),
            ("overhaul-workflows",         RW_APPROVE),
            ("surveillance-workflows",     RW_APPROVE),
            ("surveillance-dashboard",     EXPORT),
            # TA&QC
            ("taqc_inspections",           RW_APPROVE),
            ("annual_audits",              RW),
            ("annual-audit-workflows",     RW_APPROVE),
            # DASHBOARDS
            ("cee_dashboard",              READ),
            ("workflow-dashboard",         READ),
            # OUTPUT
            ("notifications",              READ),
            ("reports",                    EXPORT),
        ],
    },
    {
        "name":        "CEE_RT_RD",
        "description": "Chief Electrical Engineer – RT & R&D — Senior Management",
        "dashboard_path": "cee_rt_dashboard",
        "permissions": [
            ("equipment",                  RW),
            ("testing",                    READ),
            ("test_register",              READ),
            ("calibration-workflows",      RW_APPROVE),
            ("testing_request_approvals",  READ_APPROVE),
            ("test_templates",             RW),
            ("cee_rt_dashboard",           READ),
            ("cee_dashboard",              READ),
            ("workflow-dashboard",         READ),
            ("notifications",              READ),
            ("reports",                    EXPORT),
        ],
    },

    # ── Admin / System Roles ──────────────────────────────────────────────────
    {
        "name":        "System Administrator",
        "description": "Manages organisation structure: users, roles and departments.",
        "dashboard_path": "admin_dashboard",
        "permissions": [
            ("organizations",              FULL),
            ("org_user_roles",             FULL),
            ("org_role_permissions",       FULL),
            ("notifications",              READ),
        ],
    },

    # ── Operational / Support Roles ───────────────────────────────────────────
    {
        "name":        "Asset Data Officer",
        "description": "Creates testing requests and raises procurement. Can start repair workflows.",
        "dashboard_path": "asset_dashboard",
        "permissions": [
            ("equipment",                  RW),
            ("testing_requests",           RW),
            ("failure_registry",           RW),
            ("taqc_inspections",           RW),
            ("precommission-requests",     RW),
            ("precommission-workflows",    READ),
            ("asset_dashboard",            READ),
            ("notifications",              READ),
        ],
    },
    {
        "name":        "Transformer Repair Coordinator",
        "description": "Assigns users to repair, overhaul, calibration and audit workflow stages.",
        "dashboard_path": "ee_tlss_dashboard",
        "permissions": [
            ("repair-workflows",           RW_APPROVE),
            ("overhaul-workflows",         RW_APPROVE),
            ("calibration-workflows",      RW_APPROVE),
            ("annual-audit-workflows",     RW_APPROVE),
            ("surveillance-workflows",     RW_APPROVE),
            ("precommission-workflows",    RW_APPROVE),
            ("precommission-requests",     READ),
            ("testing_requests",           READ),
            ("workflow-dashboard",         READ),
            ("ee_tlss_dashboard",          READ),
            ("notifications",              READ),
        ],
    },
    {
        "name":        "TA&QC Inspector",
        "description": "Technical Assurance & Quality Control Inspector. Performs annual substation inspections.",
        "dashboard_path": "ee_tlss_dashboard",
        "permissions": [
            ("taqc_inspections",           RW),
            ("annual-audit-workflows",     RW_APPROVE),
            ("failure_registry",           READ),
            ("ee_tlss_dashboard",          READ),
            ("notifications",              READ),
        ],
    },
    {
        "name":        "Procurement Officer",
        "description": "Manages procurement activities. Read-only access to repair workflows.",
        "dashboard_path": "aee_dashboard",
        "permissions": [
            ("repair-workflows",           READ),
            ("aee_dashboard",              READ),
            ("notifications",              READ),
        ],
    },
]


# ─────────────────────────────────────────────────────────────
# users — one per role, assigned to Bangalore Zone departments
# ─────────────────────────────────────────────────────────────

USER_DEFS = [
    # (email, firstname, lastname, phone, dept_code, role_name)
    ("ae.je@utility.local",           "Ravi",      "Kumar",         "9900001001", "BAN_NORTH_SECTION",  "AE_JE"),
    ("aee.maintenance@utility.local", "Suresh",    "Patil",         "9900001002", "BAN_NORTH_DIV",      "AEE_MAINTENANCE"),
    ("ee.tlss@utility.local",         "Nagaraj",   "Hegde",         "9900001003", "BAN",                "EE_TLSS"),
    ("see.wm@utility.local",          "Venkatesh", "Rao",           "9900001004", "BAN",                "SEE_WM"),
    ("ee.rt@utility.local",           "Mohan",     "Prasad",        "9900001005", "BAN_RT_DIV",         "EE_RT"),
    ("see.rt@utility.local",          "Anand",     "Krishnamurthy", "9900001006", "BAN",                "SEE_RT"),
    ("cee.transmission@utility.local","Rajesh",    "Srinivasan",    "9900001007", "BAN",                "CEE_TRANSMISSION_ZONE"),
    ("cee.rtrd@utility.local",        "Prakash",   "Murthy",        "9900001008", "BAN",                "CEE_RT_RD"),
    ("orgadmin@utility.com",           "Org",       "Admin",         "9900001000", "BAN",                "System Administrator"),
    ("asset.officer@utility.local",   "Kavitha",   "Nair",          "9900001009", "BAN",                "Asset Data Officer"),
    ("trc@utility.local",             "Sanjay",    "Reddy",         "9900001010", "BAN",                "Transformer Repair Coordinator"),
    ("taqc.inspector@utility.local",  "Deepa",     "Menon",         "9900001011", "BAN",                "TA&QC Inspector"),
    ("procurement@utility.local",     "Ramesh",    "Iyer",          "9900001012", "BAN",                "Procurement Officer"),
]


# ─────────────────────────────────────────────────────────────
# main
# ─────────────────────────────────────────────────────────────

def seed():
    session = VendorSessionLocal()
    try:
        print("\n" + "=" * 70)
        print("  SEACMS — Seed KPTCL OrgRoles + Users")
        print("=" * 70 + "\n")

        # ── Get KPTCL org ───────────────────────────────────────────────
        kptcl = session.query(Organization).filter_by(code="KPTCL").first()
        if not kptcl:
            raise RuntimeError("KPTCL organization not found — run seed_kptcl_users.py first")
        print(f"[OK] KPTCL org: {kptcl.id}")

        # ── Build module path → id map ──────────────────────────────────
        all_modules = session.query(Module).all()
        module_map = {m.path: m.id for m in all_modules}
        print(f"[OK] Loaded {len(module_map)} modules")

        # ── Get departments ─────────────────────────────────────────────
        all_depts = session.query(OrgDepartment).filter_by(
            organization_id=kptcl.id, is_active=True
        ).all()
        dept_map = {d.code: d.id for d in all_depts}
        # Also index by name fragment for fallback
        dept_name_map = {d.name: d.id for d in all_depts}

        def _dept(code):
            """Return dept id by code, fallback to Bangalore Zone."""
            if code in dept_map:
                return dept_map[code]
            # Try prefix match
            for k, v in dept_map.items():
                if code in k or k.startswith(code[:3]):
                    return v
            print("Department map:", dept_map)
            print("All departments:", len(all_depts))
            # Fallback: Bangalore Zone
            return dept_map.get("BAN") or all_depts[0].id

        # ── Create/update OrgRoles ──────────────────────────────────────
        org_role_ids = {}
        for rd in ROLE_DEFS:
            existing = session.query(OrgRole).filter_by(
                organization_id=kptcl.id, name=rd["name"]
            ).first()

            # Resolve default_module_id
            dmid = module_map.get(rd["dashboard_path"])

            if existing:
                existing.description = rd["description"]
                existing.default_module_id = dmid
                existing.mts = datetime.now()
                org_role_ids[rd["name"]] = existing.id
                print(f"  [UPDATE] OrgRole: {rd['name']}")
            else:
                nr = OrgRole(
                    id=uuid.uuid4(),
                    organization_id=kptcl.id,
                    name=rd["name"],
                    description=rd["description"],
                    is_org_admin=False,
                    is_dept_admin=(rd["name"] in ("AEE_MAINTENANCE", "EE_TLSS")),
                    is_active=True,
                    default_module_id=dmid,
                    cts=datetime.now(),
                    mts=datetime.now(),
                )
                session.add(nr)
                session.flush()
                org_role_ids[rd["name"]] = nr.id
                print(f"  [CREATE] OrgRole: {rd['name']}  (default_module={rd['dashboard_path']}  id={dmid})")

            # ── Permissions ────────────────────────────────────────────
            role_id = org_role_ids[rd["name"]]
            _apply_perms(session, role_id, module_map, rd["permissions"])

        session.flush()
        print(f"\n[OK] {len(ROLE_DEFS)} OrgRoles created/updated with permissions\n")

        # ── Create users ────────────────────────────────────────────────
        password_hash = get_password_hash("Kptcl@2026")
        print("Creating demo users (password: Kptcl@2026):")
        print(f"  {'Email':<35} {'Role':<25} {'Dept'}")
        print("  " + "-" * 70)

        for email, firstname, lastname, phone, dept_code, role_name in USER_DEFS:
            dept_id = _dept(dept_code)
            role_id = org_role_ids[role_name]

            # User
            user = session.query(User).filter_by(email=email).first()
            if user:
                user.organization_id = kptcl.id
                user.department_id   = dept_id
                user.mts = datetime.now()
                user_id = user.id
                action = "UPDATED"
            else:
                user = User(
                    id=uuid.uuid4(),
                    email=email,
                    password_hash=password_hash,
                    firstname=firstname,
                    lastname=lastname,
                    phone_number=phone,
                    organization_id=kptcl.id,
                    department_id=dept_id,
                    isactive=True,
                    email_confirmed=True,
                    phone_confirmed=True,
                    cts=datetime.now(),
                    mts=datetime.now(),
                )
                session.add(user)
                session.flush()
                user_id = user.id
                action = "CREATED"

            # OrgUserRole assignment
            existing_ur = session.query(OrgUserRole).filter_by(
                user_id=user_id, org_role_id=role_id
            ).first()
            if not existing_ur:
                session.add(OrgUserRole(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    org_role_id=role_id,
                    department_id=dept_id,
                    is_active=True,
                    assigned_at=datetime.now(),
                ))

            # Resolve dept name for display
            dept_name = next((d.name for d in all_depts if d.id == dept_id), dept_code)
            print(f"  [{action}] {email:<35} {role_name:<25} {dept_name}")

        session.commit()

        print("\n" + "=" * 70)
        print("  [OK] DONE — all roles, permissions and users seeded")
        print("=" * 70)
        print("\nLogin credentials for all demo users:")
        print(f"  Password : Kptcl@2026")
        print(f"  {'Email':<35} {'Role'}")
        print("  " + "-" * 60)
        for email, *_, role_name in USER_DEFS:
            print(f"  {email:<35} {role_name}")
        print()

    except Exception as e:
        session.rollback()
        import traceback
        traceback.print_exc()
        print(f"\n[ERROR] {e}")
    finally:
        session.close()


if __name__ == "__main__":
    seed()
