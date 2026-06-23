"""
seed_seacms_roles_users.py
==========================
SOURCE OF TRUTH for all KPTCL OrgRoles and demo users.
Creates/updates 12 OrgRoles with per-module OrgRolePermissions, then one
demo user per role.

Permissions are ALWAYS re-applied on every run (existing roles are fully
re-synced, not skipped).  Old wrong permissions are deleted before the
correct set is written.

Engineering designation roles:
  AE_JE                     → ae_dashboard
  AEE_MAINTENANCE            → aee_dashboard
  EE_TLSS                   → ee_tlss_dashboard
  EE_RT                     → ee_rt_dashboard
  SEE_WM                    → see_dashboard
  SEE_RT                    → see_rt_dashboard
  CEE_TRANSMISSION_ZONE     → cee_dashboard
  CEE_RT_RD                 → cee_rt_dashboard

Admin / system roles:
  System Administrator       → admin_dashboard

Operational / support roles:
  Asset Data Officer         → asset_dashboard
  Test & Work Coordinator    → test_coordinator_dashboard
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

def _apply_perms(session, role_id, module_map, perm_list):
    """
    Upsert permissions — only touches modules listed in perm_list.
    Never deletes permissions for modules not managed by this seed.
    """
    valid_cols = {
        'can_view', 'can_add', 'can_edit', 'can_delete',
        'can_approve', 'can_assign', 'can_export', 'can_import',
    }
    for path, flags in perm_list:
        mid = module_map.get(path)
        if mid is None:
            print(f"  [WARN] Module not found: {path} — skipping")
            continue
        base = dict(
            can_view=False, can_add=False, can_edit=False,
            can_delete=False, can_approve=False, can_assign=False,
            can_export=False, can_import=False,
        )
        base.update({k: v for k, v in flags.items() if k in valid_cols})
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


# ─────────────────────────────────────────────────────────────
# permission shorthand sets
# ─────────────────────────────────────────────────────────────

READ             = dict(can_view=True)
RW               = dict(can_view=True, can_add=True, can_edit=True)
RW_APPROVE       = dict(can_view=True, can_add=True, can_edit=True, can_approve=True)
RW_APPROVE_ASSIGN= dict(can_view=True, can_add=True, can_edit=True, can_approve=True, can_assign=True)
READ_APPROVE     = dict(can_view=True, can_approve=True)
APPROVE          = dict(can_view=True, can_approve=True)
ASSIGN           = dict(can_view=True, can_assign=True)
EXPORT           = dict(can_view=True, can_export=True)
FULL             = dict(
    can_view=True, can_add=True, can_edit=True, can_delete=True,
    can_approve=True, can_assign=True, can_export=True, can_import=True,
)


# ─────────────────────────────────────────────────────────────
# role definitions  — SOURCE OF TRUTH, aligned with
# SEACMS_AI_Role_Privileges.md (last updated 2026-06-04)
# ─────────────────────────────────────────────────────────────

ROLE_DEFS = [
    # ── AE_JE ────────────────────────────────────────────────────────────────
    # Field entry only. No approval authority. No repair / lifecycle workflows.
    # Raises and enters cumulative ops (CB/OLTC) at substation level.
    {
        "name":        "AE_JE",
        "description": "Assistant Engineer / Junior Engineer / Substation Operator — Field",
        "dashboard_path": "ae_dashboard",
        "permissions": [
            # ASSETS
            ("equipment",               RW),
            # CONDITION MONITORING
            ("testing_requests",        READ),
            ("testing",                 RW),
            # LIFECYCLE
            ("overhaul-workflows",      RW),         # cumulative ops → overhaul trigger
            # OUTPUT
            ("notifications",           READ),
            # DASHBOARDS
            ("ae_dashboard",            READ),
        ],
    },

    # ── AEE_MAINTENANCE ──────────────────────────────────────────────────────
    # First approval gate for test requests, cumulative ops, workflows, audits.
    # Dept admin; annual audit queue assignment authority.
    # No RT track (calibration / calibration-workflows).
    {
        "name":        "AEE_MAINTENANCE",
        "description": "Assistant Executive Engineer – Maintenance / Nodal Officer — Field Supervisor",
        "dashboard_path": "aee_dashboard",
        "permissions": [
            # ASSETS
            ("equipment",                  RW),
            ("failure_registry",           RW),
            # CONDITION MONITORING
            ("testing_requests",           RW_APPROVE),
            ("testing",                    RW),
            ("recommendations",            READ_APPROVE),
            ("approvals",                  READ_APPROVE),
            ("testing_request_approvals",  READ_APPROVE),
            # MAINTENANCE
            ("maintenance_schedules",      READ),
            ("schedule_compliance",        READ),
            # REPAIR & LIFECYCLE
            ("repair-workflows",           RW_APPROVE_ASSIGN),
            ("overhaul-workflows",         RW_APPROVE),         # cumulative → overhaul trigger
            ("surveillance-workflows",     RW_APPROVE),
            ("surveillance-dashboard",     EXPORT),
            # TA&QC
            ("taqc_inspections",           RW),
            ("annual_audits",              RW),
            ("annual-audit-workflows",     RW_APPROVE),
            # PRE-COMMISSION
            ("precommission-requests",     RW_APPROVE),
            ("precommission-workflows",    RW_APPROVE),
            # OUTPUT
            ("notifications",              READ),
            ("reports",                    EXPORT),
            # DASHBOARDS
            ("aee_dashboard",              READ),
            ("workflow-dashboard",         READ),
        ],
    },

    # ── EE_TLSS ──────────────────────────────────────────────────────────────
    # Same approval rights as AEE but at broader division/zone scope.
    # Cumulative ops: approve-only (AE/AEE territory for add/edit).
    # No RT track (calibration / calibration-workflows).
    # Dept admin; annual audit queue assignment authority.
    {
        "name":        "EE_TLSS",
        "description": "Executive Engineer – Transmission Line Sub-Station — Zone Officer",
        "dashboard_path": "ee_tlss_dashboard",
        "permissions": [
            # ASSETS
            ("equipment",                  RW),
            ("failure_registry",           RW),
            # CONDITION MONITORING
            ("testing_requests",           RW_APPROVE),
            ("testing",                    RW),
            ("recommendations",            READ_APPROVE),
            ("approvals",                  READ_APPROVE),
            ("testing_request_approvals",  READ_APPROVE),
            # MAINTENANCE
            ("maintenance_schedules",      READ),
            ("schedule_compliance",        READ),
            # REPAIR & LIFECYCLE
            ("repair-workflows",           RW_APPROVE_ASSIGN),
            ("overhaul-workflows",         RW_APPROVE),         # cumulative → overhaul trigger
            ("surveillance-workflows",     RW_APPROVE),
            ("surveillance-dashboard",     EXPORT),
            # TA&QC
            ("taqc_inspections",           RW),
            ("annual_audits",              RW),
            ("annual-audit-workflows",     RW_APPROVE),
            # PRE-COMMISSION
            ("precommission-requests",     RW_APPROVE),
            ("precommission-workflows",    RW_APPROVE),
            # OUTPUT
            ("notifications",              READ),
            ("reports",                    EXPORT),
            # DASHBOARDS
            ("ee_tlss_dashboard",          READ),
            ("workflow-dashboard",         READ),
        ],
    },

    # ── EE_RT ────────────────────────────────────────────────────────────────
    # Parallel RT track. Calibration & calibration workflows only.
    # Read access to EE TLSS dashboard for cross-track visibility.
    # No O&M modules.
    {
        "name":        "EE_RT",
        "description": "Executive Engineer – Relay & Testing — RT Wing",
        "dashboard_path": "ee_rt_dashboard",
        "permissions": [
            # ASSETS
            ("equipment",               RW),
            # CONDITION MONITORING
            ("testing",                 RW),
            ("test_register",           READ),
            # RELAY TESTING (RT TRACK)
            ("calibration-workflows",   RW_APPROVE),
            # OUTPUT
            ("notifications",           READ),
            ("reports",                 EXPORT),
            # DASHBOARDS
            ("ee_rt_dashboard",         READ),
            ("ee_tlss_dashboard",       READ),   # cross-track visibility
            ("workflow-dashboard",      READ),
        ],
    },

    # ── SEE_WM ───────────────────────────────────────────────────────────────
    # Circle-level oversight. Mostly read/approve; no field add/edit.
    # Test Templates: read only.  No RT track.
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
            # PRE-COMMISSION
            ("precommission-requests",     APPROVE),
            ("precommission-workflows",    READ),
            # CONFIGURATION
            ("test_templates",             READ),
            # OUTPUT
            ("notifications",              READ),
            ("reports",                    EXPORT),
            # DASHBOARDS
            ("see_dashboard",              READ),
            ("workflow-dashboard",         READ),
        ],
    },

    # ── SEE_RT ───────────────────────────────────────────────────────────────
    # RT circle supervisor. Calibration approval authority at circle level.
    # No O&M module access.
    {
        "name":        "SEE_RT",
        "description": "Superintending Electrical Engineer – Relay & Testing — RT Wing",
        "dashboard_path": "see_rt_dashboard",
        "permissions": [
            # ASSETS
            ("equipment",               READ),
            # CONDITION MONITORING
            ("testing",                 RW),
            ("test_register",           READ),
            # RELAY TESTING (RT TRACK)
            ("calibration-workflows",   RW_APPROVE),
            # OUTPUT
            ("notifications",           READ),
            ("reports",                 EXPORT),
            # DASHBOARDS
            ("see_rt_dashboard",        READ),
            ("see_dashboard",           READ),    # cross-track visibility
            ("workflow-dashboard",      READ),
        ],
    },

    # ── CEE_TRANSMISSION_ZONE ────────────────────────────────────────────────
    # Highest O&M authority. Zone-wide read/approve on testing and failure registry.
    # TA&QC Inspections: RW+Approve (only role with full approve authority).
    # No RT track.
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
            ("taqc_inspections",           RW_APPROVE),  # only role with approve on TA&QC
            ("annual_audits",              RW),
            ("annual-audit-workflows",     RW_APPROVE),
            # PRE-COMMISSION
            ("precommission-requests",     APPROVE),
            ("precommission-workflows",    APPROVE),
            # OUTPUT
            ("notifications",              READ),
            ("reports",                    EXPORT),
            # DASHBOARDS
            ("cee_dashboard",              READ),
            ("workflow-dashboard",         READ),
        ],
    },

    # ── CEE_RT_RD ────────────────────────────────────────────────────────────
    # Highest RT authority. Owns test template management (RW).
    # Zone-wide calibration approval. No O&M approval authority.
    {
        "name":        "CEE_RT_RD",
        "description": "Chief Electrical Engineer – RT & R&D — Senior Management",
        "dashboard_path": "cee_rt_dashboard",
        "permissions": [
            # ASSETS
            ("equipment",                  RW),
            # CONDITION MONITORING
            ("testing",                    READ),
            ("test_register",              READ),
            ("testing_request_approvals",  READ_APPROVE),
            # RELAY TESTING (RT TRACK)
            ("calibration-workflows",      RW_APPROVE),
            # CONFIGURATION
            ("test_templates",             RW),   # only role that can create/edit templates
            # OUTPUT
            ("notifications",              READ),
            ("reports",                    EXPORT),
            # DASHBOARDS
            ("cee_rt_dashboard",           READ),
            ("cee_dashboard",              READ),   # cross-track visibility
            ("workflow-dashboard",         READ),
        ],
    },

    # ── Test & Work Coordinator ──────────────────────────────────────────────
    {
        "name":        "Test & Work Coordinator",
        "description": "Approves testing requests, assigns testers, and coordinates field maintenance work.",
        "dashboard_path": "test_coordinator_dashboard",
        "permissions": [
            ("equipment",                  READ),
            ("testing_requests",           RW_APPROVE),
            ("testing_request_approvals",  RW_APPROVE),
            ("repair-workflows",           RW_APPROVE_ASSIGN),
            ("overhaul-workflows",         RW_APPROVE),
            ("calibration-workflows",      RW_APPROVE),
            ("annual-audit-workflows",     RW_APPROVE),
            ("surveillance-workflows",     RW_APPROVE),
            ("precommission-workflows",    RW_APPROVE),
            ("workflow-dashboard",         READ),
            ("test_coordinator_dashboard", READ),
            ("notifications",              READ),
        ],
    },

    # ── System Administrator ─────────────────────────────────────────────────
    {
        "name":        "System Administrator",
        "description": "Manages organisation structure: users, roles and departments.",
        "dashboard_path": "admin_dashboard",
        "permissions": [
            ("organizations",              FULL),
            ("org_user_roles",             FULL),
            ("org_role_permissions",       FULL),
            ("equipment",                  FULL),
            ("testing_requests",           FULL),
            ("testing",                    FULL),
            ("test_register",              FULL),
            ("/testing_kit_register",      FULL),
            ("testing_schedules",          FULL),
            ("maintenance_schedules",      FULL),
            ("schedule_compliance",        FULL),
            ("recommendations",            FULL),
            ("analytics-dashboard",        FULL),
            ("asset_dashboard",            FULL),
            ("approvals",                  FULL),
            ("testing_request_approvals",  FULL),
            ("tr-wf/approval-queue",       FULL),
            ("tr-wf/result-review",        FULL),
            ("config/tr-workflow",         FULL),
            ("config/tr-routing",          FULL),
            ("repair-workflows",           FULL),
            ("overhaul-workflows",         FULL),
            ("calibration-workflows",      FULL),
            ("surveillance-workflows",     FULL),
            ("surveillance-dashboard",     FULL),
            ("annual-audit-workflows",     FULL),
            ("precommission-requests",     FULL),
            ("precommission-workflows",    FULL),
            ("failure_registry",           FULL),
            ("taqc_inspections",           FULL),
            ("annual_audits",              FULL),
            ("test_templates",             FULL),
            ("reports",                    FULL),
            ("notifications",              FULL),
            ("org_notification_center",    FULL),
            ("org_reporting_center",       FULL),
            ("workflow-dashboard",         FULL),
            ("import-data",                FULL),
            ("document-support",           FULL),
            ("document-support-queue",     FULL),
            ("admin_dashboard",            READ),
        ],
    },

    # ── Asset Data Officer ───────────────────────────────────────────────────
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

    # ── Transformer Repair Coordinator ───────────────────────────────────────
    {
        "name":        "Transformer Repair Coordinator",
        "description": "Assigns users to repair, overhaul, calibration and audit workflow stages.",
        "dashboard_path": "ee_tlss_dashboard",
        "permissions": [
            ("repair-workflows",           RW_APPROVE_ASSIGN),
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

    # ── TA&QC Inspector ──────────────────────────────────────────────────────
    {
        "name":        "TA&QC Inspector",
        "description": "Technical Assurance & Quality Control Inspector. Performs annual substation inspections.",
        "dashboard_path": "ee_tlss_dashboard",
        "permissions": [
            ("taqc_inspections",           RW),
            ("annual-audit-workflows",     RW_APPROVE),
            ("surveillance-workflows",     READ),
            ("surveillance-dashboard",     READ),
            ("failure_registry",           READ),
            ("ee_tlss_dashboard",          READ),
            ("notifications",              READ),
        ],
    },

    # ── Procurement Officer ──────────────────────────────────────────────────
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
    ("ae.je@utility.local",            "Ravi",      "Kumar",         "9900001001", "RT_NORTH",    "AE_JE"),
    ("aee.maintenance@utility.local",  "Suresh",    "Patil",         "9900001002", "RT_NORTH",    "AEE_MAINTENANCE"),
    ("ee.tlss@utility.local",          "Nagaraj",   "Hegde",         "9900001003", "BLR_CIRCLE",  "EE_TLSS"),
    ("see.wm@utility.local",           "Venkatesh", "Rao",           "9900001004", "BLR_CIRCLE",  "SEE_WM"),
    ("ee.rt@utility.local",            "Mohan",     "Prasad",        "9900001005", "RT_EAST",     "EE_RT"),
    ("see.rt@utility.local",           "Anand",     "Krishnamurthy", "9900001006", "BLR_CIRCLE",  "SEE_RT"),
    ("cee.transmission@utility.local", "Rajesh",    "Srinivasan",    "9900001007", "BLR_CIRCLE",  "CEE_TRANSMISSION_ZONE"),
    ("cee.rtrd@utility.local",         "Prakash",   "Murthy",        "9900001008", "BLR_CIRCLE",  "CEE_RT_RD"),
    ("orgadmin@utility.com",           "Org",       "Admin",         "9900001000", None,          "System Administrator"),
    ("asset.officer@utility.local",    "Kavitha",   "Nair",          "9900001009", "BLR_CIRCLE",  "Asset Data Officer"),
    ("trc@utility.local",              "Sanjay",    "Reddy",         "9900001010", "BLR_CIRCLE",  "Transformer Repair Coordinator"),
    ("taqc.inspector@utility.local",   "Deepa",     "Menon",         "9900001011", "BLR_CIRCLE",  "TA&QC Inspector"),
    ("procurement@utility.local",      "Ramesh",    "Iyer",          "9900001012", "BLR_CIRCLE",  "Procurement Officer"),
    ("tw.coordinator@utility.local",   "Kiran",     "Sharma",        "9900001013", "BLR_CIRCLE",  "Test & Work Coordinator"),
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
        dept_name_map = {d.name: d.id for d in all_depts}

        if not all_depts:
            print("[WARN] No departments found for KPTCL — run seed_kptcl_departments first.")
            print("[WARN] OrgRoles will be created but users will have no department assignment.")

        def _dept(code):
            if code is None:
                return None
            if code in dept_map:
                return dept_map[code]
            for k, v in dept_map.items():
                if code in k or k.startswith(code[:3]):
                    return v
            for name, did in dept_name_map.items():
                if code.upper() in name.upper():
                    return did
            return all_depts[0].id if all_depts else None

        # ── Create/update OrgRoles and ALWAYS re-apply permissions ──────
        org_role_ids = {}
        for rd in ROLE_DEFS:
            is_org_admin  = (rd["name"] == "System Administrator")
            is_dept_admin = rd["name"] in ("AEE_MAINTENANCE", "EE_TLSS")
            dmid = module_map.get(rd["dashboard_path"])

            existing = session.query(OrgRole).filter_by(
                organization_id=kptcl.id, name=rd["name"]
            ).first()

            if existing:
                existing.description      = rd["description"]
                existing.default_module_id = dmid
                existing.is_org_admin     = is_org_admin
                existing.is_dept_admin    = is_dept_admin
                existing.is_active        = True
                existing.mts              = datetime.now()
                role_id = existing.id
                action  = "UPDATE"
            else:
                nr = OrgRole(
                    id=uuid.uuid4(),
                    organization_id=kptcl.id,
                    name=rd["name"],
                    description=rd["description"],
                    is_org_admin=is_org_admin,
                    is_dept_admin=is_dept_admin,
                    is_active=True,
                    default_module_id=dmid,
                    cts=datetime.now(),
                    mts=datetime.now(),
                )
                session.add(nr)
                session.flush()
                role_id = nr.id
                action  = "CREATE"

            org_role_ids[rd["name"]] = role_id

            # Always re-apply permissions (deletes stale rows first)
            _apply_perms(session, role_id, module_map, rd["permissions"])
            session.flush()

            print(f"  [{action}] {rd['name']:<35} "
                  f"({len(rd['permissions'])} permissions applied)")

        print(f"\n[OK] {len(ROLE_DEFS)} OrgRoles created/updated with permissions\n")

        # ── Create/update demo users ────────────────────────────────────
        password_hash = get_password_hash("Kptcl@2026")
        print("Creating/updating demo users (password: Kptcl@2026):")
        print(f"  {'Email':<38} {'Role':<32} {'Dept'}")
        print("  " + "-" * 80)

        for email, firstname, lastname, phone, dept_code, role_name in USER_DEFS:
            dept_id = _dept(dept_code)
            role_id = org_role_ids[role_name]

            user = session.query(User).filter_by(email=email).first()
            if user:
                user.organization_id = kptcl.id
                user.department_id   = dept_id
                user.password_hash   = password_hash
                user.isactive        = True
                user.email_confirmed = True
                user.mts             = datetime.now()
                user_id = user.id
                action  = "UPDATED"
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
                action  = "CREATED"

            # OrgUserRole assignment — always sync department_id so re-seed
            # correctly resets org admin to root (None) if previously set to a zone.
            existing_ur = session.query(OrgUserRole).filter_by(
                user_id=user_id, org_role_id=role_id
            ).first()
            if existing_ur:
                existing_ur.department_id = dept_id
                existing_ur.is_active     = True
            else:
                session.add(OrgUserRole(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    org_role_id=role_id,
                    department_id=dept_id,
                    is_active=True,
                    assigned_at=datetime.now(),
                ))

            dept_name = next((d.name for d in all_depts if d.id == dept_id), dept_code)
            print(f"  [{action}] {email:<38} {role_name:<32} {dept_name}")

        session.commit()

        print("\n" + "=" * 70)
        print("  [OK] DONE — all roles, permissions and users seeded")
        print("=" * 70)
        print("\nLogin credentials for all demo users:")
        print(f"  Password : Kptcl@2026")
        print(f"  {'Email':<38} {'Role'}")
        print("  " + "-" * 70)
        for email, *_, role_name in USER_DEFS:
            print(f"  {email:<38} {role_name}")
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
