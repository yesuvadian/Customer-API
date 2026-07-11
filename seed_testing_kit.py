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


def seed_kit_mappings(db: Session):
    """
    Seed equipment_type → kit_type mappings using DB-resolved IDs.
    Idempotent — uses ON CONFLICT DO NOTHING via upsert.
    """
    from models import CategoryMaster, CategoryDetails, EquipmentTypeKitMapping

    # Resolve Testing Kit sub-type IDs by name
    def _kit_id(name: str) -> int:
        kit_master = db.query(CategoryMaster).filter(CategoryMaster.name == "Testing Kit").first()
        if not kit_master:
            raise RuntimeError("Testing Kit CategoryMaster not found — run seed first")
        cd = db.query(CategoryDetails).filter(
            CategoryDetails.category_master_id == kit_master.id,
            CategoryDetails.name == name,
        ).first()
        if not cd:
            raise RuntimeError(f"Kit sub-type '{name}' not found")
        return cd.id

    # Resolve equipment type CategoryMaster ID by name
    def _eq_type_id(name: str):
        cm = db.query(CategoryMaster).filter(CategoryMaster.name == name).first()
        return cm.id if cm else None

    # Mapping: equipment_type_name -> [(kit_name, is_required)]
    MAPPINGS = {
        "Power Transformer": [
            ("Oil BDV (Breakdown Voltage) Kit",     True),
            ("Insulation Resistance Tester",         True),
            ("High Voltage Test Set",                False),
            ("Power Analyzer",                       False),
            ("Partial Discharge Detector",           False),
            ("Infrared Thermometer / Thermal Camera",False),
        ],
        "Protection Relay": [
            ("Relay Test Kit",                       True),
            ("Multimeter / Clamp Meter",             True),
            ("Insulation Resistance Tester",         False),
        ],
        "Circuit Breaker": [
            ("Insulation Resistance Tester",         True),
            ("Earth Resistance Tester",              False),
            ("High Voltage Test Set",                False),
        ],
        "Current Transformer": [
            ("CT / PT Analyzer",                     True),
            ("Insulation Resistance Tester",         False),
        ],
        "Potential Transformer": [
            ("CT / PT Analyzer",                     True),
            ("Insulation Resistance Tester",         False),
        ],
        "Capacitor Voltage Transformer": [
            ("CT / PT Analyzer",                     True),
            ("Insulation Resistance Tester",         False),
        ],
        "Electronic Tri-vector Meter": [
            ("Multimeter / Clamp Meter",             True),
            ("Insulation Resistance Tester",         False),
        ],
    }

    total_added = 0
    for eq_type_name, kit_pairs in MAPPINGS.items():
        eq_id = _eq_type_id(eq_type_name)
        if not eq_id:
            print(f"[SKIP] Equipment type '{eq_type_name}' not found")
            continue
        for kit_name, required in kit_pairs:
            try:
                kit_id = _kit_id(kit_name)
            except RuntimeError as e:
                print(f"[WARN] {e}")
                continue
            existing = db.query(EquipmentTypeKitMapping).filter(
                EquipmentTypeKitMapping.equipment_type_id == eq_id,
                EquipmentTypeKitMapping.kit_type_id == kit_id,
            ).first()
            if existing:
                continue
            db.add(EquipmentTypeKitMapping(
                equipment_type_id=eq_id,
                kit_type_id=kit_id,
                is_required=required,
            ))
            total_added += 1

    db.commit()
    if total_added:
        print(f"[OK]   Seeded {total_added} equipment_type_kit_mappings rows")
    else:
        print("[SKIP] All kit mappings already exist")


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
        # 1. Ensure module exists with correct underscore path
        module = db.query(Module).filter(Module.name == "testing_kit_register").first()
        if module:
            if module.path != "/testing_kit_register":
                old_path = module.path
                module.path = "/testing_kit_register"
                print(f"[OK]   Fixed module path -> /testing_kit_register (was: {old_path})")
            else:
                print(f"[SKIP] Module 'testing_kit_register' already exists (id={module.id})")
        else:
            module = Module(
                name="testing_kit_register",
                description="Testing Kit Register — register and manage testing instruments",
                path="/testing_kit_register",
                group_name="ASSETS",
                is_active=True,
                is_menu=True,
            )
            db.add(module)
            db.flush()
            print(f"[OK]   Module 'testing_kit_register' created (id={module.id})")

        def _upsert_perm(role_obj, **flags):
            p = db.query(OrgRolePermission).filter(
                OrgRolePermission.org_role_id == role_obj.id,
                OrgRolePermission.module_id == module.id,
            ).first()
            if p:
                for k, v in flags.items():
                    setattr(p, k, v)
            else:
                defaults = dict(
                    can_view=False, can_add=False, can_edit=False,
                    can_delete=False, can_approve=False, can_assign=False,
                    can_export=False, can_import=False,
                )
                defaults.update(flags)
                db.add(OrgRolePermission(
                    id=uuid.uuid4(),
                    org_role_id=role_obj.id,
                    module_id=module.id,
                    **defaults,
                ))

        # 2. Asset Data Officer: read/write
        ado = db.query(OrgRole).filter(OrgRole.name == "Asset Data Officer").first()
        if ado:
            _upsert_perm(ado, can_view=True, can_add=True, can_edit=True)
            print("[OK]   Asset Data Officer -> testing_kit_register (RW)")
        else:
            print("[WARN] OrgRole 'Asset Data Officer' not found — skipping")

        # 3. Organization Admin (by name) + all is_org_admin roles: full access
        admin_roles = db.query(OrgRole).filter(
            OrgRole.is_active == True,
            (OrgRole.is_org_admin == True) | (OrgRole.name == "Organization Admin"),
        ).all()

        for ar in admin_roles:
            _upsert_perm(ar,
                         can_view=True, can_add=True, can_edit=True, can_delete=True,
                         can_approve=True, can_assign=True, can_export=True, can_import=True)
            print(f"[OK]   {ar.name} -> testing_kit_register (full access)")

        if not admin_roles:
            print("[WARN] No Organization Admin roles found")

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
        else:
            tmpl.body_template    = TESTER_ASSIGNED_EMAIL_BODY
            tmpl.subject_template = "Testing Assignment: {request_number}"
            print("[OK]   Updated tester_assigned/email template with kit availability section")

        # Always ensure attachment_vars includes the last test result PDF
        _att_var = {"var_key": "report.lastexecution.test_result_id", "type": "pdf", "source_type": "test_result"}
        existing_atts = list(tmpl.attachment_vars or [])
        if not any(a.get("var_key") == _att_var["var_key"] for a in existing_atts if isinstance(a, dict)):
            from sqlalchemy.orm.attributes import flag_modified
            tmpl.attachment_vars = existing_atts + [_att_var]
            flag_modified(tmpl, "attachment_vars")
            print("[OK]   Added last-execution PDF attachment_var to tester_assigned/email template")
        else:
            print("[SKIP] tester_assigned/email template already has last-execution PDF attachment_var")

        db.commit()
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def seed_kit_equipment_records(db: Session):
    """
    Seed representative physical testing kit equipment records for the KPTCL org.
    Distributes kits across a sample of leaf stations so the Testing Kit Register
    grid is populated. Idempotent — checks for existing kits before inserting.
    """
    from models import Organization, OrgDepartment, Equipment, CategoryMaster, CategoryDetails
    from services.equipment_service import EquipmentService
    import uuid as _uuid

    # Find KPTCL org
    org = db.query(Organization).filter(
        Organization.name.ilike("%Karnataka%")
    ).first()
    if not org:
        org = db.query(Organization).filter(
            Organization.name != "Sample Organization"
        ).first()
    if not org:
        print("[SKIP] No suitable organization found for kit equipment seed")
        return

    # Already has kits?
    kit_master = db.query(CategoryMaster).filter(CategoryMaster.name == "Testing Kit").first()
    if not kit_master:
        print("[SKIP] Testing Kit CategoryMaster not found")
        return

    existing = db.query(Equipment).filter(
        Equipment.organization_id == org.id,
        Equipment.equipment_type_id == kit_master.id,
    ).count()
    if existing > 0:
        print(f"[SKIP] {existing} kit equipment records already exist")
        return

    # Pick a few representative leaf stations
    all_depts = db.query(OrgDepartment).filter(
        OrgDepartment.organization_id == org.id,
        OrgDepartment.is_active == True,
    ).order_by(OrgDepartment.name).all()
    leaf_depts = [
        d for d in all_depts
        if not any(x.parent_department_id == d.id for x in all_depts)
    ][:8]  # seed up to 8 stations

    if not leaf_depts:
        leaf_depts = all_depts[:8]

    # Kit sub-types to distribute: required kits only
    kit_subtypes = db.query(CategoryDetails).filter(
        CategoryDetails.category_master_id == kit_master.id,
        CategoryDetails.name.in_([
            "Insulation Resistance Tester",
            "Oil BDV (Breakdown Voltage) Kit",
            "Relay Test Kit",
            "CT / PT Analyzer",
            "Multimeter / Clamp Meter",
        ]),
        CategoryDetails.is_active == True,
    ).all()

    added = 0
    # Define which station gets which kits (round-robin across stations)
    kit_station_map = [
        # (station_index, kit_subtype_name, manufacturer, model, serial, calib_last, calib_due)
        (0, "Insulation Resistance Tester", "Megger", "MIT525", "SN-MIT-001", "2025-06-01", "2026-06-01"),
        (0, "Oil BDV (Breakdown Voltage) Kit", "Baur", "OTS60AF", "SN-BDV-001", "2025-04-01", "2026-04-01"),
        (1, "Insulation Resistance Tester", "Fluke", "1550C", "SN-FLK-001", "2025-05-15", "2026-05-15"),
        (1, "Relay Test Kit", "Omicron", "CMC356", "SN-OMC-001", "2025-03-01", "2026-03-01"),
        (2, "CT / PT Analyzer", "Megger", "MPRT8", "SN-MPR-001", "2025-07-01", "2026-07-01"),
        (2, "Multimeter / Clamp Meter", "Fluke", "376FC", "SN-FLK-002", "2025-08-01", "2026-08-01"),
        (3, "Insulation Resistance Tester", "Megger", "MIT1025", "SN-MIT-002", "2025-09-01", "2026-09-01"),
        (4, "Oil BDV (Breakdown Voltage) Kit", "Megger", "OTS60SX", "SN-BDV-002", "2025-02-01", "2026-02-01"),
    ]

    subtype_map = {s.name: s for s in kit_subtypes}

    for (dept_idx, kit_name, mfr, model, serial, cal_last, cal_due) in kit_station_map:
        if dept_idx >= len(leaf_depts):
            continue
        dept = leaf_depts[dept_idx]
        kit_sub = subtype_map.get(kit_name)

        nameplate = {
            "kit_subtype":             kit_name,
            "manufacturer":            mfr,
            "model_number":            model,
            "factory_serial_number":   serial,
            "last_calibration_date":   cal_last,
            "calibration_due_date":    cal_due,
            "is_portable":             True,
        }

        existing = db.query(Equipment).filter_by(
            organization_id=org.id,
            factory_serial_number=serial,
        ).first()
        if existing:
            print(f"[SKIP] Kit '{kit_name}' @ {dept.name} already exists")
            continue

        from models import Equipment
        existing = db.query(Equipment).filter_by(
            organization_id=org.id,
            factory_serial_number=serial,
        ).first()
        if existing:
            print(f"[SKIP] Kit '{kit_name}' @ {dept.name} already exists")
            continue

        try:
            EquipmentService.create_equipment(
                db=db,
                organization_id=org.id,
                department_id=dept.id,
                equipment_type_id=kit_master.id,
                bay_number=kit_name,
                voltage_class="LV",
                manufacturer=mfr,
                model_number=model,
                factory_serial_number=serial,
                nameplate_data=nameplate,
            )
            db.flush()
            added += 1
            print(f"[OK]   Kit '{kit_name}' @ {dept.name}")
        except Exception as e:
            db.rollback()
            print(f"[WARN] Could not create kit '{kit_name}' @ {dept.name}: {e}")

    if added:
        db.commit()
        print(f"[OK]   Seeded {added} testing kit equipment records")
    else:
        print("[SKIP] No kit records added")


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
        db2 = SessionLocal()
        seed_kit_mappings(db2)
        db2.close()
    except Exception as e:
        print(f"ERROR (kit mappings): {e}", file=sys.stderr)
        sys.exit(1)

    print()
    try:
        db3 = SessionLocal()
        seed_kit_equipment_records(db3)
        db3.close()
    except Exception as e:
        print(f"ERROR (kit equipment records): {e}", file=sys.stderr)
        sys.exit(1)

    print()
    try:
        update_tester_assigned_email_template()
    except Exception as e:
        print(f"ERROR (email template update): {e}", file=sys.stderr)
        sys.exit(1)
