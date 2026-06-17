"""Quick seed: kit mappings for Power Transformer (id=12) — test only."""
from database import SessionLocal
from models import EquipmentTypeKitMapping

db = SessionLocal()

mappings = [
    {"equipment_type_id": 12, "kit_type_id": 324, "is_required": True,  "notes": "Winding insulation check"},
    {"equipment_type_id": 12, "kit_type_id": 325, "is_required": True,  "notes": "Oil dielectric strength"},
    {"equipment_type_id": 12, "kit_type_id": 329, "is_required": True,  "notes": "Load & loss measurement"},
    {"equipment_type_id": 12, "kit_type_id": 331, "is_required": False, "notes": "Hot-spot thermal scan"},
]

added = 0
for m in mappings:
    exists = db.query(EquipmentTypeKitMapping).filter_by(
        equipment_type_id=m["equipment_type_id"],
        kit_type_id=m["kit_type_id"],
    ).first()
    if not exists:
        db.add(EquipmentTypeKitMapping(**m))
        added += 1
        print(f"[ADD] kit_type_id={m['kit_type_id']} is_required={m['is_required']}")
    else:
        print(f"[SKIP] kit_type_id={m['kit_type_id']} already mapped")

db.commit()
print(f"Done. Added {added} mapping(s).")
db.close()
