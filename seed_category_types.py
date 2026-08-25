"""
Seed script — set CategoryDetails.category_type based on test type name.

Maps each CategoryDetails name to its bucket:
  test        — measurement / electrical tests
  maintenance — preventive / major maintenance
  inspection  — visual / safety / documentation inspections
  repair      — repair lifecycle work orders

Safe to run multiple times (idempotent).
"""

from __future__ import annotations
import logging
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

# name → category_type
CATEGORY_TYPE_MAP: dict[str, str] = {
    # ── Test ────────────────────────────────────────────────────────────────
    "Protection Relay Functional Test":                     "test",
    "Insulation Resistance (IR) Test":                      "test",
    "CT Ratio Test":                                        "test",
    "Core Insulation Test":                                 "test",
    "Meter Testing":                                        "test",
    "Relay Testing":                                        "test",
    "Ratio Test HV-IV":                                     "test",
    "Ratio Test HV-LV":                                     "test",
    "Short Circuit Test HV-IV":                             "test",
    "Short Circuit Test HV-LV":                             "test",
    "Magnetic Balance Test HV":                             "test",
    "Magnetic Balance Test IV":                             "test",
    "Magnetic Balance Test LV":                             "test",
    "Open Circuit Test HV-IV (1Ph)":                        "test",
    "Open Circuit Test HV-IV (3Ph)":                        "test",
    "Open Circuit Test HV-LV (1Ph)":                        "test",
    "Open Circuit Test HV-LV (3Ph)":                        "test",
    "Open Circuit Test IV-LV (1Ph)":                        "test",
    "Open Circuit Test IV-LV (3Ph)":                        "test",
    "Capacitance & Tan Delta Test (Transformer)":           "test",
    "Capacitance & Tan Delta Comparison":                   "test",
    "CT Insulation Test":                                   "test",
    "CT Ratio Test (Detailed)":                             "test",
    "Capacitance & Tan Delta Test (CT)":                    "test",
    "Tan Delta NCT Test":                                   "test",
    "CVT Test Report":                                      "test",
    "Dielectric Frequency Response (DFR / IDAX)":           "test",
    "DFR / IDAX":                                           "test",
    "Tan-Delta, Capacitance & Insulation Diagnostics":      "test",
    "Winding Resistance Measurement":                 "test",
    "220kV Bushing Tan-Delta Test":                         "test",
    "66kV Bushing Tan-Delta Test":                          "test",
    "Insulation Diagnostics (IDAX)":                        "test",
    "Sweep Frequency Response Analysis (SFRA)":             "test",
    "SFRA":                                                 "test",
    "Dielectric Frequency Response (DFR) — Routine":        "test",
    "Sweep Frequency Response Analysis (SFRA) — Routine":   "test",
    "Transformer Oil Test":                                 "test",
    "Insulating Oil Test":                                  "test",
    "Oil BDV Test":                                         "test",
    "Transformer Dissolved Gas Analysis (DGA)":             "test",
    "Dissolved Gas Analysis":                               "test",
    "DGA Test":                                             "test",
    "Protection Relay Calibration and History":             "test",
    "Electronic Tri-vector Meter Calibration":              "test",
    "Circuit Breaker Operations Count":                     "test",
    "OLTC Operations Count":                                "test",
    "Contact Resistance Test":                              "test",
    "Insulation Resistance Test":                           "test",
    "SF6 Gas Pressure Test":                                "test",
    "SF6 Gas Purity Test":                                  "test",
    "Travel and Timing Test":                               "test",
    "Minimum Trip Voltage Test":                            "test",
    "Insulation Resistance / Leakage Current Test":         "test",
    "V-I Characteristic Test":                              "test",
    "Power Frequency Voltage Withstand Test":               "test",
    "Specific Gravity Check":                               "test",
    "Float Voltage per Cell":                               "test",
    "Discharge / Capacity Test":                            "test",
    "Electrolyte Level Check":                              "test",
    "Terminal Voltage Measurement":                         "test",
    "Transformer Physical Inspection":                      "test",
    "Power Transformer Nameplate Details":                  "test",

    # ── Maintenance ─────────────────────────────────────────────────────────
    "Routine Preventive Maintenance":                       "maintenance",
    "Power Transformer Major Maintenance":                  "maintenance",
    "Circuit Breaker Major Maintenance":                    "maintenance",
    "Routine Battery Maintenance":                          "maintenance",
    "Battery Bank Major Maintenance":                       "maintenance",
    "Routine Visual Inspection":                            "maintenance",
    "LA Major Maintenance":                                 "maintenance",

    # ── Inspection ───────────────────────────────────────────────────────────
    "Electrical Safety":                                    "inspection",
    "Civil":                                                "inspection",
    "Fire Safety":                                          "inspection",
    "Documentation":                                        "inspection",
    "Environmental":                                        "inspection",
    "General Maintenance":                                  "inspection",
    "Electrical Safety Audit":                              "inspection",
    "Environmental Audit":                                  "inspection",
    "Fire Safety Audit":                                    "inspection",
    "Contact Cleaning":                                     "inspection",
}


def seed_category_types(session: Session) -> None:
    """Set category_type on CategoryDetails rows. Idempotent."""
    from models import CategoryDetails

    updated = 0
    for name, ctype in CATEGORY_TYPE_MAP.items():
        rows = session.query(CategoryDetails).filter(CategoryDetails.name == name).all()
        for row in rows:
            if row.category_type != ctype:
                row.category_type = ctype
                updated += 1

    session.commit()
    log.info(f"[seed_category_types] Updated {updated} CategoryDetails rows.")
    print(f"[OK] seed_category_types: {updated} rows updated.")


if __name__ == "__main__":
    from database import SessionLocal
    db = SessionLocal()
    try:
        seed_category_types(db)
    finally:
        db.close()
