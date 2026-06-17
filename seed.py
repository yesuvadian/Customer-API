from contextlib import contextmanager
from datetime import datetime, timedelta
import uuid
import pandas as pd
from typing import Dict, Optional
from requests import session
from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.exc import IntegrityError
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
    RepairStageTransition, RepairWorkflowDefinition, OrgTestTemplate,
    # Surveillance Workflow
    SurveillanceConfig, SurveillanceTestConfig,
    # Notification config tables
    NotificationEventCatalogue, NotificationRoutingRule, NotificationScheduleRule,
    # Schedule
    TestRequestSchedule, ScheduleFrequency,
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


def run_migration_from_file(session, migration_file: str, migration_name: str) -> bool:
    """
    Execute a SQL migration file.

    Args:
        session: SQLAlchemy session
        migration_file: Path to .sql file (e.g., "migrations/008_surveillance_workflow.sql")
        migration_name: Display name (e.g., "Migration 008: Surveillance Workflow")

    Returns:
        True if successful, False if failed
    """
    import os

    if not os.path.exists(migration_file):
        print(f"[WARN] Migration file not found: {migration_file} — skipping")
        return False

    # Read with UTF-8 encoding (handle encoding issues on Windows)
    try:
        with open(migration_file, encoding='utf-8') as fh:
            sql_content = fh.read()
    except UnicodeDecodeError:
        # Fallback to latin-1 if UTF-8 fails
        with open(migration_file, encoding='latin-1') as fh:
            sql_content = fh.read()

    # Split on semicolons, but respect dollar-quoted $$ blocks (PL/pgSQL functions)
    statements = []
    current = []
    in_dollar_quote = False
    for line in sql_content.split("\n"):
        # Track entry/exit of $$ dollar-quote blocks
        stripped = line.strip()
        dollar_count = stripped.count("$$")
        if dollar_count % 2 != 0:          # odd number → toggle state
            in_dollar_quote = not in_dollar_quote
        current.append(line)
        if not in_dollar_quote and stripped.endswith(";"):
            chunk = "\n".join(current).strip().rstrip(";").strip()
            # Strip single-line comments from non-dollar-quoted content
            if chunk:
                statements.append(chunk)
            current = []
    # Any remaining content
    if current:
        chunk = "\n".join(current).strip().rstrip(";").strip()
        if chunk:
            statements.append(chunk)

    if not statements:
        print(f"[WARN] {migration_name}: No statements found — skipping")
        return True

    print(f"\n[MIGRATION] {migration_name}: {len(statements)} statement(s)")

    for i, stmt in enumerate(statements, 1):
        # Show truncated statement for progress
        preview = stmt[:60].replace("\n", " ")
        print(f"  [{i}/{len(statements)}] {preview}...", end=" ")
        try:
            session.execute(text(stmt))
            session.commit()
            print("[OK]")
        except Exception as exc:
            msg = str(exc).lower()
            # Graceful handling for "already exists" or "does not exist" errors (idempotency)
            if "already exists" in msg or "does not exist" in msg:
                print(f"[SKIP - already applied]")
                session.rollback()
            else:
                print(f"[ERROR] {exc}")
                session.rollback()
                return False

    print(f"[OK] {migration_name} completed")
    return True


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
                "title": "Bushing Details",
                "fields": [
                    {
                        "key": "bushing_details",
                        "label": "Bushing Details (per winding / phase)",
                        "type": "table",
                        "allow_add_rows": True,
                        "allow_delete_rows": True,
                        "read_only": False,
                        "columns": [
                            {"key": "winding",   "label": "Winding / Level", "type": "dropdown",
                             "options": ["HV (220kV)", "HV (400kV)", "HV (110kV)", "MV (66kV)", "MV (33kV)", "LV (11kV)", "Tertiary", "Neutral"]},
                            {"key": "phase",     "label": "Phase",   "type": "dropdown", "options": ["R", "Y", "B", "N"]},
                            {"key": "make",      "label": "Make",    "type": "text"},
                            {"key": "serial_no", "label": "Sl. No.", "type": "text"},
                            {"key": "yo_mfg",    "label": "Y.O. Mfg.", "type": "number"},
                        ],
                    },
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
                    {"key": "nameplate_photo",  "label": "Photograph of Nameplate", "type": "file", "required": True,  "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
                    {"key": "equipment_photo",  "label": "Equipment Photograph",    "type": "file", "required": False, "read_only": False, "accept": ["image/jpeg", "image/png"], "max_size_kb": 10240},
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
    # ⚡ KPTCL FIELD ROLES (system Role table — used by seed_privileges)
    # OrgRole equivalents with full permissions seeded by seed_seacms_roles_users.py
    # =========================
    {"name": "AE_JE", "description": "Assistant Engineer / Junior Engineer - failure reporting & commissioning"},
    {"name": "AEE_MAINTENANCE", "description": "Assistant Executive Engineer - field maintenance authority"},
    {"name": "EE_TLSS", "description": "Executive Engineer - Transmission Line & Substation reviewer"},
    {"name": "SEE_WM", "description": "Superintending Engineer - Works & Maintenance supervisor"},
    {"name": "EE_RT", "description": "Executive Engineer - Research & Testing"},
    {"name": "SEE_RT", "description": "Superintending Engineer - Research & Testing"},
    {"name": "CEE_TRANSMISSION_ZONE", "description": "Chief Engineer Executive - Transmission zone authority"},
    {"name": "CEE_RT_RD", "description": "Chief Engineer Executive - Research, Testing & R&D"},

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
    """No-op — seed_users() returns [] so new_user_ids is always empty.
    Users are assigned roles via seed_seacms_roles_users (OrgUserRole)."""
    if not new_user_ids:
        return
    print(f"[SKIP] assign_viewer_role_to_new_users: no new users to assign.")

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
        {"name": "Utility",              "description": "Type of utility - Generation, Transmission, DISCOM."},
        # ── Pre-Commission QAP lookup dropdowns ─────────────────────────────────
        {"name": "PCR Voltage Class",    "description": "Voltage class options for pre-commission QAP transformer requests."},
        {"name": "PCR Transformer Type", "description": "Winding configuration options for pre-commission QAP requests."},
        {"name": "PCR Cooling Class",    "description": "Cooling method options for pre-commission QAP transformer requests."},
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


def _get_or_create_category_detail(session, name: str, category_master_id: int,
                                   description: str = None, category_type: str = None,
                                   is_active: bool = True) -> CategoryDetails:
    """
    Safely get or create a CategoryDetails row with duplicate prevention.

    Uses filter_by to check for existing records first. If insert fails due to
    unique constraint violation (race condition), retries the query.

    Returns the CategoryDetails object (existing or newly created).
    """
    # Try to find existing
    existing = session.query(CategoryDetails).filter_by(
        name=name,
        category_master_id=category_master_id
    ).first()

    if existing:
        # Update fields if provided
        if description is not None:
            existing.description = description
        if category_type is not None:
            existing.category_type = category_type
        if is_active is not None:
            existing.is_active = is_active
        return existing

    # Create new
    detail = CategoryDetails(
        name=name,
        description=description or f"Detail for {name}",
        category_master_id=category_master_id,
        category_type=category_type,
        is_active=is_active
    )
    session.add(detail)

    try:
        session.flush()
        return detail
    except IntegrityError as e:
        # Duplicate was inserted by another process/transaction
        session.rollback()
        # Query again to get the existing row
        existing = session.query(CategoryDetails).filter_by(
            name=name,
            category_master_id=category_master_id
        ).first()
        if existing:
            print(f"  [INFO] CategoryDetails '{name}' already exists (concurrent insert detected)")
            return existing
        else:
            # Should never happen, but re-raise if we can't find it
            raise


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

        # ---------------- PCR Voltage Class ----------------
        {"master_name": "PCR Voltage Class", "name": "33kV",  "description": "33 kV voltage class transformer"},
        {"master_name": "PCR Voltage Class", "name": "66kV",  "description": "66 kV voltage class transformer"},
        {"master_name": "PCR Voltage Class", "name": "110kV", "description": "110 kV voltage class transformer"},
        {"master_name": "PCR Voltage Class", "name": "220kV", "description": "220 kV voltage class transformer"},
        {"master_name": "PCR Voltage Class", "name": "400kV", "description": "400 kV voltage class transformer"},

        # ---------------- PCR Transformer Type ----------------
        {"master_name": "PCR Transformer Type", "name": "Two-winding",      "description": "Standard two-winding power transformer"},
        {"master_name": "PCR Transformer Type", "name": "Three-winding",    "description": "Three-winding power transformer"},
        {"master_name": "PCR Transformer Type", "name": "Auto Transformer", "description": "Auto transformer"},

        # ---------------- PCR Cooling Class ----------------
        {"master_name": "PCR Cooling Class", "name": "ONAN", "description": "Oil Natural Air Natural"},
        {"master_name": "PCR Cooling Class", "name": "ONAF", "description": "Oil Natural Air Forced"},
        {"master_name": "PCR Cooling Class", "name": "OFAF", "description": "Oil Forced Air Forced"},
        {"master_name": "PCR Cooling Class", "name": "ODAF", "description": "Oil Directed Air Forced"},
    ]

    for d in category_details_data:
        master_id = master_ids.get(d["master_name"])
        if not master_id:
            print(f"[WARN] Master not found: {d['master_name']}")
            continue

        _get_or_create_category_detail(
            session,
            name=d["name"],
            category_master_id=master_id,
            description=d["description"],
            is_active=True
        )

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
{"name": "Asset Dashboard","description": "Asset Officer operational dashboard","path": "asset_dashboard","group_name": "Testing","is_menu": False},
{"name": "Test Coordinator Dashboard", "description": "Test coordinator operational dashboard — test schedule monitoring, overdue tests, equipment health, and remedial actions", "path": "test_coordinator_dashboard", "group_name": "Testing"},
{"name": "AE Dashboard",    "path": "ae_dashboard",    "description": "Field officer daily work overview — tests due, overdue maintenance, remedial actions", "group_name": "Testing", "is_menu": False},
{"name": "AEE Dashboard", "description": "Field-level supervisor dashboard — AEE operational view", "path": "aee_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "SEE Dashboard", "description": "Circle-level supervisor dashboard — SEE operational view", "path": "see_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "CEE Dashboard", "description": "Zone-level management dashboard — CEE operational view", "path": "cee_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "EE RT Dashboard",  "description": "EE RT relay testing & calibration dashboard — calibration compliance, overdue cals, expiring certs, FAIL count, open workflows", "path": "ee_rt_dashboard",  "group_name": "Testing", "is_menu": False},
{"name": "SEE RT Dashboard", "description": "SEE RT circle-level calibration supervision dashboard — circle compliance, overdue, expiring, FAIL, open workflows", "path": "see_rt_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "CEE RT Dashboard", "description": "CEE RT RD zone-level calibration governance dashboard — zone compliance, relay assets, open workflows, FAIL count", "path": "cee_rt_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "Admin Dashboard", "description": "Organization admin dashboard with system-wide metrics", "path": "admin_dashboard", "group_name": "Testing", "is_menu": False},
{"name": "Notifications", "description": "In-app notification centre — alerts, overdue reminders, approvals", "path": "notifications", "group_name": "Testing"},
{"name": "Notification Center",    "description": "Notification Center — manage templates, routing rules and schedules", "path": "org_notification_center",    "group_name": "Organization", "is_menu": True},
{"name": "Notification Templates", "description": "Configure email/SMS/in-app notification templates per event type", "path": "org_notification_templates", "group_name": "Organization", "is_menu": False},
{"name": "Notification Routing",   "description": "Configure routing rules — which roles receive which notifications", "path": "org_notification_routing",   "group_name": "Organization", "is_menu": False},
{"name": "Notification Schedules", "description": "Configure scheduled notification rules (due-date reminders, digests)", "path": "org_notification_schedules", "group_name": "Organization", "is_menu": False},
{"name": "Reporting Center",       "description": "Reporting Center — define, run and schedule operational reports",   "path": "org_reporting_center",       "group_name": "Organization", "is_menu": True},
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
# ✅ WORKFLOW OPERATIONS DASHBOARD — unified view across all workflow types
{"name": "Workflow Dashboard",
 "description": "Unified operations dashboard — dynamically shows counts, stage breakdown, "
                "equipment at risk, and recent activity for all workflow types defined in "
                "repair_workflow_definitions. New workflow types appear automatically.",
 "path": "workflow-dashboard",
 "group_name": "Field Operations"},
# ✅ BREAKDOWN WORKFLOW MODULE  (renamed from "Repair Workflows" — path unchanged: repair-workflows)
{"name": "Breakdown Workflows",
 "rename_from": "Repair Workflows",
 "description": "Unplanned breakdown repair lifecycle — 10-stage workflow from Failure Reporting to Commissioning. "
                "Config (org-admin only): define stages, forms, roles, transitions. "
                "Execution: stage-role RBAC driven; each stage locks to authorized roles only.",
 "path": "repair-workflows",
 "group_name": "Field Operations"},
# ✅ OVERHAUL WORKFLOW MODULE
{"name": "Overhaul Workflows",
 "description": "Overhaul lifecycle — auto-triggered when cumulative ops count crosses threshold. "
                "Stages: Trigger Review, Execution, Completion Upload, Officer Verification. "
                "Stage-role RBAC driven; each stage locks to authorised roles only.",
 "path": "overhaul-workflows",
 "group_name": "Field Operations"},
# ✅ CALIBRATION WORKFLOW MODULE
{"name": "Calibration Workflows",
 "description": "Calibration lifecycle workflow — auto-triggered when a calibration result is Fail. "
                "Stages: Due Review, Send to Lab, Certificate Upload, Officer Verification. "
                "Stage-role RBAC driven; each stage locks to authorised roles only.",
 "path": "calibration-workflows",
 "group_name": "Field Operations"},
# ✅ ANNUAL AUDIT WORKFLOW MODULE
{"name": "Annual Audit Workflows",
 "description": "Annual audit 5-stage workflow: Observation Reporting to Closure. TA&QC Inspector executes; Reviewing Officer reviews compliance.",
 "path": "annual-audit-workflows",
 "group_name": "Field Operations"},
# ✅ SURVEILLANCE WORKFLOW MODULE (SRS §7.3)
{"name": "Surveillance Workflows",
 "description": "24-month post-commissioning surveillance with quarterly testing (Q1-Q4) and final evaluation. "
                "Tracks DGA, BDV, IR, Oil Quality tests at enhanced frequency with quality ratings.",
 "path": "surveillance-workflows",
 "group_name": "Field Operations"},
# ✅ PRE-COMMISSION QAP MODULE
{"name": "Pre-Commission Requests",
 "description": "PCR approval queue — raise and approve pre-commission QAP requests before factory inspection begins.",
 "path": "precommission-requests",
 "group_name": "Field Operations"},
{"name": "Pre-Commission Workflows",
 "description": "9-stage Manufacturing QAP workflow for 110kV/66kV Power Transformers per KPTCL QAP circular.",
 "path": "precommission-workflows",
 "group_name": "Field Operations"},
# ✅ SURVEILLANCE DASHBOARD MODULE
{"name": "Surveillance Dashboard",
 "description": "Surveillance analytics dashboard — organization-wide surveillance metrics including "
                "quality ratings distribution, abnormal test rates, quarterly completion status, "
                "and equipment health trends.",
 "path": "surveillance-dashboard",
 "group_name": "Field Operations"},
# ✅ AI ANALYTICS DASHBOARD MODULE
{"name": "AI Analytics Dashboard",
 "description": "Generic analytics engine dashboard — equipment health scores, trend analysis, "
                "threshold breach forecasts, anomaly detection, and hierarchy roll-ups. "
                "Department-scoped drill-down from zone → substation → individual equipment.",
 "path": "analytics-dashboard",
 "group_name": "Condition Monitoring"},
# ✅ TEST SCHEDULE TEMPLATES MODULE (SRS §5.1.2)
{"name": "Test Schedule Templates",
 "rename_from": "Schedule Templates",
 "description": "SRS §5.1.2 — Automated periodic test ticket generation: master test schedule templates "
                "and operational schedules per equipment. Org-admin manages master set; "
                "operational schedules auto-created on equipment commissioning.",
 "path": "testing_schedules",
 "group_name": "Condition Monitoring"},
# ✅ MAINTENANCE SCHEDULE TEMPLATES MODULE
{"name": "Maintenance Schedule Templates",
 "description": "Automated periodic maintenance ticket generation: master maintenance schedule templates "
                "and operational schedules per equipment. Mirrors test schedule structure but scoped "
                "to maintenance request category.",
 "path": "maintenance_schedules",
 "group_name": "Condition Monitoring"},
# ✅ SCHEDULE COMPLIANCE MODULE
{"name": "Test Schedules",
 "description": "Visual compliance tracker — shows per-equipment test schedule status "
                "(overdue, due-imminent, due-soon, ok) with filter by equipment type, "
                "substation, and compliance band. Accessible to EE TLSS, AEE, org-admin.",
 "path": "schedule_compliance",
 "group_name": "Condition Monitoring"},
# ✅ DATA IMPORT MODULE
{"name": "Data Import",
 "description": "Bulk import historical test reports from PDF/Excel — OCR/Excel extraction, "
                "multi-record review grid, and one-click submission as closed Testing Requests.",
 "path": "import-data",
 "group_name": "Condition Monitoring",
 "is_menu": True},
    ]

    module_ids = {}

    for m in modules_data:
        existing = session.query(Module).filter_by(name=m["name"]).first()

        # Support rename_from: if new name not found, look up old name and rename in-place
        if not existing and m.get("rename_from"):
            existing = session.query(Module).filter_by(name=m["rename_from"]).first()
            if existing:
                existing.name = m["name"]
                print(f"  [RENAME] Module '{m['rename_from']}' → '{m['name']}'")

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
            "role": "Asset Data Officer", "module": "Testing Requests",
            "can_view": True, "can_add": True, "can_edit": True,
            "can_delete": True, "can_search": True, "can_assign": True
        },
        # Removed: Validation Requests privilege (module not implemented)
       {"role": "Asset Data Officer","module": "Asset Dashboard", "can_view": True},
        # Originator — Procurement modules (full add/edit)
        {"role": "Asset Data Officer","module": "Request Quote",       "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Asset Data Officer","module": "RQ with Vendor",      "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Asset Data Officer","module": "Request Product",     "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Asset Data Officer","module": "Quotes",              "can_view": True},
        {"role": "Asset Data Officer","module": "Sales Orders",        "can_view": True},
        {"role": "Asset Data Officer","module": "Invoices",            "can_view": True},
        {"role": "Asset Data Officer","module": "Retainer Invoices",   "can_view": True},
        {"role": "Asset Data Officer","module": "Payments Made",       "can_view": True},
        {"role": "Asset Data Officer","module": "Statements",          "can_view": True},
        {"role": "Asset Data Officer","module": "Enquiry",             "can_view": True, "can_add": True},
        {"role": "Asset Data Officer","module": "Contact Us",          "can_view": True},

        # FIELD TESTER — view Testing Requests, full on Testing
        {"role": "Test Engineer", "module": "Testing Requests", "can_view": True},
        {
            "role": "Test Engineer", "module": "Testing",
            "can_view": True, "can_add": True, "can_edit": True, "can_search": True
        },

        # LAB TESTER — same as Field Tester
        {"role": "Test Engineer", "module": "Testing Requests", "can_view": True},
        {
            "role": "Test Engineer", "module": "Testing",
            "can_view": True, "can_add": True, "can_edit": True, "can_search": True
        },

        # TEST ASSIGNER (Approver) — approve/assign on Testing Request Approvals
        {
            "role": "Test & Work Coordinator", "module": "Testing Request Approvals",
            "can_view": True, "can_approve": True, "can_assign": True
        },
        {"role": "Test & Work Coordinator", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "Test & Work Coordinator", "module": "Dashboard", "can_view": True},

        # DOC-VIEWER — view only for Vendor Documents
        {
            "role": "doc-viewer", "module": "Vendor Documents",
            "can_view": True, "can_add": False, "can_edit": False, 
            "can_delete": False, "can_search": True
        },

        # DEPARTMENT HEAD — approve on Recommendations + Approvals
        {"role": "Reviewing Officer", "module": "Dashboard", "can_view": True},
        {"role": "Reviewing Officer", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "Reviewing Officer", "module": "Recommendations",
         "can_view": True, "can_approve": True},
        {"role": "Reviewing Officer", "module": "Approvals",
         "can_view": True, "can_approve": True},

        # PURCHASER — dashboard + full procurement
        {"role": "Procurement Officer", "module": "Dashboard",            "can_view": True},
        {"role": "Procurement Officer", "module": "Request Quote",        "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Procurement Officer", "module": "RQ with Vendor",       "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Procurement Officer", "module": "Request Product",      "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Procurement Officer", "module": "Quotes",               "can_view": True},
        {"role": "Procurement Officer", "module": "Sales Orders",         "can_view": True},
        {"role": "Procurement Officer", "module": "Invoices",             "can_view": True},
        {"role": "Procurement Officer", "module": "Retainer Invoices",    "can_view": True},
        {"role": "Procurement Officer", "module": "Payments Made",        "can_view": True},
        {"role": "Procurement Officer", "module": "Statements",           "can_view": True},
        {"role": "Procurement Officer", "module": "Enquiry",              "can_view": True, "can_add": True},
        {"role": "Procurement Officer", "module": "Contact Us",           "can_view": True},

        # TESTER MAPPING — Admin full, Originator view-only
        {
            "role": "Admin", "module": "Tester Mapping",
            "can_view": True, "can_add": True, "can_edit": True,
            "can_delete": True, "can_search": True
        },
        {"role": "Asset Data Officer","module": "Tester Mapping", "can_view": True},

        # TEST TEMPLATE MANAGEMENT — Admin full (via bulk), Originator view-only
        {"role": "Asset Data Officer","module": "Test Template Management", "can_view": True},

        # ✅ EQUIPMENT ASSET REGISTER — role-based access
        {
            "role": "Asset Data Officer", "module": "Equipment",
            "can_view": True, "can_add": True, "can_edit": True,
            "can_search": True
        },
        {"role": "Test Engineer", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Test Engineer", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Test & Work Coordinator", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Reviewing Officer", "module": "Equipment", "can_view": True, "can_search": True},

        # ✅ SRS DESIGNATION ROLES — Permissions per role hierarchy
        # AEE Maintenance — Field supervisor
        {"role": "Maintenance Officer", "module": "Dashboard", "can_view": True},
        {"role": "Maintenance Officer", "module": "Testing Requests", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True, "can_assign": True},
        {"role": "Maintenance Officer", "module": "Testing", "can_view": True, "can_add": True},
        {"role": "Maintenance Officer", "module": "Testing Request Approvals", "can_view": True, "can_approve": True},
        {"role": "Maintenance Officer", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Maintenance Officer", "module": "Notifications", "can_view": True},
        {"role": "Maintenance Officer", "module": "Reports", "can_view": True, "can_export": True},

        # EE TLSS — Primary reviewer (most critical role)
        # NOTE: Does NOT have Testing Request Approvals access (not applicable for this role)
        {"role": "Reviewing Officer", "module": "Dashboard", "can_view": True},
        {"role": "Reviewing Officer", "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Reviewing Officer", "module": "Testing Requests", "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Reviewing Officer", "module": "Testing", "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Reviewing Officer", "module": "Equipment", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "Reviewing Officer", "module": "Notifications", "can_view": True},
        {"role": "Reviewing Officer", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Reviewing Officer", "module": "Request Quote", "can_view": True},
        {"role": "Reviewing Officer", "module": "Quotes", "can_view": True},
        {"role": "Reviewing Officer", "module": "Sales Orders", "can_view": True},

        # SEE W&M — Circle supervisor (equivalent to Test Assigner in SRS)
        {"role": "Supervisory Officer", "module": "Dashboard", "can_view": True},
        {"role": "Supervisory Officer", "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Supervisory Officer", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "Supervisory Officer", "module": "Testing", "can_view": True},
        {"role": "Supervisory Officer", "module": "Testing Request Approvals", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "Supervisory Officer", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Supervisory Officer", "module": "Notifications", "can_view": True},
        {"role": "Supervisory Officer", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Supervisory Officer", "module": "Request Quote", "can_view": True, "can_add": True},
        {"role": "Supervisory Officer", "module": "Quotes", "can_view": True, "can_approve": True},
        {"role": "Supervisory Officer", "module": "Vendor Directory", "can_view": True},

        # EE RT — Research & Testing engineer
        {"role": "Reviewing Officer", "module": "Dashboard", "can_view": True},
        {"role": "Reviewing Officer", "module": "Testing Requests", "can_view": True, "can_add": True, "can_approve": True, "can_assign": True},
        {"role": "Reviewing Officer", "module": "Testing", "can_view": True, "can_add": True, "can_edit": True},
        {"role": "Reviewing Officer", "module": "Testing Request Approvals", "can_view": True, "can_approve": True},
        {"role": "Reviewing Officer", "module": "Test Template Management", "can_view": True, "can_edit": True},
        {"role": "Reviewing Officer", "module": "Equipment", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "Reviewing Officer", "module": "Reports", "can_view": True, "can_export": True},

        # SEE RT — Senior Research & Testing
        {"role": "Supervisory Officer", "module": "Dashboard", "can_view": True},
        {"role": "Supervisory Officer", "module": "Testing Requests", "can_view": True},
        {"role": "Supervisory Officer", "module": "Testing", "can_view": True, "can_add": True, "can_edit": True, "can_export": True},
        {"role": "Supervisory Officer", "module": "Testing Request Approvals", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "Supervisory Officer", "module": "Test Template Management", "can_view": True, "can_edit": True},
        {"role": "Supervisory Officer", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Supervisory Officer", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Supervisory Officer", "module": "Vendor Directory", "can_view": True},

        # CEE Transmission Zone — Zone management
        {"role": "Senior Management Approver", "module": "Dashboard", "can_view": True},
        {"role": "Senior Management Approver", "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Senior Management Approver", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "Senior Management Approver", "module": "Testing", "can_view": True},
        {"role": "Senior Management Approver", "module": "Testing Request Approvals", "can_view": True, "can_approve": True},
        {"role": "Senior Management Approver", "module": "Equipment", "can_view": True, "can_search": True},
        {"role": "Senior Management Approver", "module": "Notifications", "can_view": True},
        {"role": "Senior Management Approver", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Senior Management Approver", "module": "Request Quote", "can_view": True, "can_approve": True},
        {"role": "Senior Management Approver", "module": "Quotes", "can_view": True, "can_approve": True},
        {"role": "Senior Management Approver", "module": "Sales Orders", "can_view": True},
        {"role": "Senior Management Approver", "module": "Vendor Directory", "can_view": True},

        # CEE RT&R&D — Research & Development chief
        {"role": "Senior Management Approver", "module": "Dashboard", "can_view": True},
        {"role": "Senior Management Approver", "module": "Testing Requests", "can_view": True, "can_approve": True, "can_assign": True},
        {"role": "Senior Management Approver", "module": "Testing", "can_view": True},
        {"role": "Senior Management Approver", "module": "Testing Request Approvals", "can_view": True},
        {"role": "Senior Management Approver", "module": "Test Template Management", "can_view": True, "can_add": True, "can_edit": True, "can_delete": True},
        {"role": "Senior Management Approver", "module": "Equipment", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "Senior Management Approver", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Senior Management Approver", "module": "Vendor Directory", "can_view": True},

        # ✅ EE TLSS DASHBOARD — role-based access
        # All operational roles can view the dashboard; it auto-renders the
        # correct widget set based on the user's OrgRole inside dashboard_service.py.
        {"role": "Asset Data Officer",     "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Test Engineer",    "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Test Engineer",      "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Test & Work Coordinator",   "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Reviewing Officer", "module": "EE TLSS Dashboard", "can_view": True},
        {"role": "Procurement Officer",       "module": "EE TLSS Dashboard", "can_view": True},

        # ✅ NOTIFICATIONS — all active roles can view their own notification centre
        {"role": "Asset Data Officer",     "module": "Notifications", "can_view": True},
        {"role": "Test Engineer",    "module": "Notifications", "can_view": True},
        {"role": "Test Engineer",      "module": "Notifications", "can_view": True},
        {"role": "Test & Work Coordinator",   "module": "Notifications", "can_view": True},
        {"role": "Reviewing Officer", "module": "Notifications", "can_view": True},
        {"role": "Procurement Officer",       "module": "Notifications", "can_view": True},
        {"role": "Vendor",          "module": "Notifications", "can_view": True},

        # ✅ REPORTING SUITE — view + export for all operational roles
        {"role": "Asset Data Officer",     "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Test Engineer",    "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Test Engineer",      "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Test & Work Coordinator",   "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Reviewing Officer", "module": "Reports", "can_view": True, "can_export": True},
        {"role": "Procurement Officer",       "module": "Reports", "can_view": True, "can_export": True},

        # ✅ FAILURE REGISTRY — Stage 2 (SRS Sec 3.3.3)
        # Accessible to field-level and supervisory roles; TA&QC can also submit.
        {"role": "Maintenance Officer",         "module": "Failure Registry", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "Reviewing Officer",                 "module": "Failure Registry", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "Reviewing Officer",                   "module": "Failure Registry", "can_view": True, "can_add": True, "can_search": True},
        {"role": "Supervisory Officer",                 "module": "Failure Registry", "can_view": True, "can_search": True},
        {"role": "Supervisory Officer",                  "module": "Failure Registry", "can_view": True, "can_search": True},
        {"role": "Senior Management Approver",   "module": "Failure Registry", "can_view": True, "can_search": True},
        {"role": "Senior Management Approver",             "module": "Failure Registry", "can_view": True, "can_search": True},
        {"role": "Test Engineer",            "module": "Failure Registry", "can_view": True, "can_add": True},
        {"role": "Test Engineer",              "module": "Failure Registry", "can_view": True, "can_add": True},

        # ✅ TA&QC INSPECTIONS — Stage 10 (SRS Sec 6)
        {"role": "Asset Data Officer",                  "module": "TA&QC Inspections", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "Reviewing Officer",                   "module": "TA&QC Inspections", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "Supervisory Officer",                  "module": "TA&QC Inspections", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "Senior Management Approver",             "module": "TA&QC Inspections", "can_view": True, "can_add": True, "can_approve": True},
        {"role": "Reviewing Officer",                 "module": "TA&QC Inspections", "can_view": True, "can_search": True},
        {"role": "Supervisory Officer",                 "module": "TA&QC Inspections", "can_view": True, "can_search": True},
        {"role": "Senior Management Approver",   "module": "TA&QC Inspections", "can_view": True, "can_search": True},

        # ✅ REPAIR WORKFLOWS — Transformer repair lifecycle (10 stages)
        # Stage-level RBAC is enforced in the service layer via RepairStageRole.
        # Module-level privileges here control who can see the module in the nav.
        # Config endpoints (PUT /repair-workflows/config/*) require is_org_admin.

        # All stage-acting roles: can view + add (save data) + approve (advance/reject)
        {"role": "Maintenance Officer",         "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "TRC Member",              "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Senior Management Approver",             "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Senior Management Approver",   "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Vendor",                  "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Inspection Engineer",     "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Finance Officer",         "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "QA Team",                 "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Reviewing Officer",                   "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_approve": True},
        {"role": "Supervisory Officer",                  "module": "Breakdown Workflows", "can_view": True, "can_add": True, "can_approve": True},

        # Supervisory roles: view + export only (no stage actions)
        {"role": "Reviewing Officer",                 "module": "Breakdown Workflows", "can_view": True, "can_export": True},
        {"role": "Supervisory Officer",                 "module": "Breakdown Workflows", "can_view": True, "can_export": True},

        # ✅ SURVEILLANCE WORKFLOWS — Post-commissioning 24-month monitoring (SRS §7.3)
        # Stage-level RBAC enforced via RepairStageRole (same as repair workflows).
        # Module-level privileges control nav visibility.

        # All surveillance-acting roles: can view + add (save quarterly review data) + approve (advance stages)
        {"role": "Maintenance Officer",         "module": "Surveillance Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Reviewing Officer",           "module": "Surveillance Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Supervisory Officer",         "module": "Surveillance Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Senior Management Approver",  "module": "Surveillance Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "TRC Member",                  "module": "Surveillance Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Test Engineer",               "module": "Surveillance Workflows", "can_view": True, "can_add": True},

        # ✅ SURVEILLANCE DASHBOARD — Analytics and metrics
        # All roles that can view surveillance workflows can also view the dashboard
        {"role": "Maintenance Officer",         "module": "Surveillance Dashboard", "can_view": True, "can_export": True},
        {"role": "Reviewing Officer",           "module": "Surveillance Dashboard", "can_view": True, "can_export": True},
        {"role": "Supervisory Officer",         "module": "Surveillance Dashboard", "can_view": True, "can_export": True},
        {"role": "Senior Management Approver",  "module": "Surveillance Dashboard", "can_view": True, "can_export": True},
        {"role": "TRC Member",                  "module": "Surveillance Dashboard", "can_view": True, "can_export": True},
        {"role": "Test Engineer",               "module": "Surveillance Dashboard", "can_view": True},

        # ✅ AI ANALYTICS DASHBOARD — org-admin only
        {"role": "Admin",                       "module": "AI Analytics Dashboard", "can_view": True, "can_export": True},

        # ✅ PRE-COMMISSION QAP — Request tickets (approval queue)
        # Asset Data Officer creates PCR tickets; approvers approve/reject.
        {"role": "Asset Data Officer",         "module": "Pre-Commission Requests", "can_view": True, "can_add": True, "can_edit": True, "can_search": True},
        {"role": "Reviewing Officer",          "module": "Pre-Commission Requests", "can_view": True, "can_add": True, "can_approve": True, "can_search": True},
        {"role": "Supervisory Officer",        "module": "Pre-Commission Requests", "can_view": True, "can_approve": True, "can_search": True},
        {"role": "Senior Management Approver", "module": "Pre-Commission Requests", "can_view": True, "can_approve": True, "can_search": True},
        {"role": "Transformer Repair Coordinator", "module": "Pre-Commission Requests", "can_view": True, "can_search": True},

        # ✅ PRE-COMMISSION QAP — 9-stage workflow execution
        # Reviewing Officer is the primary stage actor (fills QAP forms, advances stages).
        # Coordinator handles stage assignment. Senior Management Approver escalation.
        {"role": "Reviewing Officer",          "module": "Pre-Commission Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Senior Management Approver", "module": "Pre-Commission Workflows", "can_view": True, "can_add": True, "can_edit": True, "can_approve": True},
        {"role": "Supervisory Officer",        "module": "Pre-Commission Workflows", "can_view": True, "can_export": True},
        {"role": "Asset Data Officer",         "module": "Pre-Commission Workflows", "can_view": True},
        {"role": "Transformer Repair Coordinator", "module": "Pre-Commission Workflows", "can_view": True, "can_add": True, "can_assign": True},

        # ✅ AE DASHBOARD — Test Engineer (AE_JE)
        {"role": "Test Engineer",              "module": "AE Dashboard",  "can_view": True},

        # ✅ EE RT DASHBOARD — Reviewing Officer (RT track)
        {"role": "Reviewing Officer",          "module": "EE RT Dashboard",  "can_view": True},

        # ✅ SEE RT DASHBOARD — Supervisory Officer (RT track)
        {"role": "Supervisory Officer",        "module": "SEE RT Dashboard", "can_view": True},

        # ✅ CEE RT DASHBOARD — Senior Management Approver (RT RD track)
        {"role": "Senior Management Approver", "module": "CEE RT Dashboard", "can_view": True},
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

    # Legacy equipment_tests dict removed — all types now defined in
    # equipment_types_by_category below (SRS-compliant, singular names).
    equipment_tests = {}

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
                "Transformer Oil Test",
                "Dielectric Frequency Response (DFR / IDAX)",
                "Sweep Frequency Response Analysis (SFRA)",
                "Tan-Delta, Capacitance & Insulation Diagnostics",
                "Winding Tan-Delta & Capacitance Test",
                "220kV Bushing Tan-Delta Test",
                "66kV Bushing Tan-Delta Test",
                "Insulation Diagnostics (IDAX)",
                "Dielectric Frequency Response (DFR) — Routine",
                "Sweep Frequency Response Analysis (SFRA) — Routine",
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
            # repair_lifecycle stages removed — handled by RepairWorkflow stage system
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
                "Relay Testing",
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
        # ── Surge Arrestor ───────────────────────────────────────────────────
        "Surge Arrestor": {
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
            # repair_lifecycle stages removed — handled by RepairWorkflow stage system
        },
        # ── Battery Set ──────────────────────────────────────────────────────
        "Battery Set": {
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
            # repair_lifecycle stages removed — handled by RepairWorkflow stage system
        },
        # ── Current Transformer ──────────────────────────────────────────────
        "Current Transformer": {
            "test": [
                "CT Insulation Test",
                "CT Ratio Test (Detailed)",
                "Capacitance & Tan Delta Test (CT)",
                "Tan Delta NCT Test",
                "Core Insulation Test",
                "CT Ratio Test",
                "Insulation Resistance (IR) Test",
            ],
        },
        # ── Capacitor Voltage Transformer ────────────────────────────────────
        "Capacitor Voltage Transformer": {
            "test": [
                "CVT Test Report",
            ],
        },
        # ── Potential Transformer ────────────────────────────────────────────
        "Potential Transformer": {
            "test": [
                "Insulation Resistance Test",
                "Ratio Test",
                "Polarity Test",
                "Tan Delta Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
        },
        # ── Station Auxiliary Transformer ────────────────────────────────────
        "Station Auxiliary Transformer": {
            "test": [
                "Insulation Resistance Test",
                "Ratio Test",
                "Winding Resistance Test",
                "Tan Delta Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
        },
        # ── Diesel Generator Set ─────────────────────────────────────────────
        "Diesel Generator Set": {
            "test": [
                "Load Test",
                "Fuel System Test",
                "Battery and Starting System Test",
                "Voltage and Frequency Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
                "Engine Oil Change",
                "Fuel Filter Replacement",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
                "Environmental",
            ],
        },
        # ── Digital Communication Panel ──────────────────────────────────────
        "Digital Communication Panel": {
            "test": [
                "Communication Link Test",
                "Signal Quality Test",
                "Network Connectivity Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
        },
        # ── LTAC Panel ───────────────────────────────────────────────────────
        "LTAC Panel": {
            "test": [
                "Control Circuit Test",
                "Indication Test",
                "Metering Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
        },
        # ── PLCC Panel ───────────────────────────────────────────────────────
        "PLCC Panel": {
            "test": [
                "Communication Test",
                "Logic Test",
                "Interface Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
        },
        # ── Wave Trap ────────────────────────────────────────────────────────
        "Wave Trap": {
            "test": [
                "Insulation Resistance Test",
                "Capacitance Test",
                "Inductance Test",
                "Resonance Frequency Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
        },
        # ── Control & Relay Panel ────────────────────────────────────────────
        "Control & Relay Panel": {
            "test": [
                "Control Circuit Test",
                "Relay Functional Test",
                "Interlocking Test",
                "Indication Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
                "Contact Cleaning",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
            ],
        },
        # ── Fire Fighting System ─────────────────────────────────────────────
        "Fire Fighting System": {
            "test": [
                "Pressure Test",
                "Flow Test",
                "Alarm System Test",
                "Sprinkler System Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
                "Pump Maintenance",
                "Valve Maintenance",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
                "Environmental",
            ],
        },
        # ── Battery Charger ──────────────────────────────────────────────────
        "Battery Charger": {
            "test": [
                "Output Voltage Test",
                "Output Current Test",
                "Ripple Voltage Test",
                "Float Charge Test",
            ],
            "maintenance": [
                "Routine Preventive Maintenance",
                "Contact Cleaning",
            ],
            "inspection": [
                "Electrical Safety",
                "General Maintenance",
                "Documentation",
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
            _get_or_create_category_detail(
                session,
                name=detail_name,
                category_master_id=lm.id,
                description=f"Lifecycle test type: {detail_name}",
                category_type="maintenance",
                is_active=True
            )

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
            _get_or_create_category_detail(
                session,
                name=test_name,
                category_master_id=master_id,
                description=f"Test for {equipment_name}",
                category_type="test",
                is_active=True
            )

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
                _get_or_create_category_detail(
                    session,
                    name=type_name,
                    category_master_id=master_id,
                    description=f"{category_type.replace('_', ' ').title()} for {equipment_name}",
                    category_type=category_type,
                    is_active=True
                )

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

        _get_or_create_category_detail(
            session,
            name="Nameplate",
            category_master_id=master_id,
            description=f"Nameplate data entry for {equipment_name}",
            category_type="nameplate",
            is_active=True
        )
        nameplate_created += 1

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
        _get_or_create_category_detail(
            session,
            name=p,
            category_master_id=pm_id,
            description=f"{p} priority",
            is_active=True
        )

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
        _get_or_create_category_detail(
            session,
            name=r,
            category_master_id=rm_id,
            description=f"Rating {r}",
            is_active=True
        )

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
            _get_or_create_category_detail(
                session,
                name=detail_name,
                category_master_id=m_id,
                description=master_name,
                is_active=True
            )

    session.commit()
    print("[OK] Organizational hierarchy categories seeded successfully.")


def seed_sample_testing_request(session):
    # removed — testing requests are created via the UI, not seeded
    pass


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

# ─────────────────────────────────────────────────────────────────────────────
# KPTCL TEST USER SEEDING
# Stable deterministic users for regression/auth automation
# ─────────────────────────────────────────────────────────────────────────────

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
    asset_dashboard_module_id = modules_by_name.get("Asset Dashboard")
    test_coordinator_dashboard_module_id = modules_by_name.get("Test Coordinator Dashboard")
    aee_dashboard_module_id    = modules_by_name.get("AEE Dashboard")
    see_dashboard_module_id    = modules_by_name.get("SEE Dashboard")
    cee_dashboard_module_id    = modules_by_name.get("CEE Dashboard")
    admin_dashboard_module_id  = modules_by_name.get("Admin Dashboard")
    ee_rt_dashboard_module_id  = modules_by_name.get("EE RT Dashboard")
    see_rt_dashboard_module_id = modules_by_name.get("SEE RT Dashboard")
    cee_rt_dashboard_module_id = modules_by_name.get("CEE RT Dashboard")

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
    workflows_module          = [mid for mid in [modules_by_name.get("Workflows")] if mid]
    workflow_dashboard_module       = [mid for mid in [modules_by_name.get("Workflow Dashboard")] if mid]
    breakdown_workflows_module      = [mid for mid in [modules_by_name.get("Breakdown Workflows")] if mid]
    overhaul_workflows_module       = [mid for mid in [modules_by_name.get("Overhaul Workflows")] if mid]
    calibration_workflows_module    = [mid for mid in [modules_by_name.get("Calibration Workflows")] if mid]
    annual_audit_workflows_module   = [mid for mid in [modules_by_name.get("Annual Audit Workflows")] if mid]
    surveillance_workflows_module        = [mid for mid in [modules_by_name.get("Surveillance Workflows")] if mid]
    surveillance_dashboard_module        = [mid for mid in [modules_by_name.get("Surveillance Dashboard")] if mid]
    precommission_requests_module        = [mid for mid in [modules_by_name.get("Pre-Commission Requests")] if mid]
    precommission_workflows_module       = [mid for mid in [modules_by_name.get("Pre-Commission Workflows")] if mid]
    schedule_compliance_module          = [mid for mid in [modules_by_name.get("Test Schedules")] if mid]
    test_schedule_templates_module      = [mid for mid in [modules_by_name.get("Test Schedule Templates")] if mid]
    maintenance_schedule_templates_module = [mid for mid in [modules_by_name.get("Maintenance Schedule Templates")] if mid]
    procurement_approvals_module = [mid for mid in [modules_by_name.get("Procurement Approvals")] if mid]
    taqc_inspections_module      = [mid for mid in [modules_by_name.get("TA&QC Inspections")] if mid]
    failure_registry_module      = [mid for mid in [modules_by_name.get("Failure Registry")] if mid]

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
        # ── 1. System Administrator ───────────────────────────────────────────
        {
            "name": "System Administrator",
            "rename_from": "System Administrator",
            "description": "Manages organisation structure: users, roles and departments.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _full(org_modules) +
                _approve(approvals_module) +
                _approve(testing_request_approvals_module)
            ),
        },

        # ── 2. Asset Data Officer ─────────────────────────────────────────────
        {
            "name": "Asset Data Officer",
            "rename_from": "Asset Data Officer",
            "description": "Creates testing requests and raises procurement. Can start repair workflows.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _readwrite(procurement_modules) +
                _readwrite(testing_requests_module) +
                _readwrite(equipment_module) +
                _readwrite(breakdown_workflows_module) +
                _readwrite(taqc_inspections_module) +
                _readwrite(precommission_requests_module) +
                _readonly(precommission_workflows_module)
            ),
        },

        # ── 3. AEE_MAINTENANCE ────────────────────────────────────────────────
        {
            "name": "AEE_MAINTENANCE",
            "rename_from": "Maintenance Officer",
            "description": "Field-level maintenance responsible officer. Key repair and overhaul workflow actor.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": modules_by_name.get("Asset Dashboard"),
            "permissions_template": (
                _readonly(dashboard_module) +
                _readonly(testing_requests_module) +
                _approve(approvals_module) +
                _readonly(recommendations_module) +
                _readonly(workflow_dashboard_module) +
                _readwrite(breakdown_workflows_module) +
                _readwrite(overhaul_workflows_module) +
                _readwrite(calibration_workflows_module) +
                _readwrite(annual_audit_workflows_module)
            ),
        },

        # ── 4. AE_JE ──────────────────────────────────────────────────────────
        {
            "name": "AE_JE",
            "rename_from": "Test Engineer",
            "description": "Performs on-site and laboratory transformer testing and repair/overhaul stage execution.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readonly(testing_requests_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module) +
                _readonly(workflow_dashboard_module) +
                _readwrite(breakdown_workflows_module) +
                _readwrite(overhaul_workflows_module) +
                _readwrite(calibration_workflows_module) +
                _readonly(annual_audit_workflows_module)
            ),
        },

        # ── 5. Test & Work Coordinator ────────────────────────────────────────
        {
            "name": "Test & Work Coordinator",
            "rename_from": "Test Assigner",
            "description": "Approves testing requests, assigns testers, and coordinates field maintenance work.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _approve(testing_request_approvals_module) +
                _readonly(equipment_module) +
                _readonly(dashboard_module) +
                _readonly(testing_requests_module) +
                _approve(approvals_module) +
                _readonly(recommendations_module) +
                _readonly(workflow_dashboard_module) +
                _readwrite(breakdown_workflows_module)
            ),
        },

        # ── 6. EE_TLSS ────────────────────────────────────────────────────────
        {
            "name": "EE_TLSS",
            "rename_from": "Reviewing Officer",
            "description": "EE (T&SS) — reviews and approves testing requests, recommendations and workflow stages.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": True,
            "default_module_id": ee_tlss_dashboard_module_id,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _approve(approvals_module) +
                _approve(recommendations_module) +
                _readwrite(testing_requests_module) +
                _approve(testing_request_approvals_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module) +
                _readonly(procurement_modules) +
                _readonly(workflow_dashboard_module) +
                _approve(breakdown_workflows_module) +
                _approve(overhaul_workflows_module) +
                _approve(calibration_workflows_module) +
                _approve(annual_audit_workflows_module) +
                _approve(precommission_requests_module) +
                _approve(precommission_workflows_module) +
                _readonly(failure_registry_module) +
                _readonly([ee_tlss_dashboard_module_id] if ee_tlss_dashboard_module_id else [])
            ),
        },

        # ── 7. EE_RT ──────────────────────────────────────────────────────────
        {
            "name": "EE_RT",
            "rename_from": "EE_RT",
            "description": "EE (Repair & Testing track) — same authority as EE_TLSS scoped to the RT circle.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": True,
            "default_module_id": ee_rt_dashboard_module_id,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _approve(approvals_module) +
                _approve(recommendations_module) +
                _readwrite(testing_requests_module) +
                _approve(testing_request_approvals_module) +
                _readwrite(testing_module) +
                _readonly(equipment_module) +
                _readonly(procurement_modules) +
                _readonly(workflow_dashboard_module) +
                _approve(breakdown_workflows_module) +
                _approve(overhaul_workflows_module) +
                _approve(calibration_workflows_module) +
                _approve(annual_audit_workflows_module) +
                _approve(precommission_requests_module) +
                _approve(precommission_workflows_module) +
                _readonly(failure_registry_module) +
                _readonly([ee_rt_dashboard_module_id] if ee_rt_dashboard_module_id else [])
            ),
        },

        # ── 8. SEE_WM ─────────────────────────────────────────────────────────
        {
            "name": "SEE_WM",
            "rename_from": "Supervisory Officer",
            "description": "SEE (W&M) — circle-level supervisor over repair workflows and testing.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": see_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _approve(approvals_module) +
                _readonly(recommendations_module) +
                _readonly(testing_requests_module) +
                _readwrite(testing_module) +
                _approve(testing_request_approvals_module) +
                _readonly(vendor_documents_module) +
                _readonly(equipment_module) +
                _readonly(workflow_dashboard_module) +
                _approve(breakdown_workflows_module) +
                _readonly(overhaul_workflows_module) +
                _readonly(calibration_workflows_module) +
                _readonly(annual_audit_workflows_module) +
                _approve(precommission_requests_module) +
                _readonly(precommission_workflows_module) +
                _readonly([see_rt_dashboard_module_id] if see_rt_dashboard_module_id else [])
            ),
        },

        # ── 9. SEE_RT ─────────────────────────────────────────────────────────
        {
            "name": "SEE_RT",
            "rename_from": "SEE_RT",
            "description": "SEE (Repair & Testing track) — same authority as SEE_WM scoped to the RT circle.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": see_rt_dashboard_module_id,
            "permissions_template": (
                _readonly(dashboard_module) +
                _approve(approvals_module) +
                _readonly(recommendations_module) +
                _readonly(testing_requests_module) +
                _readwrite(testing_module) +
                _approve(testing_request_approvals_module) +
                _readonly(vendor_documents_module) +
                _readonly(equipment_module) +
                _readonly(workflow_dashboard_module) +
                _approve(breakdown_workflows_module) +
                _readonly(overhaul_workflows_module) +
                _readonly(calibration_workflows_module) +
                _readonly(annual_audit_workflows_module) +
                _approve(precommission_requests_module) +
                _readonly(precommission_workflows_module) +
                _readonly([see_rt_dashboard_module_id] if see_rt_dashboard_module_id else [])
            ),
        },

        # ── 10. CEE_TRANSMISSION_ZONE ─────────────────────────────────────────
        {
            "name": "CEE_TRANSMISSION_ZONE",
            "rename_from": "Senior Management Approver",
            "description": "CEE (Transmission Zone) — zone-level final approver for all workflows.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": True,
            "default_module_id": cee_dashboard_module_id,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _approve(approvals_module) +
                _full(testing_module) +
                _readwrite(equipment_module) +
                _readonly(testing_requests_module) +
                _readonly(procurement_modules) +
                _readonly(vendor_documents_module) +
                _readonly(recommendations_module) +
                _readonly(workflow_dashboard_module) +
                _approve(breakdown_workflows_module) +
                _approve(overhaul_workflows_module) +
                _approve(calibration_workflows_module) +
                _approve(annual_audit_workflows_module) +
                _approve(precommission_requests_module) +
                _approve(precommission_workflows_module) +
                _readonly([cee_rt_dashboard_module_id] if cee_rt_dashboard_module_id else [])
            ),
        },

        # ── 11. CEE_RT_RD ─────────────────────────────────────────────────────
        {
            "name": "CEE_RT_RD",
            "rename_from": "CEE_RT_RD",
            "description": "CEE (RT & R&D) — zone-level management on the Repair & Testing / R&D track.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": True,
            "default_module_id": cee_rt_dashboard_module_id,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _approve(approvals_module) +
                _full(testing_module) +
                _readwrite(equipment_module) +
                _readonly(testing_requests_module) +
                _readonly(procurement_modules) +
                _readonly(vendor_documents_module) +
                _readonly(recommendations_module) +
                _readonly(workflow_dashboard_module) +
                _approve(breakdown_workflows_module) +
                _approve(overhaul_workflows_module) +
                _approve(calibration_workflows_module) +
                _approve(annual_audit_workflows_module) +
                _approve(precommission_requests_module) +
                _approve(precommission_workflows_module) +
                _readonly([cee_rt_dashboard_module_id] if cee_rt_dashboard_module_id else [])
            ),
        },

        # ── 12. TA&QC Inspector ───────────────────────────────────────────────
        {
            "name": "TA&QC Inspector",
            "rename_from": "TA&QC Inspector",
            "description": "Technical Assurance & Quality Control Inspector. Performs annual substation inspections.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readwrite(taqc_inspections_module) +
                _readwrite(annual_audit_workflows_module) +
                _readonly(failure_registry_module) +
                _readonly(dashboard_module)
            ),
        },

        # ── 13. Transformer Repair Coordinator ────────────────────────────────
        {
            "name": "Transformer Repair Coordinator",
            "rename_from": "Transformer Repair Coordinator",
            "description": "Assigns users to transformer repair and overhaul workflow stages.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "default_module_id": ee_tlss_dashboard_module_id,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _readonly(workflow_dashboard_module) +
                _readwrite(breakdown_workflows_module) +
                _readwrite(overhaul_workflows_module) +
                _readwrite(calibration_workflows_module) +
                _readwrite(annual_audit_workflows_module) +
                _readwrite(precommission_workflows_module) +
                _readonly(precommission_requests_module) +
                _readonly(testing_requests_module)
            ),
        },

        # ── 14. Procurement Officer ───────────────────────────────────────────
        {
            "name": "Procurement Officer",
            "rename_from": "Procurement Officer",
            "description": "Manages procurement activities. Read-only access to repair workflows.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": (
                _readwrite(dashboard_module) +
                _readwrite(procurement_modules) +
                _readwrite(breakdown_workflows_module)
            ),
        },
    ]

    created_count = 0
    updated_count = 0

    for template_data in templates_data:
        rename_from = template_data.pop("rename_from", None)
        existing = session.query(RoleTemplate).filter_by(name=template_data["name"]).first()
        if not existing and rename_from:
            existing = session.query(RoleTemplate).filter_by(name=rename_from).first()
            if existing:
                existing.name = template_data["name"]
                print(f"  [RENAME] RoleTemplate '{rename_from}' -> '{template_data['name']}'")

        if existing:
            existing.description = template_data["description"]
            existing.is_org_admin = template_data["is_org_admin"]
            existing.is_dept_admin = template_data["is_dept_admin"]
            existing.auto_provision = template_data["auto_provision"]
            existing.default_module_id = template_data.get("default_module_id")
            existing.permissions_template = template_data["permissions_template"]
            flag_modified(existing, "permissions_template")  # JSONB needs explicit dirty flag
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

    # Build valid module ID set to guard against stale IDs in permissions_template
    _valid_module_ids = {m.id for m in session.query(Module).all()}

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

        # Create permissions from template (skip stale module IDs that no longer exist)
        if template.permissions_template:
            for perm_data in template.permissions_template:
                mid = perm_data.get("module_id")
                if mid not in _valid_module_ids:
                    continue
                permission = OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mid,
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
            "name": "Test Engineer",
            "description": "Test Engineer role with exact module permissions for tester assignment"
        },
    ]

    tester_roles = []
    for role_config in tester_roles_config:
        # Check if role already exists (also check old names for rename support)
        existing_role = session.query(OrgRole).filter_by(
            organization_id=org.id,
            name=role_config["name"]
        ).first()
        if not existing_role:
            # Try legacy names
            for old_name in ("Field Tester", "Lab Tester"):
                existing_role = session.query(OrgRole).filter_by(
                    organization_id=org.id, name=old_name
                ).first()
                if existing_role:
                    existing_role.name = role_config["name"]
                    break

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
            "password": "admin123",
            "role_name": "Test Engineer",
            "firstname": "Field",
            "lastname": "Tester One",
            "phone": "9999999001"
        },
        {
            "email": "fieldtester2@sampleorg.com",
            "password": "admin123",
            "role_name": "Test Engineer",
            "firstname": "Field",
            "lastname": "Tester Two",
            "phone": "9999999002"
        },
        {
            "email": "labtester1@sampleorg.com",
            "password": "admin123",
            "role_name": "Test Engineer",
            "firstname": "Lab",
            "lastname": "Tester One",
            "phone": "9999999003"
        },
        {
            "email": "labtester2@sampleorg.com",
            "password": "admin123",
            "role_name": "Test Engineer",
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
            "email": "assetdataofficer@sampleorg.com",
            "password": "Originator123!",
            "role_name": "Asset Data Officer",
            "firstname": "Sample",
            "lastname": "Asset Officer",
            "phone": "9999999010"
        },
        {
            "email": "testworkcoordinator@sampleorg.com",
            "password": "Assigner123!",
            "role_name": "Test & Work Coordinator",
            "firstname": "Test Work",
            "lastname": "Coordinator",
            "phone": "9999999011"
        },
        {
            "email": "reviewingofficer@sampleorg.com",
            "password": "DeptHead123!",
            "role_name": "Reviewing Officer",
            "firstname": "Reviewing",
            "lastname": "Officer",
            "phone": "9999999012"
        },
        {
            "email": "procurementofficer@sampleorg.com",
            "password": "Purchaser123!",
            "role_name": "Procurement Officer",
            "firstname": "Procurement",
            "lastname": "Officer",
            "phone": "9999999013"
        },
        {
            "email": "sysadmin@sampleorg.com",
            "password": "OrgAdmin123!",
            "role_name": "System Administrator",
            "firstname": "System",
            "lastname": "Administrator",
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
        _valid_module_ids = {m.id for m in session.query(Module).all()}

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

                # Create permissions from template (skip stale module IDs)
                if template.permissions_template:
                    for perm_data in template.permissions_template:
                        mid = perm_data.get("module_id")
                        if mid not in _valid_module_ids:
                            continue
                        permission = OrgRolePermission(
                            id=uuid.uuid4(),
                            org_role_id=role.id,
                            module_id=mid,
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

        # ── Sync permissions for EXISTING roles against updated templates ──────
        # This ensures stale permissions (e.g. missing can_add after template update)
        # are refreshed on every seed run without needing to drop the org.
        print(f"[INFO] Syncing permissions for existing KPTCL roles from templates...")
        templates_by_name = {t.name: t for t in session.query(RoleTemplate).filter_by(auto_provision=True).all()}
        _valid_module_ids = {m.id for m in session.query(Module).all()}
        synced_roles = 0
        for role in session.query(OrgRole).filter_by(organization_id=org.id).all():
            template = templates_by_name.get(role.name)
            if not template or not template.permissions_template:
                continue
            # Delete existing permissions and re-insert from template
            session.query(OrgRolePermission).filter_by(org_role_id=role.id).delete()
            for perm_data in template.permissions_template:
                mid = perm_data.get("module_id")
                if mid not in _valid_module_ids:
                    continue
                session.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mid,
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
                ))
            synced_roles += 1
        session.commit()
        print(f"[OK] Synced permissions for {synced_roles} existing KPTCL roles")

        # Build a lookup of all roles (existing + newly provisioned)
        provisioned_by_name = {r.name: r for r in session.query(OrgRole).filter_by(organization_id=org.id).all()}

        # Users now seeded exclusively by seed_seacms_roles_users.py — skipped here.
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
        primary_email="info@utility.com",
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
    _valid_module_ids = {m.id for m in session.query(Module).all()}

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
        elif template.name == "Asset Data Officer":
            engineer_role = role
        elif template.name == "Test Engineer":
            tester_role = role

        # Create permissions from template (skip stale module IDs)
        if template.permissions_template:
            for perm_data in template.permissions_template:
                mid = perm_data.get("module_id")
                if mid not in _valid_module_ids:
                    continue
                permission = OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mid,
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

    # Grant ALL module permissions to org admin roles (Admin role)
    # This ensures org admins have full access to all modules
    all_modules = session.query(Module).filter_by(is_active=True).all()
    org_admin_roles = session.query(OrgRole).filter_by(
        organization_id=org.id,
        is_org_admin=True
    ).all()

    for admin_role in org_admin_roles:
        for module in all_modules:
            # Check if permission already exists
            existing_perm = session.query(OrgRolePermission).filter_by(
                org_role_id=admin_role.id,
                module_id=module.id
            ).first()

            if existing_perm:
                # Update to grant full access
                existing_perm.can_view = True
                existing_perm.can_add = True
                existing_perm.can_edit = True
                existing_perm.can_delete = True
                existing_perm.can_approve = True
                existing_perm.can_assign = True
                existing_perm.can_export = True
                existing_perm.can_import = True
            else:
                # Create new permission with full access
                permission = OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=admin_role.id,
                    module_id=module.id,
                    can_view=True,
                    can_add=True,
                    can_edit=True,
                    can_delete=True,
                    can_approve=True,
                    can_assign=True,
                    can_export=True,
                    can_import=True,
                    cts=datetime.now(datetime.now().astimezone().tzinfo),
                    mts=datetime.now(datetime.now().astimezone().tzinfo)
                )
                session.add(permission)

    # Build a lookup of provisioned roles by name for easy access
    provisioned_by_name = {r.name: r for r in session.query(OrgRole).filter_by(organization_id=org.id).all()}

    # Users now seeded exclusively by seed_seacms_roles_users.py — skipped here.
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
    user = session.query(User).filter_by(email="orgadmin@utility.com").first()
    if not user:
        print("[WARN] seed_notifications_module_and_permissions: orgadmin@utility.com not found — skipping")
        return

    # ─────────────────────────────────────────────────────────────
    # 4. Validate user belongs to KPTCL org
    # ─────────────────────────────────────────────────────────────
    org_user_role = session.query(OrgUserRole).filter_by(
        user_id=user.id,
    ).first()

    if not org_user_role:
        print("[WARN] seed_notifications_module_and_permissions: orgadmin@utility.com has no OrgUserRole — skipping notification permissions")
        return

    # ─────────────────────────────────────────────────────────────
    # 5. Get Org Admin role (ORG-SCOPED)
    # ─────────────────────────────────────────────────────────────
    org_admin_role = session.query(OrgRole).filter_by(
        organization_id=kptcl_org.id,
        name="System Administrator",
        is_active=True
    ).first()

    if not org_admin_role:
        print("[WARN] seed_notifications_module_and_permissions: 'System Administrator' OrgRole not found for KPTCL — skipping")
        return

    # ─────────────────────────────────────────────────────────────
    # 6. Assign permissions (ORG-SCOPED)
    #    Grant: Notifications + My Organization to Org Admin role
    # ─────────────────────────────────────────────────────────────
    notif_center_mod    = session.query(Module).filter_by(path="org_notification_center").first()
    notif_template_mod  = session.query(Module).filter_by(path="org_notification_templates").first()
    notif_routing_mod   = session.query(Module).filter_by(path="org_notification_routing").first()
    notif_schedule_mod  = session.query(Module).filter_by(path="org_notification_schedules").first()
    reporting_center_mod = session.query(Module).filter_by(path="org_reporting_center").first()

    for mod in filter(None, [notifications_module, notif_center_mod, notif_template_mod,
                              notif_routing_mod, notif_schedule_mod, reporting_center_mod]):
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

    # Derive hierarchy levels directly from the Excel columns (order-preserving)
    levels = list(df.columns)

    # Track created departments by full path
    department_map: Dict[str, str] = {}

    _ZONE_CODE_MAP = {
        "bagalkot zone":   "BK",
        "bangalore zone":  "BN",
        "hassan zone":     "HS",
        "kalaburagi zone": "KL",
        "mysuru zone":     "MY",
        "tumkur zone":     "TK",
    }

    def generate_code(name: str, target_len: int = 3) -> str:
        """Generate a department code from the name."""
        clean_name = name.replace(' Zone', '').replace(' Circle', '').replace(' Division', '')
        clean_name = clean_name.replace(' Section', '').replace('kV', '').strip()
        words = clean_name.split()
        if len(words) > 1:
            code = ''.join([w[0].upper() for w in words])
        else:
            code = clean_name.upper()
        return (code[:target_len]).ljust(target_len, 'X')

    # No synthetic root — zones from the Excel are the top-level nodes (parent=None)

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
                # First level (Zone) — no parent, these are the tree roots
                full_path = dept_name
                parent_id = None

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
            if level_idx == 0:
                code = _ZONE_CODE_MAP.get(dept_name.strip().lower()) or generate_code(dept_name, 2)
            elif level_idx == len(levels) - 1:
                import re as _re
                base = _re.sub(r"^\d+\s*kV\s*", "", dept_name, flags=_re.IGNORECASE).strip()
                code = generate_code(base, 4)
            else:
                code = generate_code(dept_name, 3)

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
    print(f"[OK] COMPLETED: Created {len(department_map)} total departments")
    print(f"{'='*60}\n")


def seed_kptcl_equipment(session, org_id: str, excel_path: str = None):
    """
    Seed KPTCL equipment assets from equipment_seed.xlsx.

    The workbook must contain an "Equipment" sheet with columns:
      substation, equipment_type, voltage_class, bay_name, phase,
      manufacturer, yom, doc, factory_serial_number,
      ct_ratio_actual, ct_ratio_current, pt_ratio,
      capacity_mva, vector_group, impedance_pct, status

    Each row is linked to the OrgDepartment whose name matches the
    "substation" column value.
    """
    import os
    from models import Equipment, CategoryMaster

    print("\n--- KPTCL Equipment Seeding ---")

    org = session.query(Organization).filter(Organization.id == uuid.UUID(org_id)).first()
    if not org:
        print(f"[ERROR] Organization {org_id} not found")
        return

    if excel_path is None:
        project_root = os.path.dirname(os.path.abspath(__file__))
        excel_path = os.path.join(project_root, "equipment_seed_with_all_data.xlsx")

    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Equipment seed file not found: {excel_path}")

    try:
        df = pd.read_excel(excel_path, sheet_name="Equipment", dtype=str)
        df = df.where(pd.notna(df), None)
        print(f"[OK] Loaded {len(df)} equipment rows")
    except Exception as e:
        print(f"[ERROR] Failed to read Equipment sheet: {e}")
        return

    # Resolve admin user for created_by
    admin = (
        session.query(User)
        .filter(User.organization_id == uuid.UUID(org_id), User.email.ilike("%orgadmin%"))
        .first()
        or session.query(User).filter(User.organization_id == uuid.UUID(org_id)).first()
    )
    created_by = admin.id if admin else None

    # Load equipment type (CategoryMaster) lookup
    equip_types = (
        session.query(CategoryMaster)
        .filter(CategoryMaster.description == "Testing Equipment", CategoryMaster.is_active.is_(True))
        .all()
    )
    # Normalise type names for fuzzy lookup
    type_map = {}
    for et in equip_types:
        type_map[et.name.lower()] = et.id
        # short aliases
        if "current transformer" in et.name.lower():
            type_map["ct"] = et.id
        elif "potential transformer" in et.name.lower() or "voltage transformer" in et.name.lower():
            type_map["pt"] = et.id
            type_map["cvt"] = et.id
        elif "power transformer" in et.name.lower():
            type_map["power transformer"] = et.id

    # Load all departments for this org into a name→id map
    depts = session.query(OrgDepartment).filter(
        OrgDepartment.organization_id == uuid.UUID(org_id)
    ).all()
    dept_map = {d.name.strip().lower(): d.id for d in depts}
    print(f"[INFO] {len(dept_map)} departments available for equipment lookup")

    created = skipped = 0

    for _, row in df.iterrows():
        substation_name = (row.get("substation") or "").strip()
        dept_id = dept_map.get(substation_name.lower())
        if not dept_id:
            # Fallback: try parent division name from the row
            division_name = (row.get("division") or "").strip()
            if division_name:
                dept_id = dept_map.get(division_name.lower())
            if not dept_id:
                print(f"  [WARN] Department not found for substation: '{substation_name}' — skipping row")
                skipped += 1
                continue
            else:
                print(f"  [INFO] Substation '{substation_name}' mapped to parent division '{division_name}'")

        raw_type = (row.get("equipment_type") or "").strip()
        equip_type_id = None
        for key in (raw_type.lower(), raw_type.split("(")[0].strip().lower()):
            equip_type_id = type_map.get(key)
            if equip_type_id:
                break
        if not equip_type_id:
            print(f"  [WARN] Equipment type not found: '{raw_type}' — skipping")
            skipped += 1
            continue

        # Parse numeric fields safely
        def _float(val):
            try:
                return float(val) if val else None
            except (ValueError, TypeError):
                return None

        def _int(val):
            try:
                v = str(val).split(".")[0] if val else None
                return int(v) if v else None
            except (ValueError, TypeError):
                return None

        def _clean_str(val):
            """Convert pandas nan strings and empty strings to None."""
            if val is None or val == "" or str(val).lower() in ("nan", "none", "null"):
                return None
            return str(val).strip() if val else None

        voltage_class = row.get("voltage_class") or ""
        # Strip trailing "kV" suffix if present for storage consistency
        voltage_class = voltage_class.replace("kV", "").replace("KV", "").strip() or None

        yom = _int(row.get("yom"))
        doc_raw = row.get("doc")
        doc_date = None
        if doc_raw:
            try:
                doc_date = pd.to_datetime(doc_raw, dayfirst=True).date()
            except Exception:
                doc_date = None

        # Determine status enum  (values: active, retired, scrapped, under_repair)
        raw_status = (row.get("status") or "In-service").strip().lower()
        from models import EquipmentStatus
        status_map = {
            "in-service": EquipmentStatus.active,
            "in service": EquipmentStatus.active,
            "operational": EquipmentStatus.active,
            "active": EquipmentStatus.active,
            "retired": EquipmentStatus.retired,
            "decommissioned": EquipmentStatus.scrapped,
            "scrapped": EquipmentStatus.scrapped,
            "under maintenance": EquipmentStatus.under_repair,
            "maintenance": EquipmentStatus.under_repair,
            "under repair": EquipmentStatus.under_repair,
        }
        status = status_map.get(raw_status, EquipmentStatus.active)

        from services.equipment_service import EquipmentService
        try:
            EquipmentService.create_equipment(
                db=session,
                organization_id=uuid.UUID(org_id),
                department_id=dept_id,
                equipment_type_id=equip_type_id,
                voltage_class=voltage_class,
                bay_number=_clean_str(row.get("bay_name")),
                manufacturer=_clean_str(row.get("manufacturer")),
                factory_serial_number=_clean_str(row.get("factory_serial_number")),
                year_of_manufacture=yom,
                commissioned_date=doc_date,
                phase=_clean_str(row.get("phase")),
                ct_ratio_actual=_clean_str(row.get("ct_ratio_actual")),
                ct_ratio_current=_clean_str(row.get("ct_ratio_current")),
                pt_ratio=_clean_str(row.get("pt_ratio")),
                vector_group=_clean_str(row.get("vector_group")),
                impedance_pct=_float(row.get("impedance_pct")),
                created_by=created_by,
            )
            session.commit()
            created += 1
        except Exception as e:
            session.rollback()
            print(f"  [WARN] Failed to create equipment row: {e}")
            skipped += 1

    print(f"\n[OK] Equipment seeding complete: {created} created, {skipped} skipped")


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
    # ── Reporting Center columns (idempotent) ───────────────────────────────
    session.execute(text("""
        ALTER TABLE public.report_definitions
            ADD COLUMN IF NOT EXISTS group_name         VARCHAR(100),
            ADD COLUMN IF NOT EXISTS notification_event VARCHAR(80)
    """))
    # ── extra_data on user notifications (for download URL etc.) ────────────
    session.execute(text("""
        ALTER TABLE public.user_notifications
            ADD COLUMN IF NOT EXISTS extra_data JSONB
    """))
    # ── report_query_keys table ───────────────────────────────────────────
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS public.report_query_keys (
            key               VARCHAR(100) PRIMARY KEY,
            label             VARCHAR(255) NOT NULL,
            description       TEXT,
            group_name        VARCHAR(100),
            parameters_schema JSONB NOT NULL DEFAULT '{}',
            is_active         BOOLEAN DEFAULT TRUE,
            is_system         BOOLEAN DEFAULT TRUE,
            sort_order        INTEGER DEFAULT 0,
            cts               TIMESTAMPTZ DEFAULT NOW(),
            mts               TIMESTAMPTZ DEFAULT NOW()
        )
    """))
    # ── fallback_keys on notification_variables (replaces hardcoded _ALIASES) ─
    session.execute(text("""
        ALTER TABLE public.notification_variables
            ADD COLUMN IF NOT EXISTS fallback_keys JSONB NOT NULL DEFAULT '[]'
    """))
    # ── sql_template + org_alias on report_query_keys (replaces _q_* methods) ─
    session.execute(text("""
        ALTER TABLE public.report_query_keys
            ADD COLUMN IF NOT EXISTS sql_template TEXT,
            ADD COLUMN IF NOT EXISTS org_alias    VARCHAR(10)
    """))
    session.commit()
    print("[OK] report_definitions and report_logs tables ready.")


def seed_report_definitions(session):
    """
    Insert/upsert system report definitions.
    Idempotent — updates group_name/notification_event on existing rows,
    inserts new rows if they don't exist yet.
    """
    # fmt: (name, query_key, group_name, frequency, notification_event, output_format, description)
    DEFINITIONS = [
        # ── Existing definitions — now enriched with group_name + notification_event ──────
        {
            "name": "Equipment Condition Summary",
            "description": "All active equipment with latest test condition (CRITICAL/ALERT/NORMAL/NOT_TESTED)",
            "query_key": "equipment_condition_summary",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Equipment Lifecycle",
            "notification_event": None,
        },
        # ── Testing Requests group ────────────────────────────────────────────────
        {
            "name": "Overdue Test Report",
            "description": "Tests past their due date with days-overdue count.",
            "query_key": "overdue_tests_report",
            "output_format": "excel",
            "frequency": "monthly",
            "group_name": "Testing Requests",
            "notification_event": "overdue_report_ready",
        },
        {
            "name": "Active Alerts",
            "description": "Test results with CRITICAL or ALERT evaluation",
            "query_key": "active_alerts_report",
            "output_format": "excel",
            "frequency": "daily",
            "group_name": "Testing Requests",
            "notification_event": None,
        },
        {
            "name": "ALERT / CRITICAL Equipment Report",
            "description": "All ALERT and CRITICAL equipment (deduplicated by UEIC).",
            "query_key": "flagged_equipment_report",
            "output_format": "excel",
            "frequency": "weekly",
            "group_name": "Testing Requests",
            "notification_event": "alert_report_ready",
        },
        {
            "name": "Test Compliance Status Report",
            "description": "Test compliance % by zone / circle / substation.",
            "query_key": "compliance_status_report",
            "output_format": "excel",
            "frequency": "monthly",
            "group_name": "Testing Requests",
            "notification_event": "compliance_report_ready",
        },
        {
            "name": "Testing Request Status",
            "description": "All testing requests with current status and assignment",
            "query_key": "testing_request_status_report",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Testing Requests",
            "notification_event": None,
        },
        {
            "name": "Test Results Summary",
            "description": "Test results with evaluation outcomes",
            "query_key": "test_results_summary_report",
            "output_format": "excel",
            "frequency": "weekly",
            "group_name": "Testing Requests",
            "notification_event": None,
        },
        {
            "name": "Recommendation Approvals",
            "description": "Recommendations with approval status and notes",
            "query_key": "recommendation_approval_report",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Testing Requests",
            "notification_event": None,
        },
        # ── Equipment Lifecycle group ─────────────────────────────────────────────
        {
            "name": "Equipment Inventory Report",
            "description": "Full equipment inventory with zone hierarchy, condition, age, and manufacturer.",
            "query_key": "equipment_inventory_report",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Equipment Lifecycle",
            "notification_event": None,
        },
        {
            "name": "Equipment Lifecycle Summary",
            "description": (
                "One row per equipment unit showing commissioned date, total test count, "
                "total failure count, last test date and result, and current status."
            ),
            "query_key": "equipment_lifecycle_report",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Equipment Lifecycle",
            "notification_event": None,
        },
        {
            "name": "Equipment Condition Summary",
            "description": "All active equipment with latest test condition (CRITICAL/ALERT/NORMAL/NOT_TESTED)",
            "query_key": "equipment_condition_summary",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Equipment Lifecycle",
            "notification_event": None,
        },
        # ── Failure Register group ────────────────────────────────────────────────
        {
            "name": "Equipment Failure Annual Report",
            "description": "Yearly failure summary grouped by equipment type, make, and model.",
            "query_key": "equipment_failure_annual_report",
            "output_format": "excel",
            "frequency": "annual",
            "group_name": "Failure Register",
            "notification_event": "annual_failure_report_ready",
        },
        {
            "name": "Equipment Failure Performance Analysis",
            "description": "On-demand comparative failure-rate analysis across makes, types, voltage classes, and age bands.",
            "query_key": "equipment_failure_performance_report",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Failure Register",
            "notification_event": None,
        },
        {
            "name": "Failure Resolution Report",
            "description": "End-to-end traceability: each Failure Registry record with outcome and linked work-order status.",
            "query_key": "failure_resolution_report",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Failure Register",
            "notification_event": None,
        },
        # ── Stage Workflows group ─────────────────────────────────────────────────
        {
            "name": "Transformer Repair Status Report",
            "description": "Repair lifecycle stage progress for Power Transformers with % completion and stage breakdown.",
            "query_key": "transformer_repair_status_report",
            "output_format": "excel",
            "frequency": "monthly",
            "group_name": "Stage Workflows",
            "notification_event": "repair_report_ready",
        },
        {
            "name": "Repair Lifecycle Progress",
            "description": "Repair lifecycle requests with session progress",
            "query_key": "repair_progress_report",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Stage Workflows",
            "notification_event": None,
        },
        {
            "name": "Post-Repair Transformer Evaluation",
            "description": "Pre vs post-repair test comparison. Auto-triggered on surveillance completion.",
            "query_key": "post_repair_evaluation_report",
            "output_format": "pdf",
            "frequency": "on_demand",
            "group_name": "Stage Workflows",
            "notification_event": "post_repair_report_ready",
        },
        # ── Preventive Maintenance group ──────────────────────────────────────────
        {
            "name": "PM Compliance Report",
            "description": "Preventive maintenance compliance % vs schedule, grouped by zone and circle.",
            "query_key": "pm_compliance_report",
            "output_format": "excel",
            "frequency": "monthly",
            "group_name": "Preventive Maintenance",
            "notification_event": "pm_report_ready",
        },
        {
            "name": "Maintenance Overdue",
            "description": "Preventive maintenance requests past due date",
            "query_key": "maintenance_overdue_report",
            "output_format": "excel",
            "frequency": "daily",
            "group_name": "Preventive Maintenance",
            "notification_event": None,
        },
        {
            "name": "Remedial Action Pending Report",
            "description": "Pending remedial actions with ageing and action type.",
            "query_key": "open_remediation_report",
            "output_format": "excel",
            "frequency": "monthly",
            "group_name": "Preventive Maintenance",
            "notification_event": "remedial_report_ready",
        },
        {
            "name": "Procurement Pipeline",
            "description": "All procurement requests with status",
            "query_key": "procurement_pipeline_report",
            "output_format": "excel",
            "frequency": "weekly",
            "group_name": "Preventive Maintenance",
            "notification_event": None,
        },
        # ── TA&QC group ──────────────────────────────────────────────────────────
        {
            "name": "TA&QC Observation Compliance Report",
            "description": "TA&QC observation compliance status with ageing.",
            "query_key": "taqc_compliance_report",
            "output_format": "excel",
            "frequency": "monthly",
            "group_name": "TA&QC",
            "notification_event": "taqc_report_ready",
        },
        # ── Vendor & Repairer group ───────────────────────────────────────────────
        {
            "name": "Vendor Performance Ranking Report",
            "description": "Vendor delivery timeliness and quality ranking. "
                           "DISABLED: procurement_requests has no vendor/delivery "
                           "tracking columns — on_demand until schema supports it.",
            "query_key": "vendor_performance_report",
            "output_format": "excel",
            "frequency": "on_demand",
            "group_name": "Vendor & Repairer",
            "notification_event": "vendor_report_ready",
        },
        {
            "name": "Repairer Performance Ranking Report",
            "description": "Workshop / repairer turnaround time and post-repair quality ranking.",
            "query_key": "repairer_performance_report",
            "output_format": "excel",
            "frequency": "annual",
            "group_name": "Vendor & Repairer",
            "notification_event": "repairer_report_ready",
        },
        # ── Equipment Operations group ────────────────────────────────────────────
        {
            "name": "OLTC / CB Operations Count Report",
            "description": "OLTC tap change and CB operation counts vs thresholds.",
            "query_key": "oltc_cb_operations_report",
            "output_format": "excel",
            "frequency": "monthly",
            "group_name": "Equipment Operations",
            "notification_event": "oltc_report_ready",
        },
        # ── KPI / Performance group ───────────────────────────────────────────────
        {
            "name": "Tester Performance",
            "description": "Tester completion rates and average turnaround times",
            "query_key": "tester_performance_report",
            "output_format": "excel",
            "frequency": "monthly",
            "group_name": "KPI & Performance",
            "notification_event": None,
        },
        {
            "name": "Monthly KPI Summary",
            "description": "Monthly aggregated KPIs: requests, completions, alerts, findings",
            "query_key": "monthly_kpi_report",
            "output_format": "excel",
            "frequency": "monthly",
            "group_name": "KPI & Performance",
            "notification_event": None,
        },
    ]

    created = updated = 0
    for d in DEFINITIONS:
        existing = session.query(ReportDefinition).filter_by(
            query_key=d["query_key"]
        ).first()
        if existing:
            # Upsert: refresh group_name + notification_event on existing rows
            existing.group_name         = d.get("group_name")
            existing.notification_event = d.get("notification_event")
            existing.name               = d["name"]          # keep name current
            updated += 1
        else:
            session.add(ReportDefinition(
                name=d["name"],
                description=d["description"],
                query_key=d["query_key"],
                parameters={},
                output_format=d["output_format"],
                frequency=d["frequency"],
                group_name=d.get("group_name"),
                notification_event=d.get("notification_event"),
                recipient_roles=[],
                is_active=True,
                is_system=True,
            ))
            created += 1

    session.commit()
    print(f"[OK] Report definitions seeded: {created} created, {updated} updated.")


def seed_report_query_keys(session):
    """
    Idempotent upsert of all report query keys.

    Each entry carries:
      sql_template  — full parameterised SQL (no Python string formatting).
                      Use {org_clause} where org scoping goes; use :name bind
                      params for every filter.  NULL-safe guards make every
                      filter optional.
      org_alias     — table alias for org scoping, e.g. "tr", "e", "res".
    """
    from models import ReportQueryKey

    # ── SQL helpers reused across queries ─────────────────────────────────────
    # All queries use {org_clause} which the engine replaces at runtime with
    # "AND <alias>.organization_id = :org_id"  (or "" when no org is set).
    # ─────────────────────────────────────────────────────────────────────────

    KEYS = [

        # ══════════════════════════════════════════════════════════════════════
        # Testing Requests
        # ══════════════════════════════════════════════════════════════════════

        dict(
            key="overdue_tests_report",
            label="Overdue Test Report",
            group_name="Testing Requests",
            description="Tests past their due date with days-overdue count.",
            parameters_schema={"date_from": "date", "date_to": "date"},
            sort_order=10,
            org_alias="tr",
            sql_template="""
SELECT
    tr.request_number,
    tr.title,
    tr.zone,
    tr.ce_circle,
    tr.ee_subdivision,
    tr.status,
    tr.priority,
    tr.due_date::date                         AS due_date,
    (NOW()::date - tr.due_date::date)         AS days_overdue,
    e.ueic,
    cm.name                                   AS equipment_type,
    cd.name                                   AS test_type
FROM   public.testing_requests tr
LEFT JOIN public.equipment         e  ON e.id  = tr.equipment_id
LEFT JOIN public."CategoryMaster"  cm ON cm.id = tr.equipment_type_id
LEFT JOIN public."CategoryDetails" cd ON cd.id = tr.test_type_id
WHERE  tr.request_category = 'test'
  AND  tr.due_date IS NOT NULL
  AND  tr.due_date < NOW()
  AND  tr.status IN ('submitted','assigned','accepted','in_progress',
                     'test_submitted','under_approval')
  {org_clause}
  AND  (:date_from::date IS NULL OR tr.due_date >= :date_from::date)
  AND  (:date_to::date   IS NULL OR tr.due_date <= :date_to::date)
ORDER  BY tr.due_date ASC
"""),

        dict(
            key="active_alerts_report",
            label="Active Alerts",
            group_name="Testing Requests",
            description="Test results with CRITICAL or ALERT evaluation.",
            parameters_schema={"severity": "string", "date_from": "date", "date_to": "date"},
            sort_order=20,
            org_alias="res",
            sql_template="""
SELECT
    tr.request_number,
    e.ueic,
    cm.name                                 AS equipment_type,
    tr.zone,
    tr.ee_subdivision,
    res.test_name,
    res.evaluation_result->>'overall'       AS severity,
    res.tested_at,
    u.email                                 AS tested_by
FROM   public.test_results res
JOIN   public.testing_requests   tr ON tr.id  = res.testing_request_id
LEFT JOIN public.equipment        e  ON e.id  = tr.equipment_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
LEFT JOIN public.users            u  ON u.id  = res.tested_by
WHERE  res.evaluation_result IS NOT NULL
  AND  res.evaluation_result->>'overall' IN ('CRITICAL','ALERT')
  AND  (:severity IS NULL OR :severity = 'all'
        OR res.evaluation_result->>'overall' = :severity)
  {org_clause}
  AND  (:date_from::date IS NULL OR res.tested_at >= :date_from::date)
  AND  (:date_to::date   IS NULL OR res.tested_at <= :date_to::date)
ORDER  BY res.tested_at DESC
LIMIT  500
"""),

        dict(
            key="flagged_equipment_report",
            label="ALERT / CRITICAL Equipment Report",
            group_name="Testing Requests",
            description="All ALERT and CRITICAL equipment (deduplicated by UEIC).",
            parameters_schema={},
            sort_order=30,
            org_alias="res",
            sql_template="""
SELECT DISTINCT ON (e.id)
    e.ueic,
    d.name                              AS substation,
    cm.name                             AS equipment_type,
    e.voltage_class,
    res.evaluation_result->>'overall'   AS condition,
    res.tested_at                       AS last_tested_at,
    tr.zone,
    tr.ee_subdivision
FROM   public.test_results res
JOIN   public.testing_requests   tr ON tr.id = res.testing_request_id
JOIN   public.equipment          e  ON e.id  = tr.equipment_id
LEFT JOIN public.org_departments d  ON d.id  = e.department_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
WHERE  res.evaluation_result IS NOT NULL
  AND  res.evaluation_result->>'overall' IN ('CRITICAL','ALERT')
  {org_clause}
ORDER  BY e.id, res.tested_at DESC
"""),

        dict(
            key="compliance_status_report",
            label="Test Compliance Status Report",
            group_name="Testing Requests",
            description="Test compliance % by zone / circle / substation.",
            parameters_schema={"period_days": "int"},
            sort_order=40,
            org_alias="e",
            sql_template="""
SELECT
    d.name                              AS substation,
    tr_agg.zone,
    COUNT(DISTINCT e.id)                AS total_equipment,
    COUNT(DISTINCT CASE
        WHEN latest_tr.completed_at >=
             NOW() - (INTERVAL '1 day' * COALESCE(:period_days, 365))
        THEN e.id END)                  AS tested_in_period,
    ROUND(
        100.0
        * COUNT(DISTINCT CASE
            WHEN latest_tr.completed_at >=
                 NOW() - (INTERVAL '1 day' * COALESCE(:period_days, 365))
            THEN e.id END)
        / NULLIF(COUNT(DISTINCT e.id), 0), 1
    )                                   AS compliance_pct,
    COUNT(DISTINCT CASE
        WHEN latest_res.condition = 'CRITICAL' THEN e.id END) AS critical_count,
    COUNT(DISTINCT CASE
        WHEN latest_res.condition = 'ALERT'    THEN e.id END) AS alert_count
FROM   public.equipment e
LEFT JOIN public.org_departments  d      ON d.id = e.department_id
LEFT JOIN public.testing_requests tr_agg ON tr_agg.equipment_id = e.id
LEFT JOIN LATERAL (
    SELECT completed_at FROM public.testing_requests
    WHERE  equipment_id = e.id AND status = 'completed'
    ORDER  BY completed_at DESC LIMIT 1
) latest_tr ON true
LEFT JOIN LATERAL (
    SELECT res.evaluation_result->>'overall' AS condition
    FROM   public.test_results res
    JOIN   public.testing_requests req ON req.id = res.testing_request_id
    WHERE  req.equipment_id = e.id AND res.evaluation_result IS NOT NULL
    ORDER  BY res.tested_at DESC LIMIT 1
) latest_res ON true
WHERE  e.status = 'active'
{org_clause}
GROUP  BY d.name, tr_agg.zone
ORDER  BY compliance_pct ASC NULLS FIRST
"""),

        dict(
            key="testing_request_status_report",
            label="Testing Request Status",
            group_name="Testing Requests",
            description="All testing requests with current status and assignment.",
            parameters_schema={"date_from": "date", "date_to": "date",
                               "status": "string", "category": "string"},
            sort_order=50,
            org_alias="tr",
            sql_template="""
SELECT
    tr.request_number,
    tr.title,
    tr.request_category,
    tr.status,
    tr.priority,
    tr.zone,
    tr.ce_circle,
    tr.ee_subdivision,
    tr.cts::date          AS created_date,
    tr.due_date::date     AS due_date,
    tr.completed_at::date AS completed_date,
    e.ueic,
    cm.name               AS equipment_type,
    cd.name               AS test_type,
    u_o.email             AS originator,
    u_t.email             AS assigned_tester
FROM   public.testing_requests tr
LEFT JOIN public.equipment         e   ON e.id   = tr.equipment_id
LEFT JOIN public."CategoryMaster"  cm  ON cm.id  = tr.equipment_type_id
LEFT JOIN public."CategoryDetails" cd  ON cd.id  = tr.test_type_id
LEFT JOIN public.users             u_o ON u_o.id = tr.originator_id
LEFT JOIN public.users             u_t ON u_t.id = tr.assigned_tester_id
WHERE  1=1
  {org_clause}
  AND  (:status   IS NULL OR :status   = 'all' OR tr.status            = :status)
  AND  (:category IS NULL OR :category = 'all' OR tr.request_category  = :category)
  AND  (:date_from::date IS NULL OR tr.cts >= :date_from::date)
  AND  (:date_to::date   IS NULL OR tr.cts <= :date_to::date)
ORDER  BY tr.cts DESC
"""),

        dict(
            key="test_results_summary_report",
            label="Test Results Summary",
            group_name="Testing Requests",
            description="Test results with evaluation outcomes.",
            parameters_schema={"date_from": "date", "date_to": "date", "severity": "string"},
            sort_order=60,
            org_alias="res",
            sql_template="""
SELECT
    tr.request_number,
    e.ueic,
    cm.name                                 AS equipment_type,
    res.test_name,
    res.template_key,
    res.overall_result,
    res.evaluation_result->>'overall'       AS evaluation_overall,
    res.pass_fail,
    res.tested_at,
    u.email                                 AS tested_by,
    tr.zone,
    tr.ee_subdivision
FROM   public.test_results res
JOIN   public.testing_requests   tr ON tr.id  = res.testing_request_id
LEFT JOIN public.equipment        e  ON e.id  = tr.equipment_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
LEFT JOIN public.users            u  ON u.id  = res.tested_by
WHERE  1=1
  {org_clause}
  AND  (:severity IS NULL OR :severity = 'all'
        OR res.evaluation_result->>'overall' = :severity)
  AND  (:date_from::date IS NULL OR res.tested_at >= :date_from::date)
  AND  (:date_to::date   IS NULL OR res.tested_at <= :date_to::date)
ORDER  BY res.tested_at DESC
LIMIT  1000
"""),

        dict(
            key="recommendation_approval_report",
            label="Recommendation Approvals",
            group_name="Testing Requests",
            description="Recommendations with approval status and notes.",
            parameters_schema={"status": "string"},
            sort_order=70,
            org_alias="rec",
            sql_template="""
SELECT
    tr.request_number,
    e.ueic,
    cm.name               AS equipment_type,
    rec.recommendation_type,
    rec.approval_status,
    rec.summary,
    rec.cts::date         AS submitted_date,
    rec.approved_at::date AS approved_date,
    rec.approval_notes,
    u_s.email             AS submitted_by,
    u_a.email             AS approved_by
FROM   public.recommendations rec
JOIN   public.testing_requests   tr  ON tr.id   = rec.testing_request_id
LEFT JOIN public.equipment        e   ON e.id   = tr.equipment_id
LEFT JOIN public."CategoryMaster" cm  ON cm.id  = tr.equipment_type_id
LEFT JOIN public.users            u_s ON u_s.id = rec.submitted_by
LEFT JOIN public.users            u_a ON u_a.id = rec.approved_by
WHERE  1=1
  {org_clause}
  AND  (:status IS NULL OR :status = 'all' OR rec.approval_status = :status)
ORDER  BY rec.cts DESC
"""),

        dict(
            key="tester_performance_report",
            label="Tester Performance",
            group_name="Testing Requests",
            description="Tester completion rates and average turnaround times.",
            parameters_schema={"date_from": "date", "date_to": "date"},
            sort_order=80,
            org_alias="tr",
            sql_template="""
SELECT
    u.email                                 AS tester_email,
    TRIM(COALESCE(u.firstname,'') || ' ' || COALESCE(u.lastname,'')) AS tester_name,
    COUNT(tr.id)                            AS total_assigned,
    COUNT(CASE WHEN tr.status='completed'   THEN 1 END) AS completed,
    COUNT(CASE WHEN tr.status='in_progress' THEN 1 END) AS in_progress,
    COUNT(CASE WHEN tr.status='rejected'    THEN 1 END) AS rejected,
    ROUND(AVG(CASE
        WHEN tr.status='completed'
         AND tr.completed_at IS NOT NULL
         AND tr.assigned_at  IS NOT NULL
        THEN EXTRACT(EPOCH FROM (tr.completed_at - tr.assigned_at)) / 86400.0
    END), 1)                                AS avg_days_to_complete
FROM   public.testing_requests tr
JOIN   public.users u ON u.id = tr.assigned_tester_id
WHERE  tr.assigned_tester_id IS NOT NULL
  {org_clause}
  AND  (:date_from::date IS NULL OR tr.cts >= :date_from::date)
  AND  (:date_to::date   IS NULL OR tr.cts <= :date_to::date)
GROUP  BY u.id, u.email, u.firstname, u.lastname
ORDER  BY completed DESC
"""),

        # ══════════════════════════════════════════════════════════════════════
        # Equipment Lifecycle
        # ══════════════════════════════════════════════════════════════════════

        dict(
            key="equipment_condition_summary",
            label="Equipment Condition Summary",
            group_name="Equipment Lifecycle",
            description="All active equipment with latest test condition "
                        "(CRITICAL/ALERT/NORMAL/NOT_TESTED).",
            parameters_schema={},
            sort_order=10,
            org_alias="e",
            sql_template="""
SELECT
    e.ueic,
    d.name                              AS department,
    cm.name                             AS equipment_type,
    e.voltage_class,
    e.status                            AS equipment_status,
    e.manufacturer,
    e.year_of_manufacture,
    COALESCE(lat.evaluation_result->>'overall', 'NOT_TESTED') AS condition,
    lat.tested_at                       AS last_tested_at,
    lat.test_name                       AS last_test_name
FROM   public.equipment e
LEFT JOIN public.org_departments  d  ON d.id  = e.department_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
LEFT JOIN LATERAL (
    SELECT res.evaluation_result, res.tested_at, res.test_name
    FROM   public.test_results res
    JOIN   public.testing_requests req ON req.id = res.testing_request_id
    WHERE  req.equipment_id = e.id AND res.evaluation_result IS NOT NULL
    ORDER  BY res.tested_at DESC NULLS LAST
    LIMIT  1
) lat ON true
WHERE  e.status != 'retired'
{org_clause}
ORDER  BY e.ueic
"""),

        dict(
            key="equipment_inventory_report",
            label="Equipment Inventory Report",
            group_name="Equipment Lifecycle",
            description="Full equipment inventory with zone hierarchy, condition, age, "
                        "and manufacturer.",
            parameters_schema={"equipment_type": "string", "voltage_class": "string",
                               "department_id": "uuid"},
            sort_order=20,
            org_alias="e",
            sql_template="""
SELECT
    e.ueic,
    cm.name                             AS equipment_type,
    e.voltage_class,
    e.manufacturer,
    e.model_number,
    e.factory_serial_number,
    e.year_of_manufacture,
    e.commissioned_date,
    e.status,
    d.name                              AS substation,
    d2.name                             AS ee_subdivision,
    d3.name                             AS ce_circle,
    d4.name                             AS zone,
    COALESCE(lat.evaluation_result->>'overall', 'NOT_TESTED') AS condition
FROM   public.equipment e
LEFT JOIN public.org_departments  d   ON d.id   = e.department_id
LEFT JOIN public.org_departments  d2  ON d2.id  = d.parent_department_id
LEFT JOIN public.org_departments  d3  ON d3.id  = d2.parent_department_id
LEFT JOIN public.org_departments  d4  ON d4.id  = d3.parent_department_id
LEFT JOIN public."CategoryMaster" cm  ON cm.id  = e.equipment_type_id
LEFT JOIN LATERAL (
    SELECT res.evaluation_result
    FROM   public.test_results res
    JOIN   public.testing_requests req ON req.id = res.testing_request_id
    WHERE  req.equipment_id = e.id AND res.evaluation_result IS NOT NULL
    ORDER  BY res.tested_at DESC NULLS LAST LIMIT 1
) lat ON true
WHERE  e.status != 'retired'
  {org_clause}
  AND  (:equipment_type IS NULL
        OR cm.name ILIKE '%' || :equipment_type || '%')
  AND  (:voltage_class  IS NULL OR e.voltage_class  = :voltage_class)
  AND  (:department_id  IS NULL OR e.department_id  = :department_id::uuid)
ORDER  BY d4.name NULLS LAST, d3.name NULLS LAST, d.name, e.ueic
"""),

        dict(
            key="equipment_lifecycle_report",
            label="Equipment Lifecycle Summary",
            group_name="Equipment Lifecycle",
            description="One row per equipment unit: commissioned date, test count, "
                        "failure count, last result.",
            parameters_schema={"status": "string", "voltage_class": "string",
                               "department_id": "uuid",
                               "date_from": "date", "date_to": "date"},
            sort_order=30,
            org_alias="e",
            sql_template="""
SELECT
    e.ueic,
    cm.name                             AS equipment_type,
    e.voltage_class,
    e.manufacturer,
    e.status,
    d.name                              AS department,
    e.commissioned_date,
    COUNT(DISTINCT tr.id)               AS total_tests,
    COUNT(DISTINCT fr.id)               AS total_failures,
    MAX(res.tested_at)                  AS last_tested_at,
    (SELECT res2.evaluation_result->>'overall'
     FROM   public.test_results res2
     JOIN   public.testing_requests req2 ON req2.id = res2.testing_request_id
     WHERE  req2.equipment_id = e.id
     ORDER  BY res2.tested_at DESC LIMIT 1) AS last_result
FROM   public.equipment e
LEFT JOIN public.org_departments  d   ON d.id  = e.department_id
LEFT JOIN public."CategoryMaster" cm  ON cm.id = e.equipment_type_id
LEFT JOIN public.testing_requests tr  ON tr.equipment_id = e.id
LEFT JOIN public.testing_requests fr  ON fr.equipment_id = e.id
                                     AND fr.request_category = 'failure_registry'
LEFT JOIN public.test_results     res ON res.testing_request_id = tr.id
WHERE  1=1
  {org_clause}
  AND  (:status        IS NULL OR e.status        = :status)
  AND  (:voltage_class IS NULL OR e.voltage_class = :voltage_class)
  AND  (:department_id IS NULL OR e.department_id = :department_id::uuid)
  AND  (:date_from::date IS NULL OR e.commissioned_date >= :date_from::date)
  AND  (:date_to::date   IS NULL OR e.commissioned_date <= :date_to::date)
GROUP  BY e.id, e.ueic, cm.name, e.voltage_class, e.manufacturer,
          e.status, d.name, e.commissioned_date
ORDER  BY e.ueic
"""),

        # ══════════════════════════════════════════════════════════════════════
        # Failure Register
        # ══════════════════════════════════════════════════════════════════════

        dict(
            key="equipment_failure_annual_report",
            label="Equipment Failure Annual Report",
            group_name="Failure Register",
            description="Yearly failure summary grouped by equipment type, make, "
                        "and voltage class.",
            parameters_schema={"year": "int"},
            sort_order=10,
            org_alias="tr",
            sql_template="""
SELECT
    cm.name                                              AS equipment_type,
    e.manufacturer                                       AS make,
    e.voltage_class,
    COUNT(tr.id)                                         AS failure_count,
    COUNT(DISTINCT e.id)                                 AS units_affected,
    STRING_AGG(DISTINCT tr.form_data->>'failure_category', ', ') AS failure_categories
FROM   public.testing_requests tr
JOIN   public.equipment        e   ON e.id   = tr.equipment_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
WHERE  tr.request_category = 'failure_registry'
  AND  EXTRACT(YEAR FROM tr.cts)
         = COALESCE(:year, EXTRACT(YEAR FROM NOW())::int - 1)
  {org_clause}
GROUP  BY cm.name, e.manufacturer, e.voltage_class
ORDER  BY failure_count DESC
"""),

        dict(
            key="equipment_failure_performance_report",
            label="Equipment Failure Performance Analysis",
            group_name="Failure Register",
            description="Comparative failure-rate analysis across makes, types, "
                        "voltage classes, and age bands.",
            parameters_schema={"equipment_type": "string", "make": "string",
                               "voltage_class": "string",
                               "date_from": "date", "date_to": "date"},
            sort_order=20,
            org_alias="fr",
            sql_template="""
SELECT
    cm.name                     AS equipment_type,
    e.manufacturer              AS make,
    e.voltage_class,
    CASE
        WHEN (DATE_PART('year', NOW()) - e.year_of_manufacture::int)
             BETWEEN 0  AND 10 THEN '0-10 years'
        WHEN (DATE_PART('year', NOW()) - e.year_of_manufacture::int)
             BETWEEN 11 AND 20 THEN '11-20 years'
        ELSE '>20 years'
    END                         AS age_band,
    COUNT(fr.id)                AS failure_count,
    COUNT(DISTINCT e.id)        AS unit_count,
    ROUND(COUNT(fr.id)::numeric / NULLIF(COUNT(DISTINCT e.id), 0), 2)
                                AS failure_rate_per_unit
FROM   public.testing_requests fr
JOIN   public.equipment        e   ON e.id   = fr.equipment_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
WHERE  fr.request_category = 'failure_registry'
  {org_clause}
  AND  (:date_from::date IS NULL OR fr.cts >= :date_from::date)
  AND  (:date_to::date   IS NULL OR fr.cts <= :date_to::date)
  AND  (:equipment_type  IS NULL
        OR cm.name ILIKE '%' || :equipment_type || '%')
  AND  (:make            IS NULL
        OR e.manufacturer ILIKE '%' || :make || '%')
  AND  (:voltage_class   IS NULL OR e.voltage_class = :voltage_class)
GROUP  BY cm.name, e.manufacturer, e.voltage_class, age_band
ORDER  BY failure_rate_per_unit DESC NULLS LAST
"""),

        dict(
            key="failure_resolution_report",
            label="Failure Resolution Report",
            group_name="Failure Register",
            description="Each Failure Registry record with outcome and linked "
                        "work-order status.",
            parameters_schema={"date_from": "date", "date_to": "date",
                               "outcome": "string"},
            sort_order=30,
            org_alias="fr",
            sql_template="""
SELECT
    fr.request_number           AS fr_number,
    e.ueic                      AS equipment_ueic,
    cm.name                     AS equipment_type,
    fr.form_data->>'failure_category' AS failure_category,
    fr.form_data->>'next_action'      AS resolution_outcome,
    fr.status                   AS approval_status,
    fr.cts::date                AS failure_date,
    wf.status                   AS linked_workflow_status,
    wf.id                       AS linked_workflow_id
FROM   public.testing_requests fr
JOIN   public.equipment        e   ON e.id   = fr.equipment_id
LEFT JOIN public."CategoryMaster"   cm ON cm.id = e.equipment_type_id
LEFT JOIN public.repair_workflows   wf ON wf.source_failure_id = fr.id
WHERE  fr.request_category = 'failure_registry'
  {org_clause}
  AND  (:date_from::date IS NULL OR fr.cts >= :date_from::date)
  AND  (:date_to::date   IS NULL OR fr.cts <= :date_to::date)
  AND  (:outcome IS NULL OR :outcome = 'all'
        OR fr.form_data->>'next_action' = :outcome)
ORDER  BY fr.cts DESC
"""),

        # ══════════════════════════════════════════════════════════════════════
        # Stage Workflows
        # ══════════════════════════════════════════════════════════════════════

        dict(
            key="transformer_repair_status_report",
            label="Transformer Repair Status Report",
            group_name="Stage Workflows",
            description="Repair lifecycle stage progress for Power Transformers "
                        "with % completion.",
            parameters_schema={"date_from": "date", "date_to": "date",
                               "department_id": "uuid"},
            sort_order=10,
            org_alias="wf",
            sql_template="""
SELECT
    e.ueic,
    e.manufacturer,
    e.voltage_class,
    d.name                          AS department,
    wf.id                           AS workflow_id,
    wf.status                       AS workflow_status,
    wf.created_at::date             AS started_date,
    sd.name                         AS current_stage,
    COUNT(si.id) FILTER (WHERE si.status = 'completed') AS stages_done,
    COUNT(si.id)                    AS stages_total,
    ROUND(COALESCE(wf.progress, 0)::numeric, 1) AS pct_complete,
    EXTRACT(DAY FROM NOW() - wf.created_at)::int AS days_elapsed
FROM   public.repair_workflows wf
JOIN   public.equipment          e ON e.id  = wf.equipment_id
LEFT JOIN public.org_departments d ON d.id  = e.department_id
LEFT JOIN public.repair_stage_definitions sd ON sd.id = wf.current_stage_id
LEFT JOIN public.repair_stage_instances   si ON si.workflow_id = wf.id
WHERE  wf.workflow_type = 'repair_lifecycle'
  AND  e.equipment_type_id IN (
           SELECT id FROM public."CategoryMaster"
           WHERE  name ILIKE '%transformer%')
  {org_clause}
  AND  (:date_from::date IS NULL OR wf.created_at >= :date_from::date)
  AND  (:date_to::date   IS NULL OR wf.created_at <= :date_to::date)
  AND  (:department_id   IS NULL OR e.department_id = :department_id::uuid)
GROUP  BY e.ueic, e.manufacturer, e.voltage_class, d.name, wf.id,
          wf.status, wf.created_at, sd.name, wf.progress
ORDER  BY wf.created_at DESC
"""),

        dict(
            key="repair_progress_report",
            label="Repair Lifecycle Progress",
            group_name="Stage Workflows",
            description="Repair lifecycle requests with session progress.",
            parameters_schema={},
            sort_order=20,
            org_alias="tr",
            sql_template="""
SELECT
    tr.request_number,
    e.ueic,
    cm.name                             AS equipment_type,
    tr.title,
    tr.status,
    tr.total_sessions_planned,
    tr.requested_date::date             AS requested_date,
    tr.due_date::date                   AS due_date,
    tr.zone,
    tr.ee_subdivision,
    COUNT(ts.id)                        AS sessions_completed
FROM   public.testing_requests tr
LEFT JOIN public.equipment        e  ON e.id  = tr.equipment_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
LEFT JOIN public.test_sessions    ts
       ON ts.testing_request_id = tr.id AND ts.status = 'completed'
WHERE  tr.request_category = 'repair_lifecycle'
  AND  tr.status IN ('submitted','assigned','accepted','in_progress',
                     'test_submitted','under_approval')
  {org_clause}
GROUP  BY tr.id, e.ueic, cm.name
ORDER  BY tr.cts DESC
"""),

        dict(
            key="post_repair_evaluation_report",
            label="Post-Repair Transformer Evaluation",
            group_name="Stage Workflows",
            description="Pre vs post-repair test comparison for surveillance-completed "
                        "workflows.",
            parameters_schema={"workflow_id": "uuid",
                               "date_from": "date", "date_to": "date"},
            sort_order=30,
            org_alias="wf",
            sql_template="""
SELECT
    e.ueic,
    e.manufacturer,
    e.voltage_class,
    d.name                              AS department,
    wf.id                               AS workflow_id,
    wf.completed_at::date               AS completion_date,
    pre.evaluation_result ->>'overall'  AS pre_repair_result,
    post.evaluation_result->>'overall'  AS post_repair_result,
    pre.tested_at                       AS pre_repair_tested_at,
    post.tested_at                      AS post_repair_tested_at
FROM   public.repair_workflows wf
JOIN   public.equipment          e  ON e.id  = wf.equipment_id
LEFT JOIN public.org_departments d  ON d.id  = e.department_id
LEFT JOIN LATERAL (
    SELECT res.evaluation_result, res.tested_at
    FROM   public.test_results res
    JOIN   public.testing_requests req ON req.id = res.testing_request_id
    WHERE  req.equipment_id = e.id AND res.tested_at < wf.created_at
    ORDER  BY res.tested_at DESC LIMIT 1
) pre  ON true
LEFT JOIN LATERAL (
    SELECT res.evaluation_result, res.tested_at
    FROM   public.test_results res
    JOIN   public.testing_requests req ON req.id = res.testing_request_id
    WHERE  req.equipment_id = e.id
      AND  req.surveillance_workflow_id IS NOT NULL
      AND  res.tested_at    > wf.completed_at
    ORDER  BY res.tested_at ASC LIMIT 1
) post ON true
WHERE  wf.workflow_type  = 'repair_lifecycle'
  AND  wf.completed_at IS NOT NULL
  {org_clause}
  AND  (:workflow_id IS NULL OR wf.id = :workflow_id::uuid)
  AND  (:date_from::date IS NULL OR wf.completed_at >= :date_from::date)
  AND  (:date_to::date   IS NULL OR wf.completed_at <= :date_to::date)
ORDER  BY wf.completed_at DESC
"""),

        # ══════════════════════════════════════════════════════════════════════
        # Preventive Maintenance
        # ══════════════════════════════════════════════════════════════════════

        dict(
            key="pm_compliance_report",
            label="PM Compliance Report",
            group_name="Preventive Maintenance",
            description="Preventive maintenance compliance % vs schedule, "
                        "grouped by zone and circle.",
            parameters_schema={"month": "int", "year": "int", "department_id": "uuid"},
            sort_order=10,
            org_alias="tr",
            sql_template="""
SELECT
    d4.name                         AS zone,
    d3.name                         AS ce_circle,
    d2.name                         AS ee_subdivision,
    d.name                          AS substation,
    COUNT(tr.id)                    AS scheduled,
    COUNT(CASE WHEN tr.status = 'completed' THEN 1 END) AS completed,
    ROUND(
        COUNT(CASE WHEN tr.status = 'completed' THEN 1 END)::numeric
        / NULLIF(COUNT(tr.id), 0) * 100, 1
    )                               AS compliance_pct
FROM   public.testing_requests tr
JOIN   public.equipment          e  ON e.id   = tr.equipment_id
LEFT JOIN public.org_departments d  ON d.id   = e.department_id
LEFT JOIN public.org_departments d2 ON d2.id  = d.parent_department_id
LEFT JOIN public.org_departments d3 ON d3.id  = d2.parent_department_id
LEFT JOIN public.org_departments d4 ON d4.id  = d3.parent_department_id
WHERE  tr.request_category = 'maintenance'
  AND  EXTRACT(MONTH FROM tr.due_date)
         = COALESCE(:month, EXTRACT(MONTH FROM NOW()))
  AND  EXTRACT(YEAR  FROM tr.due_date)
         = COALESCE(:year,  EXTRACT(YEAR  FROM NOW()))
  {org_clause}
  AND  (:department_id IS NULL OR d.id = :department_id::uuid)
GROUP  BY d4.name, d3.name, d2.name, d.name
ORDER  BY zone NULLS LAST, ce_circle NULLS LAST,
          ee_subdivision NULLS LAST, d.name
"""),

        dict(
            key="maintenance_overdue_report",
            label="Maintenance Overdue",
            group_name="Preventive Maintenance",
            description="Preventive maintenance requests past due date.",
            parameters_schema={},
            sort_order=20,
            org_alias="tr",
            sql_template="""
SELECT
    tr.request_number,
    tr.title,
    tr.zone,
    tr.ee_subdivision,
    tr.status,
    tr.due_date::date                         AS due_date,
    (NOW()::date - tr.due_date::date)         AS days_overdue,
    e.ueic,
    cm.name                                   AS equipment_type
FROM   public.testing_requests tr
LEFT JOIN public.equipment        e  ON e.id  = tr.equipment_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
WHERE  tr.request_category = 'maintenance'
  AND  tr.due_date IS NOT NULL
  AND  tr.due_date < NOW()
  AND  tr.status IN ('submitted','assigned','accepted','in_progress',
                     'test_submitted','under_approval')
  {org_clause}
ORDER  BY tr.due_date ASC
"""),

        dict(
            key="open_remediation_report",
            label="Remedial Action Pending Report",
            group_name="Preventive Maintenance",
            description="Pending remedial actions with ageing and action type.",
            parameters_schema={},
            sort_order=30,
            org_alias="rec",
            sql_template="""
SELECT
    tr.request_number,
    e.ueic,
    cm.name                                 AS equipment_type,
    rec.recommendation_type,
    rec.approval_status,
    rec.summary,
    rec.cts::date                           AS raised_date,
    (NOW()::date - rec.cts::date)           AS days_open,
    u.email                                 AS submitted_by,
    tr.due_date::date                       AS due_date
FROM   public.recommendations rec
JOIN   public.testing_requests   tr ON tr.id  = rec.testing_request_id
LEFT JOIN public.equipment        e  ON e.id  = tr.equipment_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
LEFT JOIN public.users            u  ON u.id  = rec.submitted_by
WHERE  rec.approval_status = 'pending'
  {org_clause}
ORDER  BY rec.cts ASC
"""),

        dict(
            key="procurement_pipeline_report",
            label="Procurement Pipeline",
            group_name="Preventive Maintenance",
            description="All procurement requests with status.",
            parameters_schema={"status": "string"},
            sort_order=40,
            org_alias="pr",
            sql_template="""
SELECT
    pr.procurement_number,
    pr.title,
    pr.status,
    pr.estimated_cost,
    pr.quantity,
    pr.raised_at::date  AS raised_date,
    tr.request_number   AS linked_request,
    u.email             AS raised_by
FROM   public.procurement_requests pr
LEFT JOIN public.testing_requests tr ON tr.id = pr.testing_request_id
LEFT JOIN public.users            u  ON u.id  = pr.raised_by
WHERE  1=1
  {org_clause}
  AND  (:status IS NULL OR :status = 'all' OR pr.status = :status)
ORDER  BY pr.raised_at DESC
"""),

        # ══════════════════════════════════════════════════════════════════════
        # TA&QC
        # ══════════════════════════════════════════════════════════════════════

        dict(
            key="taqc_compliance_report",
            label="TA&QC Observation Compliance Report",
            group_name="TA&QC",
            description="TA&QC observation compliance status with ageing.",
            parameters_schema={"month": "int", "year": "int", "department_id": "uuid"},
            sort_order=10,
            org_alias="tai",
            sql_template="""
SELECT
    d.name                          AS department,
    cd.name                         AS observation_category,
    COUNT(ti.id)                    AS total_observations,
    COUNT(CASE WHEN ti.current_stage_code ILIKE '%clos%' THEN 1 END) AS closed,
    COUNT(CASE WHEN ti.current_stage_code NOT ILIKE '%clos%'
                 OR ti.current_stage_code IS NULL THEN 1 END)        AS open,
    ROUND(
        COUNT(CASE WHEN ti.current_stage_code ILIKE '%clos%' THEN 1 END)::numeric
        / NULLIF(COUNT(ti.id), 0) * 100, 1
    )                               AS compliance_pct,
    MAX(EXTRACT(DAY FROM NOW() - ti.cts))::int AS max_age_days
FROM   public.taqc_observations ti
JOIN   public.taqc_annual_inspections tai ON tai.id = ti.inspection_id
LEFT JOIN public.org_departments d  ON d.id  = tai.department_id
LEFT JOIN public."CategoryDetails" cd ON cd.id = ti.category_detail_id
WHERE  EXTRACT(MONTH FROM ti.cts)
         = COALESCE(:month, EXTRACT(MONTH FROM NOW()))
  AND  EXTRACT(YEAR  FROM ti.cts)
         = COALESCE(:year,  EXTRACT(YEAR  FROM NOW()))
  {org_clause}
  AND  (:department_id IS NULL OR tai.department_id = :department_id::uuid)
GROUP  BY d.name, cd.name
ORDER  BY compliance_pct ASC NULLS LAST
"""),

        # ══════════════════════════════════════════════════════════════════════
        # Vendor & Repairer
        # ══════════════════════════════════════════════════════════════════════

        dict(
            key="vendor_performance_report",
            label="Vendor Performance Ranking Report",
            group_name="Vendor & Repairer",
            description="Vendor delivery timeliness and quality ranking.",
            parameters_schema={"quarter": "int", "year": "int"},
            sort_order=10,
            org_alias="pr",
            sql_template="""
SELECT
    pr.vendor_name,
    COUNT(pr.id)                        AS total_orders,
    COUNT(CASE WHEN pr.decision = 'approved' THEN 1 END) AS approved,
    COUNT(CASE WHEN pr.decision = 'rejected' THEN 1 END) AS rejected,
    ROUND(
        AVG(EXTRACT(DAY FROM pr.decision_date - pr.cts)), 1
    )                                   AS avg_days_to_decision,
    COUNT(CASE
        WHEN pr.decision = 'approved'
         AND pr.delivery_date <= pr.expected_delivery_date
        THEN 1 END)                     AS on_time_deliveries,
    ROUND(
        COUNT(CASE
            WHEN pr.decision = 'approved'
             AND pr.delivery_date <= pr.expected_delivery_date
            THEN 1 END)::numeric
        / NULLIF(COUNT(CASE WHEN pr.decision = 'approved' THEN 1 END), 0)
        * 100, 1
    )                                   AS on_time_pct
FROM   public.procurement_requests pr
WHERE  EXTRACT(QUARTER FROM pr.cts)
         = COALESCE(:quarter, EXTRACT(QUARTER FROM NOW()))
  AND  EXTRACT(YEAR FROM pr.cts)
         = COALESCE(:year, EXTRACT(YEAR FROM NOW()))
  AND  pr.vendor_name IS NOT NULL
  {org_clause}
GROUP  BY pr.vendor_name
ORDER  BY on_time_pct DESC NULLS LAST
"""),

        dict(
            key="repairer_performance_report",
            label="Repairer Performance Ranking Report",
            group_name="Vendor & Repairer",
            description="Workshop / repairer turnaround time and post-repair quality "
                        "ranking.",
            parameters_schema={"year": "int"},
            sort_order=20,
            org_alias="wf",
            sql_template="""
SELECT
    wf.vendor_name                      AS repairer_name,
    COUNT(wf.id)                        AS total_workflows,
    COUNT(CASE WHEN wf.status = 'completed' THEN 1 END) AS completed,
    ROUND(
        AVG(EXTRACT(DAY FROM wf.completed_at - wf.created_at))
        FILTER (WHERE wf.completed_at IS NOT NULL), 1
    )                                   AS avg_turnaround_days
FROM   public.repair_workflows wf
WHERE  wf.workflow_type  = 'repair_lifecycle'
  AND  EXTRACT(YEAR FROM wf.created_at)
         = COALESCE(:year, EXTRACT(YEAR FROM NOW())::int - 1)
  AND  wf.vendor_name IS NOT NULL
  {org_clause}
GROUP  BY wf.vendor_name
ORDER  BY avg_turnaround_days ASC NULLS LAST
"""),

        # ══════════════════════════════════════════════════════════════════════
        # Equipment Operations
        # ══════════════════════════════════════════════════════════════════════

        dict(
            key="oltc_cb_operations_report",
            label="OLTC / CB Operations Count Report",
            group_name="Equipment Operations",
            description="OLTC tap change and CB operation counts vs thresholds.",
            parameters_schema={"department_id": "uuid"},
            sort_order=10,
            org_alias="e",
            sql_template="""
SELECT
    e.ueic,
    cm.name                         AS equipment_type,
    d.name                          AS department,
    e.manufacturer,
    e.voltage_class,
    COALESCE((e.nameplate_data->>'oltc_tap_count')::int,     0)     AS oltc_tap_count,
    COALESCE((e.nameplate_data->>'cb_operation_count')::int, 0)     AS cb_operation_count,
    COALESCE((e.nameplate_data->>'oltc_threshold')::int,     50000) AS oltc_threshold,
    COALESCE((e.nameplate_data->>'cb_threshold')::int,       2000)  AS cb_threshold,
    CASE
        WHEN COALESCE((e.nameplate_data->>'oltc_tap_count')::int, 0)
             >= COALESCE((e.nameplate_data->>'oltc_threshold')::int, 50000)
        THEN 'EXCEEDED' ELSE 'OK'
    END                             AS oltc_status,
    CASE
        WHEN COALESCE((e.nameplate_data->>'cb_operation_count')::int, 0)
             >= COALESCE((e.nameplate_data->>'cb_threshold')::int, 2000)
        THEN 'EXCEEDED' ELSE 'OK'
    END                             AS cb_status
FROM   public.equipment e
LEFT JOIN public.org_departments  d  ON d.id  = e.department_id
LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
WHERE  e.status != 'retired'
  AND  cm.name ILIKE ANY(ARRAY['%transformer%','%circuit breaker%','%oltc%'])
  {org_clause}
  AND  (:department_id IS NULL OR e.department_id = :department_id::uuid)
ORDER  BY e.ueic
"""),

        # ══════════════════════════════════════════════════════════════════════
        # KPI & Performance
        # ══════════════════════════════════════════════════════════════════════

        dict(
            key="monthly_kpi_report",
            label="Monthly KPI Summary",
            group_name="KPI & Performance",
            description="Monthly aggregated KPIs: requests, completions, alerts, "
                        "findings.",
            parameters_schema={"months": "int"},
            sort_order=10,
            org_alias="tr",
            sql_template="""
SELECT
    TO_CHAR(DATE_TRUNC('month', tr.cts), 'YYYY-MM') AS month,
    COUNT(tr.id)                                      AS requests_raised,
    COUNT(CASE WHEN tr.status='completed' THEN 1 END) AS completed,
    COUNT(CASE
        WHEN tr.status IN ('submitted','assigned','accepted','in_progress',
                           'test_submitted','under_approval')
         AND tr.due_date IS NOT NULL
         AND tr.due_date < NOW() THEN 1 END)          AS overdue,
    COUNT(DISTINCT CASE
        WHEN res.evaluation_result->>'overall' = 'CRITICAL'
        THEN res.id END)                              AS critical_findings,
    COUNT(DISTINCT CASE
        WHEN res.evaluation_result->>'overall' = 'ALERT'
        THEN res.id END)                              AS alert_findings,
    COUNT(DISTINCT rec.id)                            AS recommendations_raised,
    COUNT(DISTINCT CASE
        WHEN rec.approval_status = 'approved'
        THEN rec.id END)                              AS recommendations_approved
FROM   public.testing_requests tr
LEFT JOIN public.test_results    res ON res.testing_request_id = tr.id
LEFT JOIN public.recommendations rec ON rec.testing_request_id = tr.id
WHERE  tr.cts >= NOW() - (INTERVAL '1 month' * COALESCE(:months, 12))
  {org_clause}
GROUP  BY DATE_TRUNC('month', tr.cts)
ORDER  BY month DESC
"""),

    ]  # end KEYS

    inserted = updated = 0
    for entry in KEYS:
        key = entry["key"]
        existing = session.query(ReportQueryKey).filter_by(key=key).first()
        if existing:
            existing.label             = entry["label"]
            existing.group_name        = entry["group_name"]
            existing.description       = entry["description"]
            existing.parameters_schema = entry["parameters_schema"]
            existing.sort_order        = entry["sort_order"]
            existing.sql_template      = entry["sql_template"].strip()
            existing.org_alias         = entry["org_alias"]
            updated += 1
        else:
            session.add(ReportQueryKey(
                key              = key,
                label            = entry["label"],
                group_name       = entry["group_name"],
                description      = entry["description"],
                parameters_schema= entry["parameters_schema"],
                sort_order       = entry["sort_order"],
                sql_template     = entry["sql_template"].strip(),
                org_alias        = entry["org_alias"],
                is_active        = True,
                is_system        = True,
            ))
            inserted += 1

    session.commit()
    print(f"[OK] Report query keys: {inserted} inserted, {updated} updated.")


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
    # removed — test register templates are created via the UI, not seeded
    pass


def seed_default_test_register(session, org):
    # removed — test register templates are created via the UI, not seeded
    pass


# ============================================================
# MASTER SCHEDULE SEED
# Creates TestRequestSchedule master rows (equipment_id=NULL)
# for representative test types across all 6 equipment types.
# Idempotent — skips if (org, equipment_type_id, test_type_id) exists.
# ============================================================

_MASTER_SCHEDULE_SEED = {
    # equipment_type_name: [(test_detail_name, frequency, advance_days, oem_ref)]
    "Power Transformer": [
        ("Ratio Test HV-LV",                          "yearly",     30, "IEC 60076-1"),
        ("Capacitance & Tan Delta Test (Transformer)", "triennial",  45, "IEC 60137"),
        ("Magnetic Balance Test HV",                  "yearly",     30, None),
    ],
    "Circuit Breaker": [
        ("Contact Resistance Test",  "yearly",    30, "IEC 62271-100"),
        ("Insulation Resistance Test", "yearly",  30, None),
        ("Travel and Timing Test",   "triennial", 45, "IEC 62271-100"),
    ],
    "Protection Relay": [
        ("Protection Relay Functional Test", "yearly", 30, "IEC 60255"),
    ],
    "Electronic Tri-vector Meter": [
        ("Meter Testing", "yearly", 30, "IS 16444"),
    ],
    "Surge Arrestor": [
        ("Insulation Resistance / Leakage Current Test", "yearly",    30, "IEC 60099-4"),
        ("V-I Characteristic Test",                      "triennial", 45, "IEC 60099-4"),
    ],
    "Battery Set": [
        ("Specific Gravity Check",    "quarterly", 15, None),
        ("Discharge / Capacity Test", "yearly",    30, "IEEE 450"),
        ("Float Voltage per Cell",    "quarterly", 15, None),
    ],
}


def seed_schedule_module_permissions(session):
    """
    Ensure 'Test Schedule Templates' and 'Maintenance Schedule Templates' modules
    exist and all is_org_admin OrgRoles across every organisation have full access
    to both. Idempotent.
    """
    MODULE_NAMES = ["Test Schedule Templates", "Maintenance Schedule Templates"]
    total_granted = 0

    admin_roles = session.query(OrgRole).filter_by(is_org_admin=True, is_active=True).all()

    for mod_name in MODULE_NAMES:
        mod = session.query(Module).filter_by(name=mod_name).first()
        if not mod:
            print(f"[WARN] '{mod_name}' module not found — run seed_modules first.")
            continue

        granted = 0
        for role in admin_roles:
            existing = (
                session.query(OrgRolePermission)
                .filter_by(org_role_id=role.id, module_id=mod.id)
                .first()
            )
            if existing:
                existing.can_view = existing.can_add = existing.can_edit = True
                existing.can_delete = existing.can_approve = existing.can_assign = True
                existing.can_export = existing.can_import = True
            else:
                session.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mod.id,
                    can_view=True, can_add=True, can_edit=True,
                    can_delete=True, can_approve=True, can_assign=True,
                    can_export=True, can_import=True,
                ))
                granted += 1
        total_granted += granted
        print(f"[OK] {mod_name}: full access granted/updated for {len(admin_roles)} org-admin role(s) ({granted} new).")

    session.commit()
    return total_granted


def seed_schedule_compliance_module_permissions(session, org=None):
    """
    Grant 'Test Schedules' module access to OrgRoles belonging to *org*.
    This module is KPTCL-specific — pass the KPTCL Organization object.
    Idempotent — inserts missing rows and updates existing ones.

    Access matrix:
      is_org_admin roles              → full access (all flags)
      Named field / supervisory roles → can_view only
    """
    mod = session.query(Module).filter_by(name="Test Schedules").first()
    if not mod:
        print("[WARN] 'Test Schedules' module not found — run seed_modules first.")
        return 0

    if org is None:
        # Fall back to KPTCL by display_name so the function is safe to call standalone
        org = session.query(Organization).filter_by(display_name="KPTCL").first()
    if org is None:
        print("[WARN] seed_schedule_compliance_module_permissions: KPTCL org not found — skipped.")
        return 0

    # Roles that get can_view only (read-only compliance tracker)
    READONLY_ROLE_NAMES = {
        # New functional roles
        "System Administrator",
        "Asset Data Officer",
        "Maintenance Officer",
        "Test Engineer",
        "Test & Work Coordinator",
        "Reviewing Officer",
        "Supervisory Officer",
        "Senior Management Approver",
        "TA&QC Inspector",
        "Transformer Repair Coordinator",
        "Procurement Officer",
        "Procurement Approver",
        "AI / Analytics User",
        "Read-Only Auditor / MIS User",
        "Admin",
    }

    # Only roles belonging to the KPTCL org
    kptcl_roles = (
        session.query(OrgRole)
        .filter(OrgRole.organization_id == org.id, OrgRole.is_active.is_(True))
        .all()
    )

    granted = 0
    for role in kptcl_roles:
        is_admin = role.is_org_admin
        is_named = role.name in READONLY_ROLE_NAMES
        if not is_admin and not is_named:
            continue  # skip roles that shouldn't see this module

        existing = (
            session.query(OrgRolePermission)
            .filter_by(org_role_id=role.id, module_id=mod.id)
            .first()
        )

        if is_admin:
            # Full access for org-admin roles
            if existing:
                existing.can_view = existing.can_add = existing.can_edit = True
                existing.can_delete = existing.can_approve = existing.can_assign = True
                existing.can_export = existing.can_import = True
            else:
                session.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mod.id,
                    can_view=True, can_add=True, can_edit=True,
                    can_delete=True, can_approve=True, can_assign=True,
                    can_export=True, can_import=True,
                ))
                granted += 1
        else:
            # Read-only for field / supervisory roles
            if existing:
                existing.can_view = True  # ensure can_view is set at minimum
            else:
                session.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=mod.id,
                    can_view=True, can_add=False, can_edit=False,
                    can_delete=False, can_approve=False, can_assign=False,
                    can_export=False, can_import=False,
                ))
                granted += 1

    session.commit()
    print(
        f"[OK] Test Schedules (KPTCL): permissions seeded for {len(kptcl_roles)} role(s) "
        f"in org '{org.display_name}' ({granted} new rows inserted)."
    )
    return granted


def seed_approval_role_permissions(session):
    """
    Ensure 'Technical Approver' and 'Org Admin' roles have can_view + can_approve
    on the 'Approvals' and 'Testing Request Approvals' modules across every org.

    Idempotent — inserts missing rows and updates existing ones so re-running
    seed.py always brings permissions to the correct state.

    Equivalent to running this SQL once per org:
        INSERT INTO public.org_role_permissions
            (id, org_role_id, module_id,
             can_view, can_add, can_edit, can_delete,
             can_approve, can_assign, can_export, can_import)
        VALUES
            (gen_random_uuid(), '<tech_approver_role_id>', <approvals_mod_id>,
             true, false, false, false, true, true, true, false),
            (gen_random_uuid(), '<tech_approver_role_id>', <tr_approvals_mod_id>,
             true, false, false, false, true, true, true, false),
            (gen_random_uuid(), '<org_admin_role_id>',    <approvals_mod_id>,
             true, false, false, false, true, true, true, false),
            (gen_random_uuid(), '<org_admin_role_id>',    <tr_approvals_mod_id>,
             true, false, false, false, true, true, true, false)
        ON CONFLICT (org_role_id, module_id) DO NOTHING;
    """
    approvals_mod = session.query(Module).filter_by(path="approvals", is_active=True).first()
    tr_approvals_mod = session.query(Module).filter_by(path="testing_request_approvals", is_active=True).first()

    if not approvals_mod:
        print("[WARN] seed_approval_role_permissions: 'Approvals' module not found — skipping")
        return 0
    if not tr_approvals_mod:
        print("[WARN] seed_approval_role_permissions: 'Testing Request Approvals' module not found — skipping")
        return 0

    target_role_names = ["Reviewing Officer", "System Administrator"]
    target_modules = [approvals_mod, tr_approvals_mod]

    inserted = 0
    updated = 0

    for role_name in target_role_names:
        roles = session.query(OrgRole).filter_by(name=role_name, is_active=True).all()
        for role in roles:
            for mod in target_modules:
                existing = (
                    session.query(OrgRolePermission)
                    .filter_by(org_role_id=role.id, module_id=mod.id)
                    .first()
                )
                if existing:
                    # Ensure correct values even if row was created without approve
                    changed = False
                    if not existing.can_view:
                        existing.can_view = True; changed = True
                    if not existing.can_approve:
                        existing.can_approve = True; changed = True
                    if changed:
                        updated += 1
                else:
                    session.add(OrgRolePermission(
                        id=uuid.uuid4(),
                        org_role_id=role.id,
                        module_id=mod.id,
                        can_view=True,
                        can_add=False,
                        can_edit=False,
                        can_delete=False,
                        can_approve=True,
                        can_assign=True,
                        can_export=True,
                        can_import=False,
                    ))
                    inserted += 1
                    print(
                        f"  [+] Granted: {role_name} "
                        f"(org={role.organization_id}) → {mod.name}"
                    )

    session.commit()
    print(
        f"[OK] Approval role permissions: "
        f"{inserted} row(s) inserted, {updated} row(s) updated "
        f"across {len(target_role_names)} role name(s)."
    )
    return inserted


def seed_missing_role_permissions(session, org=None):
    """
    Backfill OrgRolePermission rows for roles that have no template
    or had a name mismatch in _DFT_ROLES vs seed_role_templates.

    Targets (KPTCL org or all orgs if org=None):
      Finance Approver  → Procurement Approvals (approve) + Dashboard (view)
      TA&QC Officer     → TA&QC Inspections (readwrite) + Failure Registry (view) + Dashboard (view)
      Tester            → Testing Requests (view) + Testing (readwrite) + Equipment (view)
      Section Head      → Testing Requests (view) + Failure Registry (view) +
                          Recommendations (view) + Dashboard (view)
      Dept Head         → Recommendations (approve) + Approvals (approve) +
                          Equipment (view) + Repair Workflows (approve)

    Idempotent — inserts missing rows, updates existing ones.
    """
    def _get_mod(name):
        return session.query(Module).filter_by(name=name, is_active=True).first()

    mods = {
        "Procurement Approvals":    _get_mod("Procurement Approvals"),
        "TA&QC Inspections":        _get_mod("TA&QC Inspections"),
        "Failure Registry":         _get_mod("Failure Registry"),
        "Dashboard":                _get_mod("Dashboard"),
        "Testing Requests":         _get_mod("Testing Requests"),
        "Testing":                  _get_mod("Testing"),
        "Equipment":                _get_mod("Equipment"),
        "Recommendations":          _get_mod("Recommendations"),
        "Approvals":                _get_mod("Approvals"),
        "Breakdown Workflows":      _get_mod("Breakdown Workflows"),
        "Calibration Workflows":    _get_mod("Calibration Workflows"),
        "Annual Audit Workflows":   _get_mod("Annual Audit Workflows"),
        "Surveillance Workflows":   _get_mod("Surveillance Workflows"),
        "Surveillance Dashboard":   _get_mod("Surveillance Dashboard"),
    }
    missing_mods = [k for k, v in mods.items() if v is None]
    if missing_mods:
        print(f"[WARN] seed_missing_role_permissions: modules not found: {missing_mods}")

    # permission_sets: role_name → list of (module_name, can_view, can_add, can_edit, can_approve, can_assign, can_export)
    ROLE_PERMS = {
        "Procurement Approver": [
            ("Procurement Approvals", True, False, False, True,  True,  True),
            ("Dashboard",             True, False, False, False, False, False),
        ],
        "TA&QC Inspector": [
            ("TA&QC Inspections",       True, True,  True,  False, False, True),
            ("Annual Audit Workflows",  True, True,  True,  False, False, True),
            ("Failure Registry",        True, False, False, False, False, False),
            ("Dashboard",               True, False, False, False, False, False),
        ],
        "Test Engineer": [
            ("Testing Requests", True, False, False, False, False, False),
            ("Testing",          True, True,  True,  False, False, True),
            ("Equipment",        True, False, False, False, False, False),
            ("Surveillance Workflows",   True, True,  True,  False, False, False),
            ("Surveillance Dashboard",   True, False, False, False, False, False),
        ],
        "Reviewing Officer": [
            ("Recommendations",       True, False, False, True, True, True),
            ("Approvals",             True, False, False, True, True, True),
            ("Equipment",             True, False, False, False, False, False),
            ("Breakdown Workflows",      True, False, False, True, True, True),
            ("Calibration Workflows",    True, False, False, True, True, True),
            ("Annual Audit Workflows",   True, False, False, True, True, True),
            ("Surveillance Workflows",   True, True,  True,  True, True, True),
            ("Surveillance Dashboard",   True, False, False, False, False, True),
            ("Testing Requests",         True, False, False, False, False, False),
            ("Failure Registry",      True, False, False, False, False, False),
            ("Dashboard",             True, False, False, False, False, False),
        ],
    }

    # Scope to one org or all orgs
    role_filter = {}
    if org is not None:
        role_filter["organization_id"] = org.id

    inserted = 0
    for role_name, perm_list in ROLE_PERMS.items():
        roles = session.query(OrgRole).filter_by(name=role_name, is_active=True, **role_filter).all()
        for role in roles:
            for (mod_name, cv, ca, ce, capr, cass, cexp) in perm_list:
                mod = mods.get(mod_name)
                if mod is None:
                    continue
                existing = (
                    session.query(OrgRolePermission)
                    .filter_by(org_role_id=role.id, module_id=mod.id)
                    .first()
                )
                if existing:
                    existing.can_view    = cv
                    existing.can_add     = ca
                    existing.can_edit    = ce
                    existing.can_approve = capr
                    existing.can_assign  = cass
                    existing.can_export  = cexp
                else:
                    session.add(OrgRolePermission(
                        id=uuid.uuid4(),
                        org_role_id=role.id,
                        module_id=mod.id,
                        can_view=cv, can_add=ca, can_edit=ce,
                        can_delete=False, can_approve=capr,
                        can_assign=cass, can_export=cexp, can_import=False,
                    ))
                    inserted += 1

    session.commit()
    scope = f"org '{org.display_name}'" if org else "all orgs"
    print(f"[OK] Missing role permissions backfilled for {scope}: {inserted} new row(s) inserted.")
    return inserted


def seed_master_schedules(session, org):
    """Create master TestRequestSchedule rows for all 6 equipment types."""
    from datetime import timezone
    from dateutil.relativedelta import relativedelta

    _FREQ_DELTA = {
        "daily":       timedelta(days=1),
        "weekly":      timedelta(weeks=1),
        "biweekly":    timedelta(weeks=2),
        "monthly":     relativedelta(months=1),
        "quarterly":   relativedelta(months=3),
        "semi_annual": relativedelta(months=6),
        "yearly":      relativedelta(years=1),
        "triennial":   relativedelta(years=3),
    }

    now = datetime.now(timezone.utc)
    inserted = 0
    skipped = 0

    for eq_type_name, tests in _MASTER_SCHEDULE_SEED.items():
        master = (
            session.query(CategoryMaster)
            .filter_by(name=eq_type_name)
            .first()
        )
        if not master:
            print(f"  [WARN] Equipment type not found: {eq_type_name!r} — skipping")
            continue

        for detail_name, freq_str, adv_days, oem_ref in tests:
            detail = (
                session.query(CategoryDetails)
                .filter_by(category_master_id=master.id, name=detail_name)
                .first()
            )
            if not detail:
                print(f"  [WARN] Test detail not found: {detail_name!r} under {eq_type_name!r} — skipping")
                continue

            existing = (
                session.query(TestRequestSchedule)
                .filter(
                    TestRequestSchedule.equipment_id.is_(None),
                    TestRequestSchedule.organization_id == org.id,
                    TestRequestSchedule.equipment_type_id == master.id,
                    TestRequestSchedule.test_type_id == detail.id,
                    TestRequestSchedule.is_deleted == False,
                )
                .first()
            )
            if existing:
                skipped += 1
                continue

            sched = TestRequestSchedule(
                organization_id=org.id,
                equipment_type_id=master.id,
                test_type_id=detail.id,
                equipment_id=None,
                title=detail_name,
                frequency=ScheduleFrequency(freq_str),
                advance_days=adv_days,
                oem_reference=oem_ref,
                start_date=now,
                next_run_date=now + _FREQ_DELTA[freq_str],
                is_active=True,
                is_deleted=False,
            )
            session.add(sched)
            inserted += 1

    session.commit()
    print(f"[OK] Master schedules: {inserted} inserted, {skipped} already exist.")
    return inserted


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


def seed_taqc_inspection_test_type(session) -> int:
    """
    Idempotently seed a CategoryMaster "Inspection Types" and a
    CategoryDetails "Annual TA&QC Inspection" row.
    Returns the CategoryDetails.id (used as test_type_id in TAQC schedules).
    """
    master = session.query(CategoryMaster).filter_by(name="Inspection Types").first()
    if not master:
        master = CategoryMaster(
            name="Inspection Types",
            description="Types of periodic site and equipment inspections.",
            is_active=True,
        )
        session.add(master)
        session.flush()
        print("[OK] CategoryMaster 'Inspection Types' created")

    detail = _get_or_create_category_detail(
        session,
        name="Annual TA&QC Inspection",
        category_master_id=master.id,
        description="Annual TA&QC substation inspection (site-level, periodic).",
        is_active=True
    )
    print(f"[OK] CategoryDetails 'Annual TA&QC Inspection' ready id={detail.id}")

    session.commit()
    return detail.id


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
        detail = _get_or_create_category_detail(
            session,
            name=category_name,
            category_master_id=master.id,
            description=f"{category_name} annual audit observations",
            category_type="annual_audit",
            is_active=True
        )

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


def _rename_duplicate_templates(session) -> int:
    """
    Rename duplicate test templates by appending their category/test type name.

    Example: "Battery Set Annual Inspection" becomes:
      - "Battery Set Annual Inspection - Environmental"
      - "Battery Set Annual Inspection - Documentation"
      - "Battery Set Annual Inspection - General Maintenance"

    This makes templates unique and easier to identify in the UI.
    """
    from models import OrgTestTemplate
    from collections import defaultdict
    import json

    # Get all templates with their test type names
    templates = session.execute(text("""
        SELECT
            ott.id,
            ott.template_data,
            cd.name as test_type_name
        FROM org_test_templates ott
        LEFT JOIN "CategoryDetails" cd ON ott.test_type_id = cd.id
        ORDER BY ott.template_data->>'name'
    """)).fetchall()

    # Group by name to find duplicates
    templates_by_name = defaultdict(list)
    for t in templates:
        data = t.template_data
        name = data.get('name')
        if name:
            templates_by_name[name].append(t)

    # Rename duplicates
    renamed_count = 0
    for name, template_list in templates_by_name.items():
        if len(template_list) > 1:
            for t in template_list:
                data = dict(t.template_data)
                test_type = t.test_type_name or 'Unknown Type'
                old_name = data.get('name')

                # Create new name with test type (if not already there)
                if test_type and test_type not in old_name:
                    new_name = f"{old_name} - {test_type}"
                    data['name'] = new_name

                    session.execute(
                        text("UPDATE org_test_templates SET template_data = :data WHERE id = :id"),
                        {"id": t.id, "data": json.dumps(data)}
                    )
                    renamed_count += 1

    session.commit()
    return renamed_count


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
        d = _get_or_create_category_detail(
            session,
            name=name,
            category_master_id=master.id,
            description=desc,
            category_type=cat_type,
            is_active=True
        )
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
                    # Global default — overridable per equipment via EquipmentOverhaulConfig
                    "default_threshold": 5000,  # ops
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
    d = _get_or_create_category_detail(
        session,
        name=cal_name,
        category_master_id=master.id,
        description="Equipment calibration lifecycle — DATE_ADD rule, pre-due scheduling, FAIL → repair trigger.",
        category_type="maintenance",
        is_active=True
    )

    # ── Calibration template with DATE_ADD rule ───────────────────────────────
    CAL_KEY = "calibration"
    cal_template_data = {
        "name": "Calibration",
        "key": CAL_KEY,
        "description": "Equipment calibration lifecycle tracking. Computes next due date and triggers repair on failure.",
        "enable_calibration": True,
        "multi_session": False,
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
                    "result_field": "recommendation_type",
                    "order_by": "calibration_date",
                    "group_by": "equipment_id",
                    "requires_multi_session": False,
                },
            }
        ],
    }

    existing = session.query(OrgTestTemplate).filter(
        OrgTestTemplate.template_key == CAL_KEY,
        OrgTestTemplate.org_id == None,  # noqa: E711
    ).first()
    from sqlalchemy.orm.attributes import flag_modified
    count = 0
    if existing:
        existing.test_type_id = d.id
        existing.template_data = cal_template_data
        existing.is_system = True
        flag_modified(existing, "template_data")
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


def seed_dfr_template(session) -> int:
    """
    Seed the Dielectric Frequency Response (DFR / IDAX) OrgTestTemplate.

    Strategy — identical to seed_transformer_oil_template:
    - Read template_data from TEST_TEMPLATES["dfr_idax_transformer"] (single source of truth).
    - Look up CategoryMaster "Testing Equipment" (description="Testing Equipment").
    - Create CategoryDetails "Dielectric Frequency Response (DFR / IDAX)" if absent.
    - Upsert OrgTestTemplate (template_key="dfr_idax_transformer", org_id=NULL, is_system=True).
    """
    from models import CategoryMaster, OrgTestTemplate
    from test_templates import TEST_TEMPLATES

    DFR_KEY = "dfr_idax_transformer"
    template_data = TEST_TEMPLATES[DFR_KEY]

    master = session.query(CategoryMaster).filter(
        CategoryMaster.description == "Testing Equipment"
    ).first()
    if not master:
        master = CategoryMaster(
            name="Testing Equipment",
            description="Testing Equipment",
            is_active=True,
        )
        session.add(master)
        session.flush()

    detail = _get_or_create_category_detail(
        session,
        name="Dielectric Frequency Response (DFR / IDAX)",
        category_master_id=master.id,
        description="DFR / IDAX insulation diagnostics — multi-session moisture and insulation assessment for Power Transformers",
        category_type="test",
        is_active=True,
    )

    existing = session.query(OrgTestTemplate).filter(
        OrgTestTemplate.template_key == DFR_KEY,
        OrgTestTemplate.org_id == None,  # noqa: E711
    ).first()
    count = 0
    if existing:
        existing.test_type_id = detail.id
        existing.template_data = template_data
        existing.is_system = True
    else:
        session.add(OrgTestTemplate(
            template_key=DFR_KEY,
            org_id=None,
            test_type_id=detail.id,
            template_data=template_data,
            is_system=True,
            version=1,
        ))
        count = 1

    session.commit()
    print(f"[OK] DFR / IDAX template seeded (master_id={master.id}, detail_id={detail.id}).")
    return count


def seed_tan_delta_templates(session) -> int:
    """
    Seed the single-session Tan-Delta / Capacitance / IDAX test types
    (individual + combined). Each reads template_data from TEST_TEMPLATES
    (single source of truth) and is upserted as a Power Transformer test type
    under the "Testing Equipment" CategoryMaster.
    """
    from models import CategoryMaster, OrgTestTemplate
    from test_templates import TEST_TEMPLATES

    # (template_key, CategoryDetails name, description)
    _TESTS = [
        ("tan_delta_capacitance_idax",
         "Tan-Delta, Capacitance & Insulation Diagnostics",
         "Combined Tan-Delta/Capacitance (DELTA 4000) and Insulation Diagnostics (IDAX) report."),
        ("tan_delta_winding",
         "Winding Tan-Delta & Capacitance Test",
         "Winding insulation Tan-Delta and capacitance measurement with historical comparison."),
        ("tan_delta_bushing_220kv",
         "220kV Bushing Tan-Delta Test",
         "220kV bushing Tan-Delta and capacitance measurement (R/Y/B phases)."),
        ("tan_delta_bushing_66kv",
         "66kV Bushing Tan-Delta Test",
         "66kV bushing Tan-Delta and capacitance measurement (R/Y/B phases)."),
        ("idax_insulation",
         "Insulation Diagnostics (IDAX)",
         "IDAX insulation diagnostics — % moisture and oil conductivity per winding configuration."),
        ("dfr_routine",
         "Dielectric Frequency Response (DFR) — Routine",
         "Single-session DFR measurement for routine/maintenance testing (no factory baseline)."),
        ("sfra_routine",
         "Sweep Frequency Response Analysis (SFRA) — Routine",
         "Single-session SFRA with static correlation-coefficient acceptance floors (no factory baseline)."),
        ("transformer_physical_inspection",
         "Transformer Physical Inspection",
         "Physical inspection and megger test results for power transformers."),
    ]

    # Resolve the equipment-type master PER TEMPLATE from its own equipment_type
    # field (data-driven). The test type's CategoryDetails must hang off the same
    # equipment-type master the test-request form reads (equipment_type_id ->
    # CategoryMaster). This works for any equipment type, not just Power Transformer.
    def _master_for(equipment_type_name: str):
        m = session.query(CategoryMaster).filter(
            CategoryMaster.name == equipment_type_name
        ).first()
        if not m:
            m = CategoryMaster(name=equipment_type_name, description="Testing Equipment", is_active=True)
            session.add(m)
            session.flush()
        return m

    count = 0
    for key, detail_name, desc in _TESTS:
        if key not in TEST_TEMPLATES:
            print(f"[WARN] Template '{key}' not found in TEST_TEMPLATES — skipping.")
            continue
        template_data = TEST_TEMPLATES[key]
        equip_type = template_data.get("equipment_type") or "Power Transformer"
        master = _master_for(equip_type)
        detail = _get_or_create_category_detail(
            session,
            name=detail_name,
            category_master_id=master.id,
            description=desc,
            category_type="test",
            is_active=True,
        )
        existing = session.query(OrgTestTemplate).filter(
            OrgTestTemplate.template_key == key,
            OrgTestTemplate.org_id == None,  # noqa: E711
        ).first()
        if existing:
            existing.test_type_id = detail.id
            existing.template_data = template_data
            existing.is_system = True
        else:
            session.add(OrgTestTemplate(
                template_key=key,
                org_id=None,
                test_type_id=detail.id,
                template_data=template_data,
                is_system=True,
                version=1,
            ))
            count += 1

    session.commit()
    print(f"[OK] Tan-Delta / Capacitance / IDAX / routine DFR-SFRA test types seeded ({len(_TESTS)} types).")
    return count


def seed_sfra_template(session) -> int:
    """
    Seed the Sweep Frequency Response Analysis (SFRA) OrgTestTemplate.

    Strategy — identical to seed_dfr_template:
    - Read template_data from TEST_TEMPLATES["sfra_transformer"] (single source of truth).
    - Look up CategoryMaster "Testing Equipment" (description="Testing Equipment").
    - Create CategoryDetails "Sweep Frequency Response Analysis (SFRA)" if absent.
    - Upsert OrgTestTemplate (template_key="sfra_transformer", org_id=NULL, is_system=True).
    """
    from models import CategoryMaster, OrgTestTemplate
    from test_templates import TEST_TEMPLATES

    SFRA_KEY = "sfra_transformer"
    template_data = TEST_TEMPLATES[SFRA_KEY]

    master = session.query(CategoryMaster).filter(
        CategoryMaster.description == "Testing Equipment"
    ).first()
    if not master:
        master = CategoryMaster(
            name="Testing Equipment",
            description="Testing Equipment",
            is_active=True,
        )
        session.add(master)
        session.flush()

    detail = _get_or_create_category_detail(
        session,
        name="Sweep Frequency Response Analysis (SFRA)",
        category_master_id=master.id,
        description="SFRA mechanical-integrity diagnostics — multi-session winding/core fingerprint comparison for Power Transformers (IEC 60076-18 / CIGRE 342)",
        category_type="test",
        is_active=True,
    )

    existing = session.query(OrgTestTemplate).filter(
        OrgTestTemplate.template_key == SFRA_KEY,
        OrgTestTemplate.org_id == None,  # noqa: E711
    ).first()
    count = 0
    if existing:
        existing.test_type_id = detail.id
        existing.template_data = template_data
        existing.is_system = True
    else:
        session.add(OrgTestTemplate(
            template_key=SFRA_KEY,
            org_id=None,
            test_type_id=detail.id,
            template_data=template_data,
            is_system=True,
            version=1,
        ))
        count = 1

    session.commit()
    print(f"[OK] SFRA template seeded (master_id={master.id}, detail_id={detail.id}).")
    return count


def seed_transformer_oil_template(session) -> int:
    """
    Seed the Transformer Oil Test OrgTestTemplate.

    Links to CategoryDetails "Transformer Oil Test" under the
    "Testing Equipment" CategoryMaster (same master used by all other
    test-type templates). Creates master/detail only when absent.
    """
    from models import CategoryMaster, CategoryDetails, OrgTestTemplate
    from test_templates import TEST_TEMPLATES
    from sqlalchemy.orm.attributes import flag_modified

    master = session.query(CategoryMaster).filter(
        CategoryMaster.description == "Testing Equipment"
    ).first()
    if not master:
        master = CategoryMaster(
            name="Testing Equipment",
            description="Testing Equipment",
            is_active=True,
        )
        session.add(master)
        session.flush()

    detail = _get_or_create_category_detail(
        session,
        name="Transformer Oil Test",
        category_master_id=master.id,
        description="Insulating oil quality test — BDV, moisture, acidity, tan delta per IS 335 / IEC 60296",
        is_active=True
    )

    OIL_KEY = "transformer_oil_test"
    template_data = TEST_TEMPLATES[OIL_KEY]

    existing = session.query(OrgTestTemplate).filter(
        OrgTestTemplate.template_key == OIL_KEY,
        OrgTestTemplate.org_id == None,  # noqa: E711
    ).first()
    count = 0
    if existing:
        existing.test_type_id = detail.id
        existing.template_data = template_data
        existing.is_system = True
        flag_modified(existing, "template_data")
    else:
        session.add(OrgTestTemplate(
            template_key=OIL_KEY,
            org_id=None,
            test_type_id=detail.id,
            template_data=template_data,
            is_system=True,
            version=1,
        ))
        count = 1

    session.commit()
    print(f"[OK] Transformer Oil Test template seeded (detail_id={detail.id}).")
    return count


def seed_transformer_dga_template(session) -> int:
    """Seed the standalone Transformer DGA OrgTestTemplate."""
    from models import CategoryMaster, CategoryDetails, OrgTestTemplate
    from test_templates import TEST_TEMPLATES
    from sqlalchemy.orm.attributes import flag_modified

    master = session.query(CategoryMaster).filter(
        CategoryMaster.description == "Testing Equipment"
    ).first()
    if not master:
        master = CategoryMaster(
            name="Testing Equipment",
            description="Testing Equipment",
            is_active=True,
        )
        session.add(master)
        session.flush()

    detail = _get_or_create_category_detail(
        session,
        name="Transformer Dissolved Gas Analysis (DGA)",
        category_master_id=master.id,
        description="Standalone DGA sampling — gas concentration analysis per IS 10593:2017 / IEC 60599",
        is_active=True,
    )

    DGA_KEY = "transformer_dga"
    template_data = TEST_TEMPLATES[DGA_KEY]

    existing = session.query(OrgTestTemplate).filter(
        OrgTestTemplate.template_key == DGA_KEY,
        OrgTestTemplate.org_id == None,  # noqa: E711
    ).first()
    count = 0
    if existing:
        existing.test_type_id = detail.id
        existing.template_data = template_data
        existing.is_system = True
        flag_modified(existing, "template_data")
    else:
        session.add(OrgTestTemplate(
            template_key=DGA_KEY,
            org_id=None,
            test_type_id=detail.id,
            template_data=template_data,
            is_system=True,
            version=1,
        ))
        count = 1

    session.commit()
    print(f"[OK] Transformer DGA template seeded (detail_id={detail.id}).")
    return count


def seed_capacitance_tandelta_template(session) -> int:
    """Seed the Capacitance & Tan Delta Test (Transformer) OrgTestTemplate.

    This test type exists under MULTIPLE CategoryMaster rows
    (e.g. 'Power Transformer' and 'Feeder protection relays').
    We create one org_test_templates row per CategoryDetails row so that
    get_for_test_type() resolves correctly regardless of which equipment
    type the testing request was created against.
    """
    from models import CategoryDetails, OrgTestTemplate
    from sqlalchemy.orm.attributes import flag_modified
    from test_templates import TEST_TEMPLATES

    KEY = "capacitance_tandelta_transformer"
    template_data = TEST_TEMPLATES[KEY]

    # Find ALL CategoryDetails rows with this test type name
    all_details = session.query(CategoryDetails).filter(
        CategoryDetails.name == "Capacitance & Tan Delta Test (Transformer)",
    ).all()

    if not all_details:
        print("  [WARN] No CategoryDetails found for 'Capacitance & Tan Delta Test (Transformer)' — skipping")
        return 0

    count = 0
    for detail in all_details:
        existing = session.query(OrgTestTemplate).filter(
            OrgTestTemplate.template_key == KEY,
            OrgTestTemplate.test_type_id == detail.id,
            OrgTestTemplate.org_id == None,  # noqa: E711
        ).first()
        if existing:
            existing.template_data = template_data
            flag_modified(existing, "template_data")
            existing.is_system = True
        else:
            session.add(OrgTestTemplate(
                template_key=KEY,
                org_id=None,
                test_type_id=detail.id,
                template_data=template_data,
                is_system=True,
                version=1,
            ))
            count += 1

    session.commit()
    print(f"[OK] Capacitance & Tan Delta template seeded ({len(all_details)} detail rows, {count} new).")
    return count


def seed_inspection_templates(session) -> int:
    """
    Migrate equipment-specific inspection templates.

    Previously all equipment inspection types (Circuit Breaker, Surge Arrestor,
    Battery Set, Protection Relay, ETM) shared the transformer_inspection template.
    This function updates those rows to use equipment-specific template keys and
    template_data, and inserts any missing rows.

    Idempotent — safe to run multiple times.
    """
    from models import CategoryMaster, CategoryDetails, OrgTestTemplate
    from test_templates import TEST_TEMPLATES

    # Maps equipment master name → (template_key, inspection subtype names)
    equipment_inspection_map = {
        "Circuit Breaker": (
            "circuit_breaker_inspection",
            ["Electrical Safety", "Civil", "Fire Safety", "Documentation", "Environmental", "General Maintenance"],
        ),
        "Surge Arrestor": (
            "surge_arrestor_inspection",
            ["Electrical Safety", "General Maintenance", "Documentation"],
        ),
        "Battery Set": (
            "battery_inspection",
            ["Electrical Safety", "General Maintenance", "Documentation", "Environmental"],
        ),
        "Protection Relay": (
            "protection_relay_inspection",
            ["Electrical Safety", "General Maintenance", "Documentation"],
        ),
        "Electronic Tri-vector Meter": (
            "etm_inspection",
            ["Electrical Safety", "General Maintenance", "Documentation"],
        ),
    }

    updated = 0
    inserted = 0

    for equip_name, (template_key, subtypes) in equipment_inspection_map.items():
        master = session.query(CategoryMaster).filter_by(name=equip_name).first()
        if not master:
            print(f"  [SKIP] CategoryMaster '{equip_name}' not found — skipping.")
            continue

        template_data = TEST_TEMPLATES.get(template_key)
        if not template_data:
            print(f"  [SKIP] Template '{template_key}' not in TEST_TEMPLATES — skipping.")
            continue

        for subtype_name in subtypes:
            detail = session.query(CategoryDetails).filter_by(
                name=subtype_name,
                category_master_id=master.id,
                category_type="inspection",
            ).first()
            if not detail:
                print(f"  [SKIP] CategoryDetails '{subtype_name}' for '{equip_name}' not found — skipping.")
                continue

            existing = session.query(OrgTestTemplate).filter_by(
                test_type_id=detail.id,
                org_id=None,
            ).first()

            if existing:
                if existing.template_key != template_key or existing.template_data != template_data:
                    existing.template_key = template_key
                    existing.template_data = template_data
                    existing.is_system = True
                    updated += 1
            else:
                session.add(OrgTestTemplate(
                    template_key=template_key,
                    org_id=None,
                    test_type_id=detail.id,
                    template_data=template_data,
                    is_system=True,
                    version=1,
                ))
                inserted += 1

    session.commit()
    print(f"[OK] Equipment inspection templates: {updated} updated, {inserted} inserted.")
    return updated + inserted


def seed_generic_equipment_templates(session) -> int:
    """
    Map generic templates to new equipment types (PT, Station Aux Transformer,
    DG Set, Digital Comm Panel, LTAC Panel, PLCC Panel, Wave Trap, Control & Relay Panel,
    Fire Fighting System, Battery Charger).

    Creates OrgTestTemplate records linking CategoryDetails to generic templates:
    - test types → generic_equipment_test
    - maintenance types → generic_equipment_maintenance
    - inspection types → generic_equipment_inspection

    Idempotent — safe to run multiple times.
    """
    from models import CategoryMaster, CategoryDetails, OrgTestTemplate
    from test_templates import TEST_TEMPLATES

    # Equipment types to map (the 10 new equipment types)
    equipment_types = [
        "Potential Transformer",
        "Station Auxiliary Transformer",
        "Diesel Generator Set",
        "Digital Communication Panel",
        "LTAC Panel",
        "PLCC Panel",
        "Wave Trap",
        "Control & Relay Panel",
        "Fire Fighting System",
        "Battery Charger",
    ]

    # Category type → template key mapping
    template_mapping = {
        "test": "generic_equipment_test",
        "maintenance": "generic_equipment_maintenance",
        "inspection": "generic_equipment_inspection",
    }

    inserted = 0
    updated = 0

    for equip_name in equipment_types:
        master = session.query(CategoryMaster).filter_by(name=equip_name).first()
        if not master:
            print(f"  [SKIP] CategoryMaster '{equip_name}' not found — skipping.")
            continue

        # Get all test/maintenance/inspection CategoryDetails for this equipment
        details = session.query(CategoryDetails).filter_by(
            category_master_id=master.id
        ).filter(
            CategoryDetails.category_type.in_(["test", "maintenance", "inspection"])
        ).all()

        if not details:
            print(f"  [SKIP] No test/maintenance/inspection types for '{equip_name}' — skipping.")
            continue

        for detail in details:
            # Get the appropriate generic template for this category type
            template_key = template_mapping.get(detail.category_type)
            if not template_key:
                continue

            template_data = TEST_TEMPLATES.get(template_key)
            if not template_data:
                print(f"  [WARN] Template '{template_key}' not found in TEST_TEMPLATES — skipping.")
                continue

            # Check if template already exists
            existing = session.query(OrgTestTemplate).filter_by(
                test_type_id=detail.id,
                org_id=None,
            ).first()

            if existing:
                # Update if template key or data changed
                if existing.template_key != template_key or existing.template_data != template_data:
                    existing.template_key = template_key
                    existing.template_data = template_data
                    existing.is_system = True
                    updated += 1
            else:
                # Create new template mapping
                session.add(OrgTestTemplate(
                    template_key=template_key,
                    org_id=None,
                    test_type_id=detail.id,
                    template_data=template_data,
                    is_system=True,
                    version=1,
                ))
                inserted += 1

    session.commit()
    print(f"[OK] Generic equipment templates: {updated} updated, {inserted} inserted.")
    return updated + inserted


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
        _permission(fr_wf.id, t_init_approve, "Test & Work Coordinator")
        _permission(fr_wf.id, t_fr_reject,    "Test & Work Coordinator")

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
        _permission(tr_wf.id, t_assign,       "Test & Work Coordinator")
        _permission(tr_wf.id, t_tr_reject,    "Test & Work Coordinator")
        _permission(tr_wf.id, t_accept,       "Test Engineer")
        _permission(tr_wf.id, t_accept,       "Test Engineer")
        _permission(tr_wf.id, t_accept,       "Test Engineer")
        _permission(tr_wf.id, t_submit_result,"Test Engineer")
        _permission(tr_wf.id, t_submit_result,"Test Engineer")
        _permission(tr_wf.id, t_submit_result,"Test Engineer")

        for t_appr in [t_approve_maint, t_approve_insp, t_approve_rl,
                       t_approve_none, t_approve_repl, t_tech_reject]:
            _permission(tr_wf.id, t_appr, "Reviewing Officer")

        _permission(tr_wf.id, t_resubmit,    "Test Engineer")
        _permission(tr_wf.id, t_resubmit,    "Test Engineer")
        _permission(tr_wf.id, t_resubmit,    "Test Engineer")
        _permission(tr_wf.id, t_fin_approve, "Procurement Approver")
        _permission(tr_wf.id, t_fin_reject,  "Procurement Approver")

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
        _permission(taqc_wf.id, t_q_assign,    "Test & Work Coordinator")
        _permission(taqc_wf.id, t_q_reject,    "Test & Work Coordinator")
        _permission(taqc_wf.id, t_q_accept,    "Test Engineer")
        _permission(taqc_wf.id, t_q_accept,    "Test Engineer")
        _permission(taqc_wf.id, t_q_accept,    "Test Engineer")
        _permission(taqc_wf.id, t_q_submit_ec, "Test Engineer")
        _permission(taqc_wf.id, t_q_submit_ec, "Test Engineer")
        _permission(taqc_wf.id, t_q_submit_ec, "Test Engineer")
        _permission(taqc_wf.id, t_q_approve,   "Reviewing Officer")
        _permission(taqc_wf.id, t_q_tech_rej,  "Reviewing Officer")
        _permission(taqc_wf.id, t_q_resubmit,  "Test Engineer")
        _permission(taqc_wf.id, t_q_resubmit,  "Test Engineer")
        _permission(taqc_wf.id, t_q_resubmit,  "Test Engineer")

        session.commit()
        print("  [OK] taqc_inspection workflow seeded.")

    print("[OK] TR / FR / TAQC workflow seeding complete.")


def _seed_notification_variables(session) -> int:
    """
    Idempotent seed for NotificationVariable (global system variables).

    Single source of truth — supersedes DEFAULT_VARIABLES in notification_service.py
    and the thin SYSTEM_VARIABLES list that used to live in routers/notifications.py.

    Each entry carries `role_template_names` — a list of RoleTemplate names whose
    members find this variable contextually relevant in the template designer.
    Empty list = universal (shown for all roles).
    Admins can override these lists from the UI via PUT /notifications/variables/{id}.

    Re-running the seed upserts every field so corrections land in the DB.
    """
    from models import NotificationVariable, RoleTemplate

    # Build a name → UUID string lookup once for the whole run.
    role_map: dict = {
        r.name: str(r.id)
        for r in session.query(RoleTemplate).all()
    }

    def _ids(names: list) -> list:
        """Resolve a list of RoleTemplate names to UUID strings. Skips unknowns."""
        return [role_map[n] for n in names if n in role_map]

    # role_template_names:
    #   []    → universal variable — shown in all template pickers
    #   [...]  → scoped to those RoleTemplates; resolved to UUIDs at seed time
    # fallback_keys: ordered list of raw fire()-context keys to try when the
    # dot-notation var_key itself isn't present.  First match wins.
    # Replaces the hardcoded VariableResolver._ALIASES dict.
    _VARIABLES = [
        # ── Reports ──────────────────────────────────────────────────────────
        dict(var_key="report.lastexecution", label="Last Executed Test Summary",
             group_name="Reports",          resolver_key="last_execution_html",
             fallback_keys=["last_execution_html"],
             description="HTML table summarising the last completed test request for the equipment "
                         "(request number, title, test type, status, submitted date, due date). "
                         "Resolved automatically when equipment is the notification source.",
             sample_value="<table>...</table>",
             role_template_names=[]),
        dict(var_key="report.retriexls",   label="Report — Excel Download URL",
             group_name="Reports",         resolver_key="report.retriexls",
             fallback_keys=["report_xls_url", "xls_url"],
             description="Signed URL for the Excel report attachment (.xlsx).",
             sample_value="https://app.seacms.in/reports/REQ-001.xlsx",
             role_template_names=["Reviewing Officer", "Supervisory Officer", "Senior Management Approver"]),
        dict(var_key="report.retriepdf",   label="Report — PDF Download URL",
             group_name="Reports",         resolver_key="report.retriepdf",
             fallback_keys=["report_pdf_url", "pdf_url"],
             description="Signed URL for the PDF report attachment.",
             sample_value="https://app.seacms.in/reports/REQ-001.pdf",
             role_template_names=["Reviewing Officer", "Supervisory Officer", "Senior Management Approver"]),
        dict(var_key="report.ref",         label="Report Reference Number",
             group_name="Reports",         resolver_key="report.ref",
             fallback_keys=["report_ref", "request_number"],
             description="Auto-generated report reference number.",
             sample_value="RPT-2025-001",
             role_template_names=["Reviewing Officer", "Supervisory Officer", "Senior Management Approver"]),
        dict(var_key="report.generated_on", label="Report Generated Date/Time",
             group_name="Reports",           resolver_key="report.generated_on",
             fallback_keys=["report_generated_on"],
             description="Timestamp when the report was generated.",
             sample_value="2025-01-15 10:30 UTC",
             role_template_names=["Reviewing Officer", "Supervisory Officer", "Senior Management Approver"]),
        # ── Equipment ─────────────────────────────────────────────────────────
        # Universal — used by all roles in any equipment-related template.
        dict(var_key="equipment.ueic",        label="Equipment UEIC",
             group_name="Equipment",           resolver_key="equipment",
             fallback_keys=["equipment", "ueic", "old_ueic"],
             description="Unique Equipment Identity Code of the subject equipment.",
             sample_value="TX-001-2025",
             role_template_names=[]),
        dict(var_key="equipment.type",        label="Equipment Type",
             group_name="Equipment",           resolver_key="equipment_type",
             fallback_keys=["equipment_type"],
             description="Type/category of the equipment (e.g. Power Transformer).",
             sample_value="Power Transformer",
             role_template_names=[]),
        dict(var_key="equipment.department",  label="Substation / Department",
             group_name="Equipment",           resolver_key="department",
             fallback_keys=["department"],
             description="Substation, bay, or department where the equipment is installed.",
             sample_value="Relay Panel — Substation A",
             role_template_names=[]),
        dict(var_key="equipment.status",      label="Equipment Status",
             group_name="Equipment",           resolver_key="equipment_status",
             fallback_keys=["equipment_status"],
             description="Current operational status of the equipment.",
             sample_value="active",
             role_template_names=[]),
        dict(var_key="table.performance",     label="Equipment Performance Table",
             group_name="Equipment",           resolver_key="performance_table_html",
             fallback_keys=["performance_table_html"],
             description="HTML table showing the equipment's analytics health score, risk level, "
                         "condition summary, tests assessed, and last test date. "
                         "Resolved automatically when equipment is the notification source.",
             sample_value="<table>...</table>",
             role_template_names=[]),
        dict(var_key="equipment.manufacturer", label="Manufacturer",
             group_name="Equipment",            resolver_key="manufacturer",
             fallback_keys=["manufacturer"],
             description="Manufacturer / OEM of the equipment.",
             sample_value="ABB",
             role_template_names=[]),
        # ── Replacement event ─────────────────────────────────────────────────
        dict(var_key="old_ueic",    label="Retired UEIC",
             group_name="Replacement", resolver_key="old_ueic",
             fallback_keys=["old_ueic"],
             description="UEIC of the retired (replaced) equipment.",
             sample_value="TX-OLD-001",
             role_template_names=["Asset Data Officer", "Maintenance Officer"]),
        dict(var_key="new_ueic",    label="New Replacement UEIC",
             group_name="Replacement", resolver_key="new_ueic",
             fallback_keys=["new_ueic"],
             description="UEIC of the newly commissioned replacement equipment.",
             sample_value="TX-NEW-002",
             role_template_names=["Asset Data Officer", "Maintenance Officer"]),
        dict(var_key="replaced_by", label="Replaced By (User)",
             group_name="Replacement", resolver_key="replaced_by",
             fallback_keys=["replaced_by"],
             description="Name / email of the officer who recorded the replacement.",
             sample_value="EE John (john@utility.com)",
             role_template_names=["Asset Data Officer", "Maintenance Officer"]),
        dict(var_key="replaced_on", label="Replacement Date",
             group_name="Replacement", resolver_key="replaced_on",
             fallback_keys=["replaced_on"],
             description="Date on which the replacement event was recorded.",
             sample_value="2025-01-15",
             role_template_names=["Asset Data Officer", "Maintenance Officer"]),
        dict(var_key="reason",      label="Replacement / Rejection Reason",
             group_name="Replacement", resolver_key="reason",
             fallback_keys=["reason"],
             description="Free-text reason for the replacement or rejection action.",
             sample_value="End of service life — IR below threshold",
             role_template_names=[]),
        # ── Test Request workflow ──────────────────────────────────────────────
        dict(var_key="request.number",       label="Test Request Number",
             group_name="Test Request",       resolver_key="request_number",
             fallback_keys=["request_number"],
             description="Auto-generated test request reference number.",
             sample_value="REQ-2025-001",
             role_template_names=[]),
        dict(var_key="request.title",        label="Test Request Title",
             group_name="Test Request",       resolver_key="request_title",
             fallback_keys=["request_title", "title"],
             description="Title/description of the test request.",
             sample_value="IR Test — Power Transformer TX-001",
             role_template_names=[]),
        dict(var_key="request.status",       label="Request Status",
             group_name="Test Request",       resolver_key="request_status",
             fallback_keys=["request_status"],
             description="Current workflow status of the test request.",
             sample_value="submitted",
             role_template_names=[]),
        dict(var_key="request.priority",     label="Priority",
             group_name="Test Request",       resolver_key="request_priority",
             fallback_keys=["request_priority", "priority"],
             description="Priority level of the test request (high / medium / low).",
             sample_value="high",
             role_template_names=[]),
        dict(var_key="request.due_date",     label="Due Date",
             group_name="Test Request",       resolver_key="due_date",
             fallback_keys=["due_date"],
             description="Scheduled due date for the test to be completed.",
             sample_value="2025-03-31",
             role_template_names=[]),
        dict(var_key="request.submitted_by", label="Submitted By",
             group_name="Test Request",       resolver_key="originator",
             fallback_keys=["originator"],
             description="Email / name of the user who submitted the test request.",
             sample_value="originator@utility.com",
             role_template_names=[]),
        dict(var_key="request.assigned_to",  label="Assigned To (Tester)",
             group_name="Test Request",       resolver_key="tester",
             fallback_keys=["tester", "assigned_tester"],
             description="Email / name of the tester the request was assigned to.",
             sample_value="tester@utility.com",
             role_template_names=["Test & Work Coordinator", "Reviewing Officer"]),
        dict(var_key="table.testkit",        label="Test Kit Availability Table",
             group_name="Test Request",       resolver_key="kit_availability_html",
             fallback_keys=["kit_availability_html"],
             description="HTML table showing kit availability for the assigned test type and department. "
                         "Populated automatically for tester-assignment notifications.",
             sample_value="<table>...</table>",
             role_template_names=[]),
        # ── Evaluation / test result ───────────────────────────────────────────
        dict(var_key="eval.overall",     label="Overall Result (NORMAL / ALERT / CRITICAL)",
             group_name="Evaluation",    resolver_key="eval_overall",
             fallback_keys=["eval_overall", "overall"],
             description="Composite evaluation outcome from test template thresholds.",
             sample_value="CRITICAL",
             role_template_names=["Reviewing Officer", "Maintenance Officer", "Supervisory Officer"]),
        dict(var_key="eval.test_type",   label="Test Type",
             group_name="Evaluation",    resolver_key="test_name",
             fallback_keys=["test_name"],
             description="Name of the test type (e.g. IR Test, PI Test).",
             sample_value="IR Test",
             role_template_names=[]),
        dict(var_key="eval.testname",    label="Test Name",
             group_name="Evaluation",    resolver_key="test_name",
             fallback_keys=["test_name", "eval.test_type"],
             description="User-friendly test name (e.g. Short Circuit Test HV-IV).",
             sample_value="Short Circuit Test HV-IV",
             role_template_names=[]),
        dict(var_key="eval.evaluated_at", label="Evaluation Date/Time",
             group_name="Evaluation",     resolver_key="tested_at",
             fallback_keys=["tested_at", "evaluated_at"],
             description="Timestamp when the test evaluation was completed.",
             sample_value="2025-01-15 09:00 UTC",
             role_template_names=["Reviewing Officer", "Maintenance Officer"]),
        dict(var_key="alert.thresholdconfig", label="Threshold Configuration Table",
             group_name="Evaluation",          resolver_key="alert.thresholdconfig",
             fallback_keys=[],
             description="Auto-generated HTML table showing each parameter's measured value, "
                          "status (ALERT/CRITICAL), and normal/alert/critical ranges. "
                          "Populated only for eval_alert and eval_critical events.",
             sample_value="<table>...</table>",
             role_template_names=["Reviewing Officer", "Maintenance Officer", "Supervisory Officer"]),
        # ── Organisation ──────────────────────────────────────────────────────
        dict(var_key="org.name", label="Organisation Name",
             group_name="Organisation", resolver_key="org_name",
             fallback_keys=["org_name"],
             description="Name of the organisation as registered in SEACMS.",
             sample_value="KPTCL",
             role_template_names=[]),
        dict(var_key="org.id",   label="Organisation ID",
             group_name="Organisation", resolver_key="org_id",
             fallback_keys=["org_id"],
             description="UUID of the organisation.",
             sample_value="3fa85f64-5717-4562-b3fc-2c963f66afa6",
             role_template_names=[]),
        # ── Department / Context ──────────────────────────────────────────────
        dict(var_key="dept.name",  label="Department Name",
             group_name="Context", resolver_key="currentdeptname",
             fallback_keys=["currentdeptname", "department_name", "dept_name", "department"],
             description="Name of the department associated with the event.",
             sample_value="North Division",
             role_template_names=[]),
        dict(var_key="dept.code",  label="Department Code",
             group_name="Context", resolver_key="dept_code",
             fallback_keys=["dept_code", "department_code"],
             description="Short code for the department.",
             sample_value="NB-DIV",
             role_template_names=[]),
        dict(var_key="dept.level", label="Department Level",
             group_name="Context", resolver_key="dept_level",
             fallback_keys=["dept_level"],
             description="Hierarchy level of the department (e.g. Zone, Circle, Division).",
             sample_value="Division",
             role_template_names=[]),
        dict(var_key="user.name",  label="Recipient Name",
             group_name="Context", resolver_key="user_name",
             fallback_keys=["user_name", "recipient_name"],
             description="Full name of the notification recipient (resolved at dispatch time).",
             sample_value="Jane Smith",
             role_template_names=[]),
        dict(var_key="user.email", label="Recipient Email",
             group_name="Context", resolver_key="recipient_email",
             fallback_keys=["recipient_email", "user_email"],
             description="Email address of the notification recipient.",
             sample_value="jane.smith@utility.com",
             role_template_names=[]),
        # ── System ────────────────────────────────────────────────────────────
        # System vars are injected directly in build_context — no fallback lookup needed.
        dict(var_key="system.date",     label="Today's Date",
             group_name="System",        resolver_key="system.date",
             fallback_keys=[],
             description="Current date at the time the notification is rendered (YYYY-MM-DD).",
             sample_value="2025-01-15",
             role_template_names=[]),
        dict(var_key="system.time",     label="Current Time (UTC)",
             group_name="System",        resolver_key="system.time",
             fallback_keys=[],
             description="Current time at the time the notification is rendered (HH:MM UTC).",
             sample_value="10:30 UTC",
             role_template_names=[]),
        dict(var_key="system.app_name", label="Application Name (SEACMS)",
             group_name="System",        resolver_key="system.app_name",
             fallback_keys=[],
             description="Name of the application — always resolves to 'SEACMS'.",
             sample_value="SEACMS",
             role_template_names=[]),
    ]

    inserted = 0
    for entry in _VARIABLES:
        # Resolve role names → UUID strings; pop the hint key (not a model field).
        role_ids    = _ids(entry.pop("role_template_names"))
        fb_keys     = entry.pop("fallback_keys", [])

        existing = (
            session.query(NotificationVariable)
            .filter(
                NotificationVariable.var_key == entry["var_key"],
                NotificationVariable.organization_id.is_(None),
            )
            .first()
        )
        if existing:
            # Upsert: refresh every mutable field so corrections land in the DB.
            for field, val in entry.items():
                setattr(existing, field, val)
            existing.role_template_ids = role_ids
            existing.fallback_keys     = fb_keys
        else:
            session.add(NotificationVariable(
                **entry,
                role_template_ids=role_ids,
                fallback_keys=fb_keys,
                organization_id=None,
                is_system=True,
                is_active=True,
            ))
            inserted += 1

    session.commit()
    return inserted


def _seed_notification_event_catalogue(session) -> int:
    """
    Idempotent seed for NotificationEventCatalogue.
    Matches on event_type — upserts label/description/context_vars/default_roles
    so re-running the seed refreshes descriptions without duplicating rows.

    To add a new notification event type:
      1. Add an entry to _CATALOGUE below (or INSERT directly into the DB).
      2. No code change to any router or service is needed.
    """
    from models import NotificationEventCatalogue, RoleTemplate

    # Build a name → UUID string map from the live RoleTemplate table.
    # default_roles are stored as RoleTemplate.id UUID strings so the Flutter
    # template editor gets a proper FK reference it can cross-check against
    # GET /notifications/org-roles (which returns role_template_id per OrgRole).
    _rt_map: dict = {
        rt.name: str(rt.id)
        for rt in session.query(RoleTemplate).all()
    }

    # Also accept KPTCL OrgRole names as valid (RoleTemplate replaced by OrgRole)
    from models import OrgRole as _OrgRole
    _org_role_names = {r.name for r in session.query(_OrgRole).all()}
    _VALID_ROLES = set(_rt_map.keys()) | _org_role_names

    # group_name values below MUST match the Flutter _groupIcons keys in
    # notification_center_page.dart so every group renders with an icon.
    _CATALOGUE = [
        # ── Equipment Lifecycle ───────────────────────────────────────────────
        dict(
            event_type="equipment_replacement",
            label="Equipment Replacement",
            group_name="Equipment Lifecycle",
            description="Fired when equipment is retired and a replacement unit is commissioned.",
            context_vars=["old_ueic", "new_ueic", "equipment_type", "department",
                          "reason_type", "reason", "replaced_by", "replaced_on"],
            default_roles=["EE_TLSS", "SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="equipment_registered",
            label="Equipment Registered",
            group_name="Equipment Lifecycle",
            description="Fired when a new equipment unit is commissioned into the register.",
            context_vars=["equipment", "equipment_type", "department", "manufacturer", "commissioned_by"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="equipment_retired",
            label="Equipment Retired",
            group_name="Equipment Lifecycle",
            description="Fired when an equipment unit is decommissioned / retired.",
            context_vars=["equipment", "equipment_type", "department", "reason", "retired_by"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="design_problem_alert",
            label="Design Problem Alert",
            group_name="Equipment Lifecycle",
            description="Fired when a systemic design problem is identified for a make/model.",
            context_vars=["manufacturer", "equipment_type", "problem_description", "affected_count"],
            default_roles=["CEE_TRANSMISSION_ZONE", "EE_TLSS"],
        ),
        # ── Threshold Alerts ──────────────────────────────────────────────────
        dict(
            event_type="eval_critical",
            label="Threshold Critical",
            group_name="Threshold Alerts",
            description=(
                "Fired when a test evaluation result is CRITICAL — either from "
                "per-session threshold bands OR from cross-session deviation comparison "
                "(e.g. moisture increase vs FACTORY baseline on a DFR multi-session test)."
            ),
            context_vars=[
                "equipment", "ueic", "test_type", "result", "dept",
                "eval.overall", "eval.evaluated_at", "report.retriepdf",
                # Standard threshold context
                "request.number", "tester_name", "result_summary", "revised_interval",
                # {{alert.thresholdconfig}} renders per-session AND cross-session deviation
                # tables automatically — use this in email body templates
                "alert.thresholdconfig",
            ],
            default_roles=["EE_TLSS", "SEE_WM", "CEE_TRANSMISSION_ZONE", "AEE_MAINTENANCE"],
        ),
        dict(
            event_type="eval_alert",
            label="Threshold Alert",
            group_name="Threshold Alerts",
            description=(
                "Fired when a test evaluation result is ALERT — either from "
                "per-session threshold bands OR from cross-session deviation comparison "
                "(e.g. tan delta increase vs FACTORY baseline on a DFR multi-session test)."
            ),
            context_vars=[
                "equipment", "ueic", "test_type", "result", "dept",
                "eval.overall", "eval.evaluated_at", "report.retriepdf",
                "request.number", "tester_name", "result_summary", "revised_interval",
                "alert.thresholdconfig",
            ],
            default_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        ),
        # ── Testing Requests ──────────────────────────────────────────────────
        dict(
            event_type="request_submitted",
            label="Request Submitted",
            group_name="Testing Requests",
            description="Fired when an originator submits a new test request.",
            context_vars=["request.number", "request.title", "request.priority",
                          "request.submitted_by", "equipment.ueic", "equipment.department"],
            default_roles=["EE_TLSS"],
        ),
        dict(
            event_type="request_rejected",
            label="Request Rejected",
            group_name="Testing Requests",
            description="Fired when a testing request is rejected by an approver.",
            context_vars=["request.number", "request.title", "equipment.ueic", "rejected_by", "reason"],
            default_roles=["Asset Data Officer", "EE_TLSS"],
        ),
        dict(
            event_type="tester_assigned",
            label="Tester Assigned",
            group_name="Testing Requests",
            description="Fired when a test request is assigned to a field/lab tester.",
            context_vars=["request.number", "request.title", "request.assigned_to",
                          "request.due_date", "equipment.ueic",
                          "table.testkit", "table.performance", "report.lastexecution"],
            default_roles=["AE_JE", "AEE_MAINTENANCE"],
        ),
        dict(
            event_type="tester_declined",
            label="Tester Declined Assignment",
            group_name="Testing Requests",
            description="Fired when a tester declines an assignment — notifies the Test & Work Coordinator.",
            context_vars=["request.number", "tester_name", "reason"],
            default_roles=["Test & Work Coordinator", "EE_TLSS"],
        ),
        dict(
            event_type="test_submitted",
            label="Test Submitted",
            group_name="Testing Requests",
            description="Fired when a tester submits test results for review.",
            context_vars=["request.number", "request.title", "request.submitted_by",
                          "equipment.ueic", "eval.overall", "report.retriepdf"],
            default_roles=["EE_TLSS"],
        ),
        dict(
            event_type="status_changed",
            label="Status Changed",
            group_name="Testing Requests",
            description="Fired when a normal workflow status changes.",
            context_vars=["request.number", "request.status", "request.title", "equipment.ueic"],
            default_roles=["EE_TLSS", "Asset Data Officer"],
        ),
        dict(
            event_type="recommendation_approved",
            label="Recommendation Approved",
            group_name="Testing Requests",
            description="Fired when a technical approver approves a recommendation.",
            context_vars=["request.number", "recommendation_type", "product_count"],
            default_roles=["Asset Data Officer", "AEE_MAINTENANCE"],
        ),
        dict(
            event_type="recommendation_rejected",
            label="Recommendation Rejected",
            group_name="Testing Requests",
            description="Fired when a technical approver rejects a recommendation.",
            context_vars=["request.number", "reason"],
            default_roles=["AE_JE", "Asset Data Officer"],
        ),
        dict(
            event_type="repair_cancelled",
            label="Repair Workflow Cancelled",
            group_name="Repair Lifecycle",
            description="Fired when an active repair workflow is cancelled.",
            context_vars=["equipment", "equipment_type", "department", "cancelled_by", "cancel_reason"],
            default_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        ),
        dict(
            event_type="overhaul_cancelled",
            label="Overhaul Workflow Cancelled",
            group_name="Repair Lifecycle",
            description="Fired when an active overhaul workflow is cancelled.",
            context_vars=["equipment", "equipment_type", "department", "cancelled_by", "cancel_reason"],
            default_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        ),
        dict(
            event_type="calibration_cancelled",
            label="Calibration Workflow Cancelled",
            group_name="Repair Lifecycle",
            description="Fired when an active calibration workflow is cancelled.",
            context_vars=["equipment", "equipment_type", "department", "cancelled_by", "cancel_reason"],
            default_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        ),
        dict(
            event_type="surveillance_cancelled",
            label="Surveillance Workflow Cancelled",
            group_name="Repair Lifecycle",
            description="Fired when an active surveillance workflow is cancelled.",
            context_vars=["equipment", "equipment_type", "department", "cancelled_by", "cancel_reason"],
            default_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        ),
        dict(
            event_type="procurement_pending",
            label="Procurement Request Raised",
            group_name="Testing Requests",
            description="Fired when a procurement request is created — notifies Procurement Approvers.",
            context_vars=["request.number", "pr_number", "title"],
            default_roles=["Procurement Officer", "EE_TLSS"],
        ),
        dict(
            event_type="procurement_decision",
            label="Procurement Decision (Approved / Rejected)",
            group_name="Testing Requests",
            description="Fired when Procurement approves or rejects a procurement request.",
            context_vars=["request.number", "pr_number", "decision", "notes"],
            default_roles=["Asset Data Officer", "EE_TLSS"],
        ),
        # ── Schedule Reminders ────────────────────────────────────────────────
        dict(
            event_type="due_reminder",
            label="Due Reminder (15 days)",
            group_name="Schedule Reminders",
            description="Fired 15 days before a scheduled test is due (SRS §8.2 #1).",
            context_vars=["equipment.ueic", "request.title", "request.due_date",
                          "equipment.department", "days_remaining"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="due_reminder_final",
            label="Due Reminder (Final — 7 days)",
            group_name="Schedule Reminders",
            description="Final reminder fired 7 days before a scheduled test is due (SRS §8.2 #2).",
            context_vars=["equipment.ueic", "request.title", "request.due_date",
                          "equipment.department", "days_remaining"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="overdue_alert",
            label="Test Overdue",
            group_name="Schedule Reminders",
            description="Fired when a scheduled test passes its due date without completion (SRS §8.2 #3).",
            context_vars=["equipment.ueic", "request.title", "request.due_date",
                          "equipment.department", "days_overdue"],
            default_roles=["EE_TLSS", "AEE_MAINTENANCE", "SEE_WM"],
        ),
        dict(
            event_type="overdue_escalation",
            label="Test Overdue Escalation (>7 days)",
            group_name="Schedule Reminders",
            description="Escalation fired when a test is more than 7 days overdue (SRS §8.2 #4).",
            context_vars=["equipment.ueic", "request.title", "request.due_date",
                          "days_overdue", "equipment.department"],
            default_roles=["SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
        # ── Stage Workflows ───────────────────────────────────────────────────
        # "Stage Workflows" covers repair / overhaul lifecycle stages
        dict(
            event_type="repair_stage_changed",
            label="Repair Stage Advanced",
            group_name="Stage Workflows",
            description="Fired each time the repair workflow advances to the next stage.",
            context_vars=["equipment", "equipment_type", "stage", "progress"],
            default_roles=["AEE_MAINTENANCE", "Transformer Repair Coordinator"],
        ),
        dict(
            event_type="repair_delay",
            label="Repair Stage Delayed",
            group_name="Stage Workflows",
            description="Fired when a repair stage is rejected / sent back — indicating a delay.",
            context_vars=["equipment", "equipment_type", "department", "repair_stage", "days_delayed"],
            default_roles=["AEE_MAINTENANCE", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="overhaul_recommended",
            label="Overhaul Recommended",
            group_name="Stage Workflows",
            description="Fired when the repair workflow reaches completion — overhaul is done.",
            context_vars=["equipment", "equipment_type", "department", "operation_count", "operation_threshold"],
            default_roles=["AEE_MAINTENANCE", "CEE_TRANSMISSION_ZONE", "EE_TLSS"],
        ),
        dict(
            event_type="overhaul_stage_changed",
            label="Overhaul Stage Advanced",
            group_name="Stage Workflows",
            description="Fired each time the overhaul workflow advances to the next stage.",
            context_vars=["equipment", "equipment_type", "stage", "progress"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="overhaul_stage_delay",
            label="Overhaul Stage Delayed",
            group_name="Stage Workflows",
            description="Fired when an overhaul stage is rejected / sent back — indicating a delay.",
            context_vars=["equipment", "equipment_type", "department", "repair_stage", "days_delayed"],
            default_roles=["AEE_MAINTENANCE", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="calibration_stage_changed",
            label="Calibration Stage Advanced",
            group_name="Stage Workflows",
            description="Fired each time the calibration workflow advances to the next stage.",
            context_vars=["equipment", "equipment_type", "stage", "progress"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="calibration_stage_delay",
            label="Calibration Stage Delayed",
            group_name="Stage Workflows",
            description="Fired when a calibration stage is rejected / sent back — indicating a delay.",
            context_vars=["equipment", "equipment_type", "department", "repair_stage", "days_delayed"],
            default_roles=["AEE_MAINTENANCE", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="surveillance_stage_changed",
            label="Surveillance Stage Advanced",
            group_name="Stage Workflows",
            description="Fired each time the surveillance workflow advances to the next quarter stage.",
            context_vars=["equipment", "equipment_type", "stage", "progress"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="surveillance_stage_delay",
            label="Surveillance Stage Delayed",
            group_name="Stage Workflows",
            description="Fired when a surveillance stage is rejected / sent back — indicating a delay.",
            context_vars=["equipment", "equipment_type", "department", "repair_stage", "days_delayed"],
            default_roles=["AEE_MAINTENANCE", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="annual_audit_stage_changed",
            label="Annual Audit Stage Advanced",
            group_name="Stage Workflows",
            description="Fired each time the annual audit workflow advances to the next stage.",
            context_vars=["equipment", "equipment_type", "stage", "progress"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="annual_audit_stage_delay",
            label="Annual Audit Stage Delayed",
            group_name="Stage Workflows",
            description="Fired when an annual audit stage is rejected / sent back — indicating a delay.",
            context_vars=["equipment", "equipment_type", "department", "repair_stage", "days_delayed"],
            default_roles=["AEE_MAINTENANCE", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="annual_audit_cancelled",
            label="Annual Audit Workflow Cancelled",
            group_name="Stage Workflows",
            description="Fired when an active annual audit workflow is cancelled.",
            context_vars=["equipment", "equipment_type", "department", "cancelled_by", "cancel_reason"],
            default_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        ),
        dict(
            event_type="precommission_stage_changed",
            label="Pre-Commission Stage Advanced",
            group_name="Stage Workflows",
            description="Fired each time the pre-commission QAP workflow advances to the next stage.",
            context_vars=["equipment", "equipment_type", "stage", "progress"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="precommission_stage_delay",
            label="Pre-Commission Stage Delayed",
            group_name="Stage Workflows",
            description="Fired when a pre-commission stage is rejected / sent back — indicating a delay.",
            context_vars=["equipment", "equipment_type", "department", "repair_stage", "days_delayed"],
            default_roles=["AEE_MAINTENANCE", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="precommission_cancelled",
            label="Pre-Commission Workflow Cancelled",
            group_name="Stage Workflows",
            description="Fired when an active pre-commission QAP workflow is cancelled.",
            context_vars=["equipment", "equipment_type", "department", "cancelled_by", "cancel_reason"],
            default_roles=["EE_TLSS", "AEE_MAINTENANCE"],
        ),
        # ── Failure Register ──────────────────────────────────────────────────
        dict(
            event_type="fr_submitted",
            label="Failure Registry Submitted",
            group_name="Failure Register",
            description="Fired when a new Failure Registry entry is submitted and is awaiting review.",
            context_vars=["fr_number", "equipment", "originator", "category"],
            default_roles=["Test & Work Coordinator", "EE_TLSS"],
        ),
        dict(
            event_type="fr_approved",
            label="Failure Registry Approved",
            group_name="Failure Register",
            description="Fired when a Failure Registry submission is approved.",
            context_vars=["fr_number", "equipment", "approved_by", "next_action"],
            default_roles=["Asset Data Officer", "AEE_MAINTENANCE"],
        ),
        dict(
            event_type="fr_rejected",
            label="Failure Registry Rejected",
            group_name="Failure Register",
            description="Fired when a Failure Registry submission is rejected by an approver.",
            context_vars=["fr_number", "reason"],
            default_roles=["Asset Data Officer"],
        ),
        # ── Reports ───────────────────────────────────────────────────────────
        dict(
            event_type="monthly_mis_report",
            label="Monthly MIS Report",
            group_name="Reports",
            description="Fired on the first working day of the month — distributes the monthly MIS report.",
            context_vars=["report_month", "tests_completed", "critical_count", "overdue_count",
                          "report_pdf_url", "report_xls_url"],
            default_roles=["SEE_WM", "CEE_TRANSMISSION_ZONE", "EE_TLSS"],
        ),
        # ── Report-Ready events (fired by run_scheduled_reports) ──────────────────
        dict(
            event_type="overdue_report_ready",
            label="Overdue Test Report Ready",
            group_name="Reports",
            description="Fired when the scheduled Overdue Test Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS", "SEE_WM"],
        ),
        dict(
            event_type="alert_report_ready",
            label="ALERT/CRITICAL Report Ready",
            group_name="Reports",
            description="Fired when the weekly ALERT/CRITICAL Equipment Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS", "SEE_WM"],
        ),
        dict(
            event_type="compliance_report_ready",
            label="Test Compliance Report Ready",
            group_name="Reports",
            description="Fired when the monthly Test Compliance Status Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["EE_TLSS", "SEE_WM"],
        ),
        dict(
            event_type="repair_report_ready",
            label="Transformer Repair Report Ready",
            group_name="Reports",
            description="Fired when the monthly Transformer Repair Status Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS", "SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="annual_failure_report_ready",
            label="Annual Failure Report Ready",
            group_name="Reports",
            description="Fired when the annual Equipment Failure Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="pm_report_ready",
            label="PM Compliance Report Ready",
            group_name="Reports",
            description="Fired when the monthly PM Compliance Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="remedial_report_ready",
            label="Remedial Action Report Ready",
            group_name="Reports",
            description="Fired when the monthly Remedial Action Pending Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        dict(
            event_type="taqc_report_ready",
            label="TA&QC Compliance Report Ready",
            group_name="Reports",
            description="Fired when the monthly TA&QC Observation Compliance Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["EE_TLSS", "SEE_WM"],
        ),
        dict(
            event_type="vendor_report_ready",
            label="Vendor Performance Report Ready",
            group_name="Reports",
            description="Fired when the quarterly Vendor Performance Ranking Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="repairer_report_ready",
            label="Repairer Performance Report Ready",
            group_name="Reports",
            description="Fired when the annual Repairer Performance Ranking Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
        dict(
            event_type="oltc_report_ready",
            label="OLTC/CB Operations Report Ready",
            group_name="Reports",
            description="Fired when the monthly OLTC/CB Operations Count Report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["AEE_MAINTENANCE"],
        ),
        dict(
            event_type="post_repair_report_ready",
            label="Post-Repair Evaluation Report Ready",
            group_name="Reports",
            description="Fired when a Post-Repair Transformer Evaluation report is generated.",
            context_vars=["report_name", "report_period", "download_url", "format"],
            default_roles=["SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
    ]

    # Guard: surface any default_roles value that isn't a known RoleTemplate name
    # so bad entries are caught at seed time rather than silently at runtime.
    _invalid = [
        (e["event_type"], r)
        for e in _CATALOGUE
        for r in e.get("default_roles", [])
        if r not in _VALID_ROLES
    ]
    if _invalid:
        import warnings
        for _evt, _role in _invalid:
            warnings.warn(
                f"[seed] default_roles: '{_role}' in event '{_evt}' is not a known "
                "RoleTemplate name — it will NOT resolve to any OrgRole.",
                stacklevel=2,
            )

    def _resolve_role_ids(names: list) -> list:
        """Convert a list of RoleTemplate names to UUID strings. Skips unknowns."""
        return [_rt_map[n] for n in names if n in _rt_map]

    inserted = 0
    for entry in _CATALOGUE:
        # Resolve role names → RoleTemplate UUIDs before persisting.
        role_ids = _resolve_role_ids(entry.get("default_roles", []))

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
            existing.default_roles = role_ids   # UUIDs, not names
        else:
            session.add(NotificationEventCatalogue(
                event_type   = entry["event_type"],
                label        = entry["label"],
                group_name   = entry["group_name"],
                description  = entry.get("description", ""),
                context_vars = entry.get("context_vars", []),
                default_roles= role_ids,         # UUIDs, not names
            ))
            inserted += 1
    session.commit()
    return inserted


def _seed_notification_templates(session) -> int:
    """
    Idempotent upsert of global default notification templates
    (organization_id = NULL).

    Single source of truth for all system notification templates —
    supersedes DEFAULT_TEMPLATES + seed_default_templates() in
    notification_service.py.

    On first run  → inserts all rows.
    On re-run     → updates subject_template / body_template /
                    recipient_roles / attachment_vars from this list,
                    leaving org-specific overrides untouched.

    To add or edit a template:
      1. Edit the matching _tmpl() call below (or add a new one).
      2. Re-run seed.py  — or call PUT /admin/notifications/seed-defaults
         from the Flutter UI.
      Zero code changes elsewhere are needed.
    """
    from models import NotificationTemplate
    import logging as _log
    _logger = _log.getLogger(__name__)

    # ── Inline builder helpers ───────────────────────────────────────────────
    def _e(subject, body_html, roles):
        """Email channel entry."""
        return {"channel": "email", "subject_template": subject,
                "body_template": body_html, "recipient_roles": roles,
                "attachment_vars": []}

    def _ea(subject, body_html, roles, attachment_vars):
        """Email channel entry with attachment variables."""
        return {"channel": "email", "subject_template": subject,
                "body_template": body_html, "recipient_roles": roles,
                "attachment_vars": attachment_vars}

    def _s(body, roles):
        """SMS channel entry (160-char guideline)."""
        return {"channel": "sms", "subject_template": "",
                "body_template": body, "recipient_roles": roles}

    def _i(title, body, roles):
        """In-app channel entry."""
        return {"channel": "inapp", "subject_template": title,
                "body_template": body, "recipient_roles": roles}

    def _html(rows):
        """Build a compact HTML table from [(label, var_key), ...] pairs."""
        trs = "".join(
            "<tr>"
            "<td style='padding:4px 8px;border:1px solid #ddd'><b>" + str(k) + "</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{" + str(v) + "}}</td>"
            "</tr>"
            for k, v in rows
        )
        return (
            "<table cellspacing='0' style='border-collapse:collapse;"
            "font-size:13px;width:100%'>"
            + trs + "</table>"
        )

    _TEMPLATES = []

    def _tmpl(event_type, *channel_dicts):
        for d in channel_dicts:
            _TEMPLATES.append({"event_type": event_type, **d})

    # ══════════════════════════════════════════════════════════════════════════
    # TEMPLATE DEFINITIONS
    # Each event type gets up to three channels: email (_e/_ea), SMS (_s),
    # in-app (_i).  subject_template / body_template use {{var_key}} syntax.
    # Org admins can override any of these from the Flutter Template Config UI.
    # ══════════════════════════════════════════════════════════════════════════

    # ── Equipment ─────────────────────────────────────────────────────────────
    _tmpl("equipment_replacement",
        _e(
            "[REPLACEMENT] {{equipment.type}} — {{old_ueic}} → {{new_ueic}}",
            "<h3 style='color:#1E3C72'>Equipment Replacement Notification</h3>"
            "<p>A replacement event has been recorded in SEACMS on {{system.date}}.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Retired UEIC</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{old_ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>New UEIC</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{new_ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Substation / Bay</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{reason_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{reason}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Replaced By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{replaced_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{replaced_on}}</td></tr>"
            "</table>"
            "<p>Log in to SEACMS Equipment Register to download the Replacement Report PDF.</p>",
            ["EE_TLSS", "SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
        _s(
            "[KPTCL-SEACMS] {{equipment.type}} at {{equipment.department}} replaced."
            " Old:{{old_ueic}} New:{{new_ueic}}. By {{replaced_by}} on {{replaced_on}}.",
            ["EE_TLSS", "SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
        _i(
            "Equipment replaced — {{old_ueic}} → {{new_ueic}}",
            "{{equipment.type}} at {{equipment.department}} replaced by {{replaced_by}} on {{replaced_on}}."
            " Reason: {{reason_type}}.",
            ["EE_TLSS", "SEE_WM", "CEE_TRANSMISSION_ZONE"],
        ),
    )

    # ── Evaluation ────────────────────────────────────────────────────────────
    _tmpl("eval_critical",
        _ea(
            "[CRITICAL] {{equipment.ueic}} — {{eval.testname}} Threshold Exceeded",
            "<h3 style='color:red'>Critical Test Result — Immediate Action Required</h3>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.testname}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Overall Result</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.overall}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Evaluated At</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.evaluated_at}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Finding</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{result_summary}}</td></tr>"
            "</table>"
            "<h4 style='margin-top:14px'>Threshold Configuration</h4>"
            "{{alert.thresholdconfig}}"
            "<p>The evaluation report is attached to this email.</p>",
            ["Reviewing Officer", "Supervisory Officer", "Senior Management Approver", "Maintenance Officer"],
            [{"var_key": "report.retriepdf", "type": "pdf"}],
        ),
        _s(
            "[KPTCL-SEACMS] CRITICAL: {{equipment.ueic}} — {{eval.test_type}}."
            " Req:{{request.number}}. Login SEACMS for details.",
            ["Reviewing Officer", "Maintenance Officer"],
        ),
        _i(
            "CRITICAL — {{equipment.ueic}}",
            "{{eval.test_type}} result CRITICAL for {{equipment.ueic}} ({{request.number}})."
            " Evaluated: {{eval.evaluated_at}}.",
            ["Reviewing Officer", "Supervisory Officer", "Senior Management Approver", "Maintenance Officer"],
        ),
    )

    _tmpl("eval_alert",
        _ea(
            "[ALERT] {{equipment.ueic}} — {{eval.testname}} Warning",
            "<h3 style='color:orange'>Alert: Test Result Warning</h3>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.testname}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Overall Result</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.overall}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Revised Interval</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{revised_interval}}</td></tr>"
            "</table>"
            "<h4 style='margin-top:14px'>Threshold Configuration</h4>"
            "{{alert.thresholdconfig}}"
            "<p>The evaluation report is attached to this email.</p>",
            ["Reviewing Officer", "Maintenance Officer"],
            [{"var_key": "report.retriepdf", "type": "pdf"}],
        ),
        _s(
            "[KPTCL-SEACMS] ALERT: {{equipment.ueic}} — {{eval.test_type}}."
            " Revised interval: {{revised_interval}}. Req:{{request.number}}.",
            ["Reviewing Officer", "Maintenance Officer"],
        ),
        _i(
            "Alert — {{equipment.ueic}}",
            "{{eval.test_type}} threshold warning for {{equipment.ueic}}."
            " Revised interval: {{revised_interval}}.",
            ["Reviewing Officer", "Maintenance Officer"],
        ),
    )

    # ── Test Workflow ──────────────────────────────────────────────────────────
    _tmpl("request_submitted",
        _e(
            "New Test Request Submitted — {{request.number}}",
            "<h3>New Test Request Awaiting Approval</h3>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Category</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{category}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Priority</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.priority}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Submitted By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.submitted_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
            "</table>"
            "<p>Log in to SEACMS to review and approve this request.</p>",
            ["Reviewing Officer", "@owner", "@requester"],
        ),
        _s(
            "[KPTCL-SEACMS] New {{category}} request {{request.number}} submitted"
            " by {{request.submitted_by}} for {{equipment.ueic}}. Login to approve.",
            ["Reviewing Officer", "@owner", "@requester"],
        ),
        _i(
            "New submission — {{request.number}}",
            "{{equipment.ueic}} submitted for {{category}} by {{request.submitted_by}}. Priority: {{request.priority}}.",
            ["Reviewing Officer", "@owner", "@requester"],
        ),
    )

    _tmpl("tester_assigned",
        _e(
            "Testing Assignment: {request_number}",
            "<h2 style='color:#1E3C72;margin-bottom:4px;'>Testing Request Assigned to You</h2>"
            "<p style='color:#555;margin-top:0;'>Hi {tester_name}, you have been assigned to carry out a field test.</p>"
            "<table width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;font-size:13px;margin-bottom:16px;'>"
            "<tr><td style='padding:8px 0;color:#888;width:160px;'>Request Number</td><td style='padding:8px 0;font-weight:600;color:#0F172A;'>{request_number}</td></tr>"
            "<tr><td style='padding:8px 0;color:#888;'>Equipment</td><td style='padding:8px 0;font-weight:600;color:#0F172A;'>{equipment}</td></tr>"
            "<tr><td style='padding:8px 0;color:#888;'>Equipment Type</td><td style='padding:8px 0;color:#0F172A;'>{equipment.type}</td></tr>"
            "<tr><td style='padding:8px 0;color:#888;'>Station</td><td style='padding:8px 0;color:#0F172A;'>{dept.name}</td></tr>"
            "<tr><td style='padding:8px 0;color:#888;'>Test Type</td><td style='padding:8px 0;color:#0F172A;'>{tr.test_type}</td></tr>"
            "<tr><td style='padding:8px 0;color:#888;'>Priority</td><td style='padding:8px 0;color:#0F172A;'>{request.priority}</td></tr>"
            "</table>"
            "{{table.testkit}}"
            "{{table.performance}}"
            "{{report.lastexecution}}"
            "<p style='margin-top:20px;'>Please log in to the SEACMS app to acknowledge and begin testing. "
            "Collect any required kits before proceeding to the site.</p>",
            ["@assignee", "Test Engineer", "Maintenance Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] You are assigned test req {{request.number}}"
            " for {{equipment.ueic}}. Due: {{request.due_date}}. Login SEACMS.",
            ["@assignee", "Test Engineer"],
        ),
        _i(
            "Assigned — {{request.number}}",
            "You have been assigned {{request.number}} for {{equipment.ueic}}. Due: {{request.due_date}}.",
            ["@assignee", "Test Engineer", "Maintenance Officer"],
        ),
    )

    _tmpl("tester_declined",
        _e(
            "Tester Declined Assignment — {{request.number}}",
            "<h3>Tester Declined — Reassignment Required</h3>"
            "<p><b>Request:</b> {{request.number}}</p>"
            "<p><b>Declined by:</b> {{tester_name}}</p>"
            "<p><b>Reason:</b> {{reason}}</p>"
            "<p>Please reassign this request in SEACMS.</p>",
            ["Test & Work Coordinator", "Reviewing Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] {{tester_name}} declined req {{request.number}}."
            " Reason: {{reason}}. Please reassign.",
            ["Test & Work Coordinator"],
        ),
        _i(
            "Tester declined — {{request.number}}",
            "{{tester_name}} declined {{request.number}}. Reason: {{reason}}.",
            ["Test & Work Coordinator", "Reviewing Officer"],
        ),
    )

    _tmpl("test_submitted",
        _ea(
            "Test Results Ready for Review — {{request.number}}",
            "<h3>Test Results Submitted — Awaiting Your Review</h3>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Overall Result</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{eval.overall}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Submitted By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.submitted_by}}</td></tr>"
            "</table>"
            "<p>The test report is attached to this email.</p>"
            "<p>Log in to SEACMS to approve or reject these results.</p>",
            ["Reviewing Officer"],
            [{"var_key": "report.retriepdf", "type": "pdf"}],
        ),
        _s(
            "[KPTCL-SEACMS] Results submitted for {{request.number}} ({{equipment.ueic}})."
            " Result: {{eval.overall}}. Login SEACMS to review.",
            ["Reviewing Officer"],
        ),
        _i(
            "Results submitted — {{request.number}}",
            "Test results for {{equipment.ueic}} ({{request.number}}) await review. Result: {{eval.overall}}.",
            ["Reviewing Officer"],
        ),
    )

    _tmpl("status_changed",
        _e(
            "Request Status Updated — {{request.number}}",
            "<h3>Testing Request Status Changed</h3>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Previous Status</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{status_from}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>New Status</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{status_to}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Changed By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{changed_by}}</td></tr>"
            "</table>"
            "<p>Log in to SEACMS to view the request.</p>",
            ["Reviewing Officer", "Asset Data Officer"],
        ),
        _i(
            "Status updated — {{request.number}}",
            "Request {{request.number}} moved from {{status_from}} to {{status_to}} by {{changed_by}}.",
            ["Reviewing Officer", "Asset Data Officer"],
        ),
    )

    _tmpl("recommendation_approved",
        _e(
            "Recommendation Approved — {{request.number}}",
            "<h3>Equipment Recommendation Approved</h3>"
            "<p><b>Request:</b> {{request.number}}</p>"
            "<p><b>Recommendation Type:</b> {{recommendation_type}}</p>"
            "<p><b>Replacement Products:</b> {{product_count}}</p>"
            "<p>Log in to SEACMS to proceed with procurement.</p>",
            ["Asset Data Officer", "Maintenance Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] Recommendation approved for {{request.number}}."
            " Type: {{recommendation_type}}. Login SEACMS.",
            ["Asset Data Officer"],
        ),
        _i(
            "Recommendation approved — {{request.number}}",
            "{{recommendation_type}} recommendation approved. {{product_count}} product(s) for procurement.",
            ["Asset Data Officer", "Maintenance Officer"],
        ),
    )

    _tmpl("recommendation_rejected",
        _e(
            "Recommendation Rejected — {{request.number}}",
            "<h3>Recommendation Rejected — Action Required</h3>"
            "<p><b>Request:</b> {{request.number}}</p>"
            "<p><b>Reason:</b> {{reason}}</p>"
            "<p>Please revise and resubmit your recommendation in SEACMS.</p>",
            ["Test Engineer", "Asset Data Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] Recommendation for {{request.number}} rejected."
            " Reason: {{reason}}. Please revise.",
            ["Test Engineer"],
        ),
        _i(
            "Recommendation rejected — {{request.number}}",
            "Recommendation rejected. Reason: {{reason}}.",
            ["Test Engineer", "Asset Data Officer"],
        ),
    )

    _tmpl("request_rejected",
        _e(
            "Test Request Rejected — {{request.number}}",
            "<h3>Testing Request Rejected</h3>"
            "<p><b>Request:</b> {{request.number}}</p>"
            "<p><b>Equipment:</b> {{equipment.ueic}}</p>"
            "<p><b>Rejected by:</b> {{rejected_by}}</p>"
            "<p><b>Reason:</b> {{reason}}</p>"
            "<p>Please review the request and resubmit it in SEACMS.</p>",
            ["Asset Data Officer", "Reviewing Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] Request {{request.number}} rejected by {{rejected_by}}. Reason: {{reason}}.",
            ["Asset Data Officer"],
        ),
        _i(
            "Request rejected — {{request.number}}",
            "Testing request {{request.number}} was rejected. Reason: {{reason}}.",
            ["Asset Data Officer", "Reviewing Officer"],
        ),
    )

    # ── Scheduling ────────────────────────────────────────────────────────────
    _tmpl("due_reminder",
        _e(
            "{{digest_count}} Test(s) Due Soon — {{dept.name}}",
            "<h3>Upcoming Tests Due — {{dept.name}}</h3>"
            "<p>The following <b>{{digest_count}}</b> test request(s) are due soon and require attention.</p>"
            "{{digest_table}}"
            "<p>Please ensure tests are scheduled and resources are allocated.</p>",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _s(
            "[SEACMS] {{digest_count}} test(s) due soon in {{dept.name}}."
            " Earliest: {{equipment.ueic}} due {{request.due_date}}.",
            ["Maintenance Officer"],
        ),
        _i(
            "{{digest_count}} test(s) due soon — {{dept.name}}",
            "{{digest_count}} request(s) due soon in {{dept.name}}. Earliest: {{equipment.ueic}} due {{request.due_date}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    _tmpl("due_reminder_final",
        _e(
            "FINAL REMINDER: {{digest_count}} Test(s) Due — {{dept.name}}",
            "<h3 style='color:orange'>Final Reminder — Tests Due Soon — {{dept.name}}</h3>"
            "<p><b>{{digest_count}}</b> test request(s) require immediate scheduling.</p>"
            "{{digest_table}}"
            "<p><b>Action required:</b> Ensure all listed tests are completed by their due dates.</p>",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _s(
            "[SEACMS] FINAL REMINDER: {{digest_count}} test(s) due in {{dept.name}}."
            " Earliest: {{equipment.ueic}} due {{request.due_date}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Final reminder — {{digest_count}} test(s) due — {{dept.name}}",
            "{{digest_count}} test(s) require immediate action in {{dept.name}}. Earliest due: {{request.due_date}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    _tmpl("overdue_alert",
        _e(
            "[OVERDUE] {{digest_count}} Test(s) Not Completed — {{dept.name}}",
            "<h3 style='color:red'>Tests Overdue — Immediate Action Required — {{dept.name}}</h3>"
            "<p><b>{{digest_count}}</b> test request(s) in your department are overdue.</p>"
            "{{digest_table}}"
            "<p>Please take immediate action to complete or reschedule these tests.</p>",
            ["Reviewing Officer", "Maintenance Officer", "Supervisory Officer"],
        ),
        _s(
            "[SEACMS] OVERDUE: {{digest_count}} test(s) in {{dept.name}} are overdue."
            " Oldest: {{equipment.ueic}} ({{days_overdue}}d). Req: {{request.number}}.",
            ["Reviewing Officer", "Maintenance Officer"],
        ),
        _i(
            "{{digest_count}} overdue test(s) — {{dept.name}}",
            "{{digest_count}} test(s) are overdue in {{dept.name}}. Oldest: {{equipment.ueic}} overdue {{days_overdue}} days.",
            ["Reviewing Officer", "Maintenance Officer", "Supervisory Officer"],
        ),
    )

    _tmpl("overdue_escalation",
        _e(
            "[ESCALATION] {{digest_count}} Test(s) Critically Overdue — {{dept.name}}",
            "<h3 style='color:darkred'>Escalation: Tests Critically Overdue — {{dept.name}}</h3>"
            "<p><b>{{digest_count}}</b> test request(s) have been escalated to management.</p>"
            "{{digest_table}}"
            "<p>This has been escalated to zone/circle management for immediate intervention.</p>",
            ["Supervisory Officer", "Senior Management Approver"],
        ),
        _s(
            "[SEACMS] ESCALATION: {{digest_count}} test(s) critically overdue in {{dept.name}}."
            " Oldest: {{equipment.ueic}} ({{days_overdue}}d). Req: {{request.number}}.",
            ["Supervisory Officer", "Senior Management Approver"],
        ),
        _i(
            "Escalation — {{digest_count}} critical overdue — {{dept.name}}",
            "{{digest_count}} test(s) critically overdue in {{dept.name}}. Oldest: {{equipment.ueic}} {{days_overdue}} days.",
            ["Supervisory Officer", "Senior Management Approver"],
        ),
    )

    # ── Procurement ───────────────────────────────────────────────────────────
    _tmpl("procurement_pending",
        _e(
            "Procurement Request Raised — {{pr_number}}",
            "<h3>New Procurement Request Awaiting Finance Approval</h3>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>PR Number</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{pr_number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Title</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{title}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
            "</table>"
            "<p>Log in to SEACMS to approve or reject this procurement request.</p>",
            ["Procurement Approver", "Reviewing Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] Procurement {{pr_number}} raised for {{request.number}}."
            " Awaiting your finance approval. Login SEACMS.",
            ["Procurement Approver"],
        ),
        _i(
            "Procurement raised — {{pr_number}}",
            "PR {{pr_number}} for test request {{request.number}} is awaiting finance approval.",
            ["Procurement Approver", "Reviewing Officer"],
        ),
    )

    _tmpl("procurement_decision",
        _e(
            "Procurement {{decision|upper}} — {{pr_number}}",
            "<h3>Procurement Decision: {{decision|upper}}</h3>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>PR Number</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{pr_number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Test Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Decision</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{decision}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Notes</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{notes}}</td></tr>"
            "</table>",
            ["Asset Data Officer", "Reviewing Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] Procurement {{pr_number}} {{decision}}."
            " Req: {{request.number}}. Notes: {{notes}}.",
            ["Asset Data Officer"],
        ),
        _i(
            "Procurement {{decision}} — {{pr_number}}",
            "PR {{pr_number}} ({{request.number}}) has been {{decision}} by Finance. Notes: {{notes}}.",
            ["Asset Data Officer", "Reviewing Officer"],
        ),
    )

    # ── Equipment Lifecycle ───────────────────────────────────────────────────
    _tmpl("equipment_registered",
        _e(
            "[NEW EQUIPMENT] {{equipment.ueic}} Commissioned — {{equipment.type}}",
            "<h3 style='color:#1E3C72'>New Equipment Registered in SEACMS</h3>"
            "<p>A new equipment record has been created on {{system.date}}.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>UEIC</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Manufacturer</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.manufacturer}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Substation / Bay</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Commissioned By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{commissioned_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
            "</table>"
            "<p>Log in to SEACMS to review the equipment details and configure test schedules.</p>",
            ["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        _s(
            "[KPTCL-SEACMS] New equipment registered: {{equipment.ueic}} ({{equipment.type}})"
            " at {{equipment.department}} on {{system.date}} by {{commissioned_by}}.",
            ["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        _i(
            "New equipment — {{equipment.ueic}}",
            "{{equipment.type}} ({{equipment.ueic}}) commissioned at {{equipment.department}} by {{commissioned_by}}.",
            ["AEE_MAINTENANCE", "EE_TLSS"],
        ),
    )

    _tmpl("equipment_retired",
        _e(
            "[RETIRED] {{equipment.ueic}} — {{equipment.type}} Decommissioned",
            "<h3 style='color:#555'>Equipment Retired from Service</h3>"
            "<p>The following equipment has been decommissioned on {{system.date}}.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>UEIC</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Substation / Bay</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{reason}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Retired By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{retired_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
            "</table>"
            "<p>All pending test schedules for this equipment have been cancelled. Log in to SEACMS to confirm.</p>",
            ["AEE_MAINTENANCE", "EE_TLSS", "SEE_WM"],
        ),
        _s(
            "[KPTCL-SEACMS] Equipment {{equipment.ueic}} ({{equipment.type}}) at"
            " {{equipment.department}} RETIRED on {{system.date}}. Reason: {{reason}}.",
            ["AEE_MAINTENANCE", "EE_TLSS"],
        ),
        _i(
            "Equipment retired — {{equipment.ueic}}",
            "{{equipment.type}} ({{equipment.ueic}}) at {{equipment.department}} has been decommissioned. Reason: {{reason}}.",
            ["AEE_MAINTENANCE", "EE_TLSS", "SEE_WM"],
        ),
    )

    # ── Remedial / Compliance ─────────────────────────────────────────────────
    _tmpl("remedial_action_due",
        _e(
            "[ACTION REQUIRED] Remedial Compliance Not Uploaded — {{request.number}}",
            "<h3 style='color:red'>Remedial Action Compliance Overdue</h3>"
            "<p>The remedial action compliance document has not been uploaded by the due date.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Compliance Due</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{compliance_due_date}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Overdue</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_overdue}}</td></tr>"
            "</table>"
            "<p>Please upload the compliance proof immediately in SEACMS.</p>",
            ["Field Officer", "Reviewing Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] Remedial compliance NOT uploaded for {{request.number}}"
            " ({{equipment.ueic}}). Due: {{compliance_due_date}}. Upload in SEACMS.",
            ["Field Officer", "Reviewing Officer"],
        ),
        _i(
            "Remedial compliance overdue — {{request.number}}",
            "Compliance for {{request.number}} ({{equipment.ueic}}) was due {{compliance_due_date}}"
            " and is now {{days_overdue}} day(s) overdue.",
            ["Field Officer", "Reviewing Officer"],
        ),
    )

    _tmpl("taqc_observation_overdue",
        _e(
            "[TAQC] Observation Compliance Not Uploaded — {{request.number}}",
            "<h3 style='color:orange'>TA&amp;QC Observation Compliance Overdue</h3>"
            "<p>The compliance document for a TA&amp;QC observation has not been uploaded by the target date.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Target Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{compliance_due_date}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Overdue</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_overdue}}</td></tr>"
            "</table>"
            "<p>Please upload the compliance document in SEACMS immediately.</p>",
            ["Reviewing Officer", "Supervisory Officer", "Senior Management Approver"],
        ),
        _s(
            "[KPTCL-SEACMS] TA&QC compliance NOT uploaded. Req:{{request.number}}"
            " ({{equipment.ueic}}). Target: {{compliance_due_date}}. Upload in SEACMS.",
            ["Reviewing Officer", "Supervisory Officer"],
        ),
        _i(
            "TA&QC compliance overdue — {{request.number}}",
            "Observation compliance for {{request.number}} ({{equipment.ueic}})"
            " is {{days_overdue}} day(s) past target {{compliance_due_date}}.",
            ["Reviewing Officer", "Supervisory Officer", "Senior Management Approver"],
        ),
    )

    # ── Maintenance ───────────────────────────────────────────────────────────
    _tmpl("maintenance_due",
        _e(
            "Maintenance Due in {{days_remaining}} Days — {{equipment.ueic}}",
            "<h3 style='color:#1E3C72'>Upcoming Maintenance Due — 15-Day Reminder</h3>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Due Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.due_date}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Remaining</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_remaining}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Request</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "</table>"
            "<p>Please ensure maintenance resources and outage window are scheduled.</p>",
            ["Maintenance Officer", "Nodal Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] Maintenance due in {{days_remaining}} days for {{equipment.ueic}}"
            " at {{equipment.department}}. Due: {{request.due_date}}.",
            ["Maintenance Officer", "Nodal Officer"],
        ),
        _i(
            "Maintenance due in {{days_remaining}} days — {{equipment.ueic}}",
            "Request {{request.number}} for {{equipment.ueic}} maintenance is due on {{request.due_date}}.",
            ["Maintenance Officer", "Nodal Officer"],
        ),
    )

    _tmpl("overhaul_recommended",
        _e(
            "[OVERHAUL] Operation Count Threshold Reached — {{equipment.ueic}}",
            "<h3 style='color:darkorange'>Overhaul Recommendation — Operation Threshold Exceeded</h3>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Operations Count</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{operation_count}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Threshold</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{operation_threshold}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Recommendation Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
            "</table>"
            "<p>An overhaul is recommended. Please raise a maintenance request in SEACMS.</p>",
            ["Maintenance Officer", "Reviewing Officer", "Supervisory Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] Overhaul needed: {{equipment.ueic}} ({{equipment.type}}) at"
            " {{equipment.department}}. Operations: {{operation_count}}/{{operation_threshold}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Overhaul recommended — {{equipment.ueic}}",
            "{{equipment.type}} ({{equipment.ueic}}) has reached {{operation_count}} operations"
            " (threshold: {{operation_threshold}}). Overhaul recommended.",
            ["Maintenance Officer", "Reviewing Officer", "Supervisory Officer"],
        ),
    )

    # ── Design / Systemic Issues ──────────────────────────────────────────────
    _tmpl("design_problem_alert",
        _e(
            "[DESIGN ALERT] Problem Detected on {{equipment.manufacturer}} {{equipment.type}}",
            "<h3 style='color:darkred'>Design Problem Alert — All Affected Equipment</h3>"
            "<p>A systemic design problem has been identified linked to a specific make/model.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Manufacturer</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.manufacturer}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Problem Description</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{problem_description}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Affected Count</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{affected_count}} units</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Identified On</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
            "</table>"
            "<p>Inspect all {{equipment.type}} units of this make immediately. Log in to SEACMS for the affected equipment list.</p>",
            ["Maintenance Officer", "Reviewing Officer", "Supervisory Officer"],
        ),
        _s(
            "[KPTCL-SEACMS] DESIGN ALERT: {{equipment.manufacturer}} {{equipment.type}}."
            " {{affected_count}} units affected. Problem: {{problem_description}}. Login SEACMS.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Design problem — {{equipment.manufacturer}} {{equipment.type}}",
            "Systemic problem detected on {{equipment.manufacturer}} {{equipment.type}}:"
            " {{problem_description}}. {{affected_count}} unit(s) affected.",
            ["Maintenance Officer", "Reviewing Officer", "Supervisory Officer"],
        ),
    )

    # ── Repair Cycle ──────────────────────────────────────────────────────────
    _tmpl("repair_delay",
        _e(
            "[REPAIR DELAY] Stage Timeline Exceeded — {{equipment.ueic}}",
            "<h3 style='color:darkorange'>Transformer Repair Delay Alert</h3>"
            "<p>A repair stage has exceeded its scheduled timeline.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Repair Stage</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{repair_stage}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Stage Deadline</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{stage_deadline}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Delayed</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{days_delayed}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.department}}</td></tr>"
            "</table>"
            "<p>Please review and update the repair timeline in SEACMS.</p>",
            ["Reviewing Officer", "Senior Management Approver", "CEE RT&R&D"],
        ),
        _s(
            "[KPTCL-SEACMS] REPAIR DELAY: {{equipment.ueic}} stage '{{repair_stage}}'"
            " is {{days_delayed}} days overdue (deadline: {{stage_deadline}}).",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _i(
            "Repair delay — {{equipment.ueic}} ({{repair_stage}})",
            "Repair stage '{{repair_stage}}' for {{equipment.ueic}} is {{days_delayed}}"
            " day(s) past deadline {{stage_deadline}}.",
            ["Reviewing Officer", "Senior Management Approver", "CEE RT&R&D"],
        ),
    )

    # ── Reports ───────────────────────────────────────────────────────────────
    _tmpl("monthly_mis_report",
        _ea(
            "[MONTHLY MIS] SEACMS Monthly Report — {{report_month}}",
            "<h3 style='color:#1E3C72'>Monthly MIS Report — {{report_month}}</h3>"
            "<p>Your monthly equipment management report is ready for {{report_month}}.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Report Period</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{report_month}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Generated On</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{report.generated_on}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Tests Completed</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{tests_completed}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Critical Findings</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{critical_count}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Overdue Tests</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{overdue_count}}</td></tr>"
            "</table>"
            "<p>The PDF and Excel reports are attached to this email.</p>",
            ["Supervisory Officer", "Senior Management Approver"],
            [
                {"var_key": "report.retriepdf",  "type": "pdf"},
                {"var_key": "report.retriexls", "type": "excel"},
            ],
        ),
        _i(
            "Monthly MIS Report — {{report_month}} ready",
            "The SEACMS MIS report for {{report_month}} is available."
            " Tests: {{tests_completed}}, Critical: {{critical_count}}, Overdue: {{overdue_count}}.",
            ["Supervisory Officer", "Senior Management Approver"],
        ),
    )

    # ── Failure Registry ──────────────────────────────────────────────────────
    _tmpl("fr_submitted",
        _e(
            "[FAILURE REGISTER] New Entry Submitted — {{fr_number}}",
            "<h3 style='color:#1a73e8'>Failure Register Entry Submitted</h3>"
            "<p>A new failure register entry has been submitted and is awaiting your review.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Entry Reference</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{fr_number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Submitted By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{originator}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
            "</table>"
            "<p>Please log in to SEACMS to review and take action on this entry.</p>",
            ["Test & Work Coordinator", "Reviewing Officer"],
        ),
        _i(
            "New failure register entry — {{fr_number}}",
            "A new failure register entry {{fr_number}} for {{equipment}} has been submitted by {{originator}}.",
            ["Test & Work Coordinator", "Reviewing Officer"],
        ),
    )

    _tmpl("fr_approved",
        _e(
            "[FAILURE REGISTER] Entry Approved — {{fr_number}}",
            "<h3 style='color:#27ae60'>Failure Register Entry Approved</h3>"
            "<p>Your failure register entry has been reviewed and approved.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Entry Reference</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{fr_number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Approved By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{approved_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Next Action</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{next_action}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
            "</table>",
            ["Asset Data Officer", "Maintenance Officer"],
        ),
        _i(
            "Failure register approved — {{fr_number}}",
            "Failure register entry {{fr_number}} for {{equipment}} has been approved by {{approved_by}}."
            " Next action: {{next_action}}.",
            ["Asset Data Officer", "Maintenance Officer"],
        ),
    )

    _tmpl("fr_rejected",
        _e(
            "[FAILURE REGISTER] Entry Rejected — {{request.number}}",
            "<h3 style='color:#c0392b'>Failure Register Entry Rejected</h3>"
            "<p>A failure register entry you submitted has been rejected and requires revision.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Entry Reference</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{request.number}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Rejected By</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{rejected_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{rejection_reason}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Date</b></td><td style='padding:4px 8px;border:1px solid #ddd'>{{system.date}}</td></tr>"
            "</table>"
            "<p>Please log in to SEACMS, review the rejection reason, and resubmit a corrected entry.</p>",
            ["Reviewing Officer", "Test & Work Coordinator"],
        ),
        _i(
            "Failure register rejected — {{request.number}}",
            "Failure register entry {{request.number}} for {{equipment.ueic}} was rejected by {{rejected_by}}."
            " Reason: {{rejection_reason}}.",
            ["Reviewing Officer", "Test & Work Coordinator"],
        ),
    )

    # ── Repair Lifecycle ──────────────────────────────────────────────────────
    _tmpl("repair_stage_changed",
        _e(
            "[REPAIR] Stage Advanced — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#1E3C72'>Repair Workflow Stage Advanced</h3>"
            "<p>The repair workflow for the following equipment has advanced to the next stage.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Current Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{stage}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Progress</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{progress}}%</td></tr>"
            "</table>"
            "<p>Please log in to SEACMS to view the current stage and take any required action.</p>",
            ["Test Engineer", "Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Repair stage advanced — {{equipment}}",
            "Repair stage for {{equipment}} ({{equipment_type}}) has advanced"
            " to '{{stage}}'. Progress: {{progress}}%.",
            ["Test Engineer", "Maintenance Officer", "Reviewing Officer"],
        ),
    )

    # ── Overhaul Lifecycle ────────────────────────────────────────────────────
    _tmpl("overhaul_stage_changed",
        _e(
            "[OVERHAUL] Stage Advanced — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#1E3C72'>Overhaul Workflow Stage Advanced</h3>"
            "<p>The overhaul workflow has advanced to the next stage.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Current Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{stage}}</td></tr>"
            "</table>",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Overhaul stage advanced — {{equipment}}",
            "Overhaul stage for {{equipment}} ({{equipment_type}}) has advanced"
            " to '{{stage}}'.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    _tmpl("overhaul_stage_delay",
        _e(
            "[OVERHAUL DELAY] Stage Rejected — {{equipment.ueic}}",
            "<h3 style='color:darkorange'>Overhaul Delay Alert</h3>"
            "<p>An overhaul stage has been rejected and sent back, indicating a delay.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Overhaul Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{repair_stage}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Stage Deadline</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{stage_deadline}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Delayed</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{days_delayed}}</td></tr>"
            "</table>"
            "<p>Please review and update the overhaul timeline in SEACMS.</p>",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "[KPTCL-SEACMS] OVERHAUL DELAY: {{equipment.ueic}} stage '{{repair_stage}}'"
            " is {{days_delayed}} days overdue (deadline: {{stage_deadline}}).",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _i(
            "Overhaul delay — {{equipment.ueic}} ({{repair_stage}})",
            "Overhaul stage '{{repair_stage}}' for {{equipment.ueic}} was rejected,"
            " causing a delay of {{days_delayed}} day(s). Deadline: {{stage_deadline}}.",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
    )

    # ── Calibration Lifecycle ──────────────────────────────────────────────────
    _tmpl("calibration_stage_changed",
        _e(
            "[CALIBRATION] Stage Advanced — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#1E3C72'>Calibration Workflow Stage Advanced</h3>"
            "<p>The calibration workflow has advanced to the next stage.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Current Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{stage}}</td></tr>"
            "</table>",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Calibration stage advanced — {{equipment}}",
            "Calibration stage for {{equipment}} ({{equipment_type}}) has advanced"
            " to '{{stage}}'.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    _tmpl("calibration_stage_delay",
        _e(
            "[CALIBRATION DELAY] Stage Rejected — {{equipment.ueic}}",
            "<h3 style='color:darkorange'>Calibration Delay Alert</h3>"
            "<p>A calibration stage has been rejected and sent back, indicating a delay.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Calibration Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{repair_stage}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Delayed</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{days_delayed}}</td></tr>"
            "</table>"
            "<p>Please review and update the calibration timeline in SEACMS.</p>",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "[KPTCL-SEACMS] CALIBRATION DELAY: {{equipment.ueic}} stage '{{repair_stage}}'"
            " is {{days_delayed}} days overdue.",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _i(
            "Calibration delay — {{equipment.ueic}} ({{repair_stage}})",
            "Calibration stage '{{repair_stage}}' for {{equipment.ueic}} was rejected,"
            " causing a delay of {{days_delayed}} day(s).",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
    )

    # ── Surveillance Lifecycle ─────────────────────────────────────────────────
    _tmpl("surveillance_stage_changed",
        _e(
            "[SURVEILLANCE] Stage Advanced — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#1E3C72'>Surveillance Workflow Stage Advanced</h3>"
            "<p>The surveillance workflow has advanced to the next stage.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Current Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{stage}}</td></tr>"
            "</table>",
            ["Maintenance Officer", "Reviewing Officer", "Supervisory Officer"],
        ),
        _i(
            "Surveillance stage advanced — {{equipment}}",
            "Surveillance stage for {{equipment}} ({{equipment_type}}) has advanced"
            " to '{{stage}}'.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    _tmpl("surveillance_stage_delay",
        _e(
            "[SURVEILLANCE DELAY] Stage Rejected — {{equipment.ueic}}",
            "<h3 style='color:darkorange'>Surveillance Delay Alert</h3>"
            "<p>A surveillance stage has been rejected and sent back, indicating a delay.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Surveillance Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{repair_stage}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Delayed</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{days_delayed}}</td></tr>"
            "</table>"
            "<p>Please review and update the surveillance timeline in SEACMS.</p>",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "[KPTCL-SEACMS] SURVEILLANCE DELAY: {{equipment.ueic}} stage '{{repair_stage}}'"
            " is {{days_delayed}} days overdue.",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _i(
            "Surveillance delay — {{equipment.ueic}} ({{repair_stage}})",
            "Surveillance stage '{{repair_stage}}' for {{equipment.ueic}} was rejected,"
            " causing a delay of {{days_delayed}} day(s).",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
    )

    _tmpl("repair_cancelled",
        _e(
            "[REPAIR] Workflow Cancelled — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#B00020'>Repair Workflow Cancelled</h3>"
            "<p>The repair workflow for {{equipment}} has been cancelled.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Cancelled By</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancelled_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancel_reason}}</td></tr>"
            "</table>"
            "<p>Review the cancelled workflow in SEACMS for next steps.</p>",
            ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "Repair workflow for {{equipment}} was cancelled by {{cancelled_by}}. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Repair workflow cancelled — {{equipment}}",
            "The repair workflow for {{equipment}} has been cancelled. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    _tmpl("overhaul_cancelled",
        _e(
            "[OVERHAUL] Workflow Cancelled — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#B00020'>Overhaul Workflow Cancelled</h3>"
            "<p>The overhaul workflow for {{equipment}} has been cancelled.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Cancelled By</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancelled_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancel_reason}}</td></tr>"
            "</table>"
            "<p>Review the cancelled workflow in SEACMS for next steps.</p>",
            ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "Overhaul workflow for {{equipment}} was cancelled by {{cancelled_by}}. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Overhaul workflow cancelled — {{equipment}}",
            "The overhaul workflow for {{equipment}} has been cancelled. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    _tmpl("calibration_cancelled",
        _e(
            "[CALIBRATION] Workflow Cancelled — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#B00020'>Calibration Workflow Cancelled</h3>"
            "<p>The calibration workflow for {{equipment}} has been cancelled.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Cancelled By</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancelled_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancel_reason}}</td></tr>"
            "</table>"
            "<p>Review the cancelled workflow in SEACMS for next steps.</p>",
            ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "Calibration workflow for {{equipment}} was cancelled by {{cancelled_by}}. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Calibration workflow cancelled — {{equipment}}",
            "The calibration workflow for {{equipment}} has been cancelled. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    _tmpl("surveillance_cancelled",
        _e(
            "[SURVEILLANCE] Workflow Cancelled — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#B00020'>Surveillance Workflow Cancelled</h3>"
            "<p>The surveillance workflow for {{equipment}} has been cancelled.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Cancelled By</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancelled_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancel_reason}}</td></tr>"
            "</table>"
            "<p>Review the cancelled workflow in SEACMS for next steps.</p>",
            ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "Surveillance workflow for {{equipment}} was cancelled by {{cancelled_by}}. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Surveillance workflow cancelled — {{equipment}}",
            "The surveillance workflow for {{equipment}} has been cancelled. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    # ── Annual Audit Workflow Notifications ────────────────────────────────────
    _tmpl("annual_audit_stage_changed",
        _e(
            "[ANNUAL AUDIT] Stage Advanced — {{equipment}} ({{stage}})",
            "<h3 style='color:#1E3C72'>Annual Audit Stage Update</h3>"
            "<p>The annual audit workflow has advanced to a new stage.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Current Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{stage}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Progress</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{progress}}%</td></tr>"
            "</table>"
            "<p>Log in to SEACMS to view the latest audit stage progress.</p>",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "[KPTCL-SEACMS] Annual Audit stage '{{stage}}' reached for {{equipment}} ({{progress}}% complete).",
            ["Reviewing Officer"],
        ),
        _i(
            "Annual Audit advanced — {{stage}}",
            "Annual audit for {{equipment}} is now at stage '{{stage}}' ({{progress}}% complete).",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
    )

    _tmpl("annual_audit_stage_delay",
        _e(
            "[ANNUAL AUDIT DELAY] Stage Rejected — {{equipment.ueic}}",
            "<h3 style='color:darkorange'>Annual Audit Delay Alert</h3>"
            "<p>An annual audit stage has been rejected and sent back, indicating a delay.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Audit Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{repair_stage}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Delayed</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{days_delayed}}</td></tr>"
            "</table>"
            "<p>Please review and update the annual audit timeline in SEACMS.</p>",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "[KPTCL-SEACMS] ANNUAL AUDIT DELAY: {{equipment.ueic}} stage '{{repair_stage}}'"
            " is {{days_delayed}} days overdue.",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _i(
            "Annual audit delay — {{equipment.ueic}} ({{repair_stage}})",
            "Annual audit stage '{{repair_stage}}' for {{equipment.ueic}} was rejected,"
            " causing a delay of {{days_delayed}} day(s).",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
    )

    _tmpl("annual_audit_cancelled",
        _e(
            "[ANNUAL AUDIT] Workflow Cancelled — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#B00020'>Annual Audit Workflow Cancelled</h3>"
            "<p>The annual audit workflow for {{equipment}} has been cancelled.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Cancelled By</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancelled_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancel_reason}}</td></tr>"
            "</table>"
            "<p>Review the cancelled workflow in SEACMS for next steps.</p>",
            ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "Annual Audit workflow for {{equipment}} was cancelled by {{cancelled_by}}. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Annual audit workflow cancelled — {{equipment}}",
            "The annual audit workflow for {{equipment}} has been cancelled. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    # ── Pre-Commission Workflow Notifications ──────────────────────────────────
    _tmpl("precommission_stage_changed",
        _e(
            "[PRE-COMMISSION] QAP Stage Advanced — {{equipment}} ({{stage}})",
            "<h3 style='color:#1E3C72'>Pre-Commission QAP Stage Update</h3>"
            "<p>The pre-commission QAP workflow has advanced to a new stage.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Current Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{stage}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Progress</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{progress}}%</td></tr>"
            "</table>"
            "<p>Log in to SEACMS to view the QAP stage progress.</p>",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "[KPTCL-SEACMS] Pre-Commission QAP stage '{{stage}}' reached for {{equipment}} ({{progress}}% complete).",
            ["Reviewing Officer"],
        ),
        _i(
            "Pre-Commission QAP advanced — {{stage}}",
            "Pre-commission for {{equipment}} is now at QAP stage '{{stage}}' ({{progress}}% complete).",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
    )

    _tmpl("precommission_stage_delay",
        _e(
            "[PRE-COMMISSION DELAY] QAP Stage Rejected — {{equipment.ueic}}",
            "<h3 style='color:darkorange'>Pre-Commission QAP Delay Alert</h3>"
            "<p>A pre-commission QAP stage has been rejected and sent back, indicating a delay.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment.ueic}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>QAP Stage</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{repair_stage}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Days Delayed</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{days_delayed}}</td></tr>"
            "</table>"
            "<p>Please review and update the pre-commission QAP timeline in SEACMS.</p>",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "[KPTCL-SEACMS] PRE-COMMISSION DELAY: {{equipment.ueic}} QAP stage '{{repair_stage}}'"
            " is {{days_delayed}} days overdue.",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
        _i(
            "Pre-commission QAP delay — {{equipment.ueic}} ({{repair_stage}})",
            "Pre-commission QAP stage '{{repair_stage}}' for {{equipment.ueic}} was rejected,"
            " causing a delay of {{days_delayed}} day(s).",
            ["Reviewing Officer", "Senior Management Approver"],
        ),
    )

    _tmpl("precommission_cancelled",
        _e(
            "[PRE-COMMISSION] Workflow Cancelled — {{equipment}} ({{equipment_type}})",
            "<h3 style='color:#B00020'>Pre-Commission Workflow Cancelled</h3>"
            "<p>The pre-commission workflow for {{equipment}} has been cancelled.</p>"
            "<table cellspacing='0' style='border-collapse:collapse;font-size:13px;width:100%'>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Equipment</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Type</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{equipment_type}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Department</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{department}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Cancelled By</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancelled_by}}</td></tr>"
            "<tr><td style='padding:4px 8px;border:1px solid #ddd'><b>Reason</b></td>"
            "<td style='padding:4px 8px;border:1px solid #ddd'>{{cancel_reason}}</td></tr>"
            "</table>"
            "<p>Review the cancelled workflow in SEACMS for next steps.</p>",
            ["Maintenance Officer", "Reviewing Officer", "Senior Management Approver"],
        ),
        _s(
            "Pre-commission workflow for {{equipment}} was cancelled by {{cancelled_by}}. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
        _i(
            "Pre-commission workflow cancelled — {{equipment}}",
            "The pre-commission workflow for {{equipment}} has been cancelled. Reason: {{cancel_reason}}.",
            ["Maintenance Officer", "Reviewing Officer"],
        ),
    )

    # ── Upsert into DB ────────────────────────────────────────────────────────
    inserted = 0
    for tpl in _TEMPLATES:
        existing = (
            session.query(NotificationTemplate)
            .filter(
                NotificationTemplate.event_type == tpl["event_type"],
                NotificationTemplate.channel    == tpl["channel"],
                NotificationTemplate.organization_id.is_(None),
            )
            .first()
        )
        if existing:
            existing.subject_template = tpl.get("subject_template", existing.subject_template)
            existing.body_template    = tpl["body_template"]
            existing.recipient_roles  = tpl.get("recipient_roles", existing.recipient_roles)
            existing.attachment_vars  = tpl.get("attachment_vars", existing.attachment_vars or [])
        else:
            session.add(NotificationTemplate(**tpl))
            inserted += 1

    session.commit()
    _logger.info(
        f"[Seed] Notification templates: {inserted} new inserted"
        f" ({len(_TEMPLATES) - inserted} refreshed)."
    )
    return inserted


def _seed_notification_schedule_rules(session) -> int:
    """
    Idempotent seed for NotificationScheduleRule rows.
    Matches on event_type + trigger_type + offset_days + trigger_on_status + frequency
    (the full natural key from uq_notif_schedule_rule_v3) — won't duplicate on re-run.

    frequency semantics:
      None         — fires once per day while the trigger condition is true (default).
      "weekly"     — re-fires every 7 days; good for ongoing overdue reminders.
      "biweekly"   — every 14 days.
      "monthly"    — every 30 days; good for inspection/maintenance cadence summaries.
      "semi_annual"— every 6 months; compliance health-check intervals.
      "yearly"     — annual audit / calibration reminders.
      "recurring"  — trigger_type="recurring" fires purely on the frequency with no
                     date condition (used for periodic status digests, MIS reports, etc.)

    To add a new scheduler-based notification:
      1. Insert a row here (or directly in the DB).
      2. Ensure a NotificationTemplate exists for the event_type.
      Zero code change to main.py or notification_service.py is needed.
    """
    from models import NotificationScheduleRule

    # ── Default digest table columns ─────────────────────────────────────────
    # Stored in the DB on each schedule rule so admins can customise per-rule
    # from the Notification Center UI without touching code.
    # Rules that don't produce digest emails leave digest_columns=None.
    _DIGEST_COLS_DUE = [
        {"field": "equipment",  "header": "Equipment"},
        {"field": "department", "header": "Department"},
        {"field": "due_date",   "header": "Due Date"},
        {"field": "days",       "header": "Days Remaining"},
        {"field": "request",    "header": "Request No."},
        {"field": "status",     "header": "Status"},
    ]
    _DIGEST_COLS_OVERDUE = [
        {"field": "equipment",  "header": "Equipment"},
        {"field": "department", "header": "Department"},
        {"field": "due_date",   "header": "Was Due"},
        {"field": "days",       "header": "Days Overdue"},
        {"field": "request",    "header": "Request No."},
        {"field": "assigned_to","header": "Assigned To"},
        {"field": "status",     "header": "Status"},
    ]

    _DEFAULT_RULES = [
        # ── Due-date reminders (one-shot — no frequency; fires once when window opens) ──

        # SRS §8.2 #1 — 15-day early reminder
        dict(
            event_type="due_reminder",
            label="Test Due Reminder — 15 days before",
            trigger_type="due_soon",
            offset_days=15,
            severity="info",
            frequency=None,
            applicable_categories=[],
            digest_columns=_DIGEST_COLS_DUE,
        ),
        # SRS §8.2 #2 — 7-day final reminder
        dict(
            event_type="due_reminder_final",
            label="Test Due Final Reminder — 7 days before",
            trigger_type="due_soon",
            offset_days=7,
            severity="alert",
            frequency=None,
            applicable_categories=[],
            digest_columns=_DIGEST_COLS_DUE,
        ),

        # ── Overdue alerts (weekly repeat — keep notifying while still overdue) ──────

        # SRS §8.2 #3 — overdue alert, repeats weekly until resolved
        dict(
            event_type="overdue_alert",
            label="Test Overdue — weekly repeat",
            trigger_type="overdue",
            offset_days=0,
            severity="alert",
            frequency="weekly",
            applicable_categories=[],
            digest_columns=_DIGEST_COLS_OVERDUE,
        ),
        # SRS §8.2 #4 — escalation after 7 days overdue, repeats weekly
        dict(
            event_type="overdue_escalation",
            label="Test Overdue Escalation (>7 days) — weekly repeat",
            trigger_type="escalation",
            offset_days=7,
            severity="critical",
            frequency="weekly",
            applicable_categories=[],
            digest_columns=_DIGEST_COLS_OVERDUE,
        ),

        # ── Maintenance ──────────────────────────────────────────────────────────────

        # Maintenance-specific 15-day due reminder
        dict(
            event_type="due_reminder",
            label="Maintenance Due Reminder — 15 days before",
            trigger_type="due_soon",
            offset_days=15,
            severity="info",
            frequency=None,          # one-shot
            applicable_categories=["maintenance"],
        ),
        # Maintenance due event (separate event type for routing rule separation)
        dict(
            event_type="maintenance_due",
            label="Maintenance Due — 15 days before",
            trigger_type="due_soon",
            offset_days=15,
            severity="info",
            frequency=None,          # one-shot
            applicable_categories=["maintenance"],
        ),

        # ── Status-transition triggers (one-shot — fire once on status change) ───────

        # Status-based: fire when request reaches "compliance_pending" status
        dict(
            event_type="remedial_action_due",
            label="Remedial Action — when status is compliance_pending",
            trigger_type="status_transition",
            offset_days=0,
            trigger_on_status="compliance_pending",
            severity="alert",
            frequency=None,          # one-shot on status change
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
            frequency=None,          # one-shot on status change
            applicable_categories=[],
        ),

        # ── Combined time + status (weekly repeat) ───────────────────────────────────

        # Tester still in_progress but 5 days overdue → weekly reminder until resolved
        dict(
            event_type="overdue_alert",
            label="Overdue — in_progress 5 days after due date (weekly)",
            trigger_type="both",
            offset_days=5,
            trigger_on_status="in_progress",
            severity="alert",
            frequency="weekly",      # keep reminding every week while condition holds
            applicable_categories=[],
            advanced_conditions={
                "and": [
                    {"type": "overdue_by", "min_days": 5},
                    {"type": "status",     "on_status": "in_progress"},
                ]
            },
        ),

        # ── Recurring — periodic digests / summaries (no date condition) ─────────────

        # Weekly open-test digest for test coordinators
        dict(
            event_type="due_reminder",
            label="Weekly Open Tests Summary",
            trigger_type="recurring",
            offset_days=0,
            severity="info",
            frequency="weekly",      # fires every Monday (or whichever day scheduler runs)
            applicable_categories=[],
        ),
        # Monthly overdue summary (management visibility)
        dict(
            event_type="overdue_alert",
            label="Monthly Overdue Tests Summary",
            trigger_type="recurring",
            offset_days=0,
            severity="alert",
            frequency="monthly",     # fires once a month for any still-open overdue TRs
            applicable_categories=[],
        ),
        # Bi-annual inspection compliance reminder
        dict(
            event_type="due_reminder",
            label="Six-Month Inspection Compliance Reminder",
            trigger_type="recurring",
            offset_days=0,
            severity="info",
            frequency="semi_annual", # fires every 6 months for inspection-type TRs
            applicable_categories=["inspection"],
        ),
        # Yearly calibration reminder
        dict(
            event_type="due_reminder",
            label="Annual Calibration Reminder",
            trigger_type="recurring",
            offset_days=0,
            severity="info",
            frequency="yearly",      # fires once a year for calibration-type TRs
            applicable_categories=["calibration"],
        ),
    ]

    inserted = 0
    for rule_def in _DEFAULT_RULES:
        # Match on the full natural key (v3): includes frequency so weekly and monthly
        # variants of the same event_type + trigger_type can coexist.
        freq_val = rule_def.get("frequency")
        existing = (
            session.query(NotificationScheduleRule)
            .filter(
                NotificationScheduleRule.organization_id.is_(None),
                NotificationScheduleRule.event_type   == rule_def["event_type"],
                NotificationScheduleRule.trigger_type == rule_def["trigger_type"],
                NotificationScheduleRule.offset_days  == rule_def.get("offset_days", 0),
                (
                    NotificationScheduleRule.trigger_on_status == rule_def["trigger_on_status"]
                    if "trigger_on_status" in rule_def
                    else NotificationScheduleRule.trigger_on_status.is_(None)
                ),
                (
                    NotificationScheduleRule.frequency == freq_val
                    if freq_val is not None
                    else NotificationScheduleRule.frequency.is_(None)
                ),
            )
            .first()
        )
        if existing:
            # Update digest_columns on existing rows so re-seeding keeps
            # the column config in sync (only if rule still has DB default/NULL)
            if existing.digest_columns is None and rule_def.get("digest_columns"):
                existing.digest_columns = rule_def["digest_columns"]
        else:
            # Build kwargs — only pass fields that exist on the model
            kwargs = {
                "event_type":                rule_def["event_type"],
                "label":                     rule_def["label"],
                "trigger_type":              rule_def["trigger_type"],
                "offset_days":               rule_def.get("offset_days", 0),
                "trigger_on_status":         rule_def.get("trigger_on_status"),
                "frequency":                 freq_val,
                "applicable_categories":     rule_def.get("applicable_categories", []),
                "applicable_workflow_types": rule_def.get("applicable_workflow_types", []),
                "advanced_conditions":       rule_def.get("advanced_conditions"),
                "digest_columns":            rule_def.get("digest_columns"),
                "severity":                  rule_def.get("severity", "info"),
                "is_active":                 rule_def.get("is_active", True),
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

        ("status_changed",
         ["testing_request", "taqc_inspection"], [],
         ["email", "inapp"],
         "Test Request Status Changed"),

        # ── Recommendations ───────────────────────────────────────────────────
        ("recommendation_approved",
         [], [],
         ["email", "inapp"],
         "Recommendation Approved — all workflows"),

        ("recommendation_rejected",
         [], [],
         ["email", "inapp"],
         "Recommendation Rejected — all workflows"),

        ("request_rejected",
         ["testing_request"], [],
         ["email", "inapp"],
         "Request Rejected — all workflows"),

        # ── Failure Registry ──────────────────────────────────────────────────
        ("fr_submitted",
         ["failure_registry"], [],
         ["email", "inapp"],
         "Failure Registry Submitted"),

        ("fr_approved",
         ["failure_registry"], [],
         ["email", "inapp"],
         "Failure Registry Approved"),

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
         ["email", "inapp"],
         "Repair Stage Advanced — Email + in-app"),

        ("overhaul_recommended",
         ["repair_lifecycle"], [],
         ["email", "sms"],
         "Overhaul Recommended — Email + SMS"),

        ("repair_delay",
         ["repair_lifecycle"], [],
         ["email", "sms", "inapp"],
         "Repair Stage Delay — Email + SMS + in-app"),

        ("repair_cancelled",
         [], [],
         ["email", "inapp"],
         "Repair Workflow Cancelled — Email + in-app"),

        ("overhaul_cancelled",
         [], [],
         ["email", "inapp"],
         "Overhaul Workflow Cancelled — Email + in-app"),

        ("calibration_cancelled",
         [], [],
         ["email", "inapp"],
         "Calibration Workflow Cancelled — Email + in-app"),

        ("surveillance_cancelled",
         [], [],
         ["email", "inapp"],
         "Surveillance Workflow Cancelled — Email + in-app"),

        # ── Overhaul Lifecycle ────────────────────────────────────────────────
        ("overhaul_stage_changed",
         [], [],
         ["email", "inapp"],
         "Overhaul Stage Advanced — Email + in-app"),

        ("overhaul_stage_delay",
         [], [],
         ["email", "sms", "inapp"],
         "Overhaul Stage Delay — Email + SMS + in-app"),

        # ── Calibration Lifecycle ─────────────────────────────────────────────
        ("calibration_stage_changed",
         [], [],
         ["email", "inapp"],
         "Calibration Stage Advanced — Email + in-app"),

        ("calibration_stage_delay",
         [], [],
         ["email", "sms", "inapp"],
         "Calibration Stage Delay — Email + SMS + in-app"),

        # ── Surveillance Lifecycle ────────────────────────────────────────────
        ("surveillance_stage_changed",
         [], [],
         ["email", "inapp"],
         "Surveillance Stage Advanced — Email + in-app"),

        ("surveillance_stage_delay",
         [], [],
         ["email", "sms", "inapp"],
         "Surveillance Stage Delay — Email + SMS + in-app"),

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
        if existing:
            # Update channels + label so re-seeding corrects stale rows
            existing.channels_enabled = channels
            existing.label = label
        else:
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


# ── Public convenience wrapper ────────────────────────────────────────────────

def seed_notification_defaults(session) -> dict:
    """
    Idempotent seed for ALL notification defaults in dependency order:
      1. event_catalogue  — the 24 canonical event types
      2. variables        — template-variable registry
      3. templates        — default email/sms/inapp templates per event
      4. schedule_rules   — time-based trigger rules (reminders, overdue)
      5. routing_rules    — channel-routing rules per workflow / test type

    Call this from create_tables.py, main.py startup, and the admin
    /seed-defaults endpoint.  There is no need to import any individual
    private seeder outside this file.

    Returns a dict with per-seeder insert counts.
    """
    return {
        "event_catalogue":  _seed_notification_event_catalogue(session),
        "variables":        _seed_notification_variables(session),
        "templates":        _seed_notification_templates(session),
        "schedule_rules":   _seed_notification_schedule_rules(session),
        "routing_rules":    _seed_notification_routing_rules(session),
    }


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
        seed_report_query_keys(session)
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
        seed_taqc_inspection_test_type(session)
        n3 = seed_annual_audit_templates(session)
        print(f"[OK] Annual Audit templates: {n3} seeded.")
        from seed_annual_audit import seed_annual_audit_stages
        seed_annual_audit_stages(session)
        # Ensure the ANNUAL_AUDIT workflow definition exists and all its stage
        # rows carry the correct workflow_definition_id.
        _aa_def = session.query(RepairWorkflowDefinition).filter_by(workflow_code="ANNUAL_AUDIT").first()
        if not _aa_def:
            _aa_def = RepairWorkflowDefinition(
                id=uuid.uuid4(),
                workflow_code="ANNUAL_AUDIT",
                name="Annual Audit Workflow",
                is_active=True,
            )
            session.add(_aa_def)
            session.flush()
        from seed_annual_audit import STAGES as _AA_STAGES
        _aa_codes = [s["code"] for s in _AA_STAGES]
        _aa_stages = session.query(RepairStageDefinition).filter(
            RepairStageDefinition.code.in_(_aa_codes)
        ).all()
        for _s in _aa_stages:
            if _s.workflow_definition_id != _aa_def.id:
                _s.workflow_definition_id = _aa_def.id
        session.flush()
        print(f"[OK] RepairWorkflowDefinition ANNUAL_AUDIT: {_aa_def.id} ({len(_aa_stages)} stages linked)")
        n4 = seed_cumulative_template(session)
        print(f"[OK] Cumulative / Operations Tracking template: {n4} seeded.")
        n5 = seed_calibration_template(session)
        print(f"[OK] Calibration template: {n5} seeded.")
        n5b = seed_dfr_template(session)
        print(f"[OK] DFR / IDAX template: {n5b} seeded.")
        n5c = seed_sfra_template(session)
        print(f"[OK] SFRA template: {n5c} seeded.")
        n5d = seed_tan_delta_templates(session)
        print(f"[OK] Tan-Delta / Capacitance / IDAX test types: {n5d} seeded.")
        n6 = seed_transformer_oil_template(session)
        print(f"[OK] Transformer Oil Test template: {n6} seeded.")
        n6b = seed_transformer_dga_template(session)
        print(f"[OK] Transformer DGA template: {n6b} seeded.")
        n7 = seed_capacitance_tandelta_template(session)
        print(f"[OK] Capacitance & Tan Delta template: {n7} seeded.")
        n8 = seed_inspection_templates(session)
        print(f"[OK] Equipment-specific inspection templates: {n8} migrated.")
        n9 = seed_generic_equipment_templates(session)
        print(f"[OK] Generic equipment templates: {n9} seeded.")

        # Organization Multi-Tenancy System
        print("\n--- Organization System Seeding ---")
        seed_super_admin(session)
        seed_tester_role_module_requirements(session)
        seed_sample_organization(session)

        # Seed KPTCL Organization with Departments
        kptcl_org = seed_kptcl_organization(session)

        if kptcl_org:
            # ── 1. Department hierarchy first — roles/users need depts to exist ──
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

            # Equipment seeding moved after seed_dept_filter_users so RT_EAST/RT_NORTH
            # etc. divisions exist for the substation→division fallback lookup
            pass

        # Sample Equipment (after departments + equipment types exist)
        seed_sample_equipment(session, kptcl_org)

        # Master Schedules — blueprint templates for each equipment type
        print("\n--- Master Schedule Seeding ---")
        try:
            seed_master_schedules(session, kptcl_org)
        except Exception as _e:
            import traceback
            print(f"[WARN] Master schedule seed failed (non-fatal): {_e}")
            traceback.print_exc()

        # Test & Maintenance Schedule Templates — full access for org-admin roles
        print("\n--- Schedule Templates Module Permissions ---")
        try:
            seed_schedule_module_permissions(session)
        except Exception as _e:
            print(f"[WARN] Schedule module permissions failed (non-fatal): {_e}")

        # Test Schedules module — KPTCL-only (pass kptcl_org to scope it)
        print("\n--- Test Schedules Module Permissions (KPTCL) ---")
        try:
            seed_schedule_compliance_module_permissions(session, org=kptcl_org)
        except Exception as _e:
            print(f"[WARN] Test Schedules module permissions failed (non-fatal): {_e}")

        # Approval module permissions — Technical Approver + Org Admin across all orgs
        # Grants can_view + can_approve on Approvals (module 48) and
        # Testing Request Approvals (module 49) so the FR 2-step flow works.
        print("\n--- Approval Role Permissions (FR flow) ---")
        try:
            seed_approval_role_permissions(session)
        except Exception as _e:
            print(f"[WARN] Approval role permissions failed (non-fatal): {_e}")

        # Backfill permissions for roles that had no template or name mismatch:
        # Procurement Approver, TA&QC Inspector, Test Engineer, Reviewing Officer
        print("\n--- Missing Role Permissions Backfill (KPTCL) ---")
        try:
            seed_missing_role_permissions(session, org=kptcl_org)
        except Exception as _e:
            print(f"[WARN] Missing role permissions backfill failed (non-fatal): {_e}")

        # Zoho Import Mapping — moved after seacms so Asset Data Officer role exists
        
        # Org role permissions — AFTER all orgs + org_roles are created
        # DISABLED: This grants VIEW to ALL modules for ALL roles, breaking RBAC
        # Proper permissions are already set via role templates during org role provisioning
        # seed_org_role_permissions_for_modules(session, module_ids)

        # Notification defaults moved after seed_seacms_roles_users so OrgRole
        # names are available for _VALID_ROLES validation in event catalogue
            traceback.print_exc()

        # Repair Workflow — stages, templates, transitions only (roles deferred)
        print("\n--- Repair Workflow Seeding ---")
        try:
            import inspect

            print("FUNCTION:", seed_workflow)
            print("MODULE:", seed_workflow.__module__)
            print("SIGNATURE:", inspect.signature(seed_workflow))
            seed_workflow(session, skip_roles=True)
        except Exception as _e:
            print(f"[WARN] Repair workflow seed failed (non-fatal): {_e}")

        # === Surveillance Migrations ===
        print("\n" + "=" * 80)
        print("  SURVEILLANCE WORKFLOW MIGRATIONS")
        print("=" * 80)

        # Migration 008: Create surveillance tables (surveillance_config, surveillance_test_config, repair_surveillance_tests)
        # + Add surveillance_workflow_id/surveillance_quarter to testing_requests
        # + Add quarter_number to repair_stage_instances
        migration_008_ok = run_migration_from_file(
            session,
            "migrations/008_surveillance_workflow.sql",
            "Migration 008: Surveillance Workflow Schema"
        )

        # Migration 013: Add surveillance linkage to test_request_schedules
        # (surveillance_workflow_id, surveillance_quarter columns + index)
        migration_013_ok = run_migration_from_file(
            session,
            "migrations/013_add_surveillance_to_schedules.sql",
            "Migration 013: Surveillance Schedule Linkage"
        )

        if not migration_008_ok or not migration_013_ok:
            print("\n[WARN] Some migrations failed — surveillance seeding may fail")

        print("\n--- Surveillance Workflow Seeding ---")
        try:
            from seed_surveillance_workflow import seed_surveillance_stages
            seed_surveillance_stages(session)
            seed_surveillance_config(session)
        except Exception as _e:
            print(f"[WARN] Surveillance workflow seed failed (non-fatal): {_e}")

        # Overhaul Workflow — definition + stages for cumulative threshold trigger
        try:
            from seed_overhaul_workflow import seed_overhaul_stages
            seed_overhaul_stages(session)
        except Exception as _e:
            print(f"[WARN] Overhaul workflow seed failed (non-fatal): {_e}")

        # Calibration Workflow — definition + stages for DATE_ADD fail trigger
        try:
            from seed_calibration_workflow import seed_calibration_stages
            seed_calibration_stages(session)
        except Exception as _e:
            print(f"[WARN] Calibration workflow seed failed (non-fatal): {_e}")

        # Pre-Commission QAP Workflow — 9-stage factory inspection workflow
        print("\n--- Pre-Commission QAP Workflow Seeding ---")
        try:
            from seed_precommission_workflow import seed_precommission_stages
            seed_precommission_stages(session)
        except Exception as _e:
            print(f"[WARN] Pre-commission workflow seed failed (non-fatal): {_e}")

        # NOTE: All workflow role mappings moved after seed_seacms_roles_users
        # so KPTCL OrgRoles exist before stage→role assignments are made

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

        # ── KPTCL Org Roles + Users — LAST, after ALL departments exist ──────────
        # BLR_CIRCLE, RT_NORTH, RT_EAST etc. are created by seed_dept_filter_users.
        # Must run after both seed_kptcl_departments AND seed_dept_filter_users.
        print("\n--- KPTCL Org Roles & Demo Users (seed_seacms_roles_users) ---")
        try:
            from seed_seacms_roles_users import seed as seed_seacms_roles_users
            seed_seacms_roles_users()
        except Exception as _e:
            import traceback
            print(f"[WARN] KPTCL org roles seed failed (non-fatal): {_e}")
            traceback.print_exc()

        # System Administrator — elevate to org-admin + full module permissions
        # Must run after seed_seacms_roles_users so OrgRoles exist
        print("\n--- System Administrator Permissions ---")
        try:
            seed_system_admin_permissions(session)
        except Exception as _e:
            print(f"[WARN] System Administrator permissions failed (non-fatal): {_e}")

        # Zoho + Notifications — after seacms so roles and users exist
        seed_zoho_import_mapping(session, kptcl_org)
        seed_notifications_module_and_permissions(session)

        # Role templates — must precede notification defaults so _rt_map resolves
        print("\n--- Role Templates Seeding ---")
        try:
            seed_role_templates(session)
            print("[OK] Role templates seeded.")
        except Exception as _e:
            import traceback
            print(f"[WARN] Role templates seed failed (non-fatal): {_e}")
            traceback.print_exc()

        # Notification defaults — after seacms so OrgRole names pass _VALID_ROLES check
        print("\n--- Notification Defaults Seeding ---")
        try:
            _nc = seed_notification_defaults(session)
            print(f"[OK] Event catalogue  : {_nc['event_catalogue']} inserted (0 = already seeded)")
            print(f"[OK] Variables        : {_nc['variables']} inserted (0 = already seeded)")
            print(f"[OK] Templates        : {_nc['templates']} inserted (0 = already seeded)")
            print(f"[OK] Schedule rules   : {_nc['schedule_rules']} inserted (0 = already seeded)")
            print(f"[OK] Routing rules    : {_nc['routing_rules']} inserted (0 = already seeded)")
        except Exception as _e:
            import traceback
            print(f"[WARN] Notification defaults seed failed (non-fatal): {_e}")
            traceback.print_exc()

        # ── All workflow role mappings — after seed_seacms_roles_users ───────────
        # OrgRoles (EE_TLSS, AEE_MAINTENANCE, etc.) must exist before stage→role

        # Repair workflow role assignments (stages already seeded above)
        print("\n--- Repair Workflow Role Assignments ---")
        try:
            import inspect

            print("FUNCTION:", seed_workflow)
            print("MODULE:", seed_workflow.__module__)
            print("SIGNATURE:", inspect.signature(seed_workflow))
            seed_workflow(session, skip_roles=False)
        except Exception as _e:
            print(f"[WARN] Repair workflow role assignment failed (non-fatal): {_e}")

        if kptcl_org:
            try:
                from seed_overhaul_workflow import seed_overhaul_role_mappings
                seed_overhaul_role_mappings(session, kptcl_org.id)
            except Exception as _e:
                session.rollback()
                print(f"[WARN] Overhaul role mapping failed: {_e}")

            try:
                from seed_calibration_workflow import seed_calibration_role_mappings
                seed_calibration_role_mappings(session, kptcl_org.id)
            except Exception as _e:
                session.rollback()
                print(f"[WARN] Calibration role mapping failed: {_e}")

            try:
                from seed_surveillance_workflow import seed_surveillance_role_mappings
                seed_surveillance_role_mappings(session, kptcl_org.id)
            except Exception as _e:
                session.rollback()
                print(f"[WARN] Surveillance role mapping failed: {_e}")

        if kptcl_org:
            try:
                from seed_precommission_workflow import seed_precommission_role_mappings
                seed_precommission_role_mappings(session, kptcl_org.id)
            except Exception as _e:
                session.rollback()
                print(f"[WARN] Pre-commission role mapping failed: {_e}")

        # Ensure RT substations that are in equipment_seed.xlsx but not in
        # KPTCL_Substation_Mapping.xlsx exist before equipment seeding runs.
        # Each dept is committed individually so a later rollback cannot remove them.
        if kptcl_org:
            _RT_EXTRA_SUBSTATIONS = [
                # (name, 4-char-code, parent_division_name)
                ("220kV Kanakapura",         "KANA", "RT South Division"),
                ("400kV DHP",               "DHPX", "RT East Division"),
                ("220kV EDC",               "EDCX", "RT East Division"),
                ("220kV Manyatha Tech Park", "MANY", "RT North Division"),
            ]
            for sub_name, sub_code, parent_div_name in _RT_EXTRA_SUBSTATIONS:
                try:
                    # Find or create the parent division
                    parent_div = session.query(OrgDepartment).filter_by(
                        organization_id=kptcl_org.id,
                        name=parent_div_name,
                    ).first()
                    if not parent_div:
                        print(f"  [WARN] Parent division '{parent_div_name}' not found — skipping {sub_name}")
                        continue
                    existing = session.query(OrgDepartment).filter(
                        OrgDepartment.organization_id == kptcl_org.id,
                        OrgDepartment.name == sub_name,
                    ).first()
                    if existing:
                        if existing.code != sub_code:
                            existing.code = sub_code
                            session.commit()
                            print(f"  [INFO] Updated code for '{sub_name}' → {sub_code}")
                        continue
                    now = datetime.now()
                    dept = OrgDepartment(
                        organization_id=kptcl_org.id,
                        name=sub_name,
                        code=sub_code,
                        parent_department_id=parent_div.id,
                        is_active=True,
                        cts=now, mts=now,
                    )
                    session.add(dept)
                    session.commit()
                    print(f"  [INFO] Created RT substation '{sub_name}' ({sub_code})")
                except Exception as _e:
                    session.rollback()
                    print(f"  [WARN] Could not ensure RT substation '{sub_name}': {_e}")

        # Equipment + Annual Audit role mappings — after seed_dept_filter_users
        # so RT_EAST/RT_NORTH/BLR_CIRCLE depts exist for equipment lookup,
        # and after seed_seacms_roles_users so KPTCL OrgRoles exist for stage mapping
        if kptcl_org:
            try:
                seed_kptcl_equipment(session, str(kptcl_org.id))
            except FileNotFoundError:
                print("[WARN] equipment_seed.xlsx not found. Skipping equipment seeding.")
            except Exception as e:
                print(f"[WARN] KPTCL equipment seeding failed: {e}")

            try:
                session.rollback()
                from seed_annual_audit import seed_annual_audit_role_mappings
                seed_annual_audit_role_mappings(session, kptcl_org.id)
            except Exception as e:
                session.rollback()
                print(f"[WARN] Annual Audit role mapping failed: {e}")

        # Rename duplicate test templates (add category to name for uniqueness)
        print("\n--- Renaming Duplicate Test Templates ---")
        try:
            renamed = _rename_duplicate_templates(session)
            print(f"[OK] Renamed {renamed} duplicate templates")
        except Exception as _e:
            print(f"[WARN] Template renaming failed (non-fatal): {_e}")

        # ── Testing Kit module ────────────────────────────────────────────────
        print("\n--- Testing Kit Module Seeding ---")
        try:
            from seed_testing_kit import (
                ensure_table,
                run as seed_testing_kit_run,
                seed_module_and_privileges,
                seed_kit_mappings,
                seed_kit_equipment_records,
                update_tester_assigned_email_template,
            )
            ensure_table()
            seed_testing_kit_run(session)
            seed_module_and_privileges()
            seed_kit_mappings(session)
            seed_kit_equipment_records(session)
            update_tester_assigned_email_template()
        except Exception as _e:
            import traceback
            print(f"[WARN] Testing kit seed failed (non-fatal): {_e}")
            traceback.print_exc()

        print("\n" + "=" * 80)
        print("  [OK] ALL SEED DATA INSERTED SUCCESSFULLY")
        print("=" * 80)
        print("\nQuick Start:")
        print("  1. Super Admin: superadmin@system.com / Admin123!")
        print("  2. Sample Org Admin: orgadmin@sampleorg.com / OrgAdmin123!")
        if kptcl_org:
            print("  3. KPTCL Org Admin: orgadmin@utility.com / admin123")
        print("  4. Dept-filter users: tester.north / tester.south / tester.mysuru @ kptcl.com / TestDept@123")
        print(f"  {5 if kptcl_org else 4}. View API docs: http://localhost:8000/docs")
        print("\n" + "=" * 80 + "\n")


def seed_system_admin_permissions(session) -> int:
    """
    Idempotently elevate every 'System Administrator' OrgRole to full org-admin.

    Mirrors the logic in system_admin_permissions.py so it runs automatically
    during seed instead of requiring a manual script invocation.

    Steps:
      1. Find all OrgRole rows named 'System Administrator' (any org)
      2. Set is_org_admin=True, is_active=True
      3. Upsert OrgRolePermission for every active Module with all flags True

    Returns the number of permission rows created/updated.
    """
    roles = (
        session.query(OrgRole)
        .filter(OrgRole.name == "System Administrator")
        .all()
    )

    if not roles:
        print("[WARN] seed_system_admin_permissions: no 'System Administrator' OrgRole found — skipping")
        return 0

    modules = session.query(Module).filter_by(is_active=True).all()
    total_upserted = 0

    for role in roles:
        # Elevate to org-admin
        role.is_org_admin = True
        role.is_active    = True

        for module in modules:
            perm = (
                session.query(OrgRolePermission)
                .filter_by(org_role_id=role.id, module_id=module.id)
                .first()
            )
            if perm:
                perm.can_view    = True
                perm.can_add     = True
                perm.can_edit    = True
                perm.can_delete  = True
                perm.can_approve = True
                perm.can_assign  = True
                if hasattr(perm, "can_export"):
                    perm.can_export = True
                if hasattr(perm, "can_import"):
                    perm.can_import = True
            else:
                session.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role.id,
                    module_id=module.id,
                    can_view=True,
                    can_add=True,
                    can_edit=True,
                    can_delete=True,
                    can_approve=True,
                    can_assign=True,
                    can_export=True,
                    can_import=True,
                    cts=datetime.now(),
                    mts=datetime.now(),
                ))
            total_upserted += 1

    session.commit()
    print(f"[OK] seed_system_admin_permissions: {len(roles)} role(s), {total_upserted} permission rows upserted")
    return total_upserted


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
        ("Capacitor Voltage Transformer", "220", "01", "BHEL", "CVT-220-A", "CVT2024001", 2020),
        ("Power Transformer", "66", "01", "Crompton Greaves", "PT-66-C", "PT2024003", 2018),
        ("Protection Relay", "220", "01", "L&T", "REL-220-A", "REL2024001", 2023),
        ("Electronic Tri-vector Meter", "110", "01", "Secure Meters", "MTR-110-A", "MTR2024001", 2021),
        # Cumulative lifecycle
        ("Circuit Breaker", "220", "01", "ABB", "CB-220-A", "CB2024001", 2021),
        ("Circuit Breaker", "110", "02", "Siemens", "CB-110-B", "CB2024002", 2020),
        # Calibration lifecycle
        ("Protection Relay", "220", "01", "GE", "PR-220-A", "PR2024001", 2022),
        ("Protection Relay", "110", "02", "SEL", "PR-110-B", "PR2024002", 2021),
        ("Electronic Tri-vector Meter", "110", "01", "Secure Meters", "TVM-110-A", "TVM2024001", 2023),
        ("Electronic Tri-vector Meter", "220", "02", "L&T", "TVM-220-B", "TVM2024002", 2022),
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
        organization_id=kptcl_org.id, name="Asset Data Officer"
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
def seed_workflow(db, skip_roles=False):
    import uuid

    stages = load_json("REPAIR_WORKFLOW_STAGES.json")
    templates = load_json("REPAIR_STAGE_TEMPLATES.json")
    stage_template_map = load_json("STAGE_TEMPLATE_MAP.json")
    stage_role_list = load_json("repair_stage_roles.json")
    transitions = load_json("Repair_Role_Transitions.json")

    NAME_TO_CODE = {
        "Failure Reporting": "FAILURE_REPORT",
        "Committee Review": "COMMITTEE_REVIEW",
        "Vendor Assignment": "VENDOR_ASSIGNMENT",
        "Lifting": "LIFTING",
        "Joint Inspection": "JOINT_INSPECTION",
        "Estimate & Work Award": "ESTIMATE",
        "Repair QA": "QA",
        "Final Inspection": "FINAL_INSPECTION",
        "Dispatch": "DISPATCH",
        "Commissioning": "COMMISSIONING",
    }

    # --------------------------------------------------
    # 0. WORKFLOW DEFINITION
    # --------------------------------------------------
    workflow_def = (
        db.query(RepairWorkflowDefinition)
        .filter_by(workflow_code="BREAKDOWN")
        .first()
    )

    if not workflow_def:
        workflow_def = RepairWorkflowDefinition(
            id=uuid.uuid4(),
            workflow_code="BREAKDOWN",
            name="Breakdown Repair Workflow",
            is_active=True,
        )
        db.add(workflow_def)
        db.flush()

    # --------------------------------------------------
    # 1. TEMPLATES
    # --------------------------------------------------
    template_map = {}

    for key, t in templates.items():

        existing = (
            db.query(OrgTestTemplate)
            .filter_by(template_key=key)
            .first()
        )

        if existing:
            template_map[key] = existing.id
            continue

        obj = OrgTestTemplate(
            id=uuid.uuid4(),
            template_key=key,
            template_data=t,
            is_system=True,
            version=1,
        )

        db.add(obj)
        db.flush()

        template_map[key] = obj.id

    # --------------------------------------------------
    # 2. STAGES
    # --------------------------------------------------
    stage_map_by_name = {}
    stage_map_by_code = {}

    for s in stages:

        stage_name = s["name"]

        stage_code = (
            s.get("code")
            or NAME_TO_CODE.get(
                stage_name,
                stage_name.upper().replace(" ", "_")
            )
        )

        existing = (
            db.query(RepairStageDefinition)
            .filter_by(
                workflow_definition_id=workflow_def.id,
                name=stage_name
            )
            .first()
        )

        if existing:
            if existing.workflow_definition_id != workflow_def.id:
                existing.workflow_definition_id = workflow_def.id

            stage_map_by_name[stage_name] = existing.id
            stage_map_by_code[existing.code] = existing.id
            continue

        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            workflow_definition_id=workflow_def.id,
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

    # --------------------------------------------------
    # 3. STAGE → TEMPLATE
    # --------------------------------------------------
    for stage_name, template_key in stage_template_map.items():

        stage_id = stage_map_by_name.get(stage_name)
        template_id = template_map.get(template_key)

        if not stage_id or not template_id:
            continue

        exists = (
            db.query(RepairStageTemplate)
            .filter_by(stage_id=stage_id)
            .first()
        )

        if not exists:
            db.add(
                RepairStageTemplate(
                    stage_id=stage_id,
                    template_id=template_id,
                )
            )
        else:
            exists.template_id = template_id

    # --------------------------------------------------
    # 4. ROLES (optional)
    # --------------------------------------------------
    if skip_roles:
        db.commit()
        print(
            f"[OK] BREAKDOWN workflow seeded "
            f"({len(stage_map_by_name)} stages, roles deferred)"
        )
        return

    for entry in stage_role_list:

        stage_code = entry.get("stage_code")
        stage_id = stage_map_by_code.get(stage_code)

        if not stage_id:
            print(
                f"[WARN] stage_code '{stage_code}' not found"
            )
            continue

        for role_name in entry.get("roles", []):

            role = (
                db.query(OrgRole)
                .filter_by(name=role_name)
                .first()
            )

            if not role:
                print(
                    f"[WARN] role '{role_name}' not found"
                )
                continue

            exists = (
                db.query(RepairStageRole)
                .filter_by(
                    stage_id=stage_id,
                    role_id=role.id,
                )
                .first()
            )

            if not exists:
                db.add(
                    RepairStageRole(
                        id=uuid.uuid4(),
                        stage_id=stage_id,
                        role_id=role.id,
                        can_edit=True,
                        can_approve=True,
                        can_assign=False,
                    )
                )

        assign_role_name = entry.get("assignment_role")

        if assign_role_name:

            assign_role = (
                db.query(OrgRole)
                .filter_by(name=assign_role_name)
                .first()
            )

            if assign_role:

                exists = (
                    db.query(RepairStageRole)
                    .filter_by(
                        stage_id=stage_id,
                        role_id=assign_role.id,
                    )
                    .first()
                )

                if not exists:
                    db.add(
                        RepairStageRole(
                            id=uuid.uuid4(),
                            stage_id=stage_id,
                            role_id=assign_role.id,
                            can_edit=False,
                            can_approve=False,
                            can_assign=True,
                        )
                    )
                elif not exists.can_assign:
                    exists.can_assign = True

    # --------------------------------------------------
    # 5. TRANSITIONS
    # --------------------------------------------------
    for t in transitions:

        from_id = stage_map_by_name.get(t["from"])
        to_id = stage_map_by_name.get(t["to"])

        if not from_id:
            print(
                f"[WARN] transition from '{t['from']}' not found"
            )
            continue

        exists = (
            db.query(RepairStageTransition)
            .filter_by(
                from_stage_id=from_id,
                action=t["action"],
            )
            .first()
        )

        if not exists:
            db.add(
                RepairStageTransition(
                    id=uuid.uuid4(),
                    from_stage_id=from_id,
                    to_stage_id=to_id,
                    action=t["action"],
                )
            )
        else:
            exists.to_stage_id = to_id

    db.commit()

    print(
        f"[OK] BREAKDOWN workflow seeded successfully "
        f"({len(stage_map_by_name)} stages)"
    )

def load_json(file_name):
    with open(file_name, "r") as f:
        return json.load(f)

def seed_workflow_legacy(session):
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

    # Default contractual duration (calendar days) per stage — used for Work Award pre-fill
    DEFAULT_DURATION_DAYS = {
        "FAILURE_REPORT":   3,
        "COMMITTEE_REVIEW": 2,
        "VENDOR_ASSIGNMENT": 1,
        "LIFTING":           1,
        "JOINT_INSPECTION":  2,
        "ESTIMATE":          3,
        "QA":                3,
        "FINAL_INSPECTION":  2,
        "DISPATCH":          1,
        "COMMISSIONING":     2,
    }

    # ── 0. Workflow definition ────────────────────────────────────────────────
    wf_def = session.query(RepairWorkflowDefinition).filter_by(workflow_code="BREAKDOWN").first()
    if not wf_def:
        wf_def = RepairWorkflowDefinition(
            id=uuid.uuid4(),
            workflow_code="BREAKDOWN",
            name="Transformer Repair Workflow",
            is_active=True,
        )
        session.add(wf_def)
        session.flush()
    print(f"[OK] RepairWorkflowDefinition BREAKDOWN: {wf_def.id}")

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
        duration = DEFAULT_DURATION_DAYS.get(code)
        if existing:
            if existing.workflow_definition_id != wf_def.id:
                existing.workflow_definition_id = wf_def.id
            if duration is not None and existing.default_duration_days != duration:
                existing.default_duration_days = duration
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
            workflow_definition_id=wf_def.id,
            default_duration_days=duration,
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
    ("System Administrator",              False, True),
    ("Asset Data Officer",                False, False),
    ("AEE_MAINTENANCE",                   False, False),
    ("AE_JE",                             False, False),
    ("Test & Work Coordinator",           False, False),
    ("EE_TLSS",                           False, True),
    ("SEE_WM",                            False, False),
    ("CEE_TRANSMISSION_ZONE",             False, True),
    ("TA&QC Inspector",                   False, False),
    ("Transformer Repair Coordinator",    False, False),
    ("Procurement Officer",               False, False),
]

_DFT_DEPTS = [
    ("north",  "RT North Division",  "north"),
    ("south",  "RT South Division",  "south"),
    ("mysuru", "Mysuru Division",     "mysuru"),
]

_DFT_ROLE_EMAIL = {
    "System Administrator":             "sysadmin",
    "Asset Data Officer":               "assetofficer",
    "AEE_MAINTENANCE":                  "maintoff",
    "AE_JE":                            "testengineer",
    "Test & Work Coordinator":          "testcoord",
    "EE_TLSS":                          "reviewoff",
    "SEE_WM":                           "supervoff",
    "CEE_TRANSMISSION_ZONE":            "seniormgmt",
    "TA&QC Inspector":                  "taqc",
    "Transformer Repair Coordinator":   "repaircoord",
    "Procurement Officer":              "procoff",
}

_DFT_ROLE_FNAME = {
    "System Administrator":             "SysAdmin",
    "Asset Data Officer":               "AssetOfficer",
    "AEE_MAINTENANCE":                  "AEE",
    "AE_JE":                            "AE",
    "Test & Work Coordinator":          "TestCoordinator",
    "EE_TLSS":                          "EE",
    "SEE_WM":                           "SEE",
    "CEE_TRANSMISSION_ZONE":            "CEE",
    "TA&QC Inspector":                  "TAQCInspector",
    "Transformer Repair Coordinator":   "RepairCoord",
    "Procurement Officer":              "ProcOfficer",
}

_DFT_PHONE = {
    ("north",  "System Administrator"):             "9900001001",
    ("north",  "Asset Data Officer"):               "9900001002",
    ("north",  "AEE_MAINTENANCE"):                  "9900001003",
    ("north",  "AE_JE"):                            "9900001004",
    ("north",  "Test & Work Coordinator"):          "9900001005",
    ("north",  "EE_TLSS"):                          "9900001006",
    ("north",  "SEE_WM"):                           "9900001007",
    ("north",  "CEE_TRANSMISSION_ZONE"):            "9900001008",
    ("north",  "TA&QC Inspector"):                  "9900001009",
    ("north",  "Transformer Repair Coordinator"):   "9900001010",
    ("north",  "Procurement Officer"):              "9900001011",
    ("south",  "System Administrator"):             "9900002001",
    ("south",  "Asset Data Officer"):               "9900002002",
    ("south",  "AEE_MAINTENANCE"):                  "9900002003",
    ("south",  "AE_JE"):                            "9900002004",
    ("south",  "Test & Work Coordinator"):          "9900002005",
    ("south",  "EE_TLSS"):                          "9900002006",
    ("south",  "SEE_WM"):                           "9900002007",
    ("south",  "CEE_TRANSMISSION_ZONE"):            "9900002008",
    ("south",  "TA&QC Inspector"):                  "9900002009",
    ("south",  "Transformer Repair Coordinator"):   "9900002010",
    ("south",  "Procurement Officer"):              "9900002011",
    ("mysuru", "System Administrator"):             "9900003001",
    ("mysuru", "Asset Data Officer"):               "9900003002",
    ("mysuru", "AEE_MAINTENANCE"):                  "9900003003",
    ("mysuru", "AE_JE"):                            "9900003004",
    ("mysuru", "Test & Work Coordinator"):          "9900003005",
    ("mysuru", "EE_TLSS"):                          "9900003006",
    ("mysuru", "SEE_WM"):                           "9900003007",
    ("mysuru", "CEE_TRANSMISSION_ZONE"):            "9900003008",
    ("mysuru", "TA&QC Inspector"):                  "9900003009",
    ("mysuru", "Transformer Repair Coordinator"):   "9900003010",
    ("mysuru", "Procurement Officer"):              "9900003011",
}


def seed_surveillance_workflow(session):
    """
    Seed surveillance workflow stages, templates, role assignments, and transitions.

    Source files (all at repo root):
      SURVEILLANCE_WORKFLOW_STAGES.json      — [{name, sequence}]
      SURVEILLANCE_STAGE_TEMPLATES.json      — {template_key: {name, sections, ...}}
      SURVEILLANCE_STAGE_TEMPLATE_MAP.json   — {stage_name: template_key}
      SURVEILLANCE_STAGE_ROLES.json          — [{stage_code, roles:[role_name,...]}]
    """
    import json as _json
    import os as _os

    def _load(fname):
        path = _os.path.join(_os.path.dirname(__file__), fname)
        if not _os.path.exists(path):
            print(f"[WARN] File not found: {fname} - skipping")
            return None
        with open(path, encoding="utf-8") as fh:
            return _json.load(fh)

    stages_raw      = _load("SURVEILLANCE_WORKFLOW_STAGES.json")
    templates_raw   = _load("SURVEILLANCE_STAGE_TEMPLATES.json")
    stage_tmpl_map  = _load("SURVEILLANCE_STAGE_TEMPLATE_MAP.json")
    roles_raw       = _load("SURVEILLANCE_STAGE_ROLES.json")

    if not stages_raw or not templates_raw or not stage_tmpl_map:
        print("[WARN] Missing surveillance JSON files - skipping surveillance workflow seed")
        return

    # Stage name → code mapping
    NAME_TO_CODE = {
        "Q1 Surveillance Testing":     "Q1_SURVEILLANCE",
        "Q2 Surveillance Testing":     "Q2_SURVEILLANCE",
        "Q3 Surveillance Testing":     "Q3_SURVEILLANCE",
        "Q4 Surveillance Testing":     "Q4_SURVEILLANCE",
        "Final Evaluation & Report":   "FINAL_EVALUATION",
    }
    CODE_TO_NAME = {v: k for k, v in NAME_TO_CODE.items()}

    # Default duration for each surveillance stage (in days)
    DEFAULT_SURVEILLANCE_DURATION_DAYS = {
        "Q1_SURVEILLANCE":    30,  # 30 days to complete quarterly review
        "Q2_SURVEILLANCE":    30,
        "Q3_SURVEILLANCE":    30,
        "Q4_SURVEILLANCE":    30,
        "FINAL_EVALUATION":   45,  # 45 days for comprehensive final report
    }

    # ── 0. Workflow definition ────────────────────────────────────────────────
    wf_def = session.query(RepairWorkflowDefinition).filter_by(workflow_code="SURVEILLANCE").first()
    if not wf_def:
        wf_def = RepairWorkflowDefinition(
            id=uuid.uuid4(),
            workflow_code="SURVEILLANCE",
            name="Post-Commissioning Surveillance",
            is_active=True,
        )
        session.add(wf_def)
        session.flush()
    print(f"[OK] RepairWorkflowDefinition SURVEILLANCE: {wf_def.id}")

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
    print(f"[OK] Surveillance templates: {len(template_map)} ready")

    # ── 2. Stages ─────────────────────────────────────────────────────────────
    stage_map = {}      # name → UUID
    code_map  = {}      # code → UUID
    for s in stages_raw:
        name = s["name"]
        code = NAME_TO_CODE.get(name, name.upper().replace(" ", "_"))
        duration = DEFAULT_SURVEILLANCE_DURATION_DAYS.get(code)
        existing = session.query(RepairStageDefinition).filter_by(code=code).first()
        if existing:
            if existing.workflow_definition_id != wf_def.id:
                existing.workflow_definition_id = wf_def.id
            if duration is not None and existing.default_duration_days != duration:
                existing.default_duration_days = duration
            if not existing.weight:  # backfill weight so progress calc works
                existing.weight = 20
            stage_map[name] = existing.id
            code_map[code]  = existing.id
            continue
        stage = RepairStageDefinition(
            id=uuid.uuid4(),
            name=name,
            code=code,
            sequence=s["sequence"],
            weight=20,          # 5 stages × 20 = 100 — required for progress calculation
            is_active=True,
            is_mandatory=True,
            workflow_definition_id=wf_def.id,
            default_duration_days=duration,
        )
        session.add(stage)
        session.flush()
        stage_map[name] = stage.id
        code_map[code]  = stage.id
    print(f"[OK] Surveillance stages: {len(stage_map)} ready")

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
    if roles_raw:
        for entry in roles_raw:
            stage_code = entry.get("stage_code") or entry.get("code")
            stage_id   = code_map.get(stage_code)
            if not stage_id:
                print(f"[WARN] Stage code not found: {stage_code}")
                continue

            # Stage actor roles (can_edit + can_approve)
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
                            stage_id=stage_id,
                            role_id=role.id,
                            can_edit=True,
                            can_approve=True,
                            can_assign=False,
                        ))
                    else:
                        exists.can_edit    = True
                        exists.can_approve = True

            # Stage actor roles that also get can_assign (e.g. senior officer can assign)
            for role_name in entry.get("assign_also", []):
                matched_roles = session.query(OrgRole).filter(OrgRole.name == role_name).all()
                for role in matched_roles:
                    mapping = session.query(RepairStageRole).filter_by(
                        stage_id=stage_id, role_id=role.id
                    ).first()
                    if mapping and not mapping.can_assign:
                        mapping.can_assign = True

            # Assignment coordinator role (can_assign only)
            assign_role_name = entry.get("assignment_role")
            if assign_role_name:
                matched_assign_roles = session.query(OrgRole).filter(OrgRole.name == assign_role_name).all()
                if not matched_assign_roles:
                    print(f"[WARN] Assignment role not found in any org: {assign_role_name}")
                for role in matched_assign_roles:
                    exists = session.query(RepairStageRole).filter_by(
                        stage_id=stage_id, role_id=role.id
                    ).first()
                    if not exists:
                        session.add(RepairStageRole(
                            stage_id=stage_id,
                            role_id=role.id,
                            can_edit=False,
                            can_approve=False,
                            can_assign=True,
                        ))
                    elif not exists.can_assign:
                        exists.can_assign = True

    # ── 5. Stage Transitions ──────────────────────────────────────────────────
    # Q1 → Q2 → Q3 → Q4 → Final (no transition after final = workflow completes)
    transitions = [
        ("Q1_SURVEILLANCE", "Q2_SURVEILLANCE", "approve"),
        ("Q2_SURVEILLANCE", "Q3_SURVEILLANCE", "approve"),
        ("Q3_SURVEILLANCE", "Q4_SURVEILLANCE", "approve"),
        ("Q4_SURVEILLANCE", "FINAL_EVALUATION", "approve"),
    ]

    for from_code, to_code, action in transitions:
        from_id = code_map.get(from_code)
        to_id   = code_map.get(to_code)
        if not from_id or not to_id:
            continue
        exists = session.query(RepairStageTransition).filter_by(
            from_stage_id=from_id, to_stage_id=to_id, action=action
        ).first()
        if not exists:
            session.add(RepairStageTransition(
                from_stage_id=from_id,
                to_stage_id=to_id,
                action=action,
            ))

    session.commit()

    # ── 6. Validation ─────────────────────────────────────────────────────────
    print("\n[INFO] Validating surveillance workflow seed...")

    # Verify workflow definition
    verify_wf = session.query(RepairWorkflowDefinition).filter_by(
        workflow_code="SURVEILLANCE"
    ).first()

    if not verify_wf:
        print("[ERROR] SURVEILLANCE workflow definition not found after seeding!")
        return False

    print(f"  [OK] Workflow definition: {verify_wf.name} (ID: {verify_wf.id})")

    # Verify stages
    verify_stages = session.query(RepairStageDefinition).filter_by(
        workflow_definition_id=verify_wf.id
    ).order_by(RepairStageDefinition.sequence).all()

    if len(verify_stages) != 5:
        print(f"[ERROR] Expected 5 stages, found {len(verify_stages)}")
        return False

    print(f"  [OK] Stages ({len(verify_stages)}):")
    for stage in verify_stages:
        print(f"       {stage.sequence}. {stage.name} ({stage.code}, {stage.default_duration_days} days)")

    # Verify transitions
    verify_transitions = session.query(RepairStageTransition).filter(
        RepairStageTransition.from_stage_id.in_([s.id for s in verify_stages])
    ).all()

    print(f"  [OK] Transitions: {len(verify_transitions)} configured")

    # Verify templates
    verify_templates = session.query(OrgTestTemplate).filter(
        OrgTestTemplate.template_key.in_(template_map.keys())
    ).all()

    print(f"  [OK] Templates: {len(verify_templates)} ready")

    print("\n[SUCCESS] Surveillance workflow seed validation passed!")


from sqlalchemy import func

def seed_surveillance_config(session):
    """
    Seed surveillance configuration data.

    Creates:
    1. System-wide default surveillance config
    2. Surveillance test configurations for Power Transformers
    """

    print("\n[INFO] Seeding surveillance configuration...")

    # ------------------------------------------------------------------
    # 1. System Configuration
    # ------------------------------------------------------------------
    system_config = (
        session.query(SurveillanceConfig)
        .filter_by(
            organization_id=None,
            department_id=None
        )
        .first()
    )

    if not system_config:
        system_config = SurveillanceConfig(
            id=uuid.uuid4(),
            organization_id=None,
            department_id=None,
            surveillance_period_months=24,
            frequency_multiplier=2.0,
            abnormal_statuses=[
                "FAIL",
                "MARGINAL",
                "CRITICAL",
                "ALERT",
            ],
            quality_threshold_fair=20.0,
            is_active=True,
        )

        session.add(system_config)
        session.flush()

        print(
            f"[OK] System surveillance config created: "
            f"{system_config.id}"
        )
    else:
        print(
            f"[SKIP] System surveillance config already exists: "
            f"{system_config.id}"
        )

    # ------------------------------------------------------------------
    # 2. Equipment Type
    # ------------------------------------------------------------------
    equip_master = (
        session.query(CategoryMaster)
        .filter(
            func.lower(CategoryMaster.name)
            == "power transformer"
        )
        .first()
    )

    if not equip_master:
        print(
            "[WARN] Power Transformer CategoryMaster not found "
            "- skipping surveillance test config"
        )
        return

    # ------------------------------------------------------------------
    # 3. Surveillance Tests
    # ------------------------------------------------------------------
    surveillance_tests = [
        ("Transformer Oil Test", "high", True),
        ("Capacitance & Tan Delta Test (Transformer)", "high", True),
        ("Transformer Physical Inspection", "medium", True),
        ("Insulation Resistance Test", "medium", True),
    ]

    for test_name, priority, required in surveillance_tests:

        test_type = (
            session.query(CategoryDetails)
            .filter(
                func.lower(CategoryDetails.name)
                == test_name.lower(),
                CategoryDetails.category_master_id
                == equip_master.id,
            )
            .first()
        )

        if not test_type:
            print(
                f"[WARN] Test type not found for surveillance "
                f"config: {test_name}"
            )
            continue

        existing = (
            session.query(SurveillanceTestConfig)
            .filter_by(
                equipment_type_id=equip_master.id,
                test_type_id=test_type.id,
            )
            .first()
        )

        if existing:
            print(
                f"[SKIP] Surveillance test config exists: "
                f"{test_name}"
            )
            continue

        session.add(
            SurveillanceTestConfig(
                id=uuid.uuid4(),
                equipment_type_id=equip_master.id,
                test_type_id=test_type.id,
                is_required=required,
                default_priority=priority,
                is_active=True,
            )
        )

        print(
            f"[OK] Surveillance test config created: "
            f"{test_name}"
        )

    session.commit()

    print(
        "[OK] Surveillance configuration seeded successfully"
    )


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
        primary_email="info@utility.com",
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
    # Fallback: match by name + parent to avoid creating duplicates when the
    # same dept was already seeded with a different code (e.g. KPTCL zones).
    d = session.query(OrgDepartment).filter_by(
        organization_id=org_id,
        name=name,
        parent_department_id=parent_id,
    ).first()
    if d:
        # Fix code if the existing dept has the wrong code (e.g. old long codes like RT_NORTH)
        if d.code != code and len(code) <= 4:
            d.code = code
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
    "System Administrator":             "admin_dashboard",
    "Asset Data Officer":               "asset_dashboard",
    "AEE_MAINTENANCE":                  "aee_dashboard",
    "AE_JE":                            "ae_dashboard",
    "Test & Work Coordinator":          "test_coordinator_dashboard",
    "EE_TLSS":                          "ee_tlss_dashboard",
    "SEE_WM":                           "see_dashboard",
    "CEE_TRANSMISSION_ZONE":            "cee_dashboard",
    "TA&QC Inspector":                  "ee_tlss_dashboard",
    "Transformer Repair Coordinator":   "ee_tlss_dashboard",
    "Procurement Officer":              "aee_dashboard",
}


def _dft_get_or_create_role(session, org_id, name,
                             is_org_admin=False, is_dept_admin=False) -> OrgRole:
    r = session.query(OrgRole).filter_by(
        organization_id=org_id, name=name
    ).first()
    module_path = _DFT_ROLE_MODULE_PATH.get(name)
    mod = session.query(Module).filter_by(path=module_path).first() if module_path else None

    if r:
        # Sync flags so re-seeding always fixes stale DB state
        updated = False
        if r.is_org_admin != is_org_admin:
            r.is_org_admin = is_org_admin
            updated = True
        if r.is_dept_admin != is_dept_admin:
            r.is_dept_admin = is_dept_admin
            updated = True
        if mod and r.default_module_id != mod.id:
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

    exists = (
        session.query(OrgUserRole)
        .filter_by(
            user_id=user_id,
            org_role_id=role_id,
            department_id=dept_id,
        )
        .first()
    )

    if exists:
        return

    now = datetime.now().astimezone()

    mapping = OrgUserRole(
        user_id=user_id,
        org_role_id=role_id,
        department_id=dept_id,
        is_active=True,
        assigned_at=now,
    )

    session.add(mapping)

    session.flush()

def _seed_dft_equipment(session, org, dept_map: dict):

    from services.equipment_service import EquipmentService
    from models import CategoryMaster

    if not org:
        return

    admin = (
        session.query(User)
        .filter(
            User.organization_id == org.id,
            User.email.ilike("%orgadmin%"),
        )
        .first()
        or session.query(User)
        .filter(User.organization_id == org.id)
        .first()
    )

    created_by = admin.id if admin else None

    equip_types = (
        session.query(CategoryMaster)
        .filter(
            CategoryMaster.description == "Testing Equipment",
            CategoryMaster.is_active.is_(True),
        )
        .all()
    )

    type_map = {et.name: et.id for et in equip_types}

    division_configs = {
    "north": [
        ("Power Transformer", "220", "01", "BHEL", "PT-220-N", "NTH2024001", 2021),
        ("Current Transformer", "220", "01", "Siemens", "CT-220-N", "NTH2024002", 2022),
        ("Power Transformer", "110", "01", "ABB", "PT-110-N", "NTH2024003", 2020),
    ],

    "south": [
        ("Power Transformer", "220", "01", "BHEL", "PT-220-S", "STH2024001", 2021),
        ("Current Transformer", "110", "01", "CGL", "CT-110-S", "STH2024002", 2022),
        ("Capacitor Voltage Transformer", "220", "01", "BHEL", "CVT-220-S", "STH2024003", 2020),
    ],

    "mysuru": [
        ("Power Transformer", "110", "01", "Crompton Greaves", "PT-110-M", "MYS2024001", 2019),
        ("Current Transformer", "220", "01", "Siemens", "CT-220-M", "MYS2024002", 2021),
        ("Power Transformer", "66", "01", "ABB", "PT-066-M", "MYS2024003", 2018),
    ],
}

    created = 0

    for slug, dept_obj in dept_map.items():

        configs = division_configs.get(slug, [])

        for (
            type_name,
            voltage,
            bay,
            mfr,
            model,
            serial,
            year,
        ) in configs:

            if type_name not in type_map:
                print(f"  [WARN] Missing equipment type: {type_name}")
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

                session.commit()

                created += 1

            except Exception as e:

                session.rollback()

                print(
                    f"  [WARN] Equipment seed failed "
                    f"for {serial}: {e}"
                )
                print(
        f"\n[ERROR] Equipment seed failed"
    )

                print(f"type       : {type_name}")
                print(f"serial     : {serial}")
                print(f"department : {slug}")

                print(f"\nException:\n{repr(e)}\n")

    print(
        f"  [OK] {created} equipment items seeded "
        f"across {len(dept_map)} divisions"
    )
def seed_dept_filter_users(session, org=None):
    """
    Seeds KPTCL org with 3 department divisions, each having the complete set
    of 10 role-users (30 users total).  Used to validate department-scope
    filters in IntegratedWorkflowEngine.

    Pass the already-created KPTCL Organization object as `org` so this
    function reuses it as the default org rather than doing a separate lookup.

    Hierarchy:  BLR_ZONE → BLR_CIRCLE → RT_NORTH / RT_SOUTH / MYSURU
    Email:      {role}.{dept}@utility.com   (e.g. tester.north@utility.com)
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
        name="Bangalore Zone", code="BN",
    )
    print(f"  Zone   : {zone.name}")

    circle = _dft_get_or_create_dept(
        session, oid,
        name="Bangalore Transmission Circle", code="BLRC",
        parent_id=zone.id,
    )
    print(f"  Circle : {circle.name}")

    div_north  = _dft_get_or_create_dept(
        session, oid,
        name="RT North Division", code="RTNR",
        parent_id=circle.id,
    )
    div_south  = _dft_get_or_create_dept(
        session, oid,
        name="RT South Division", code="RTSO",
        parent_id=circle.id,
    )
    div_east   = _dft_get_or_create_dept(
        session, oid,
        name="RT East Division", code="RTEA",
        parent_id=circle.id,
    )
    div_mysuru = _dft_get_or_create_dept(
        session, oid,
        name="Mysuru Division", code="MYSR",
        parent_id=circle.id,
    )
    dept_map = {"north": div_north, "south": div_south, "east": div_east, "mysuru": div_mysuru}
    for slug, dept in dept_map.items():
        print(f"  Div [{slug:6s}]: {dept.name}  ({dept.id})")

    # Seed RT substations missing from KPTCL_Substation_Mapping.xlsx
    # so equipment_seed.xlsx rows for these substations resolve to a dept
    _rt_substations = [
        ("220kV EDC",             "EDCX", div_east.id),
        ("400kV DHP",             "DHPX", div_east.id),
        ("220kV Kanakapura",      "KANA", div_south.id),
        ("220kV Manyatha Tech Park", "MANY", div_north.id),
    ]
    for sub_name, sub_code, parent_id in _rt_substations:
        _dft_get_or_create_dept(session, oid, name=sub_name, code=sub_code, parent_id=parent_id)
    session.commit()

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
            email     = f"{_DFT_ROLE_EMAIL[role_name]}.{email_sfx}@utility.com"
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
        ("ee.circle@utility.com",   "EE",   "Circle", "EE_TLSS",             circle),
        ("see.circle@utility.com",  "SEE",  "Circle", "SEE_WM",              circle),
        ("cee.zone@utility.com",    "CEE",  "Zone",   "CEE_TRANSMISSION_ZONE", zone),
        ("see.zone@utility.com",    "SEE",  "Zone",   "SEE_WM",              zone),
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
    Run KPTCL department + equipment seeding for a specific organization.
    Usage: python seed.py --kptcl <org_id>
    """
    with get_db_session() as session:
        print("\n" + "=" * 80)
        print("  KPTCL DEPARTMENT SEEDING")
        print("=" * 80 + "\n")
        seed_kptcl_departments(session, org_id)
        print("\n" + "=" * 80)
        print("  KPTCL EQUIPMENT SEEDING")
        print("=" * 80 + "\n")
        seed_kptcl_equipment(session, org_id)
        print("\n" + "=" * 80)
        print("  [OK] KPTCL SEEDING COMPLETED SUCCESSFULLY")
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
                print("\n[INFO] Seeding KPTCL departments + equipment...")
                with get_db_session() as session:
                    seed_kptcl_departments(session, org_id)
                    seed_kptcl_equipment(session, org_id)

    except Exception as e:
        import traceback
        traceback.print_exc()
