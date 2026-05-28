"""
Check surveillance test configuration.
"""
from database import VendorSessionLocal
from models import SurveillanceTestConfig, CategoryDetails, EquipmentType

db = VendorSessionLocal()

try:
    # Get all surveillance test configs
    configs = db.query(SurveillanceTestConfig).filter(
        SurveillanceTestConfig.is_active == True
    ).all()

    if not configs:
        print("\n[WARN] No surveillance test configs found!")
        print("       Run: seed_surveillance_config() to create them")
    else:
        print(f"\n[OK] Found {len(configs)} surveillance test configurations:\n")

        # Group by equipment type
        from collections import defaultdict
        by_equipment_type = defaultdict(list)

        for config in configs:
            # Get equipment type name
            eq_type = db.query(EquipmentType).filter(
                EquipmentType.id == config.equipment_type_id
            ).first()

            # Get test type name
            test_type = db.query(CategoryDetails).filter(
                CategoryDetails.id == config.test_type_id
            ).first()

            eq_type_name = eq_type.name if eq_type else f"Unknown ({config.equipment_type_id})"
            test_type_name = test_type.name if test_type else f"Unknown ({config.test_type_id})"

            by_equipment_type[eq_type_name].append({
                'test_name': test_type_name,
                'test_id': config.test_type_id,
                'priority': config.default_priority,
                'mandatory': config.is_mandatory
            })

        # Print grouped results
        for eq_type_name, tests in by_equipment_type.items():
            print(f"Equipment Type: {eq_type_name}")
            print(f"  Tests configured: {len(tests)}")
            for test in tests:
                mandatory = "[MANDATORY]" if test['mandatory'] else "[OPTIONAL]"
                print(f"    - {test['test_name']} (ID: {test['test_id']}) {mandatory} [Priority: {test['priority']}]")
            print()

finally:
    db.close()
