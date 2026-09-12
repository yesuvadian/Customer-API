from database import SessionLocal
from models import OrgTestTemplate, CategoryDetails, CategoryMaster

db = SessionLocal()

POWER_TRANSFORMER_NAMES = [
    "220kV Bushing Tan-Delta Test", "66kV Bushing Tan-Delta Test",
    "Capacitance & Tan Delta Comparison", "Insulation Diagnostics (IDAX)",
    "Magnetic Balance Test HV", "Magnetic Balance Test IV", "Magnetic Balance Test LV",
    "Open Circuit Test HV-IV (1Ph)", "Open Circuit Test HV-IV (3Ph)",
    "Open Circuit Test IV-LV (1Ph)", "Open Circuit Test IV-LV (3Ph)",
    "Power Transformer Nameplate Details", "Ratio Test HV-IV", "Ratio Test HV-LV",
    "Short Circuit Test HV-IV", "Tan-Delta, Capacitance & Insulation Diagnostics",
    "Transformer Physical Inspection",
]

pt_master = db.query(CategoryMaster).filter_by(name="Power Transformer").first()
for name in POWER_TRANSFORMER_NAMES:
    cd = db.query(CategoryDetails).filter_by(category_master_id=pt_master.id, name=name).first()
    if cd and not cd.is_active:
        cd.is_active = True
        print("activated:", name)
    elif cd:
        print("already active:", name)
    else:
        print("NOT FOUND:", name)

LINK_AND_ACTIVATE = [
    ("transformer_ttr_test", "Transformer Turns Ratio (TTR)", "Power Transformer"),
    ("oltc_drm_test", "OLTC Dynamic Resistance Measurement (DRM)", "Power Transformer"),
    ("potential_transformer_test", "Potential Transformer Test", "Potential Transformer"),
    ("potential_transformer_maintenance", "Potential Transformer Preventive Maintenance", "Potential Transformer"),
    ("battery_charger_test", "Battery Charger Output & Ripple Test", "Battery Charger"),
    ("battery_charger_maintenance", "Battery Charger Preventive Maintenance", "Battery Charger"),
    ("ltac_panel_test", "LTAC Panel Tuning & Insertion Loss Test", "LTAC Panel"),
    ("ltac_panel_maintenance", "LTAC Panel Preventive Maintenance", "LTAC Panel"),
    ("plcc_panel_test", "PLCC Panel Carrier & Signal Test", "PLCC Panel"),
    ("plcc_panel_maintenance", "PLCC Panel Preventive Maintenance", "PLCC Panel"),
    ("comm_panel_test", "Digital Communication Panel Functional Test", "Digital Communication Panel"),
    ("comm_panel_maintenance", "Digital Communication Panel Preventive Maintenance", "Digital Communication Panel"),
]
for template_key, cd_name, master_name in LINK_AND_ACTIVATE:
    m = db.query(CategoryMaster).filter_by(name=master_name).first()
    if not m:
        print("NOT FOUND master:", master_name)
        continue
    cd = db.query(CategoryDetails).filter_by(category_master_id=m.id, name=cd_name).first()
    t = db.query(OrgTestTemplate).filter(OrgTestTemplate.org_id.is_(None), OrgTestTemplate.template_key==template_key).first()
    if not cd or not t:
        print("NOT FOUND:", template_key)
        continue
    t.template_data["is_active"] = True
    t.test_type_id = cd.id
    cd.is_active = True
    print("activated:", cd_name)

pd_t = db.query(OrgTestTemplate).filter(OrgTestTemplate.org_id.is_(None), OrgTestTemplate.template_key=="partial_discharge_test").first()
if pd_t:
    pt_cd = db.query(CategoryDetails).filter_by(category_master_id=pt_master.id, name="Partial Discharge Measurement").first()
    pd_t.template_data["is_active"] = True
    pd_t.test_type_id = pt_cd.id
    for master_name in ["Power Transformer", "Current Transformer", "Potential Transformer", "Capacitor Voltage Transformer"]:
        m = db.query(CategoryMaster).filter_by(name=master_name).first()
        cd = db.query(CategoryDetails).filter_by(category_master_id=m.id, name="Partial Discharge Measurement").first()
        if cd:
            cd.is_active = True
            print("activated:", master_name, "- Partial Discharge Measurement")

db.commit()
db.close()
print("Done.")