"""Seed OVERHAUL RepairWorkflowDefinition + stages."""
import uuid
from database import get_db
from models import RepairWorkflowDefinition, RepairStageDefinition, RepairWorkflow

db = next(get_db())

# 1. Find or create definition
defn = db.query(RepairWorkflowDefinition).filter(
    RepairWorkflowDefinition.workflow_code == "OVERHAUL"
).first()

if defn:
    print(f"OVERHAUL definition already exists: {defn.id}")
else:
    defn = RepairWorkflowDefinition(
        id=uuid.uuid4(),
        workflow_code="OVERHAUL",
        name="Overhaul Workflow",
        is_active=True,
    )
    db.add(defn)
    db.flush()
    print(f"Created OVERHAUL definition: {defn.id}")

# 2. Seed stages
stages_data = [
    {"sequence": 1, "code": "OVERHAUL_TRIGGER",     "name": "Overhaul Triggered",        "weight": 10},
    {"sequence": 2, "code": "OVERHAUL_EXECUTION",   "name": "Overhaul Execution",         "weight": 30},
    {"sequence": 3, "code": "COMPLETION_UPLOAD",    "name": "Completion Record Upload",   "weight": 30},
    {"sequence": 4, "code": "OFFICER_VERIFICATION", "name": "Officer Verification",       "weight": 30},
]

for s in stages_data:
    ex = db.query(RepairStageDefinition).filter(
        RepairStageDefinition.workflow_definition_id == defn.id,
        RepairStageDefinition.code == s["code"],
    ).first()
    if ex:
        print(f"  stage {s['code']} already exists")
    else:
        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            workflow_definition_id=defn.id,
            name=s["name"],
            code=s["code"],
            sequence=s["sequence"],
            weight=s["weight"],
            is_active=True,
        )
        db.add(stage)
        print(f"  Created stage: {s['code']} — {s['name']}")

db.commit()

# 3. Backfill existing OVERHAUL workflows — set workflow_code so they link to the definition
updated = 0
existing_workflows = db.query(RepairWorkflow).filter(
    RepairWorkflow.workflow_type == "OVERHAUL",
    RepairWorkflow.workflow_code == None,
).all()
for wf in existing_workflows:
    wf.workflow_code = "OVERHAUL"
    updated += 1

if updated:
    db.commit()
    print(f"Backfilled {updated} existing OVERHAUL workflow(s) with workflow_code='OVERHAUL'")

print(f"\nDone. Definition ID: {defn.id}")
