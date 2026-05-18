"""
Seed overhaul workflow stages, stage templates, transitions, and role mappings.

Source files (all at repo root):
  OVERHAUL_STAGE_TEMPLATES.json      — {template_key: {name, template_type, sections, ...}}
  OVERHAUL_STAGE_TEMPLATE_MAP.json   — {stage_name: template_key}
  OVERHAUL_STAGE_ROLES.json          — [{stage_code, roles, assign_also, assignment_role}]

Call order:
  1. seed_overhaul_stages(db)                   — org-agnostic; run once during full seed
  2. seed_overhaul_role_mappings(db, org_id)    — org-specific; run per organization

Lifecycle:
  OVERHAUL_TRIGGER      → (approve) → OVERHAUL_EXECUTION
  OVERHAUL_EXECUTION    → (approve) → COMPLETION_UPLOAD
  COMPLETION_UPLOAD     → (approve) → OFFICER_VERIFICATION
  OFFICER_VERIFICATION  → (approve) → [closed / terminal]
  OFFICER_VERIFICATION  → (reject)  → COMPLETION_UPLOAD
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

# ---------------------------------------------------------------------------
# Stage + transition definitions  (source of truth for DB shape)
# ---------------------------------------------------------------------------

STAGES = [
    {"code": "OVERHAUL_TRIGGER",     "name": "Overhaul Triggered",       "sequence": 1, "default_duration_days": 1},
    {"code": "OVERHAUL_EXECUTION",   "name": "Overhaul Execution",        "sequence": 2, "default_duration_days": 14},
    {"code": "COMPLETION_UPLOAD",    "name": "Completion Record Upload",  "sequence": 3, "default_duration_days": 3},
    {"code": "OFFICER_VERIFICATION", "name": "Officer Verification",      "sequence": 4, "default_duration_days": 3},
]

# (from_code, action, to_code | None for terminal)
TRANSITIONS = [
    ("OVERHAUL_TRIGGER",     "approve", "OVERHAUL_EXECUTION"),
    ("OVERHAUL_EXECUTION",   "approve", "COMPLETION_UPLOAD"),
    ("COMPLETION_UPLOAD",    "approve", "OFFICER_VERIFICATION"),
    ("OFFICER_VERIFICATION", "approve", None),                 # terminal — overhaul closed
    ("OFFICER_VERIFICATION", "reject",  "COMPLETION_UPLOAD"),  # Officer rejects → re-upload
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(fname: str):
    path = os.path.join(os.path.dirname(__file__), fname)
    with open(path) as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Stage + template seeding  (org-agnostic)
# ---------------------------------------------------------------------------

def seed_overhaul_stages(db) -> int:
    """
    Idempotently insert:
      - RepairWorkflowDefinition  (OVERHAUL)
      - RepairStageDefinition     (4 stages)
      - RepairStageTransition     (5 transitions)
      - OrgTestTemplate           (one per stage)
      - RepairStageTemplate       (stage → template links)

    Safe to run multiple times. Returns count of stage rows inserted (0 if all already present).
    """
    templates_raw  = _load("OVERHAUL_STAGE_TEMPLATES.json")
    stage_tmpl_map = _load("OVERHAUL_STAGE_TEMPLATE_MAP.json")  # {stage_name: template_key}

    # ── 0. Workflow definition ────────────────────────────────────────────────
    wf_def = db.query(RepairWorkflowDefinition).filter_by(workflow_code="OVERHAUL").first()
    if not wf_def:
        wf_def = RepairWorkflowDefinition(
            id=uuid.uuid4(),
            workflow_code="OVERHAUL",
            name="Overhaul Workflow",
            is_active=True,
        )
        db.add(wf_def)
        db.flush()
    print(f"[OK] RepairWorkflowDefinition OVERHAUL: {wf_def.id}")

    # ── 1. Templates ─────────────────────────────────────────────────────────
    template_map = {}   # key → UUID
    for key, t in templates_raw.items():
        existing = db.query(OrgTestTemplate).filter_by(template_key=key).first()
        if existing:
            existing.template_data = t   # always sync latest sections
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
    print(f"[OK] Overhaul stage templates: {len(template_map)} ready")

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
            weight=25,
            is_active=True,
            is_mandatory=True,
            default_duration_days=duration,
        )
        db.add(stage)
        db.flush()
        stage_map[s["name"]] = stage.id
        code_map[s["code"]]  = stage.id
        inserted += 1

    print(f"[OK] Overhaul stages: {inserted} inserted ({len(stage_map)} total)")

    # ── 3. Stage → Template links ─────────────────────────────────────────────
    for stage_name, tmpl_key in stage_tmpl_map.items():
        stage_id    = stage_map.get(stage_name)
        template_id = template_map.get(tmpl_key)
        if not stage_id or not template_id:
            print(f"[WARN] Skipping stage-template link: {stage_name!r} → {tmpl_key!r} (not found)")
            continue
        exists = db.query(RepairStageTemplate).filter_by(stage_id=stage_id).first()
        if not exists:
            db.add(RepairStageTemplate(stage_id=stage_id, template_id=template_id))
        else:
            exists.template_id = template_id   # keep link pointing at latest template

    # ── 4. Transitions ────────────────────────────────────────────────────────
    for from_code, action, to_code in TRANSITIONS:
        from_id = code_map.get(from_code)
        to_id   = code_map.get(to_code) if to_code else None
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
    print("[OK] Overhaul stages seeded successfully")
    return inserted


# ---------------------------------------------------------------------------
# Role mapping seeding  (org-specific)
# ---------------------------------------------------------------------------

def seed_overhaul_role_mappings(db, organization_id) -> int:
    """
    Idempotently insert/update RepairStageRole rows for the given organization.

    Must be called after seed_overhaul_stages so stage rows exist.
    Returns the number of role mapping rows upserted.
    """
    roles_raw = _load("OVERHAUL_STAGE_ROLES.json")
    upserted  = 0

    for entry in roles_raw:
        stage_code = entry["stage_code"]
        stage = db.query(RepairStageDefinition).filter_by(code=stage_code).first()
        if not stage:
            print(f"[WARN] Stage not found: {stage_code} — run seed_overhaul_stages first")
            continue

        def _upsert(role_name, can_edit, can_approve, can_assign):
            nonlocal upserted
            role = db.query(OrgRole).filter(
                OrgRole.organization_id == organization_id,
                OrgRole.name == role_name,
                OrgRole.is_active.is_(True),
            ).first()
            if not role:
                print(f"[WARN] Role not found in org: {role_name!r}")
                return
            mapping = db.query(RepairStageRole).filter_by(
                stage_id=stage.id, role_id=role.id
            ).first()
            if not mapping:
                mapping = RepairStageRole(
                    id=uuid.uuid4(),
                    stage_id=stage.id,
                    role_id=role.id,
                )
                db.add(mapping)
            mapping.can_edit    = can_edit
            mapping.can_approve = can_approve
            mapping.can_assign  = can_assign
            upserted += 1

        for role_name in entry.get("roles", []):
            _upsert(role_name, can_edit=True, can_approve=True, can_assign=False)

        for role_name in entry.get("assign_also", []):
            role = db.query(OrgRole).filter(
                OrgRole.organization_id == organization_id,
                OrgRole.name == role_name,
                OrgRole.is_active.is_(True),
            ).first()
            if role:
                mapping = db.query(RepairStageRole).filter_by(
                    stage_id=stage.id, role_id=role.id
                ).first()
                if mapping:
                    mapping.can_assign = True

        assign_role_name = entry.get("assignment_role")
        if assign_role_name:
            _upsert(assign_role_name, can_edit=False, can_approve=False, can_assign=True)

    db.commit()
    print(f"[OK] Overhaul role mappings: {upserted} upserted for org {organization_id}")
    return upserted


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        seed_overhaul_stages(db)
    finally:
        db.close()
