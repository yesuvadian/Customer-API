"""
Seed the DPR (Detailed Project Report) approval workflow — stages, per-stage
dynamic-form templates, transitions, and role mappings.

Follows the exact pattern seed_precommission_workflow.py / seed_overhaul_workflow.py
already use: RepairWorkflowDefinition + RepairStageDefinition + RepairStageRole +
RepairStageTransition + RepairStageTemplate (-> OrgTestTemplate). Nothing new in
the workflow engine itself — only new stage/template/role/transition DATA.

Call order:
  1. seed_dpr_stages(db)                    — org-agnostic; run once during full seed
  2. seed_dpr_role_mappings(db, org_id)     — org-specific; run per organization
     (RepairStageRole — stage-level edit/approve gates on the workflow itself)
  3. seed_dpr_role_permissions(db, org_id)  — org-specific; run per organization
     (OrgRolePermission — sidebar visibility + module-level CRUD grant for the
     "DPR Projects" Module row seeded by seed.py's seed_modules(). This is a
     DIFFERENT table from step 2's RepairStageRole: OrgRolePermission controls
     whether a role sees "DPR Projects" in the sidebar at all and what it can
     do at the module level; RepairStageRole controls which *stage* within an
     already-open DPR project a role can act on. Both are needed.)

Lifecycle (§11):
  INITIATION           → (approve) → COST_ESTIMATION
  COST_ESTIMATION      → (approve) → TECHNICAL_REVIEW
  TECHNICAL_REVIEW     → (approve) → AUTHORITY_APPROVAL
  AUTHORITY_APPROVAL   → (approve) → EXECUTION_TRACKING
  EXECUTION_TRACKING   → (approve) → [terminal — DPR complete]

  Reject sends the DPR back one stage for revision (Cost Estimation reject ->
  Initiation, Technical Review reject -> Cost Estimation, Authority Approval
  reject -> Technical Review), except:
    - INITIATION reject has nowhere earlier to go -> terminal (DPR rejected
      outright at the proposal stage).
    - EXECUTION_TRACKING has no reject action - once approved, an execution
      problem is a project-management concern, not a workflow rejection.

OPEN DESIGN QUESTION (not resolved by this seed): "Authority approval...
likely tiered by cost, though the spec doesn't specify exact thresholds."
Two ways to implement tiering once thresholds are known:
  (a) Multiple RepairStageRole grants on the single AUTHORITY_APPROVAL stage,
      keyed by a cost band read from DprProject.estimated_cost in application
      code before showing available approvers (simplest, no schema change).
  (b) Split into AUTHORITY_APPROVAL_L1 / _L2 / _L3 sub-stages with a
      COMPARE-style branch chosen by cost - same pattern already used for
      voltage-tier branching in capacitance_tandelta_transformer's
      visibility_rule (see alter_capacitance_tandelta_visibility_rules.py).
  This seed ships a single AUTHORITY_APPROVAL stage (option a's shape) -
  swap to (b) once the actual cost thresholds are confirmed.

ROLES: ships wired to EXISTING org roles (AEE_MAINTENANCE / EE_TLSS /
CEE_TRANSMISSION_ZONE / Transformer Repair Coordinator - borrowed from TAQC
and Pre-Commission, see ROLE_MAP below), not dedicated DPR roles, per
instruction to build with what exists now and re-tag once real DPR-specific
approval roles are created.
"""

import uuid

from models import (
    OrgRole,
    OrgTestTemplate,
    RepairStageDefinition,
    RepairStageRole,
    RepairStageTemplate,
    RepairStageTransition,
    RepairWorkflowDefinition,
)

WORKFLOW_CODE = "DPR_APPROVAL"

STAGES = [
    {"code": "DPR_INITIATION",         "name": "Initiation",           "sequence": 1, "default_duration_days": 7},
    {"code": "DPR_COST_ESTIMATION",    "name": "Cost Estimation",      "sequence": 2, "default_duration_days": 14},
    {"code": "DPR_TECHNICAL_REVIEW",   "name": "Technical Review",     "sequence": 3, "default_duration_days": 10},
    {"code": "DPR_AUTHORITY_APPROVAL", "name": "Authority Approval",   "sequence": 4, "default_duration_days": 14},
    {"code": "DPR_EXECUTION_TRACKING", "name": "Execution Tracking",   "sequence": 5, "default_duration_days": None},
]

# (from_code, action, to_code | None for terminal)
TRANSITIONS = [
    ("DPR_INITIATION",         "approve", "DPR_COST_ESTIMATION"),
    ("DPR_COST_ESTIMATION",    "approve", "DPR_TECHNICAL_REVIEW"),
    ("DPR_TECHNICAL_REVIEW",   "approve", "DPR_AUTHORITY_APPROVAL"),
    ("DPR_AUTHORITY_APPROVAL", "approve", "DPR_EXECUTION_TRACKING"),
    ("DPR_EXECUTION_TRACKING", "approve", None),  # terminal — DPR complete

    # Reject → previous stage for revision; Initiation reject has no earlier
    # stage to return to, so it's terminal (DPR rejected outright).
    ("DPR_INITIATION",         "reject",  None),
    ("DPR_COST_ESTIMATION",    "reject",  "DPR_INITIATION"),
    ("DPR_TECHNICAL_REVIEW",   "reject",  "DPR_COST_ESTIMATION"),
    ("DPR_AUTHORITY_APPROVAL", "reject",  "DPR_TECHNICAL_REVIEW"),
    # No reject on DPR_EXECUTION_TRACKING — see module docstring.
]

# INTERIM: mapped onto roles that already exist in this org today, borrowed
# from other workflows (TAQC / Pre-Commission / TR) rather than a dedicated
# DPR approval hierarchy — none of these are DPR-specific. Per instruction:
# ship with existing roles now, create real DPR-specific roles (proper
# EE/SEE/CE-equivalent capital-approval tiers) and re-tag ROLE_MAP later.
# Source of each name: ANNUAL_AUDIT_STAGE_ROLES.json (AEE_MAINTENANCE,
# Transformer Repair Coordinator) and PRECOMMISSION_STAGE_ROLES.json
# (EE_TLSS, CEE_TRANSMISSION_ZONE) — confirmed live in this org.
# Unknown role names are skipped with a [WARN], same as
# seed_precommission_role_mappings() — safe to run speculatively.
ROLE_MAP = {
    # stage_code: {
    #   "edit": [...roles that can fill the form...],
    #   "approve": [...roles that can advance/reject...],
    #   "assign": [...roles that can assign users to this stage (coordinators)...]
    # }
    "DPR_INITIATION":         {"edit": ["AEE_MAINTENANCE"], "approve": ["EE_TLSS"], "assign": ["AEE_MAINTENANCE", "Transformer Repair Coordinator"]},
    "DPR_COST_ESTIMATION":    {"edit": ["AEE_MAINTENANCE"], "approve": ["EE_TLSS"], "assign": ["AEE_MAINTENANCE", "Transformer Repair Coordinator"]},
    "DPR_TECHNICAL_REVIEW":   {"edit": ["EE_TLSS"],          "approve": ["CEE_TRANSMISSION_ZONE"], "assign": ["EE_TLSS", "Transformer Repair Coordinator"]},
    "DPR_AUTHORITY_APPROVAL": {"edit": [],                    "approve": ["CEE_TRANSMISSION_ZONE"], "assign": ["CEE_TRANSMISSION_ZONE"]},  # see tiering note above — highest existing role, re-tag once real approval tiers exist
    "DPR_EXECUTION_TRACKING": {"edit": ["AEE_MAINTENANCE", "Transformer Repair Coordinator"], "approve": ["EE_TLSS"], "assign": ["AEE_MAINTENANCE", "Transformer Repair Coordinator"]},
}

# ── Per-stage dynamic-form schemas (OrgTestTemplate.template_data) ─────────
# Same shape as test_templates.py: {"sections": [{"title", "fields": [...]}]}.
# Kept intentionally lean for this sketch — extend field-by-field the same
# way the Template Designer already lets you.

_TEMPLATES = {
    "dpr_initiation_form": {
        "name": "DPR — Initiation",
        "sections": [
            {
                "title": "Project Justification",
                "fields": [
                    {"key": "justification",     "label": "Justification / Need for the Project", "type": "textarea", "required": True},
                    {"key": "urgency",           "label": "Urgency", "type": "dropdown",
                     "options": ["Routine", "Priority", "Emergency"], "required": True},
                    {"key": "expected_benefit",  "label": "Expected Benefit / Outcome", "type": "textarea", "required": True},
                    {"key": "proposed_timeline", "label": "Proposed Timeline", "type": "text", "placeholder": "e.g. 6 months from sanction"},
                ],
            },
        ],
    },
    "dpr_cost_estimation_form": {
        "name": "DPR — Cost Estimation",
        "sections": [
            {
                "title": "Estimation Basis",
                "fields": [
                    {"key": "estimation_basis", "label": "Estimation Basis", "type": "dropdown",
                     "options": ["Schedule of Rates", "Market Quotation", "Vendor Quote", "Departmental Estimate"], "required": True},
                    {"key": "estimate_prepared_by", "label": "Estimate Prepared By", "type": "text"},
                ],
            },
            {
                "title": "Cost Breakdown",
                "fields": [
                    {
                        "key": "cost_breakdown",
                        "label": "Cost Breakdown",
                        "type": "table",
                        "allow_add_rows": True,
                        "allow_delete_rows": True,
                        "columns": [
                            {"key": "category",    "label": "Category", "type": "dropdown",
                             "options": ["Equipment", "Civil Works", "Labour", "Contingency", "Other"]},
                            {"key": "item_description", "label": "Item Description", "type": "text"},
                            {"key": "quantity",    "label": "Quantity",   "type": "number"},
                            {"key": "unit_rate",   "label": "Unit Rate",  "type": "number", "unit": "₹"},
                            {
                                "key": "amount", "label": "Amount", "type": "calculated", "read_only": True,
                                "rule": {"type": "FORMULA", "config": {
                                    "formula": "PRODUCT",
                                    "inputs": {"a": "quantity", "b": "unit_rate"},
                                    "precision": 2,
                                }},
                            },
                        ],
                    },
                    # No table-level SUM formula exists yet in the rule engine
                    # (only PRODUCT/SUM(a,b)/RATIO/AVERAGE-of-two, and the
                    # table-column AVERAGE — no "sum a column" op). Total is
                    # entered manually for now; wire up a table-summary/SUM
                    # formula later to auto-total "amount" instead.
                    {"key": "total_estimated_cost", "label": "Total Estimated Cost", "type": "number", "unit": "₹", "required": True},
                ],
            },
        ],
    },
    "dpr_technical_review_form": {
        "name": "DPR — Technical Review",
        "sections": [
            {
                "title": "Feasibility Checklist",
                "fields": [
                    {
                        "key": "review_checklist",
                        "label": "Review Checklist",
                        "type": "table",
                        "allow_add_rows": False,
                        "allow_delete_rows": False,
                        "columns": [
                            {"key": "item",    "label": "Item",    "type": "readonly"},
                            {"key": "status",  "label": "Status",  "type": "dropdown", "options": ["OK", "NOT OK", "N/A"]},
                            {"key": "remarks", "label": "Remarks", "type": "text"},
                        ],
                        "default_rows": [
                            {"item": "Load justification"},
                            {"item": "Technical specification adequacy"},
                            {"item": "Site feasibility"},
                            {"item": "Environmental clearance (if applicable)"},
                            {"item": "Vendor / OEM suitability"},
                        ],
                    },
                ],
            },
            {
                "title": "Recommendation",
                "fields": [
                    {"key": "technical_recommendation", "label": "Technical Recommendation", "type": "dropdown",
                     "options": ["Recommended", "Recommended with Conditions", "Not Recommended"], "required": True},
                    {"key": "conditions", "label": "Conditions (if any)", "type": "textarea"},
                ],
            },
        ],
    },
    "dpr_authority_approval_form": {
        "name": "DPR — Authority Approval",
        "sections": [
            {
                "title": "Approval Decision",
                "fields": [
                    {"key": "approval_decision", "label": "Decision", "type": "dropdown",
                     "options": ["Approved", "Approved with Modifications", "Rejected", "Returned for Revision"], "required": True},
                    {"key": "approved_amount",   "label": "Approved Amount", "type": "number", "unit": "₹"},
                    {"key": "sanction_reference","label": "Sanction / Approval Reference No.", "type": "text"},
                    {"key": "approval_remarks",  "label": "Remarks", "type": "textarea"},
                ],
            },
        ],
    },
    "dpr_execution_tracking_form": {
        "name": "DPR — Execution Tracking",
        "sections": [
            {
                "title": "Progress Update",
                "fields": [
                    {"key": "physical_progress_percent",  "label": "Physical Progress",   "type": "number", "unit": "%"},
                    {"key": "financial_progress_percent",  "label": "Financial Progress",  "type": "number", "unit": "%"},
                    {"key": "expenditure_to_date",          "label": "Expenditure to Date", "type": "number", "unit": "₹"},
                    {"key": "expected_completion_date",     "label": "Expected Completion Date", "type": "date"},
                    {"key": "progress_remarks",             "label": "Remarks", "type": "textarea"},
                ],
            },
        ],
        # Note: vendor/contractor + contract-completion-date already have a
        # home on RepairWorkflow itself (vendor_name, contracted_completion,
        # work_award_at/work_award_by) — no need to duplicate them here.
    },
}

STAGE_TEMPLATE_MAP = {
    "Initiation":         "dpr_initiation_form",
    "Cost Estimation":    "dpr_cost_estimation_form",
    "Technical Review":   "dpr_technical_review_form",
    "Authority Approval": "dpr_authority_approval_form",
    "Execution Tracking": "dpr_execution_tracking_form",
}


def seed_dpr_stages(db) -> int:
    """
    Idempotently insert:
      - RepairWorkflowDefinition  (DPR_APPROVAL)
      - RepairStageDefinition     (5 stages)
      - RepairStageTransition     (9 transitions)
      - OrgTestTemplate           (one per stage)
      - RepairStageTemplate       (stage -> template links)

    Safe to run multiple times. Returns count of stage rows inserted (0 if all present).
    """
    # ── 0. Workflow definition ────────────────────────────────────────────────
    wf_def = db.query(RepairWorkflowDefinition).filter_by(workflow_code=WORKFLOW_CODE).first()
    if not wf_def:
        wf_def = RepairWorkflowDefinition(
            id=uuid.uuid4(),
            workflow_code=WORKFLOW_CODE,
            name="DPR Approval Workflow",
            is_active=True,
        )
        db.add(wf_def)
        db.flush()
    print(f"[OK] RepairWorkflowDefinition {WORKFLOW_CODE}: {wf_def.id}")

    # ── 1. Templates ─────────────────────────────────────────────────────────
    template_map = {}
    for key, t in _TEMPLATES.items():
        existing = db.query(OrgTestTemplate).filter_by(template_key=key).first()
        if existing:
            existing.template_data = t
            existing.is_system = True
            template_map[key] = existing.id
        else:
            obj = OrgTestTemplate(
                id=uuid.uuid4(),
                template_key=key,
                template_data=t,
                is_system=True,
            )
            db.add(obj)
            db.flush()
            template_map[key] = obj.id
    db.flush()
    print(f"[OK] DPR stage templates: {len(template_map)} ready")

    # ── 2. Stages ─────────────────────────────────────────────────────────────
    stage_map = {}
    code_map = {}
    inserted = 0

    for s in STAGES:
        existing = db.query(RepairStageDefinition).filter_by(
            workflow_definition_id=wf_def.id, code=s["code"]
        ).first()
        if existing:
            existing.name = s["name"]
            existing.sequence = s["sequence"]
            existing.default_duration_days = s["default_duration_days"]
            stage_map[s["name"]] = existing.id
            code_map[s["code"]] = existing.id
            continue
        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            workflow_definition_id=wf_def.id,
            name=s["name"],
            code=s["code"],
            sequence=s["sequence"],
            weight=round(100 / len(STAGES)),
            is_active=True,
            is_mandatory=True,
            default_duration_days=s["default_duration_days"],
        )
        db.add(stage)
        db.flush()
        stage_map[s["name"]] = stage.id
        code_map[s["code"]] = stage.id
        inserted += 1

    print(f"[OK] DPR stages: {inserted} inserted ({len(stage_map)} total)")

    # ── 3. Stage → Template links ─────────────────────────────────────────────
    for stage_name, tmpl_key in STAGE_TEMPLATE_MAP.items():
        stage_id = stage_map.get(stage_name)
        template_id = template_map.get(tmpl_key)
        if not stage_id or not template_id:
            print(f"[WARN] Skipping stage-template link: {stage_name!r} -> {tmpl_key!r}")
            continue
        exists = db.query(RepairStageTemplate).filter_by(stage_id=stage_id).first()
        if not exists:
            db.add(RepairStageTemplate(stage_id=stage_id, template_id=template_id))
        else:
            exists.template_id = template_id

    # ── 4. Transitions ────────────────────────────────────────────────────────
    for from_code, action, to_code in TRANSITIONS:
        from_id = code_map.get(from_code)
        to_id = code_map.get(to_code) if to_code else None
        if not from_id:
            continue
        exists = db.query(RepairStageTransition).filter_by(
            from_stage_id=from_id, action=action
        ).first()
        if not exists:
            db.add(RepairStageTransition(
                id=uuid.uuid4(),
                from_stage_id=from_id,
                to_stage_id=to_id,
                action=action,
            ))
        else:
            exists.to_stage_id = to_id

    db.commit()
    print(f"[OK] DPR workflow seeded successfully ({len(TRANSITIONS)} transitions)")
    return inserted


def seed_dpr_role_mappings(db, organization_id) -> int:
    """
    Idempotently insert/update RepairStageRole rows for the given organization,
    from ROLE_MAP. Must be called after seed_dpr_stages so stage rows exist.

    ROLE_MAP's role names are borrowed from existing workflows (TAQC /
    Pre-Commission), not dedicated DPR roles — swap in real DPR-specific
    roles here once they're created. Unknown names are skipped with [WARN],
    so it's safe to run speculatively.
    """
    upserted = 0

    def _find_role(role_name):
        return db.query(OrgRole).filter(
            OrgRole.organization_id == organization_id,
            OrgRole.name == role_name,
            OrgRole.is_active.is_(True),
        ).first()

    def _upsert(stage, role_name, can_edit, can_approve, can_assign=False):
        nonlocal upserted
        role = _find_role(role_name)
        if not role:
            print(f"[WARN] Role not found in org: {role_name!r} — skipping {stage.code}")
            return
        mapping = db.query(RepairStageRole).filter_by(
            stage_id=stage.id, role_id=role.id
        ).first()
        if not mapping:
            mapping = RepairStageRole(id=uuid.uuid4(), stage_id=stage.id, role_id=role.id)
            db.add(mapping)
            upserted += 1
        # Always update permissions (OR them together if role appears in multiple grant lists)
        mapping.can_edit = mapping.can_edit or can_edit
        mapping.can_approve = mapping.can_approve or can_approve
        mapping.can_assign = mapping.can_assign or can_assign
        db.flush()  # Force flush after each role to avoid session conflicts

    for stage_code, grants in ROLE_MAP.items():
        stage = db.query(RepairStageDefinition).filter_by(code=stage_code).first()
        if not stage:
            print(f"[WARN] Stage not found: {stage_code} — run seed_dpr_stages first")
            continue
        for role_name in grants.get("edit", []):
            _upsert(stage, role_name, can_edit=True, can_approve=False, can_assign=False)
        for role_name in grants.get("approve", []):
            _upsert(stage, role_name, can_edit=False, can_approve=True, can_assign=False)
        for role_name in grants.get("assign", []):
            _upsert(stage, role_name, can_edit=False, can_approve=False, can_assign=True)

    db.commit()
    print(f"[OK] DPR role mappings: {upserted} upserted for org {organization_id}")
    return upserted


DPR_MODULE_NAME = "DPR Projects"  # seeded by seed.py's seed_modules() — see seed.py: "DPR Projects" module entry


def seed_dpr_role_permissions(db, organization_id) -> int:
    """
    Idempotently insert/update OrgRolePermission rows on the "DPR Projects"
    Module for every role referenced in ROLE_MAP, so those roles actually see
    the module in their sidebar and can act at the module level. Derived
    automatically from ROLE_MAP so the two never drift apart:
      - any role that ever "edit"s a stage    -> can_view + can_add + can_edit
      - any role that ever "approve"s a stage -> can_view + can_approve + can_assign
      (a role appearing in both gets the union of both grants)

    Must be called after seed_dpr_stages AND after seed.py's seed_modules()
    has created the "DPR Projects" Module row. Unknown role names are skipped
    with [WARN], same as seed_dpr_role_mappings — safe to run speculatively.

    NOTE: this is a DIFFERENT table from seed_dpr_role_mappings' RepairStageRole
    — see the module docstring's "Call order" section for why both are needed.
    """
    from models import Module, OrgRolePermission

    module = db.query(Module).filter_by(name=DPR_MODULE_NAME, is_active=True).first()
    if not module:
        print(f"[WARN] Module {DPR_MODULE_NAME!r} not found — run seed.py's seed_modules() first")
        return 0

    # Derive the union of grants per role from ROLE_MAP.
    grants_by_role: dict[str, dict[str, bool]] = {}
    for stage_grants in ROLE_MAP.values():
        for role_name in stage_grants.get("edit", []):
            g = grants_by_role.setdefault(role_name, {})
            g["can_view"] = True
            g["can_add"] = True
            g["can_edit"] = True
        for role_name in stage_grants.get("approve", []):
            g = grants_by_role.setdefault(role_name, {})
            g["can_view"] = True
            g["can_approve"] = True
            g["can_assign"] = True
        # A role that's only a coordinator (assign, not edit/approve) at every
        # stage it appears in - e.g. "Transformer Repair Coordinator" isn't in
        # any stage's "approve" list - would otherwise never enter
        # grants_by_role at all and get zero module access. Doesn't apply
        # today (every current "assign" role also holds "edit" somewhere),
        # but keeps this in sync with ROLE_MAP instead of silently gapping if
        # that stops being true.
        for role_name in stage_grants.get("assign", []):
            g = grants_by_role.setdefault(role_name, {})
            g["can_view"] = True
            g["can_assign"] = True

    # System Administrator gets full access regardless of ROLE_MAP — same
    # blanket-admin convention as seed_privileges()'s "Admin" role grants in
    # seed.py, just on the org-scoped OrgRolePermission table instead of the
    # legacy global one.
    grants_by_role["System Administrator"] = {
        "can_view": True, "can_add": True, "can_edit": True, "can_delete": True,
        "can_approve": True, "can_assign": True, "can_export": True, "can_import": True,
    }

    upserted = 0
    for role_name, grants in grants_by_role.items():
        role = db.query(OrgRole).filter(
            OrgRole.organization_id == organization_id,
            OrgRole.name == role_name,
            OrgRole.is_active.is_(True),
        ).first()
        if not role:
            print(f"[WARN] Role not found in org: {role_name!r} — skipping module permission")
            continue
        perm = db.query(OrgRolePermission).filter_by(
            org_role_id=role.id, module_id=module.id
        ).first()
        if not perm:
            perm = OrgRolePermission(org_role_id=role.id, module_id=module.id)
            db.add(perm)
        for key, value in grants.items():
            setattr(perm, key, value)
        upserted += 1

    db.commit()
    print(f"[OK] DPR module permissions: {upserted} upserted for org {organization_id}")
    return upserted


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        seed_dpr_stages(db)
    finally:
        db.close()
