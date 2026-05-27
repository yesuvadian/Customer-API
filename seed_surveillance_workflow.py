"""
Seed surveillance workflow stages, stage templates, transitions, and role mappings.

Post-commissioning 24-month surveillance with quarterly testing (Q1-Q4) and final evaluation.

Source files (templates only - at repo root):
  SURVEILLANCE_STAGE_TEMPLATES.json      — {template_key: {name, template_type, sections, ...}}
  SURVEILLANCE_STAGE_TEMPLATE_MAP.json   — {stage_name: template_key}

Call order:
  1. seed_surveillance_stages(db)                   — org-agnostic; run once during full seed
  2. seed_surveillance_role_mappings(db, org_id)    — org-specific; run per organization

Lifecycle:
  Q1_SURVEILLANCE → (approve) → Q2_SURVEILLANCE
  Q2_SURVEILLANCE → (approve) → Q3_SURVEILLANCE
  Q3_SURVEILLANCE → (approve) → Q4_SURVEILLANCE
  Q4_SURVEILLANCE → (approve) → FINAL_EVALUATION
  FINAL_EVALUATION → (approve) → [closed / terminal]
"""

import json
import os
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

SURVEILLANCE_WORKFLOW_CODE = "SURVEILLANCE"

# Surveillance stages: Q1-Q4 quarterly reviews + final evaluation
STAGES = [
    {"code": "Q1_SURVEILLANCE",  "name": "Q1 Surveillance Testing",    "sequence": 1, "default_duration_days": 30},
    {"code": "Q2_SURVEILLANCE",  "name": "Q2 Surveillance Testing",    "sequence": 2, "default_duration_days": 30},
    {"code": "Q3_SURVEILLANCE",  "name": "Q3 Surveillance Testing",    "sequence": 3, "default_duration_days": 30},
    {"code": "Q4_SURVEILLANCE",  "name": "Q4 Surveillance Testing",    "sequence": 4, "default_duration_days": 30},
    {"code": "FINAL_EVALUATION", "name": "Final Evaluation & Report",  "sequence": 5, "default_duration_days": 45},
]

# (from_code, action, to_code | None for terminal)
TRANSITIONS = [
    ("Q1_SURVEILLANCE",  "approve", "Q2_SURVEILLANCE"),
    ("Q2_SURVEILLANCE",  "approve", "Q3_SURVEILLANCE"),
    ("Q3_SURVEILLANCE",  "approve", "Q4_SURVEILLANCE"),
    ("Q4_SURVEILLANCE",  "approve", "FINAL_EVALUATION"),
    ("FINAL_EVALUATION", "approve", None),  # terminal — surveillance closed
]

# Stage role assignments
# Each stage_code maps to:
#   roles: list of role names that can edit/submit the stage
#   assign_also: roles that can be assigned to the stage
#   assignment_role: role that can assign users to the stage
STAGE_ROLES = [
    {
        "stage_code": "Q1_SURVEILLANCE",
        "roles": ["Reviewing Officer", "Maintenance Officer", "Supervisory Officer"],
        "assign_also": ["Reviewing Officer"],
        "assignment_role": "Transformer Repair Coordinator"
    },
    {
        "stage_code": "Q2_SURVEILLANCE",
        "roles": ["Reviewing Officer", "Maintenance Officer", "Supervisory Officer"],
        "assign_also": ["Reviewing Officer"],
        "assignment_role": "Transformer Repair Coordinator"
    },
    {
        "stage_code": "Q3_SURVEILLANCE",
        "roles": ["Reviewing Officer", "Maintenance Officer", "Supervisory Officer"],
        "assign_also": ["Reviewing Officer"],
        "assignment_role": "Transformer Repair Coordinator"
    },
    {
        "stage_code": "Q4_SURVEILLANCE",
        "roles": ["Reviewing Officer", "Maintenance Officer", "Supervisory Officer"],
        "assign_also": ["Reviewing Officer"],
        "assignment_role": "Transformer Repair Coordinator"
    },
    {
        "stage_code": "FINAL_EVALUATION",
        "roles": ["Senior Management Approver", "Supervisory Officer", "Reviewing Officer"],
        "assign_also": ["Supervisory Officer"],
        "assignment_role": "Transformer Repair Coordinator"
    },
]


def _load(fname: str):
    path = os.path.join(os.path.dirname(__file__), fname)
    if not os.path.exists(path):
        print(f"[WARN] File not found: {fname}")
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def seed_surveillance_stages(db) -> int:
    """
    Idempotently insert:
      - RepairWorkflowDefinition  (SURVEILLANCE)
      - RepairStageDefinition     (5 stages: Q1-Q4 + Final Evaluation)
      - RepairStageTransition     (4 approve transitions + 1 terminal)
      - OrgTestTemplate           (one per stage)
      - RepairStageTemplate       (stage → template links)

    Safe to run multiple times. Returns count of stage rows inserted (0 if all already present).
    """
    templates_raw  = _load("SURVEILLANCE_STAGE_TEMPLATES.json")
    stage_tmpl_map = _load("SURVEILLANCE_STAGE_TEMPLATE_MAP.json")

    if not templates_raw or not stage_tmpl_map:
        print("[WARN] Missing surveillance template JSON files - skipping surveillance stages")
        return 0

    # ── 0. Workflow definition ────────────────────────────────────────────────
    wf_def = db.query(RepairWorkflowDefinition).filter_by(
        workflow_code=SURVEILLANCE_WORKFLOW_CODE
    ).first()
    if not wf_def:
        wf_def = RepairWorkflowDefinition(
            id=uuid.uuid4(),
            workflow_code=SURVEILLANCE_WORKFLOW_CODE,
            name="Post-Commissioning Surveillance",
            is_active=True,
        )
        db.add(wf_def)
        db.flush()
    print(f"[OK] RepairWorkflowDefinition SURVEILLANCE: {wf_def.id}")

    # ── 1. Templates ─────────────────────────────────────────────────────────
    template_map = {}   # key → UUID
    for key, t in templates_raw.items():
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
    print(f"[OK] Surveillance stage templates: {len(template_map)} ready")

    # ── 2. Stages ─────────────────────────────────────────────────────────────
    stage_map = {}   # name → UUID
    code_map  = {}   # code → UUID
    inserted  = 0

    for s in STAGES:
        duration = s.get("default_duration_days")
        existing = db.query(RepairStageDefinition).filter_by(
            workflow_definition_id=wf_def.id, code=s["code"]
        ).first()
        if existing:
            existing.name     = s["name"]
            existing.sequence = s["sequence"]
            if duration is not None and existing.default_duration_days != duration:
                existing.default_duration_days = duration
            stage_map[s["name"]] = existing.id
            code_map[s["code"]]  = existing.id
            continue
        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            workflow_definition_id=wf_def.id,
            name=s["name"],
            code=s["code"],
            sequence=s["sequence"],
            weight=20,  # 5 stages = 20% each
            is_active=True,
            is_mandatory=True,
            default_duration_days=duration,
        )
        db.add(stage)
        db.flush()
        stage_map[s["name"]] = stage.id
        code_map[s["code"]]  = stage.id
        inserted += 1

    print(f"[OK] Surveillance stages: {inserted} inserted ({len(stage_map)} total)")

    # ── 3. Stage → Template links ─────────────────────────────────────────────
    for stage_name, tmpl_key in stage_tmpl_map.items():
        stage_id    = stage_map.get(stage_name)
        template_id = template_map.get(tmpl_key)
        if not stage_id or not template_id:
            continue
        link = db.query(RepairStageTemplate).filter_by(
            stage_id=stage_id, template_id=template_id
        ).first()
        if not link:
            db.add(RepairStageTemplate(stage_id=stage_id, template_id=template_id))

    db.flush()
    print(f"[OK] Surveillance stage → template links: {len(stage_tmpl_map)} ready")

    # ── 4. Transitions ────────────────────────────────────────────────────────
    for from_code, action, to_code in TRANSITIONS:
        from_id = code_map.get(from_code)
        to_id   = code_map.get(to_code) if to_code else None  # None = terminal
        if not from_id:
            continue
        exists = db.query(RepairStageTransition).filter_by(
            from_stage_id=from_id, to_stage_id=to_id, action=action
        ).first()
        if not exists:
            db.add(RepairStageTransition(
                from_stage_id=from_id,
                to_stage_id=to_id,
                action=action,
            ))

    db.flush()
    print(f"[OK] Surveillance stage transitions: {len(TRANSITIONS)} ready")

    # ── 5. Validation ─────────────────────────────────────────────────────────
    print("\n[INFO] Validating surveillance workflow seed...")

    # Verify workflow definition
    verify_wf = db.query(RepairWorkflowDefinition).filter_by(
        workflow_code=SURVEILLANCE_WORKFLOW_CODE
    ).first()

    if not verify_wf:
        print("[ERROR] SURVEILLANCE workflow definition not found after seeding!")
        return inserted

    print(f"  [OK] Workflow definition: {verify_wf.name} (ID: {verify_wf.id})")

    # Verify stages
    verify_stages = db.query(RepairStageDefinition).filter_by(
        workflow_definition_id=verify_wf.id
    ).order_by(RepairStageDefinition.sequence).all()

    if len(verify_stages) != 5:
        print(f"[ERROR] Expected 5 stages, found {len(verify_stages)}")
        return inserted

    print(f"  [OK] Stages ({len(verify_stages)}):")
    for stage in verify_stages:
        print(f"       {stage.sequence}. {stage.name} ({stage.code}, {stage.default_duration_days} days)")

    # Verify transitions
    verify_transitions = db.query(RepairStageTransition).filter(
        RepairStageTransition.from_stage_id.in_([s.id for s in verify_stages])
    ).all()

    print(f"  [OK] Transitions: {len(verify_transitions)} configured")

    # Verify templates
    verify_templates = db.query(OrgTestTemplate).filter(
        OrgTestTemplate.template_key.in_(template_map.keys())
    ).all()

    print(f"  [OK] Templates: {len(verify_templates)} ready")

    print("\n[SUCCESS] Surveillance workflow seed validation passed!")

    db.commit()
    return inserted


def seed_surveillance_role_mappings(db, org_id: uuid.UUID) -> int:
    """
    Create RepairStageRole rows linking surveillance stages to org roles.

    Args:
        db: SQLAlchemy session
        org_id: Organization UUID

    Returns:
        Number of role assignments created
    """
    # Get workflow definition
    wf_def = db.query(RepairWorkflowDefinition).filter_by(
        workflow_code=SURVEILLANCE_WORKFLOW_CODE
    ).first()
    if not wf_def:
        print("[WARN] SURVEILLANCE workflow definition not found - skipping role mappings")
        return 0

    # Get stages
    stages = db.query(RepairStageDefinition).filter_by(
        workflow_definition_id=wf_def.id
    ).all()
    code_map = {s.code: s.id for s in stages}

    # Get org roles
    org_roles = db.query(OrgRole).filter_by(organization_id=org_id).all()
    role_name_map = {r.role_name: r.id for r in org_roles}

    inserted = 0

    for stage_role_spec in STAGE_ROLES:
        stage_code = stage_role_spec["stage_code"]
        stage_id = code_map.get(stage_code)
        if not stage_id:
            continue

        # can_edit / can_approve roles
        for role_name in stage_role_spec.get("roles", []):
            role_id = role_name_map.get(role_name)
            if not role_id:
                continue
            existing = db.query(RepairStageRole).filter_by(
                stage_id=stage_id, role_id=role_id
            ).first()
            if not existing:
                db.add(RepairStageRole(
                    stage_id=stage_id,
                    role_id=role_id,
                    can_edit=True,
                    can_approve=True,
                ))
                inserted += 1

        # assign_also roles (can be assigned to this stage)
        for role_name in stage_role_spec.get("assign_also", []):
            role_id = role_name_map.get(role_name)
            if not role_id:
                continue
            existing = db.query(RepairStageRole).filter_by(
                stage_id=stage_id, role_id=role_id
            ).first()
            if existing:
                if not existing.can_be_assigned:
                    existing.can_be_assigned = True
            else:
                db.add(RepairStageRole(
                    stage_id=stage_id,
                    role_id=role_id,
                    can_be_assigned=True,
                ))
                inserted += 1

        # assignment_role (can assign users to this stage)
        assignment_role_name = stage_role_spec.get("assignment_role")
        if assignment_role_name:
            role_id = role_name_map.get(assignment_role_name)
            if role_id:
                existing = db.query(RepairStageRole).filter_by(
                    stage_id=stage_id, role_id=role_id
                ).first()
                if existing:
                    if not existing.can_assign:
                        existing.can_assign = True
                else:
                    db.add(RepairStageRole(
                        stage_id=stage_id,
                        role_id=role_id,
                        can_assign=True,
                    ))
                    inserted += 1

    db.flush()
    print(f"[OK] Surveillance stage role mappings: {inserted} created for org {org_id}")

    db.commit()
    return inserted
