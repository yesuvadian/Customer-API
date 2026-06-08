"""
Seed pre-commission QAP workflow stages, templates, transitions, and role mappings.

Source files (all at repo root):
  PRECOMMISSION_STAGE_TEMPLATES.json      — {template_key: {name, template_type, sections, ...}}
  PRECOMMISSION_STAGE_TEMPLATE_MAP.json   — {stage_name: template_key}
  PRECOMMISSION_STAGE_ROLES.json          — [{stage_code, roles, assign_also, assignment_role}]

Call order:
  1. seed_precommission_stages(db)                   — org-agnostic; run once during full seed
  2. seed_precommission_role_mappings(db, org_id)    — org-specific; run per organization

Lifecycle:
  QAP_RAW_MATERIAL   → (approve) → QAP_CORE_ASSEMBLY
  QAP_CORE_ASSEMBLY  → (approve) → QAP_WINDING
  QAP_WINDING        → (approve) → QAP_ACTIVE_PART
  QAP_ACTIVE_PART    → (approve) → QAP_TANK_FITTINGS
  QAP_TANK_FITTINGS  → (approve) → QAP_ACTIVE_IN_TANK
  QAP_ACTIVE_IN_TANK → (approve) → QAP_ROUTINE_TESTS
  QAP_ROUTINE_TESTS  → (approve) → QAP_SPECIAL_TESTS
  QAP_SPECIAL_TESTS  → (approve) → QAP_FINAL_DISPATCH
  QAP_FINAL_DISPATCH → (approve) → [terminal — QAP complete]

  Any stage        → (reject)  → same stage  [re-inspection at same fabrication phase]
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

WORKFLOW_CODE = "PRE_COMMISSION"

STAGES = [
    {"code": "QAP_RAW_MATERIAL",   "name": "Raw Material Inspection",        "sequence": 1, "default_duration_days": 3},
    {"code": "QAP_CORE_ASSEMBLY",  "name": "Core Building & Frame Assembly", "sequence": 2, "default_duration_days": 3},
    {"code": "QAP_WINDING",        "name": "Winding Inspection",             "sequence": 3, "default_duration_days": 3},
    {"code": "QAP_ACTIVE_PART",    "name": "Active Part Assembly",           "sequence": 4, "default_duration_days": 3},
    {"code": "QAP_TANK_FITTINGS",  "name": "Tank & Accessories",             "sequence": 5, "default_duration_days": 3},
    {"code": "QAP_ACTIVE_IN_TANK", "name": "Active Part in Main Tank",       "sequence": 6, "default_duration_days": 3},
    {"code": "QAP_ROUTINE_TESTS",  "name": "Pre-Delivery Routine Tests",     "sequence": 7, "default_duration_days": 2},
    {"code": "QAP_SPECIAL_TESTS",  "name": "Special / Type Tests",           "sequence": 8, "default_duration_days": 2},
    {"code": "QAP_FINAL_DISPATCH", "name": "Final Inspection & Dispatch",    "sequence": 9, "default_duration_days": 1},
]

# (from_code, action, to_code | None for terminal)
TRANSITIONS = [
    ("QAP_RAW_MATERIAL",   "approve", "QAP_CORE_ASSEMBLY"),
    ("QAP_CORE_ASSEMBLY",  "approve", "QAP_WINDING"),
    ("QAP_WINDING",        "approve", "QAP_ACTIVE_PART"),
    ("QAP_ACTIVE_PART",    "approve", "QAP_TANK_FITTINGS"),
    ("QAP_TANK_FITTINGS",  "approve", "QAP_ACTIVE_IN_TANK"),
    ("QAP_ACTIVE_IN_TANK", "approve", "QAP_ROUTINE_TESTS"),
    ("QAP_ROUTINE_TESTS",  "approve", "QAP_SPECIAL_TESTS"),
    ("QAP_SPECIAL_TESTS",  "approve", "QAP_FINAL_DISPATCH"),
    ("QAP_FINAL_DISPATCH", "approve", None),               # terminal — QAP complete
    # reject on any stage loops back to same stage (re-inspection)
    ("QAP_RAW_MATERIAL",   "reject",  "QAP_RAW_MATERIAL"),
    ("QAP_CORE_ASSEMBLY",  "reject",  "QAP_CORE_ASSEMBLY"),
    ("QAP_WINDING",        "reject",  "QAP_WINDING"),
    ("QAP_ACTIVE_PART",    "reject",  "QAP_ACTIVE_PART"),
    ("QAP_TANK_FITTINGS",  "reject",  "QAP_TANK_FITTINGS"),
    ("QAP_ACTIVE_IN_TANK", "reject",  "QAP_ACTIVE_IN_TANK"),
    ("QAP_ROUTINE_TESTS",  "reject",  "QAP_ROUTINE_TESTS"),
    ("QAP_SPECIAL_TESTS",  "reject",  "QAP_SPECIAL_TESTS"),
    ("QAP_FINAL_DISPATCH", "reject",  "QAP_FINAL_DISPATCH"),
]


def _load(fname: str):
    path = os.path.join(os.path.dirname(__file__), fname)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def seed_precommission_stages(db) -> int:
    """
    Idempotently insert:
      - RepairWorkflowDefinition  (PRE_COMMISSION)
      - RepairStageDefinition     (9 stages)
      - RepairStageTransition     (17 transitions)
      - OrgTestTemplate           (one per stage)
      - RepairStageTemplate       (stage → template links)

    Safe to run multiple times. Returns count of stage rows inserted (0 if all present).
    """
    templates_raw  = _load("PRECOMMISSION_STAGE_TEMPLATES.json")
    stage_tmpl_map = _load("PRECOMMISSION_STAGE_TEMPLATE_MAP.json")

    # ── 0. Workflow definition ────────────────────────────────────────────────
    wf_def = db.query(RepairWorkflowDefinition).filter_by(workflow_code=WORKFLOW_CODE).first()
    if not wf_def:
        wf_def = RepairWorkflowDefinition(
            id=uuid.uuid4(),
            workflow_code=WORKFLOW_CODE,
            name="Pre-Commission QAP Workflow",
            is_active=True,
        )
        db.add(wf_def)
        db.flush()
    print(f"[OK] RepairWorkflowDefinition {WORKFLOW_CODE}: {wf_def.id}")

    # ── 1. Templates ─────────────────────────────────────────────────────────
    template_map = {}
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
    print(f"[OK] Pre-commission stage templates: {len(template_map)} ready")

    # ── 2. Stages ─────────────────────────────────────────────────────────────
    stage_map = {}
    code_map  = {}
    inserted  = 0

    for s in STAGES:
        existing = db.query(RepairStageDefinition).filter_by(
            workflow_definition_id=wf_def.id, code=s["code"]
        ).first()
        if existing:
            existing.name     = s["name"]
            existing.sequence = s["sequence"]
            if existing.default_duration_days != s["default_duration_days"]:
                existing.default_duration_days = s["default_duration_days"]
            stage_map[s["name"]] = existing.id
            code_map[s["code"]]  = existing.id
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
        code_map[s["code"]]  = stage.id
        inserted += 1

    print(f"[OK] Pre-commission stages: {inserted} inserted ({len(stage_map)} total)")

    # ── 3. Stage → Template links ─────────────────────────────────────────────
    for stage_name, tmpl_key in stage_tmpl_map.items():
        stage_id    = stage_map.get(stage_name)
        template_id = template_map.get(tmpl_key)
        if not stage_id or not template_id:
            print(f"[WARN] Skipping stage-template link: {stage_name!r} → {tmpl_key!r}")
            continue
        exists = db.query(RepairStageTemplate).filter_by(stage_id=stage_id).first()
        if not exists:
            db.add(RepairStageTemplate(stage_id=stage_id, template_id=template_id))
        else:
            exists.template_id = template_id

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
    print(f"[OK] Pre-commission workflow seeded successfully ({len(TRANSITIONS)} transitions)")
    return inserted


def seed_precommission_role_mappings(db, organization_id) -> int:
    """
    Idempotently insert/update RepairStageRole rows for the given organization.
    Must be called after seed_precommission_stages so stage rows exist.
    """
    roles_raw = _load("PRECOMMISSION_STAGE_ROLES.json")
    upserted  = 0

    for entry in roles_raw:
        stage_code = entry["stage_code"]
        stage = db.query(RepairStageDefinition).filter_by(code=stage_code).first()
        if not stage:
            print(f"[WARN] Stage not found: {stage_code} — run seed_precommission_stages first")
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
    print(f"[OK] Pre-commission role mappings: {upserted} upserted for org {organization_id}")
    return upserted


if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        seed_precommission_stages(db)
    finally:
        db.close()
