"""
Seed the Document Support Workflow for the generic WF engine.

Workflow graph:
  [DS Pending Manager]  --assign-->    [DS Pending Processor]
  [DS Pending Processor]--assign-->    [DS Processing]
  [DS Processing]       --complete-->  [DS Originator Review]
  [DS Originator Review]--accept-->    TERMINAL: ds_completed
  [DS Originator Review]--reject-->    [DS Processing]          (send-back to same processor)

Reject from DS Pending Manager → TERMINAL: ds_cancelled
Cancel from any stage → TERMINAL: ds_cancelled

Run this script once after running the DB migration that creates:
  - entity_type / entity_id columns on tr_wf_instances
  - entity_type / entity_id on tr_wf_audit_logs (nullable testing_request_id)
  - document_requests table

All functions are idempotent (get-or-create on every row).
"""

import uuid
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from database import SessionLocal
from models import (
    Organization,
    OrgRole,
    TrWfDefinition,
    TrWfStage,
    TrWfStageRole,
    TrWfStageTransition,
    TrWfStatus,
)


def _org(session) -> Organization:
    for kw in ["%kptcl%", "%karnataka%", "%transmission%"]:
        o = session.query(Organization).filter(Organization.name.ilike(kw)).first()
        if o:
            return o
    o = session.query(Organization).first()
    if not o:
        raise RuntimeError("No organization found — run base seed first.")
    return o


def _get_or_create_definition(session, org_id) -> TrWfDefinition:
    defn = (
        session.query(TrWfDefinition)
        .filter(
            TrWfDefinition.org_id == org_id,
            TrWfDefinition.request_type == "document_support",
        )
        .first()
    )
    if not defn:
        defn = TrWfDefinition(
            id=uuid.uuid4(),
            org_id=org_id,
            name="Document Support Workflow",
            request_type="document_support",
            is_default=False,
            is_active=True,
        )
        session.add(defn)
        session.flush()
        print(f"  Created TrWfDefinition: {defn.id}")
    else:
        print(f"  Found TrWfDefinition:   {defn.id}")
    return defn


def _get_or_create_status(session, defn_id, code, name, seq, is_terminal=False, color=None) -> TrWfStatus:
    s = (
        session.query(TrWfStatus)
        .filter(TrWfStatus.wf_definition_id == defn_id, TrWfStatus.status_code == code)
        .first()
    )
    if not s:
        s = TrWfStatus(
            id=uuid.uuid4(),
            wf_definition_id=defn_id,
            status_code=code,
            status_name=name,
            sequence=seq,
            is_terminal=is_terminal,
            color=color,
            is_active=True,
        )
        session.add(s)
        session.flush()
        print(f"    + Status {code}")
    return s


def _get_or_create_stage(session, defn_id, code, name, seq, status_id=None) -> TrWfStage:
    stg = (
        session.query(TrWfStage)
        .filter(TrWfStage.wf_definition_id == defn_id, TrWfStage.code == code)
        .first()
    )
    if not stg:
        stg = TrWfStage(
            id=uuid.uuid4(),
            wf_definition_id=defn_id,
            status_id=status_id,
            name=name,
            code=code,
            sequence=seq,
            is_mandatory=True,
            is_active=True,
        )
        session.add(stg)
        session.flush()
        print(f"    + Stage {code}")
    return stg


def _add_role(session, stage_id, role_id, can_approve=False, can_assign=False, can_edit=False):
    from models import TrWfStageRole
    existing = (
        session.query(TrWfStageRole)
        .filter(TrWfStageRole.stage_id == stage_id, TrWfStageRole.role_id == role_id)
        .first()
    )
    if not existing:
        session.add(TrWfStageRole(
            id=uuid.uuid4(),
            stage_id=stage_id,
            role_id=role_id,
            can_approve=can_approve,
            can_assign=can_assign,
            can_edit=can_edit,
        ))
        session.flush()


def _add_transition(session, from_stage_id, action_code, to_stage_id=None,
                    terminal_status_id=None, requires_comment=False, is_rejection=False, label=None):
    existing = (
        session.query(TrWfStageTransition)
        .filter(
            TrWfStageTransition.from_stage_id == from_stage_id,
            TrWfStageTransition.action_code == action_code,
        )
        .first()
    )
    if existing:
        if label and not existing.label:
            existing.label = label
    else:
        session.add(TrWfStageTransition(
            id=uuid.uuid4(),
            from_stage_id=from_stage_id,
            to_stage_id=to_stage_id,
            action_code=action_code,
            label=label,
            terminal_status_id=terminal_status_id,
            requires_comment=requires_comment,
            is_rejection=is_rejection,
        ))
    session.flush()


def _resolve_role(session, org_id, *name_fragments) -> OrgRole | None:
    for frag in name_fragments:
        r = (
            session.query(OrgRole)
            .filter(OrgRole.organization_id == org_id, OrgRole.name.ilike(f"%{frag}%"))
            .first()
        )
        if r:
            return r
    return None


def seed_doc_support_workflow(session, org=None):
    if org is None:
        org = _org(session)
    org_id = org.id
    print(f"\n[DS-WF] Seeding Document Support Workflow for org: {org.name} ({org_id})")

    defn = _get_or_create_definition(session, org_id)
    defn_id = defn.id

    # ── Statuses ───────────────────────────────────────────────────────────
    st_pending_mgr    = _get_or_create_status(session, defn_id, "ds_pending_manager",   "Pending Manager Review", 10, color="#7C3AED")
    st_pending_proc   = _get_or_create_status(session, defn_id, "ds_pending_processor", "Pending Processor",      20, color="#0891B2")
    st_processing     = _get_or_create_status(session, defn_id, "ds_processing",        "Processing",             30, color="#EA580C")
    st_orig_review    = _get_or_create_status(session, defn_id, "ds_originator_review", "Originator Review",      40, color="#D97706")
    st_completed      = _get_or_create_status(session, defn_id, "ds_completed",         "Completed",              50, is_terminal=True, color="#16A34A")
    st_cancelled      = _get_or_create_status(session, defn_id, "ds_cancelled",         "Cancelled",              60, is_terminal=True, color="#6B7280")
    st_rejected       = _get_or_create_status(session, defn_id, "ds_rejected",          "Rejected",               70, is_terminal=True, color="#DC2626")

    # ── Stages ─────────────────────────────────────────────────────────────
    stg_mgr    = _get_or_create_stage(session, defn_id, "ds_manager_review",    "Manager Review",      10, status_id=st_pending_mgr.id)
    stg_proc   = _get_or_create_stage(session, defn_id, "ds_processor_queue",   "Processor Queue",     20, status_id=st_pending_proc.id)
    stg_work   = _get_or_create_stage(session, defn_id, "ds_processing",        "Processing",          30, status_id=st_processing.id)
    stg_review = _get_or_create_stage(session, defn_id, "ds_originator_review", "Originator Review",   40, status_id=st_orig_review.id)

    # ── Roles ──────────────────────────────────────────────────────────────
    mgr_role  = _resolve_role(session, org_id, "Dev Support Manager", "Document Manager", "Support Manager")
    proc_role = _resolve_role(session, org_id, "Dev Support", "Document Support", "Support Team")

    if mgr_role:
        _add_role(session, stg_mgr.id, mgr_role.id, can_approve=True, can_assign=True)
        print(f"    Role on Manager stage: {mgr_role.name}")
    else:
        print("    WARNING: No Dev Support Manager role found — add manually after seeding.")

    if proc_role:
        _add_role(session, stg_proc.id, proc_role.id, can_approve=True)
        _add_role(session, stg_work.id, proc_role.id, can_approve=True, can_edit=True)
        print(f"    Role on Processor stages: {proc_role.name}")
    else:
        print("    WARNING: No Dev Support Team role found — add manually after seeding.")

    # Originator review — use __originator__ special sentinel
    # (WorkflowRoutingService already supports this for TR WF; for generic WF
    #  you may need to resolve this in the future if you want dynamic originator role lookup.
    #  For now, leave stage open — originator accepts/rejects via entity's submitted_by check in router.)

    # ── Transitions ────────────────────────────────────────────────────────
    # Manager stage
    _add_transition(session, stg_mgr.id, "assign",  to_stage_id=stg_proc.id,  label="Assign to Processor")
    _add_transition(session, stg_mgr.id, "reject",  terminal_status_id=st_cancelled.id,
                    is_rejection=True, requires_comment=True,                   label="Reject")
    _add_transition(session, stg_mgr.id, "cancel",  terminal_status_id=st_cancelled.id,
                    is_rejection=True,                                           label="Cancel")

    # Processor queue stage (processor self-accepts → work stage)
    _add_transition(session, stg_proc.id, "assign",  to_stage_id=stg_work.id,  label="Accept & Start")
    _add_transition(session, stg_proc.id, "cancel",  terminal_status_id=st_cancelled.id,
                    is_rejection=True,                                           label="Cancel")

    # Processing stage
    _add_transition(session, stg_work.id, "complete", to_stage_id=stg_review.id, label="Mark Complete")
    _add_transition(session, stg_work.id, "cancel",   terminal_status_id=st_cancelled.id,
                    is_rejection=True,                                             label="Cancel")

    # Originator review
    _add_transition(session, stg_review.id, "accept", terminal_status_id=st_completed.id, label="Accept")
    _add_transition(session, stg_review.id, "reject", to_stage_id=stg_work.id,
                    is_rejection=True, requires_comment=True,                              label="Request Changes")

    print(f"[DS-WF] Done. Definition ID: {defn_id}")
    session.commit()


if __name__ == "__main__":
    from seed_doc_support_roles_users import seed_doc_support_roles_users
    from database import VendorSessionLocal
    roles_session = VendorSessionLocal()
    try:
        seed_doc_support_roles_users(roles_session)
    finally:
        roles_session.close()

    db = SessionLocal()
    try:
        seed_doc_support_workflow(db)
    finally:
        db.close()
