#!/usr/bin/env python3
"""
One-time setup: create the equipment_criticality_mappings table (via the
EquipmentCriticalityMapping model in models.py) and seed it with a starting
default per equipment type — a structural proxy (equipment type, and a
voltage-class bump) standing in for a full manual classification, per
KPTCL spec §12.5's Condition Risk Matrix.

This is a STARTING DEFAULT, not a KPTCL-confirmed classification — every
value here is editable afterward directly in the
equipment_criticality_mappings table (an admin CRUD UI for it is a
follow-up, not part of this script). Re-running this script is safe: it
only inserts rows that don't already exist for a given
(equipment_type_id, voltage_class) pair, so manual edits already made are
never overwritten.

Usage:
    python alter_equipment_criticality_mapping.py
"""
from database import VendorSessionLocal
from models import Base, CategoryMaster, EquipmentCriticalityMapping

# Type-level defaults (voltage_class = NULL, applies at any voltage).
# Judgment calls, pending KPTCL review — see module docstring.
TYPE_DEFAULTS = {
    "Power Transformer":            "Critical",
    "Station Auxiliary Transformer": "High",
    "Circuit Breaker":              "High",
    "Fire Fighting System":         "High",   # safety-critical, not power-delivery-critical
    "Current Transformer":          "Medium",
    "Potential Transformer":        "Medium",
    "Capacitor Voltage Transformer": "Medium",
    "Protection Relay":             "Medium",
    "Surge Arrestor":               "Medium",
    "Control & Relay Panel":        "Medium",
    "Battery Set":                  "Medium",
    "Battery Charger":              "Medium",
    "Diesel Generator Set":         "Medium",
    "Isolator / Disconnector":      "Low",
    "Wave Trap":                    "Low",
    "LTAC Panel":                   "Low",
    "PLCC Panel":                   "Low",
    "Digital Communication Panel":  "Low",
    "Electronic Tri-vector Meter":  "Low",
}

# Voltage-class bump: for these (equipment_type, voltage_class) pairs,
# override the type default with a higher tier — 220kV+ generally raises
# the consequence of failure by one tier for instrument transformers.
VOLTAGE_OVERRIDES = {
    ("Current Transformer", "220kV"): "High",
    ("Current Transformer", "400kV"): "High",
    ("Potential Transformer", "220kV"): "High",
    ("Potential Transformer", "400kV"): "High",
    ("Capacitor Voltage Transformer", "220kV"): "High",
    ("Capacitor Voltage Transformer", "400kV"): "High",
}


def main():
    Base.metadata.create_all(
        bind=VendorSessionLocal().get_bind(),
        tables=[EquipmentCriticalityMapping.__table__],
    )
    print("Ensured equipment_criticality_mappings table exists.")

    db = VendorSessionLocal()
    try:
        types = {c.name: c.id for c in db.query(CategoryMaster).all()}

        inserted, skipped, missing = 0, 0, []

        def _upsert(type_name, voltage_class, criticality):
            nonlocal inserted, skipped
            type_id = types.get(type_name)
            if type_id is None:
                missing.append(type_name)
                return
            exists = (
                db.query(EquipmentCriticalityMapping)
                .filter(
                    EquipmentCriticalityMapping.equipment_type_id == type_id,
                    EquipmentCriticalityMapping.voltage_class == voltage_class,
                )
                .first()
            )
            if exists:
                skipped += 1
                return
            db.add(EquipmentCriticalityMapping(
                equipment_type_id=type_id,
                voltage_class=voltage_class,
                criticality=criticality,
                notes="Seeded starting default — pending KPTCL review.",
            ))
            inserted += 1

        for type_name, criticality in TYPE_DEFAULTS.items():
            _upsert(type_name, None, criticality)

        for (type_name, voltage_class), criticality in VOLTAGE_OVERRIDES.items():
            _upsert(type_name, voltage_class, criticality)

        db.commit()
        print(f"Inserted {inserted} mapping row(s), skipped {skipped} already present.")
        if missing:
            print(f"WARNING: equipment type(s) not found in CategoryMaster, skipped: {sorted(set(missing))}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
