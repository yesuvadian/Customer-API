from contextlib import contextmanager
from datetime import datetime
from database import SessionLocal
from models import CategoryDetails, CategoryMaster, Country, Division, Plan, Product, ProductCategory, ProductSubCategory, Role, RoleModulePrivilege, State, User, UserRole, Module ,City
from security_utils import get_password_hash  # password hashing utils

# Context manager for DB session
@contextmanager
def get_db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ----------------- Seed Functions -----------------

def seed_users(session):
    users_data = [
        {"first_name": "Admin", "last_name": "User", "email": "admin@relu.com",
         "phone_number": "9999999999", "password": "Admin@123"},
        {"first_name": "Viewer", "last_name": "User", "email": "viewer@relu.com",
         "phone_number": "8888888888", "password": "Viewer@123"},
        {"first_name": "Operator", "last_name": "User", "email": "operator@relu.com",
         "phone_number": "7777777777", "password": "Operator@123"},
        {"first_name": "Auditor", "last_name": "User", "email": "auditor@relu.com",
         "phone_number": "6666666666", "password": "Auditor@123"},
    ]

    for u in users_data:
        existing_user = session.query(User).filter_by(email=u["email"]).first()
        if not existing_user:
            user = User(
                firstname=u["first_name"],
                lastname=u["last_name"],
                email=u["email"],
                phone_number=u["phone_number"],
                password_hash=get_password_hash(u["password"]),
                isactive=1
            )
            session.add(user)
        else:
            existing_user.isactive = 1
            existing_user.password_hash = get_password_hash(u["password"])
    session.commit()
    print("✅ Users seeded successfully.")


def seed_roles(session):
    roles_data = [
        {"name": "Admin", "description": "Full access to all modules"},
        {"name": "Viewer", "description": "Read-only access"},
        {"name": "Operator", "description": "Can scan and submit inventory"},
        {"name": "Auditor", "description": "Can view scan history and audit trails"}
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
    print("✅ Roles seeded successfully.")
    return role_ids


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
    print("✅ Plans seeded successfully.")
def seed_category_master(session):
    """Seeds the CategoryMaster table with ONLY the 'Company Documents' category."""
    
    category_master_data = [
        {"name": "Company Documents", "description": "Mandatory compliance, technical, and financial documentation."},
    ]

    master_ids = {}
    for c in category_master_data:
        # Check if it already exists
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
            # Update existing if needed
            existing.description = c["description"]
            existing.is_active = True
            master_ids[c["name"]] = existing.id
            
    session.commit()
    print("✅ Category Master 'Company Documents' seeded successfully.")
    return master_ids
def seed_category_details(session, master_ids):
    """Seeds the CategoryDetails table ONLY for the 'Company Documents' master."""
    
    category_details_data = [
        # Company Documents Details
        {"master_name": "Company Documents", "name": "Quality Manual", "description": "Document outlining the organization's quality management system."},
        {"master_name": "Company Documents", "name": "Manufacturing Capability", "description": "Documentation detailing production capacity and infrastructure."},
        {"master_name": "Company Documents", "name": "Technical Specifications", "description": "Detailed engineering and product specifications."},
        {"master_name": "Company Documents", "name": "Type Test Reports", "description": "Reports from accredited labs confirming product type compliance."},
        {"master_name": "Company Documents", "name": "List of Machineries", "description": "Inventory of primary manufacturing and support machinery."},
        {"master_name": "Company Documents", "name": "List of Testing Equipment's", "description": "Inventory of quality control and measurement equipment."},
        {"master_name": "Company Documents", "name": "Employee Count", "description": "Official report on the total number of employees."},
        {"master_name": "Company Documents", "name": "Lists of Clients", "description": "Reference list of major and relevant clients."},
        {"master_name": "Company Documents", "name": "ISO 9001:2015 & ISO 14001:2015 certificate", "description": "Current ISO quality and environmental management certificates."},
        {"master_name": "Company Documents", "name": "Bank Financial Capability", "description": "Bank statement or certificate proving financial stability/capability."},
        {"master_name": "Company Documents", "name": "Audit Report", "description": "Latest external financial audit report."},
        {"master_name": "Company Documents", "name": "Profit and Loss", "description": "Most recent Profit and Loss (Income) Statement."},
        {"master_name": "Company Documents", "name": "3 years cash flow statement", "description": "Cash flow statements for the last three financial years."},
    ]

    for d in category_details_data:
        master_name = d["master_name"]
        detail_name = d["name"]
        master_id = master_ids.get(master_name)
        
        if not master_id:
            # This should not happen if master_ids comes from the updated seed_category_master
            print(f"⚠️ Master category not found for detail: {detail_name} (Master: {master_name})")
            continue

        existing = session.query(CategoryDetails).filter_by(
            name=detail_name,
            category_master_id=master_id 
        ).first()
        
        description = d["description"]
        
        if not existing:
            detail = CategoryDetails(
                name=detail_name,
                description=description,
                category_master_id=master_id,
                is_active=True
            )
            session.add(detail)
        else:
            existing.description = description
            existing.is_active = True
            existing.category_master_id = master_id 
            
    session.commit()
    print("✅ Category Details for 'Company Documents' seeded successfully.")
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
        print("✅ India seeded successfully.")
    else:
        print("ℹ️ India already exists in countries table.")
        
def seed_modules(session):
    modules_data = [
        {"name": "Roles", "description": "Manage roles", "path": "roles", "group_name": "User & Access"},
        {"name": "App Modules", "description": "Manage application modules", "path": "modules", "group_name": "User & Access"},
        {"name": "User Roles", "description": "Assign roles to users", "path": "roles", "group_name": "User & Access"},
        {"name": "Role Permissions", "description": "Configure role-based privileges", "path": "role_module_privileges", "group_name": "User & Access"},
        {"name": "Login Sessions", "description": "Track user login sessions", "path": "user_sessions", "group_name": "User & Access"},
        {"name": "Countries", "description": "Manage country list", "path": "countries", "group_name": "Geography"},
        {"name": "States", "description": "Manage state list", "path": "states", "group_name": "Geography"},
        {"name": "Addresses", "description": "User address book", "path": "addresses", "group_name": "User & Access"},
        {"name": "Tax Information", "description": "Company tax registration details", "path": "company_tax_info", "group_name": "Company"},
        {"name": "Tax Documents", "description": "Upload company tax documents", "path": "company_tax_documents", "group_name": "Company"},
        {"name": "Product Categories", "description": "Define product categories", "path": "categories", "group_name": "Inventory"},
        {"name": "Product Subcategories", "description": "Define product subcategories", "path": "subcategories", "group_name": "Inventory"},
        {"name": "Products", "description": "Manage product master", "path": "products", "group_name": "Inventory"},
        {"name": "Users", "description": "Manage users", "path": "users", "group_name": "User & Access"},
        {"name": "Company Products", "description": "Company-specific product inventory", "path": "company_products", "group_name": "Inventory"},
        {"name": "Plans", "description": "Manage subscription plans", "path": "plans", "group_name": "User & Access"},
         {"name": "Dashboard", "description": "Admin dashboard", "path": "dashboard", "group_name": "Inventory"},
         {"name": "Assign User Roles", "description": "Assign roles to users", "path": "user_roles", "group_name": "User & Access"},
         {"name": "User Product Search", "description": "Filtering user", "path": "user_product_search", "group_name": "User & Access"},
         {"name": "Bank Information", "description": "Company bank account information", "path": "company_bank_info", "group_name": "Company"},
        {"name": "Bank Documents", "description": "Upload company bank documents", "path": "bank_documents", "group_name": "Company"},

        {"name": "Company Product Certificates", "description": "Upload product performance certificates", "path": "company_product_certificates", "group_name": "Company"},
{"name": "Company Product Supply References", "description": "Upload supply reference documents for company products", "path": "company_product_supply_references", "group_name": "Company"},
{"name": "Divisions", "description": "Manage company divisions for approvals", "path": "divisions", "group_name": "Company"},
{"name": "User Documents", "description": "Upload and manage user-specific documents by division", "path": "user_documents", "group_name": "Company"},
{"name": "Sync ERP Vendor", "description": "Sync pending users to ERP", "path": "erp", "group_name": "ERP"},
{"name": "Category Master", "description": "Manage top-level categories for documents/assets (e.g., Company Documents)", "path": "category_master", "group_name": "Documents category"},
{"name": "Category Details", "description": "Manage detailed items under Category Master (e.g., Quality Manual)", "path": "category_details", "group_name": "Documents category"},
{"name": "KYC Status", "description": "Check user pending KYC sections", "path": "kyc", "group_name": "Company"},



    ]

    module_ids = {}
    for m in modules_data:
        existing_module = session.query(Module).filter_by(name=m["name"]).first()
        if not existing_module:
            module = Module(
                name=m["name"],
                description=m["description"],
                path=m["path"],
                group_name=m["group_name"],
                is_active=True
            )
            session.add(module)
            session.flush()
            module_ids[m["name"]] = module.id
        else:
            existing_module.description = m["description"]
            existing_module.path = m["path"]
            existing_module.group_name = m["group_name"]
            existing_module.is_active = True
            module_ids[m["name"]] = existing_module.id

    session.commit()
    print("✅ Modules seeded successfully.")
    return module_ids


def seed_privileges(session, role_ids, module_ids):
    module_names = [
    "Roles", "App Modules", "User Roles", "Role Permissions", "Login Sessions",
    "Countries", "States", "Addresses", "Tax Information", "Tax Documents",
    "Product Categories", "Product Subcategories", "Products", "Users",
    "Company Products", "Plans", "Dashboard", "Assign User Roles",
    "User Product Search", "Bank Information", "Bank Documents",
    "Divisions", "User Documents",
    "Company Product Certificates", "Company Product Supply References",
    "Category Master", "Category Details", 
    "Sync ERP Vendor","KYC Status"           
    ]




    privileges_data = [
        # Admin full access
        *[
            {
                "role": "Admin",
                "module": module,
                "can_view": True,
                "can_add": True,
                "can_edit": True,
                "can_delete": True,
                "can_search": True,
                "can_import": True,
                "can_export": True
            }
            for module in module_names
        ],
        # Viewer read-only access
        *[
            {
                "role": "Viewer",
                "module": module,
                "can_view": True
            }
            for module in module_names
        ],
        # Operator limited access
        *[
            {
                "role": "Operator",
                "module": module,
                "can_view": True,
                "can_search": module in ["Products", "Company Products", "Login Sessions"]
            }
            for module in ["Products", "Company Products", "Login Sessions"]
        ],
        # Auditor view-only access
        *[
            {
                "role": "Auditor",
                "module": module,
                "can_view": True,
                "can_search": module in ["Products", "Company Products", "Login Sessions"]
            }
            for module in module_names
        ]
    ]

    for p in privileges_data:
        role_id = role_ids.get(p["role"])
        module_id = module_ids.get(p["module"])
        if not role_id or not module_id:
            print(f"⚠️ Skipping privilege for missing role or module: {p['role']} - {p['module']}" )
            continue

        exists = session.query(RoleModulePrivilege).filter_by(
            role_id=role_id, module_id=module_id
        ).first()

        if not exists:
            privilege = RoleModulePrivilege(
                role_id=role_id,
                module_id=module_id,
                can_view=p.get("can_view", False),
                can_add=p.get("can_add", False),
                can_edit=p.get("can_edit", False),
                can_delete=p.get("can_delete", False),
                can_search=p.get("can_search", False),
                can_import=p.get("can_import", False),
                can_export=p.get("can_export", False)
            )
            session.add(privilege)

    session.commit()
    print("✅ Role-module privileges seeded successfully.")


def seed_user_roles(session, role_ids):
    user_roles_data = [
        {"email": "admin@relu.com", "role": "Admin"},
        {"email": "viewer@relu.com", "role": "Viewer"},
        {"email": "operator@relu.com", "role": "Operator"},
        {"email": "auditor@relu.com", "role": "Auditor"}
    ]

    for ur in user_roles_data:
        user = session.query(User).filter_by(email=ur["email"]).first()
        role_id = role_ids.get(ur["role"])
        if user and role_id:
            exists = session.query(UserRole).filter_by(user_id=user.id, role_id=role_id).first()
            if not exists:
                session.add(UserRole(user_id=user.id, role_id=role_id))
    session.commit()
    print("✅ User-role assignments seeded successfully.")


# ----------------- TNEB Product Seed -----------------

def seed_product_categories(session):
 
    categories_data = [
        {"name": "Transformers", "description": "Distribution and power transformers"},
        {"name": "Meters", "description": "Electricity meters – single phase, three phase"},
        {"name": "Cables & Wires", "description": "Electrical cables, wires, and conductors"},
        {"name": "Switchgear & Panels", "description": "Circuit breakers, panels, and switchgear"},
        {"name": "Street Lighting", "description": "LED lamps, poles, and lighting equipment"},
        {"name": "Tools & Accessories", "description": "Electrical tools, testers, and accessories"},
        {"name": "Solar Combiner Boxes", "description": "Polycarbonate and FRP/GRP enclosures for solar combiner systems"},
        {"name": "Cable Glands", "description": "Brass and polyamide cable glands for secure cable terminations"},
        {"name": "Sockets", "description": "Panel-mounted sockets for industrial power connections"},
        {"name": "Plug", "description": "Industrial power plugs for electrical connections"},
        {"name": "Fuse Holder", "description": "Fuse holders for electrical and photovoltaic protection"},
        {"name": "Fuse", "description": "Fuses for circuit protection and electrical safety"},
        {"name": "EV Changer", "description": "AC, DC, and EV charging connectors"},
        {"name": "Surge Protection", "description": "Devices for surge and overvoltage protection"},
        {"name": "Filteration", "description": "Transformer oil filtration systems"},
        {"name": "Transformer Safety", "description": "Transformer safety and fire protection systems"},
        
  {"name": "Poles", "description": "Poles"},
  {"name": "Cross Arms", "description": "Cross Arms"},
  {"name": "Supports", "description": "Supports"},
  {"name": "Accessories", "description": "Accessories"},
  {"name": "Earthing", "description": "Earthing"},
  {"name": "Clamps", "description": "Clamps"},
  {"name": "Anchors", "description": "Anchors"},
  {"name": "Plates", "description": "Plates"},
  {"name": "Insulators", "description": "Insulators"},
  {"name": "Conductors", "description": "Conductors"},
  {"name": "Wires", "description": "Wires"},
  {"name": "Connectors", "description": "Connectors"},
  {"name": "Transformers", "description": "Various types of electrical transformers"},
  {"name": "Transformer Oils", "description": "Transformer oils"},
  {"name": "Protection", "description": "Protection equipment"},
  {"name": "Distribution Boxes", "description": "Distribution boxes"},
  {"name": "Lightning Arresters", "description": "Lightning arresters"},
  {"name": "Fuses", "description": "Fuse units"},
  {"name": "Mounting Structures", "description": "Mounting structures"},
  {"name": "H Frames", "description": "H frame structures"},
  {"name": "Platforms", "description": "Platforms and FRP components"},
  {"name": "GOS", "description": "Gang operated switches"},
  {"name": "GOS Components", "description": "Components for GOS"},
  {"name": "DOLO", "description": "Drop out fuse (DOLO)"}


    ]


    category_ids = {}
    for c in categories_data:
        existing = session.query(ProductCategory).filter_by(name=c["name"]).first()
        if not existing:
            category = ProductCategory(
                name=c["name"],
                description=c["description"],
               # path=f"category_{c['name'].lower().replace(' ', '_')}",
                #group_name="Inventory",
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
    print("✅ Product categories seeded successfully.")
    return category_ids

def seed_divisions(session):
    """
    Seeds default divisions that can be used for approval and user document uploads.
    """
    divisions_data = [
        {"division_name": "Electrical Division", "code": "ELEC", "is_active": True, "description": "Handles all electrical-related approvals"},
        {"division_name": "Mechanical Division", "code": "MECH","is_active": True, "description": "Handles mechanical and fabrication approvals"},
        {"division_name": "Civil Division", "code": "CIVIL","is_active": True, "description": "Handles civil and infrastructure approvals"},
        {"division_name": "IT Division", "code": "IT","is_active": True, "description": "Handles IT, software, and digital infrastructure"},
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
    print("✅ Divisions seeded successfully.")

def seed_product_subcategories(session, category_ids):
    subcategories_data = [
        {"name": "Distribution Transformers", "category": "Transformers"},
        {"name": "Three Phase Meters", "category": "Meters"},
        {"name": "XLPE Cables", "category": "Cables & Wires"},
        {"name": "Circuit Breakers", "category": "Switchgear & Panels"},
        {"name": "LED Lamps", "category": "Street Lighting"},
        {"name": "Testers", "category": "Tools & Accessories"},
        {"name": "Polycarbonate Enclosures", "category": "Solar Combiner Boxes"},
        {"name": "FRP/GRP Enclosures", "category": "Solar Combiner Boxes"},
        {"name": "Brass", "category": "Cable Glands"},
        {"name": "Polyamide", "category": "Cable Glands"},
        {"name": "Panel Mounted Sockets", "category": "Sockets"},
        {"name": "Industrial Plug", "category": "Plug"},
        {"name": "Fuse Accessories", "category": "Fuse Holder"},
        {"name": "Fuse Links", "category": "Fuse"},
        {"name": "EV Connectors", "category": "EV Changer"},
        {"name": "SPD", "category": "Surge Protection"},
        {"name": "Filteration", "category": "Filteration"},
        {"name": "Transformer Safety", "category": "Transformer Safety"},
    
  {"name": "RCC Poles", "category": "Poles"},
  {"name": "PSCC Poles", "category": "Poles"},
  {"name": "Tubular Spun Poles", "category": "Poles"},
  
  {"name": "Mild Steel Cross Arms", "category": "Cross Arms"},
  {"name": "Galvanized Iron Cross Arms", "category": "Cross Arms"},
  {"name": "SMC Cross Arms", "category": "Cross Arms"},
  
  {"name": "Mild Steel Supports", "category": "Supports"},
  {"name": "Galvanized Iron Supports", "category": "Supports"},
  
  {"name": "Stirrups", "category": "Accessories"},
  {"name": "Spikes", "category": "Accessories"},
  
  {"name": "Electrodes", "category": "Earthing"},
  
  {"name": "Mild Steel Clamps", "category": "Clamps"},
  {"name": "Galvanized Iron Clamps", "category": "Clamps"},
  {"name": "Strain Clamps", "category": "Clamps"},
  {"name": "T-Clamps", "category": "Clamps"},
  {"name": "Pad Clamps", "category": "Clamps"},
  
  {"name": "Mild Steel Anchor Rods", "category": "Anchors"},
  {"name": "Galvanized Iron Anchor Rods", "category": "Anchors"},
  
  {"name": "Mild Steel Plates", "category": "Plates"},
  {"name": "Galvanized Iron Plates", "category": "Plates"},
  
  {"name": "Ceramic Pin Insulators", "category": "Insulators"},
  {"name": "GI Pins", "category": "Insulators"},
  {"name": "Polymeric Pin Insulators", "category": "Insulators"},
  {"name": "Strain Insulators", "category": "Insulators"},
  {"name": "Disc Insulators", "category": "Insulators"},
  {"name": "Polymeric Insulators", "category": "Insulators"},
  
  {"name": "ACSR Conductors", "category": "Conductors"},
  {"name": "Aluminium Conductors", "category": "Conductors"},
  
  {"name": "Guy Wires", "category": "Wires"},
  {"name": "GI Wires", "category": "Wires"},
  {"name": "Barbed Wire", "category": "Wires"},
  
  {"name": "ACSR Connectors", "category": "Connectors"},
  {"name": "Wedge Connectors", "category": "Connectors"},
  
  {"name": "Distribution Transformers", "category": "Transformers"},
  {"name": "Conventional Transformers", "category": "Transformers"},
  {"name": "Star Rated Transformers", "category": "Transformers"},
  
  {"name": "EHV Grade Oil", "category": "Transformer Oils"},
  {"name": "Reclaimed Oil", "category": "Transformer Oils"},
  {"name": "Contaminated Oil", "category": "Transformer Oils"},
  
  {"name": "LT Kits", "category": "Protection"},
  
  {"name": "Sheet Metal Boxes", "category": "Distribution Boxes"},
  {"name": "SMC Boxes", "category": "Distribution Boxes"},
  
  {"name": "Ceramic Arresters", "category": "Lightning Arresters"},
  {"name": "Polymeric Arresters", "category": "Lightning Arresters"},
  
  {"name": "HG Fuse Units", "category": "Fuses"},
  
  {"name": "MS Structures", "category": "Mounting Structures"},
  {"name": "GI Structures", "category": "Mounting Structures"},
  
  {"name": "MS Structures", "category": "H Frames"},
  {"name": "GI Structures", "category": "H Frames"},
  
  {"name": "MS Structures", "category": "Platforms"},
  {"name": "FRP Components", "category": "Platforms"},
  
  {"name": "Conventional", "category": "GOS"},
  {"name": "Polymer", "category": "GOS"},
  {"name": "Special Roaster", "category": "GOS"},
  
  {"name": "Contacts", "category": "GOS Components"},
  {"name": "Operating Rods", "category": "GOS Components"},
  
  {"name": "Conventional", "category": "DOLO"},
  {"name": "REC Specification", "category": "DOLO"}
]

    



    subcategory_ids = {}
    for sc in subcategories_data:
        category_name = sc["category"]
        subcategory_name = sc["name"]
        category_id = category_ids.get(category_name)
        if not category_id:
            print(f"⚠️ Category not found for subcategory: {subcategory_name}")
            continue

        existing = session.query(ProductSubCategory).filter_by(
            name=subcategory_name,
            category_id=category_id 
        ).first()
        description = f"{subcategory_name} under {category_name}"
        if not existing:
            subcat = ProductSubCategory(
                name=subcategory_name,
                description=description,
                category_id=category_id,  # ✅ FIX 2: Assign category_id during creation
                #path=f"subcategory_{sc['name'].lower().replace(' ', '_')}",
                #group_name="Inventory",
                is_active=True
            )
            session.add(subcat)
            session.flush()
            # Store the subcategory ID using its name (or its unique name+category combo)
            subcategory_ids[subcategory_name] = subcat.id 
        else:
            existing.description = description
            existing.is_active = True
            existing.category_id = category_id # Update category_id on existing for consistency
            subcategory_ids[subcategory_name] = existing.id

    session.commit()
    print("✅ Product subcategories seeded successfully.")
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
    print("✅ Indian states seeded successfully.")
    return inserted_states

# ----------------- Country & States Seed -----------------
def seed_india_country(session):
    india = session.query(Country).filter_by(name="INDIA").first()
    if not india:
        india = Country(name="INDIA", code="IND", erp_external_id="1473917605099")
        session.add(india)
        session.commit()
        print("✅ India seeded successfully.")
        
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
        {"name": "Surge Protection Device", "category": "Surge Protection", "subcategory": "SPD", "sku": "", "description": "Surge protection device"},
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
    print("✅ Existing data + file data seeded successfully.")
    

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
            print(f"⚠️ State '{c['statename']}' not found. Skipping city '{c['name']}'.")
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
    print("✅ Cities seeded successfully.")
# ----------------- Run Seed -----------------

def run_seed():
    with get_db_session() as session:
        role_ids = seed_roles(session)
        seed_users(session)
        module_ids = seed_modules(session)
        seed_privileges(session, role_ids, module_ids)
        seed_user_roles(session, role_ids)
        seed_plans(session)
        category_ids = seed_product_categories(session)
        subcategory_ids = seed_product_subcategories(session, category_ids)
        seed_products(session, category_ids, subcategory_ids)
            # Geography
        seed_country_india
        india = seed_india_country(session)
        state_ids=seed_indian_states(session, india)
        seed_cities(session,state_ids)
        seed_divisions(session)
        master_ids=seed_category_master(session)
        seed_category_details(session, master_ids)
        print("✅ All seed data inserted successfully.")


if __name__ == "__main__":
    try:
        run_seed()
    except Exception as e:
        import traceback
        traceback.print_exc()
