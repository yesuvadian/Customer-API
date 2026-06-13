"""
Seed: Testing Kit equipment type, sub-categories, and nameplate template.
Also creates the equipment_type_kit_mappings table if it doesn't exist.
Run once:  python seed_testing_kit.py
"""
import sys
import uuid
from sqlalchemy import text
from sqlalchemy.orm import Session
from database import SessionLocal, VendorSessionLocal, engine
from models import CategoryMaster, CategoryDetails, Module, OrgRole, OrgRolePermission, OrgTestTemplate


TESTING_KIT_SUBCATEGORIES = [
    "Relay Test Kit",
    "Insulation Resistance Tester",
    "Oil BDV (Breakdown Voltage) Kit",
    "CT / PT Analyzer",
    "Earth Resistance Tester",
    "High Voltage Test Set",
    "Power Analyzer",
    "Partial Discharge Detector",
    "Infrared Thermometer / Thermal Camera",
    "Multimeter / Clamp Meter",
]

TESTING_KIT_NAMEPLATE_TEMPLATE = {
    "sections": [
        {
            "title": "Kit Identity",
            "fields": [
                {"key": "kit_subtype",        "label": "Kit Sub-Type",          "type": "text",   "required": True},
                {"key": "manufacturer",        "label": "Manufacturer",          "type": "text",   "required": True},
                {"key": "model_number",        "label": "Model Number",          "type": "text",   "required": True},
                {"key": "factory_serial_number","label": "Serial Number",        "type": "text",   "required": True},
                {"key": "year_of_manufacture", "label": "Year of Manufacture",   "type": "number", "required": False},
            ],
        },
        {
            "title": "Calibration",
            "fields": [
                {"key": "last_calibration_date", "label": "Last Calibration Date", "type": "date",   "required": True},
                {"key": "calibration_due_date",  "label": "Calibration Due Date",  "type": "date",   "required": True},
                {"key": "calibration_authority", "label": "Calibration Authority",  "type": "text",   "required": False},
                {"key": "calibration_certificate_ref","label": "Certificate Ref",   "type": "text",   "required": False},
            ],
        },
        {
            "title": "Specifications",
            "fields": [
                {"key": "measurement_range",  "label": "Measurement Range",   "type": "text",     "required": False},
                {"key": "accuracy_class",     "label": "Accuracy Class",      "type": "text",     "required": False},
                {"key": "is_portable",        "label": "Portable",            "type": "boolean",  "required": False},
                {"key": "rated_voltage",      "label": "Rated Voltage (V)",   "type": "number",   "required": False},
            ],
        },
        {
            "title": "Ownership & Location",
            "fields": [
                {"key": "owned_by_dept",  "label": "Owned By Department", "type": "text", "required": False},
                {"key": "storage_location","label": "Storage Location",   "type": "text", "required": False},
                {"key": "notes",          "label": "Notes",               "type": "textarea", "required": False},
            ],
        },
    ]
}


def ensure_table():
    """Create equipment_type_kit_mappings table if it doesn't already exist."""
    ddl = """
    CREATE TABLE IF NOT EXISTS public.equipment_type_kit_mappings (
        id               SERIAL PRIMARY KEY,
        equipment_type_id INTEGER NOT NULL
            REFERENCES public."CategoryMaster"(id) ON DELETE CASCADE,
        kit_type_id       INTEGER NOT NULL
            REFERENCES public."CategoryDetails"(id) ON DELETE CASCADE,
        is_required       BOOLEAN DEFAULT TRUE,
        notes             TEXT,
        created_by        UUID REFERENCES public.users(id),
        cts               TIMESTAMPTZ DEFAULT now(),
        mts               TIMESTAMPTZ DEFAULT now(),
        CONSTRAINT uq_eq_type_kit_type UNIQUE (equipment_type_id, kit_type_id)
    );
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))
    print("[OK]   Table 'equipment_type_kit_mappings' ready")


def run(db: Session):
    # 0. Ensure DB table exists
    ensure_table()

    # 1. Create or fetch "Testing Kit" CategoryMaster
    kit_master = db.query(CategoryMaster).filter(CategoryMaster.name == "Testing Kit").first()
    if kit_master:
        print(f"[SKIP] CategoryMaster 'Testing Kit' already exists (id={kit_master.id})")
    else:
        kit_master = CategoryMaster(name="Testing Kit", description="Portable instruments used for field testing of electrical equipment", is_active=True)
        db.add(kit_master)
        db.flush()
        print(f"[OK]   Created CategoryMaster 'Testing Kit' id={kit_master.id}")

    # 2. Seed sub-categories
    for name in TESTING_KIT_SUBCATEGORIES:
        existing = db.query(CategoryDetails).filter(
            CategoryDetails.category_master_id == kit_master.id,
            CategoryDetails.name == name,
        ).first()
        if existing:
            print(f"[SKIP] Sub-category '{name}' already exists")
            continue
        db.add(CategoryDetails(
            category_master_id=kit_master.id,
            name=name,
            category_type="testing_kit",
            is_active=True,
        ))
        print(f"[OK]   Sub-category '{name}'")

    # 3. Seed global nameplate template
    template_key = "Testing_Kit_Nameplate"
    existing_tmpl = db.query(OrgTestTemplate).filter(
        OrgTestTemplate.org_id == None,
        OrgTestTemplate.template_key == template_key,
    ).first()
    if existing_tmpl:
        print(f"[SKIP] Nameplate template '{template_key}' already exists")
    else:
        db.add(OrgTestTemplate(
            id=uuid.uuid4(),
            org_id=None,
            template_key=template_key,
            test_type_id=None,
            template_data=TESTING_KIT_NAMEPLATE_TEMPLATE,
            is_system=True,
            version=1,
        ))
        print(f"[OK]   Nameplate template '{template_key}'")

    db.commit()
    print("\nSeeding complete.")
    print(f"Testing Kit CategoryMaster id = {kit_master.id}")
    print("Use this id when creating kit mappings via POST /equipment-type-kit-mappings/")


def seed_module_and_privileges():
    """
    Create the 'testing_kit_register' Module and grant Asset Data Officer
    full RW access (can_view, can_add, can_edit).
    Uses VendorSessionLocal — the same DB as roles/modules.
    """
    db = VendorSessionLocal()
    try:
        # 1. Ensure module exists
        module = db.query(Module).filter(Module.name == "testing_kit_register").first()
        if module:
            print(f"[SKIP] Module 'testing_kit_register' already exists (id={module.id})")
        else:
            module = Module(
                name="testing_kit_register",
                description="Testing Kit Register — register and manage testing instruments",
                path="/testing-kit-register",
                group_name="ASSETS",
                is_active=True,
                is_menu=True,
            )
            db.add(module)
            db.flush()
            print(f"[OK]   Module 'testing_kit_register' created (id={module.id})")

        # 2. Find Asset Data Officer role (org-scoped role via OrgRole)
        role = db.query(OrgRole).filter(OrgRole.name == "Asset Data Officer").first()
        if not role:
            print("[WARN] OrgRole 'Asset Data Officer' not found — skipping privilege grant")
            db.commit()
            return

        # 3. Upsert OrgRolePermission
        perm = db.query(OrgRolePermission).filter(
            OrgRolePermission.org_role_id == role.id,
            OrgRolePermission.module_id == module.id,
        ).first()

        if perm:
            perm.can_view = True
            perm.can_add  = True
            perm.can_edit = True
            print(f"[OK]   Updated privileges for Asset Data Officer -> testing_kit_register")
        else:
            db.add(OrgRolePermission(
                id=uuid.uuid4(),
                org_role_id=role.id,
                module_id=module.id,
                can_view=True,
                can_add=True,
                can_edit=True,
                can_delete=False,
                can_approve=False,
                can_assign=False,
                can_export=False,
                can_import=False,
            ))
            print(f"[OK]   Granted Asset Data Officer -> testing_kit_register (RW)")

        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


TESTER_ASSIGNED_EMAIL_BODY = """
<h2 style="color:#1E3C72;margin-bottom:4px;">Testing Request Assigned to You</h2>
<p style="color:#555;margin-top:0;">Hi {tester_name}, you have been assigned to carry out a field test.</p>

<table width="100%" cellpadding="0" cellspacing="0"
  style="border-collapse:collapse;font-size:13px;margin-bottom:16px;">
  <tr>
    <td style="padding:8px 0;color:#888;width:160px;">Request Number</td>
    <td style="padding:8px 0;font-weight:600;color:#0F172A;">{request_number}</td>
  </tr>
  <tr>
    <td style="padding:8px 0;color:#888;">Equipment</td>
    <td style="padding:8px 0;font-weight:600;color:#0F172A;">{equipment}</td>
  </tr>
  <tr>
    <td style="padding:8px 0;color:#888;">Equipment Type</td>
    <td style="padding:8px 0;color:#0F172A;">{equipment.type}</td>
  </tr>
  <tr>
    <td style="padding:8px 0;color:#888;">Station</td>
    <td style="padding:8px 0;color:#0F172A;">{dept.name}</td>
  </tr>
  <tr>
    <td style="padding:8px 0;color:#888;">Test Type</td>
    <td style="padding:8px 0;color:#0F172A;">{tr.test_type}</td>
  </tr>
  <tr>
    <td style="padding:8px 0;color:#888;">Priority</td>
    <td style="padding:8px 0;color:#0F172A;">{request.priority}</td>
  </tr>
</table>

{kit_availability_html}

<p style="margin-top:20px;">
  Please log in to the SEACMS app to acknowledge and begin testing.
  Collect any required kits before proceeding to the site.
</p>
"""


def update_tester_assigned_email_template():
    """
    Update the existing tester_assigned / email NotificationTemplate body
    to include the kit availability section.
    Idempotent — safe to run multiple times.
    """
    from models import NotificationTemplate
    db = SessionLocal()
    try:
        tmpl = db.query(NotificationTemplate).filter(
            NotificationTemplate.event_type == "tester_assigned",
            NotificationTemplate.channel == "email",
            NotificationTemplate.organization_id.is_(None),
        ).first()

        if not tmpl:
            print("[SKIP] tester_assigned/email template not found — run add_request_notification_templates.py first")
            return

        if "{kit_availability_html}" in (tmpl.body_template or ""):
            print("[SKIP] tester_assigned/email template already has kit_availability_html")
            return

        tmpl.body_template = TESTER_ASSIGNED_EMAIL_BODY
        tmpl.subject_template = "Testing Assignment: {request_number}"
        db.commit()
        print("[OK]   Updated tester_assigned/email template with kit availability section")
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    db = SessionLocal()
    try:
        run(db)
    except Exception as e:
        db.rollback()
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()

    print()
    try:
        seed_module_and_privileges()
    except Exception as e:
        print(f"ERROR (module/privileges): {e}", file=sys.stderr)
        sys.exit(1)

    print()
    try:
        update_tester_assigned_email_template()
    except Exception as e:
        print(f"ERROR (email template update): {e}", file=sys.stderr)
        sys.exit(1)
