"""
Seed the Configurable Test-Request Workflow Engine (tr_wf_*) for KPTCL.

Call order (from seed.py):
  1. run_migration_from_file(..., "migrations/029_tr_wf_engine.sql", ...)
     — must run first so all tr_wf_* tables exist.
  2. seed_tr_wf_workflow(session)
     — must run after seed_seacms_roles_users so EE_TLSS OrgRole exists.

Workflow graph seeded (Normal / Standard path):
  [L2 Approval & Route]  --approve-->  [L3 Tester Assignment]
  [L3 Tester Assignment] --assign-->   [L4 Test Execution]
  [L4 Test Execution]    --complete--> [L3 Result Review]
  [L4 Test Execution]    --return-->   [L3 Tester Assignment]   (send-back)
  [L3 Result Review]     --approve-->  TERMINAL: wf_completed   (triggers WorkflowDispatchService)
  [L3 Result Review]     --reject-->   [L4 Test Execution]      (rework)

Failure and Special definitions are seeded with no stages so admins can
configure them independently through the TR Workflow Config UI.

All functions are idempotent (get-or-create on every row).
"""

import uuid

from models import (
    Module,
    Organization,
    OrgRole,
    OrgRolePermission,
    TrWfDefinition,
    TrWfRoutingDefault,
    TrWfRoutingRule,
    TrWfStage,
    TrWfStageRole,
    TrWfStageTransition,
    TrWfStatus,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_org(session):
    """Return the KPTCL org (or the first org as fallback)."""
    for keyword in ["%kptcl%", "%karnataka%", "%transmission%"]:
        org = session.query(Organization).filter(
            Organization.name.ilike(keyword)
        ).first()
        if org:
            return org
    return session.query(Organization).first()


def _resolve_module_ids(session):
    """Return {module_name: module_id} for the 4 tr_wf modules."""
    names = [
        "TR Approval Queue",
        "TR Result Review",
        "TR Workflow Config",
        "TR Routing Config",
        "Testing",
    ]
    return {
        m.name: m.id
        for m in session.query(Module).filter(Module.name.in_(names)).all()
    }


def _get_or_create_role(session, org_id, name, description, is_tester_assignable=False):
    r = session.query(OrgRole).filter_by(
        organization_id=org_id, name=name
    ).first()
    if not r:
        r = OrgRole(
            id=uuid.uuid4(),
            organization_id=org_id,
            name=name,
            description=description,
            role_type="custom",
            is_org_admin=False,
            is_dept_admin=False,
            is_tester_assignable=is_tester_assignable,
            is_active=True,
        )
        session.add(r)
        session.flush()
        print(f"  [NEW] OrgRole: {name}")
    return r


def _grant_module(session, role, mod_map, mod_name,
                  can_view=True, can_add=False, can_edit=False,
                  can_delete=False, can_approve=False, can_assign=False):
    mod_id = mod_map.get(mod_name)
    if not mod_id:
        return
    exists = session.query(OrgRolePermission).filter_by(
        org_role_id=role.id, module_id=mod_id
    ).first()
    if not exists:
        session.add(OrgRolePermission(
            id=uuid.uuid4(),
            org_role_id=role.id,
            module_id=mod_id,
            can_view=can_view,
            can_add=can_add,
            can_edit=can_edit,
            can_delete=can_delete,
            can_approve=can_approve,
            can_assign=can_assign,
        ))


def _get_or_create_definition(session, org_id, name, request_type, is_default=False):
    d = session.query(TrWfDefinition).filter_by(
        org_id=org_id, name=name
    ).first()
    if not d:
        d = TrWfDefinition(
            id=uuid.uuid4(),
            org_id=org_id,
            name=name,
            request_type=request_type,
            is_default=is_default,
            is_active=True,
        )
        session.add(d)
        session.flush()
        print(f"  [NEW] TrWfDefinition: {name}")
    return d


def _get_or_create_status(session, wf, code, name, seq, color,
                           approval=False, assignment=False, terminal=False):
    s = session.query(TrWfStatus).filter_by(
        wf_definition_id=wf.id, status_code=code
    ).first()
    if not s:
        s = TrWfStatus(
            id=uuid.uuid4(),
            wf_definition_id=wf.id,
            status_code=code,
            status_name=name,
            sequence=seq,
            color=color,
            approval_required=approval,
            assignment_required=assignment,
            is_terminal=terminal,
            is_active=True,
        )
        session.add(s)
        session.flush()
    return s


def _get_or_create_stage(session, wf, status, name, code, seq):
    s = session.query(TrWfStage).filter_by(
        wf_definition_id=wf.id, code=code
    ).first()
    if not s:
        s = TrWfStage(
            id=uuid.uuid4(),
            wf_definition_id=wf.id,
            status_id=status.id,
            name=name,
            code=code,
            sequence=seq,
            weight=10,
            is_mandatory=True,
            is_active=True,
        )
        session.add(s)
        session.flush()
        print(f"  [NEW] TrWfStage: {code}")
    return s


def _get_or_create_stage_role(session, stage, role,
                               can_approve=False, can_assign=False, can_edit=False):
    if not role:
        return
    exists = session.query(TrWfStageRole).filter_by(
        stage_id=stage.id, role_id=role.id
    ).first()
    if not exists:
        session.add(TrWfStageRole(
            id=uuid.uuid4(),
            stage_id=stage.id,
            role_id=role.id,
            can_approve=can_approve,
            can_assign=can_assign,
            can_edit=can_edit,
        ))


def _get_or_create_transition(session, from_stage, to_stage, action_code,
                               requires_comment=False, is_rejection=False,
                               terminal_status=None, post_action=None):
    exists = session.query(TrWfStageTransition).filter_by(
        from_stage_id=from_stage.id, action_code=action_code
    ).first()
    if exists:
        if post_action is not None and exists.post_action != post_action:
            exists.post_action = post_action
    else:
        session.add(TrWfStageTransition(
            id=uuid.uuid4(),
            from_stage_id=from_stage.id,
            to_stage_id=to_stage.id if to_stage else None,
            action_code=action_code,
            requires_comment=requires_comment,
            is_rejection=is_rejection,
            terminal_status_id=terminal_status.id if terminal_status else None,
            post_action=post_action,
        ))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def seed_tr_wf_workflow(session):
    """
    Idempotently seed the TR Configurable Workflow Engine.

    Must be called after:
      • run_migration_from_file(029_tr_wf_engine.sql)  — tables must exist
      • seed_seacms_roles_users()                      — EE_TLSS role must exist
      • seed_modules()                                 — TR module rows must exist
    """
    print("\n--- TR Configurable Workflow Engine Seeding ---")

    org = _resolve_org(session)
    if not org:
        print("  [WARN] No organization found — skipping tr_wf seed")
        return

    mod_map = _resolve_module_ids(session)

    # ── Resolve existing roles (created by seed_seacms_roles_users) ─────────
    role_ee_tlss = session.query(OrgRole).filter_by(
        organization_id=org.id, name="EE_TLSS"
    ).first()
    role_aee_maint = session.query(OrgRole).filter_by(
        organization_id=org.id, name="AEE_MAINTENANCE"
    ).first()
    role_ae_je = session.query(OrgRole).filter_by(
        organization_id=org.id, name="AE_JE"
    ).first()
    # Mark AE_JE tester-assignable if it exists
    if role_ae_je and not role_ae_je.is_tester_assignable:
        role_ae_je.is_tester_assignable = True

    # ── 6 new OrgRoles ───────────────────────────────────────────────────────
    role_ee_rt  = _get_or_create_role(session, org.id, "EE-R&T",  "Test Result Reviewer — R&T Stream")
    role_aee_rt = _get_or_create_role(session, org.id, "AEE R&T", "Test Assigner — R&T Stream")
    role_ae_rt  = _get_or_create_role(session, org.id, "AE-R&T",  "Tester — R&T Stream (Level 4)", is_tester_assignable=True)
    role_ee_rd  = _get_or_create_role(session, org.id, "EE-R&D",  "Test Result Reviewer — R&D Stream")
    role_aee_rd = _get_or_create_role(session, org.id, "AEE-R&D", "Test Assigner — R&D Stream")
    role_ae_rd  = _get_or_create_role(session, org.id, "AE-R&D",  "Tester — R&D Stream (Level 4)", is_tester_assignable=True)
    session.flush()

    # ── Module permissions ────────────────────────────────────────────────────
    if role_ee_tlss:
        _grant_module(session, role_ee_tlss, mod_map, "TR Approval Queue", can_view=True, can_add=True, can_edit=True)
        _grant_module(session, role_ee_tlss, mod_map, "TR Result Review",  can_view=True, can_edit=True)
        _grant_module(session, role_ee_tlss, mod_map, "TR Workflow Config", can_view=True, can_add=True, can_edit=True)
        _grant_module(session, role_ee_tlss, mod_map, "TR Routing Config",  can_view=True, can_add=True, can_edit=True)
    if role_aee_maint:
        _grant_module(session, role_aee_maint, mod_map, "TR Approval Queue", can_view=True, can_add=True, can_edit=True)
    if role_ae_je:
        _grant_module(session, role_ae_je, mod_map, "TR Approval Queue", can_view=True, can_edit=True)
    _grant_module(session, role_aee_rt,  mod_map, "TR Approval Queue",  can_view=True, can_add=True, can_edit=True)
    _grant_module(session, role_aee_rd,  mod_map, "TR Approval Queue",  can_view=True, can_add=True, can_edit=True)
    _grant_module(session, role_ae_rt,   mod_map, "TR Approval Queue",  can_view=True, can_edit=True)
    _grant_module(session, role_ae_rd,   mod_map, "TR Approval Queue",  can_view=True, can_edit=True)
    _grant_module(session, role_ee_rt,   mod_map, "TR Result Review",   can_view=True, can_edit=True)
    _grant_module(session, role_ee_rd,   mod_map, "TR Result Review",   can_view=True, can_edit=True)
    # AE-R&T and AE-R&D must have Testing module perms to appear in the tester picker
    _grant_module(session, role_ae_rt,   mod_map, "Testing",  can_view=True, can_add=True, can_edit=True, can_delete=True, can_approve=True, can_assign=True)
    _grant_module(session, role_ae_rd,   mod_map, "Testing",  can_view=True, can_add=True, can_edit=True, can_delete=True, can_approve=True, can_assign=True)
    session.flush()

    # ── Workflow definitions ──────────────────────────────────────────────────
    wf_normal  = _get_or_create_definition(session, org.id, "Standard Test Workflow",    "normal",  is_default=True)
    wf_rnd     = _get_or_create_definition(session, org.id, "Standard R&D Workflow",     None)
    wf_failure = _get_or_create_definition(session, org.id, "Failure Registry Workflow", "failure")
    wf_special = _get_or_create_definition(session, org.id, "Special Test Workflow",     "special")

    # Set default L3 role + default tester role on Standard Test Workflow
    if wf_normal.default_l3_role_id is None and role_aee_rt:
        wf_normal.default_l3_role_id = role_aee_rt.id
        print("  [SET] Standard Test Workflow default_l3_role -> AEE R&T")
    if wf_normal.default_tester_role_id is None and role_ae_rt:
        wf_normal.default_tester_role_id = role_ae_rt.id
        print("  [SET] Standard Test Workflow default_tester_role -> AE-R&T")

    # Set default L3 role + default tester role on Standard R&D Workflow
    if wf_rnd.default_l3_role_id is None and role_aee_rd:
        wf_rnd.default_l3_role_id = role_aee_rd.id
        print("  [SET] Standard R&D Workflow default_l3_role -> AEE-R&D")
    if wf_rnd.default_tester_role_id is None and role_ae_rd:
        wf_rnd.default_tester_role_id = role_ae_rd.id
        print("  [SET] Standard R&D Workflow default_tester_role -> AE-R&D")

    session.flush()

    # ── Statuses for Normal workflow ──────────────────────────────────────────
    st_l2_pending = _get_or_create_status(session, wf_normal, "l2_pending_approval",   "Pending L2 Approval",   10, "#F59E0B", approval=True)
    st_l3_pending = _get_or_create_status(session, wf_normal, "l3_pending_assignment", "Pending L3 Assignment", 20, "#3B82F6", assignment=True)
    st_testing    = _get_or_create_status(session, wf_normal, "testing_in_progress",   "Testing In Progress",   30, "#8B5CF6")
    st_review     = _get_or_create_status(session, wf_normal, "under_l3_review",       "Under L3 Review",       40, "#0891B2", approval=True)
    st_completed  = _get_or_create_status(session, wf_normal, "wf_completed",          "Workflow Completed",    50, "#10B981", terminal=True)
    st_rejected   = _get_or_create_status(session, wf_normal, "wf_rejected",           "Rejected",              60, "#EF4444", terminal=True)
    st_cancelled  = _get_or_create_status(session, wf_normal, "wf_cancelled",          "Cancelled",             70, "#6B7280", terminal=True)
    session.flush()

    # ── Stages for Normal workflow ────────────────────────────────────────────
    sg_l2    = _get_or_create_stage(session, wf_normal, st_l2_pending, "L2 Approval & Route",  "l2_approve_route",  1)
    sg_l3a   = _get_or_create_stage(session, wf_normal, st_l3_pending, "L3 Tester Assignment", "l3_assign_tester",  2)
    sg_l4    = _get_or_create_stage(session, wf_normal, st_testing,    "L4 Test Execution",    "l4_test_execution", 3)
    sg_l3rev = _get_or_create_stage(session, wf_normal, st_review,     "L3 Result Review",     "l3_review_result",  4)
    session.flush()

    # ── Stage roles ───────────────────────────────────────────────────────────
    _get_or_create_stage_role(session, sg_l2,    role_ee_tlss,  can_approve=True)
    _get_or_create_stage_role(session, sg_l3a,   role_aee_rt,   can_assign=True)
    _get_or_create_stage_role(session, sg_l3a,   role_aee_rd,   can_assign=True)
    if role_aee_maint:
        _get_or_create_stage_role(session, sg_l3a, role_aee_maint, can_assign=True)
    _get_or_create_stage_role(session, sg_l4,    role_ae_rt,    can_edit=True)
    _get_or_create_stage_role(session, sg_l4,    role_ae_rd,    can_edit=True)
    if role_ae_je:
        _get_or_create_stage_role(session, sg_l4, role_ae_je,   can_edit=True)
    _get_or_create_stage_role(session, sg_l3rev, role_ee_rt,    can_approve=True)
    _get_or_create_stage_role(session, sg_l3rev, role_ee_rd,    can_approve=True)
    if role_ee_tlss:
        _get_or_create_stage_role(session, sg_l3rev, role_ee_tlss, can_approve=True)
    session.flush()

    # ── Transitions ───────────────────────────────────────────────────────────
    # L2
    _get_or_create_transition(session, sg_l2, sg_l3a,  "approve")
    _get_or_create_transition(session, sg_l2, None,    "reject",  requires_comment=True, is_rejection=True, terminal_status=st_rejected)
    _get_or_create_transition(session, sg_l2, None,    "cancel",  requires_comment=True, terminal_status=st_cancelled)
    # L3 assign
    _get_or_create_transition(session, sg_l3a, sg_l4,  "assign")
    _get_or_create_transition(session, sg_l3a, None,   "cancel",  requires_comment=True, terminal_status=st_cancelled)
    # L4 execution
    _get_or_create_transition(session, sg_l4, sg_l3rev, "complete")
    _get_or_create_transition(session, sg_l4, sg_l3a,   "return",  requires_comment=True)
    # L3 review
    _get_or_create_transition(session, sg_l3rev, None,  "approve", terminal_status=st_completed, post_action="recommendation_finalize")
    _get_or_create_transition(session, sg_l3rev, sg_l4, "reject",  requires_comment=True, is_rejection=True)
    _get_or_create_transition(session, sg_l3rev, None,  "cancel",  requires_comment=True, terminal_status=st_cancelled)
    session.flush()

    # ── Routing default + request_type overrides ──────────────────────────────
    if not session.query(TrWfRoutingDefault).filter_by(org_id=org.id).first():
        session.add(TrWfRoutingDefault(
            id=uuid.uuid4(),
            org_id=org.id,
            wf_definition_id=wf_normal.id,
        ))
        print("  [NEW] TrWfRoutingDefault -> Standard Test Workflow")

    for req_type, wf_def in [("failure", wf_failure), ("special", wf_special)]:
        if not session.query(TrWfRoutingRule).filter_by(
            org_id=org.id, request_type=req_type,
            equipment_type_id=None, test_type_id=None,
        ).first():
            session.add(TrWfRoutingRule(
                id=uuid.uuid4(),
                org_id=org.id,
                wf_definition_id=wf_def.id,
                request_type=req_type,
                priority=10,
                is_active=True,
            ))
            print(f"  [NEW] TrWfRoutingRule: request_type={req_type} -> {wf_def.name}")

    # ── R&D role override rules ───────────────────────────────────────────────
    # For these test types the override_role (AEE-R&D) takes precedence over the
    # workflow's default_l3_role (AEE R&T). No workflow switch — same Standard
    # Test Workflow runs, but the L3 assigner queue is filtered to AEE-R&D only.
    # IDs from CategoryDetails where category_type='test':
    #   64  Capacitance & Tan Delta Test (Transformer)
    #   65  Capacitance & Tan Delta Comparison
    #   70  Winding Tan-Delta & Capacitance Test
    #   71  220kV Bushing Tan-Delta Test
    #   72  66kV Bushing Tan-Delta Test
    #  136  Insulation Resistance (IR) Test
    #  186  Insulation Resistance Test (PI variant)
    #   66  Transformer Oil Test (BDV)
    #   68  Sweep Frequency Response Analysis (SFRA)
    #   75  SFRA — Routine
    rd_test_type_ids = [64, 65, 70, 71, 72, 136, 186, 66, 68, 75]
    for tt_id in rd_test_type_ids:
        existing = session.query(TrWfRoutingRule).filter_by(
            org_id=org.id, test_type_id=tt_id,
            equipment_type_id=None, request_type=None,
        ).first()
        if not existing:
            session.add(TrWfRoutingRule(
                id=uuid.uuid4(),
                org_id=org.id,
                wf_definition_id=wf_normal.id,
                override_role_id=role_aee_rd.id,
                override_tester_role_id=role_ae_rd.id,
                test_type_id=tt_id,
                priority=20,
                is_active=True,
            ))
            print(f"  [NEW] TrWfRoutingRule: test_type_id={tt_id} -> override_role=AEE-R&D, tester=AE-R&D")
        else:
            changed = False
            if existing.override_role_id is None and role_aee_rd:
                existing.override_role_id = role_aee_rd.id
                existing.wf_definition_id = wf_normal.id
                changed = True
            if existing.override_tester_role_id is None and role_ae_rd:
                existing.override_tester_role_id = role_ae_rd.id
                changed = True
            if changed:
                print(f"  [UPD] TrWfRoutingRule: test_type_id={tt_id} -> AEE-R&D / AE-R&D")

    session.flush()
    print("  [OK] TR Configurable Workflow Engine seeding complete")
