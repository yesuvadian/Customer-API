from contextlib import contextmanager
from datetime import datetime, timedelta
import uuid
import pandas as pd
from typing import Dict, Optional
from sqlalchemy import text
from database import VendorSessionLocal, Base, vendor_engine
from models import (
    CategoryDetails, CategoryMaster, Country, Division, Plan, Product,
    ProductCategory, ProductSubCategory, Role, RoleModulePrivilege,
    State, City, User, UserRole, Module,
    # Organization models
    Organization, OrgDepartment, OrgRole, OrgUserRole,
    OrgRolePermission, RoleTemplate, OrgInvitation, TesterRoleModuleRequirement,
    ZohoImportMapping, Equipment, EquipmentStatus,
    # Reporting Suite
    ReportDefinition,
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
    COMMON_PASSWORD = "utility@123"
    newly_created_user_ids = []
    users_data = [
        {"first_name": "Admin", "last_name": "User", "email": "admin@relu.com",
         "phone_number": "9999999999", "password": "Admin@123"},
        {"first_name": "Viewer", "last_name": "User", "email": "viewer@relu.com",
         "phone_number": "8888888888", "password": "Viewer@123"},
        {"first_name": "Operator", "last_name": "User", "email": "operator@relu.com",
         "phone_number": "7777777777", "password": "Operator@123"},
        {"first_name": "Auditor", "last_name": "User", "email": "auditor@relu.com",
         "phone_number": "6666666666", "password": "Auditor@123"},
        {"first_name": "Vendor", "last_name": "User", "email": "vendor@relu.com",
         "phone_number": "5555555555", "password": "vendor@123"},
        {"first_name": "ERP", "last_name": "Service", "email": "erp_bot@relu.com",
         "phone_number": "4444444444", "password": "ErpBot@123"},
        # {"first_name": "Originator", "last_name": "User", "email": "dakshanamurthy@hotmail.com",
        #  "phone_number": "3333333333", "password": "Originator@123"},
        {"first_name": "Tester", "last_name": "User", "email": "tester@relu.com",
         "phone_number": "2222222222", "password": "Tester@123"},
        {"first_name": "Approver", "last_name": "User", "email": "approver@relu.com",
         "phone_number": "1111111111", "password": "Approver@123"},
        # Testers per circle/division
        {"first_name": "Ramesh", "last_name": "AE - BMAZ North", "email": "tester.bmaz.north@relu.com",
         "phone_number": "2200000001"},
        {"first_name": "Suresh", "last_name": "AE - BMAZ South", "email": "tester.bmaz.south@relu.com",
         "phone_number": "2200000002"},
        {"first_name": "Mahesh", "last_name": "AE - BRAZ", "email": "tester.braz@relu.com",
         "phone_number": "2200000003"},
        {"first_name": "Ganesh", "last_name": "AE - Hubli Division", "email": "tester.hubli@relu.com",
         "phone_number": "2200000004"},
        {"first_name": "Naresh", "last_name": "AE - Belagavi Division", "email": "tester.belagavi@relu.com",
         "phone_number": "2200000005"},
        {"first_name": "Rajesh", "last_name": "AE - Mysuru Division", "email": "tester.mysuru@relu.com",
         "phone_number": "2200000006"},
        {"first_name": "Dinesh", "last_name": "AE - Gulbarga Division", "email": "tester.gulbarga@relu.com",
         "phone_number": "2200000007"},
        {"first_name": "Harish", "last_name": "AE - Bellary Division", "email": "tester.bellary@relu.com",
         "phone_number": "2200000008"},
          # ✅ SHEET USERS (NEW → customer)
        {"first_name": "MVS", "last_name": "MANIAN", "email": "venkat@vmepl.com",
         "phone_number": "9876543210", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "BMAZ NORTH", "email": "ceenz@bescom.co.in",
         "phone_number": "+91-8277892599", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "BMAZ SOUTH", "email": "cebmaz@bescom.co.in",
         "phone_number": "+91-9449045888", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "BRAZ", "email": "cebraz@bescom.co.in",
         "phone_number": "+91-9448234567", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "CTAZ", "email": "cectaz@bescom.co.in",
         "phone_number": "+91-9448461466", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "O&M ZONE HUBBALLI", "email": "ceomz.hubli@hescom.co.in",
         "phone_number": "+91-9448277608", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "BELAGAVI ZONE", "email": "ceomzbgm@hescom.co.in",
         "phone_number": "+91-9448370243", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "MANGALURU ZONE", "email": "ceemangaluru@mesco.in",
         "phone_number": "+91-9448289424", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "SHIVAMOGGA ZONE", "email": "ceeshivamogga@mesco.in",
         "phone_number": "+91-9480880565", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "MYSURU ZONE", "email": "ceez@cescmysore.org",
         "phone_number": "+91-9448994722", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "HASSAN ZONE", "email": "ceehsnzone@cescmysore.org",
         "phone_number": "+91-9448998099", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "GULBARGA ZONE", "email": "cegulbarga@gescom.in",
         "phone_number": "+91-9448359005", "usertype": "customer"},

        {"first_name": "CHIEF ENGINEER", "last_name": "BELLARY ZONE", "email": "cebellary@gescom.in",
         "phone_number": "+91-9448359029", "usertype": "customer"},
    ]

    for u in users_data:
        exists = session.query(User.id).filter_by(email=u["email"]).first()
        if exists:
            continue  # ❌ do nothing for existing users

        user = User(
            id=uuid.uuid4(),
            firstname=u["first_name"],
            lastname=u["last_name"],
            email=u["email"],
            phone_number=u["phone_number"],
            password_hash=get_password_hash(COMMON_PASSWORD),
            usertype=u.get("usertype", None),
            isactive=True,
            email_confirmed=True,
            phone_confirmed=True
        )
        session.add(user)
        session.flush()

        # ⭐ Track newly inserted users ONLY
        newly_created_user_ids.append(user.id)

    session.commit()
    print("[OK] New users seeded.")
    return newly_created_user_ids


def seed_roles(session):
    roles_data = [
        {"name": "Admin", "description": "Full access to all modules"},
        {"name": "Viewer", "description": "Read-only access"},
        {"name": "Operator", "description": "Can scan and submit inventory"},
        {"name": "Auditor", "description": "Can view scan history and audit trails"},
        {"name": "Vendor", "description": "Can have access over products"},
         # ✅ ERP SERVICE ROLE
        {"name": "ERP_SERVICE", "description": "Automated ERP sync service"},
        # ✅ TESTING REQUEST SYSTEM ROLES
        {"name": "Originator", "description": "Creates testing requests and raises procurement"},
        {"name": "Tester", "description": "Performs transformer testing and uploads results"},
        {"name": "Approver", "description": "Reviews and approves or rejects recommendations"},
        # ✅ SRS-SPECIFIED DESIGNATION ROLES (SEACMS-AI v1.3 Section 2.3)
        {"name": "AEE Maintenance", "description": "Assistant Executive Engineer - Field-level maintenance responsible officer"},
        {"name": "EE TLSS", "description": "Executive Engineer - Transmission Line & Substation primary reviewer"},
        {"name": "SEE W&M", "description": "Superintending Engineer - Works & Maintenance circle supervisor"},
        {"name": "EE RT", "description": "Executive Engineer - Research & Testing"},
        {"name": "SEE RT", "description": "Superintending Engineer - Research & Testing"},
        {"name": "CEE Transmission Zone", "description": "Chief Engineer Executive - Transmission zone management"},
        {"name": "CEE RT&R&D", "description": "Chief Engineer Executive - Research Testing & R&D"},
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
# ✅ TEST REGISTER MODULE (SRS §5.1.1)
{"name": "Test Register",
 "description": "SRS §5.1.1 — Periodic test catalogue: defines what tests are mandatory, "
                "how often, and by which role for each equipment type. "
                "Accessible to: EE TLSS, Department Head, AEE Maintenance.",
 "path": "test_register",
 "group_name": "Condition Monitoring"},
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
    user_roles_data = [
        {"email": "admin@relu.com", "role": "Admin"},
        {"email": "viewer@relu.com", "role": "Viewer"},
        {"email": "operator@relu.com", "role": "Operator"},
        {"email": "auditor@relu.com", "role": "Auditor"},
        {"email": "vendor@relu.com", "role": "Vendor"},
          # ✅ ERP SERVICE USER ROLE
        {"email": "erp_bot@relu.com", "role": "ERP_SERVICE"},
        # ✅ TESTING REQUEST SYSTEM USER ROLES
        {"email": "originator@relu.com", "role": "Originator"},
        {"email": "tester@relu.com", "role": "Tester"},
        {"email": "approver@relu.com", "role": "Approver"},
        # Circle/Division testers
        {"email": "tester.bmaz.north@relu.com", "role": "Tester"},
        {"email": "tester.bmaz.south@relu.com", "role": "Tester"},
        {"email": "tester.braz@relu.com", "role": "Tester"},
        {"email": "tester.hubli@relu.com", "role": "Tester"},
        {"email": "tester.belagavi@relu.com", "role": "Tester"},
        {"email": "tester.mysuru@relu.com", "role": "Tester"},
        {"email": "tester.gulbarga@relu.com", "role": "Tester"},
        {"email": "tester.bellary@relu.com", "role": "Tester"},
    ]

    for ur in user_roles_data:
        user = session.query(User).filter_by(email=ur["email"]).first()
        role_id = role_ids.get(ur["role"])
        if user and role_id:
            # Single-role rule: remove any existing roles first
            session.query(UserRole).filter(
                UserRole.user_id == user.id,
                UserRole.role_id != role_id
            ).delete()

            exists = session.query(UserRole).filter_by(user_id=user.id, role_id=role_id).first()
            if not exists:
                session.add(UserRole(user_id=user.id, role_id=role_id))
    session.commit()
    print("[OK] User-role assignments seeded successfully (single-role enforced).")


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
        # ── 3. Originator — procurement + testing requests + equipment ────────
        {
            "name": "Originator",
            "description": "Creates testing requests and raises procurement. Access to dashboard, all procurement modules, testing requests, and equipment register.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _readwrite(procurement_modules) +
                _readwrite(testing_requests_module) +
                _readwrite(equipment_module)
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
        # ── 5. Field Tester ───────────────────────────────────────────────────
        {
            "name": "Field Tester",
            "description": "Performs on-site transformer testing and uploads results. View testing requests; full access to testing module; view equipment register.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readonly(testing_requests_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module)
            ),
        },
        # ── 6. Lab Tester ─────────────────────────────────────────────────────
        {
            "name": "Lab Tester",
            "description": "Performs laboratory testing and uploads results. View testing requests; full access to testing module; view equipment register.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readonly(testing_requests_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module)
            ),
        },
        # ── 7. Department Head — recommendations & approvals + equipment view
        {
            "name": "Department Head",
            "description": "Reviews and approves recommendations from testers. Access to Recommendations, Approvals modules, and view equipment register.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": True,
            "permissions_template": (
                _approve(recommendations_module) +
                _approve(approvals_module) +
                _readonly(equipment_module)
            ),
        },
        # ── 8. Purchaser — dashboard + procurement ────────────────────────────
        {
            "name": "Purchaser",
            "description": "Manages procurement activities. Access to dashboard and all procurement modules.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _readwrite(procurement_modules)
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

        # ── 10. AEE Maintenance — Field supervisor ────────────────────────────
        {
            "name": "AEE Maintenance",
            "description": "Assistant Executive Engineer - Field-level maintenance responsible officer",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": aee_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _readonly(testing_requests_module) +
                _approve(approvals_module) +
                _readonly(recommendations_module)
            ),
        },

        # ── 11. EE TLSS — Primary reviewer (CRITICAL ROLE) ────────────────────
        {
            "name": "EE TLSS",
            "description": "Executive Engineer - Transmission Line & Substation primary reviewer",
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
                _readonly(procurement_modules)
            ),
        },

        # ── 12. SEE W&M — Circle supervisor (CRITICAL ROLE) ───────────────────
        {
            "name": "SEE W&M",
            "description": "Superintending Engineer - Works & Maintenance circle supervisor",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": see_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _approve(approvals_module) +
                _readonly(vendor_documents_module) +
                _readonly(recommendations_module) +
                _readonly(testing_requests_module)
            ),
        },

        # ── 13. EE RT — R&D engineer ──────────────────────────────────────────
        {
            "name": "EE RT",
            "description": "Executive Engineer - Research & Testing",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": ee_tlss_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _readwrite(testing_requests_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module)
            ),
        },

        # ── 14. SEE RT — Senior R&D ───────────────────────────────────────────
        {
            "name": "SEE RT",
            "description": "Superintending Engineer - Research & Testing",
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
                _readonly(equipment_module)
            ),
        },

        # ── 15. CEE Transmission Zone — Zone management ───────────────────────
        {
            "name": "CEE Transmission Zone",
            "description": "Chief Engineer Executive - Transmission zone management",
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
                _readonly(equipment_module)
            ),
        },

        # ── 16. CEE RT&R&D — R&D chief ────────────────────────────────────────
        {
            "name": "CEE RT&R&D",
            "description": "Chief Engineer Executive - Research Testing & R&D",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": True,
            "default_module_id": cee_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _full(testing_module) +
                _readwrite(equipment_module) +
                _readonly(testing_requests_module) +
                _readonly(recommendations_module)
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
                user_id=user.id, org_role_id=role.id, is_active=True
            ).first()
            if not existing_role:
                session.add(OrgUserRole(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    org_role_id=role.id,
                    department_id=None,
                    is_active=True,
                    assigned_at=datetime.now(datetime.now().astimezone().tzinfo),
                    assigned_by=None
                ))

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
        if not existing_role:
            session.add(OrgUserRole(
                id=uuid.uuid4(),
                user_id=user.id,
                org_role_id=role.id,
                department_id=None,
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
    kptcl_org = session.query(Organization).filter_by(name="KPTCL").first()
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
        organization_id=kptcl_org.id
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
    # 6. Assign permission (ORG-SCOPED)
    # ─────────────────────────────────────────────────────────────
    existing_perm = session.query(OrgRolePermission).filter_by(
        org_role_id=org_admin_role.id,
        module_id=notifications_module.id
    ).first()

    if not existing_perm:
        session.add(
            OrgRolePermission(
                org_role_id=org_admin_role.id,
                module_id=notifications_module.id,
                can_view=True,
                can_create=False,
                can_edit=False,
                can_delete=False
                # 🔥 Add this IF your model has it:
                # organization_id=kptcl_org.id
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


def run_seed():
    # ── Create ALL SQLAlchemy tables (idempotent — safe on existing DB) ──────
    print("[INIT] Creating database schema via Base.metadata.create_all …")
    import models  # noqa: F401  — ensures all model classes register with Base
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
        print(f"[OK] Overall assessment template: {'provisioned' if inserted else 'already exists'}.")

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

        print("\n" + "=" * 80)
        print("  [OK] ALL SEED DATA INSERTED SUCCESSFULLY")
        print("=" * 80)
        print("\nQuick Start:")
        print("  1. Super Admin: superadmin@system.com / Admin123!")
        print("  2. Sample Org Admin: orgadmin@sampleorg.com / OrgAdmin123!")
        if kptcl_org:
            print("  3. KPTCL Org Admin: orgadmin@kptcl.com / admin123")
        print(f"  {4 if kptcl_org else 3}. View API docs: http://localhost:8000/docs")
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
        # Check for --kptcl flag for KPTCL-only seeding
        if len(sys.argv) > 2 and sys.argv[1] == "--kptcl":
            org_id = sys.argv[2]
            seed_kptcl_only(org_id)
        else:
            # Run full seed
            run_seed()

            # Optionally seed KPTCL if --with-kptcl flag is provided with org_id
            if len(sys.argv) > 2 and sys.argv[1] == "--with-kptcl":
                org_id = sys.argv[2]
                print("\n[INFO] Seeding KPTCL departments...")
                with get_db_session() as session:
                    seed_kptcl_departments(session, org_id)
    except Exception as e:
        import traceback
        traceback.print_exc()
