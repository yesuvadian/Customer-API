"""
Seed: Condition Monitoring Recommendations

Inserts score-band recommendation configs for ALL equipment types covering
test, maintenance, and inspection categories.

Score bands:
  0  – 30  : Critical  → Monthly   (most urgent, diagnostic tests)
  31 – 60  : High      → Quarterly (significant degradation, regular checks)
  61 – 80  : Medium    → Semi-Annual (moderate condition, routine monitoring)
  81 – 100 : Low       → Yearly    (healthy, standard preventive cycle)

Run once:
    python seed_condition_recommendations.py
"""
import sys
from sqlalchemy.orm import Session
from database import SessionLocal
from models import CategoryMaster, CategoryDetails, ConditionMonitoringRecommendation, ScheduleFrequency


# ── Score-band → frequency map ────────────────────────────────────────────────
BANDS = [
    (0,  30,  ScheduleFrequency.monthly,     1),   # Critical
    (31, 60,  ScheduleFrequency.quarterly,   2),   # High
    (61, 80,  ScheduleFrequency.semi_annual, 3),   # Medium
    (81, 100, ScheduleFrequency.yearly,      4),   # Low
]

# ── Equipment-type recommendation matrix ──────────────────────────────────────
# Format: equipment_type_name → {category_type → [test_name_per_band]}
# Each list has exactly 4 entries (one per score band: Critical, High, Medium, Low).
# Use None to skip a band.
RECOMMENDATION_MATRIX = {
    "Power Transformer": {
        "test": [
            "Transformer Oil Test",                              # 0-30  Critical
            "Capacitance & Tan Delta Test (Transformer)",        # 31-60 High
            "Transformer Physical Inspection",                   # 61-80 Medium
            "Sweep Frequency Response Analysis (SFRA) — Routine",# 81-100 Low
        ],
        "maintenance": [
            "Power Transformer Major Maintenance",               # 0-30
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "OLTC Operations Count",                             # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "Fire Safety",                                       # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Circuit Breaker": {
        "test": [
            "Contact Resistance Test",                           # 0-30
            "Insulation Resistance Test",                        # 31-60
            "Travel and Timing Test",                            # 61-80
            "Minimum Trip Voltage Test",                         # 81-100
        ],
        "maintenance": [
            "Circuit Breaker Major Maintenance",                 # 0-30
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Circuit Breaker Operations Count",                  # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "Fire Safety",                                       # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Current Transformer": {
        "test": [
            "Capacitance & Tan Delta Test (CT)",                 # 0-30
            "CT Insulation Test",                                # 31-60
            "CT Ratio Test (Detailed)",                          # 61-80
            "CT Ratio Test",                                     # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30  (no separate major)
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "Fire Safety",                                       # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Potential Transformer": {
        "test": [
            "Tan Delta Test",                                    # 0-30
            "Insulation Resistance Test",                        # 31-60
            "Ratio Test",                                        # 61-80
            "Polarity Test",                                     # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60 (no Fire Safety for PT in DB)
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Capacitor Voltage Transformer": {
        "test": [
            "CVT Test Report",                                   # 0-30
            "CVT Test Report",                                   # 31-60
            "CVT Test Report",                                   # 61-80
            "CVT Test Report",                                   # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "Fire Safety",                                       # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Surge Arrestor": {
        "test": [
            "V-I Characteristic Test",                           # 0-30
            "Insulation Resistance / Leakage Current Test",      # 31-60
            "Insulation Resistance / Leakage Current Test",      # 61-80
            "Power Frequency Voltage Withstand Test",            # 81-100
        ],
        "maintenance": [
            "LA Major Maintenance",                              # 0-30
            "Routine Visual Inspection",                         # 31-60
            "Routine Visual Inspection",                         # 61-80
            "Routine Visual Inspection",                         # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Isolator / Disconnector": {
        "test": [
            "Insulation Resistance Test",                        # 0-30
            "Insulation Resistance Test",                        # 31-60
            "Contact Resistance Test",                           # 61-80
            "Contact Resistance Test",                           # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Control & Relay Panel": {
        "test": [
            "Relay Functional Test",                             # 0-30
            "Control Circuit Test",                              # 31-60
            "Interlocking Test",                                 # 61-80
            "Indication Test",                                   # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30
            "Contact Cleaning",                                  # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Battery Set": {
        "test": [
            "Discharge / Capacity Test",                         # 0-30
            "Specific Gravity Check",                            # 31-60
            "Float Voltage per Cell",                            # 61-80
            "Terminal Voltage Measurement",                      # 81-100
        ],
        "maintenance": [
            "Battery Bank Major Maintenance",                    # 0-30
            "Routine Battery Maintenance",                       # 31-60
            "Routine Battery Maintenance",                       # 61-80
            "Routine Battery Maintenance",                       # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "Environmental",                                     # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Battery Charger": {
        "test": [
            "Ripple Voltage Test",                               # 0-30
            "Output Voltage Test",                               # 31-60
            "Float Charge Test",                                 # 61-80
            "Output Current Test",                               # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30
            "Contact Cleaning",                                  # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Wave Trap": {
        "test": [
            "Resonance Frequency Test",                          # 0-30
            "Insulation Resistance Test",                        # 31-60
            "Capacitance Test",                                  # 61-80
            "Inductance Test",                                   # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Station Auxiliary Transformer": {
        "test": [
            "Tan Delta Test",                                    # 0-30
            "Insulation Resistance Test",                        # 31-60
            "Ratio Test",                                        # 61-80
            "Winding Resistance Test",                           # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60 (no Fire Safety for SAT in DB)
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "LTAC Panel": {
        "test": [
            "Control Circuit Test",                              # 0-30
            "Metering Test",                                     # 31-60
            "Indication Test",                                   # 61-80
            "Indication Test",                                   # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Fire Fighting System": {
        "test": [
            "Alarm System Test",                                 # 0-30
            "Pressure Test",                                     # 31-60
            "Flow Test",                                         # 61-80
            "Sprinkler System Test",                             # 81-100
        ],
        "maintenance": [
            "Pump Maintenance",                                  # 0-30
            "Valve Maintenance",                                 # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60 (no Fire Safety for FFS in DB)
            "Environmental",                                     # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "PLCC Panel": {
        "test": [
            "Communication Test",                                # 0-30
            "Logic Test",                                        # 31-60
            "Interface Test",                                    # 61-80
            "Communication Test",                                # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Digital Communication Panel": {
        "test": [
            "Communication Link Test",                           # 0-30
            "Signal Quality Test",                               # 31-60
            "Network Connectivity Test",                         # 61-80
            "Communication Link Test",                           # 81-100
        ],
        "maintenance": [
            "Routine Preventive Maintenance",                    # 0-30
            "Routine Preventive Maintenance",                    # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Protection Relay": {
        "test": [
            "Protection Relay Functional Test",                  # 0-30
            "Relay Testing",                                     # 31-60
            "Protection Relay Functional Test",                  # 61-80
            "Relay Testing",                                     # 81-100
        ],
        "maintenance": [
            "Protection Relay Calibration and History",          # 0-30
            "Protection Relay Calibration and History",          # 31-60
            "Protection Relay Calibration and History",          # 61-80
            "Protection Relay Calibration and History",          # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Electronic Tri-vector Meter": {
        "test": [
            "Meter Testing",                                     # 0-30
            "Meter Testing",                                     # 31-60
            "Meter Testing",                                     # 61-80
            "Meter Testing",                                     # 81-100
        ],
        "maintenance": [
            "Electronic Tri-vector Meter Calibration",          # 0-30
            "Electronic Tri-vector Meter Calibration",          # 31-60
            "Electronic Tri-vector Meter Calibration",          # 61-80
            "Electronic Tri-vector Meter Calibration",          # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "General Maintenance",                               # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
    "Diesel Generator Set": {
        "test": [
            "Load Test",                                         # 0-30
            "Battery and Starting System Test",                  # 31-60
            "Voltage and Frequency Test",                        # 61-80
            "Fuel System Test",                                  # 81-100
        ],
        "maintenance": [
            "Engine Oil Change",                                 # 0-30
            "Fuel Filter Replacement",                           # 31-60
            "Routine Preventive Maintenance",                    # 61-80
            "Routine Preventive Maintenance",                    # 81-100
        ],
        "inspection": [
            "Electrical Safety",                                 # 0-30
            "Environmental",                                     # 31-60
            "General Maintenance",                               # 61-80
            "Documentation",                                     # 81-100
        ],
    },
}


# ── Seed function ─────────────────────────────────────────────────────────────

def run(db: Session) -> None:
    inserted = 0
    skipped  = 0

    for eq_type_name, categories in RECOMMENDATION_MATRIX.items():
        # Resolve equipment type
        master = db.query(CategoryMaster).filter_by(name=eq_type_name).first()
        if not master:
            print(f"[SKIP] CategoryMaster '{eq_type_name}' not found in DB — skipping")
            continue

        for category_type, test_names_by_band in categories.items():
            for band_idx, (score_from, score_to, frequency, display_order) in enumerate(BANDS):
                test_name = test_names_by_band[band_idx] if band_idx < len(test_names_by_band) else None
                if not test_name:
                    continue

                # Resolve test type scoped to this equipment type's CategoryMaster
                detail = (
                    db.query(CategoryDetails)
                    .filter(
                        CategoryDetails.name == test_name,
                        CategoryDetails.category_master_id == master.id,
                        CategoryDetails.is_active == True,
                    )
                    .first()
                )
                if not detail:
                    print(f"  [SKIP] CategoryDetails '{test_name}' not found — skipping")
                    continue

                # Idempotency: skip if this exact combo already exists
                existing = db.query(ConditionMonitoringRecommendation).filter_by(
                    equipment_type_id = master.id,
                    test_type_id      = detail.id,
                    score_from        = score_from,
                    score_to          = score_to,
                ).first()

                if existing:
                    skipped += 1
                    continue

                db.add(ConditionMonitoringRecommendation(
                    equipment_type_id = master.id,
                    score_from        = score_from,
                    score_to          = score_to,
                    test_type_id      = detail.id,
                    frequency         = frequency,
                    is_active         = True,
                    display_order     = display_order,
                ))
                inserted += 1

        db.flush()

    db.commit()
    print(f"\n[OK] Condition monitoring recommendations seeded: "
          f"{inserted} inserted, {skipped} already existed")


if __name__ == "__main__":
    db = SessionLocal()
    try:
        # Ensure CategoryDetails rows exist before running recommendations
        from seed import seed_category_master, seed_category_details, seed_test_type_categories
        master_ids = seed_category_master(db)
        seed_category_details(db, master_ids)
        seed_test_type_categories(db, master_ids)
        db.commit()
        run(db)
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        import traceback; traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()
