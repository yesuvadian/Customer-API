"""
Check if surveillance workflow definition and stages exist in database.
"""
from database import VendorSessionLocal
from models import RepairWorkflowDefinition, RepairStageDefinition

def check_surveillance_seed():
    db = VendorSessionLocal()
    try:
        # Check workflow definition
        wf_def = db.query(RepairWorkflowDefinition).filter(
            RepairWorkflowDefinition.workflow_code == 'SURVEILLANCE'
        ).first()

        if not wf_def:
            print("[ERROR] SURVEILLANCE workflow definition NOT FOUND!")
            print("        Run: python seed.py")
            return False

        print(f"[OK] SURVEILLANCE workflow definition exists: {wf_def.id}")
        print(f"     Name: {wf_def.name}")
        print(f"     Active: {wf_def.is_active}")

        # Check stages
        stages = db.query(RepairStageDefinition).filter(
            RepairStageDefinition.workflow_definition_id == wf_def.id
        ).order_by(RepairStageDefinition.sequence).all()

        print(f"\n[OK] Found {len(stages)} stages:")
        for stage in stages:
            print(f"     {stage.sequence}. {stage.name} (code: {stage.code}, duration: {stage.default_duration_days} days)")

        if len(stages) != 5:
            print(f"\n[WARN] Expected 5 stages, found {len(stages)}")
            print("       Run: python seed.py to fix")
            return False

        return True

    finally:
        db.close()

if __name__ == "__main__":
    result = check_surveillance_seed()
    if result:
        print("\n[SUCCESS] Surveillance workflow is properly seeded!")
    else:
        print("\n[FAILED] Surveillance workflow seed is incomplete or missing!")
