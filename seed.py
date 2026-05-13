from contextlib import contextmanager
from datetime import datetime, timedelta
import uuid
import pandas as pd
from typing import Dict, Optional
from requests import session
from sqlalchemy import text
from database import VendorSessionLocal, Base, vendor_engine
from models import (
    CategoryDetails, CategoryMaster, Country, Division, OrgTestTemplate, Plan, Product,
    ProductCategory, ProductSubCategory, RepairStageDefinition, RepairStageRole, RepairStageTemplate, RepairStageTransition, Role, RoleModulePrivilege,
    State, City, User, UserRole, Module,
    # Organization models
    Organization, OrgDepartment, OrgRole, OrgUserRole,
    OrgRolePermission, RoleTemplate, OrgInvitation, TesterRoleModuleRequirement,
    ZohoImportMapping, Equipment, EquipmentStatus,
    # Reporting Suite
    ReportDefinition,
    # Repair Workflow
    RepairStageDefinition, RepairStageTemplate, RepairStageRole,
    RepairStageTransition, OrgTestTemplate,
    # Notification config tables
    NotificationEventCatalogue, NotificationRoutingRule, NotificationScheduleRule,
)
from security_utils import get_password_hash  # password hashing utils

# Context manager for DB session
@contextmanager
def get_db_session():
    session = VendorSessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Nameplate field-entry templates for 19 KPTCL substation equipment types.
# Seeded into OrgTestTemplate (is_system=True, org_id=NULL) once at startup.
# After seeding the DB row is the live source — this dict is seed-only.
# ---------------------------------------------------------------------------

NAMEPLATE_TEMPLATES = {

    # ── 1. Power Transformer ─────────────────────────────────────────────────
    "nameplate_power_transformer": {
        "name": "Power Transformer",
        "equipment_type": "Power Transformer",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",  "label": "Substation Name",  "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",        "label": "Bay Number",        "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",     "label": "Voltage Class",     "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                ]
            },
            {
                "title": "Manufacturer Details",
                "fields": [
                    {"key": "manufacturer_name",    "label": "Manufacturer Name",     "type": "text",   "required": True,  "read_only": False},
                    {"key": "country_of_origin",    "label": "Country of Origin",     "type": "text",   "required": False, "read_only": False},
                    {"key": "year_of_manufacture",  "label": "Year of Manufacture",   "type": "number", "required": True,  "read_only": False},
                    {"key": "factory_serial_number","label": "Factory Serial Number", "type": "text",   "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Transformer Type & Cooling",
                "fields": [
                    {"key": "type",           "label": "Transformer Type", "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["Auto", "Two-Winding", "Three-Winding"]},
                    {"key": "cooling_class",  "label": "Cooling Class",    "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["ONAN", "ONAF", "ODAF", "OFAF"]},
                    {"key": "rated_mva_onan", "label": "Rated MVA (ONAN)", "type": "number",   "required": True,  "read_only": False, "unit": "MVA"},
                    {"key": "rated_mva_onaf", "label": "Rated MVA (ONAF)", "type": "number",   "required": False, "read_only": False, "unit": "MVA"},
                    {"key": "rated_mva_odaf", "label": "Rated MVA (ODAF)", "type": "number",   "required": False, "read_only": False, "unit": "MVA"},
                ]
            },
            {
                "title": "Voltage & Current Ratings",
                "fields": [
                    {"key": "hv_voltage",  "label": "HV Voltage",  "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "mv_voltage",  "label": "MV Voltage",  "type": "number", "required": False, "read_only": False, "unit": "kV"},
                    {"key": "lv_voltage",  "label": "LV Voltage",  "type": "number", "required": False, "read_only": False, "unit": "kV"},
                    {"key": "hv_current",  "label": "HV Current",  "type": "number", "required": True,  "read_only": False, "unit": "A"},
                    {"key": "mv_current",  "label": "MV Current",  "type": "number", "required": False, "read_only": False, "unit": "A"},
                    {"key": "lv_current",  "label": "LV Current",  "type": "number", "required": False, "read_only": False, "unit": "A"},
                ]
            },
            {
                "title": "Electrical Characteristics",
                "fields": [
                    {"key": "vector_group",          "label": "Vector Group",      "type": "text",   "required": True,  "read_only": False},
                    {"key": "impedance_voltage_pct", "label": "Impedance Voltage", "type": "number", "required": True,  "read_only": False, "unit": "%"},
                    {"key": "no_load_loss",          "label": "No-Load Loss",      "type": "number", "required": False, "read_only": False, "unit": "kW"},
                    {"key": "full_load_loss",        "label": "Full-Load Loss",    "type": "number", "required": False, "read_only": False, "unit": "kW"},
                ]
            },
            {
                "title": "OLTC Details",
                "fields": [
                    {"key": "oltc_make",          "label": "OLTC Make",          "type": "text",     "required": False, "read_only": False},
                    {"key": "oltc_type",          "label": "OLTC Type",          "type": "text",     "required": False, "read_only": False},
                    {"key": "oltc_rated_current", "label": "OLTC Rated Current", "type": "number",   "required": False, "read_only": False, "unit": "A"},
                    {"key": "oltc_positions",     "label": "OLTC Positions",     "type": "number",   "required": False, "read_only": False},
                    {"key": "oltc_drive_type",    "label": "OLTC Drive Type",    "type": "dropdown", "required": False, "read_only": False,
                     "options": ["Motor", "Manual"]},
                ]
            },
            {
                "title": "Insulating Oil",
                "fields": [
                    {"key": "oil_type",                  "label": "Oil Type",           "type": "dropdown", "required": False, "read_only": False,
                     "options": ["Mineral Oil", "Synthetic Ester", "Natural Ester"]},
                    {"key": "oil_volume_litres",         "label": "Oil Volume",         "type": "number",   "required": False, "read_only": False, "unit": "L"},
                    {"key": "conservator_volume_litres", "label": "Conservator Volume", "type": "number",   "required": False, "read_only": False, "unit": "L"},
                ]
            },
            {
                "title": "Commissioning & Procurement",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date",     "required": True,  "read_only": False},
                    {"key": "po_number",             "label": "PO Number",             "type": "text",     "required": False, "read_only": False},
                    {"key": "contract_number",       "label": "Contract Number",       "type": "text",     "required": False, "read_only": False},
                    {"key": "vendor_ranking",        "label": "Vendor Ranking",        "type": "dropdown", "required": False, "read_only": False,
                     "options": ["1", "2", "3", "4", "5"]},
                    {"key": "warranty_expiry_date",  "label": "Warranty Expiry Date",  "type": "date",     "required": False, "read_only": False},
                    {"key": "insurance_details",     "label": "Insurance Details",     "type": "textarea", "required": False, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "sld_bay",          "label": "SLD of Bay",              "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 2. Circuit Breaker ───────────────────────────────────────────────────
    "nameplate_circuit_breaker": {
        "name": "Circuit Breaker",
        "equipment_type": "Circuit Breaker",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",          "label": "Bay Number",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",       "label": "Voltage Class",       "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Ratings",
                "fields": [
                    {"key": "type",                   "label": "Breaker Type",            "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["SF6", "Vacuum", "Oil", "Air Blast"]},
                    {"key": "number_of_poles",        "label": "Number of Poles",         "type": "number",   "required": True,  "read_only": False},
                    {"key": "rated_voltage",          "label": "Rated Voltage",           "type": "number",   "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "rated_current",          "label": "Rated Current",           "type": "number",   "required": True,  "read_only": False, "unit": "A"},
                    {"key": "rated_breaking_current", "label": "Rated Breaking Current",  "type": "number",   "required": True,  "read_only": False, "unit": "kA rms"},
                    {"key": "rated_making_current",   "label": "Rated Making Current",    "type": "number",   "required": False, "read_only": False, "unit": "kA peak"},
                    {"key": "short_circuit_duration", "label": "Short-Circuit Duration",  "type": "number",   "required": False, "read_only": False, "unit": "s"},
                ]
            },
            {
                "title": "Operating Mechanism",
                "fields": [
                    {"key": "mechanism_type",  "label": "Mechanism Type",  "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["Spring", "Hydraulic", "Pneumatic"]},
                    {"key": "mechanism_make",  "label": "Mechanism Make",  "type": "text",     "required": False, "read_only": False},
                    {"key": "mechanism_model", "label": "Mechanism Model", "type": "text",     "required": False, "read_only": False},
                ]
            },
            {
                "title": "SF6 Gas Details",
                "fields": [
                    {"key": "sf6_rated_pressure",      "label": "SF6 Rated Pressure",      "type": "number", "required": False, "read_only": False, "unit": "bar"},
                    {"key": "sf6_alarm_pressure",      "label": "SF6 Alarm Pressure",      "type": "number", "required": False, "read_only": False, "unit": "bar"},
                    {"key": "sf6_gas_weight_per_pole", "label": "SF6 Gas Weight per Pole", "type": "number", "required": False, "read_only": False, "unit": "kg"},
                ]
            },
            {
                "title": "Contacts & Coils",
                "fields": [
                    {"key": "close_coils_count",  "label": "Close Coils (Count)",  "type": "number", "required": False, "read_only": False},
                    {"key": "trip_coils_count",   "label": "Trip Coils (Count)",   "type": "number", "required": False, "read_only": False},
                    {"key": "aux_contact_config", "label": "Aux Contact Config",   "type": "text",   "required": False, "read_only": False},
                    {"key": "contact_travel",     "label": "Contact Travel",       "type": "number", "required": False, "read_only": False, "unit": "mm"},
                    {"key": "min_trip_current",   "label": "Minimum Trip Current", "type": "number", "required": False, "read_only": False, "unit": "A"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning",               "label": "Date of Commissioning",               "type": "date",   "required": True,  "read_only": False},
                    {"key": "operations_counter_at_commissioning", "label": "Operations Counter at Commissioning", "type": "number", "required": False, "read_only": False, "default": 0},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 3. Current Transformer ───────────────────────────────────────────────
    "nameplate_current_transformer": {
        "name": "Current Transformer",
        "equipment_type": "Current Transformer",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",          "label": "Bay Number",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",       "label": "Voltage Class",       "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Ratings",
                "fields": [
                    {"key": "type",                  "label": "Type",                  "type": "dropdown", "required": True,  "read_only": False, "options": ["AIS", "GIS"]},
                    {"key": "rated_voltage",         "label": "Rated Voltage",         "type": "number",   "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "rated_current",         "label": "Rated Current",         "type": "number",   "required": True,  "read_only": False, "unit": "A"},
                    {"key": "burden_va",             "label": "Burden",                "type": "number",   "required": False, "read_only": False, "unit": "VA"},
                    {"key": "accuracy_class",        "label": "Accuracy Class",        "type": "text",     "required": False, "read_only": False},
                    {"key": "short_circuit_current", "label": "Short-Circuit Current", "type": "number",   "required": False, "read_only": False, "unit": "kA"},
                    {"key": "ct_ratio",              "label": "CT Ratio",              "type": "text",     "required": False, "read_only": False, "placeholder": "e.g. 200/1"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True,  "read_only": False},
                    {"key": "po_number",             "label": "PO Number",             "type": "text", "required": False, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 4. Potential Transformer ─────────────────────────────────────────────
    "nameplate_potential_transformer": {
        "name": "Potential Transformer",
        "equipment_type": "Potential Transformer",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",          "label": "Bay Number",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",       "label": "Voltage Class",       "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Ratings",
                "fields": [
                    {"key": "type",             "label": "Type",             "type": "dropdown", "required": True,  "read_only": False, "options": ["AIS", "GIS"]},
                    {"key": "rated_voltage_hv", "label": "Rated HV Voltage", "type": "number",   "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "rated_voltage_lv", "label": "Rated LV Voltage", "type": "number",   "required": True,  "read_only": False, "unit": "V"},
                    {"key": "burden_va",        "label": "Burden",           "type": "number",   "required": False, "read_only": False, "unit": "VA"},
                    {"key": "accuracy_class",   "label": "Accuracy Class",   "type": "text",     "required": False, "read_only": False},
                    {"key": "pt_ratio",         "label": "PT Ratio",         "type": "text",     "required": False, "read_only": False, "placeholder": "e.g. 11000/110"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 5. Capacitor Voltage Transformer ────────────────────────────────────
    "nameplate_capacitor_voltage_transformer": {
        "name": "Capacitor Voltage Transformer",
        "equipment_type": "Capacitor Voltage Transformer",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",          "label": "Bay Number",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",       "label": "Voltage Class",       "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Ratings",
                "fields": [
                    {"key": "system_voltage",               "label": "System Voltage",               "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "electromagnetic_unit_voltage", "label": "Electromagnetic Unit Voltage", "type": "number", "required": False, "read_only": False, "unit": "kV"},
                    {"key": "capacitor_stack",              "label": "Capacitor Stack",              "type": "text",   "required": False, "read_only": False},
                    {"key": "burden_va",                    "label": "Burden",                       "type": "number", "required": False, "read_only": False, "unit": "VA"},
                    {"key": "accuracy_class",               "label": "Accuracy Class",               "type": "text",   "required": False, "read_only": False},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 6. Surge Arrestor ───────────────────────────────────────────────────
    "nameplate_surge_arrestor": {
        "name": "Surge Arrestor",
        "equipment_type": "Surge Arrestor",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",          "label": "Bay Number",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",       "label": "Voltage Class",       "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Ratings",
                "fields": [
                    {"key": "type",                        "label": "Type",                         "type": "dropdown", "required": True,  "read_only": False, "options": ["AIS", "GIS"]},
                    {"key": "rated_voltage",               "label": "Rated Voltage",                "type": "number",   "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "continuous_operating_voltage","label": "Continuous Operating Voltage", "type": "number",   "required": False, "read_only": False, "unit": "kV"},
                    {"key": "energy_capability",           "label": "Energy Capability",            "type": "number",   "required": False, "read_only": False, "unit": "kJ"},
                    {"key": "discharge_current",           "label": "Discharge Current",            "type": "number",   "required": False, "read_only": False, "unit": "kA"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 7. Isolator / Disconnector ───────────────────────────────────────────
    "nameplate_isolator": {
        "name": "Isolator / Disconnector",
        "equipment_type": "Isolator / Disconnector",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",          "label": "Bay Number",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",       "label": "Voltage Class",       "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Ratings",
                "fields": [
                    {"key": "type",                   "label": "Type",                   "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["AIS-Manual", "AIS-Motor", "GIS"]},
                    {"key": "rated_voltage",          "label": "Rated Voltage",          "type": "number",   "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "rated_current",          "label": "Rated Current",          "type": "number",   "required": True,  "read_only": False, "unit": "A"},
                    {"key": "short_circuit_duration", "label": "Short-Circuit Duration", "type": "number",   "required": False, "read_only": False, "unit": "s"},
                    {"key": "operating_mechanism",    "label": "Operating Mechanism",    "type": "dropdown", "required": False, "read_only": False,
                     "options": ["Motor", "Manual"]},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 8. Control & Relay Panel ─────────────────────────────────────────────
    "nameplate_control_relay_panel": {
        "name": "Control & Relay Panel",
        "equipment_type": "Control & Relay Panel",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "panel_number",        "label": "Panel Number",        "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",       "label": "Voltage Class",       "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Panel Details",
                "fields": [
                    {"key": "panel_type",           "label": "Panel Type",           "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["Numerical", "Electromechanical"]},
                    {"key": "protection_functions", "label": "Protection Functions", "type": "textarea", "required": False, "read_only": False},
                    {"key": "relay_make",            "label": "Relay Make",           "type": "text",     "required": False, "read_only": False},
                    {"key": "relay_model",           "label": "Relay Model",          "type": "text",     "required": False, "read_only": False},
                    {"key": "dc_supply_voltage",     "label": "DC Supply Voltage",    "type": "number",   "required": False, "read_only": False, "unit": "V"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 9. Battery Set ──────────────────────────────────────────────────────
    "nameplate_battery_set": {
        "name": "Battery Set",
        "equipment_type": "Battery Set",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "battery_id",          "label": "Battery ID",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "type",           "label": "Battery Type",    "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["Lead Acid", "VRLA", "Ni-Cd"]},
                    {"key": "cell_count",     "label": "Cell Count",      "type": "number",   "required": True,  "read_only": False},
                    {"key": "cell_voltage",   "label": "Cell Voltage",    "type": "number",   "required": True,  "read_only": False, "unit": "V"},
                    {"key": "ah_capacity",    "label": "Ah Capacity",     "type": "number",   "required": True,  "read_only": False, "unit": "Ah"},
                    {"key": "float_voltage",  "label": "Float Voltage",   "type": "number",   "required": False, "read_only": False, "unit": "V"},
                    {"key": "nominal_voltage","label": "Nominal Voltage", "type": "number",   "required": False, "read_only": False, "unit": "V"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning","label": "Date of Commissioning","type": "date","required": True,  "read_only": False},
                    {"key": "warranty_expiry_date", "label": "Warranty Expiry Date", "type": "date","required": False, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 10. Battery Charger ──────────────────────────────────────────────────
    "nameplate_battery_charger": {
        "name": "Battery Charger",
        "equipment_type": "Battery Charger",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "charger_id",          "label": "Charger ID",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "charger_type",      "label": "Charger Type",         "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["Float cum Boost", "Float Only"]},
                    {"key": "input_voltage",     "label": "Input Voltage",         "type": "number",   "required": True,  "read_only": False, "unit": "V"},
                    {"key": "output_voltage",    "label": "Output Voltage",        "type": "number",   "required": True,  "read_only": False, "unit": "V"},
                    {"key": "output_current",    "label": "Output Current",        "type": "number",   "required": True,  "read_only": False, "unit": "A"},
                    {"key": "float_voltage_set", "label": "Float Voltage Setting", "type": "number",   "required": False, "read_only": False, "unit": "V"},
                    {"key": "boost_voltage_set", "label": "Boost Voltage Setting", "type": "number",   "required": False, "read_only": False, "unit": "V"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 11. Wave Trap ────────────────────────────────────────────────────────
    "nameplate_wave_trap": {
        "name": "Wave Trap",
        "equipment_type": "Wave Trap",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",          "label": "Bay Number",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",       "label": "Voltage Class",       "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "rated_current",    "label": "Rated Current",    "type": "number", "required": True,  "read_only": False, "unit": "A"},
                    {"key": "tuning_frequency", "label": "Tuning Frequency", "type": "number", "required": False, "read_only": False, "unit": "Hz"},
                    {"key": "inductance",       "label": "Inductance",       "type": "number", "required": False, "read_only": False, "unit": "mH"},
                    {"key": "attenuation_db",   "label": "Attenuation",      "type": "number", "required": False, "read_only": False, "unit": "dB"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 12. Station Auxiliary Transformer ────────────────────────────────────
    "nameplate_station_auxiliary_transformer": {
        "name": "Station Auxiliary Transformer",
        "equipment_type": "Station Auxiliary Transformer",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Ratings",
                "fields": [
                    {"key": "type",          "label": "Type",              "type": "dropdown", "required": True,  "read_only": False, "options": ["Dry", "Oil"]},
                    {"key": "rated_kva",     "label": "Rated kVA",         "type": "number",   "required": True,  "read_only": False, "unit": "kVA"},
                    {"key": "hv_voltage",    "label": "HV Voltage",        "type": "number",   "required": True,  "read_only": False, "unit": "V"},
                    {"key": "lv_voltage",    "label": "LV Voltage",        "type": "number",   "required": True,  "read_only": False, "unit": "V"},
                    {"key": "vector_group",  "label": "Vector Group",      "type": "text",     "required": False, "read_only": False},
                    {"key": "impedance_pct", "label": "Impedance Voltage", "type": "number",   "required": False, "read_only": False, "unit": "%"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 13. LTAC Panel ──────────────────────────────────────────────────────
    "nameplate_ltac_panel": {
        "name": "LTAC Panel",
        "equipment_type": "LTAC Panel",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "panel_id",            "label": "Panel ID",            "type": "text",   "required": True,  "read_only": False},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "rated_voltage",              "label": "Rated Voltage",              "type": "number", "required": True,  "read_only": False, "unit": "V"},
                    {"key": "rated_current",              "label": "Rated Current",              "type": "number", "required": True,  "read_only": False, "unit": "A"},
                    {"key": "incoming_feeder",            "label": "Incoming Feeder",            "type": "text",   "required": False, "read_only": False},
                    {"key": "number_of_outgoing_feeders", "label": "No. of Outgoing Feeders",   "type": "number", "required": False, "read_only": False},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 14. Fire Fighting System ─────────────────────────────────────────────
    "nameplate_fire_fighting_system": {
        "name": "Fire Fighting System",
        "equipment_type": "Fire Fighting System",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "system_id",           "label": "System ID",           "type": "text",   "required": True,  "read_only": False},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "type",                "label": "System Type",          "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["Fixed", "Trolley-mounted", "Portable"]},
                    {"key": "medium",              "label": "Fire-Fighting Medium", "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["CO2", "DCP", "Foam", "Water Mist"]},
                    {"key": "capacity",            "label": "Capacity",             "type": "number",   "required": True,  "read_only": False, "unit": "kg"},
                    {"key": "last_refill_date",    "label": "Last Refill Date",     "type": "date",     "required": False, "read_only": False},
                    {"key": "next_inspection_date","label": "Next Inspection Date", "type": "date",     "required": False, "read_only": False},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 15. PLCC Panel ──────────────────────────────────────────────────────
    "nameplate_plcc_panel": {
        "name": "PLCC Panel",
        "equipment_type": "PLCC Panel",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "panel_id",            "label": "Panel ID",            "type": "text",   "required": True,  "read_only": False},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "frequency_range",    "label": "Frequency Range",  "type": "text",   "required": False, "read_only": False, "placeholder": "e.g. 30–500 kHz"},
                    {"key": "power_output_watts", "label": "Power Output",     "type": "number", "required": False, "read_only": False, "unit": "W"},
                    {"key": "line_trap_tuning",   "label": "Line Trap Tuning", "type": "text",   "required": False, "read_only": False},
                    {"key": "associated_line",    "label": "Associated Line",  "type": "text",   "required": False, "read_only": False},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 16. Digital Communication Panel ─────────────────────────────────────
    "nameplate_digital_communication_panel": {
        "name": "Digital Communication Panel",
        "equipment_type": "Digital Communication Panel",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "panel_id",            "label": "Panel ID",            "type": "text",   "required": True,  "read_only": False},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "technology",    "label": "Technology", "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["SDH", "OFC", "OPGW", "PDH"]},
                    {"key": "capacity",      "label": "Capacity",   "type": "text",     "required": False, "read_only": False, "placeholder": "e.g. STM-1, 155 Mbps"},
                    {"key": "fiber_type",    "label": "Fiber Type", "type": "text",     "required": False, "read_only": False, "placeholder": "e.g. Single-mode G.652"},
                    {"key": "wavelength_nm", "label": "Wavelength", "type": "number",   "required": False, "read_only": False, "unit": "nm"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 17. Diesel Generator Set ─────────────────────────────────────────────
    "nameplate_diesel_generator_set": {
        "name": "Diesel Generator Set",
        "equipment_type": "Diesel Generator Set",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "rated_kva",          "label": "Rated kVA",         "type": "number", "required": True,  "read_only": False, "unit": "kVA"},
                    {"key": "rated_kw",           "label": "Rated kW",          "type": "number", "required": True,  "read_only": False, "unit": "kW"},
                    {"key": "rated_voltage",      "label": "Rated Voltage",     "type": "number", "required": True,  "read_only": False, "unit": "V"},
                    {"key": "power_factor",       "label": "Power Factor",      "type": "number", "required": False, "read_only": False},
                    {"key": "speed_rpm",          "label": "Speed",             "type": "number", "required": False, "read_only": False, "unit": "rpm"},
                    {"key": "fuel_tank_capacity", "label": "Fuel Tank Capacity","type": "number", "required": False, "read_only": False, "unit": "L"},
                    {"key": "engine_make",        "label": "Engine Make",       "type": "text",   "required": False, "read_only": False},
                    {"key": "engine_model",       "label": "Engine Model",      "type": "text",   "required": False, "read_only": False},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True,  "read_only": False},
                    {"key": "last_maintenance_date", "label": "Last Maintenance Date", "type": "date", "required": False, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 18. Electronic Tri-vector Meter ──────────────────────────────────────
    "nameplate_electronic_trivector_meter": {
        "name": "Electronic Tri-vector Meter",
        "equipment_type": "Electronic Tri-vector Meter",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",          "label": "Bay Number",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "type",           "label": "Meter Type",         "type": "text",     "required": False, "read_only": False, "default": "ETV"},
                    {"key": "accuracy_class", "label": "Accuracy Class",     "type": "text",     "required": False, "read_only": False},
                    {"key": "ct_ratio",       "label": "CT Ratio",           "type": "text",     "required": False, "read_only": False, "placeholder": "e.g. 200/1"},
                    {"key": "pt_ratio",       "label": "PT Ratio",           "type": "text",     "required": False, "read_only": False, "placeholder": "e.g. 11000/110"},
                    {"key": "meter_constant", "label": "Meter Constant",     "type": "number",   "required": False, "read_only": False},
                    {"key": "communication",  "label": "Communication Port", "type": "dropdown", "required": False, "read_only": False,
                     "options": ["RS485", "Ethernet", "IEC 61850"]},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date",    "required": True,  "read_only": False},
                    {"key": "seal_intact",           "label": "Seal Intact",           "type": "boolean", "required": False, "read_only": False, "default": True},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

    # ── 19. Protection Relay ─────────────────────────────────────────────────
    "nameplate_protection_relay": {
        "name": "Protection Relay",
        "equipment_type": "Protection Relay",
        "template_type": "nameplate",
        "sections": [
            {
                "title": "Identification",
                "fields": [
                    {"key": "substation_name",    "label": "Substation Name",    "type": "text",   "required": True,  "read_only": False},
                    {"key": "bay_number",          "label": "Bay Number",          "type": "text",   "required": True,  "read_only": False},
                    {"key": "voltage_class",       "label": "Voltage Class",       "type": "number", "required": True,  "read_only": False, "unit": "kV"},
                    {"key": "make",                "label": "Make",                "type": "text",   "required": True,  "read_only": False},
                    {"key": "model",               "label": "Model",               "type": "text",   "required": True,  "read_only": False},
                    {"key": "serial_number",       "label": "Serial Number",       "type": "text",   "required": True,  "read_only": False},
                    {"key": "year_of_manufacture", "label": "Year of Manufacture", "type": "number", "required": True,  "read_only": False},
                ]
            },
            {
                "title": "Technical Details",
                "fields": [
                    {"key": "type",              "label": "Relay Type",       "type": "dropdown", "required": True,  "read_only": False,
                     "options": ["Numerical", "Static", "Electromechanical"]},
                    {"key": "relay_function",    "label": "Relay Function(s)","type": "textarea", "required": True,  "read_only": False,
                     "placeholder": "e.g. 51 OC, 50 Instantaneous, 64 Earth Fault"},
                    {"key": "rated_current",     "label": "Rated Current",    "type": "number",   "required": False, "read_only": False, "unit": "A"},
                    {"key": "rated_voltage",     "label": "Rated Voltage",    "type": "number",   "required": False, "read_only": False, "unit": "V"},
                    {"key": "burden_va",         "label": "Burden",           "type": "number",   "required": False, "read_only": False, "unit": "VA"},
                    {"key": "operating_time_ms", "label": "Operating Time",   "type": "number",   "required": False, "read_only": False, "unit": "ms"},
                ]
            },
            {
                "title": "Commissioning",
                "fields": [
                    {"key": "date_of_commissioning", "label": "Date of Commissioning", "type": "date", "required": True, "read_only": False},
                ]
            },
            {
                "title": "Documents",
                "fields": [
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg"], "max_size_kb": 10240},
                    {"key": "test_certificate", "label": "Test Certificate",        "type": "file", "required": False, "read_only": False, "accept": ["application/pdf"], "max_size_kb": 10240},
                ]
            },
        ]
    },

}  # end NAMEPLATE_TEMPLATES


NAMEPLATE_EQUIPMENT_TYPES = [
    ("Power Transformer",             "nameplate_power_transformer"),
    ("Circuit Breaker",               "nameplate_circuit_breaker"),
    ("Current Transformer",           "nameplate_current_transformer"),
    ("Potential Transformer",         "nameplate_potential_transformer"),
    ("Capacitor Voltage Transformer", "nameplate_capacitor_voltage_transformer"),
    ("Surge Arrestor",                "nameplate_surge_arrestor"),
    ("Isolator / Disconnector",       "nameplate_isolator"),
    ("Control & Relay Panel",         "nameplate_control_relay_panel"),
    ("Battery Set",                   "nameplate_battery_set"),
    ("Battery Charger",               "nameplate_battery_charger"),
    ("Wave Trap",                     "nameplate_wave_trap"),
    ("Station Auxiliary Transformer", "nameplate_station_auxiliary_transformer"),
    ("LTAC Panel",                    "nameplate_ltac_panel"),
    ("Fire Fighting System",          "nameplate_fire_fighting_system"),
    ("PLCC Panel",                    "nameplate_plcc_panel"),
    ("Digital Communication Panel",   "nameplate_digital_communication_panel"),
    ("Diesel Generator Set",          "nameplate_diesel_generator_set"),
    ("Electronic Tri-vector Meter",   "nameplate_electronic_trivector_meter"),
    ("Protection Relay",              "nameplate_protection_relay"),
]

NAMEPLATE_TYPE_TO_TEMPLATE = {name: key for name, key in NAMEPLATE_EQUIPMENT_TYPES}


# ----------------- Seed Functions -----------------

def seed_users(session):
    # Hardcoded test users removed — use seed_dept_filter_users() for KPTCL
    # role-based users, or create users through the application UI.
    print("[SKIP] seed_users: no hardcoded users — skipped.")
    return []  # return empty list; downstream assign_viewer_role_to_new_users is a no-op


def seed_roles(session):
    roles_data = [

    # =========================
    # 🔐 SYSTEM ROLES
    # =========================
    {"name": "ADMIN", "description": "Full access to all modules"},
    {"name": "VIEWER", "description": "Read-only access"},
    {"name": "OPERATOR", "description": "Can scan and submit inventory"},
    {"name": "AUDITOR", "description": "Can view scan history and audit trails"},

    # =========================
    # 🏭 EXTERNAL / SERVICE
    # =========================
    {"name": "VENDOR", "description": "Approved repair vendor with access to assigned transformers"},
    {"name": "ERP_SERVICE", "description": "Automated ERP sync service"},

    # =========================
    # 🧪 TESTING WORKFLOW ROLES
    # =========================
    {"name": "ORIGINATOR", "description": "Creates testing requests and raises procurement"},
    {"name": "TESTER", "description": "Performs transformer testing and uploads results"},
    {"name": "APPROVER", "description": "Reviews and approves or rejects recommendations"},

    # =========================
    # ⚡ KPTCL FIELD ROLES
    # =========================
    {"name": "AE_JE", "description": "Assistant Engineer / Junior Engineer - failure reporting & commissioning"},
    {"name": "AEE_MAINTENANCE", "description": "Assistant Executive Engineer - field maintenance authority"},
    {"name": "EE_TLSS", "description": "Executive Engineer - Transmission Line & Substation reviewer"},
    {"name": "SEE_WM", "description": "Superintending Engineer - Works & Maintenance supervisor"},

    # =========================
    # 🧠 TECHNICAL / COMMITTEE
    # =========================
    {"name": "TRC_MEMBER", "description": "Transformer Repair Committee member responsible for stage review decisions"},

    # =========================
    # 🧪 INSPECTION & QA
    # =========================
    {"name": "INSPECTION_ENGINEER", "description": "Performs joint and final inspections"},
    {"name": "QA_TEAM", "description": "Performs stage-wise quality inspections during repair"},

    # =========================
    # 💰 FINANCE
    # =========================
    {"name": "FINANCE_OFFICER", "description": "Approves estimates and financial sanction for repair"},

    # =========================
    # 🏢 SPECIALIZED ENGINEERING (R&D / TRANSMISSION)
    # =========================
    {"name": "EE_RT", "description": "Executive Engineer - Research & Testing"},
    {"name": "SEE_RT", "description": "Superintending Engineer - Research & Testing"},

    {"name": "CEE_TRANSMISSION_ZONE", "description": "Chief Engineer Executive - Transmission zone authority"},
    {"name": "CEE_RT_RD", "description": "Chief Engineer Executive - Research, Testing & R&D"}

]

    role_ids = {}
    for r in roles_data:
        existing_role = session.query(Role).filter_by(name=r["name"]).first()
        if not existing_role:
            role = Role(name=r["name"], description=r["description"])
            session.add(role)
            session.flush()
            role_ids[r["name"]] = role.id
        else:
            role_ids[r["name"]] = existing_role.id
    session.commit()
    print("[OK] Roles seeded successfully.")
    return role_ids

def assign_viewer_role_to_new_users(session, new_user_ids, role_ids):
    """Assign Viewer role to new users who don't have ANY role yet.
    Rule: Each user can only belong to ONE role.
    """
    viewer_role_id = role_ids.get("Viewer")
    if not viewer_role_id:
        print("[ERROR] Viewer role not found")
        return

    for user_id in new_user_ids:
        # Skip if user already has ANY role (single-role rule)
        has_any_role = session.query(UserRole).filter(
            UserRole.user_id == user_id
        ).first()
        if has_any_role:
            continue

        session.add(UserRole(
            user_id=user_id,
            role_id=viewer_role_id
        ))

    session.commit()
    print("[OK] Viewer (Read-only) role assigned to new users without any role.")

def seed_plans(session):
    plans_data = [
        {"planname": "Basic", "plan_description": "Basic plan with limited access", "plan_limit": 10, "isactive": True},
        {"planname": "Standard", "plan_description": "Standard plan with moderate access", "plan_limit": 50, "isactive": True},
        {"planname": "Premium", "plan_description": "Premium plan with full access", "plan_limit": 100, "isactive": True},
    ]

    for p in plans_data:
        existing_plan = session.query(Plan).filter_by(planname=p["planname"]).first()
        if not existing_plan:
            plan = Plan(
                planname=p["planname"],
                plan_description=p["plan_description"],
                plan_limit=p["plan_limit"],
                isactive=p["isactive"]
            )
            session.add(plan)
        else:
            existing_plan.plan_description = p["plan_description"]
            existing_plan.plan_limit = p["plan_limit"]
            existing_plan.isactive = p["isactive"]
    session.commit()
    print("[OK] Plans seeded successfully.")
def seed_category_master(session):
    """Seeds the CategoryMaster table with required categories."""

    category_master_data = [
        {"name": "Company Documents", "description": "Mandatory compliance, technical, and financial documentation."},
        {"name": "Tax Documents", "description": "Statutory tax-related compliance documents."},
        {"name": "Bank Account Types", "description": "Dropdown values for company bank account types (e.g., savings, current, salary)."},
        {"name": "Bank Document Types", "description": "Dropdown values for required company bank documents (e.g., cancelled cheque, bank statement)."},
        {"name": "GST Slabs", "description": "GST percentage slabs applicable to goods and services in India."},
        {"name": "Utility", "description": "Type of utility - Generation, Transmission, DISCOM."},
        
    ]

    master_ids = {}

    for c in category_master_data:
        existing = session.query(CategoryMaster).filter_by(name=c["name"]).first()
        if not existing:
            master = CategoryMaster(
                name=c["name"],
                description=c["description"],
                is_active=True
            )
            session.add(master)
            session.flush()
            master_ids[c["name"]] = master.id
        else:
            existing.description = c["description"]
            existing.is_active = True
            master_ids[c["name"]] = existing.id

    session.commit()
    print("[OK] Category Master seeded successfully.")
    return master_ids

def seed_category_details(session, master_ids):
    """Seeds the CategoryDetails table for all masters."""

    category_details_data = [
        # ---------------- Company Documents ----------------
        {"master_name": "Company Documents", "name": "Quality Manual", "description": "Document outlining the organization's quality management system."},
        {"master_name": "Company Documents", "name": "Manufacturing Capability", "description": "Documentation detailing production capacity and infrastructure."},
        {"master_name": "Company Documents", "name": "Technical Specifications", "description": "Detailed engineering and product specifications."},
        {"master_name": "Company Documents", "name": "Type Test Reports", "description": "Reports from accredited labs confirming product type compliance."},
        {"master_name": "Company Documents", "name": "List of Machineries", "description": "Inventory of primary manufacturing and support machinery."},
        {"master_name": "Company Documents", "name": "List of Testing Equipment's", "description": "Inventory of quality control and measurement equipment."},
        {"master_name": "Company Documents", "name": "Employee Count", "description": "Official report on the total number of employees."},
        {"master_name": "Company Documents", "name": "Lists of Clients", "description": "Reference list of major and relevant clients."},
        {"master_name": "Company Documents", "name": "ISO certificate", "description": "Current ISO quality and environmental management certificates."},
        {"master_name": "Company Documents", "name": "Bank Financial Capability", "description": "Bank statement or certificate proving financial stability."},
        {"master_name": "Company Documents", "name": "Audit Report", "description": "Latest external financial audit report."},
        {"master_name": "Company Documents", "name": "Profit and Loss", "description": "Most recent Profit and Loss Statement."},
        {"master_name": "Company Documents", "name": "Cash Flow Statement", "description": "Cash flow statements for the last three financial years."},
        {"master_name": "Company Documents", "name": "Purchase Order Copy", "description": "Authorized purchase orders issued to vendors."},
        {"master_name": "Company Documents", "name": "Certificate of Incorporation", "description": "Official Certificate of Incorporation issued by ROC."},
        {"master_name": "Company Documents", "name": "Performance Certificate", "description": "Certificates proving successful project execution."},

        # ---------------- Tax Documents ----------------
        {"master_name": "Tax Documents", "name": "GST Certificate", "description": "GST registration certificate."},
        {"master_name": "Tax Documents", "name": "PAN Card", "description": "Permanent Account Number card."},

        # ---------------- Bank Account Types ----------------
        {"master_name": "Bank Account Types", "name": "SAVINGS", "description": "Savings Account"},
        {"master_name": "Bank Account Types", "name": "CURRENT", "description": "Current Account"},
        {"master_name": "Bank Account Types", "name": "SALARY", "description": "Salary Account"},

        # ---------------- Bank Document Types ----------------
        {"master_name": "Bank Document Types", "name": "CANCELLED_CHEQUE", "description": "Cancelled Cheque"},
        {"master_name": "Bank Document Types", "name": "BANK_STATEMENT", "description": "Bank Statement"},
        {"master_name": "Bank Document Types", "name": "PASSBOOK", "description": "Passbook"},

        # ---------------- GST Slabs ----------------
        {"master_name": "GST Slabs", "name": "0", "description": "0% GST (Nil-rated goods and services)"},
        {"master_name": "GST Slabs", "name": "5", "description": "5% GST slab"},
        {"master_name": "GST Slabs", "name": "12", "description": "12% GST slab"},
        {"master_name": "GST Slabs", "name": "18", "description": "18% GST slab"},
        {"master_name": "GST Slabs", "name": "28", "description": "28% GST slab"},

        # ---------------- Utility ----------------
        {"master_name": "Utility", "name": "Generation", "description": "Power generation utility"},
        {"master_name": "Utility", "name": "Transmission", "description": "Power transmission utility"},
        {"master_name": "Utility", "name": "DISCOM", "description": "Distribution company utility"},
    ]

    for d in category_details_data:
        master_id = master_ids.get(d["master_name"])
        if not master_id:
            print(f"[WARN] Master not found: {d['master_name']}")
            continue

        existing = session.query(CategoryDetails).filter_by(
            name=d["name"],
            category_master_id=master_id
        ).first()

        if not existing:
            session.add(CategoryDetails(
                name=d["name"],
                description=d["description"],
                category_master_id=master_id,
                is_active=True
            ))
        else:
            existing.description = d["description"]
            existing.is_active = True

    session.commit()
    print("[OK] Category Details seeded successfully.")

def seed_country_india(session):
    existing = session.query(Country).filter_by(name="INDIA").first()
    if not existing:
        country = Country(
            name="INDIA",
            code="IND",
            erp_external_id="1473917605099"
            
        )
        session.add(country)
        session.commit()
        print("[OK] India seeded successfully.")
    else:
        print("[INFO] India already exists in countries table.")
        
def seed_modules(session):
    modules_data = [
        {"name": "Roles", "description": "Manage roles (Legacy)", "path": "roles", "group_name": "User & Access", "is_active": False},
        {"name": "App Modules", "description": "Manage application modules", "path": "modules", "group_name": "User & Access"},
        {"name": "User Roles", "description": "Assign roles to users (Legacy)", "path": "roles", "group_name": "User & Access", "is_active": False},
        {"name": "Role Permissions", "description": "Configure role-based privileges (Legacy)", "path": "role_module_privileges", "group_name": "User & Access", "is_active": False},
       {"name": "Login Sessions", "description": "Track user login sessions", "path": "user_sessions", "group_name": "User & Access", "is_active": False},
        {"name": "Countries", "description": "Manage country list", "path": "countries", "group_name": "Geography"},
        {"name": "States", "description": "Manage state list", "path": "states", "group_name": "Geography"},
        {"name": "Cities", "description": "Manage cities list", "path": "cities", "group_name": "Geography"},
        {"name": "Addresses", "description": "User address book", "path": "addresses", "group_name": "User & Access"},
        {"name": "Tax Information", "description": "Company tax registration details", "path": "company_tax_info", "group_name": "Company"},
        {"name": "Tax Documents", "description": "Upload company tax documents", "path": "company_tax_documents", "group_name": "Company", "is_active": False},
        {"name": "Product Categories", "description": "Define product categories", "path": "categories", "group_name": "Inventory"},
        {"name": "Product Subcategories", "description": "Define product subcategories", "path": "subcategories", "group_name": "Inventory"},
        {"name": "Products", "description": "Manage product master", "path": "products", "group_name": "Inventory"},
        {"name": "Users", "description": "Manage users", "path": "users", "group_name": "User & Access"},
        {"name": "Company Products", "description": "Company-specific product inventory", "path": "company_products", "group_name": "Inventory"},
        {"name": "Plans", "description": "Manage subscription plans", "path": "plans", "group_name": "User & Access"},
         {"name": "Dashboard", "description": "Admin dashboard", "path": "dashboard", "group_name": "Inventory"},
         {"name": "Assign User Roles", "description": "Assign organization roles to users", "path": "user_roles", "group_name": "User & Access"},
         {"name": "User Product Search", "description": "Filtering user", "path": "user_product_search", "group_name": "User & Access", "is_active": False},
         {"name": "Bank Information", "description": "Company bank account information", "path": "company_bank_info", "group_name": "Company"},
        {"name": "Bank Documents", "description": "Upload company bank documents", "path": "bank_documents", "group_name": "Company", "is_active": False},
        {"name": "Company Product Certificates", "description": "Upload product performance certificates", "path": "company_product_certificates", "group_name": "Company"},
{"name": "Company Product Supply References", "description": "Upload supply reference documents for company products", "path": "company_product_supply_references", "group_name": "Company"},
{"name": "Divisions", "description": "Manage company divisions for approvals", "path": "divisions", "group_name": "Company"},
{"name": "User Documents", "description": "Upload and manage user-specific documents by division", "path": "user_documents", "group_name": "Company"},
{"name": "Sync ERP Vendor", "description": "Sync pending users to ERP", "path": "erp", "group_name": "ERP", "is_active": False},
{"name": "Category Master", "description": "Manage top-level categories for documents/assets (e.g., Company Documents)", "path": "category_master", "group_name": "Documents category"},
{"name": "Category Details", "description": "Manage detailed items under Category Master (e.g., Quality Manual)", "path": "category_details", "group_name": "Documents category"},
{"name": "KYC Status", "description": "Check user pending KYC sections", "path": "kyc", "group_name": "Company"},
{"name": "ERP Database","description": "Internal ERP DB access (backend only)","path": "erp_database","group_name": "ERP","is_active": False},
{"name": "Mongo Database","description": "Internal Mongo DB access (backend only)", "path": "mongo_database", "group_name": "ERP", "is_active": False},
{"name": "zohocontacts", "description": "Manage Zoho Contacts", "path": "zohocontacts", "group_name": "CRM"},
# ✅ PROCUREMENT / ZOHO PORTAL MODULES
{"name": "Request Quote", "description": "Request quotes from suppliers", "path": "request_quote", "group_name": "Procurement"},
{"name": "RQ with Vendor", "description": "Request quotes with vendor selection", "path": "rqWithVendor", "group_name": "Procurement", "is_menu": False},
{"name": "Request Product", "description": "Request new products", "path": "request_product", "group_name": "Procurement", "is_menu": False},
{"name": "Quotes", "description": "View and manage quotes", "path": "quotes", "group_name": "Procurement"},
{"name": "Sales Orders", "description": "View and manage sales orders", "path": "sales_orders", "group_name": "Procurement", "is_menu": False},
{"name": "Invoices", "description": "View and manage invoices", "path": "invoices", "group_name": "Procurement", "is_menu": False},
{"name": "Retainer Invoices", "description": "Manage retainer invoices", "path": "retainer_invoices", "group_name": "Procurement", "is_menu": False},
{"name": "Payments Made", "description": "Track payments made", "path": "payments_made", "group_name": "Procurement", "is_menu": False},
{"name": "Statements", "description": "View account statements", "path": "statements", "group_name": "Procurement", "is_menu": False},
{"name": "Enquiry", "description": "Submit and manage enquiries", "path": "enquiry", "group_name": "Procurement", "is_menu": False},
{"name": "Contact Us", "description": "Customer support", "path": "contact_us", "group_name": "Procurement", "is_menu": False},
# ✅ TESTING REQUEST SYSTEM MODULES
{"name": "Testing Requests", "description": "Create and manage transformer testing requests", "path": "testing_requests", "group_name": "Testing"},
{"name": "Testing", "description": "Perform tests and upload results", "path": "testing", "group_name": "Testing"},
{"name": "Recommendations", "description": "Submit component recommendations", "path": "recommendations", "group_name": "Testing"},
{"name": "Approvals", "description": "Review and approve recommendations", "path": "approvals", "group_name": "Testing"},
{"name": "Testing Request Approvals", "description": "Approve testing requests and assign testers", "path": "testing_request_approvals", "group_name": "Testing"},
# Removed: Validation Requests (not implemented)
# Removed: Tester Mapping (no longer used)
{"name": "Test Template Management", "description": "Design and customise per-org test form templates", "path": "test_templates", "group_name": "Testing"},
# ✅ ORGANIZATION MANAGEMENT MODULES
{"name": "Organizations", "description": "Manage organizations, departments, roles, and users", "path": "organizations", "group_name": "Organization"},
{"name": "Organization User Roles", "description": "Assign organization-specific roles to users within your organization", "path": "org_user_roles", "group_name": "Organization"},
{"name": "Organization Role Permissions", "description": "Configure permissions for organization roles", "path": "org_role_permissions", "group_name": "Organization"},
# ✅ WORKFLOW MANAGEMENT MODULE
{"name": "Workflows", "description": "Manage workflow definitions, states, transitions, and permissions", "path": "workflows", "group_name": "Administration", "is_menu": False},
{"name": "Vendor Documents",
 "description": "View vendor uploaded documents",
 "path": "vendor_documents",
 "group_name": "Organization"},
# ✅ EQUIPMENT ASSET REGISTER MODULE
{"name": "Equipment", "description": "Equipment asset register with UEIC auto-generation", "path": "equipment", "group_name": "Testing"},
# ✅ DASHBOARD KPI MODULES - Role-specific dashboards
{"name": "EE TLSS Dashboard", "description": "Condition monitoring KPI dashboard — EE TLSS operational view", "path": "ee_tlss_dashboard", "group_name": "Testing"},
{"name": "AEE Dashboard", "description": "Field-level supervisor dashboard — AEE operational view", "path": "aee_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "SEE Dashboard", "description": "Circle-level supervisor dashboard — SEE operational view", "path": "see_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "CEE Dashboard", "description": "Zone-level management dashboard — CEE operational view", "path": "cee_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "Admin Dashboard", "description": "Organization admin dashboard with system-wide metrics", "path": "admin_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "Notifications", "description": "In-app notification centre — alerts, overdue reminders, approvals", "path": "notifications", "group_name": "Testing"},
{"name": "Notification Templates", "description": "Configure email/SMS/in-app notification templates per event type", "path": "org_notification_templates", "group_name": "Organization"},
{"name": "Notification Routing",   "description": "Configure routing rules — which roles receive which notifications", "path": "org_notification_routing",   "group_name": "Organization"},
{"name": "Notification Schedules", "description": "Configure scheduled notification rules (due-date reminders, digests)", "path": "org_notification_schedules", "group_name": "Organization"},
# ✅ REPORTING SUITE MODULE
{"name": "Reports", "description": "Generic report engine — 14 SRS operational reports with Excel/PDF export", "path": "reports", "group_name": "Testing"},
# ✅ DIRECT SUBMISSION MODULES (Stage 2 & Stage 10 — no tester assignment)
{"name": "Failure Registry",
 "description": "Stage 2 — Record equipment failure events (SRS Sec 3.3.3–3.3.4). "
                "Accessible to: Field Staff, AEE, EE TLSS, TA&QC Officer.",
 "path": "failure_registry",
 "group_name": "Field Operations"},
{"name": "TA&QC Inspections",
 "description": "Stage 10 — TA&QC annual substation inspection observations with "
                "severity classification and compliance tracking (SRS Sec 6). "
                "Accessible to: TA&QC Officer.",
 "path": "taqc_inspections",
 "group_name": "Field Operations"},
{"name": "Annual Audits",
 "description": "Independent annual audit observation tickets with stage-wise assignment, compliance, review and closure.",
 "path": "annual_audits",
 "group_name": "Field Operations"},
{"name": "Procurement Approvals",
 "description": "Finance Approver queue — review and approve / reject replacement procurement "
                "requests created after Technical Approver approves a 'replacement' recommendation. "
                "Accessible to: Finance Approver role.",
 "path": "procurement_approvals",
 "group_name": "Field Operations"},
# ✅ TEST REGISTER MODULE (SRS §5.1.1)
{"name": "Test Register",
 "description": "SRS §5.1.1 — Periodic test catalogue: defines what tests are mandatory, "
                "how often, and by which role for each equipment type. "
                "Accessible to: EE TLSS, Department Head, AEE Maintenance.",
 "path": "test_register",
 "group_name": "Condition Monitoring"},
# ✅ REPAIR WORKFLOW MODULE
{"name": "Repair Workflows",
 "description": "Transformer repair lifecycle — 10-stage workflow from Failure Reporting to Commissioning. "
                "Config (org-admin only): define stages, forms, roles, transitions. "
                "Execution: stage-role RBAC driven; each stage locks to authorized roles only.",
 "path": "repair-workflows",
 "group_name": "Field Operations"},
    ]

    module_ids = {}

    for m in modules_data:
        existing = session.query(Module).filter_by(name=m["name"]).first()

        if not existing:
            module = Module(
                name=m["name"],
                description=m["description"],
                path=m["path"],
                group_name=m["group_name"],
                is_active=m.get("is_active", True),
                is_menu=m.get("is_menu", True),
            )
            session.add(module)
            session.flush()
            module_ids[m["name"]] = module.id

        else:
            existing.description = m["description"]
            existing.path = m["path"]
            existing.group_name = m["group_name"]
            existing.is_active = m.get("is_active", True)
            existing.is_menu = m.get("is_menu", True)

            module_ids[m["name"]] = existing.id

    session.commit()
    print("[OK] Modules seeded successfully.")
    return module_ids


def seed_privileges(session, role_ids, module_ids):
    module_names = [
    # Legacy modules disabled: "Roles", "User Roles", "Role Permissions", "Login Sessions",
    "App Modules",
    "Countries", "States", "Cities","Addresses", "Tax Information", "Tax Documents",
    "Product Categories", "Product Subcategories", "Products", "Users",
    "Company Products", "Plans", "Dashboard", "Assign User Roles",
    "User Product Search", "Bank Information", "Bank Documents",
    "Divisions", "User Documents",
    "Company Product Certificates", "Company Product Supply References",
    "Category Master", "Category Details",
    "Sync ERP Vendor","KYC Status" , "zohocontacts", "Vendor Documents"
    ]


    # -------------------------------------------------------
    # REMOVE all Vendor privileges before re-seeding
    # -------------------------------------------------------
    vendor_role_id = role_ids.get("Vendor")
    if vendor_role_id:
        session.query(RoleModulePrivilege).filter(
            RoleModulePrivilege.role_id == vendor_role_id
        ).delete()
        session.commit()

    # -------------------------------------------------------
    # ALL MODULES
    # -------------------------------------------------------
    module_names = [
        # Legacy modules disabled: "Roles", "User Roles", "Role Permissions", "Login Sessions",
        "App Modules",
        "Countries", "States", "Cities", "Addresses", "Tax Information", "Tax Documents",
        "Product Categories", "Product Subcategories", "Products", "Users",
        "Company Products", "Plans", "Dashboard", "Assign User Roles",
        "User Product Search", "Bank Information", "Bank Documents",
        "Divisions", "User Documents",
        "Company Product Certificates", "Company Product Supply References",
        "Category Master", "Category Details",
        "Sync ERP Vendor", "KYC Status", "zohocontacts",
        # ✅ PROCUREMENT / ZOHO PORTAL MODULES
        "Request Quote", "Request Product", "Quotes", "Sales Orders",
        "Invoices", "Retainer Invoices", "Payments Made", "Statements",
        "Enquiry", "Contact Us", "RQ with Vendor",
        # ✅ TESTING REQUEST SYSTEM MODULES
        "Testing Requests", "Testing", "Recommendations", "Approvals",
        # Removed: "Validation Requests" (not implemented)
        "Test Template Management",
        # ✅ ORGANIZATION MANAGEMENT MODULE
        "Organizations",
        # ✅ WORKFLOW MANAGEMENT MODULE
        "Workflows","Vendor Documents",
        # ✅ EQUIPMENT ASSET REGISTER
        "Equipment",
        # ✅ DASHBOARD KPI & NOTIFICATIONS
        "EE TLSS Dashboard",
        "Notifications",
        # ✅ REPORTING SUITE
        "Reports",
    ]

    # -------------------------------------------------------
    # PRIVILEGES DATA (ADMIN / VIEWER / OPERATOR / AUDITOR)
    # -------------------------------------------------------
    privileges_data = [

        # ADMIN FULL ACCESS
        *[
            {
                "role": "Admin",
                "module": module,
                "can_view": True, "can_add": True, "can_edit": True,
                "can_delete": True, "can_search": True,
                "can_import": True, "can_export": True
            }
            for module in module_names
        ],

        # VIEWER — only view
        *[
            { "role": "Viewer", "module": module, "can_view": True }
            for module in module_names
        ],

        # OPERATOR — selected modules
        *[
            { "role": "Operator", "module": module, "can_view": True }
            for module in ["Products", "Company Products", "Login Sessions"]
        ],

        # AUDITOR — view only all modules
        *[
            { "role": "Auditor", "module": module, "can_view": True }
            for module in module_names
        ]
    ]

    # -------------------------------------------------------
    # ⭐ NEW VENDOR PERMISSIONS (FULL + VIEW-ONLY)
    # -------------------------------------------------------
    vendor_privileges = [

        # Vendor — FULL ACCESS modules
        *[
            {
                "role": "Vendor",
                "module": module,
                "can_view": True,
                "can_add": True,
                "can_edit": True,
                "can_delete": True,
                "can_search": True,
                "can_import": True,
                "can_export": True
            }
            for module in [
                "Dashboard",
                "Company Products",
                "Bank Information",
                "Bank Documents",
                "Tax Information",
                "Tax Documents",
                "User Documents",
                "Addresses"
            ]
        ],

        # Vendor — VIEW ONLY module
        {
            "role": "Vendor",
            "module": "Divisions",
            "can_view": True,
            "can_add": False,
            "can_edit": False,
            "can_delete": False,
            "can_search": False,
            "can_import": False,
            "can_export": False
        }
    ]

    # -------------------------------------------------------
    # MERGE vendor privileges into main privilege list
    # -------------------------------------------------------
    privileges_data.extend(vendor_privileges)
        # -------------------------------------------------------
    # ⭐ ERP SERVICE PRIVILEGES (FULL ERP ACCESS ONLY)
    # -------------------------------------------------------
    erp_service_privileges = [
        {
            "role": "ERP_SERVICE",
            "module": "Sync ERP Vendor",
            "can_view": True,
            "can_add": True,
            "can_edit": True,
            "can_delete": False,
            "can_search": False,
            "can_import": False,
            "can_export": False
        }
    ]

    privileges_data.extend(erp_service_privileges)

    # -------------------------------------------------------
    # ⭐ TESTING REQUEST SYSTEM PRIVILEGES  (aligned with role-module map)
    # -------------------------------------------------------
    testing_privileges = [
        # ORIGINATOR — dashboard + procurement + testing requests (no Testing itself)
        {
            "role": "Originator", "module": "Testing Requests",
            "can_view": True, "can_add": True, "can_edit": True,
            "can_delete": True, "can_search": True, "can_assign": True
        },
        # Removed: Validation Requests privilege (module not implemented)
        {"role": "Originator", "module": "Dashboard", "can_view": True},
        # Originator — Procurement modules (full add/edit)
        {"role": "Originator", "module": "Request Quote",       "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Originator", "module": "RQ with Vendor",      "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Originator", "module": "Request Product",     "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Originator", "module": "Quotes",              "can_view": True},
        {"role": "Originator", "module": "Sales Orders",        "can_view": True},
        {"role": "Originator", "module": "Invoices",            "can_view": True},
        {"role": "Originator", "module": "Retainer Invoices",   "can_view": True},
        {"role": "Originator", "module": "Payments Made",       "can_view": True},
        {"role": "Originator", "module": "Statements",          "can_view": True},
        {"role": "Originator", "module": "Enquiry",             "can_view": True, "can_add": True},
        {"role": "Originator", "module": "Contact Us",          "can_view": True},

        # FIELD TESTER — view Testing Requests, full on Testing
        {"role": "Field Tester", "module": "Testing Requests", "can_view": True},
        {
            "role": "Field Tester", "module": "Testing",
            "can_view": True, "can_add": True, "can_edit": True, "can_search": True
        },

        # LAB TESTER — same as Field Tester
        {"role": "Lab Tester", "module": "Testing Requests", "can_view": True},
        {
            "role": "Lab Tester", "module": "Testing",
            "can_view": True, "can_add": True, "can_edit": True, "can_search": True
        },

        # TEST ASSIGNER (Approver) — approve/assign on Testing Request Approvals
        {
            "role": "Test Assigner", "module": "Testing Request Approvals",
            "can_view": True, "can_approve": True, "can_assign": True
        },
        {"role": "Test Assigner", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "Test Assigner", "module": "Dashboard", "can_view": True},

        # DOC-VIEWER — view only for Vendor Documents
        {
            "role": "doc-viewer", "module": "Vendor Documents",
            "can_view": True, "can_add": False, "can_edit": False, 
            "can_delete": False, "can_search": True
        },

        # DEPARTMENT HEAD — approve on Recommendations + Approvals
        {"role": "Department Head", "module": "Dashboard", "can_view": True},
        {"role": "Department Head", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "Department Head", "module": "Recommendations",
         "can_view": True, "can_approve": True},
        {"role": "Department Head", "module": "Approvals",
         "can_view": True, "can_approve": True},

        # PURCHASER — dashboard + full procurement
        {"role": "Purchaser", "module": "Dashboard",            "can_view": True},
        {"role": "Purchaser", "module": "Request Quote",        "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Purchaser", "module": "RQ with Vendor",       "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Purchaser", "module": "Request Product",      "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Purchaser", "module": "Quotes",               "can_view": True},
        {"role": "Purchaser", "module": "Sales Orders",         "can_view": True},
        {"role": "Purchaser", "module": "Invoices",             "can_view": True},
        {"role": "Purchaser", "module": "Retainer Invoices",    "can_view": True},
        {"role": "Purchaser", "module": "Payments Made",        "can_view": True},
        {"role": "Purchaser", "module": "Statements",           "can_view": True},
        {"role": "Purchaser", "module": "Enquiry",              "can_view": True, "can_add": True},
        {"role": "Purchaser", "module": "Contact Us",           "can_view": True},

        # TESTER MAPPING — Admin full, Originator view-only
        {
            "role": "Admin", "module": "Tester Mapping",
            "can_view": True, "can_add": True, "can_edit": True,
            "can_delete": True, "can_search": True
        },
        {"role": "Originator", "module": "Tester Mapping", "can_view": True},

        # TEST TEMPLATE MANAGEMENT — Admin full (via bulk), Originator view-only
        {"role": "Originator", "module": "Test Template Management", "can_view": True},

        # ✅ EQUIPMENT ASSET REGISTER — role-based access
        {
            "role": "Originator", "module": "Equipment",
            "can_view": True, "can_add": True, "can_edit": True,
            "can_search": True
        },
        {"role": "Field Tester", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Lab Tester", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Test Assigner", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Department Head", "module": "Equipment", "can_view": True, "can_search": True},

        # ✅ SRS DESIGNATION ROLES — Permissions per role hierarchy
        # AEE Maintenance — Field supervisor
        {"role": "AEE Maintenance", "module": "Dashboard", "can_view": True},
        {"role": "AEE Maintenance", "module": "Testing Requests", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True, "can_assign": True},
        {"role": "AEE Maintenance", "module": "Testing", "can_view": True, "can_add": True},
        {"role": "AEE Maintenance", "module": "Testing Request Approvals", "can_view": True, "can_approve": True},
        {"role": "AEE Maintenance", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "AEE Maintenance", "module": "Notifications", "can_view": True},
        {"role": "AEE Maintenance", "module": "Reports", "can_view": True, "can_export": True},

        # EE TLSS — Primary reviewer (most critical role)
        # NOTE: Does NOT have Testing Request Approvals access (not applicable for this role)
        {"role": "EE TLSS", "module": "Dashboard", "can_view": True},
        {"role": "EE TLSS", "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "EE TLSS", "module": "Testing Requests", "can_view": True, "can_add": True, "can_edit": True},
        {"role": "EE TLSS", "module": "Testing", "can_view": True, "can_add": True, "can_edit": True},
        {"role": "EE TLSS", "module": "Equipment", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "EE TLSS", "module": "Notifications", "can_view": True},
        {"role": "EE TLSS", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "EE TLSS", "module": "Request Quote", "can_view": True},
        {"role": "EE TLSS", "module": "Quotes", "can_view": True},
        {"role": "EE TLSS", "module": "Sales Orders", "can_view": True},

        # SEE W&M — Circle supervisor (equivalent to Test Assigner in SRS)
        {"role": "SEE W&M", "module": "Dashboard", "can_view": True},
        {"role": "SEE W&M", "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "SEE W&M", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "SEE W&M", "module": "Testing", "can_view": True},
        {"role": "SEE W&M", "module": "Testing Request Approvals", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "SEE W&M", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "SEE W&M", "module": "Notifications", "can_view": True},
        {"role": "SEE W&M", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "SEE W&M", "module": "Request Quote", "can_view": True, "can_add": True},
        {"role": "SEE W&M", "module": "Quotes", "can_view": True, "can_approve": True},
        {"role": "SEE W&M", "module": "Vendor Directory", "can_view": True},

        # EE RT — Research & Testing engineer
        {"role": "EE RT", "module": "Dashboard", "can_view": True},
        {"role": "EE RT", "module": "Testing Requests", "can_view": True, "can_add": True, "can_approve": True, "can_assign": True},
        {"role": "EE RT", "module": "Testing", "can_view": True, "can_add": True, "can_edit": True},
        {"role": "EE RT", "module": "Testing Request Approvals", "can_view": True, "can_approve": True},
        {"role": "EE RT", "module": "Test Template Management", "can_view": True, "can_edit": True},
        {"role": "EE RT", "module": "Equipment", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "EE RT", "module": "Reports", "can_view": True, "can_export": True},

        # SEE RT — Senior Research & Testing
        {"role": "SEE RT", "module": "Dashboard", "can_view": True},
        {"role": "SEE RT", "module": "Testing Requests", "can_view": True},
        {"role": "SEE RT", "module": "Testing", "can_view": True, "can_add": True, "can_edit": True, "can_export": True},
        {"role": "SEE RT", "module": "Testing Request Approvals", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "SEE RT", "module": "Test Template Management", "can_view": True, "can_edit": True},
        {"role": "SEE RT", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "SEE RT", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "SEE RT", "module": "Vendor Directory", "can_view": True},

        # CEE Transmission Zone — Zone management
        {"role": "CEE Transmission Zone", "module": "Dashboard", "can_view": True},
        {"role": "CEE Transmission Zone", "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "CEE Transmission Zone", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "CEE Transmission Zone", "module": "Testing", "can_view": True},
        {"role": "CEE Transmission Zone", "module": "Testing Request Approvals", "can_view": True, "can_approve": True},
        {"role": "CEE Transmission Zone", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "CEE Transmission Zone", "module": "Notifications", "can_view": True},
        {"role": "CEE Transmission Zone", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "CEE Transmission Zone", "module": "Request Quote", "can_view": True, "can_approve": True},
        {"role": "CEE Transmission Zone", "module": "Quotes", "can_view": True, "can_approve": True},
        {"role": "CEE Transmission Zone", "module": "Sales Orders", "can_view": True},
        {"role": "CEE Transmission Zone", "module": "Vendor Directory", "can_view": True},

        # CEE RT&R&D — Research & Development chief
        {"role": "CEE RT&R&D", "module": "Dashboard", "can_view": True},
        {"role": "CEE RT&R&D", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "CEE RT&R&D", "module": "Testing", "can_view": True},
        {"role": "CEE RT&R&D", "module": "Testing Request Approvals", "can_view": True},
        {"role": "CEE RT&R&D", "module": "Test Template Management", "can_view": True, "can_add": True, "can_edit": True, "can_delete": True},
        {"role": "CEE RT&R&D", "module": "Equipment", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "CEE RT&R&D", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "CEE RT&R&D", "module": "Vendor Directory", "can_view": True},

        # ✅ EE TLSS DASHBOARD — role-based access
        # All operational roles can view the dashboard; it auto-renders the
        # correct widget set based on the user's OrgRole inside dashboard_service.py.
        {"role": "Originator",      "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Field Tester",    "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Lab Tester",      "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Test Assigner",   "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Department Head", "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Purchaser",       "module": "EE TLSS Dashboard", "can_view": True},

        # ✅ NOTIFICATIONS — all active roles can view their own notification centre
        {"role": "Originator",      "module": "Notifications", "can_view": True},
        {"role": "Field Tester",    "module": "Notifications", "can_view": True},
        {"role": "Lab Tester",      "module": "Notifications", "can_view": True},
        {"role": "Test Assigner",   "module": "Notifications", "can_view": True},
        {"role": "Department Head", "module": "Notifications", "can_view": True},
        {"role": "Purchaser",       "module": "Notifications", "can_view": True},
        {"role": "Vendor",          "module": "Notifications", "can_view": True},

        # ✅ REPORTING SUITE — view + export for all operational roles
        {"role": "Originator",      "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Field Tester",    "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Lab Tester",      "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Test Assigner",   "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Department Head", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Purchaser",       "module": "Reports", "can_view": True, "can_export": True},

        # ✅ FAILURE REGISTRY — Stage 2 (SRS Sec 3.3.3)
        # Accessible to field-level and supervisory roles; TA&QC can also submit.
        {"role": "AEE Maintenance",         "module": "Failure Registry", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "EE TLSS",                 "module": "Failure Registry", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "EE RT",                   "module": "Failure Registry", "can_view": True, "can_add": True, "can_search": True},
        {"role": "SEE W&M",                 "module": "Failure Registry", "can_view": True, "can_search": True},
        {"role": "SEE RT",                  "module": "Failure Registry", "can_view": True, "can_search": True},
        {"role": "CEE Transmission Zone",   "module": "Failure Registry", "can_view": True, "can_search": True},
        {"role": "CEE RT&R&D",             "module": "Failure Registry", "can_view": True, "can_search": True},
        {"role": "Field Tester",            "module": "Failure Registry", "can_view": True, "can_add": True},
        {"role": "Lab Tester",              "module": "Failure Registry", "can_view": True, "can_add": True},

        # ✅ TA&QC INSPECTIONS — Stage 10 (SRS Sec 6)
        # Restricted to TA&QC Officers and supervisory roles.
        {"role": "EE RT",                   "module": "TA&QC Inspections", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "SEE RT",                  "module": "TA&QC Inspections", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "CEE RT&R&D",             "module": "TA&QC Inspections", "can_view": True, "can_add": True, "can_approve": True},
        {"role": "EE TLSS",                 "module": "TA&QC Inspections", "can_view": True, "can_search": True},
        {"role": "SEE W&M",                 "module": "TA&QC Inspections", "can_view": True, "can_search": True},
        {"role": "CEE Transmission Zone",   "module": "TA&QC Inspections", "can_view": True, "can_search": True},

        # ✅ REPAIR WORKFLOWS — Transformer repair lifecycle (10 stages)
        # Stage-level RBAC is enforced in the service layer via RepairStageRole.
        # Module-level privileges here control who can see the module in the nav.
        # Config endpoints (PUT /repair-workflows/config/*) require is_org_admin.

        # All stage-acting roles: can view + add (save data) + approve (advance/reject)
        {"role": "AEE Maintenance",         "module": "Repair Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "TRC Member",              "module": "Repair Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "CEE RT&R&D",             "module": "Repair Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "CEE Transmission Zone",   "module": "Repair Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Vendor",                  "module": "Repair Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Inspection Engineer",     "module": "Repair Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Finance Officer",         "module": "Repair Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "QA Team",                 "module": "Repair Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "EE RT",                   "module": "Repair Workflows", "can_view": True, "can_add": True, "can_approve": True},
        {"role": "SEE RT",                  "module": "Repair Workflows", "can_view": True, "can_add": True, "can_approve": True},

        # Supervisory roles: view + export only (no stage actions)
        {"role": "EE TLSS",                 "module": "Repair Workflows", "can_view": True, "can_export": True},
        {"role": "SEE W&M",                 "module": "Repair Workflows", "can_view": True, "can_export": True},
    ]

    privileges_data.extend(testing_privileges)

    # -------------------------------------------------------
    # INSERT PRIVILEGES INTO DATABASE
    # -------------------------------------------------------
    for p in privileges_data:
        role_id = role_ids.get(p["role"])
        module_id = module_ids.get(p["module"])

        if not role_id or not module_id:
            continue

        exists = session.query(RoleModulePrivilege).filter_by(
            role_id=role_id,
            module_id=module_id
        ).first()

        if not exists:
            session.add(RoleModulePrivilege(
                role_id=role_id,
                module_id=module_id,
                can_view=p.get("can_view", False),
                can_add=p.get("can_add", False),
                can_edit=p.get("can_edit", False),
                can_delete=p.get("can_delete", False),
                can_search=p.get("can_search", False),
                can_import=p.get("can_import", False),
                can_export=p.get("can_export", False),
                can_approve=p.get("can_approve", False),
                can_assign=p.get("can_assign", False),
            ))

    session.commit()
    print("[OK] Privileges seeded successfully!")


def seed_user_roles(session, role_ids):
    # Hardcoded role assignments removed — roles are assigned via the
    # application UI or seed_dept_filter_users() for dept-filter test users.
    print("[SKIP] seed_user_roles: no hardcoded role assignments — skipped.")


# ----------------- TNEB Product Seed -----------------

import json

def seed_product_categories(session):

    # ---- 1. READ categories from JSON file ----
    with open("categories_data_clean.json", "r", encoding="utf-8") as f:
        categories_raw = json.load(f)

    # ---- 2. REMOVE DUPLICATES BY CATEGORY NAME ----
    unique_categories = {}
    for item in categories_raw:
        name = item["name"].strip()

        # Keep ONLY first occurrence
        if name not in unique_categories:
            unique_categories[name] = item["description"].strip()

    # Convert back to list of dicts
    categories_data = [
        {"name": name, "description": desc}
        for name, desc in unique_categories.items()
    ]

    # ---- 3. SEED INTO DATABASE (your original logic) ----
    category_ids = {}

    for c in categories_data:
        existing = session.query(ProductCategory).filter_by(name=c["name"]).first()

        if not existing:
            category = ProductCategory(
                name=c["name"],
                description=c["description"],
                is_active=True
            )
            session.add(category)
            session.flush()
            category_ids[c["name"]] = category.id
        else:
            existing.description = c["description"]
            existing.is_active = True
            category_ids[c["name"]] = existing.id

    session.commit()

    print("[OK] Product categories seeded successfully.")
    return category_ids


def seed_divisions(session):
    """
    Seeds default divisions that can be used for approval and user document uploads.
    """
    divisions_data = [
        {"division_name": "UTILITY", "code": "UTILITY","is_active": True, "description": "Handles IT, software, and digital infrastructure", "erp_external_id": 1758544460722},
    ]

    for d in divisions_data:
        existing = session.query(Division).filter_by(division_name=d["division_name"]).first()
        if not existing:
            division = Division(
                division_name=d["division_name"],
                code=d["code"],
                description=d["description"],
                is_active=True
            )
            session.add(division)
        else:
            existing.description = d["description"]
            existing.is_active = True

    session.commit()
    print("[OK] Divisions seeded successfully.")

import json

import json

def seed_product_subcategories(session, category_ids):

    # ---- 1. Load subcategories from JSON file ----
    with open("subcategories_data_clean.json", "r", encoding="utf-8") as f:
        subcategories_raw = json.load(f)

    # ---- 2. Remove duplicates (unique by name + category) ----
    unique_pairs = set()
    subcategories_data = []

    for item in subcategories_raw:
        name = item["name"].strip()
        category = item["category"].strip()

        key = (name, category)
        if key not in unique_pairs:
            unique_pairs.add(key)
            subcategories_data.append({
                "name": name,
                "category": category
            })

    print(f"[INFO] Unique subcategories found: {len(subcategories_data)}")

    # ---- 3. Seed subcategories into DB ----
    subcategory_ids = {}

    for sc in subcategories_data:
        category_name = sc["category"]
        subcategory_name = sc["name"]

        # Must exist in categories
        category_id = category_ids.get(category_name)
        if not category_id:
            print(f"[WARN] Category not found for subcategory: {subcategory_name}")
            continue

        # Check if subcategory already exists under this category
        existing = session.query(ProductSubCategory).filter_by(
            name=subcategory_name,
            category_id=category_id
        ).first()

        description = f"{subcategory_name} under {category_name}"

        if not existing:
            # Create new record
            subcat = ProductSubCategory(
                name=subcategory_name,
                description=description,
                category_id=category_id,
                is_active=True
            )
            session.add(subcat)
            session.flush()

            # ❗ Store ID by pure subcategory name
            subcategory_ids[subcategory_name] = subcat.id

        else:
            # Update existing
            existing.description = description
            existing.category_id = category_id
            existing.is_active = True

            subcategory_ids[subcategory_name] = existing.id

    session.commit()

    print("[OK] Product subcategories seeded successfully.")
    return subcategory_ids


def seed_indian_states(session, india):
    states_data = [
       {"erp_external_id": 6000001, "name": "ANDAMAN AND NICOBAR", "code": "AN"},
       {"erp_external_id": 6000002, "name": "ANDHRA PRADESH", "code": "AP"},
       {"erp_external_id": 6000003, "name": "ARUNACHAL PRADESH", "code": "AR"},
       {"erp_external_id": 6000004, "name": "ASSAM", "code": "AS"},
       {"erp_external_id": 6000005, "name": "BIHAR", "code": "BH"},
       {"erp_external_id": 6000006, "name": "CHANDIGARH", "code": "CH"},
       {"erp_external_id": 6000007, "name": "CHHATTISGARH", "code": "CG"},
       {"erp_external_id": 6000008, "name": "DADRA AND NAGAR HAVELI", "code": "DN"},
       {"erp_external_id": 6000009, "name": "DAMAN AND DIU", "code": "DD"},
       {"erp_external_id": 6000010, "name": "DELHI", "code": "DL"},
       {"erp_external_id": 6000011, "name": "GOA", "code": "GA"},
       {"erp_external_id": 6000012, "name": "GUJARAT", "code": "GJ"},
       {"erp_external_id": 6000013, "name": "HARYANA", "code": "HR"},
       {"erp_external_id": 6000014, "name": "HIMACHAL PRADESH", "code": "HP"},
       {"erp_external_id": 6000015, "name": "JAMMU AND KASHMIR", "code": "JK"},
       {"erp_external_id": 6000016, "name": "JHARKHAND", "code": "JH"},
       {"erp_external_id": 6000017, "name": "KARNATAKA", "code": "KA"},
       {"erp_external_id": 6000018, "name": "KERALA", "code": "KL"},
       {"erp_external_id": 6000019, "name": "LAKSHADWEEP", "code": "LD"},
       {"erp_external_id": 6000020, "name": "MADHYA PRADESH", "code": "MP"},
       {"erp_external_id": 6000021, "name": "MAHARASHTRA", "code": "MH"},
       {"erp_external_id": 6000022, "name": "MANIPUR", "code": "MN"},
       {"erp_external_id": 6000023, "name": "MEGHALAYA", "code": "ML"},
       {"erp_external_id": 6000024, "name": "MIZORAM", "code": "MM"},
       {"erp_external_id": 6000025, "name": "NAGALAND", "code": "NL"},
       {"erp_external_id": 6000026, "name": "ODISHA", "code": "OR"},
       {"erp_external_id": 6000027, "name": "PUDUCHERRY", "code": "PN"},
       {"erp_external_id": 6000028, "name": "PUNJAB", "code": "PJ"},
       {"erp_external_id": 6000029, "name": "RAJASTHAN", "code": "RJ"},
       {"erp_external_id": 6000030, "name": "SIKKIM", "code": "SK"},
       {"erp_external_id": 6000031, "name": "TAMIL NADU", "code": "TN"},
       {"erp_external_id": 6000032, "name": "TRIPURA", "code": "TR"},
       {"erp_external_id": 6000033, "name": "UTTAR PRADESH", "code": "UP"},
       {"erp_external_id": 6000034, "name": "UTTARANCHAAL", "code": "UT"},
       {"erp_external_id": 6000035, "name": "WEST BENGAL", "code": "WB"},
       {"erp_external_id": 1502861055959, "name": "TELANGANA", "code": "TS"},
       {"erp_external_id": 1614244756824, "name": "OTHER COUNTRY", "code": "OTC"},
       {"erp_external_id": 1614244756822, "name": "OTHER TERRITORY", "code": "OTH"},
       {"erp_external_id": 1696053504315, "name": "LADAKH", "code": "LD"},
    ]
    inserted_states = {}
    for s in states_data:
        existing = session.query(State).filter_by(name=s["name"], country_id=india.id).first()
        if not existing:
            state = State(
                name=s["name"],
                code=s["code"],
                erp_external_id=s["erp_external_id"],
                country_id=india.id
            )
            session.add(state)
            session.flush()
            inserted_states[s["name"]] = state.id  # use ID
        else:
            inserted_states[s["name"]] = existing.id

    session.commit()
    print("[OK] Indian states seeded successfully.")
    return inserted_states

# ----------------- Country & States Seed -----------------
def seed_india_country(session):
    india = session.query(Country).filter_by(name="INDIA").first()
    if not india:
        india = Country(name="INDIA", code="IND", erp_external_id="1473917605099")
        session.add(india)
        session.commit()
        print("[OK] India seeded successfully.")
        
    return session.query(Country).filter_by(name="INDIA").first()

import json

def seed_products(session, category_ids, subcategory_ids, filepath="product.json"):

    # -----------------------------
    # 1. Your existing products_data
    # -----------------------------
    existing_data = [
        {"name": "11kV Distribution Transformer 100 kVA", "category": "Transformers", "subcategory": "Distribution Transformers", "sku": "TNEB-TR100", "description": "Oil-immersed 11kV transformer for distribution"},
        {"name": "3 Phase Energy Meter", "category": "Meters", "subcategory": "Three Phase Meters", "sku": "TNEB-MTR3P", "description": "3 phase digital energy meter"},
        {"name": "XLPE Power Cable 1.1kV 50mm²", "category": "Cables & Wires", "subcategory": "XLPE Cables", "sku": "TNEB-CBL50", "description": "XLPE insulated 1.1kV power cable"},
        {"name": "Air Circuit Breaker 400A", "category": "Switchgear & Panels", "subcategory": "Circuit Breakers", "sku": "TNEB-ACB400", "description": "400A air circuit breaker"},
        {"name": "LED Street Light 50W", "category": "Street Lighting", "subcategory": "LED Lamps", "sku": "TNEB-LED50", "description": "Energy-efficient 50W LED street lamp"},
        {"name": "Digital Clamp Meter", "category": "Tools & Accessories", "subcategory": "Testers", "sku": "TNEB-TLM01", "description": "Clamp meter for electrical measurements"},
        {"name": "Polycarbonate Encloser 600X600X227", "category": "Solar Combiner Boxes", "subcategory": "Polycarbonate Enclosures", "sku": "01 17 07831-HE-PC 6060 22/180 T X P", "description": "Solar Combiner boxes"},
        {"name": "Polycarbonate Encloser 600X600X227", "category": "Solar Combiner Boxes", "subcategory": "Polycarbonate Enclosures", "sku": "01 17 00606-HE-PC 5638 18/150 T X P", "description": "Solar Combiner boxes"},
        {"name": "FRP/GRP Encloser 650X550X250", "category": "Solar Combiner Boxes", "subcategory": "FRP/GRP Enclosures", "sku": "01 17 06378-FRP/GRP ENCL 650X550X250 H", "description": "Solar Combiner boxes"},
        {"name": "FRP/GRP Encloser 850X700X300", "category": "Solar Combiner Boxes", "subcategory": "FRP/GRP Enclosures", "sku": "01 17 07827-FRP/GRP ENCL 850X700X300 VERTI", "description": "Solar Combiner boxes"},
        {"name": "Cable Gland M40-IP68", "category": "Cable Glands", "subcategory": "Brass", "sku": "01 17 11006-TTMMUL-40", "description": "Cable Glands - Nickel Plated Brass"},
        {"name": "Cable Gland M50-IP68", "category": "Cable Glands", "subcategory": "Brass", "sku": "01 17 11007-TTMMUL-50", "description": "Cable Glands - Nickel Plated Brass"},
        {"name": "Cable Gland M63-IP68", "category": "Cable Glands", "subcategory": "Brass", "sku": "01 17 11008-TTMMUL-63", "description": "Cable Glands - Nickel Plated Brass"},
        {"name": "Cable Gland M40-IP68", "category": "Cable Glands", "subcategory": "Polyamide", "sku": "01 17 11046-TTMWUL-40", "description": "Cable Glands - Polyamide"},
        {"name": "Cable Gland M50-IP68", "category": "Cable Glands", "subcategory": "Polyamide", "sku": "01 17 11047--TTMWUL-50", "description": "Cable Glands - Polyamide"},
        {"name": "Cable Gland M63-IP68", "category": "Cable Glands", "subcategory": "Polyamide", "sku": "01 17 11048--TTMWUL-63", "description": "Cable Glands - Polyamide"},
        {"name": "Panel Mounted Socket 16A,3P TTS-B1361-6 IP67", "category": "Sockets", "subcategory": "Panel Mounted Sockets", "sku": "014300037-Socket 16A,3P TTS-B1361-6 IP67", "description": "Panel Mounted Sockets"},
        {"name": "Plug 16A,3P TTS-A136-6 IP67", "category": "Plug", "subcategory": "Industrial Plug", "sku": "014300010-Plug 16A,3P TTS-A136-6 IP67", "description": "Plug"},
        {"name": "Panel Mounted Socket 32A,3P TTS-B2361-6 IP67", "category": "Sockets", "subcategory": "Panel Mounted Sockets", "sku": "014300048-Socket 32A,3P TTS-B2361-6 IP67", "description": "Panel Mounted Sockets"},
        {"name": "Plug 32A,3P TTS-A236-6 IP67", "category": "Plug", "subcategory": "Industrial Plug", "sku": "014300050-Plug 32A,3P TTS-A236-6 IP67", "description": "Plug"},
        {"name": "Panel Mounted Socket 63A,3P TTS-B3361-6 IP67", "category": "Sockets", "subcategory": "Panel Mounted Sockets", "sku": "014300068-Socket 63A,3P TTS-B3361-6 IP67", "description": "Panel Mounted Sockets"},
        {"name": "Plug 63A,3P TTS-A336-6 IP67", "category": "Plug", "subcategory": "Industrial Plug", "sku": "014-300069-Plug 63A,3P TTS-A336-6 IP67", "description": "Plug"},
        {"name": "Fuse Holder 32A 1000V", "category": "Fuse Holder", "subcategory": "Fuse Accessories", "sku": "011709980 - TT PV FUSE HOLDER 32A 1000V", "description": "Fuse Holder"},
        {"name": "Fuse PV10-32A-38", "category": "Fuse", "subcategory": "Fuse Links", "sku": "039926800-PV10-32A-38", "description": "Fuse"},
        {"name": "LEV DC 2W/3W CONNECTOR", "category": "EV Changer", "subcategory": "EV Connectors", "sku": "011716389-TTEV50A-60VDC-T6-7C2", "description": "EV Changer"},
        {"name": "AC TYPE 2 CONNECTOR", "category": "EV Changer", "subcategory": "EV Connectors", "sku": "011710084-TTEV32A-3P5T2", "description": "EV Changer"},
        {"name": "DC CCS-2 CHARGING CONNECTOR", "category": "EV Changer", "subcategory": "EV Connectors", "sku": "011710077-TTEV-200ADC-CCS", "description": "EV Changer"},
        {"name": "Transformer Online dryout System", "category": "Filteration", "subcategory": "Filteration", "sku": "TODOS", "description": "Online dryout boosts transformer lifespan"},
        {"name": "Transformer Offline Filteration Machine", "category": "Filteration", "subcategory": "Filteration", "sku": "TOFT", "description": "Offline filtration restores transformer oil"},
        {"name": "Nitrogen Injection Fire Protection System", "category": "Transformer Safety", "subcategory": "Transformer Safety", "sku": "NIFPS", "description": "Nitrogen system protects transformers from fires"}
    ]

    # -----------------------------
    # 2. Load products from file
    # -----------------------------
    with open(filepath, "r", encoding="utf-8") as f:
        file_data = json.load(f)

    # -----------------------------
    # 3. Merge BOTH lists
    # -----------------------------
    products_data = existing_data + file_data

    # -----------------------------
    # 4. Insert/Update in DB
    # -----------------------------
    for p in products_data:
        category_id = category_ids.get(p["category"])
        subcategory_id = subcategory_ids.get(p["subcategory"])

        existing = session.query(Product).filter_by(sku=p["sku"]).first()

        if not existing:
            product = Product(
                name=p["name"],
                category_id=category_id,
                subcategory_id=subcategory_id,
                sku=p["sku"],
                description=p.get("description", ""),
                is_active=True
            )
            session.add(product)

        else:
            existing.name = p["name"]
            existing.category_id = category_id
            existing.subcategory_id = subcategory_id
            existing.description = p.get("description", "")
            existing.is_active = True

    session.commit()
    print("[OK] Existing data + file data seeded successfully.")
    

def seed_cities(session, state_ids, filepath="city.json"):
    """
    Seed cities from city.json.
    state_ids: a dict mapping state names to their IDs
    """
    with open(filepath, "r", encoding="utf-8") as f:
        file_data = json.load(f)

    for c in file_data:
        state_id = state_ids.get(c["statename"])
        if not state_id:
            print(f"[WARN] State '{c['statename']}' not found. Skipping city '{c['name']}'.")
            continue

        existing = session.query(City).filter_by(name=c["name"], state_id=state_id).first()

        if not existing:
            city = City(
                name=c["name"],
                state_id=state_id,
                erp_sync_status="pending",
                erp_external_id=c["erp_external_id"]
            )
            session.add(city)
        else:
            existing.state_id = state_id
            existing.erp_sync_status = "pending"

    session.commit()
    print("[OK] Cities seeded successfully.")


# ----------------- Testing Request System Seed -----------------

def seed_test_type_categories(session, master_ids):
    """
    Seeds Equipment types as CategoryMaster rows and
    Test types as CategoryDetails rows linked to their parent equipment.
    Description='Testing Equipment' tags these masters for filtering.
    """

    # Updated structure: equipment types now have types grouped by request category
    # Per SRS: test, maintenance, inspection, repair_lifecycle all need type dropdowns
    equipment_tests = {
        # ── From user's Equipment → Test mapping (legacy, kept for backward compat) ──
        "Feeder protection relays": [
            "Relay Testing Report",
        ],
        "Power transformers": [
            "Differential Protection Test",
        ],
        "Transformer differential relay": [
            "Stability / Bias Test",
        ],
        "Protection relays": [
            "Protection Relay Functional Test",
        ],
        "Current transformers": [
            "Insulation Resistance (IR) Test",
            "CT Ratio Test",
            "Core Insulation Test",
        ],
        "Protection system": [
            "Transformer Protection Commissioning",
        ],
        "Feeder Metering": [
            "Energy meter accuracy test",
        ],
        "Transformer": [
            "Physical inspection",
            "Insulation resistance test",
            "Transformer ratio test",
            "Current ratio test",
            "Short circuit test",
            "Open circuit test",
            "Magnetic balance test",
        ],
        # ── Additional equipment from KPTCL flow (PDF) ──
        "Relay": [
            "Relay Testing",
        ],
        "Meter": [
            "Meter Testing",
        ],
        # ── Power Transformer (from HTML mockups) ──
        "Power Transformer": [
            "Power Transformer Nameplate Details",
            "Transformer Physical Inspection",
            "Ratio Test HV-IV",
            "Ratio Test HV-LV",
            "Short Circuit Test HV-IV",
            "Short Circuit Test HV-LV",
            "Magnetic Balance Test HV",
            "Magnetic Balance Test IV",
            "Magnetic Balance Test LV",
            "Open Circuit Test HV-IV (1Ph)",
            "Open Circuit Test HV-IV (3Ph)",
            "Open Circuit Test HV-LV (1Ph)",
            "Open Circuit Test HV-LV (3Ph)",
            "Open Circuit Test IV-LV (1Ph)",
            "Open Circuit Test IV-LV (3Ph)",
            "Capacitance & Tan Delta Test (Transformer)",
            "Capacitance & Tan Delta Comparison",
        ],
        # ── Current Transformer (additional tests from HTML mockups) ──
        "Current Transformer": [
            "CT Insulation Test",
            "CT Ratio Test (Detailed)",
            "Capacitance & Tan Delta Test (CT)",
            "Tan Delta NCT Test",
        ],
        # ── CVT (new equipment type from HTML mockups) ──
        "CVT": [
            "CVT Test Report",
        ],
    }

    # ── NEW: Category-based types structure (SRS-compliant) ──
    # Power Transformer with all 4 categories defined
    equipment_types_by_category = {
        "Power Transformer": {
            "test": [
                "Power Transformer Nameplate Details",
                "Transformer Physical Inspection",
                "Ratio Test HV-IV",
                "Ratio Test HV-LV",
                "Short Circuit Test HV-IV",
                "Short Circuit Test HV-LV",
                "Magnetic Balance Test HV",
                "Magnetic Balance Test IV",
                "Magnetic Balance Test LV",
                "Open Circuit Test HV-IV (1Ph)",
                "Open Circuit Test HV-IV (3Ph)",
                "Open Circuit Test HV-LV (1Ph)",
                "Open Circuit Test HV-LV (3Ph)",
                "Open Circuit Test IV-LV (1Ph)",
                "Open Circuit Test IV-LV (3Ph)",
                "Capacitance & Tan Delta Test (Transformer)",
                "Capacitance & Tan Delta Comparison",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
                "Power Transformer Major Maintenance",
                "OLTC Operations Count",              # cumulative tap-change tracking
            ],
            "inspection": [
                "Electrical Safety",
                "Civil",
                "Fire Safety",
                "Documentation",
                "Environmental",
                "General Maintenance",
            ],
            "repair_lifecycle": [
                "S1: Failure Report",
                "S2: Repair Committee",
                "S3: Allotment to Repairer",
                "S4: Lifting by Repairer",
                "S5: Joint Inspection at Vendor",
                "S6: Estimate & Revised Work Award",
                "S7: Stage Inspections",
                "S8: Final Inspection",
                "S9: Dispatch",
                "S10: Erection, Testing & Commissioning",
            ],
        },
        "Circuit Breaker": {
            "test": [
                "Contact Resistance Test",
                "Insulation Resistance Test",
                "SF6 Gas Pressure Test",
                "SF6 Gas Purity Test",
                "Travel and Timing Test",
                "Minimum Trip Voltage Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
                "Circuit Breaker Major Maintenance",
                "Circuit Breaker Operations Count",   # cumulative ops tracking
            ],
            "inspection": [
                "Electrical Safety",
                "Civil",
                "Fire Safety",
                "Documentation",
                "Environmental",
                "General Maintenance",
            ],
           
        },
        # ── Protection Relay ─────────────────────────────────────────────────
        "Protection Relay": {
            "test": [
                "Protection Relay Functional Test",
            ],
            "maintenance": [
                "Protection Relay Calibration and History",  # calibration lifecycle
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
        },
        # ── Electronic Tri-vector Meter ──────────────────────────────────────
        "Electronic Tri-vector Meter": {
            "test": [
                "Meter Testing",
            ],
            "maintenance": [
                "Electronic Tri-vector Meter Calibration",  # calibration lifecycle
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
        },
        # ── Lightning Arrester ───────────────────────────────────────────────
        "Lightning Arrester": {
            "test": [
                "Insulation Resistance / Leakage Current Test",
                "V-I Characteristic Test",
                "Power Frequency Voltage Withstand Test",
            ],
            "maintenance": [
                "Routine Visual Inspection",
                "LA Major Maintenance",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
            "repair_lifecycle": [
                "S1: Failure Report",
                "S2: Repair Committee",
                "S3: Replacement / Repair",
            ],
        },
        # ── Battery Bank ─────────────────────────────────────────────────────
        "Battery Bank": {
            "test": [
                "Specific Gravity Check",
                "Float Voltage per Cell",
                "Discharge / Capacity Test",
                "Electrolyte Level Check",
                "Terminal Voltage Measurement",
            ],
            "maintenance": [
                "Routine Battery Maintenance",
                "Battery Bank Major Maintenance",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
                "Environmental",
            ],
            "repair_lifecycle": [
                "S1: Failure Report",
                "S2: Battery Replacement",
            ],
        },
    }

    # ── Dedicated lifecycle masters (NOT under "Testing Equipment") ──────────
    # These are fetched via GET /testing_requests/lifecycle-types, not mixed
    # into the equipment-type dropdown.
    lifecycle_masters = {
        "Calibration Lifecycle": {
            "description": "Calibration Lifecycle",
            "details": [
                "Protection Relay Calibration and History",
                "Electronic Tri-vector Meter Calibration",
            ],
        },
        "Cumulative Lifecycle": {
            "description": "Cumulative Lifecycle",
            "details": [
                "Circuit Breaker Operations Count",
                "OLTC Operations Count",
            ],
        },
    }

    for master_name, cfg in lifecycle_masters.items():
        lm = session.query(CategoryMaster).filter_by(name=master_name).first()
        if not lm:
            lm = CategoryMaster(
                name=master_name,
                description=cfg["description"],
                is_active=True,
            )
            session.add(lm)
            session.flush()
        else:
            lm.description = cfg["description"]
            lm.is_active = True

        for detail_name in cfg["details"]:
            existing_d = session.query(CategoryDetails).filter_by(
                name=detail_name,
                category_master_id=lm.id,
            ).first()
            if not existing_d:
                session.add(CategoryDetails(
                    name=detail_name,
                    description=f"Lifecycle test type: {detail_name}",
                    category_type="maintenance",
                    category_master_id=lm.id,
                    is_active=True,
                ))
            else:
                existing_d.category_type = "maintenance"
                existing_d.is_active = True

    session.flush()

    for equipment_name, test_list in equipment_tests.items():
        # ---- upsert CategoryMaster (Equipment) ----
        existing_master = session.query(CategoryMaster).filter_by(name=equipment_name).first()
        if not existing_master:
            master = CategoryMaster(
                name=equipment_name,
                description="Testing Equipment",
                is_active=True,
            )
            session.add(master)
            session.flush()
            master_id = master.id
        else:
            existing_master.description = "Testing Equipment"
            existing_master.is_active = True
            master_id = existing_master.id

        master_ids[equipment_name] = master_id

        # ---- upsert CategoryDetails (Test Types) ----
        for test_name in test_list:
            existing_detail = session.query(CategoryDetails).filter_by(
                name=test_name,
                category_master_id=master_id,
            ).first()
            if not existing_detail:
                session.add(CategoryDetails(
                    name=test_name,
                    description=f"Test for {equipment_name}",
                    category_type="test",
                    category_master_id=master_id,
                    is_active=True,
                ))
            else:
                existing_detail.is_active = True
                existing_detail.category_type = "test"

    # ── Seed category-based types (new SRS-compliant structure) ──
    for equipment_name, categories in equipment_types_by_category.items():
        # Get or create equipment master
        existing_master = session.query(CategoryMaster).filter_by(name=equipment_name).first()
        if not existing_master:
            master = CategoryMaster(
                name=equipment_name,
                description="Testing Equipment",
                is_active=True,
            )
            session.add(master)
            session.flush()
            master_id = master.id
        else:
            master_id = existing_master.id

        master_ids[equipment_name] = master_id

        # Add types for each category (test, maintenance, inspection, repair_lifecycle)
        for category_type, type_list in categories.items():
            for type_name in type_list:
                # Check if this type already exists
                existing_detail = session.query(CategoryDetails).filter_by(
                    name=type_name,
                    category_master_id=master_id,
                ).first()

                if not existing_detail:
                    # Create new CategoryDetail with category_type
                    detail = CategoryDetails(
                        name=type_name,
                        description=f"{category_type.replace('_', ' ').title()} for {equipment_name}",
                        category_type=category_type,
                        category_master_id=master_id,
                        is_active=True,
                    )
                    session.add(detail)
                else:
                    existing_detail.is_active = True
                    # Update description and category_type
                    existing_detail.description = f"{category_type.replace('_', ' ').title()} for {equipment_name}"
                    existing_detail.category_type = category_type

    session.commit()
    print("[OK] Equipment & Test Type categories seeded successfully.")
    print("[OK] Category-based types (maintenance, inspection, repair_lifecycle) seeded.")

    # ── Nameplate test types (one "Nameplate" CategoryDetails per equipment type) ──
    nameplate_created = 0
    for equipment_name in NAMEPLATE_TYPE_TO_TEMPLATE:
        existing_master = session.query(CategoryMaster).filter_by(name=equipment_name).first()
        if not existing_master:
            master = CategoryMaster(
                name=equipment_name,
                description="Testing Equipment",
                is_active=True,
            )
            session.add(master)
            session.flush()
            master_id = master.id
        else:
            master_id = existing_master.id
        master_ids[equipment_name] = master_id

        existing_detail = session.query(CategoryDetails).filter_by(
            name="Nameplate",
            category_master_id=master_id,
        ).first()
        if not existing_detail:
            session.add(CategoryDetails(
                name="Nameplate",
                description=f"Nameplate data entry for {equipment_name}",
                category_type="nameplate",
                category_master_id=master_id,
                is_active=True,
            ))
            nameplate_created += 1
        else:
            existing_detail.is_active = True
            existing_detail.category_type = "nameplate"

    session.commit()
    print(f"[OK] Nameplate test types seeded: {nameplate_created} new entries.")

    # ── Priority master ──
    priority_master_name = "Testing Priority"
    existing_pm = session.query(CategoryMaster).filter_by(name=priority_master_name).first()
    if not existing_pm:
        pm = CategoryMaster(name=priority_master_name, description="Testing Priority", is_active=True)
        session.add(pm)
        session.flush()
        pm_id = pm.id
    else:
        existing_pm.description = "Testing Priority"
        pm_id = existing_pm.id
    master_ids[priority_master_name] = pm_id

    for p in ["Low", "Normal", "Medium", "High", "Critical"]:
        existing_p = session.query(CategoryDetails).filter_by(name=p, category_master_id=pm_id).first()
        if not existing_p:
            session.add(CategoryDetails(name=p, description=f"{p} priority", category_master_id=pm_id, is_active=True))

    # ── Transformer Rating master ──
    rating_master_name = "Transformer Rating"
    existing_rm = session.query(CategoryMaster).filter_by(name=rating_master_name).first()
    if not existing_rm:
        rm = CategoryMaster(name=rating_master_name, description="Transformer Rating", is_active=True)
        session.add(rm)
        session.flush()
        rm_id = rm.id
    else:
        existing_rm.description = "Transformer Rating"
        rm_id = existing_rm.id
    master_ids[rating_master_name] = rm_id

    for r in ["5 kVA", "10 kVA", "16 kVA", "25 kVA", "63 kVA", "100 kVA", "200 kVA",
              "315 kVA", "500 kVA", "1 MVA", "2 MVA", "5 MVA", "10 MVA",
              "20 MVA", "31.5 MVA", "50 MVA", "100 MVA", "160 MVA", "315 MVA"]:
        existing_r = session.query(CategoryDetails).filter_by(name=r, category_master_id=rm_id).first()
        if not existing_r:
            session.add(CategoryDetails(name=r, description=f"Rating {r}", category_master_id=rm_id, is_active=True))

    session.commit()
    print("[OK] Priority & Transformer Rating categories seeded successfully.")

    # ── Organizational Hierarchy dropdowns ──
    org_hierarchy = {
        "KPTCL Zone": [
            "Bangalore Zone",
            "Gulbarga Zone",
            "Hubli Zone",
            "Mysore Zone",
        ],
        "CE Circle": [
            "BMAZ North",
            "BMAZ South",
            "BRAZ",
            "CTAZ",
            "O&M Zone Hubballi",
            "Belagavi Zone",
            "Mangaluru Zone",
            "Shivamogga Zone",
            "Mysuru Zone",
            "Hassan Zone",
            "Gulbarga Zone",
            "Bellary Zone",
        ],
        "SE Division": [
            "Bangalore Urban Division",
            "Bangalore Rural Division",
            "Tumkur Division",
            "Ramanagara Division",
            "Mysuru Division",
            "Mandya Division",
            "Hassan Division",
            "Hubli Division",
            "Dharwad Division",
            "Belagavi Division",
            "Gulbarga Division",
            "Raichur Division",
            "Bellary Division",
        ],
        "EE Sub-Division": [
            "TL & SS Sub-Division 1",
            "TL & SS Sub-Division 2",
            "TL & SS Sub-Division 3",
            "TL & SS Sub-Division 4",
            "TL & SS Sub-Division 5",
        ],
        "AEE Section": [
            "SS Section 1",
            "SS Section 2",
            "SS Section 3",
            "SS Section 4",
            "SS Section 5",
        ],
        "AE-JE Maintenance": [
            "AE Maintenance 1",
            "AE Maintenance 2",
            "JE Maintenance 1",
            "JE Maintenance 2",
            "JE Maintenance 3",
        ],
    }

    for master_name, details_list in org_hierarchy.items():
        existing_m = session.query(CategoryMaster).filter_by(name=master_name).first()
        if not existing_m:
            m = CategoryMaster(name=master_name, description=master_name, is_active=True)
            session.add(m)
            session.flush()
            m_id = m.id
        else:
            existing_m.description = master_name
            m_id = existing_m.id
        master_ids[master_name] = m_id

        for detail_name in details_list:
            existing_d = session.query(CategoryDetails).filter_by(name=detail_name, category_master_id=m_id).first()
            if not existing_d:
                session.add(CategoryDetails(name=detail_name, description=master_name, category_master_id=m_id, is_active=True))

    session.commit()
    print("[OK] Organizational hierarchy categories seeded successfully.")


def seed_sample_testing_request(session):
    """Seeds a sample testing request in draft status for demo purposes."""
    from models import TestingRequest, TestingRequestStatus

    existing = session.query(TestingRequest).filter_by(request_number="TR-20260313-0001").first()
    if existing:
        print("[INFO] Sample testing request already exists.")
        return

    originator = session.query(User).filter_by(email="originator@relu.com").first()
    if not originator:
        print("[WARN] Originator user not found. Skipping sample testing request.")
        return

    request = TestingRequest(
        request_number="TR-20260313-0001",
        title="11kV Distribution Transformer 100kVA - Routine Testing",
        description="Routine testing required for newly procured 11kV 100kVA distribution transformer before deployment.",
        transformer_type="Distribution Transformer",
        transformer_rating="100 kVA",
        manufacturer="Sample Manufacturer Ltd",
        serial_number="DT-2026-001",
        status=TestingRequestStatus.draft,
        priority="normal",
        originator_id=originator.id,
        created_by=originator.id,
    )
    session.add(request)
    session.commit()
    print("[OK] Sample testing request seeded.")


# ----------------- Migrate Equipment Asset Register -----------------

def migrate_equipment_register(session):
    """Create equipment table and add equipment_id, request_category, evaluation_result columns."""
    from sqlalchemy import text
    try:
        # Create equipment table
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public.equipment (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                ueic VARCHAR(50) NOT NULL UNIQUE,
                organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
                department_id UUID NOT NULL REFERENCES public.org_departments(id) ON DELETE CASCADE,
                equipment_type_id INTEGER NOT NULL REFERENCES public."CategoryMaster"(id),
                voltage_class VARCHAR(10),
                bay_number VARCHAR(10),
                serial_in_bay VARCHAR(10),
                nameplate_data JSONB,
                status VARCHAR(20) NOT NULL DEFAULT 'active',
                replaces_equipment_id UUID REFERENCES public.equipment(id),
                commissioned_date TIMESTAMPTZ,
                retired_date TIMESTAMPTZ,
                retirement_reason TEXT,
                manufacturer VARCHAR(255),
                model_number VARCHAR(255),
                factory_serial_number VARCHAR(100),
                year_of_manufacture INTEGER,
                created_by UUID REFERENCES public.users(id),
                modified_by UUID REFERENCES public.users(id),
                cts TIMESTAMPTZ DEFAULT now(),
                mts TIMESTAMPTZ DEFAULT now()
            );
        """))

        # Create indexes on equipment table
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_equipment_org ON public.equipment(organization_id);
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_equipment_dept ON public.equipment(department_id);
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_equipment_type ON public.equipment(equipment_type_id);
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_equipment_status ON public.equipment(status);
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_equipment_ueic ON public.equipment(ueic);
        """))

        # Add equipment_id to testing_requests
        session.execute(text("""
            ALTER TABLE public.testing_requests
            ADD COLUMN IF NOT EXISTS equipment_id UUID REFERENCES public.equipment(id);
        """))

        # Add request_category to testing_requests
        session.execute(text("""
            ALTER TABLE public.testing_requests
            ADD COLUMN IF NOT EXISTS request_category VARCHAR(20) DEFAULT 'test';
        """))

        # Add evaluation_result to test_results
        session.execute(text("""
            ALTER TABLE public.test_results
            ADD COLUMN IF NOT EXISTS evaluation_result JSONB;
        """))

        session.commit()
        print("[OK] Equipment register table + columns migrated successfully.")
    except Exception as e:
        session.rollback()
        print(f"[WARN] Equipment migration skipped or failed: {e}")


# ----------------- Migrate Schema -----------------

def migrate_testing_request_columns(session):
    """Add columns to testing_requests and create tester_locations table if missing."""
    from sqlalchemy import text
    try:
        session.execute(text("""
            ALTER TABLE public.testing_requests
            ADD COLUMN IF NOT EXISTS equipment_type_id INTEGER
            REFERENCES public."CategoryMaster"(id);
        """))
        session.execute(text("""
            ALTER TABLE public.testing_requests
            ADD COLUMN IF NOT EXISTS test_type_id INTEGER
            REFERENCES public."CategoryDetails"(id);
        """))
        # Organizational hierarchy columns
        for col in ["zone", "ce_circle", "se_division", "ee_subdivision", "aee_section", "ae_je"]:
            session.execute(text(f"""
                ALTER TABLE public.testing_requests
                ADD COLUMN IF NOT EXISTS {col} VARCHAR(255);
            """))
        # Create tester_locations mapping table
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS public.tester_locations (
                id SERIAL PRIMARY KEY,
                user_id UUID NOT NULL REFERENCES public.users(id),
                zone VARCHAR(255),
                ce_circle VARCHAR(255),
                se_division VARCHAR(255),
                ee_subdivision VARCHAR(255),
                is_active BOOLEAN DEFAULT TRUE
            );
        """))
        session.commit()
        print("[OK] testing_requests columns + tester_locations table migrated.")
    except Exception as e:
        session.rollback()
        print(f"[WARN] Migration skipped or failed: {e}")


def seed_tester_locations(session):
    """Seeds tester-to-location mappings in tester_locations table."""
    from models import TesterLocation

    tester_mappings = [
        {"email": "tester@relu.com", "zone": "Bangalore Zone", "ce_circle": "BMAZ North",
         "se_division": "Bangalore Urban Division", "ee_subdivision": "TL & SS Sub-Division 1"},
        {"email": "tester.bmaz.north@relu.com", "zone": "Bangalore Zone", "ce_circle": "BMAZ North",
         "se_division": "Bangalore Urban Division", "ee_subdivision": "TL & SS Sub-Division 1"},
        {"email": "tester.bmaz.south@relu.com", "zone": "Bangalore Zone", "ce_circle": "BMAZ South",
         "se_division": "Bangalore Rural Division", "ee_subdivision": "TL & SS Sub-Division 2"},
        {"email": "tester.braz@relu.com", "zone": "Bangalore Zone", "ce_circle": "BRAZ",
         "se_division": "Tumkur Division", "ee_subdivision": "TL & SS Sub-Division 3"},
        {"email": "tester.hubli@relu.com", "zone": "Hubli Zone", "ce_circle": "O&M Zone Hubballi",
         "se_division": "Hubli Division", "ee_subdivision": "TL & SS Sub-Division 1"},
        {"email": "tester.belagavi@relu.com", "zone": "Hubli Zone", "ce_circle": "Belagavi Zone",
         "se_division": "Belagavi Division", "ee_subdivision": "TL & SS Sub-Division 2"},
        {"email": "tester.mysuru@relu.com", "zone": "Mysore Zone", "ce_circle": "Mysuru Zone",
         "se_division": "Mysuru Division", "ee_subdivision": "TL & SS Sub-Division 1"},
        {"email": "tester.gulbarga@relu.com", "zone": "Gulbarga Zone", "ce_circle": "Gulbarga Zone",
         "se_division": "Gulbarga Division", "ee_subdivision": "TL & SS Sub-Division 1"},
        {"email": "tester.bellary@relu.com", "zone": "Gulbarga Zone", "ce_circle": "Bellary Zone",
         "se_division": "Bellary Division", "ee_subdivision": "TL & SS Sub-Division 2"},
    ]

    for tm in tester_mappings:
        user = session.query(User).filter_by(email=tm["email"]).first()
        if not user:
            continue
        existing = session.query(TesterLocation).filter_by(user_id=user.id).first()
        if not existing:
            session.add(TesterLocation(
                user_id=user.id,
                zone=tm["zone"],
                ce_circle=tm["ce_circle"],
                se_division=tm["se_division"],
                ee_subdivision=tm["ee_subdivision"],
                is_active=True,
            ))
        else:
            existing.zone = tm["zone"]
            existing.ce_circle = tm["ce_circle"]
            existing.se_division = tm["se_division"]
            existing.ee_subdivision = tm["ee_subdivision"]
            existing.is_active = True

    session.commit()
    print("[OK] Tester-location mappings seeded successfully.")


# ----------------- Organization System Seed -----------------

def seed_role_templates(session):
    """
    Seed role templates for auto-provisioning default roles to new organizations.
    """
    # Get all modules with their details
    all_modules = session.query(Module).filter(Module.is_active == True).all()

    if not all_modules:
        print("[WARN] No modules found. Role templates will be created without permission templates.")

    # Build module lookup by group and name
    modules_by_group = {}
    modules_by_name = {}
    for mod in all_modules:
        if mod.group_name:
            modules_by_group.setdefault(mod.group_name, []).append(mod.id)
        if mod.name:
            modules_by_name[mod.name] = mod.id

    # Get all module IDs (for Admin role only)
    all_module_ids = [m.id for m in all_modules]

    # Define module sets for different roles
    # Testing group modules
    testing_modules = modules_by_group.get("Testing", [])

    # Procurement modules (by name)
    procurement_module_names = [
        "Request Quote", "RQ with Vendor", "Request Product", "Quotes",
        "Sales Orders", "Invoices", "Retainer Invoices", "Payments Made",
        "Statements", "Enquiry", "Contact Us"
    ]
    procurement_modules = [modules_by_name.get(name) for name in procurement_module_names if modules_by_name.get(name)]

    # Organization modules
    org_modules = modules_by_group.get("Organization", [])

    # Dashboard (should be accessible to everyone)
    dashboard_module = [modules_by_name.get("Dashboard")] if modules_by_name.get("Dashboard") else []

    # Role-specific dashboard module IDs
    ee_tlss_dashboard_module_id = modules_by_name.get("EE TLSS Dashboard")
    aee_dashboard_module_id = modules_by_name.get("AEE Dashboard")
    see_dashboard_module_id = modules_by_name.get("SEE Dashboard")
    cee_dashboard_module_id = modules_by_name.get("CEE Dashboard")
    admin_dashboard_module_id = modules_by_name.get("Admin Dashboard")

    # ── Named module-set shortcuts ─────────────────────────────────────────
    # Procurement modules (without Dashboard — added individually where needed)
    procurement_module_names = [
        "Request Quote", "RQ with Vendor", "Request Product", "Quotes",
        "Sales Orders", "Invoices", "Retainer Invoices", "Payments Made",
        "Statements", "Enquiry", "Contact Us"
    ]
    procurement_modules = [modules_by_name[n] for n in procurement_module_names if n in modules_by_name]

    # Org-management modules
    org_module_names = ["Organizations", "Organization User Roles", "Organization Role Permissions"]
    org_modules = [modules_by_name[n] for n in org_module_names if n in modules_by_name]

    # Testing-specific modules (by name, so we can pick individual ones)
    testing_requests_module  = [mid for mid in [modules_by_name.get("Testing Requests")] if mid]
    testing_module           = [mid for mid in [modules_by_name.get("Testing")] if mid]
    testing_request_approvals_module = [mid for mid in [modules_by_name.get("Testing Request Approvals")] if mid]
    recommendations_module   = [mid for mid in [modules_by_name.get("Recommendations")] if mid]
    approvals_module         = [mid for mid in [modules_by_name.get("Approvals")] if mid]
    workflows_module         = [mid for mid in [modules_by_name.get("Workflows")] if mid]
    repair_workflows_module  = [mid for mid in [modules_by_name.get("Repair Workflows")] if mid]

    dashboard_module = [mid for mid in [modules_by_name.get("Dashboard")] if mid]

    def _full(mids):
        """Full read/write/delete/approve/assign permissions for a list of module_ids."""
        return [{"module_id": m, "can_view": True, "can_add": True, "can_edit": True,
                 "can_delete": True, "can_approve": True, "can_assign": True,
                 "can_export": True, "can_import": True} for m in mids]

    def _readwrite(mids):
        """Read + write (no delete / approve / assign) permissions."""
        return [{"module_id": m, "can_view": True, "can_add": True, "can_edit": True,
                 "can_delete": False, "can_approve": False, "can_assign": False,
                 "can_export": True, "can_import": False} for m in mids]

    def _readonly(mids):
        """View-only permissions."""
        return [{"module_id": m, "can_view": True, "can_add": False, "can_edit": False,
                 "can_delete": False, "can_approve": False, "can_assign": False,
                 "can_export": False, "can_import": False} for m in mids]

    def _approve(mids):
        """View + approve permissions (for approval-workflow roles)."""
        return [{"module_id": m, "can_view": True, "can_add": False, "can_edit": False,
                 "can_delete": False, "can_approve": True, "can_assign": True,
                 "can_export": True, "can_import": False} for m in mids]

    # Super Admin modules: everything the Excel column lists
    vendor_documents_module = [mid for mid in [modules_by_name.get("Vendor Documents")] if mid]
    equipment_module = [mid for mid in [modules_by_name.get("Equipment")] if mid]

    super_admin_modules = list({
        *dashboard_module,
        *procurement_modules,
        *testing_requests_module,
        *testing_module,
        *recommendations_module,
        *approvals_module,
        *testing_request_approvals_module,
        *org_modules,
        *workflows_module,
        *equipment_module,
    })

    templates_data = [
        # ── 1. Admin (Super Admin) — full access to all modules ──────────────
        {
            "name": "Admin",
            "description": "Super admin with full access to all modules including org management, testing, procurement, and workflows.",
            "is_org_admin": True,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": admin_dashboard_module_id,
            "permissions_template": _full(all_module_ids),
        },
        # ── 2. Org Admin — manages org structure only ─────────────────────────
        {
            "name": "Org Admin",
            "description": "Manages organization structure: users, roles, and departments. No access to testing or procurement.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": _full(org_modules),
        },
        # ── 3. Originator — procurement + testing requests + equipment + repair ─
        {
            "name": "Originator",
            "description": "Creates testing requests and raises procurement. Can start repair workflows.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _readwrite(procurement_modules) +
                _readwrite(testing_requests_module) +
                _readwrite(equipment_module) +
                _readwrite(repair_workflows_module)
            ),
        },
        # ── 4. Test Assigner (Approver) — testing request approvals + equipment view
        {
            "name": "Test Assigner",
            "description": "Approves testing requests and assigns testers. Access to Testing Request Approvals module and view equipment register.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _approve(testing_request_approvals_module) +
                _readonly(equipment_module)
            ),
        },
        # ── 5. Field Tester — testing + repair stage execution ────────────────
        {
            "name": "Field Tester",
            "description": "Performs on-site transformer testing and repair stage execution.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readonly(testing_requests_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module) +
                _readwrite(repair_workflows_module)
            ),
        },
        # ── 6. Lab Tester — lab testing + repair stage execution ──────────────
        {
            "name": "Lab Tester",
            "description": "Performs laboratory testing and repair stage execution.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readonly(testing_requests_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module) +
                _readwrite(repair_workflows_module)
            ),
        },
        # ── 7. Department Head — recommendations + approvals + repair approve ─
        {
            "name": "Department Head",
            "description": "Reviews and approves recommendations from testers. Can approve repair workflow stages.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": True,
            "permissions_template": (
                _approve(recommendations_module) +
                _approve(approvals_module) +
                _readonly(equipment_module) +
                _approve(repair_workflows_module)
            ),
        },
        # ── 8. Purchaser — procurement + repair view ───────────────────────────
        {
            "name": "Purchaser",
            "description": "Manages procurement activities. Read-only access to repair workflows (procurement stage).",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _readwrite(procurement_modules) +
                _readwrite(repair_workflows_module)
            ),
        },

        # ── 9. Doc Viewer — verifies uploaded documents ───────────────────────
        {
            "name": "doc-viewer",
            "description": "Verifies vendor uploaded documents. Access to Vendor Documents module only.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": _readonly(vendor_documents_module),
        },

        # ═══════════════════════════════════════════════════════════════════════════
        # SRS-SPECIFIED DESIGNATION ROLES (SEACMS-AI v1.3 Section 2.3)
        # ═══════════════════════════════════════════════════════════════════════════

        # ── 10. AEE Maintenance — Field supervisor + repair stage executor ─────
        {
            "name": "AEE Maintenance",
            "description": "Assistant Executive Engineer - Field-level maintenance responsible officer. Key repair workflow actor.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": aee_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _readonly(testing_requests_module) +
                _approve(approvals_module) +
                _readonly(recommendations_module) +
                _readwrite(repair_workflows_module)
            ),
        },

        # ── 11. EE TLSS — Primary reviewer + repair stage approver ───────────
        {
            "name": "EE TLSS",
            "description": "Executive Engineer - Transmission Line & Substation primary reviewer. Approves repair workflow stages.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": ee_tlss_dashboard_module_id,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _readwrite(testing_requests_module) +
                _approve(testing_request_approvals_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module) +
                _readonly(procurement_modules) +
                _approve(repair_workflows_module)
            ),
        },

        # ── 12. SEE W&M — Circle supervisor + repair stage approver ──────────
        {
            "name": "SEE W&M",
            "description": "Superintending Engineer - Works & Maintenance circle supervisor. Approves repair workflow stages.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": see_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _approve(approvals_module) +
                _readonly(vendor_documents_module) +
                _readonly(recommendations_module) +
                _readonly(testing_requests_module) +
                _approve(repair_workflows_module)
            ),
        },

        # ── 13. EE RT — R&D engineer + repair stage executor ─────────────────
        {
            "name": "EE RT",
            "description": "Executive Engineer - Research & Testing. Executes repair workflow testing stages.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": ee_tlss_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _readwrite(testing_requests_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module) +
                _readwrite(repair_workflows_module)
            ),
        },

        # ── 14. SEE RT — Senior R&D + repair stage approver ──────────────────
        {
            "name": "SEE RT",
            "description": "Superintending Engineer - Research & Testing. Approves repair workflow testing stages.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": see_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _approve(approvals_module) +
                # Testing Requests: view only — SEE RT is a tester, not an originator
                _readonly(testing_requests_module) +
                _readwrite(testing_module) +
                _approve(testing_request_approvals_module) +
                _readonly(vendor_documents_module) +
                _readonly(equipment_module) +
                _approve(repair_workflows_module)
            ),
        },

        # ── 15. CEE Transmission Zone — Zone management + repair final approver
        {
            "name": "CEE Transmission Zone",
            "description": "Chief Engineer Executive - Transmission zone management. Final approver for repair workflows.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": True,
            "default_module_id": cee_dashboard_module_id,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _approve(approvals_module) +
                _readonly(recommendations_module) +
                _readonly(testing_requests_module) +
                _readonly(procurement_modules) +
                _readonly(vendor_documents_module) +
                _readonly(equipment_module) +
                _approve(repair_workflows_module)
            ),
        },

        # ── 16. CEE RT&R&D — R&D chief + repair final approver ───────────────
        {
            "name": "CEE RT&R&D",
            "description": "Chief Engineer Executive - Research Testing & R&D. Final approver for repair workflow R&D stages.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": True,
            "default_module_id": cee_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _full(testing_module) +
                _readwrite(equipment_module) +
                _readonly(testing_requests_module) +
                _readonly(recommendations_module) +
                _approve(repair_workflows_module)
            ),
        },

        # ── 17. Workflow Coordinator — assigns users to repair workflow stages ──
        {
            "name": "Workflow Coordinator",
            "description": "Assigns users to transformer repair workflow stages and manages the assignment queue",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": ee_tlss_dashboard_module_id,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _readwrite(repair_workflows_module) +
                _readonly(testing_requests_module)
            ),
        },
    ]

    created_count = 0
    updated_count = 0

    for template_data in templates_data:
        existing = session.query(RoleTemplate).filter_by(name=template_data["name"]).first()

        if existing:
            existing.description = template_data["description"]
            existing.is_org_admin = template_data["is_org_admin"]
            existing.is_dept_admin = template_data["is_dept_admin"]
            existing.auto_provision = template_data["auto_provision"]
            existing.default_module_id = template_data.get("default_module_id")
            existing.permissions_template = template_data["permissions_template"]
            existing.mts = datetime.now(datetime.now().astimezone().tzinfo)
            updated_count += 1
        else:
            template = RoleTemplate(
                id=uuid.uuid4(),
                name=template_data["name"],
                description=template_data["description"],
                is_org_admin=template_data["is_org_admin"],
                is_dept_admin=template_data["is_dept_admin"],
                auto_provision=template_data["auto_provision"],
                default_module_id=template_data.get("default_module_id"),
                permissions_template=template_data["permissions_template"],
                cts=datetime.now(datetime.now().astimezone().tzinfo),
                mts=datetime.now(datetime.now().astimezone().tzinfo)
            )
            session.add(template)
            created_count += 1

    session.commit()
    print(f"[OK] Role templates seeded: {created_count} created, {updated_count} updated")


def seed_super_admin(session):
    """
    Create a super admin user if it doesn't exist.
    """
    super_admin_email = "superadmin@system.com"

    existing = session.query(User).filter_by(email=super_admin_email).first()
    if existing:
        # Update existing user to super admin
        existing.usertype = "super_admin"
        existing.isactive = True
        session.commit()
        print(f"[OK] Super admin user updated: {super_admin_email}")
        return existing.id

    # Create new super admin
    super_admin = User(
        id=uuid.uuid4(),
        email=super_admin_email,
        password_hash=get_password_hash("Admin123!"),
        firstname="Super",
        lastname="Admin",
        phone_number="+1234567890",
        usertype="super_admin",
        isactive=True,
        email_confirmed=True,
        phone_confirmed=True
    )
    session.add(super_admin)
    session.commit()
    print(f"[OK] Super admin user created: {super_admin_email} / Admin123!")
    return super_admin.id


def seed_tester_role_module_requirements(session):
    """
    Seed global default configuration for tester role module requirements.
    Defines which modules a role must have FULL permissions on to appear in tester assignment dropdown.
    Always deletes and recreates so module IDs stay correct after a drop-reseed.
    """
    # Always delete and recreate so IDs are always correct (idempotent)
    session.query(TesterRoleModuleRequirement).filter_by(organization_id=None).delete()
    session.flush()

    # Dynamically resolve module IDs by name so they survive any reseed sequence
    # Only modules where testers need FULL permissions (not VIEW-only)
    # Testers only need Testing module - NOT Testing Request Approvals (that's for approvers)
    _tester_req_module_names = [
        "Testing",  # Module 46 - Core testing work module
        # Removed "Testing Request Approvals" - testers don't approve/assign, only perform tests
        # Removed "Testing Requests" (VIEW-only, not FULL)
        # Removed "Tester Mapping" (no longer used)
    ]
    required_ids = []
    for mod_name in _tester_req_module_names:
        mod = session.query(Module).filter_by(name=mod_name, is_active=True).first()
        if mod:
            required_ids.append(mod.id)
        else:
            print(f"[WARN] Module '{mod_name}' not found — excluded from tester requirements")

    if not required_ids:
        print("[WARN] No tester-requirement modules found — skipping TesterRoleModuleRequirement seeding")
        return None

    config = TesterRoleModuleRequirement(
        id=uuid.uuid4(),
        organization_id=None,  # Global default
        required_module_ids=required_ids,
        description=(
            "Global default: Roles must have full permissions (view, add, edit) on "
            "Testing module to qualify as tester roles"
        ),
        is_active=True,
        cts=datetime.now(datetime.now().astimezone().tzinfo),
        mts=datetime.now(datetime.now().astimezone().tzinfo),
    )
    session.add(config)
    session.commit()

    print(f"[OK] Global tester role module requirements seeded: {config.required_module_ids}")
    return config.id


def seed_sample_organization(session):
    """
    Create a sample organization with admin user for testing.
    """
    org_code = "SAMPLE_ORG"

    # Check if organization already exists
    existing_org = session.query(Organization).filter_by(code=org_code).first()
    if existing_org:
        print(f"[INFO] Sample organization already exists: {org_code}")
        org = existing_org
        # Skip organization creation but continue with tester roles/users
        skip_org_creation = True
    else:
        skip_org_creation = False

    now = datetime.now(datetime.now().astimezone().tzinfo)

    if not skip_org_creation:
        # Get a basic plan if available
        basic_plan = session.query(Plan).filter_by(planname="Basic").first()
        plan_id = basic_plan.id if basic_plan else None

        # Create organization
        org = Organization(
            id=uuid.uuid4(),
            name="Sample Organization",
            code=org_code,
            display_name="Sample Org",
            organization_type="vendor",
            industry="Technology",
            primary_email="info@sampleorg.com",
            primary_phone="+1234567890",
            website="https://sampleorg.com",
            address="123 Sample Street",
            city="Sample City",
            state="Sample State",
            country="USA",
            pincode="12345",
            is_active=True,
            is_verified=False,
            plan_id=plan_id,
            subscription_start_date=now,
            subscription_end_date=now + timedelta(days=365),
            settings={},
            created_by=None,
            modified_by=None,
            cts=now,
            mts=now,
            erp_sync_status="pending",
            erp_last_sync_at=None,
            erp_error_message=None,
            erp_external_id=None
        )
        session.add(org)
        session.flush()

    # Provision default roles from templates
    templates = session.query(RoleTemplate).filter_by(auto_provision=True).all()

    provisioned_roles = []
    for template in templates:
        # Skip if role already exists for this org
        existing_role = session.query(OrgRole).filter_by(
            organization_id=org.id, name=template.name
        ).first()
        if existing_role:
            provisioned_roles.append(existing_role)
            continue

        role = OrgRole(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=template.name,
            description=template.description,
            role_type="default",
            is_org_admin=template.is_org_admin,
            is_dept_admin=template.is_dept_admin,
            default_module_id=template.default_module_id,
            is_active=True,
            cts=datetime.now(datetime.now().astimezone().tzinfo),
            mts=datetime.now(datetime.now().astimezone().tzinfo)
        )
        session.add(role)
        session.flush()

        # Save all provisioned roles for later assignment
        provisioned_roles.append(role)

        # Create permissions from template
        if template.permissions_template:
            for perm_data in template.permissions_template:
                permission = OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=perm_data.get("module_id"),
                    can_view=perm_data.get("can_view", False),
                    can_add=perm_data.get("can_add", False),
                    can_edit=perm_data.get("can_edit", False),
                    can_delete=perm_data.get("can_delete", False),
                    can_approve=perm_data.get("can_approve", False),
                    can_assign=perm_data.get("can_assign", False),
                    can_export=perm_data.get("can_export", False),
                    can_import=perm_data.get("can_import", False),
                    cts=datetime.now(datetime.now().astimezone().tzinfo),
                    mts=datetime.now(datetime.now().astimezone().tzinfo)
                )
                session.add(permission)

    # Create org admin user
    admin_email = "orgadmin@sampleorg.com"
    existing_admin = session.query(User).filter_by(email=admin_email).first()

    if not existing_admin:
        admin_user = User(
            id=uuid.uuid4(),
            email=admin_email,
            password_hash=get_password_hash("OrgAdmin123!"),
            firstname="Organization",
            lastname="Admin",
            phone_number="+1987654321",
            organization_id=org.id,
            isactive=True,
            email_confirmed=True,
            phone_confirmed=True
        )
        session.add(admin_user)
        session.flush()

        # Assign Admin role to admin user
        admin_role = next((r for r in provisioned_roles if r.is_org_admin), None)
        if admin_role:
            user_role = OrgUserRole(
                id=uuid.uuid4(),
                user_id=admin_user.id,
                org_role_id=admin_role.id,
                assigned_by=admin_user.id,
                is_active=True
            )
            session.add(user_role)

        session.commit()
        print(f"[OK] Sample organization created: {org_code}")
        print(f"    Admin User: {admin_email} / OrgAdmin123!")
    else:
        # Update existing user and assign Admin role
        existing_admin.organization_id = org.id
        admin_role = next((r for r in provisioned_roles if r.is_org_admin), None)
        if admin_role:
            existing_role = session.query(OrgUserRole).filter_by(
                user_id=existing_admin.id,
                org_role_id=admin_role.id
            ).first()
            if not existing_role:
                user_role = OrgUserRole(
                    id=uuid.uuid4(),
                    user_id=existing_admin.id,
                    org_role_id=admin_role.id,
                    assigned_by=existing_admin.id,
                    is_active=True
                )
                session.add(user_role)
        session.commit()
        print(f"[OK] Sample organization created and linked to existing admin: {admin_email}")

        # Create sample departments
        print(f"[INFO] Creating sample departments for {org_code}")

    # Check if departments already exist
    existing_depts = session.query(OrgDepartment).filter_by(organization_id=org.id).count()
    if existing_depts == 0:
        now = datetime.now(datetime.now().astimezone().tzinfo)

        # Engineering department (root)
        engineering_dept = OrgDepartment(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Engineering",
            code="ENG",
            description="Engineering and Development",
            parent_department_id=None,
            is_active=True,
            cts=now,
            mts=now
        )
        session.add(engineering_dept)
        session.flush()

        # Backend team (child of Engineering)
        backend_dept = OrgDepartment(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Backend Team",
            code="BACKEND",
            description="Backend Development Team",
            parent_department_id=engineering_dept.id,
            is_active=True,
            cts=now,
            mts=now
        )
        session.add(backend_dept)

        # Frontend team (child of Engineering)
        frontend_dept = OrgDepartment(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Frontend Team",
            code="FRONTEND",
            description="Frontend Development Team",
            parent_department_id=engineering_dept.id,
            is_active=True,
            cts=now,
            mts=now
        )
        session.add(frontend_dept)

        # Sales department (root)
        sales_dept = OrgDepartment(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Sales",
            code="SALES",
            description="Sales and Business Development",
            parent_department_id=None,
            is_active=True,
            cts=now,
            mts=now
        )
        session.add(sales_dept)
        session.flush()

        # Inside Sales (child of Sales)
        inside_sales_dept = OrgDepartment(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Inside Sales",
            code="INSIDE_SALES",
            description="Inside Sales Team",
            parent_department_id=sales_dept.id,
            is_active=True,
            cts=now,
            mts=now
        )
        session.add(inside_sales_dept)

        # Human Resources (root)
        hr_dept = OrgDepartment(
            id=uuid.uuid4(),
            organization_id=org.id,
            name="Human Resources",
            code="HR",
            description="Human Resources Department",
            parent_department_id=None,
            is_active=True,
            cts=now,
            mts=now
        )
        session.add(hr_dept)

        session.commit()
        print(f"[OK] Created 6 sample departments (3 root, 3 child)")
    else:
        print(f"[INFO] Sample organization already has {existing_depts} departments")

    # END of organization creation block

    # Create sample tester roles with EXACT module permissions (always run)
    print(f"[INFO] Creating sample tester roles for {org_code}")

    # Dynamically resolve module IDs so they survive any drop-reseed sequence
    _tester_module_names = [
        "Testing Requests",
        "Testing",
        "Testing Request Approvals",
        # Removed "Tester Mapping" - no longer used
    ]
    TESTER_REQUIRED_MODULES = []
    for _mod_name in _tester_module_names:
        _mod = session.query(Module).filter_by(name=_mod_name, is_active=True).first()
        if _mod:
            TESTER_REQUIRED_MODULES.append(_mod.id)
        else:
            print(f"[WARN] Module '{_mod_name}' not found — excluded from tester role permissions")

    tester_roles_config = [
        {
            "name": "Field Tester",
            "description": "Field tester role with exact module permissions for tester assignment"
        },
        {
            "name": "Lab Tester",
            "description": "Laboratory tester role with exact module permissions for tester assignment"
        }
    ]

    tester_roles = []
    for role_config in tester_roles_config:
        # Check if role already exists
        existing_role = session.query(OrgRole).filter_by(
            organization_id=org.id,
            name=role_config["name"]
        ).first()

        if existing_role:
            role = existing_role
            # Clear existing permissions
            session.query(OrgRolePermission).filter_by(org_role_id=role.id).delete()
        else:
            # Create new role
            role = OrgRole(
                id=uuid.uuid4(),
                organization_id=org.id,
                name=role_config["name"],
                description=role_config["description"],
                is_org_admin=False,
                is_dept_admin=False,
                is_active=True,
                cts=now,
                mts=now
            )
            session.add(role)
            session.flush()

        # Add FULL permissions for EXACT modules
        for module_id in TESTER_REQUIRED_MODULES:
            perm = OrgRolePermission(
                id=uuid.uuid4(),
                org_role_id=role.id,
                module_id=module_id,
                can_view=True,
                can_add=True,
                can_edit=True,
                can_delete=True,
                can_approve=True,
                can_assign=True
            )
            session.add(perm)

        tester_roles.append(role)

    session.commit()
    print(f"[OK] Created {len(tester_roles)} sample tester roles with exact module permissions {TESTER_REQUIRED_MODULES}")

    # Create sample tester users
    print(f"[INFO] Creating sample tester users for {org_code}")

    tester_users_config = [
        {
            "email": "fieldtester1@sampleorg.com",
            "password": "Tester123!",
            "role_name": "Field Tester",
            "firstname": "Field",
            "lastname": "Tester One",
            "phone": "9999999001"
        },
        {
            "email": "fieldtester2@sampleorg.com",
            "password": "Tester123!",
            "role_name": "Field Tester",
            "firstname": "Field",
            "lastname": "Tester Two",
            "phone": "9999999002"
        },
        {
            "email": "labtester1@sampleorg.com",
            "password": "Tester123!",
            "role_name": "Lab Tester",
            "firstname": "Lab",
            "lastname": "Tester One",
            "phone": "9999999003"
        },
        {
            "email": "labtester2@sampleorg.com",
            "password": "Tester123!",
            "role_name": "Lab Tester",
            "firstname": "Lab",
            "lastname": "Tester Two",
            "phone": "9999999004"
        }
    ]

    created_users = 0
    for user_config in tester_users_config:
        # Check if user exists
        existing_user = session.query(User).filter_by(email=user_config["email"]).first()

        if existing_user:
            user = existing_user
        else:
            # Create user
            hashed_password = get_password_hash(user_config["password"])
            user = User(
                id=uuid.uuid4(),
                email=user_config["email"],
                password_hash=hashed_password,
                firstname=user_config["firstname"],
                lastname=user_config["lastname"],
                phone_number=user_config["phone"],
                organization_id=org.id,
                isactive=True,
                cts=now,
                mts=now
            )
            session.add(user)
            session.flush()
            created_users += 1

        # Get the role
        role = next((r for r in tester_roles if r.name == user_config["role_name"]), None)
        if not role:
            print(f"[WARN] Role '{user_config['role_name']}' not found for user {user_config['email']}")
            continue

        # Check if user already has this role
        existing_assignment = session.query(OrgUserRole).filter_by(
            user_id=user.id,
            org_role_id=role.id
        ).first()

        if not existing_assignment:
            # Assign role to user
            user_role = OrgUserRole(
                id=uuid.uuid4(),
                user_id=user.id,
                org_role_id=role.id,
                is_active=True
            )
            session.add(user_role)

    session.commit()
    print(f"[OK] Created {created_users} sample tester users and assigned roles")

    # -------------------------------------------------------
    # Create sample users for remaining org roles
    # (Originator, Test Assigner, Department Head, Purchaser, Org Admin)
    # -------------------------------------------------------
    print(f"[INFO] Creating sample users for remaining org roles in {org_code}")

    other_users_config = [
        {
            "email": "originator@sampleorg.com",
            "password": "Originator123!",
            "role_name": "Originator",
            "firstname": "Sample",
            "lastname": "Originator",
            "phone": "9999999010"
        },
        {
            "email": "testassigner@sampleorg.com",
            "password": "Assigner123!",
            "role_name": "Test Assigner",
            "firstname": "Test",
            "lastname": "Assigner",
            "phone": "9999999011"
        },
        {
            "email": "depthead@sampleorg.com",
            "password": "DeptHead123!",
            "role_name": "Department Head",
            "firstname": "Department",
            "lastname": "Head",
            "phone": "9999999012"
        },
        {
            "email": "purchaser@sampleorg.com",
            "password": "Purchaser123!",
            "role_name": "Purchaser",
            "firstname": "Sample",
            "lastname": "Purchaser",
            "phone": "9999999013"
        },
        {
            "email": "orgadmin@sampleorg.com",
            "password": "OrgAdmin123!",
            "role_name": "Org Admin",
            "firstname": "Org",
            "lastname": "Admin",
            "phone": "9999999014"
        },
        {
            "email": "docviewer@sampleorg.com",
            "password": "DocViewer123!",
            "role_name": "doc-viewer",
            "firstname": "Document",
            "lastname": "Viewer",
            "phone": "9999999015"
        },
    ]

    created_other = 0
    for user_config in other_users_config:
        existing_user = session.query(User).filter_by(email=user_config["email"]).first()
        if existing_user:
            user = existing_user
            user.organization_id = org.id
        else:
            user = User(
                id=uuid.uuid4(),
                email=user_config["email"],
                password_hash=get_password_hash(user_config["password"]),
                firstname=user_config["firstname"],
                lastname=user_config["lastname"],
                phone_number=user_config["phone"],
                organization_id=org.id,
                isactive=True,
                email_confirmed=True,
                phone_confirmed=True,
                cts=now,
                mts=now
            )
            session.add(user)
            session.flush()
            created_other += 1

        # Find the OrgRole for this user
        role = session.query(OrgRole).filter_by(
            organization_id=org.id,
            name=user_config["role_name"]
        ).first()
        if not role:
            print(f"[WARN] OrgRole '{user_config['role_name']}' not found for {user_config['email']}")
            continue

        existing_assignment = session.query(OrgUserRole).filter_by(
            user_id=user.id,
            org_role_id=role.id
        ).first()
        if not existing_assignment:
            session.add(OrgUserRole(
                id=uuid.uuid4(),
                user_id=user.id,
                org_role_id=role.id,
                is_active=True
            ))

    session.commit()
    print(f"[OK] Created {created_other} additional sample org users")
    print("  Credentials summary:")
    for u in other_users_config:
        print(f"    {u['role_name']:20s}  {u['email']:35s}  {u['password']}")


def seed_kptcl_organization(session):
    """
    Create KPTCL organization with admin user and roles.
    Returns the created organization object or existing one.
    """
    org_code = "KPTCL"

    # Check if organization already exists
    existing_org = session.query(Organization).filter_by(code=org_code).first()
    if existing_org:
        print(f"[INFO] KPTCL organization already exists: {org_code}")
        org = existing_org

        # Provision any missing roles from updated role templates
        print(f"[INFO] Provisioning missing roles for existing KPTCL org...")
        templates = session.query(RoleTemplate).filter_by(auto_provision=True).all()
        existing_role_names = {r.name for r in session.query(OrgRole).filter_by(organization_id=org.id).all()}

        provisioned_count = 0
        for template in templates:
            if template.name not in existing_role_names:
                role = OrgRole(
                    id=uuid.uuid4(),
                    organization_id=org.id,
                    name=template.name,
                    description=template.description,
                    role_type="default",
                    is_org_admin=template.is_org_admin,
                    is_dept_admin=template.is_dept_admin,
                    is_active=True,
                    cts=datetime.now(datetime.now().astimezone().tzinfo),
                    mts=datetime.now(datetime.now().astimezone().tzinfo)
                )
                session.add(role)
                session.flush()

                # Create permissions from template
                if template.permissions_template:
                    for perm_data in template.permissions_template:
                        permission = OrgRolePermission(
                            id=uuid.uuid4(),
                            org_role_id=role.id,
                            module_id=perm_data.get("module_id"),
                            can_view=perm_data.get("can_view", False),
                            can_add=perm_data.get("can_add", False),
                            can_edit=perm_data.get("can_edit", False),
                            can_delete=perm_data.get("can_delete", False),
                            can_approve=perm_data.get("can_approve", False),
                            can_assign=perm_data.get("can_assign", False),
                            can_export=perm_data.get("can_export", False),
                            can_import=perm_data.get("can_import", False),
                            cts=datetime.now(datetime.now().astimezone().tzinfo),
                            mts=datetime.now(datetime.now().astimezone().tzinfo)
                        )
                        session.add(permission)
                provisioned_count += 1
                print(f"  [+] Provisioned role: {template.name}")

        session.commit()
        print(f"[OK] Provisioned {provisioned_count} new roles for KPTCL")

        # Build a lookup of all roles (existing + newly provisioned)
        provisioned_by_name = {r.name: r for r in session.query(OrgRole).filter_by(organization_id=org.id).all()}

        # Create missing test users for new SRS roles
        kptcl_users = [
            {
                "email": "aee.maintenance@kptcl.com",
                "password": "admin123",
                "firstname": "AEE",
                "lastname": "Maintenance",
                "phone": "+91-9900000010",
                "role_name": "AEE Maintenance",
                "employee_id": "KPTCL-AEE-M-001",
            },
            {
                "email": "ee.tlss@kptcl.com",
                "password": "admin123",
                "firstname": "EE",
                "lastname": "TLSS",
                "phone": "+91-9900000011",
                "role_name": "EE TLSS",
                "employee_id": "KPTCL-EE-TLSS-001",
            },
            {
                "email": "see.wm@kptcl.com",
                "password": "admin123",
                "firstname": "SEE",
                "lastname": "W&M",
                "phone": "+91-9900000012",
                "role_name": "SEE W&M",
                "employee_id": "KPTCL-SEE-WM-001",
            },
            {
                "email": "ee.rt@kptcl.com",
                "password": "admin123",
                "firstname": "EE",
                "lastname": "RT",
                "phone": "+91-9900000013",
                "role_name": "EE RT",
                "employee_id": "KPTCL-EE-RT-001",
            },
            {
                "email": "see.rt@kptcl.com",
                "password": "admin123",
                "firstname": "SEE",
                "lastname": "RT",
                "phone": "+91-9900000014",
                "role_name": "SEE RT",
                "employee_id": "KPTCL-SEE-RT-001",
                "zone": "Bangalore Zone", "ce_circle": "BMAZ North",
                "se_division": "Bangalore Urban Division", "ee_subdivision": "TL & SS Sub-Division 1",
            },
            # ── Zone-based SEE RT testers ──────────────────────────────────────
            {
                "email": "see.rt.bangalore@kptcl.com",
                "password": "admin123",
                "firstname": "SEE RT",
                "lastname": "Bangalore",
                "phone": "+91-9900000020",
                "role_name": "SEE RT",
                "employee_id": "KPTCL-SEE-RT-BLR-001",
                "zone": "Bangalore Zone", "ce_circle": "BMAZ South",
                "se_division": "Bangalore Rural Division", "ee_subdivision": "TL & SS Sub-Division 2",
            },
            {
                "email": "see.rt.hubli@kptcl.com",
                "password": "admin123",
                "firstname": "SEE RT",
                "lastname": "Hubli",
                "phone": "+91-9900000021",
                "role_name": "SEE RT",
                "employee_id": "KPTCL-SEE-RT-HBL-001",
                "zone": "Hubli Zone", "ce_circle": "O&M Zone Hubballi",
                "se_division": "Hubli Division", "ee_subdivision": "TL & SS Sub-Division 1",
            },
            {
                "email": "see.rt.mysore@kptcl.com",
                "password": "admin123",
                "firstname": "SEE RT",
                "lastname": "Mysore",
                "phone": "+91-9900000022",
                "role_name": "SEE RT",
                "employee_id": "KPTCL-SEE-RT-MYS-001",
                "zone": "Mysore Zone", "ce_circle": "Mysuru Zone",
                "se_division": "Mysuru Division", "ee_subdivision": "TL & SS Sub-Division 1",
            },
            {
                "email": "see.rt.gulbarga@kptcl.com",
                "password": "admin123",
                "firstname": "SEE RT",
                "lastname": "Gulbarga",
                "phone": "+91-9900000023",
                "role_name": "SEE RT",
                "employee_id": "KPTCL-SEE-RT-GLB-001",
                "zone": "Gulbarga Zone", "ce_circle": "Gulbarga Zone",
                "se_division": "Gulbarga Division", "ee_subdivision": "TL & SS Sub-Division 1",
            },
            {
                "email": "cee.zone@kptcl.com",
                "password": "admin123",
                "firstname": "CEE",
                "lastname": "Transmission Zone",
                "phone": "+91-9900000015",
                "role_name": "CEE Transmission Zone",
                "employee_id": "KPTCL-CEE-TZ-001",
            },
            {
                "email": "cee.rtrd@kptcl.com",
                "password": "admin123",
                "firstname": "CEE",
                "lastname": "RT&R&D",
                "phone": "+91-9900000016",
                "role_name": "CEE RT&R&D",
                "employee_id": "KPTCL-CEE-RTRD-001",
            },
            {
                "email": "field.tester@kptcl.com",
                "password": "Tester123!",
                "firstname": "Field",
                "lastname": "Tester",
                "phone": "+91-9900000017",
                "role_name": "Field Tester",
                "employee_id": "KPTCL-FT-001",
            },
            {
                "email": "lab.tester@kptcl.com",
                "password": "Tester123!",
                "firstname": "Lab",
                "lastname": "Tester",
                "phone": "+91-9900000018",
                "role_name": "Lab Tester",
                "employee_id": "KPTCL-LT-001",
            },
            {
                "email": "wf.coordinator@kptcl.com",
                "password": "Coord123!",
                "firstname": "Workflow",
                "lastname": "Coordinator",
                "phone": "+91-9900000019",
                "role_name": "Workflow Coordinator",
                "employee_id": "KPTCL-WFC-001",
            },
        ]

        created_users = 0
        for user_data in kptcl_users:
            existing_user = session.query(User).filter_by(email=user_data["email"]).first()
            if existing_user:
                user = existing_user
                if user.organization_id != org.id:
                    user.organization_id = org.id
            else:
                user = User(
                    id=uuid.uuid4(),
                    email=user_data["email"],
                    password_hash=get_password_hash(user_data["password"]),
                    firstname=user_data["firstname"],
                    lastname=user_data["lastname"],
                    phone_number=user_data["phone"],
                    employee_id=user_data.get("employee_id"),
                    organization_id=org.id,
                    isactive=True,
                    email_confirmed=True,
                    phone_confirmed=True,
                    cts=datetime.now(datetime.now().astimezone().tzinfo),
                    mts=datetime.now(datetime.now().astimezone().tzinfo)
                )
                session.add(user)
                session.flush()
                created_users += 1

            role = provisioned_by_name.get(user_data["role_name"])
            if not role:
                print(f"[WARN] OrgRole '{user_data['role_name']}' not found for {user_data['email']}")
                continue

            existing_role = session.query(OrgUserRole).filter_by(
            user_id=user.id,
            org_role_id=role.id,
        ).first()

        if existing_role:
            # UPDATE existing mapping
            existing_role.department_id = user_data.get("department_id")
            existing_role.is_active = True
            existing_role.assigned_at = datetime.now(datetime.now().astimezone().tzinfo)

            print(
                f"[UPDATED ROLE] "
                f"{user.email} -> {user_data.get('department_id')}"
            )

        else:
            # CREATE new mapping
            session.add(OrgUserRole(
                id=uuid.uuid4(),
                user_id=user.id,
                org_role_id=role.id,
                department_id=user_data.get("department_id"),
                is_active=True,
                assigned_at=datetime.now(datetime.now().astimezone().tzinfo),
                assigned_by=None
            ))

        print(
            f"[CREATED ROLE] "
            f"{user.email} -> {user_data.get('department_id')}"
        )
        session.commit()
        print(f"[OK] Created {created_users} new SRS designation users for KPTCL")
        return existing_org

    # Get a basic plan if available
    basic_plan = session.query(Plan).filter_by(planname="Basic").first()
    plan_id = basic_plan.id if basic_plan else None

    # Create KPTCL organization
    now = datetime.now(datetime.now().astimezone().tzinfo)
    org = Organization(
        id=uuid.uuid4(),
        name="Karnataka Power Transmission Corporation Limited",
        code=org_code,
        display_name="KPTCL",
        organization_type="utility",
        industry="Power Transmission",
        primary_email="info@kptcl.com",
        primary_phone="+91-80-25801500",
        website="https://kptcl.karnataka.gov.in",
        address="Cauvery Bhavan, K.G. Road",
        city="Bengaluru",
        state="Karnataka",
        country="India",
        pincode="560009",
        is_active=True,
        is_verified=True,
        plan_id=plan_id,
        subscription_start_date=now,
        subscription_end_date=now + timedelta(days=365),
        settings={},
        created_by=None,
        modified_by=None,
        cts=now,
        mts=now,
        erp_sync_status="pending",
        erp_last_sync_at=None,
        erp_error_message=None,
        erp_external_id=None
    )
    session.add(org)
    session.flush()

    # Provision default roles from templates
    templates = session.query(RoleTemplate).filter_by(auto_provision=True).all()

    org_admin_role = None
    engineer_role = None
    tester_role = None
    dept_head_role = None

    for template in templates:
        role = OrgRole(
            id=uuid.uuid4(),
            organization_id=org.id,
            name=template.name,
            description=template.description,
            role_type="default",
            is_org_admin=template.is_org_admin,
            is_dept_admin=template.is_dept_admin,
            default_module_id=template.default_module_id,
            is_active=True,
            cts=datetime.now(datetime.now().astimezone().tzinfo),
            mts=datetime.now(datetime.now().astimezone().tzinfo)
        )
        session.add(role)
        session.flush()

        # Save specific roles for user assignment
        if role.is_org_admin:
            org_admin_role = role
        elif template.name == "Originator":
            engineer_role = role
        elif template.name == "Tester":
            tester_role = role

        # Create permissions from template
        if template.permissions_template:
            for perm_data in template.permissions_template:
                permission = OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=perm_data.get("module_id"),
                    can_view=perm_data.get("can_view", False),
                    can_add=perm_data.get("can_add", False),
                    can_edit=perm_data.get("can_edit", False),
                    can_delete=perm_data.get("can_delete", False),
                    can_approve=perm_data.get("can_approve", False),
                    can_assign=perm_data.get("can_assign", False),
                    can_export=perm_data.get("can_export", False),
                    can_import=perm_data.get("can_import", False),
                    cts=datetime.now(datetime.now().astimezone().tzinfo),
                    mts=datetime.now(datetime.now().astimezone().tzinfo)
                )
                session.add(permission)

    # Build a lookup of provisioned roles by name for easy access
    provisioned_by_name = {r.name: r for r in session.query(OrgRole).filter_by(organization_id=org.id).all()}

    # Create KPTCL users — one per org role
    kptcl_users = [
        {
            "email": "orgadmin@kptcl.com",
            "password": "admin123",
            "firstname": "Org",
            "lastname": "Admin",
            "phone": "+91-9900000001",
            "role_name": "Admin",
            "employee_id": "KPTCL-ADM-001",
        },
        {
            "email": "originator@kptcl.com",
            "password": "admin123",
            "firstname": "KPTCL",
            "lastname": "Originator",
            "phone": "+91-9900000002",
            "role_name": "Originator",
            "employee_id": "KPTCL-ORIG-001",
        },
        {
            "email": "testassigner@kptcl.com",
            "password": "admin123",
            "firstname": "KPTCL Test",
            "lastname": "Assigner",
            "phone": "+91-9900000005",
            "role_name": "Test Assigner",
            "employee_id": "KPTCL-TA-001",
        },
        {
            "email": "depthead@kptcl.com",
            "password": "admin123",
            "firstname": "Department",
            "lastname": "Head",
            "phone": "+91-9900000004",
            "role_name": "Department Head",
            "employee_id": "KPTCL-DH-001",
        },
        {
            "email": "purchaser@kptcl.com",
            "password": "admin123",
            "firstname": "KPTCL",
            "lastname": "Purchaser",
            "phone": "+91-9900000006",
            "role_name": "Purchaser",
            "employee_id": "KPTCL-PUR-001",
        },
        {
            "email": "docviewer@kptcl.com",
            "password": "admin123",
            "firstname": "KPTCL Doc",
            "lastname": "Viewer",
            "phone": "+91-9900000007",
            "role_name": "doc-viewer",
            "employee_id": "KPTCL-DOC-001",
        },
        # ✅ SRS DESIGNATION ROLES — Test users
        {
            "email": "aee.maintenance@kptcl.com",
            "password": "admin123",
            "firstname": "AEE",
            "lastname": "Maintenance",
            "phone": "+91-9900000010",
            "role_name": "AEE Maintenance",
            "employee_id": "KPTCL-AEE-M-001",
        },
        {
            "email": "ee.tlss@kptcl.com",
            "password": "admin123",
            "firstname": "EE",
            "lastname": "TLSS",
            "phone": "+91-9900000011",
            "role_name": "EE TLSS",
            "employee_id": "KPTCL-EE-TLSS-001",
        },
        {
            "email": "see.wm@kptcl.com",
            "password": "admin123",
            "firstname": "SEE",
            "lastname": "W&M",
            "phone": "+91-9900000012",
            "role_name": "SEE W&M",
            "employee_id": "KPTCL-SEE-WM-001",
        },
        {
            "email": "ee.rt@kptcl.com",
            "password": "admin123",
            "firstname": "EE",
            "lastname": "RT",
            "phone": "+91-9900000013",
            "role_name": "EE RT",
            "employee_id": "KPTCL-EE-RT-001",
        },
        {
            "email": "see.rt@kptcl.com",
            "password": "admin123",
            "firstname": "SEE",
            "lastname": "RT",
            "phone": "+91-9900000014",
            "role_name": "SEE RT",
            "employee_id": "KPTCL-SEE-RT-001",
            "zone": "Bangalore Zone", "ce_circle": "BMAZ North",
            "se_division": "Bangalore Urban Division", "ee_subdivision": "TL & SS Sub-Division 1",
        },
        # ── Zone-based SEE RT testers ──────────────────────────────────────
        {
            "email": "see.rt.bangalore@kptcl.com",
            "password": "admin123",
            "firstname": "SEE RT",
            "lastname": "Bangalore",
            "phone": "+91-9900000020",
            "role_name": "SEE RT",
            "employee_id": "KPTCL-SEE-RT-BLR-001",
            "zone": "Bangalore Zone", "ce_circle": "BMAZ South",
            "se_division": "Bangalore Rural Division", "ee_subdivision": "TL & SS Sub-Division 2",
        },
        {
            "email": "see.rt.hubli@kptcl.com",
            "password": "admin123",
            "firstname": "SEE RT",
            "lastname": "Hubli",
            "phone": "+91-9900000021",
            "role_name": "SEE RT",
            "employee_id": "KPTCL-SEE-RT-HBL-001",
            "zone": "Hubli Zone", "ce_circle": "O&M Zone Hubballi",
            "se_division": "Hubli Division", "ee_subdivision": "TL & SS Sub-Division 1",
        },
        {
            "email": "see.rt.mysore@kptcl.com",
            "password": "admin123",
            "firstname": "SEE RT",
            "lastname": "Mysore",
            "phone": "+91-9900000022",
            "role_name": "SEE RT",
            "employee_id": "KPTCL-SEE-RT-MYS-001",
            "zone": "Mysore Zone", "ce_circle": "Mysuru Zone",
            "se_division": "Mysuru Division", "ee_subdivision": "TL & SS Sub-Division 1",
        },
        {
            "email": "see.rt.gulbarga@kptcl.com",
            "password": "admin123",
            "firstname": "SEE RT",
            "lastname": "Gulbarga",
            "phone": "+91-9900000023",
            "role_name": "SEE RT",
            "employee_id": "KPTCL-SEE-RT-GLB-001",
            "zone": "Gulbarga Zone", "ce_circle": "Gulbarga Zone",
            "se_division": "Gulbarga Division", "ee_subdivision": "TL & SS Sub-Division 1",
        },
        {
            "email": "cee.zone@kptcl.com",
            "password": "admin123",
            "firstname": "CEE",
            "lastname": "Transmission Zone",
            "phone": "+91-9900000015",
            "role_name": "CEE Transmission Zone",
            "employee_id": "KPTCL-CEE-TZ-001",
        },
        {
            "email": "cee.rtrd@kptcl.com",
            "password": "admin123",
            "firstname": "CEE",
            "lastname": "RT&R&D",
            "phone": "+91-9900000016",
            "role_name": "CEE RT&R&D",
            "employee_id": "KPTCL-CEE-RTRD-001",
        },
    ]

    for user_data in kptcl_users:
        existing_user = session.query(User).filter_by(email=user_data["email"]).first()
        if existing_user:
            user = existing_user
            if user.organization_id != org.id:
                user.organization_id = org.id
        else:
            user = User(
                id=uuid.uuid4(),
                email=user_data["email"],
                password_hash=get_password_hash(user_data["password"]),
                firstname=user_data["firstname"],
                lastname=user_data["lastname"],
                phone_number=user_data["phone"],
                employee_id=user_data.get("employee_id"),
                organization_id=org.id,
                isactive=True,
                email_confirmed=True,
                phone_confirmed=True,
                cts=datetime.now(datetime.now().astimezone().tzinfo),
                mts=datetime.now(datetime.now().astimezone().tzinfo)
            )
            session.add(user)
            session.flush()

        role = provisioned_by_name.get(user_data["role_name"])
        if not role:
            print(f"[WARN] OrgRole '{user_data['role_name']}' not found for {user_data['email']}")
            continue

        existing_role = session.query(OrgUserRole).filter_by(
            user_id=user.id, org_role_id=role.id, is_active=True
        ).first()
        if existing_role:
            existing_role.department_id = user_data.get("department_id")
            existing_role.is_active = True
            existing_role.assigned_at = datetime.now(
            datetime.now().astimezone().tzinfo
    )

        else:
            session.add(OrgUserRole(
            id=uuid.uuid4(),
            user_id=user.id,
            org_role_id=role.id,
            department_id=user_data.get("department_id"),
            is_active=True,
            assigned_at=datetime.now(datetime.now().astimezone().tzinfo),
            assigned_by=None
            ))

    session.commit()
    print(f"[OK] KPTCL organization created with admin user and roles")
    print("  KPTCL user credentials:")
    for u in kptcl_users:
        print(f"    {u['role_name']:20s}  {u['email']:35s}  {u['password']}")

    # Create sample tester roles with EXACT module permissions
    print(f"[INFO] Creating sample tester roles for KPTCL")

    # Required modules for testers: [45, 46, 49]
    # Removed 51 (Tester Mapping) - no longer used
    TESTER_REQUIRED_MODULES = [45, 46, 49]

    tester_roles_config = [
        {
            "name": "Field Tester",
            "description": "Field tester role with exact module permissions for tester assignment"
        },
        {
            "name": "Lab Tester",
            "description": "Laboratory tester role with exact module permissions for tester assignment"
        }
    ]

    tester_roles = []
    for role_config in tester_roles_config:
        # Check if role already exists
        existing_role = session.query(OrgRole).filter_by(
            organization_id=org.id,
            name=role_config["name"]
        ).first()

        if existing_role:
            role = existing_role
            # FIX: Clear the limited template permissions so we can overwrite them
            session.query(OrgRolePermission).filter_by(org_role_id=role.id).delete()
        else:
            # Create tester role
            role = OrgRole(
                id=uuid.uuid4(),
                organization_id=org.id,
                name=role_config["name"],
                description=role_config["description"],
                role_type="tester",
                is_org_admin=False,
                is_dept_admin=False,
                is_active=True,
                cts=now,
                mts=now
            )
            session.add(role)
            session.flush()

        # FIX: Move this OUTSIDE the else block to guarantee full permissions are added
        for module_id in TESTER_REQUIRED_MODULES:
            perm = OrgRolePermission(
                id=uuid.uuid4(),
                org_role_id=role.id,
                module_id=module_id,
                can_view=True,
                can_add=True,
                can_edit=True,
                can_delete=True,
                can_approve=True,
                can_assign=True,
                can_export=True,
                can_import=True,
                cts=now,
                mts=now
            )
            session.add(perm)

        tester_roles.append(role)

    session.commit()
    print(f"[OK] Created {len(tester_roles)} sample tester roles with exact module permissions {TESTER_REQUIRED_MODULES}")

    # Create sample tester users
    print(f"[INFO] Creating sample tester users for KPTCL")

    tester_users_config = [
        {
            "email": "fieldtester1@kptcl.com",
            "password": "Tester123!",
            "role_name": "Field Tester",
            "firstname": "KPTCL Field",
            "lastname": "Tester One",
            "phone": "9999999101"
        },
        {
            "email": "fieldtester2@kptcl.com",
            "password": "Tester123!",
            "role_name": "Field Tester",
            "firstname": "KPTCL Field",
            "lastname": "Tester Two",
            "phone": "9999999102"
        },
        {
            "email": "labtester1@kptcl.com",
            "password": "Tester123!",
            "role_name": "Lab Tester",
            "firstname": "KPTCL Lab",
            "lastname": "Tester One",
            "phone": "9999999103"
        },
        {
            "email": "labtester2@kptcl.com",
            "password": "Tester123!",
            "role_name": "Lab Tester",
            "firstname": "KPTCL Lab",
            "lastname": "Tester Two",
            "phone": "9999999104"
        }
    ]

    created_users = 0
    for user_config in tester_users_config:
        # Check if user exists
        existing_user = session.query(User).filter_by(email=user_config["email"]).first()

        if existing_user:
            user = existing_user
        else:
            # Create user
            hashed_password = get_password_hash(user_config["password"])
            user = User(
                id=uuid.uuid4(),
                email=user_config["email"],
                password_hash=hashed_password,
                firstname=user_config["firstname"],
                lastname=user_config["lastname"],
                phone_number=user_config["phone"],
                organization_id=org.id,
                isactive=True,
                email_confirmed=True,
                phone_confirmed=True,
                cts=now,
                mts=now
            )
            session.add(user)
            session.flush()
            created_users += 1

        # Get the role — first check tester_roles list, then fall back to org roles
        role = next((r for r in tester_roles if r.name == user_config["role_name"]), None)
        if not role:
            role = session.query(OrgRole).filter_by(
                organization_id=org.id, name=user_config["role_name"]
            ).first()
        if not role:
            print(f"[WARN] Role '{user_config['role_name']}' not found for user {user_config['email']}")
            continue

        existing_assignment = session.query(OrgUserRole).filter_by(
            user_id=user.id,
            org_role_id=role.id
        ).first()

        if not existing_assignment:
            session.add(OrgUserRole(
                id=uuid.uuid4(),
                user_id=user.id,
                org_role_id=role.id,
                is_active=True
            ))

    session.commit()
    print(f"[OK] Created {created_users} KPTCL field/lab tester users and assigned roles")

    return org
# ---------------------------------------------------------------------------
# ADD: Notifications Module + Role Mapping
# ---------------------------------------------------------------------------

def seed_notifications_module_and_permissions(session):
    # ─────────────────────────────────────────────────────────────
    # 1. Ensure Module exists
    # ─────────────────────────────────────────────────────────────
    notifications_module = session.query(Module).filter_by(name="Notifications").first()
    if not notifications_module:
        notifications_module = Module(
            name="Notifications",
            route="/notifications",
            description="Notifications screen"
        )
        session.add(notifications_module)
        session.flush()

    # ─────────────────────────────────────────────────────────────
    # 2. Get KPTCL org
    # ─────────────────────────────────────────────────────────────
    kptcl_org = session.query(Organization).filter_by(display_name="KPTCL").first()
    if not kptcl_org:
        raise Exception("KPTCL organization not found")

    # ─────────────────────────────────────────────────────────────
    # 3. Get user
    # ─────────────────────────────────────────────────────────────
    user = session.query(User).filter_by(email="orgadmin@kptcl.com").first()
    if not user:
        raise Exception("User orgadmin@kptcl.com not found")

    # ─────────────────────────────────────────────────────────────
    # 4. Validate user belongs to KPTCL org
    # ─────────────────────────────────────────────────────────────
    org_user_role = session.query(OrgUserRole).filter_by(
        user_id=user.id,
    ).first()

    if not org_user_role:
        raise Exception("User is not part of KPTCL organization")

    # ─────────────────────────────────────────────────────────────
    # 5. Get Org Admin role (ORG-SCOPED)
    # ─────────────────────────────────────────────────────────────
    org_admin_role = session.query(OrgRole).filter_by(
        organization_id=kptcl_org.id,
        name="Org Admin",
        is_active=True
    ).first()

    if not org_admin_role:
        raise Exception("Org Admin role not found for KPTCL")

    # ─────────────────────────────────────────────────────────────
    # 6. Assign permissions (ORG-SCOPED)
    #    Grant: Notifications + My Organization to Org Admin role
    # ─────────────────────────────────────────────────────────────
    notif_template_mod  = session.query(Module).filter_by(path="org_notification_templates").first()
    notif_routing_mod   = session.query(Module).filter_by(path="org_notification_routing").first()
    notif_schedule_mod  = session.query(Module).filter_by(path="org_notification_schedules").first()

    for mod in filter(None, [notifications_module, notif_template_mod,
                              notif_routing_mod, notif_schedule_mod]):
        existing_perm = session.query(OrgRolePermission).filter_by(
            org_role_id=org_admin_role.id,
            module_id=mod.id
        ).first()
        if not existing_perm:
            session.add(
                OrgRolePermission(
                    org_role_id=org_admin_role.id,
                    module_id=mod.id,
                    can_view=True,
                    can_add=True,
                    can_edit=True,
                    can_delete=False,
                )
            )

    session.commit()

def seed_kptcl_departments(session, org_id: str, excel_path: str = None):
    """
    Seed KPTCL department hierarchy from Excel file.
    Creates 6-level hierarchy: Zone → Circle → Division → Sub Division → Section → Substation
    """
    print("\n--- KPTCL Department Hierarchy Seeding ---")

    # Check if organization exists
    org = session.query(Organization).filter(Organization.id == uuid.UUID(org_id)).first()
    if not org:
        print(f"[ERROR] Organization {org_id} not found")
        return

    # Determine Excel file path
    if excel_path is None:
        import os
        project_root = os.path.dirname(os.path.abspath(__file__))
        excel_path = os.path.join(project_root, "KPTCL_Substation_Mapping.xlsx")

    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    # Delete existing testing requests first (to avoid FK violation with equipment)
    print(f"[INFO] Deleting existing testing requests for organization: {org.name}")
    from models import TestingRequest
    deleted_requests = session.query(TestingRequest).filter(
        TestingRequest.organization_id == uuid.UUID(org_id)
    ).delete()
    session.commit()
    print(f"[OK] Deleted {deleted_requests} testing requests")

    # Delete annual audit inspections first (FK → equipment, observations cascade)
    try:
        from models import TAQCAnnualInspection
        deleted_inspections = session.query(TAQCAnnualInspection).filter(
            TAQCAnnualInspection.organization_id == uuid.UUID(org_id)
        ).delete()
        session.commit()
        if deleted_inspections:
            print(f"[OK] Deleted {deleted_inspections} annual audit inspections (and their observations)")
    except Exception:
        session.rollback()

    # Delete existing equipment for this organization
    print(f"[INFO] Deleting existing equipment for organization: {org.name}")
    from models import Equipment
    deleted_equipment = session.query(Equipment).filter(
        Equipment.organization_id == uuid.UUID(org_id)
    ).delete()
    session.commit()
    print(f"[OK] Deleted {deleted_equipment} equipment records")

    # Delete existing departments for this organization
    print(f"[INFO] Deleting existing departments for organization: {org.name}")
    existing_depts = session.query(OrgDepartment).filter(
        OrgDepartment.organization_id == uuid.UUID(org_id)
    ).all()
    for dept in existing_depts:
        session.delete(dept)
    session.commit()
    print(f"[OK] Deleted {len(existing_depts)} existing departments")

    # Read Excel file
    try:
        print(f"[INFO] Reading Excel file: {excel_path}")
        df = pd.read_excel(excel_path)
        print(f"[OK] Loaded {len(df)} rows with columns: {df.columns.tolist()}")
    except Exception as e:
        print(f"[ERROR] Failed to read Excel file: {e}")
        return

    # Hierarchy levels in order
    levels = ['Zone', 'Circle', 'Division', 'Sub Division', 'Section', 'Substation']

    # Track created departments by full path
    department_map: Dict[str, str] = {}

    def generate_code(name: str) -> str:
        """Generate a department code from the name."""
        clean_name = name.replace(' Zone', '').replace(' Circle', '').replace(' Division', '')
        clean_name = clean_name.replace(' Section', '').replace('kV', '').strip()
        words = clean_name.split()
        if len(words) > 1:
            code = ''.join([w[0].upper() for w in words[:3]])
        else:
            code = clean_name[:3].upper()
        return code

    # Create root "Zone" parent department
    print(f"\n{'='*60}")
    print(f"Creating root Zone parent department...")
    print(f"{'='*60}")

    root_zone_id = str(uuid.uuid4())
    root_zone = OrgDepartment(
        id=uuid.UUID(root_zone_id),
        organization_id=uuid.UUID(org_id),
        name="Zone",
        code="ZONE",
        description="Root parent for all zones",
        parent_department_id=None,
        manager_id=None,
        is_active=True,
        cts=datetime.utcnow(),
        mts=datetime.utcnow()
    )
    session.add(root_zone)
    session.commit()
    print(f"[OK] Created root Zone department")

    # Process each level
    for level_idx, level in enumerate(levels):
        print(f"\n{'='*60}")
        print(f"Creating {level} departments...")
        print(f"{'='*60}")

        parent_level = levels[level_idx - 1] if level_idx > 0 else None

        # Get unique combinations at this level
        if parent_level:
            parent_cols = levels[:level_idx]
            current_cols = parent_cols + [level]
            unique_combos = df[current_cols].drop_duplicates()
        else:
            unique_combos = df[[level]].drop_duplicates()

        print(f"Found {len(unique_combos)} unique {level} departments")

        # Create each department at this level
        created_count = 0
        skipped_count = 0
        for _, row in unique_combos.iterrows():
            dept_name = str(row[level]).strip()

            # Build full path for tracking
            if parent_level:
                parent_path = '|'.join([str(row[pl]).strip() for pl in parent_cols])
                full_path = f"{parent_path}|{dept_name}"

                # Get parent ID
                parent_id = department_map.get(parent_path)
                if not parent_id:
                    print(f"  [WARNING] Parent not found for {dept_name}")
                    skipped_count += 1
                    continue
            else:
                # First level (Zone) - use root Zone as parent
                full_path = dept_name
                parent_id = root_zone_id

            # Check if department with this name already exists in this org
            existing = session.query(OrgDepartment).filter(
                OrgDepartment.organization_id == uuid.UUID(org_id),
                OrgDepartment.name == dept_name
            ).first()

            if existing:
                # Use existing department ID
                department_map[full_path] = str(existing.id)
                skipped_count += 1
                continue

            # Generate code
            code = generate_code(dept_name)

            # Create department - commit immediately to handle unique constraint
            dept_id = str(uuid.uuid4())
            new_dept = OrgDepartment(
                id=uuid.UUID(dept_id),
                organization_id=uuid.UUID(org_id),
                name=dept_name,
                code=code,
                description=None,
                parent_department_id=uuid.UUID(parent_id) if parent_id else None,
                manager_id=None,
                is_active=True,
                cts=datetime.utcnow(),
                mts=datetime.utcnow()
            )
            session.add(new_dept)

            try:
                session.commit()
                department_map[full_path] = dept_id
                created_count += 1
            except Exception as e:
                session.rollback()
                print(f"  [ERROR] Failed to create {dept_name}: {e}")
                skipped_count += 1

        print(f"[OK] Created {created_count} {level} departments (skipped {skipped_count} duplicates)")

    print(f"\n{'='*60}")
    print(f"[OK] COMPLETED: Created {len(department_map) + 1} total departments (including root Zone)")
    print(f"{'='*60}\n")


# ----------------- Reporting Suite Seed -----------------

def migrate_report_tables(session):
    """
    Create report_definitions and report_logs tables if they don't exist.
    Safe to run multiple times — uses IF NOT EXISTS.
    """
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS public.report_definitions (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organization_id  UUID REFERENCES public.organizations(id) ON DELETE CASCADE,
            name             VARCHAR(255) NOT NULL,
            description      TEXT,
            query_key        VARCHAR(100) NOT NULL,
            parameters       JSONB NOT NULL DEFAULT '{}',
            output_format    VARCHAR(20)  NOT NULL DEFAULT 'excel',
            frequency        VARCHAR(20)  NOT NULL DEFAULT 'on_demand',
            recipient_roles  JSONB NOT NULL DEFAULT '[]',
            is_active        BOOLEAN DEFAULT TRUE,
            is_system        BOOLEAN DEFAULT FALSE,
            last_generated_at TIMESTAMPTZ,
            created_by       UUID REFERENCES public.users(id),
            modified_by      UUID REFERENCES public.users(id),
            cts              TIMESTAMPTZ DEFAULT NOW(),
            mts              TIMESTAMPTZ DEFAULT NOW()
        )
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS public.report_logs (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            definition_id   UUID NOT NULL REFERENCES public.report_definitions(id) ON DELETE CASCADE,
            organization_id UUID,
            generated_by    UUID REFERENCES public.users(id) ON DELETE SET NULL,
            parameters_used JSONB NOT NULL DEFAULT '{}',
            output_format   VARCHAR(20) NOT NULL DEFAULT 'excel',
            file_path       VARCHAR(500),
            file_name       VARCHAR(255),
            file_size       INTEGER,
            row_count       INTEGER,
            status          VARCHAR(20) DEFAULT 'pending',
            error_message   TEXT,
            started_at      TIMESTAMPTZ,
            completed_at    TIMESTAMPTZ,
            cts             TIMESTAMPTZ DEFAULT NOW()
        )
    """))
    session.commit()
    print("[OK] report_definitions and report_logs tables ready.")


def seed_report_definitions(session):
    """
    Insert the 14 SRS report definitions as system rows.
    Idempotent — skips rows that already exist (matched by query_key).
    """
    DEFINITIONS = [
        {
            "name": "Equipment Condition Summary",
            "description": "All active equipment with latest test condition (CRITICAL/ALERT/NORMAL/NOT_TESTED)",
            "query_key": "equipment_condition_summary",
            "output_format": "excel",
            "frequency": "on_demand",
        },
        {
            "name": "Overdue Tests",
            "description": "Testing requests past their due date",
            "query_key": "overdue_tests_report",
            "output_format": "excel",
            "frequency": "daily",
        },
        {
            "name": "Active Alerts",
            "description": "Test results with CRITICAL or ALERT evaluation",
            "query_key": "active_alerts_report",
            "output_format": "excel",
            "frequency": "daily",
        },
        {
            "name": "Flagged Equipment",
            "description": "Equipment with CRITICAL or ALERT status (deduplicated)",
            "query_key": "flagged_equipment_report",
            "output_format": "excel",
            "frequency": "weekly",
        },
        {
            "name": "Repair Lifecycle Progress",
            "description": "Repair lifecycle requests with session progress",
            "query_key": "repair_progress_report",
            "output_format": "excel",
            "frequency": "on_demand",
        },
        {
            "name": "Maintenance Overdue",
            "description": "Preventive maintenance requests past due date",
            "query_key": "maintenance_overdue_report",
            "output_format": "excel",
            "frequency": "daily",
        },
        {
            "name": "Procurement Pipeline",
            "description": "All procurement requests with status",
            "query_key": "procurement_pipeline_report",
            "output_format": "excel",
            "frequency": "weekly",
        },
        {
            "name": "Open Remediation Records",
            "description": "Pending recommendations awaiting approval",
            "query_key": "open_remediation_report",
            "output_format": "excel",
            "frequency": "on_demand",
        },
        {
            "name": "Testing Request Status",
            "description": "All testing requests with current status and assignment",
            "query_key": "testing_request_status_report",
            "output_format": "excel",
            "frequency": "on_demand",
        },
        {
            "name": "Test Results Summary",
            "description": "Test results with evaluation outcomes",
            "query_key": "test_results_summary_report",
            "output_format": "excel",
            "frequency": "weekly",
        },
        {
            "name": "Recommendation Approvals",
            "description": "Recommendations with approval status and notes",
            "query_key": "recommendation_approval_report",
            "output_format": "excel",
            "frequency": "on_demand",
        },
        {
            "name": "Compliance Status by Substation",
            "description": "Equipment testing compliance rates grouped by substation",
            "query_key": "compliance_status_report",
            "output_format": "excel",
            "frequency": "monthly",
        },
        {
            "name": "Tester Performance",
            "description": "Tester completion rates and average turnaround times",
            "query_key": "tester_performance_report",
            "output_format": "excel",
            "frequency": "monthly",
        },
        {
            "name": "Monthly KPI Summary",
            "description": "Monthly aggregated KPIs: requests, completions, alerts, findings",
            "query_key": "monthly_kpi_report",
            "output_format": "excel",
            "frequency": "monthly",
        },
        # §3.3.3 Equipment Failure Registry
        {
            "name": "Equipment Failure Annual Report",
            "description": (
                "Yearly failure summary grouped by equipment type, make, and model. "
                "Available as PDF or Excel. Auto-generated each calendar year."
            ),
            "query_key": "equipment_failure_annual_report",
            "output_format": "excel",
            "frequency": "annual",
        },
        {
            "name": "Equipment Failure Performance Analysis",
            "description": (
                "On-demand report comparing failure rates across makes, equipment types, "
                "voltage classes, and age bands."
            ),
            "query_key": "equipment_failure_performance_report",
            "output_format": "excel",
            "frequency": "on_demand",
        },
        # §3.3.4 Failure Resolution
        {
            "name": "Failure Resolution Report",
            "description": (
                "End-to-end traceability: each Failure Registry record with its outcome "
                "(Repair / Replacement / Under Investigation) and the linked Repair Lifecycle "
                "work-order status. Supports date range and outcome filters."
            ),
            "query_key": "failure_resolution_report",
            "output_format": "excel",
            "frequency": "on_demand",
        },
        # §3.5 Equipment Lifecycle
        {
            "name": "Equipment Lifecycle Summary",
            "description": (
                "One row per equipment unit showing commissioned date, total test count, "
                "total failure count, last test date and result, and current status. "
                "Supports filters: status, voltage_class, department_id, date_from, date_to "
                "(commissioned date range)."
            ),
            "query_key": "equipment_lifecycle_report",
            "output_format": "excel",
            "frequency": "on_demand",
        },
    ]

    created = 0
    for d in DEFINITIONS:
        existing = session.query(ReportDefinition).filter_by(
            query_key=d["query_key"]
        ).first()
        if existing:
            continue
        session.add(ReportDefinition(
            name=d["name"],
            description=d["description"],
            query_key=d["query_key"],
            parameters={},
            output_format=d["output_format"],
            frequency=d["frequency"],
            recipient_roles=[],
            is_active=True,
            is_system=True,
        ))
        created += 1

    session.commit()
    print(f"[OK] Report definitions seeded: {created} created, "
          f"{len(DEFINITIONS) - created} already existed.")


# ----------------- Run Seed -----------------

def seed_org_role_permissions_for_modules(session, module_ids):
    """
    Grant can_view on every module in module_ids to every active OrgRole
    across all organisations.  Idempotent — skips rows that already exist.

    The dashboard_service already gates which widgets each OrgRole sees, so
    granting view at the module level is safe for all roles.
    """
    module_names_granted = []
    org_roles = session.query(OrgRole).filter(OrgRole.is_active.is_(True)).all()

    for module_name, module_id in module_ids.items():
        for org_role in org_roles:
            exists = session.query(OrgRolePermission).filter_by(
                org_role_id=org_role.id,
                module_id=module_id,
            ).first()
            if exists:
                continue
            session.add(OrgRolePermission(
                org_role_id=org_role.id,
                module_id=module_id,
                can_view=True,
                can_add=False,
                can_edit=False,
                can_delete=False,
                can_approve=False,
                can_assign=False,
                can_export=False,
                can_import=False,
            ))
        module_names_granted.append(module_name)

    session.commit()
    if module_names_granted:
        print(f"[OK] org_role_permissions granted for: {', '.join(module_names_granted)}"
              f" -> {len(org_roles)} org role(s)")
    else:
        print("[INFO] org_role_permissions: all entries already exist.")


def seed_test_register(session, org):
    """
    SRS §5.1.1 — Seed the Test Register for a KPTCL organisation.

    Creates TestingRequest (is_schedule_template=True) + TestRequestSchedule rows
    for each mandatory periodic test grouped by equipment type.

    Idempotent — skips entries whose request_number already exists.
    """
    if not org:
        print("[SKIP] seed_test_register: no org supplied.")
        return

    from models import (
        CategoryMaster, OrgRole, ScheduleFrequency,
        TestingRequest, TestingRequestStatus, TestRequestSchedule, RequestCategory
    )
    from datetime import datetime, timezone
    import uuid as _uuid

    now = datetime.now(timezone.utc)

    # ── look up system user (org admin) as template originator ────────────────
    from models import User, OrgUserRole
    admin_role = session.query(OrgRole).filter_by(
        organization_id=org.id, name="Org Admin"
    ).first()
    system_user = None
    if admin_role:
        link = session.query(OrgUserRole).filter_by(org_role_id=admin_role.id).first()
        if link:
            system_user = session.query(User).filter_by(id=link.user_id).first()
    if not system_user:
        system_user = session.query(User).filter_by(email="superadmin@system.com").first()
    if not system_user:
        print("[WARN] seed_test_register: no system user found — skipping.")
        return

    # ── look up key OrgRoles ──────────────────────────────────────────────────
    def get_role(name):
        return session.query(OrgRole).filter_by(
            organization_id=org.id, name=name
        ).first()

    aee_maintenance = get_role("AEE Maintenance")
    ee_tlss         = get_role("EE TLSS")
    field_tester    = get_role("Field Tester")
    aee_role        = get_role("AEE")

    responsible_default = aee_maintenance
    reviewing_default   = ee_tlss

    # ── helper: get equipment type master ─────────────────────────────────────
    def get_eq_type(name):
        return session.query(CategoryMaster).filter_by(
            name=name, is_active=True
        ).first()

    # ── register catalogue ────────────────────────────────────────────────────
    # (equipment_type_name, test_name, template_key, frequency, advance_days,
    #  responsible_role, reviewing_role, revised_periodicity_days, oem_reference)
    REGISTER = [
        # ── Power Transformer ─────────────────────────────────────────────────
        ("Power Transformer", "DGA — Dissolved Gas Analysis",
         "transformer_dga",
         ScheduleFrequency.yearly, 15,
         aee_maintenance, ee_tlss, 180,
         "IS 10593 / IS 1866 Cl.4.2"),

        ("Power Transformer", "BDV — Oil Dielectric Strength",
         "transformer_bdv",
         ScheduleFrequency.semi_annual, 10,
         aee_maintenance, ee_tlss, 90,
         "IS 6792 Cl.5.1"),

        ("Power Transformer", "IR — Winding Insulation Resistance",
         "transformer_ir",
         ScheduleFrequency.semi_annual, 10,
         aee_maintenance, ee_tlss, None,
         "IS 2026 Pt.1"),

        ("Power Transformer", "Tan Delta / Power Factor Test",
         "transformer_tan_delta",
         ScheduleFrequency.triennial, 30,
         aee_maintenance, ee_tlss, None,
         "IS 2026 Pt.1 / IEC 60076-1"),

        # ── Circuit Breaker ───────────────────────────────────────────────────
        ("Circuit Breaker", "SF6 Gas Purity Test",
         "cb_sf6_purity",
         ScheduleFrequency.yearly, 15,
         aee_maintenance, ee_tlss, 180,
         "IEC 60376 / IS 13734"),

        ("Circuit Breaker", "SF6 Gas Pressure Check",
         "cb_sf6_pressure",
         ScheduleFrequency.quarterly, 7,
         field_tester or aee_maintenance, aee_maintenance or ee_tlss, None,
         "Manufacturer O&M Manual"),

        ("Circuit Breaker", "IR — Insulation Resistance",
         "cb_ir",
         ScheduleFrequency.semi_annual, 10,
         aee_maintenance, ee_tlss, None,
         "IEC 62271-100"),

        ("Circuit Breaker", "Contact Resistance Test",
         "cb_contact_resistance",
         ScheduleFrequency.semi_annual, 10,
         aee_maintenance, ee_tlss, None,
         "IEC 62271-100 Cl.6.4"),

        # ── Current Transformer ───────────────────────────────────────────────
        ("Current Transformer", "IR — Insulation Resistance",
         "ct_ir",
         ScheduleFrequency.yearly, 15,
         aee_maintenance, ee_tlss, None,
         "IS 2705 / IEC 61869-2"),

        ("Current Transformer", "Ratio & Phase Error Test",
         "ct_ratio",
         ScheduleFrequency.yearly, 15,
         aee_maintenance, ee_tlss, None,
         "IS 2705 Cl.8"),

        # ── Lightning Arrester ────────────────────────────────────────────────
        ("Lightning Arrester", "IR / Leakage Current Test",
         "la_ir",
         ScheduleFrequency.yearly, 15,
         aee_maintenance, ee_tlss, 180,
         "IS 3070 Pt.3 / IEC 60099-4"),

        ("Lightning Arrester", "V-I Characteristic Test",
         "la_vi",
         ScheduleFrequency.triennial, 30,
         aee_maintenance, ee_tlss, None,
         "IEC 60099-4 Cl.8.3"),

        # ── Battery Bank ──────────────────────────────────────────────────────
        ("Battery Bank", "Specific Gravity Check",
         "battery_specific_gravity",
         ScheduleFrequency.quarterly, 7,
         field_tester or aee_maintenance, aee_maintenance or ee_tlss, None,
         "IS 1651 / Manufacturer Manual"),

        ("Battery Bank", "Float Voltage per Cell",
         "battery_float_voltage",
         ScheduleFrequency.monthly, 5,
         field_tester or aee_maintenance, aee_maintenance or ee_tlss, None,
         "IS 1652 / Manufacturer Manual"),

        ("Battery Bank", "Discharge / Capacity Test",
         "battery_capacity",
         ScheduleFrequency.yearly, 15,
         aee_maintenance, ee_tlss, None,
         "IS 1651 Cl.10"),
    ]

    created = 0
    skipped = 0

    for (eq_type_name, test_name, tpl_key, freq, adv_days,
         resp_role, rev_role, revised_days, oem_ref) in REGISTER:

        eq_type = get_eq_type(eq_type_name)
        if not eq_type:
            print(f"  [WARN] Equipment type '{eq_type_name}' not found — skipping '{test_name}'")
            skipped += 1
            continue

        # Idempotency: skip if a template with this title + org + eq_type already exists
        existing = session.query(TestingRequest).filter_by(
            title=test_name,
            organization_id=org.id,
            equipment_type_id=eq_type.id,
            is_schedule_template=True,
        ).first()
        if existing:
            skipped += 1
            continue

        req_num = f"TR-REG-{now.strftime('%Y%m%d')}-{(created + 1):04d}"
        req = TestingRequest(
            id=_uuid.uuid4(),
            request_number=req_num,
            title=test_name,
            description=f"Mandatory periodic test per {oem_ref}" if oem_ref else None,
            equipment_type_id=eq_type.id,
            organization_id=org.id,
            request_category=RequestCategory.test,
            priority="normal",
            notes=oem_ref,
            status=TestingRequestStatus.draft,
            is_schedule_template=True,
            is_direct_submission=False,
            originator_id=system_user.id,
            created_by=system_user.id,
            requested_date=now,
        )
        session.add(req)
        session.flush()

        sched = TestRequestSchedule(
            id=_uuid.uuid4(),
            test_request_id=req.id,
            organization_id=org.id,
            frequency=freq,
            start_date=now,
            next_run_date=now,   # placeholder; overwritten on commissioning
            advance_days=adv_days,
            is_active=True,
            responsible_role_id=getattr(resp_role, "id", None),
            reviewing_role_id=getattr(rev_role, "id", None),
            revised_periodicity_days=revised_days,
            oem_reference=oem_ref,
            created_by=system_user.id,
        )
        session.add(sched)
        created += 1

    session.commit()
    print(
        f"[OK] Test Register seeded: {created} templates created, "
        f"{skipped} skipped (already exist or missing eq type)."
    )


def migrate_new_status_values(session):
    """
    Add new TestingRequestStatus enum values to PostgreSQL.
    PostgreSQL requires explicit ALTER TYPE to add enum values.
    Safe to run multiple times — uses IF NOT EXISTS.
    """
    from sqlalchemy import text
    new_values = ["under_review", "finance_pending", "outcome_active", "commissioned"]
    for val in new_values:
        try:
            session.execute(text(
                f"ALTER TYPE testingrequeststatus ADD VALUE IF NOT EXISTS '{val}';"
            ))
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"[WARN] Could not add enum value '{val}': {e}")

    # Add next_action and schedule_frequency columns to recommendations
    try:
        session.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='recommendations'
                    AND column_name='next_action'
                ) THEN
                    ALTER TABLE public.recommendations ADD COLUMN next_action VARCHAR(20);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema='public' AND table_name='recommendations'
                    AND column_name='schedule_frequency'
                ) THEN
                    ALTER TABLE public.recommendations ADD COLUMN schedule_frequency VARCHAR(20);
                END IF;
            END$$;
        """))
        session.commit()
        print("[OK] recommendations.next_action + schedule_frequency columns ensured.")
    except Exception as e:
        session.rollback()
        print(f"[WARN] recommendations column migration: {e}")

    print("[OK] Status enum migration complete.")


def seed_direct_submission_templates(session) -> int:
    """
    Seed OrgTestTemplate rows for direct-submission forms:
      - taqc_inspection  (TA&QC Inspection form)
      - failure_registry (Equipment Failure Registry form)

    Idempotent — skips existing rows.
    Returns count of newly inserted rows.
    """
    from models import OrgTestTemplate

    TEMPLATES = {
        "taqc_inspection": {
            "key": "taqc_inspection",
            "name": "TA&QC Inspection",
            "description": "Substation Inspection — record observations and compliance actions.",
            "sections": [
                {
                    "title": "Inspection Details",
                    "fields": [
                        {"key": "substation",          "label": "Substation Name / Area",  "type": "text",     "required": True},
                        {"key": "inspection_date",     "label": "Date of Inspection",       "type": "date",     "required": True},
                        {"key": "inspection_category", "label": "Inspection Category",      "type": "dropdown", "required": True,
                         "options": ["Electrical Safety", "Civil", "Fire Safety", "Documentation", "Environmental", "General Maintenance"]},
                    ],
                },
                {
                    "title": "Observation",
                    "fields": [
                        {"key": "observation_description", "label": "Description of Observation", "type": "textarea", "required": True},
                        {"key": "severity",                "label": "Severity",                   "type": "dropdown", "required": True,
                         "options": ["Major", "Minor", "Advisory"]},
                    ],
                },
                {
                    "title": "Compliance",
                    "fields": [
                        {"key": "target_compliance_date", "label": "Target Compliance Date", "type": "date",     "required": False},
                        {"key": "remarks",                "label": "Remarks",                "type": "textarea", "required": False},
                    ],
                },
            ],
        },
        "failure_registry": {
            "key": "failure_registry",
            "name": "Equipment Failure Registry",
            "description": "Record equipment failures for tracking and root-cause analysis.",
            "sections": [
                {
                    "title": "Failure Information",
                    "fields": [
                        {"key": "failure_date",        "label": "Date of Failure",       "type": "date",     "required": True},
                        {"key": "failure_category",    "label": "Failure Category",      "type": "dropdown", "required": True,
                         "options": ["Electrical", "Mechanical", "Oil", "Protection", "Thermal", "Other"]},
                        {"key": "failure_description", "label": "Description of Failure","type": "textarea", "required": True},
                        {"key": "root_cause_analysis", "label": "Root Cause Analysis",   "type": "textarea", "required": False},
                    ],
                },
                {
                    "title": "Outage Impact",
                    "fields": [
                        {"key": "outage_duration_hours", "label": "Outage Duration (hours)",      "type": "number",   "required": False},
                        {"key": "affected_consumers",    "label": "Affected Consumers (count)",   "type": "number",   "required": False},
                        {"key": "outage_impact",         "label": "Outage Impact Description",    "type": "textarea", "required": False},
                    ],
                },
                # NOTE: "Outcome" section removed — the API appends "Outcome & Scheduling"
                # from the overall_assessment template for failure_registry forms,
                # which covers next_action, schedule, summary and notes.
            ],
        },
    }

    count = 0
    for key, data in TEMPLATES.items():
        existing = session.query(OrgTestTemplate).filter(
            OrgTestTemplate.template_key == key,
            OrgTestTemplate.org_id == None,  # noqa: E711
        ).first()
        if existing:
            # Always update template_data so changes to sections/fields are picked up
            existing.template_data = data
            existing.version = (existing.version or 1) + 1
        else:
            session.add(OrgTestTemplate(
                template_key=key,
                org_id=None,
                test_type_id=None,
                template_data=data,
                is_system=True,
                version=1,
            ))
            count += 1
    session.commit()
    return count


def seed_annual_audit_templates(session) -> int:
    """
    Seed Annual Audit categories and category-specific OrgTestTemplate rows.

    Annual Audit is separate from taqc_inspection commissioning. Templates are
    linked to CategoryDetails.id through OrgTestTemplate.test_type_id.
    """
    from models import CategoryMaster, CategoryDetails, OrgTestTemplate

    master = session.query(CategoryMaster).filter(
        CategoryMaster.name == "Annual Audit Categories"
    ).first()
    if not master:
        master = CategoryMaster(
            name="Annual Audit Categories",
            description="Annual Substation Audit Observation Categories",
            is_active=True,
        )
        session.add(master)
        session.flush()

    template_specs = [
        (
            "Electrical Safety",
            "audit_electrical_safety",
            "Electrical Safety Audit",
            [
                {
                    "title": "Earthing System",
                    "fields": [
                        {"key": "earthing_condition", "label": "Earthing Condition", "type": "dropdown", "required": True, "options": ["Good", "Damaged", "Corroded"]},
                        {"key": "earthing_resistance", "label": "Earthing Resistance", "type": "number", "unit": "ohms", "required": False},
                        {"key": "earthing_photo", "label": "Earthing Photograph", "type": "file", "required": False},
                    ],
                },
                {
                    "title": "Safety Protection",
                    "fields": [
                        {"key": "danger_board_available", "label": "Danger Board Available", "type": "boolean", "required": False},
                        {"key": "shock_hazard_observed", "label": "Shock Hazard Observed", "type": "boolean", "required": False},
                        {"key": "safety_remarks", "label": "Safety Remarks", "type": "textarea", "required": False},
                    ],
                },
            ],
        ),
        (
            "Civil",
            "audit_civil",
            "Civil Audit",
            [
                {
                    "title": "Civil Condition",
                    "fields": [
                        {"key": "foundation_condition", "label": "Foundation Condition", "type": "dropdown", "required": True, "options": ["Good", "Cracked", "Settled", "Damaged"]},
                        {"key": "yard_drainage_status", "label": "Yard Drainage Status", "type": "dropdown", "required": False, "options": ["Clear", "Blocked", "Water Logging"]},
                        {"key": "fencing_condition", "label": "Fencing / Compound Condition", "type": "dropdown", "required": False, "options": ["Good", "Damaged", "Missing"]},
                        {"key": "civil_photo", "label": "Civil Observation Photo", "type": "file", "required": False},
                    ],
                },
            ],
        ),
        (
            "Fire Safety",
            "audit_fire_safety",
            "Fire Safety Audit",
            [
                {
                    "title": "Fire Safety Equipment",
                    "fields": [
                        {"key": "fire_extinguisher_available", "label": "Fire Extinguisher Available", "type": "boolean", "required": False},
                        {"key": "fire_extinguisher_expiry", "label": "Fire Extinguisher Expiry", "type": "date", "required": False},
                        {"key": "fire_alarm_operational", "label": "Fire Alarm Operational", "type": "boolean", "required": False},
                        {"key": "oil_leakage_present", "label": "Oil Leakage Present", "type": "boolean", "required": False},
                        {"key": "fire_safety_photo", "label": "Fire Safety Photograph", "type": "file", "required": False},
                    ],
                },
            ],
        ),
        (
            "Documentation",
            "audit_documentation",
            "Documentation Audit",
            [
                {
                    "title": "Records Verification",
                    "fields": [
                        {"key": "maintenance_register_updated", "label": "Maintenance Register Updated", "type": "boolean", "required": False},
                        {"key": "test_records_available", "label": "Test Records Available", "type": "boolean", "required": False},
                        {"key": "single_line_diagram_available", "label": "Single Line Diagram Available", "type": "boolean", "required": False},
                        {"key": "document_gap_details", "label": "Documentation Gap Details", "type": "textarea", "required": False},
                    ],
                },
            ],
        ),
        (
            "Environmental",
            "audit_environmental",
            "Environmental Audit",
            [
                {
                    "title": "Environmental Checks",
                    "fields": [
                        {"key": "oil_spillage_observed", "label": "Oil Spillage Observed", "type": "boolean", "required": False},
                        {"key": "waste_disposal_status", "label": "Waste Disposal Status", "type": "dropdown", "required": False, "options": ["Compliant", "Non-Compliant", "Not Applicable"]},
                        {"key": "vegetation_clearance_status", "label": "Vegetation Clearance Status", "type": "dropdown", "required": False, "options": ["Clear", "Needs Trimming", "Unsafe"]},
                        {"key": "environmental_photo", "label": "Environmental Observation Photo", "type": "file", "required": False},
                    ],
                },
            ],
        ),
        (
            "General Maintenance",
            "audit_general_maintenance",
            "General Maintenance Audit",
            [
                {
                    "title": "General Maintenance",
                    "fields": [
                        {"key": "cleanliness_status", "label": "Cleanliness Status", "type": "dropdown", "required": False, "options": ["Good", "Average", "Poor"]},
                        {"key": "illumination_status", "label": "Illumination Status", "type": "dropdown", "required": False, "options": ["Adequate", "Inadequate", "Not Working"]},
                        {"key": "access_path_condition", "label": "Access Path Condition", "type": "dropdown", "required": False, "options": ["Good", "Obstructed", "Damaged"]},
                        {"key": "maintenance_remarks", "label": "Maintenance Remarks", "type": "textarea", "required": False},
                    ],
                },
            ],
        ),
    ]

    count = 0
    for category_name, template_key, template_name, category_sections in template_specs:
        detail = session.query(CategoryDetails).filter(
            CategoryDetails.category_master_id == master.id,
            CategoryDetails.name == category_name,
        ).first()
        if not detail:
            detail = CategoryDetails(
                category_master_id=master.id,
                name=category_name,
                description=f"{category_name} annual audit observations",
                category_type="annual_audit",
                is_active=True,
            )
            session.add(detail)
            session.flush()
        else:
            detail.category_type = "annual_audit"

        template_data = {
            "key": template_key,
            "name": template_name,
            "description": f"{category_name} annual audit observation template",
            "template_type": "annual_audit",
            "sections": category_sections + [
                {
                    "title": "Observation Assessment",
                    "fields": [
                        {"key": "observation_description", "label": "Observation Description", "type": "textarea", "required": True},
                        {"key": "severity", "label": "Severity", "type": "dropdown", "required": True, "options": ["Major", "Minor", "Advisory"]},
                        {"key": "target_compliance_date", "label": "Target Compliance Date", "type": "date", "required": True},
                        {"key": "overall_result", "label": "Overall Result", "type": "dropdown", "required": True, "options": ["Compliant", "Non-Compliant", "Conditional"]},
                    ],
                },
                {
                    "title": "Compliance Action",
                    "fields": [
                        {"key": "corrective_action", "label": "Corrective Action", "type": "textarea", "required": False},
                        {"key": "compliance_evidence", "label": "Compliance Evidence", "type": "file", "required": False},
                        {"key": "date_of_compliance", "label": "Date of Compliance", "type": "date", "required": False},
                        {"key": "review_remarks", "label": "Review Remarks", "type": "textarea", "required": False},
                    ],
                },
            ],
        }

        existing = session.query(OrgTestTemplate).filter(
            OrgTestTemplate.template_key == template_key,
            OrgTestTemplate.org_id == None,  # noqa: E711
        ).first()
        if existing:
            existing.test_type_id = detail.id
            existing.template_data = template_data
            existing.is_system = True
        else:
            session.add(OrgTestTemplate(
                template_key=template_key,
                org_id=None,
                test_type_id=detail.id,
                template_data=template_data,
                is_system=True,
                version=1,
            ))
            count += 1

    session.commit()
    return count


def seed_cumulative_template(session) -> int:
    """
    Seed the Operations Tracking OrgTestTemplate (CUMULATIVE_DIFF rules).

    Strategy — never modify existing CategoryMaster / CategoryDetails rows:
    - CategoryMaster "Repair Lifecycle" is owned by the stage-based workflow
      engine; touching it breaks existing repair lifecycle flows.
    - We only CREATE the master/detail when they are completely absent, and we
      never update any fields on rows that already exist.
    - Only the OrgTestTemplate (template_key="operations_tracking") is
      upserted, because it is owned solely by this feature.
    """
    from models import CategoryMaster, CategoryDetails, OrgTestTemplate

    # ── CategoryMaster — look up only, create if truly absent ─────────────────
    master = session.query(CategoryMaster).filter(
        CategoryMaster.name == "Repair Lifecycle"
    ).first()
    if not master:
        master = CategoryMaster(
            name="Repair Lifecycle",
            description="Repair and Lifecycle workflow test types",
            is_active=True,
        )
        session.add(master)
        session.flush()
    # Never modify an existing master row.

    # ── CategoryDetails — look up only, create if absent ─────────────────────
    # (name, description, category_type)
    # Operations Tracking: category_type='maintenance' → Maintenance dropdown.
    # Others: workflow-launcher subtypes, no category_type assigned here.
    subtypes = [
        ("Breakdown Repair",          "Unplanned breakdown repair workflow",                                                          None),
        ("Preventive Maintenance",     "Scheduled preventive maintenance workflow",                                                    None),
        ("Major Maintenance Overhaul", "Planned major maintenance and overhaul workflow",                                              None),
        ("Operations Tracking",        "Multi-session cumulative operations tracking — triggers overhaul when threshold crossed",  "maintenance"),
    ]
    detail_ids = {}
    for name, desc, cat_type in subtypes:
        d = session.query(CategoryDetails).filter(
            CategoryDetails.category_master_id == master.id,
            CategoryDetails.name == name,
        ).first()
        if not d:
            d = CategoryDetails(
                category_master_id=master.id,
                name=name,
                description=desc,
                category_type=cat_type,
                is_active=True,
            )
            session.add(d)
            session.flush()
        # Never update existing rows — they belong to the live system.
        detail_ids[name] = d.id

    # ── Operations Tracking template with rules[] ─────────────────────────────
    OPS_KEY = "operations_tracking"
    ops_template_data = {
        "name": "Operations Tracking",
        "key": OPS_KEY,
        "description": "Multi-session operations tracking with cumulative difference calculation for overhaul triggering.",
        "enable_cumulative": True,
        "multi_session": True,
        "sections": [
            {
                "title": "Session Reading",
                "fields": [
                    {
                        "key": "reading",
                        "label": "Operations Reading",
                        "type": "number",
                        "required": True,
                        "unit": "ops",
                    },
                    {
                        "key": "reading_date",
                        "label": "Reading Date",
                        "type": "date",
                        "required": True,
                    },
                    {
                        "key": "notes",
                        "label": "Notes",
                        "type": "textarea",
                        "required": False,
                    },
                ],
            }
        ],
        "rules": [
            {
                "field": "reading",
                "type": "CUMULATIVE_DIFF",
                "config": {
                    "order_by": "reading_date",
                    "group_by": "equipment_id",
                    "requires_multi_session": True,
                    "reset_on_drop": True,
                },
            }
        ],
    }

    existing = session.query(OrgTestTemplate).filter(
        OrgTestTemplate.template_key == OPS_KEY,
        OrgTestTemplate.org_id == None,  # noqa: E711
    ).first()
    count = 0
    if existing:
        existing.test_type_id = detail_ids["Operations Tracking"]
        existing.template_data = ops_template_data
        existing.is_system = True
    else:
        session.add(OrgTestTemplate(
            template_key=OPS_KEY,
            org_id=None,
            test_type_id=detail_ids["Operations Tracking"],
            template_data=ops_template_data,
            is_system=True,
            version=1,
        ))
        count = 1

    session.commit()
    print(f"[OK] Repair Lifecycle / Operations Tracking template seeded (master_id={master.id}).")
    return count


def seed_calibration_template(session) -> int:
    """
    Seed the Calibration OrgTestTemplate (DATE_ADD rule).

    Strategy — same as seed_cumulative_template:
    - Never modify existing CategoryMaster / CategoryDetails rows.
    - Only CREATE master/detail when completely absent.
    - Upsert the OrgTestTemplate (template_key="calibration") which is
      owned solely by this feature.
    """
    from models import CategoryMaster, CategoryDetails, OrgTestTemplate

    # ── CategoryMaster — look up only, create if truly absent ─────────────────
    master = session.query(CategoryMaster).filter(
        CategoryMaster.name == "Repair Lifecycle"
    ).first()
    if not master:
        master = CategoryMaster(
            name="Repair Lifecycle",
            description="Repair and Lifecycle workflow test types",
            is_active=True,
        )
        session.add(master)
        session.flush()
    # Never modify an existing master row.

    # ── CategoryDetails — look up, create if absent ───────────────────────────
    cal_name = "Calibration"
    d = session.query(CategoryDetails).filter(
        CategoryDetails.category_master_id == master.id,
        CategoryDetails.name == cal_name,
    ).first()
    if not d:
        d = CategoryDetails(
            category_master_id=master.id,
            name=cal_name,
            description="Equipment calibration lifecycle — DATE_ADD rule, pre-due scheduling, FAIL → repair trigger.",
            category_type="maintenance",
            is_active=True,
        )
        session.add(d)
        session.flush()
    # Never update existing rows.

    # ── Calibration template with DATE_ADD rule ───────────────────────────────
    CAL_KEY = "calibration"
    cal_template_data = {
        "name": "Calibration",
        "key": CAL_KEY,
        "description": "Equipment calibration lifecycle tracking. Computes next due date and triggers repair on failure.",
        "enable_calibration": True,
        "multi_session": True,
        "sections": [
            {
                "title": "Calibration Record",
                "fields": [
                    {
                        "key": "calibration_date",
                        "label": "Calibration Date",
                        "type": "date",
                        "required": True,
                    },
                    {
                        "key": "validity_months",
                        "label": "Validity (Months)",
                        "type": "number",
                        "required": True,
                        "unit": "months",
                    },
                    {
                        "key": "overall_result",
                        "label": "Result",
                        "type": "dropdown",
                        "options": ["Pass", "Fail"],
                        "required": True,
                    },
                    {
                        "key": "calibrated_by",
                        "label": "Calibrated By (Agency / Lab)",
                        "type": "text",
                        "required": False,
                    },
                    {
                        "key": "certificate_number",
                        "label": "Certificate Number",
                        "type": "text",
                        "required": False,
                    },
                    {
                        "key": "notes",
                        "label": "Notes",
                        "type": "textarea",
                        "required": False,
                    },
                ],
            }
        ],
        "rules": [
            {
                "field": "calibration_date",
                "type": "DATE_ADD",
                "config": {
                    "validity_field": "validity_months",
                    "result_field": "overall_result",
                    "order_by": "calibration_date",
                    "group_by": "equipment_id",
                    "requires_multi_session": True,
                },
            }
        ],
    }

    existing = session.query(OrgTestTemplate).filter(
        OrgTestTemplate.template_key == CAL_KEY,
        OrgTestTemplate.org_id == None,  # noqa: E711
    ).first()
    count = 0
    if existing:
        existing.test_type_id = d.id
        existing.template_data = cal_template_data
        existing.is_system = True
    else:
        session.add(OrgTestTemplate(
            template_key=CAL_KEY,
            org_id=None,
            test_type_id=d.id,
            template_data=cal_template_data,
            is_system=True,
            version=1,
        ))
        count = 1

    session.commit()
    print(f"[OK] Calibration template seeded (master_id={master.id}, detail_id={d.id}).")
    return count


def seed_tr_workflows(session):
    """
    Seed the IntegratedWorkflowEngine with three workflows:
      1. failure_registry  — FR Pass 1 only (Test Assigner initial-approve)
      2. testing_request   — TR flow shared by FR-spawned TR and Adhoc TR
      3. taqc_inspection   — E&C commissioning flow

    Idempotent — skips if workflow already seeded.
    Permission matrix rows use role name lookup (OrgRole) for all orgs.
    """
    from models import (
        Workflow, WorkflowState, WorkflowTransition, PermissionMatrix, OrgRole
    )

    # ── Role name → all OrgRole ids mapping (across all orgs) ────────────────
    def _role_ids(role_name: str):
        return [r.id for r in session.query(OrgRole).filter_by(name=role_name, is_active=True).all()]

    def _get_or_create_workflow(wf_type: str, name: str):
        existing = session.query(Workflow).filter_by(
            workflow_type=wf_type, organization_id=None, is_active=True
        ).first()
        if existing:
            print(f"  [SKIP] Workflow '{wf_type}' already exists.")
            return existing, True
        wf = Workflow(
            name=name,
            workflow_type=wf_type,
            organization_id=None,
            is_active=True,
            version=1,
        )
        session.add(wf)
        session.flush()
        return wf, False

    def _state(wf_id, code, name, state_type="intermediate", order=0, color="#3FA9F5"):
        existing = session.query(WorkflowState).filter_by(
            workflow_id=wf_id, state_code=code
        ).first()
        if existing:
            return existing
        s = WorkflowState(
            workflow_id=wf_id,
            state_code=code,
            state_name=name,
            state_type=state_type,
            display_order=order,
            color=color,
            is_active=True,
        )
        session.add(s)
        session.flush()
        return s

    def _transition(wf_id, from_state, to_state, action, label,
                    color="#3FA9F5", requires_comment=False,
                    conditions=None, order=0):
        existing = session.query(WorkflowTransition).filter_by(
            workflow_id=wf_id,
            from_state_id=from_state.id,
            to_state_id=to_state.id,
            action_code=action,
        ).first()
        if existing:
            return existing
        t = WorkflowTransition(
            workflow_id=wf_id,
            from_state_id=from_state.id,
            to_state_id=to_state.id,
            transition_name=label,
            action_code=action,
            button_label=label,
            button_color=color,
            requires_comment=requires_comment,
            conditions=conditions,
            display_order=order,
            is_active=True,
        )
        session.add(t)
        session.flush()
        return t

    def _permission(wf_id, transition, role_name, scope="department_tree"):
        for role_id in _role_ids(role_name):
            existing = session.query(PermissionMatrix).filter_by(
                transition_id=transition.id, role_id=role_id
            ).first()
            if existing:
                continue
            session.add(PermissionMatrix(
                workflow_id=wf_id,
                transition_id=transition.id,
                role_id=role_id,
                scope_type=scope,
                can_execute=True,
                can_view=True,
                is_active=True,
            ))
        session.flush()

    # ══════════════════════════════════════════════════════════════════════════
    # 1. FAILURE REGISTRY WORKFLOW
    # ══════════════════════════════════════════════════════════════════════════
    print("  Seeding: failure_registry workflow …")
    fr_wf, existed = _get_or_create_workflow("failure_registry", "Failure Registry Workflow")
    if not existed:
        # States
        fr_submitted  = _state(fr_wf.id, "submitted",  "Submitted",  "intermediate", 0, "#FF9800")
        fr_approved   = _state(fr_wf.id, "approved",   "Approved",   "terminal",     1, "#4CAF50")
        fr_rejected   = _state(fr_wf.id, "rejected",   "Rejected",   "terminal",     2, "#F44336")

        # Transitions
        t_init_approve = _transition(fr_wf.id, fr_submitted, fr_approved,
                                     "initial_approve", "Initial Approve",
                                     color="#4CAF50", order=0)
        t_fr_reject    = _transition(fr_wf.id, fr_submitted, fr_rejected,
                                     "reject", "Reject",
                                     color="#F44336", requires_comment=True, order=1)

        # Permissions
        _permission(fr_wf.id, t_init_approve, "Test Assigner")
        _permission(fr_wf.id, t_fr_reject,    "Test Assigner")

        session.commit()
        print("  [OK] failure_registry workflow seeded.")

    # ══════════════════════════════════════════════════════════════════════════
    # 2. TESTING REQUEST WORKFLOW  (shared by FR-spawned TR + Adhoc TR)
    # ══════════════════════════════════════════════════════════════════════════
    print("  Seeding: testing_request workflow …")
    tr_wf, existed = _get_or_create_workflow("testing_request", "Testing Request Workflow")
    if not existed:
        # States
        s_submitted      = _state(tr_wf.id, "submitted",      "Submitted",        "intermediate",  0, "#FF9800")
        s_assigned       = _state(tr_wf.id, "assigned",       "Assigned",         "intermediate",  1, "#2196F3")
        s_accepted       = _state(tr_wf.id, "accepted",       "Accepted",         "intermediate",  2, "#03A9F4")
        s_under_approval = _state(tr_wf.id, "under_approval", "Under Approval",   "intermediate",  3, "#9C27B0")
        s_under_review   = _state(tr_wf.id, "under_review",   "Under Review",     "intermediate",  4, "#FF5722")
        s_finance_pend   = _state(tr_wf.id, "finance_pending","Finance Pending",  "intermediate",  5, "#FF9800")
        s_outcome        = _state(tr_wf.id, "outcome_active", "Outcome Active",   "terminal",      6, "#4CAF50")
        s_closed         = _state(tr_wf.id, "closed",         "Closed",           "terminal",      7, "#9E9E9E")
        s_rejected       = _state(tr_wf.id, "rejected",       "Rejected",         "terminal",      8, "#F44336")

        # submitted → assigned / rejected
        t_assign = _transition(tr_wf.id, s_submitted, s_assigned,
                               "approve_and_assign", "Approve & Assign", color="#4CAF50", order=0)
        t_tr_reject = _transition(tr_wf.id, s_submitted, s_rejected,
                                  "reject", "Reject", color="#F44336",
                                  requires_comment=True, order=1)

        # assigned → accepted
        t_accept = _transition(tr_wf.id, s_assigned, s_accepted,
                               "accept", "Accept Assignment", color="#2196F3", order=0)

        # accepted → under_approval
        t_submit_result = _transition(tr_wf.id, s_accepted, s_under_approval,
                                      "submit_result", "Submit Result", color="#9C27B0", order=0)

        # under_approval → outcome_active (conditional on next_action)
        t_approve_maint = _transition(tr_wf.id, s_under_approval, s_outcome,
                                      "approve", "Approve",
                                      conditions={"next_action": "maintenance"}, order=0)
        t_approve_insp  = _transition(tr_wf.id, s_under_approval, s_outcome,
                                      "approve", "Approve",
                                      conditions={"next_action": "inspection"}, order=1)
        t_approve_rl    = _transition(tr_wf.id, s_under_approval, s_outcome,
                                      "approve", "Approve",
                                      conditions={"next_action": "repair_cycle"}, order=2)
        t_approve_none  = _transition(tr_wf.id, s_under_approval, s_closed,
                                      "approve", "Approve",
                                      conditions={"next_action": "none"}, order=3)
        t_approve_repl  = _transition(tr_wf.id, s_under_approval, s_finance_pend,
                                      "approve", "Approve",
                                      conditions={"next_action": "replacement"}, order=4)

        # under_approval → under_review (tech reject)
        t_tech_reject = _transition(tr_wf.id, s_under_approval, s_under_review,
                                    "reject", "Reject", color="#F44336",
                                    requires_comment=True, order=5)

        # under_review → accepted (tester resubmit)
        t_resubmit = _transition(tr_wf.id, s_under_review, s_accepted,
                                 "resubmit", "Resubmit", color="#FF5722", order=0)

        # finance_pending → outcome_active / under_review
        t_fin_approve = _transition(tr_wf.id, s_finance_pend, s_outcome,
                                    "finance_approve", "Finance Approve", color="#4CAF50", order=0)
        t_fin_reject  = _transition(tr_wf.id, s_finance_pend, s_under_review,
                                    "finance_reject", "Finance Reject", color="#F44336",
                                    requires_comment=True, order=1)

        # ── Permissions ────────────────────────────────────────────────────────
        _permission(tr_wf.id, t_assign,       "Test Assigner")
        _permission(tr_wf.id, t_tr_reject,    "Test Assigner")
        _permission(tr_wf.id, t_accept,       "Tester")
        _permission(tr_wf.id, t_accept,       "Field Tester")
        _permission(tr_wf.id, t_accept,       "Lab Tester")
        _permission(tr_wf.id, t_submit_result,"Tester")
        _permission(tr_wf.id, t_submit_result,"Field Tester")
        _permission(tr_wf.id, t_submit_result,"Lab Tester")

        for t_appr in [t_approve_maint, t_approve_insp, t_approve_rl,
                       t_approve_none, t_approve_repl, t_tech_reject]:
            _permission(tr_wf.id, t_appr, "Technical Approver")

        _permission(tr_wf.id, t_resubmit,    "Tester")
        _permission(tr_wf.id, t_resubmit,    "Field Tester")
        _permission(tr_wf.id, t_resubmit,    "Lab Tester")
        _permission(tr_wf.id, t_fin_approve, "Finance Approver")
        _permission(tr_wf.id, t_fin_reject,  "Finance Approver")

        session.commit()
        print("  [OK] testing_request workflow seeded.")

    # ══════════════════════════════════════════════════════════════════════════
    # 3. TAQC INSPECTION WORKFLOW
    # ══════════════════════════════════════════════════════════════════════════
    print("  Seeding: taqc_inspection workflow …")
    taqc_wf, existed = _get_or_create_workflow("taqc_inspection", "TAQC / E&C Inspection Workflow")
    if not existed:
        # States
        q_submitted      = _state(taqc_wf.id, "submitted",      "Submitted",       "intermediate", 0, "#FF9800")
        q_assigned       = _state(taqc_wf.id, "assigned",       "Assigned",        "intermediate", 1, "#2196F3")
        q_accepted       = _state(taqc_wf.id, "accepted",       "Accepted",        "intermediate", 2, "#03A9F4")
        q_under_approval = _state(taqc_wf.id, "under_approval", "Under Approval",  "intermediate", 3, "#9C27B0")
        q_under_review   = _state(taqc_wf.id, "under_review",   "Under Review",    "intermediate", 4, "#FF5722")
        q_commissioned   = _state(taqc_wf.id, "commissioned",   "Commissioned",    "terminal",     5, "#4CAF50")
        q_rejected       = _state(taqc_wf.id, "rejected",       "Rejected",        "terminal",     6, "#F44336")

        # Transitions
        t_q_assign    = _transition(taqc_wf.id, q_submitted, q_assigned,
                                    "approve_and_assign", "Approve & Assign", color="#4CAF50", order=0)
        t_q_reject    = _transition(taqc_wf.id, q_submitted, q_rejected,
                                    "reject", "Reject", color="#F44336",
                                    requires_comment=True, order=1)
        t_q_accept    = _transition(taqc_wf.id, q_assigned, q_accepted,
                                    "accept", "Accept Assignment", color="#2196F3", order=0)
        t_q_submit_ec = _transition(taqc_wf.id, q_accepted, q_under_approval,
                                    "submit_ec_form", "Submit E&C Form", color="#9C27B0", order=0)
        t_q_approve   = _transition(taqc_wf.id, q_under_approval, q_commissioned,
                                    "approve", "Approve & Commission", color="#4CAF50", order=0)
        t_q_tech_rej  = _transition(taqc_wf.id, q_under_approval, q_under_review,
                                    "reject", "Reject", color="#F44336",
                                    requires_comment=True, order=1)
        t_q_resubmit  = _transition(taqc_wf.id, q_under_review, q_accepted,
                                    "resubmit", "Resubmit", color="#FF5722", order=0)

        # Permissions
        _permission(taqc_wf.id, t_q_assign,    "Test Assigner")
        _permission(taqc_wf.id, t_q_reject,    "Test Assigner")
        _permission(taqc_wf.id, t_q_accept,    "Tester")
        _permission(taqc_wf.id, t_q_accept,    "Field Tester")
        _permission(taqc_wf.id, t_q_accept,    "Lab Tester")
        _permission(taqc_wf.id, t_q_submit_ec, "Tester")
        _permission(taqc_wf.id, t_q_submit_ec, "Field Tester")
        _permission(taqc_wf.id, t_q_submit_ec, "Lab Tester")
        _permission(taqc_wf.id, t_q_approve,   "Technical Approver")
        _permission(taqc_wf.id, t_q_tech_rej,  "Technical Approver")
        _permission(taqc_wf.id, t_q_resubmit,  "Tester")
        _permission(taqc_wf.id, t_q_resubmit,  "Field Tester")
        _permission(taqc_wf.id, t_q_resubmit,  "Lab Tester")

        session.commit()
        print("  [OK] taqc_inspection workflow seeded.")

    print("[OK] TR / FR / TAQC workflow seeding complete.")


def _seed_notification_event_catalogue(session) -> int:
    """
    Idempotent seed for NotificationEventCatalogue.
    Matches on event_type — upserts label/description/context_vars/default_roles
    so re-running the seed refreshes descriptions without duplicating rows.

    To add a new notification event type:
      1. Add an entry to _CATALOGUE below (or INSERT directly into the DB).
      2. No code change to any router or service is needed.
    """
    from models import NotificationEventCatalogue

    _CATALOGUE = [
        # ── Equipment ─────────────────────────────────────────────────────────
        dict(
            event_type="equipment_replacement",
            label="Equipment Replacement",
            group_name="Equipment",
            description="Fired when equipment is retired and a replacement unit is commissioned.",
            context_vars=["old_ueic", "new_ueic", "equipment_type", "department",
                          "reason_type", "reason", "replaced_by", "replaced_on"],
            default_roles=["EE TLSS", "SEE W&M", "CEE Transmission Zone"],
        ),
        # ── Evaluation ────────────────────────────────────────────────────────
        dict(
            event_type="eval_critical",
            label="Critical Test Result",
            group_name="Evaluation",
            description="Fired when a test evaluation result is CRITICAL (per test template thresholds).",
            context_vars=["equipment", "ueic", "test_type", "result", "dept",
                          "eval.overall", "eval.evaluated_at", "report.retriepdf"],
            default_roles=["EE TLSS", "SEE W&M", "CEE Transmission Zone", "AEE Maintenance"],
        ),
        dict(
            event_type="eval_alert",
            label="Alert Test Result",
            group_name="Evaluation",
            description="Fired when a test evaluation result is ALERT (per test template thresholds).",
            context_vars=["equipment", "ueic", "test_type", "result", "dept",
                          "eval.overall", "eval.evaluated_at", "report.retriepdf"],
            default_roles=["EE TLSS", "AEE Maintenance"],
        ),
        # ── Test Workflow ─────────────────────────────────────────────────────
        dict(
            event_type="request_submitted",
            label="Test Request Submitted",
            group_name="Test Workflow",
            description="Fired when an originator submits a new test request.",
            context_vars=["request.number", "request.title", "request.priority",
                          "request.submitted_by", "equipment.ueic", "equipment.department"],
            default_roles=["EE TLSS", "Department Head"],
        ),
        dict(
            event_type="tester_assigned",
            label="Tester Assigned to Request",
            group_name="Test Workflow",
            description="Fired when a test request is assigned to a field/lab tester.",
            context_vars=["request.number", "request.title", "request.assigned_to",
                          "request.due_date", "equipment.ueic"],
            default_roles=["Tester", "AEE Maintenance"],
        ),
        dict(
            event_type="tester_declined",
            label="Tester Declined Assignment",
            group_name="Test Workflow",
            description="Fired when a tester declines an assignment — notifies the Test Assigner.",
            context_vars=["request.number", "tester_name", "reason"],
            default_roles=["TestAssigner", "EE TLSS"],
        ),
        dict(
            event_type="test_submitted",
            label="Test Results Submitted",
            group_name="Test Workflow",
            description="Fired when a tester submits test results for review.",
            context_vars=["request.number", "request.title", "request.submitted_by",
                          "equipment.ueic", "eval.overall", "report.retriepdf"],
            default_roles=["EE TLSS", "Department Head"],
        ),
        dict(
            event_type="recommendation_approved",
            label="Recommendation Approved",
            group_name="Test Workflow",
            description="Fired when a technical approver approves a recommendation.",
            context_vars=["request.number", "recommendation_type", "product_count"],
            default_roles=["Originator", "AEE Maintenance"],
        ),
        dict(
            event_type="recommendation_rejected",
            label="Recommendation Rejected",
            group_name="Test Workflow",
            description="Fired when a technical approver rejects a recommendation.",
            context_vars=["request.number", "reason"],
            default_roles=["Tester", "Originator"],
        ),
        # ── Scheduling ────────────────────────────────────────────────────────
        dict(
            event_type="due_reminder",
            label="Test Due Soon Reminder (15 days)",
            group_name="Scheduling",
            description="Fired 15 days before a scheduled test is due (SRS §8.2 #1).",
            context_vars=["equipment.ueic", "request.title", "request.due_date",
                          "equipment.department", "days_remaining"],
            default_roles=["AEE Maintenance", "EE TLSS"],
        ),
        dict(
            event_type="due_reminder_final",
            label="Test Due Final Reminder (7 days)",
            group_name="Scheduling",
            description="Final reminder fired 7 days before a scheduled test is due (SRS §8.2 #2).",
            context_vars=["equipment.ueic", "request.title", "request.due_date",
                          "equipment.department", "days_remaining"],
            default_roles=["AEE Maintenance", "EE TLSS", "Department Head"],
        ),
        dict(
            event_type="overdue_alert",
            label="Test Overdue",
            group_name="Scheduling",
            description="Fired when a scheduled test passes its due date without completion (SRS §8.2 #3).",
            context_vars=["equipment.ueic", "request.title", "request.due_date",
                          "equipment.department", "days_overdue"],
            default_roles=["EE TLSS", "AEE Maintenance", "SEE W&M"],
        ),
        dict(
            event_type="overdue_escalation",
            label="Test Overdue Escalation (>7 days)",
            group_name="Scheduling",
            description="Escalation fired when a test is more than 7 days overdue (SRS §8.2 #4).",
            context_vars=["equipment.ueic", "request.title", "request.due_date",
                          "days_overdue", "equipment.department"],
            default_roles=["SEE W&M", "CEE Transmission Zone"],
        ),
        # ── Recommendations / Procurement ─────────────────────────────────────
        dict(
            event_type="procurement_pending",
            label="Procurement Request Raised",
            group_name="Recommendations",
            description="Fired when a procurement request is created — notifies Finance Approvers.",
            context_vars=["request.number", "pr_number", "title"],
            default_roles=["FinanceApprover", "Department Head"],
        ),
        dict(
            event_type="procurement_decision",
            label="Procurement Decision (Approved / Rejected)",
            group_name="Recommendations",
            description="Fired when Finance approves or rejects a procurement request.",
            context_vars=["request.number", "pr_number", "decision", "notes"],
            default_roles=["Originator", "TechApprover", "EE TLSS"],
        ),
        # ── Equipment ─────────────────────────────────────────────────────────
        dict(
            event_type="equipment_registered",
            label="Equipment Registered",
            group_name="Equipment",
            description="Fired when a new equipment unit is commissioned into the register.",
            context_vars=["equipment", "equipment_type", "department", "manufacturer", "commissioned_by"],
            default_roles=["AEE Maintenance", "EE TLSS"],
        ),
        dict(
            event_type="equipment_retired",
            label="Equipment Retired",
            group_name="Equipment",
            description="Fired when an equipment unit is decommissioned / retired.",
            context_vars=["equipment", "equipment_type", "department", "reason", "retired_by"],
            default_roles=["AEE Maintenance", "EE TLSS", "Department Head"],
        ),
        dict(
            event_type="design_problem_alert",
            label="Design Problem Alert",
            group_name="Equipment",
            description="Fired when a systemic design problem is identified for a make/model.",
            context_vars=["manufacturer", "equipment_type", "problem_description", "affected_count"],
            default_roles=["CEE Transmission Zone", "EE TLSS", "Department Head"],
        ),
        # ── Repair Lifecycle ──────────────────────────────────────────────────
        dict(
            event_type="repair_stage_changed",
            label="Repair Stage Advanced",
            group_name="Repair",
            description="Fired each time the repair workflow advances to the next stage.",
            context_vars=["equipment", "equipment_type", "stage", "progress"],
            default_roles=["AEE Maintenance", "TRC Member"],
        ),
        dict(
            event_type="repair_delay",
            label="Repair Stage Delayed",
            group_name="Repair",
            description="Fired when a repair stage is rejected / sent back — indicating a delay.",
            context_vars=["equipment", "equipment_type", "department", "repair_stage", "days_delayed"],
            default_roles=["AEE Maintenance", "CEE Transmission Zone"],
        ),
        dict(
            event_type="overhaul_recommended",
            label="Overhaul Recommended",
            group_name="Repair",
            description="Fired when the repair workflow reaches completion — overhaul is done.",
            context_vars=["equipment", "equipment_type", "department", "operation_count", "operation_threshold"],
            default_roles=["AEE Maintenance", "CEE Transmission Zone", "Department Head"],
        ),
        # ── Failure Registry ──────────────────────────────────────────────────
        dict(
            event_type="fr_rejected",
            label="Failure Registry Rejected",
            group_name="Failure Registry",
            description="Fired when a Failure Registry submission is rejected by an approver.",
            context_vars=["fr_number", "reason"],
            default_roles=["Originator"],
        ),
        # ── Reports ───────────────────────────────────────────────────────────
        dict(
            event_type="monthly_mis_report",
            label="Monthly MIS Report",
            group_name="Reports",
            description="Fired on the first working day of the month — distributes the monthly MIS report.",
            context_vars=["report_month", "tests_completed", "critical_count", "overdue_count",
                          "report_pdf_url", "report_xls_url"],
            default_roles=["SEE W&M", "CEE Transmission Zone", "Department Head"],
        ),
    ]

    inserted = 0
    for entry in _CATALOGUE:
        existing = (
            session.query(NotificationEventCatalogue)
            .filter(NotificationEventCatalogue.event_type == entry["event_type"])
            .first()
        )
        if existing:
            # Upsert: refresh mutable fields without changing PK
            existing.label         = entry["label"]
            existing.group_name    = entry["group_name"]
            existing.description   = entry.get("description", "")
            existing.context_vars  = entry.get("context_vars", [])
            existing.default_roles = entry.get("default_roles", [])
        else:
            session.add(NotificationEventCatalogue(**entry))
            inserted += 1
    session.commit()
    return inserted


def _seed_notification_schedule_rules(session) -> int:
    """
    Idempotent seed for NotificationScheduleRule rows.
    Matches on event_type + trigger_type + offset_days — won't duplicate on re-run.

    To add a new scheduler-based notification:
      1. Insert a row here (or directly in the DB).
      2. Ensure a NotificationTemplate exists for the event_type.
      Zero code change to main.py or notification_service.py is needed.
    """
    from models import NotificationScheduleRule

    _DEFAULT_RULES = [
        # SRS §8.2 #1 — 15-day early reminder
        dict(
            event_type="due_reminder",
            label="Test Due Reminder — 15 days before",
            trigger_type="due_soon",
            offset_days=15,
            severity="info",
            applicable_categories=[],
        ),
        # SRS §8.2 #2 — 7-day final reminder
        dict(
            event_type="due_reminder_final",
            label="Test Due Final Reminder — 7 days before",
            trigger_type="due_soon",
            offset_days=7,
            severity="alert",
            applicable_categories=[],
        ),
        # SRS §8.2 #3 — overdue alert (any day past due)
        dict(
            event_type="overdue_alert",
            label="Test Overdue",
            trigger_type="overdue",
            offset_days=0,
            severity="alert",
            applicable_categories=[],
        ),
        # SRS §8.2 #4 — escalation after 7 days overdue
        dict(
            event_type="overdue_escalation",
            label="Test Overdue Escalation (>7 days)",
            trigger_type="escalation",
            offset_days=7,
            severity="critical",
            applicable_categories=[],
        ),
        # Maintenance-specific 15-day due reminder (separate from test due_reminder)
        dict(
            event_type="due_reminder",
            label="Maintenance Due Reminder — 15 days before",
            trigger_type="due_soon",
            offset_days=15,
            severity="info",
            applicable_categories=["maintenance"],
        ),
        # Maintenance due event (separate event type for routing rule separation)
        dict(
            event_type="maintenance_due",
            label="Maintenance Due — 15 days before",
            trigger_type="due_soon",
            offset_days=15,
            severity="info",
            applicable_categories=["maintenance"],
        ),
        # Status-based: fire when request reaches "compliance_pending" status
        dict(
            event_type="remedial_action_due",
            label="Remedial Action — when status is compliance_pending",
            trigger_type="status_transition",
            offset_days=0,
            trigger_on_status="compliance_pending",
            severity="alert",
            applicable_categories=[],
        ),
        # TAQC observation overdue — status_transition trigger
        dict(
            event_type="taqc_observation_overdue",
            label="TA&QC Observation — when status is compliance_pending",
            trigger_type="status_transition",
            offset_days=0,
            trigger_on_status="compliance_pending",
            severity="alert",
            applicable_categories=[],
        ),
        # "Both" example: tester still in_progress but due date passed 5 days ago
        # → catches testers who started but never uploaded results
        dict(
            event_type="overdue_alert",
            label="Overdue — in_progress 5 days after due date",
            trigger_type="both",
            offset_days=5,
            trigger_on_status="in_progress",
            severity="alert",
            applicable_categories=[],
            advanced_conditions={
                "and": [
                    {"type": "overdue_by", "min_days": 5},
                    {"type": "status",     "on_status": "in_progress"},
                ]
            },
        ),
    ]

    inserted = 0
    for rule_def in _DEFAULT_RULES:
        # Match on the new natural key: event_type + trigger_type + offset_days + trigger_on_status
        existing = (
            session.query(NotificationScheduleRule)
            .filter(
                NotificationScheduleRule.organization_id.is_(None),
                NotificationScheduleRule.event_type    == rule_def["event_type"],
                NotificationScheduleRule.trigger_type  == rule_def["trigger_type"],
                NotificationScheduleRule.offset_days   == rule_def.get("offset_days", 0),
                (
                    NotificationScheduleRule.trigger_on_status == rule_def["trigger_on_status"]
                    if "trigger_on_status" in rule_def
                    else NotificationScheduleRule.trigger_on_status.is_(None)
                ),
            )
            .first()
        )
        if not existing:
            # Build kwargs — only pass fields that exist on the model
            kwargs = {
                "event_type":               rule_def["event_type"],
                "label":                    rule_def["label"],
                "trigger_type":             rule_def["trigger_type"],
                "offset_days":              rule_def.get("offset_days", 0),
                "trigger_on_status":        rule_def.get("trigger_on_status"),
                "applicable_categories":    rule_def.get("applicable_categories", []),
                "applicable_workflow_types": rule_def.get("applicable_workflow_types", []),
                "advanced_conditions":      rule_def.get("advanced_conditions"),
                "severity":                 rule_def.get("severity", "info"),
                "is_active":                rule_def.get("is_active", True),
            }
            session.add(NotificationScheduleRule(**kwargs))
            inserted += 1
    session.commit()
    return inserted


def _seed_notification_routing_rules(session) -> int:
    """
    Idempotent seed for NotificationRoutingRule global defaults (organization_id=NULL).

    Design
    ──────
    Each row defines: for a given event_type, which channels are enabled when
    the call originates from a specific workflow_type / test_type combination.

    Scope filter semantics (all JSONB arrays):
      • empty []  = "match everything" (wildcard)
      • non-empty = "only match if the call's value is in this list"

    Adding a new workflow or changing channel rules = INSERT / UPDATE rows here
    (or directly in the DB via Flutter Admin UI). Zero code change.

    Matching priority (higher wins):
      0  = global defaults (seeded here)
      10 = org-specific overrides (set by org admin via API)
    """
    from models import NotificationRoutingRule

    # Workflow type values match Workflow.workflow_type in DB exactly
    _ALL_TEST_TYPES = ["test", "inspection", "maintenance", "repair_lifecycle"]

    # ── Global default rules ──────────────────────────────────────────────────
    # Format: (event_type, workflow_types[], test_types[], channels[], label)
    # workflow_types=[] means "all workflows"; test_types=[] means "all categories"
    # Workflow type values: "testing_request" | "taqc_inspection" |
    #                       "failure_registry" | "repair_lifecycle"
    # Test type values = CategoryDetails.category_type:
    #   "test" | "maintenance" | "inspection" | "repair_lifecycle"
    # ─────────────────────────────────────────────────────────────────────────
    _RULES = [

        # ── Equipment Register ────────────────────────────────────────────────
        ("equipment_replacement",
         [], [],
         ["email", "sms", "inapp"],
         "Equipment Replacement — Email + SMS + in-app"),

        ("equipment_registered",
         [], [],
         ["email", "sms", "inapp"],
         "Equipment Registered — Email + SMS + in-app"),

        ("equipment_retired",
         [], [],
         ["email", "sms", "inapp"],
         "Equipment Retired — Email + SMS + in-app"),

        # ── Evaluation results ────────────────────────────────────────────────
        ("eval_critical",
         ["testing_request", "taqc_inspection"], [],
         ["email", "sms", "inapp"],
         "Critical Evaluation — all channels"),

        ("eval_alert",
         ["testing_request", "taqc_inspection"], [],
         ["email", "sms", "inapp"],
         "Alert Evaluation — Email + SMS + Dashboard"),

        # ── Test lifecycle — testing_request workflow (test/maintenance/inspection) ──
        ("request_submitted",
         ["testing_request"], [],
         ["email", "inapp"],
         "Test Request Submitted"),

        ("request_submitted",
         ["testing_request"], ["maintenance"],
         ["email", "sms", "inapp"],
         "Maintenance Request Submitted — Email + SMS"),

        ("request_submitted",
         ["failure_registry"], [],
         ["email", "inapp"],
         "Failure Registry Submitted"),

        ("request_submitted",
         ["taqc_inspection"], [],
         ["inapp"],
         "TAQC Inspection Submitted — in-app only"),

        # ── Tester workflow ───────────────────────────────────────────────────
        ("tester_assigned",
         ["testing_request"], [],
         ["email", "sms", "inapp"],
         "Tester Assigned — all channels"),

        ("tester_assigned",
         ["taqc_inspection"], [],
         ["email", "inapp"],
         "TAQC Inspector Assigned"),

        ("tester_declined",
         [], [],
         ["email", "inapp"],
         "Tester Declined — all workflows"),

        ("test_submitted",
         ["testing_request", "taqc_inspection"], [],
         ["email", "inapp"],
         "Test Results Submitted"),

        # ── Recommendations ───────────────────────────────────────────────────
        ("recommendation_approved",
         [], [],
         ["email", "inapp"],
         "Recommendation Approved — all workflows"),

        ("recommendation_rejected",
         [], [],
         ["email", "inapp"],
         "Recommendation Rejected — all workflows"),

        # ── Failure Registry ──────────────────────────────────────────────────
        ("fr_rejected",
         ["failure_registry"], [],
         ["email", "inapp"],
         "Failure Registry Rejected"),

        # ── Scheduling / Reminders ────────────────────────────────────────────
        ("due_reminder",
         ["testing_request"], _ALL_TEST_TYPES,
         ["email", "sms", "inapp"],
         "15-Day Test Due Reminder — Email + SMS"),

        ("due_reminder_final",
         ["testing_request"], _ALL_TEST_TYPES,
         ["email", "sms", "inapp"],
         "7-Day Final Reminder — Email + SMS"),

        ("overdue_alert",
         [], _ALL_TEST_TYPES,
         ["email", "sms", "inapp"],
         "Test Overdue — Email + SMS + Dashboard"),

        ("overdue_escalation",
         [], [],
         ["email", "sms", "inapp"],
         "Overdue Escalation — Email + SMS"),

        # Maintenance-specific: higher urgency
        ("maintenance_due",
         ["testing_request"], ["maintenance"],
         ["email", "sms", "inapp"],
         "Maintenance Due (15 days) — Email + SMS"),

        # Inspection reminders: lower urgency
        ("due_reminder",
         ["testing_request"], ["inspection"],
         ["email", "inapp"],
         "Due Reminder — Inspection: email + in-app"),

        # ── Compliance / Remedial ─────────────────────────────────────────────
        ("remedial_action_due",
         [], [],
         ["email", "sms"],
         "Remedial Action Compliance Due — Email + SMS"),

        ("taqc_observation_overdue",
         ["taqc_inspection"], [],
         ["email", "sms"],
         "TA&QC Observation Compliance Overdue — Email + SMS"),

        # ── Repair Lifecycle ──────────────────────────────────────────────────
        ("repair_stage_changed",
         ["repair_lifecycle"], [],
         ["inapp"],
         "Repair Stage Advanced — in-app only"),

        ("overhaul_recommended",
         ["repair_lifecycle"], [],
         ["email", "sms"],
         "Overhaul Recommended — Email + SMS"),

        ("repair_delay",
         ["repair_lifecycle"], [],
         ["email", "sms"],
         "Repair Stage Delay — Email + SMS"),

        # ── Design / Systemic ─────────────────────────────────────────────────
        ("design_problem_alert",
         [], [],
         ["email", "sms"],
         "Design Problem Alert — Email + SMS"),

        # ── Reports ───────────────────────────────────────────────────────────
        ("monthly_mis_report",
         [], [],
         ["email"],
         "Monthly MIS Report — Email only"),

        # ── Procurement ───────────────────────────────────────────────────────
        ("procurement_pending",
         [], [],
         ["email", "inapp"],
         "Procurement Raised — email + in-app"),

        ("procurement_decision",
         [], [],
         ["email", "inapp"],
         "Procurement Decision — email + in-app"),
    ]

    inserted = 0
    for (event_type, wf_types, test_types, channels, label) in _RULES:
        # Match on event_type + workflow_types + test_types to avoid duplicates
        import json as _json
        existing = (
            session.query(NotificationRoutingRule)
            .filter(
                NotificationRoutingRule.event_type == event_type,
                NotificationRoutingRule.organization_id.is_(None),
                NotificationRoutingRule.applicable_workflow_types.cast(
                    __import__("sqlalchemy.dialects.postgresql", fromlist=["JSONB"]).JSONB
                ) == _json.dumps(wf_types),
                NotificationRoutingRule.applicable_test_types.cast(
                    __import__("sqlalchemy.dialects.postgresql", fromlist=["JSONB"]).JSONB
                ) == _json.dumps(test_types),
            )
            .first()
        )
        if not existing:
            session.add(NotificationRoutingRule(
                event_type=event_type,
                label=label,
                applicable_workflow_types=wf_types,
                applicable_equipment_types=[],
                applicable_test_types=test_types,
                applicable_status_from=None,
                applicable_status_to=None,
                channels_enabled=channels,
                recipient_roles_override=None,
                priority=0,
                is_active=True,
            ))
            inserted += 1
    session.commit()
    return inserted


def run_seed():
    # ── Drop ALL tables then recreate from scratch ────────────────────────────
    print("[INIT] Dropping all tables (Base.metadata.drop_all) …")
    import models  # noqa: F401  — ensures all model classes register with Base
    #Base.metadata.drop_all(bind=vendor_engine)
    print("[OK]   All tables dropped.")
    print("[INIT] Creating database schema via Base.metadata.create_all …")
    Base.metadata.create_all(bind=vendor_engine)
    print("[OK]   Schema ready.")

    with get_db_session() as session:
        print("\n" + "=" * 80)
        print("  DATABASE SEEDING STARTED")
        print("=" * 80 + "\n")

        # Core System
        migrate_testing_request_columns(session)
        migrate_equipment_register(session)
        role_ids = seed_roles(session)
        new_user_ids = seed_users(session)  # 👈 capture new users
        module_ids = seed_modules(session)
        seed_privileges(session, role_ids, module_ids)
        # org_role_permissions seeded AFTER orgs are created (see end of org section)
        migrate_report_tables(session)
        seed_report_definitions(session)
        seed_user_roles(session, role_ids)
        assign_viewer_role_to_new_users(session, new_user_ids, role_ids)
        seed_plans(session)

        # Geography
        seed_country_india
        india = seed_india_country(session)
        state_ids=seed_indian_states(session, india)
        seed_cities(session,state_ids)

        # Company Structure
        seed_divisions(session)
        master_ids=seed_category_master(session)
        seed_category_details(session, master_ids)
        seed_test_type_categories(session, master_ids)
        # seed_tester_locations(session)  # DEPRECATED - using org departments instead
        seed_sample_testing_request(session)
        # Provision global test templates from static dict
        from services.org_test_template_service import OrgTestTemplateService
        svc = OrgTestTemplateService(session)
        n = svc.provision_global_defaults()
        print(f"[OK] Provisioned {n} global test templates.")
        inserted = svc.provision_overall_assessment()
        print(f"[OK] Overall assessment template: {'inserted' if inserted else 'updated'}.")
        n2 = seed_direct_submission_templates(session)
        print(f"[OK] Direct-submission templates: {n2} seeded.")
        n3 = seed_annual_audit_templates(session)
        print(f"[OK] Annual Audit templates: {n3} seeded.")
        from seed_annual_audit import seed_annual_audit_stages
        seed_annual_audit_stages(session)
        n4 = seed_cumulative_template(session)
        print(f"[OK] Cumulative / Operations Tracking template: {n4} seeded.")
        n5 = seed_calibration_template(session)
        print(f"[OK] Calibration template: {n5} seeded.")

        # Organization Multi-Tenancy System
        print("\n--- Organization System Seeding ---")
        seed_role_templates(session)
        seed_super_admin(session)
        seed_tester_role_module_requirements(session)
        seed_sample_organization(session)

        # Seed KPTCL Organization with Departments
        kptcl_org = seed_kptcl_organization(session)
        if kptcl_org:
            print("\n--- KPTCL Department Hierarchy Seeding ---")
            try:
                seed_kptcl_departments(session, str(kptcl_org.id))
            except FileNotFoundError:
                print("[WARN] KPTCL Excel file not found. Skipping department seeding.")
                print("[INFO] You can seed KPTCL departments later with:")
                print(f"       python seed.py --kptcl {kptcl_org.id}")
            except Exception as e:
                print(f"[WARN] KPTCL department seeding failed: {e}")
                print("[INFO] You can retry with:")
                print(f"       python seed.py --kptcl {kptcl_org.id}")

        # Annual Audit role mappings for KPTCL (stages must already exist from seed_annual_audit_stages above)
        if kptcl_org:
            try:
                session.rollback()  # clear any aborted transaction from earlier steps
                from seed_annual_audit import seed_annual_audit_role_mappings
                seed_annual_audit_role_mappings(session, kptcl_org.id)
            except Exception as e:
                session.rollback()
                print(f"[WARN] Annual Audit role mapping failed: {e}")

        # Sample Equipment (after departments + equipment types exist)
        seed_sample_equipment(session, kptcl_org)

        # Test Register (SRS §5.1.1) — after KPTCL org + roles + equipment types exist
        print("\n--- Test Register Seeding (SRS §5.1.1) ---")
        seed_test_register(session, kptcl_org)

        # Zoho Import Mapping (after KPTCL org + departments exist)
        seed_zoho_import_mapping(session, kptcl_org)
        seed_notifications_module_and_permissions(session)
        # Org role permissions — AFTER all orgs + org_roles are created
        # DISABLED: This grants VIEW to ALL modules for ALL roles, breaking RBAC
        # Proper permissions are already set via role templates during org role provisioning
        # seed_org_role_permissions_for_modules(session, module_ids)

        # Notification defaults — templates + variable registry (idempotent)
        print("\n--- Notification Defaults Seeding ---")
        try:
            from services.notification_service import seed_default_templates, seed_default_variables
            seeded_t = seed_default_templates(session)
            seeded_v = seed_default_variables(session)
            print(f"[OK] Notification templates : {seeded_t} inserted (0 = already seeded)")
            print(f"[OK] Notification variables : {seeded_v} inserted (0 = already seeded)")
        except Exception as _e:
            print(f"[WARN] Notification seed failed (non-fatal): {_e}")

        # Notification event catalogue (config-driven event types — idempotent)
        print("\n--- Notification Event Catalogue Seeding ---")
        try:
            seeded_c = _seed_notification_event_catalogue(session)
            print(f"[OK] Notification event catalogue : {seeded_c} inserted (0 = already seeded)")
        except Exception as _e:
            print(f"[WARN] Notification event catalogue seed failed (non-fatal): {_e}")

        # Notification schedule rules (config-driven scheduler — idempotent)
        print("\n--- Notification Schedule Rules Seeding ---")
        try:
            seeded_r = _seed_notification_schedule_rules(session)
            print(f"[OK] Notification schedule rules : {seeded_r} inserted (0 = already seeded)")
        except Exception as _e:
            print(f"[WARN] Notification schedule rules seed failed (non-fatal): {_e}")

        # Notification routing rules (workflow/equipment/test-type channel scoping — idempotent)
        print("\n--- Notification Routing Rules Seeding ---")
        try:
            seeded_rr = _seed_notification_routing_rules(session)
            print(f"[OK] Notification routing rules : {seeded_rr} inserted (0 = already seeded)")
        except Exception as _e:
            print(f"[WARN] Notification routing rules seed failed (non-fatal): {_e}")

        # Repair Workflow — stages, templates, roles, transitions
        print("\n--- Repair Workflow Seeding ---")
        try:
            seed_workflow(session)
        except Exception as _e:
            print(f"[WARN] Repair workflow seed failed (non-fatal): {_e}")

        # TR / FR / TAQC Workflow Engine — states, transitions, permission matrix
        print("\n--- TR / FR / TAQC Workflow Engine Seeding ---")
        try:
            seed_tr_workflows(session)
        except Exception as _e:
            import traceback
            print(f"[WARN] TR workflow seed failed (non-fatal): {_e}")
            traceback.print_exc()

        # Migrate new enum values into PostgreSQL
        print("\n--- DB Migration: new status enum values ---")
        try:
            migrate_new_status_values(session)
        except Exception as _e:
            print(f"[WARN] Status enum migration (non-fatal): {_e}")

        # Dept-filter test users — always seeded under the default KPTCL org
        print("\n--- Dept-filter test users (KPTCL org) ---")
        try:
            seed_dept_filter_users(session, org=kptcl_org)
        except Exception as _e:
            import traceback
            print(f"[WARN] Dept-filter seed failed (non-fatal): {_e}")
            traceback.print_exc()

        print("\n" + "=" * 80)
        print("  [OK] ALL SEED DATA INSERTED SUCCESSFULLY")
        print("=" * 80)
        print("\nQuick Start:")
        print("  1. Super Admin: superadmin@system.com / Admin123!")
        print("  2. Sample Org Admin: orgadmin@sampleorg.com / OrgAdmin123!")
        if kptcl_org:
            print("  3. KPTCL Org Admin: orgadmin@kptcl.com / admin123")
        print("  4. Dept-filter users: tester.north / tester.south / tester.mysuru @ kptcl.com / TestDept@123")
        print(f"  {5 if kptcl_org else 4}. View API docs: http://localhost:8000/docs")
        print("\n" + "=" * 80 + "\n")


def seed_sample_equipment(session, org):
    """
    Seed sample equipment for an organization so testing requests can link to registered assets.
    Creates equipment across several substations with different types and voltage classes.
    """
    if not org:
        print("[SKIP] No org — skipping equipment seeding")
        return

    from services.equipment_service import EquipmentService

    # Get an admin user for created_by
    admin_user = session.query(User).filter(
        User.organization_id == org.id,
        User.email.ilike("%orgadmin%")
    ).first()
    if not admin_user:
        admin_user = session.query(User).filter(
            User.organization_id == org.id
        ).first()
    created_by = admin_user.id if admin_user else None

    # Get leaf departments (substations — those with no children)
    from sqlalchemy import exists, select
    from sqlalchemy.orm import aliased
    ChildDept = aliased(OrgDepartment)
    substations = (
        session.query(OrgDepartment)
        .filter(
            OrgDepartment.organization_id == org.id,
            ~exists(
                select(ChildDept.id)
                .where(ChildDept.parent_department_id == OrgDepartment.id)
            ),
        )
        .order_by(OrgDepartment.name)
        .limit(10)
        .all()
    )
    if not substations:
        # Fallback: any departments
        substations = (
            session.query(OrgDepartment)
            .filter(OrgDepartment.organization_id == org.id)
            .limit(5)
            .all()
        )

    if not substations:
        print("[WARN] No departments found — skipping equipment seeding")
        return

    # Get equipment types
    equip_types = (
        session.query(CategoryMaster)
        .filter(CategoryMaster.description == "Testing Equipment", CategoryMaster.is_active == True)
        .all()
    )
    if not equip_types:
        print("[WARN] No equipment types found — skipping equipment seeding")
        return

    # Map equipment type names to their IDs
    type_map = {et.name: et.id for et in equip_types}

    # Define sample equipment configurations
    equipment_configs = [
        # (equipment_type_name, voltage_class, bay_number, manufacturer, model, serial, year)
        ("Power Transformer", "220", "01", "BHEL", "PT-220-A", "PT2024001", 2020),
        ("Power Transformer", "110", "02", "ABB", "PT-110-B", "PT2024002", 2019),
        ("Current Transformer", "220", "01", "Siemens", "CT-220-X", "CT2024001", 2021),
        ("Current Transformer", "110", "01", "CGL", "CT-110-Y", "CT2024002", 2022),
        ("CVT", "220", "01", "BHEL", "CVT-220-A", "CVT2024001", 2020),
        ("Power Transformer", "66", "01", "Crompton Greaves", "PT-66-C", "PT2024003", 2018),
        ("Relay", "220", "01", "L&T", "REL-220-A", "REL2024001", 2023),
        ("Meter", "110", "01", "Secure Meters", "MTR-110-A", "MTR2024001", 2021),
    ]

    created = 0
    for i, substation in enumerate(substations):
        # Each substation gets 2-3 pieces of equipment
        configs_for_station = equipment_configs[i % len(equipment_configs): i % len(equipment_configs) + 3]
        if not configs_for_station:
            configs_for_station = equipment_configs[:2]

        for type_name, voltage, bay, mfr, model, serial, year in configs_for_station:
            if type_name not in type_map:
                continue

            try:
                equipment = EquipmentService.create_equipment(
                    db=session,
                    organization_id=org.id,
                    department_id=substation.id,
                    equipment_type_id=type_map[type_name],
                    voltage_class=voltage,
                    bay_number=bay,
                    manufacturer=mfr,
                    model_number=model,
                    factory_serial_number=serial,
                    year_of_manufacture=year,
                    created_by=created_by,
                )
                created += 1
            except Exception as e:
                # Skip duplicates or other errors
                session.rollback()
                continue

    print(f"[OK] Seeded {created} sample equipment items for {org.name}")


def seed_zoho_import_mapping(session, kptcl_org):
    """
    Create default Zoho import mapping for KPTCL.
    Maps Zoho-imported users → KPTCL org, Originator role, RT North SD3 Devanahalli dept.
    """
    if not kptcl_org:
        print("[SKIP] No KPTCL org — skipping Zoho import mapping")
        return

    # Find the Originator org role for KPTCL
    originator_role = session.query(OrgRole).filter_by(
        organization_id=kptcl_org.id, name="Originator"
    ).first()

    if not originator_role:
        print("[WARN] Originator org role not found for KPTCL -- mapping created without role")

    # Find "RT North SD3 Devanahalli" department
    dept = session.query(OrgDepartment).filter(
        OrgDepartment.organization_id == kptcl_org.id,
        OrgDepartment.name.ilike("%RT North SD3 Devanahalli%")
    ).first()

    if not dept:
        print("[WARN] 'RT North SD3 Devanahalli' department not found -- mapping created without dept")

    # Check if mapping already exists -- update it with current dept/role IDs
    existing = session.query(ZohoImportMapping).filter_by(
        organization_id=kptcl_org.id, is_default=True
    ).first()
    if existing:
        existing.department_id = dept.id if dept else None
        existing.org_role_id = originator_role.id if originator_role else None
        session.commit()
        print(f"[OK] Zoho import mapping updated: KPTCL -> Originator, dept={dept.name if dept else 'None'}")
        return

    mapping = ZohoImportMapping(
        id=uuid.uuid4(),
        zoho_org_id=None,
        label="KPTCL Default — Zoho Customers",
        organization_id=kptcl_org.id,
        department_id=dept.id if dept else None,
        org_role_id=originator_role.id if originator_role else None,
        is_default=True,
        is_active=True,
    )
    session.add(mapping)
    session.commit()
    print(f"[OK] Zoho import mapping created: KPTCL -> Originator, dept={dept.name if dept else 'None'}")
def seed_workflow(db):

    import uuid
    from datetime import datetime

    stages = load_json("REPAIR_WORKFLOW_STAGES.json")
    templates = load_json("REPAIR_STAGE_TEMPLATES.json")
    stage_template_map = load_json("STAGE_TEMPLATE_MAP.json")
    # repair_stage_roles.json is a LIST: [{stage_code, roles}, ...]
    stage_role_list = load_json("repair_stage_roles.json")
    # Repair_Role_Transitions.json is a LIST: [{from, to, action}, ...]  — match by stage name
    transitions = load_json("Repair_Role_Transitions.json")

    # Derived name → code mapping (from stage sequence / template map keys)
    NAME_TO_CODE = {
        "Failure Reporting":   "FAILURE_REPORT",
        "Committee Review":    "COMMITTEE_REVIEW",
        "Vendor Assignment":   "VENDOR_ASSIGNMENT",
        "Lifting":             "LIFTING",
        "Joint Inspection":    "JOINT_INSPECTION",
        "Estimate & Work Award": "ESTIMATE",
        "Repair QA":           "QA",
        "Final Inspection":    "FINAL_INSPECTION",
        "Dispatch":            "DISPATCH",
        "Commissioning":       "COMMISSIONING",
    }

    # -------------------------------
    # 1. TEMPLATES
    # -------------------------------
    template_map = {}

    for key, t in templates.items():

        existing = db.query(OrgTestTemplate).filter_by(template_key=key).first()
        if existing:
            template_map[key] = existing.id
            continue

        obj = OrgTestTemplate(
            id=uuid.uuid4(),
            template_key=key,
            template_type=t["template_type"],
            template_data=t,
            created_at=datetime.utcnow()
        )

        db.add(obj)
        db.flush()

        template_map[key] = obj.id

    # -------------------------------
    # 2. STAGES
    # Keyed by name for template/transition lookup;
    # also keyed by code for role lookup.
    # -------------------------------
    stage_map_by_name = {}  # stage name -> stage.id
    stage_map_by_code = {}  # stage code -> stage.id

    for s in stages:
        stage_name = s["name"]
        stage_code = s.get("code") or NAME_TO_CODE.get(stage_name, stage_name.upper().replace(" ", "_"))

        existing = db.query(RepairStageDefinition).filter_by(name=stage_name).first()
        if existing:
            stage_map_by_name[stage_name] = existing.id
            stage_map_by_code[existing.code] = existing.id
            continue

        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            name=stage_name,
            code=stage_code,
            sequence=s["sequence"],
            weight=s.get("weight", 10),
            is_mandatory=s.get("is_mandatory", True),
            is_active=True,
        )

        db.add(stage)
        db.flush()

        stage_map_by_name[stage_name] = stage.id
        stage_map_by_code[stage_code] = stage.id

    # -------------------------------
    # 3. STAGE → TEMPLATE
    # -------------------------------
    for stage_name, template_key in stage_template_map.items():

        stage_id = stage_map_by_name.get(stage_name)
        template_id = template_map.get(template_key)

        if not stage_id or not template_id:
            continue

        exists = db.query(RepairStageTemplate).filter_by(stage_id=stage_id).first()

        if not exists:
            db.add(RepairStageTemplate(
                stage_id=stage_id,
                template_id=template_id
            ))
        else:
            exists.template_id = template_id

    # -------------------------------
    # 4. STAGE → ROLE
    # repair_stage_roles.json: [{stage_code, roles, assignment_role}, ...]
    # roles[]         → can_edit=True, can_approve=True, can_assign=False
    # assignment_role → can_edit=False, can_approve=False, can_assign=True
    # -------------------------------
    for entry in stage_role_list:
        stage_code = entry.get("stage_code")
        stage_id = stage_map_by_code.get(stage_code)

        if not stage_id:
            print(f"  [WARN] seed_workflow: stage_code '{stage_code}' not found — skipping roles")
            continue

        # Stage actor roles (can_edit + can_approve)
        for role_name in entry.get("roles", []):
            role = db.query(OrgRole).filter_by(name=role_name).first()
            if not role:
                print(f"  [WARN] seed_workflow: role '{role_name}' not found in org_roles")
                continue

            exists = db.query(RepairStageRole).filter_by(
                stage_id=stage_id,
                role_id=role.id
            ).first()

            if not exists:
                db.add(RepairStageRole(
                    id=uuid.uuid4(),
                    stage_id=stage_id,
                    role_id=role.id,
                    can_edit=True,
                    can_approve=True,
                    can_assign=False,
                ))

        # Assignment role (can_assign only — driven from JSON, not hardcoded)
        assign_role_name = entry.get("assignment_role")
        if assign_role_name:
            assign_role = db.query(OrgRole).filter_by(name=assign_role_name).first()
            if assign_role:
                exists = db.query(RepairStageRole).filter_by(
                    stage_id=stage_id,
                    role_id=assign_role.id
                ).first()
                if not exists:
                    db.add(RepairStageRole(
                        id=uuid.uuid4(),
                        stage_id=stage_id,
                        role_id=assign_role.id,
                        can_edit=False,
                        can_approve=False,
                        can_assign=True,
                    ))
                elif not exists.can_assign:
                    exists.can_assign = True

    # -------------------------------
    # 5. TRANSITIONS
    # Repair_Role_Transitions.json: [{from, to, action}, ...]
    # Match stages by name.
    # -------------------------------
    for t in transitions:
        from_id = stage_map_by_name.get(t["from"])
        to_id = stage_map_by_name.get(t["to"])

        if not from_id:
            print(f"  [WARN] seed_workflow: transition from-stage '{t['from']}' not found")
            continue

        exists = db.query(RepairStageTransition).filter_by(
            from_stage_id=from_id,
            action=t["action"]
        ).first()

        if not exists:
            db.add(RepairStageTransition(
                id=uuid.uuid4(),
                from_stage_id=from_id,
                to_stage_id=to_id,
                action=t["action"]
            ))
        else:
            exists.to_stage_id = to_id

    db.commit()
    # -------------------------------
    # DONE
    # -------------------------------
    print("✅ Workflow seeded")

def load_json(file_name):
    with open(file_name, "r") as f:
        return json.load(f)

def seed_workflow(session):
    """
    Seed repair workflow stages, templates, role assignments, and transitions.

    Source files (all at repo root):
      REPAIR_WORKFLOW_STAGES.json   — [{name, sequence}]
      REPAIR_STAGE_TEMPLATES.json   — {template_key: {name, template_type, sections, ...}}
      STAGE_TEMPLATE_MAP.json       — {stage_name: template_key}
      repair_stage_roles.json       — [{stage_code, roles:[role_name,...]}]
      Repair_Role_Transitions.json  — [{from, to, action}]  (stage names)
    """
    import json as _json
    import os as _os

    def _load(fname):
        path = _os.path.join(_os.path.dirname(__file__), fname)
        with open(path) as fh:
            return _json.load(fh)

    stages_raw      = _load("REPAIR_WORKFLOW_STAGES.json")
    templates_raw   = _load("REPAIR_STAGE_TEMPLATES.json")
    stage_tmpl_map  = _load("STAGE_TEMPLATE_MAP.json")        # {stage_name: template_key}
    roles_raw       = _load("repair_stage_roles.json")         # [{stage_code, roles:[...]}]
    transitions_raw = _load("Repair_Role_Transitions.json")    # [{from, to, action}]

    # Canonical stage_name → code mapping (must stay in sync with JSON files)
    NAME_TO_CODE = {
        "Failure Reporting":      "FAILURE_REPORT",
        "Committee Review":       "COMMITTEE_REVIEW",
        "Vendor Assignment":      "VENDOR_ASSIGNMENT",
        "Lifting":                "LIFTING",
        "Joint Inspection":       "JOINT_INSPECTION",
        "Estimate & Work Award":  "ESTIMATE",
        "Repair QA":              "QA",
        "Final Inspection":       "FINAL_INSPECTION",
        "Dispatch":               "DISPATCH",
        "Commissioning":          "COMMISSIONING",
    }
    CODE_TO_NAME = {v: k for k, v in NAME_TO_CODE.items()}

    # ── 1. Templates ──────────────────────────────────────────────────────────
    template_map = {}   # key → UUID
    for key, t in templates_raw.items():
        existing = session.query(OrgTestTemplate).filter_by(template_key=key).first()
        if existing:
            template_map[key] = existing.id
            continue
        obj = OrgTestTemplate(
            id=uuid.uuid4(),
            template_key=key,
            template_data=t,
            is_system=True,
        )
        session.add(obj)
        session.flush()
        template_map[key] = obj.id
    print(f"[OK] Repair templates: {len(template_map)} ready")

    # ── 2. Stages ─────────────────────────────────────────────────────────────
    stage_map = {}      # name → UUID
    code_map  = {}      # code → UUID
    for s in stages_raw:
        name = s["name"]
        code = NAME_TO_CODE.get(name, name.upper().replace(" ", "_"))
        existing = session.query(RepairStageDefinition).filter_by(code=code).first()
        if existing:
            stage_map[name] = existing.id
            code_map[code]  = existing.id
            continue
        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            name=name,
            code=code,
            sequence=s["sequence"],
            weight=s.get("weight", 10),
            is_active=True,
            is_mandatory=True,
        )
        session.add(stage)
        session.flush()
        stage_map[name] = stage.id
        code_map[code]  = stage.id
    print(f"[OK] Repair stages: {len(stage_map)} ready")

    # ── 3. Stage → Template mapping ───────────────────────────────────────────
    for stage_name, tmpl_key in stage_tmpl_map.items():
        stage_id   = stage_map.get(stage_name)
        template_id = template_map.get(tmpl_key)
        if not stage_id or not template_id:
            continue
        exists = session.query(RepairStageTemplate).filter_by(stage_id=stage_id).first()
        if not exists:
            session.add(RepairStageTemplate(stage_id=stage_id, template_id=template_id))

    # ── 4. Stage → Role mapping ───────────────────────────────────────────────
    # repair_stage_roles.json: [{stage_code, roles, assignment_role}, ...]
    # roles[]         → can_edit=True, can_approve=True, can_assign=False
    # assignment_role → can_edit=False, can_approve=False, can_assign=True  (from JSON — not hardcoded)
    # Query ALL org roles with the same name (one per org) so that RBAC works
    # for users in ANY organization.
    for entry in roles_raw:
        stage_code = entry.get("stage_code") or entry.get("code")
        stage_id   = code_map.get(stage_code)
        if not stage_id:
            print(f"[WARN] Stage code not found: {stage_code}")
            continue

        # Stage actor roles
        for role_name in entry.get("roles", []):
            matched_roles = session.query(OrgRole).filter(OrgRole.name == role_name).all()
            if not matched_roles:
                print(f"[WARN] Role not found in any org: {role_name}")
                continue
            for role in matched_roles:
                exists = session.query(RepairStageRole).filter_by(
                    stage_id=stage_id, role_id=role.id
                ).first()
                if not exists:
                    session.add(RepairStageRole(
                        id=uuid.uuid4(),
                        stage_id=stage_id,
                        role_id=role.id,
                        can_edit=True,
                        can_approve=True,
                        can_assign=False,
                    ))

        # Assignment role — read from JSON field, not hardcoded
        assign_role_name = entry.get("assignment_role")
        if assign_role_name:
            matched_assign_roles = session.query(OrgRole).filter(OrgRole.name == assign_role_name).all()
            for role in matched_assign_roles:
                exists = session.query(RepairStageRole).filter_by(
                    stage_id=stage_id, role_id=role.id
                ).first()
                if not exists:
                    session.add(RepairStageRole(
                        id=uuid.uuid4(),
                        stage_id=stage_id,
                        role_id=role.id,
                        can_edit=False,
                        can_approve=False,
                        can_assign=True,
                    ))
                elif not exists.can_assign:
                    exists.can_assign = True

    # ── 5. Transitions ────────────────────────────────────────────────────────
    for t in transitions_raw:
        from_id = stage_map.get(t["from"])
        to_id   = stage_map.get(t.get("to"))  # None = terminal
        if not from_id:
            continue
        exists = session.query(RepairStageTransition).filter_by(
            from_stage_id=from_id, action=t["action"]
        ).first()
        if not exists:
            session.add(RepairStageTransition(
                id=uuid.uuid4(),
                from_stage_id=from_id,
                to_stage_id=to_id,
                action=t["action"],
            ))

    session.commit()
    print("[OK] Repair workflow seeded successfully")


# ── Department-filter test seed ───────────────────────────────────────────────
# Seeds KPTCL org with 3 peer divisions, each having the full set of 10
# role-users.  Purpose: validate IntegratedWorkflowEngine department-scope
# filters (exact / department_tree / organization / any).
#
# Hierarchy:  BLR_ZONE  →  BLR_CIRCLE  →  RT_NORTH / RT_SOUTH / MYSURU
# Users:      {role}.north / .south / .mysuru @ kptcl.com   (pw: TestDept@123)
# ─────────────────────────────────────────────────────────────────────────────

_DFT_ROLES = [
    ("Org Admin",              False, True),
    ("Dept Head",              False, True),
    ("Originator",             False, False),
    ("Tester",                 False, False),
    ("Test Assigner",          False, False),
    ("Technical Approver",     False, False),
    ("Finance Approver",       False, False),
    ("EE TLSS",                False, False),
    ("TA&QC Officer",          False, False),
    ("Section Head",           False, True),
    ("AEE Maintenance",        False, False),
    ("SEE W&M",                False, False),
    ("EE RT",                  False, False),
    ("SEE RT",                 False, False),
    ("CEE Transmission Zone",  False, False),
    ("CEE RT&R&D",             False, False),
    ("Purchaser",              False, False),
    ("Field Tester",           False, False),
    ("Lab Tester",             False, False),
    ("Workflow Coordinator",   False, False),
]

_DFT_DEPTS = [
    ("north",  "RT North Division",  "north"),
    ("south",  "RT South Division",  "south"),
    ("mysuru", "Mysuru Division",     "mysuru"),
]

_DFT_ROLE_EMAIL = {
    "Org Admin":              "orgadmin",
    "Dept Head":              "depthead",
    "Originator":             "originator",
    "Tester":                 "tester",
    "Test Assigner":          "assigner",
    "Technical Approver":     "techapprover",
    "Finance Approver":       "financeapprover",
    "EE TLSS":                "eetlss",
    "TA&QC Officer":          "taqc",
    "Section Head":           "sectionhead",
    "AEE Maintenance":        "aeemaint",
    "SEE W&M":                "seewm",
    "EE RT":                  "eert",
    "SEE RT":                 "seert",
    "CEE Transmission Zone":  "ceezone",
    "CEE RT&R&D":             "ceertrd",
    "Purchaser":              "purchaser",
    "Field Tester":           "fieldtester",
    "Lab Tester":             "labtester",
    "Workflow Coordinator":   "wfcoordinator",
}

_DFT_ROLE_FNAME = {
    "Org Admin":              "Admin",
    "Dept Head":              "DeptHead",
    "Originator":             "Originator",
    "Tester":                 "Tester",
    "Test Assigner":          "Assigner",
    "Technical Approver":     "TechApprover",
    "Finance Approver":       "FinApprover",
    "EE TLSS":                "EETLSS",
    "TA&QC Officer":          "TAQC",
    "Section Head":           "SectionHead",
    "AEE Maintenance":        "AEE",
    "SEE W&M":                "SEE",
    "EE RT":                  "EERT",
    "SEE RT":                 "SEERT",
    "CEE Transmission Zone":  "CEEZone",
    "CEE RT&R&D":             "CEERTRD",
    "Purchaser":              "Purchaser",
    "Field Tester":           "FieldTester",
    "Lab Tester":             "LabTester",
    "Workflow Coordinator":   "WFCoord",
}

_DFT_PHONE = {
    ("north",  "Org Admin"):              "9900001001",
    ("north",  "Dept Head"):              "9900001002",
    ("north",  "Originator"):             "9900001003",
    ("north",  "Tester"):                 "9900001004",
    ("north",  "Test Assigner"):          "9900001005",
    ("north",  "Technical Approver"):     "9900001006",
    ("north",  "Finance Approver"):       "9900001007",
    ("north",  "EE TLSS"):                "9900001008",
    ("north",  "TA&QC Officer"):          "9900001009",
    ("north",  "Section Head"):           "9900001010",
    ("north",  "AEE Maintenance"):        "9900001011",
    ("north",  "SEE W&M"):                "9900001012",
    ("north",  "EE RT"):                  "9900001013",
    ("north",  "SEE RT"):                 "9900001014",
    ("north",  "CEE Transmission Zone"):  "9900001015",
    ("north",  "CEE RT&R&D"):             "9900001016",
    ("north",  "Purchaser"):              "9900001017",
    ("north",  "Field Tester"):           "9900001018",
    ("north",  "Lab Tester"):             "9900001019",
    ("north",  "Workflow Coordinator"):   "9900001020",
    ("south",  "Org Admin"):              "9900002001",
    ("south",  "Dept Head"):              "9900002002",
    ("south",  "Originator"):             "9900002003",
    ("south",  "Tester"):                 "9900002004",
    ("south",  "Test Assigner"):          "9900002005",
    ("south",  "Technical Approver"):     "9900002006",
    ("south",  "Finance Approver"):       "9900002007",
    ("south",  "EE TLSS"):                "9900002008",
    ("south",  "TA&QC Officer"):          "9900002009",
    ("south",  "Section Head"):           "9900002010",
    ("south",  "AEE Maintenance"):        "9900002011",
    ("south",  "SEE W&M"):                "9900002012",
    ("south",  "EE RT"):                  "9900002013",
    ("south",  "SEE RT"):                 "9900002014",
    ("south",  "CEE Transmission Zone"):  "9900002015",
    ("south",  "CEE RT&R&D"):             "9900002016",
    ("south",  "Purchaser"):              "9900002017",
    ("south",  "Field Tester"):           "9900002018",
    ("south",  "Lab Tester"):             "9900002019",
    ("south",  "Workflow Coordinator"):   "9900002020",
    ("mysuru", "Org Admin"):              "9900003001",
    ("mysuru", "Dept Head"):              "9900003002",
    ("mysuru", "Originator"):             "9900003003",
    ("mysuru", "Tester"):                 "9900003004",
    ("mysuru", "Test Assigner"):          "9900003005",
    ("mysuru", "Technical Approver"):     "9900003006",
    ("mysuru", "Finance Approver"):       "9900003007",
    ("mysuru", "EE TLSS"):                "9900003008",
    ("mysuru", "TA&QC Officer"):          "9900003009",
    ("mysuru", "Section Head"):           "9900003010",
    ("mysuru", "AEE Maintenance"):        "9900003011",
    ("mysuru", "SEE W&M"):                "9900003012",
    ("mysuru", "EE RT"):                  "9900003013",
    ("mysuru", "SEE RT"):                 "9900003014",
    ("mysuru", "CEE Transmission Zone"):  "9900003015",
    ("mysuru", "CEE RT&R&D"):             "9900003016",
    ("mysuru", "Purchaser"):              "9900003017",
    ("mysuru", "Field Tester"):           "9900003018",
    ("mysuru", "Lab Tester"):             "9900003019",
    ("mysuru", "Workflow Coordinator"):   "9900003020",
}


def _dft_get_or_create_org(session) -> Organization:
    org = session.query(Organization).filter_by(code="KPTCL").first()
    if org:
        print(f"  [SKIP] Org KPTCL already exists  ({org.id})")
        return org
    now = datetime.now()
    org = Organization(
        name="Karnataka Power Transmission Corporation Limited",
        code="KPTCL",
        display_name="KPTCL",
        organization_type="utility",
        industry="Power Transmission",
        primary_email="info@kptcl.com",
        primary_phone="+91-80-22207684",
        is_active=True,
        is_verified=True,
        settings={},
        cts=now, mts=now,
    )
    session.add(org)
    session.flush()
    print(f"  [NEW] Org KPTCL created  ({org.id})")
    return org


def _dft_get_or_create_dept(session, org_id, name, code,
                             parent_id=None) -> OrgDepartment:
    d = session.query(OrgDepartment).filter_by(
        organization_id=org_id, code=code
    ).first()
    if d:
        if parent_id and d.parent_department_id != parent_id:
            d.parent_department_id = parent_id
            session.flush()
        return d
    now = datetime.now()
    d = OrgDepartment(
        organization_id=org_id,
        name=name,
        code=code,
        parent_department_id=parent_id,
        is_active=True,
        cts=now, mts=now,
    )
    session.add(d)
    session.flush()
    return d


# Maps dept-filter role names to their default dashboard module path.
# Must match the Module.path values seeded in seed_modules().
_DFT_ROLE_MODULE_PATH = {
    "Org Admin":              "admin_dashboard",
    "Dept Head":              "see_dashboard",
    "Section Head":           "see_dashboard",
    "Technical Approver":     "see_dashboard",
    "Finance Approver":       "see_dashboard",
    "SEE W&M":                "see_dashboard",
    "SEE RT":                 "see_dashboard",
    "CEE Transmission Zone":  "cee_dashboard",
    "CEE RT&R&D":             "cee_dashboard",
    "EE TLSS":                "ee_tlss_dashboard",
    "EE RT":                  "ee_tlss_dashboard",
    "TA&QC Officer":          "ee_tlss_dashboard",
    "Originator":             "aee_dashboard",
    "Tester":                 "aee_dashboard",
    "Test Assigner":          "aee_dashboard",
    "AEE Maintenance":        "aee_dashboard",
    "Field Tester":           "aee_dashboard",
    "Lab Tester":             "aee_dashboard",
    "Purchaser":              "aee_dashboard",
    "Workflow Coordinator":   "ee_tlss_dashboard",
}


def _dft_get_or_create_role(session, org_id, name,
                             is_org_admin=False, is_dept_admin=False) -> OrgRole:
    r = session.query(OrgRole).filter_by(
        organization_id=org_id, name=name
    ).first()
    if r:
        # Sync flags so re-seeding always fixes stale DB state
        updated = False
        if r.is_org_admin != is_org_admin:
            r.is_org_admin = is_org_admin
            updated = True
        if r.is_dept_admin != is_dept_admin:
            r.is_dept_admin = is_dept_admin
            updated = True
        if not r.default_module_id:
            module_path = _DFT_ROLE_MODULE_PATH.get(name)
            if module_path:
                mod = session.query(Module).filter_by(path=module_path).first()
                if mod:
                    r.default_module_id = mod.id
                    updated = True
        if updated:
            session.flush()
        return r
    now = datetime.now()

    # Resolve default_module_id from module path (mirrors what full seed does)
    module_path = _DFT_ROLE_MODULE_PATH.get(name)
    default_module_id = None
    if module_path:
        mod = session.query(Module).filter_by(path=module_path).first()
        if mod:
            default_module_id = mod.id

    r = OrgRole(
        organization_id=org_id,
        name=name,
        description=f"{name} — seeded for dept-filter testing",
        role_type="default",
        is_org_admin=is_org_admin,
        is_dept_admin=is_dept_admin,
        is_active=True,
        default_module_id=default_module_id,
        cts=now, mts=now,
    )
    session.add(r)
    session.flush()
    return r


def _dft_get_or_create_user(session, org_id, email,
                             firstname, lastname, phone, dept_id) -> User:
    u = session.query(User).filter_by(email=email).first()
    if u:
        u.organization_id = org_id
        u.department_id   = dept_id
        # Always reset to TestDept@123 so hierarchy users (e.g. cee.zone created
        # earlier by seed_kptcl_organization with admin123) use a consistent pw.
        u.password_hash = get_password_hash("TestDept@123")
        session.flush()
        return u
    now = datetime.now()
    u = User(
        email=email,
        password_hash=get_password_hash("TestDept@123"),
        firstname=firstname,
        lastname=lastname,
        phone_number=phone,
        organization_id=org_id,
        department_id=dept_id,
        isactive=True,
        email_confirmed=True,
        phone_confirmed=True,
        cts=now, mts=now,
    )
    session.add(u)
    session.flush()
    return u


def _dft_assign_role(session, user_id, role_id, dept_id):
    exists = session.query(OrgUserRole).filter_by(
        user_id=user_id, org_role_id=role_id
    ).first()
    if exists:
        if exists.department_id != dept_id:
            exists.department_id = dept_id
            session.flush()
        return
    now = datetime.now()
    session.add(OrgUserRole(
        user_id=user_id,
        org_role_id=role_id,
        department_id=dept_id,
        is_active=True,
        assigned_at=now,
    ))
    session.flush()


def _seed_dft_equipment(session, org, dept_map: dict):
    """
    Seed sample equipment into each of the 3 dept-filter divisions
    (RT_NORTH, RT_SOUTH, MYSURU) so originators / testers scoped to those
    divisions can see equipment in the TR form without needing the org-wide
    fallback.

    dept_map = {"north": <OrgDepartment>, "south": ..., "mysuru": ...}
    """
    from services.equipment_service import EquipmentService
    from models import CategoryMaster

    if not org:
        return

    # Get admin user for created_by
    admin = session.query(User).filter(
        User.organization_id == org.id,
        User.email.ilike("%orgadmin%"),
    ).first() or session.query(User).filter(
        User.organization_id == org.id
    ).first()
    created_by = admin.id if admin else None

    equip_types = (
        session.query(CategoryMaster)
        .filter(CategoryMaster.description == "Testing Equipment", CategoryMaster.is_active == True)
        .all()
    )
    type_map = {et.name: et.id for et in equip_types}

    # Per-division sample configs  (type, voltage, bay, manufacturer, model, serial, year)
    division_configs = {
        "north": [
            ("Power Transformer",   "220", "01", "BHEL",             "PT-220-N",  "NTH2024001", 2021),
            ("Current Transformer", "220", "01", "Siemens",          "CT-220-N",  "NTH2024002", 2022),
            ("Power Transformer",   "110", "01", "ABB",              "PT-110-N",  "NTH2024003", 2020),
        ],
        "south": [
            ("Power Transformer",   "220", "01", "BHEL",             "PT-220-S",  "STH2024001", 2021),
            ("Current Transformer", "110", "01", "CGL",              "CT-110-S",  "STH2024002", 2022),
            ("CVT",                 "220", "01", "BHEL",             "CVT-220-S", "STH2024003", 2020),
        ],
        "mysuru": [
            ("Power Transformer",   "110", "01", "Crompton Greaves", "PT-110-M",  "MYS2024001", 2019),
            ("Current Transformer", "220", "01", "Siemens",          "CT-220-M",  "MYS2024002", 2021),
            ("Power Transformer",   "66",  "01", "ABB",              "PT-066-M",  "MYS2024003", 2018),
        ],
    }

    created = 0
    for slug, dept_obj in dept_map.items():
        configs = division_configs.get(slug, [])
        for type_name, voltage, bay, mfr, model, serial, year in configs:
            if type_name not in type_map:
                continue
            try:
                EquipmentService.create_equipment(
                    db=session,
                    organization_id=org.id,
                    department_id=dept_obj.id,
                    equipment_type_id=type_map[type_name],
                    voltage_class=voltage,
                    bay_number=bay,
                    manufacturer=mfr,
                    model_number=model,
                    factory_serial_number=serial,
                    year_of_manufacture=year,
                    created_by=created_by,
                )
                created += 1
            except Exception:
                session.rollback()
    print(f"  [OK] {created} equipment items seeded across {len(dept_map)} divisions")


def seed_dept_filter_users(session, org=None):
    """
    Seeds KPTCL org with 3 department divisions, each having the complete set
    of 10 role-users (30 users total).  Used to validate department-scope
    filters in IntegratedWorkflowEngine.

    Pass the already-created KPTCL Organization object as `org` so this
    function reuses it as the default org rather than doing a separate lookup.

    Hierarchy:  BLR_ZONE → BLR_CIRCLE → RT_NORTH / RT_SOUTH / MYSURU
    Email:      {role}.{dept}@kptcl.com   (e.g. tester.north@kptcl.com)
    Password:   TestDept@123
    """
    print("\n" + "=" * 72)
    print("  DEPT FILTER TEST SEED  —  3 depts × 20 roles = 60 users")
    print("=" * 72)

    # 1. Organisation — reuse the already-seeded KPTCL org (default org)
    print("\n[1] Organisation")
    org = org or _dft_get_or_create_org(session)
    oid = org.id

    # 2. Department hierarchy
    print("\n[2] Department hierarchy")
    zone = _dft_get_or_create_dept(
        session, oid,
        name="Bangalore Zone", code="BLR_ZONE",
    )
    print(f"  Zone   : {zone.name}")

    circle = _dft_get_or_create_dept(
        session, oid,
        name="Bangalore Transmission Circle", code="BLR_CIRCLE",
        parent_id=zone.id,
    )
    print(f"  Circle : {circle.name}")

    div_north  = _dft_get_or_create_dept(
        session, oid,
        name="RT North Division", code="RT_NORTH",
        parent_id=circle.id,
    )
    div_south  = _dft_get_or_create_dept(
        session, oid,
        name="RT South Division", code="RT_SOUTH",
        parent_id=circle.id,
    )
    div_mysuru = _dft_get_or_create_dept(
        session, oid,
        name="Mysuru Division", code="MYSURU",
        parent_id=circle.id,
    )
    dept_map = {"north": div_north, "south": div_south, "mysuru": div_mysuru}
    for slug, dept in dept_map.items():
        print(f"  Div [{slug:6s}]: {dept.name}  ({dept.id})")

    # 3. Roles  (org-scoped, shared across all 3 divisions)
    print("\n[3] Roles")
    role_map: dict = {}
    for name, is_admin, is_dept in _DFT_ROLES:
        r = _dft_get_or_create_role(session, oid, name, is_admin, is_dept)
        role_map[name] = r
        tag = " [org-admin]" if is_admin else (" [dept-admin]" if is_dept else "")
        print(f"  {name}{tag}")

    # 4. Users  (3 depts × 10 roles = 30 users)
    print("\n[4] Users  (password: TestDept@123 for all)")
    print(f"  {'Email':48s}  {'Role':22s}  Dept")
    print("  " + "-" * 85)

    for dept_slug, dept_label, email_sfx in _DFT_DEPTS:
        dept_obj = dept_map[dept_slug]
        for role_name, is_admin, is_dept in _DFT_ROLES:
            email     = f"{_DFT_ROLE_EMAIL[role_name]}.{email_sfx}@kptcl.com"
            firstname = _DFT_ROLE_FNAME[role_name]
            lastname  = dept_label.split()[0]          # "RT" or "Mysuru"
            phone     = _DFT_PHONE[(dept_slug, role_name)]

            u = _dft_get_or_create_user(
                session, oid, email, firstname, lastname, phone, dept_obj.id,
            )
            _dft_assign_role(session, u.id, role_map[role_name].id, dept_obj.id)
            print(f"  {email:48s}  {role_name:22s}  {dept_label}")

    # 5. Top-level users: circle & zone levels
    print("\n[5] Top-level hierarchy users  (circle + zone)")
    _top_level_users = [
        # (email,                   fname,  lname,    role_name,             dept_obj)
        ("ee.circle@kptcl.com",   "EE",   "Circle", "EE TLSS",             circle),
        ("see.circle@kptcl.com",  "SEE",  "Circle", "Technical Approver",  circle),
        ("cee.zone@kptcl.com",    "CEE",  "Zone",   "Org Admin",           zone),
        ("see.zone@kptcl.com",    "SEE",  "Zone",   "Technical Approver",  zone),
    ]
    for email, fname, lname, role_name, dept_obj in _top_level_users:
        phone = "9000000099"
        u = _dft_get_or_create_user(
            session, oid, email, fname, lname, phone, dept_obj.id,
        )
        r = role_map.get(role_name)
        if r:
            _dft_assign_role(session, u.id, r.id, dept_obj.id)
        print(f"  {email:48s}  {role_name:22s}  {dept_obj.name}")

    # ── 6. Sample equipment in each division ────────────────────────────────
    # Without this, originator/tester users see no equipment in the TR form
    # because seed_sample_equipment() only seeds into the Excel-based KPTCL
    # substations, which are in a different branch of the dept tree.
    print("\n[6] Sample equipment per division")
    _seed_dft_equipment(session, org, dept_map)

    session.commit()

    print("\n" + "=" * 72)
    print("  SEED COMPLETE -- 64 users created / updated  (60 leaf + 4 top-level)")
    print("=" * 72)
    print("""
Department-filter validation matrix:
  scope=exact (leaf-level users)
    tester.north  -> sees ONLY RT_NORTH TRs
    tester.south  -> sees ONLY RT_SOUTH TRs
    tester.mysuru -> sees ONLY MYSURU TRs

  scope=department_tree (circle-level users)
    ee.circle     -> sees RT_NORTH + RT_SOUTH + MYSURU TRs  (all 3 divisions)
    see.circle    -> sees RT_NORTH + RT_SOUTH + MYSURU TRs

  scope=zone (zone-level users)
    cee.zone      -> sees BLR_CIRCLE + all divisions beneath it
    see.zone      -> sees BLR_CIRCLE + all divisions beneath it

  scope=organization (org-admin)
    orgadmin.north / .south / .mysuru -> all see ALL KPTCL TRs

  Cross-dept isolation:
    tester.north should NOT see tester.south's requests
    tester.south should NOT see tester.mysuru's requests
""")


def seed_kptcl_only(org_id: str):
    """
    Run only KPTCL department seeding for a specific organization.
    Usage: python seed.py --kptcl <org_id>
    """
    with get_db_session() as session:
        print("\n" + "=" * 80)
        print("  KPTCL DEPARTMENT SEEDING")
        print("=" * 80 + "\n")
        seed_kptcl_departments(session, org_id)
        print("\n" + "=" * 80)
        print("  [OK] KPTCL DEPARTMENTS SEEDED SUCCESSFULLY")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    import sys

    try:
        # --kptcl <org_id>  → seed KPTCL departments only (no full seed)
        if len(sys.argv) > 2 and sys.argv[1] == "--kptcl":
            org_id = sys.argv[2]
            seed_kptcl_only(org_id)

        else:
            # Full seed — dept-filter users are always included inside run_seed()
            run_seed()

            # --with-kptcl <org_id>  → also seed KPTCL departments after full seed
            if len(sys.argv) > 2 and sys.argv[1] == "--with-kptcl":
                org_id = sys.argv[2]
                print("\n[INFO] Seeding KPTCL departments...")
                with get_db_session() as session:
                    seed_kptcl_departments(session, org_id)

    except Exception as e:
        import traceback
        traceback.print_exc()
