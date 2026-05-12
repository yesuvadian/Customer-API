import json
import uuid
from datetime import datetime

from models import (
    OrgTestTemplate,
    RepairStageDefinition,
    RepairStageTemplate,
    RepairStageRole,
    RepairStageTransition,
    OrgRole,
    CategoryMaster,
    CategoryDetail
)


def seed_all(db, templates, stages, roles, transitions):

    template_map = {}
    stage_map = {}

    # =====================
    # 1. INSERT TEMPLATES
    # =====================
    for key, t in templates.items():

        category = db.query(CategoryMaster).filter_by(code=t["category_code"]).first()
        category_detail = db.query(CategoryDetail).filter_by(code=t["category_detail_code"]).first()

        existing = db.query(OrgTestTemplate).filter_by(template_key=key).first()

        if existing:
            template_map[key] = existing.id
            continue

        obj = OrgTestTemplate(
            id=uuid.uuid4(),
            template_key=key,
            template_type=t["template_type"],
            template_data=t,
            category_id=category.id if category else None,
            category_detail_id=category_detail.id if category_detail else None,
            created_at=datetime.utcnow()
        )

        db.add(obj)
        db.flush()
        template_map[key] = obj.id

    # =====================
    # 2. INSERT STAGES
    # =====================
    for s in stages:

        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            code=s["code"],
            name=s["name"],
            sequence=s["sequence"],
            weight=s.get("weight", 10),
            is_active=True
        )

        db.add(stage)
        db.flush()

        stage_map[s["code"]] = stage.id

        db.add(RepairStageTemplate(
            stage_id=stage.id,
            template_id=template_map[s["template_key"]]
        ))

    # =====================
    # 3. ROLE MAPPING
    # =====================
    for r in roles:

        stage_id = stage_map[r["stage_code"]]

        for role_name in r["roles"]:

            role = db.query(OrgRole).filter_by(name=role_name).first()

            if role:
                db.add(RepairStageRole(
                    stage_id=stage_id,
                    role_id=role.id,
                    can_edit=True,
                    can_approve=True
                ))

    # =====================
    # 4. TRANSITIONS
    # =====================
    for t in transitions:

        db.add(RepairStageTransition(
            id=uuid.uuid4(),
            from_stage_id=stage_map[t["from"]],
            to_stage_id=stage_map.get(t["to"]),
            action=t["action"]
        ))

    db.commit()

    print("✅ FULL WORKFLOW SEEDED")