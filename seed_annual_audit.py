"""
Seed annual audit workflow stages, stage templates, transitions, and role mappings.

Source files (all at repo root):
  ANNUAL_AUDIT_STAGE_TEMPLATES.json    — {template_key: {name, template_type, sections, ...}}
  ANNUAL_AUDIT_STAGE_TEMPLATE_MAP.json — {stage_name: template_key}
  ANNUAL_AUDIT_STAGE_ROLES.json        — [{stage_code, roles, assign_also, assignment_role}]

Call order:
  1. seed_annual_audit_stages(db)              — org-agnostic; run once during full seed
  2. seed_annual_audit_role_mappings(db, org)  — org-specific; run per organization
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
)

# ---------------------------------------------------------------------------
# Stage + transition definitions  (source of truth for DB shape)
# ---------------------------------------------------------------------------

STAGES = [
    {"code": "OBSERVATION_REPORTING",  "name": "Observation Reporting",  "sequence": 2100},
    {"code": "OBSERVATION_ASSIGNMENT", "name": "Observation Assignment", "sequence": 2110},
    {"code": "COMPLIANCE_SUBMISSION",  "name": "Compliance Submission",  "sequence": 2120},
    {"code": "COMPLIANCE_REVIEW",      "name": "Compliance Review",      "sequence": 2130},
    {"code": "OBSERVATION_CLOSURE",    "name": "Observation Closure",    "sequence": 2140},
]

# (from_code, action, to_code | None for terminal)
TRANSITIONS = [
    ("OBSERVATION_REPORTING",  "approve", "OBSERVATION_ASSIGNMENT"),
    ("OBSERVATION_ASSIGNMENT", "approve", "COMPLIANCE_SUBMISSION"),
    ("COMPLIANCE_SUBMISSION",  "approve", "COMPLIANCE_REVIEW"),
    ("COMPLIANCE_REVIEW",      "approve", "OBSERVATION_CLOSURE"),
    ("OBSERVATION_CLOSURE",    "approve", None),
    ("COMPLIANCE_REVIEW",      "reject",  "COMPLIANCE_SUBMISSION"),
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

def seed_annual_audit_stages(db) -> int:
    """
    Idempotently insert:
      - RepairStageDefinition  (5 stages)
      - RepairStageTransition  (6 transitions)
      - OrgTestTemplate        (one per stage, from ANNUAL_AUDIT_STAGE_TEMPLATES.json)
      - RepairStageTemplate    (stage → template links, from ANNUAL_AUDIT_STAGE_TEMPLATE_MAP.json)

    Safe to run multiple times. Returns the count of stage rows inserted (0 if all already present).
    """
    templates_raw = _load("ANNUAL_AUDIT_STAGE_TEMPLATES.json")
    stage_tmpl_map = _load("ANNUAL_AUDIT_STAGE_TEMPLATE_MAP.json")  # {stage_name: template_key}

    # ── 1. Templates ─────────────────────────────────────────────────────────
    template_map = {}   # key → UUID
    for key, t in templates_raw.items():
        existing = db.query(OrgTestTemplate).filter_by(template_key=key).first()
        if existing:
            template_map[key] = existing.id
            continue
        obj = OrgTestTemplate(
            id=uuid.uuid4(),
            template_key=key,
            template_data=t,
            is_system=True,
        )
        db.add(obj)
        db.flush()
        template_map[key] = obj.id
    print(f"[OK] Annual Audit stage templates: {len(template_map)} ready")

    # ── 2. Stages ─────────────────────────────────────────────────────────────
    stage_map = {}      # name → UUID
    code_map  = {}      # code → UUID
    inserted  = 0

    for s in STAGES:
        existing = db.query(RepairStageDefinition).filter_by(code=s["code"]).first()
        if existing:
            # Keep name/sequence in sync
            existing.name     = s["name"]
            existing.sequence = s["sequence"]
            stage_map[s["name"]] = existing.id
            code_map[s["code"]]  = existing.id
            continue
        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            name=s["name"],
            code=s["code"],
            sequence=s["sequence"],
            weight=20,
            is_active=True,
            is_mandatory=True,
        )
        db.add(stage)
        db.flush()
        stage_map[s["name"]] = stage.id
        code_map[s["code"]]  = stage.id
        inserted += 1

    print(f"[OK] Annual Audit stages: {inserted} inserted ({len(stage_map)} total)")

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
    print("[OK] Annual Audit stages seeded successfully")
    return inserted


# ---------------------------------------------------------------------------
# Role mapping seeding  (org-specific — KPTCL for now)
# ---------------------------------------------------------------------------

def seed_annual_audit_role_mappings(db, organization_id) -> int:
    """
    Idempotently insert/update RepairStageRole rows for the given organization
    using ANNUAL_AUDIT_STAGE_ROLES.json.

    JSON format per entry:
      stage_code      — matches RepairStageDefinition.code
      roles           — can_edit=True, can_approve=True
      assign_also     — roles that are also in `roles` but additionally need can_assign=True
      assignment_role — can_assign=True only (Workflow Coordinator pattern)

    Must be called after seed_annual_audit_stages so stage rows exist.
    Returns the number of role mapping rows upserted.
    """
    roles_raw = _load("ANNUAL_AUDIT_STAGE_ROLES.json")
    upserted  = 0

    for entry in roles_raw:
        stage_code = entry["stage_code"]
        stage = db.query(RepairStageDefinition).filter_by(code=stage_code).first()
        if not stage:
            print(f"[WARN] Stage not found: {stage_code} — run seed_annual_audit_stages first")
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

        # Stage actor roles: can_edit + can_approve
        for role_name in entry.get("roles", []):
            _upsert(role_name, can_edit=True, can_approve=True, can_assign=False)

        # Roles that also need can_assign (already seeded above — just flip the flag)
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

        # Pure assignment role: can_assign only
        assign_role_name = entry.get("assignment_role")
        if assign_role_name:
            _upsert(assign_role_name, can_edit=False, can_approve=False, can_assign=True)

    db.commit()
    print(f"[OK] Annual Audit role mappings: {upserted} upserted for org {organization_id}")
    return upserted


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from database import SessionLocal

    db = SessionLocal()
    try:
        seed_annual_audit_stages(db)
    finally:
        db.close()
