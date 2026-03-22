from contextlib import contextmanager
from datetime import datetime, timedelta
import uuid
import pandas as pd
from typing import Dict, Optional
from database import VendorSessionLocal
from models import (
    CategoryDetails, CategoryMaster, Country, Division, Plan, Product,
    ProductCategory, ProductSubCategory, Role, RoleModulePrivilege,
    State, City, User, UserRole, Module,
    # Organization models
    Organization, OrgDepartment, OrgRole, OrgUserRole,
    OrgRolePermission, RoleTemplate, OrgInvitation
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
                # ✅ ERP SERVICE USER
        {"first_name": "ERP", "last_name": "Service", "email": "erp_bot@relu.com",
         "phone_number": "4444444444", "password": "ErpBot@123"},
        # ✅ TESTING REQUEST SYSTEM USERS
        {"first_name": "Originator", "last_name": "User", "email": "dakshanamurthy@hotmail.com",
         "phone_number": "3333333333", "password": "Originator@123"},
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
        {"name": "Roles", "description": "Manage roles", "path": "roles", "group_name": "User & Access"},
        {"name": "App Modules", "description": "Manage application modules", "path": "modules", "group_name": "User & Access"},
        {"name": "User Roles", "description": "Assign roles to users", "path": "roles", "group_name": "User & Access", "is_active": False},
        {"name": "Role Permissions", "description": "Configure role-based privileges", "path": "role_module_privileges", "group_name": "User & Access"},
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
         {"name": "Assign User Roles", "description": "Assign roles to users", "path": "user_roles", "group_name": "User & Access"},
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
{"name": "RQ with Vendor", "description": "Request quotes with vendor selection", "path": "rqWithVendor", "group_name": "Procurement"},
{"name": "Request Product", "description": "Request new products", "path": "request_product", "group_name": "Procurement"},
{"name": "Quotes", "description": "View and manage quotes", "path": "quotes", "group_name": "Procurement"},
{"name": "Sales Orders", "description": "View and manage sales orders", "path": "sales_orders", "group_name": "Procurement"},  
{"name": "Invoices", "description": "View and manage invoices", "path": "invoices", "group_name": "Procurement"},
{"name": "Retainer Invoices", "description": "Manage retainer invoices", "path": "retainer_invoices", "group_name": "Procurement"},
{"name": "Payments Made", "description": "Track payments made", "path": "payments_made", "group_name": "Procurement"},
{"name": "Statements", "description": "View account statements", "path": "statements", "group_name": "Procurement"},
{"name": "Enquiry", "description": "Submit and manage enquiries", "path": "enquiry", "group_name": "Procurement"},
{"name": "Contact Us", "description": "Customer support", "path": "contact_us", "group_name": "Procurement"},
# ✅ TESTING REQUEST SYSTEM MODULES
{"name": "Testing Requests", "description": "Create and manage transformer testing requests", "path": "testing_requests", "group_name": "Testing"},
{"name": "Testing", "description": "Perform tests and upload results", "path": "testing", "group_name": "Testing"},
{"name": "Recommendations", "description": "Submit component recommendations", "path": "recommendations", "group_name": "Testing"},
{"name": "Approvals", "description": "Review and approve recommendations", "path": "approvals", "group_name": "Testing"},
{"name": "Validation Requests", "description": "Create and manage validation requests", "path": "validation_requests", "group_name": "Testing"},
{"name": "Tester Mapping", "description": "Map testers to locations (zone/circle/division)", "path": "tester_mapping", "group_name": "Testing"},
# ✅ ORGANIZATION MANAGEMENT MODULE
{"name": "Organizations", "description": "Manage organizations, departments, roles, and users", "path": "organizations", "group_name": "User & Access"},

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
                is_active=m.get("is_active", True)
            )
            session.add(module)
            session.flush()
            module_ids[m["name"]] = module.id

        else:
            existing.description = m["description"]
            existing.path = m["path"]
            existing.group_name = m["group_name"]

            # 🔥 MOST IMPORTANT FIX
            existing.is_active = m.get("is_active", True)

            module_ids[m["name"]] = existing.id

    session.commit()
    print("[OK] Modules seeded successfully.")
    return module_ids


def seed_privileges(session, role_ids, module_ids):
    module_names = [
    "Roles", "App Modules", "User Roles", "Role Permissions", "Login Sessions",
    "Countries", "States", "Cities","Addresses", "Tax Information", "Tax Documents",
    "Product Categories", "Product Subcategories", "Products", "Users",
    "Company Products", "Plans", "Dashboard", "Assign User Roles",
    "User Product Search", "Bank Information", "Bank Documents",
    "Divisions", "User Documents",
    "Company Product Certificates", "Company Product Supply References",
    "Category Master", "Category Details", 
    "Sync ERP Vendor","KYC Status" , "zohocontacts"      
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
        "Roles", "App Modules", "User Roles", "Role Permissions", "Login Sessions",
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
        "Testing Requests", "Testing", "Recommendations", "Approvals", "Validation Requests",
        # ✅ ORGANIZATION MANAGEMENT MODULE
        "Organizations"
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
    # ⭐ TESTING REQUEST SYSTEM PRIVILEGES
    # -------------------------------------------------------
    testing_privileges = [
        # ORIGINATOR — full on Testing Requests + Procurement, view on others, can_assign
        {
            "role": "Originator", "module": "Testing Requests",
            "can_view": True, "can_add": True, "can_edit": True,
            "can_delete": True, "can_search": True, "can_assign": True
        },
        {"role": "Originator", "module": "Testing", "can_view": True},
        {"role": "Originator", "module": "Recommendations", "can_view": True},
        {"role": "Originator", "module": "Approvals", "can_view": True},
        {
            "role": "Originator", "module": "Validation Requests",
            "can_view": True, "can_add": True, "can_edit": True, "can_search": True
        },
        {"role": "Originator", "module": "Dashboard", "can_view": True},
        # Originator — Procurement modules
        {"role": "Originator", "module": "Request Quote", "can_view": True, "can_add": True},
        {"role": "Originator", "module": "RQ with Vendor", "can_view": True, "can_add": True},
        {"role": "Originator", "module": "Request Product", "can_view": True, "can_add": True},
        {"role": "Originator", "module": "Quotes", "can_view": True},
        {"role": "Originator", "module": "Sales Orders", "can_view": True},
        {"role": "Originator", "module": "Invoices", "can_view": True},
        {"role": "Originator", "module": "Retainer Invoices", "can_view": True},
        {"role": "Originator", "module": "Payments Made", "can_view": True},
        {"role": "Originator", "module": "Statements", "can_view": True},
        {"role": "Originator", "module": "Enquiry", "can_view": True, "can_add": True},
        {"role": "Originator", "module": "Contact Us", "can_view": True},

        # TESTER — view Testing Requests, full on Testing + Recommendations
        {"role": "Tester", "module": "Testing Requests", "can_view": True},
        {
            "role": "Tester", "module": "Testing",
            "can_view": True, "can_add": True, "can_edit": True, "can_search": True
        },
        {
            "role": "Tester", "module": "Recommendations",
            "can_view": True, "can_add": True, "can_edit": True
        },
        {"role": "Tester", "module": "Dashboard", "can_view": True},

        # APPROVER — view Testing Requests + Recommendations, approve on Approvals
        {"role": "Approver", "module": "Testing Requests", "can_view": True},
        {"role": "Approver", "module": "Testing", "can_view": True},
        {"role": "Approver", "module": "Recommendations", "can_view": True},
        {
            "role": "Approver", "module": "Approvals",
            "can_view": True, "can_approve": True
        },
        {"role": "Approver", "module": "Dashboard", "can_view": True},

        # TESTER MAPPING — Admin full, Originator view-only
        {
            "role": "Admin", "module": "Tester Mapping",
            "can_view": True, "can_add": True, "can_edit": True,
            "can_delete": True, "can_search": True
        },
        {"role": "Originator", "module": "Tester Mapping", "can_view": True},
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

    equipment_tests = {
        # ── From user's Equipment → Test mapping ──
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
                    category_master_id=master_id,
                    is_active=True,
                ))
            else:
                existing_detail.is_active = True

    session.commit()
    print("[OK] Equipment & Test Type categories seeded successfully.")

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
    # Get all module IDs for permission templates
    all_modules = session.query(Module.id).filter(Module.is_active == True).all()
    module_ids = [m.id for m in all_modules]

    if not module_ids:
        print("[WARN] No modules found. Role templates will be created without permission templates.")
        module_ids = []

    templates_data = [
        {
            "name": "Admin",
            "description": "Full administrative access to the organization. Can manage users, roles, departments, and all organization resources.",
            "is_org_admin": True,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": True,
                    "can_approve": True,
                    "can_assign": True,
                    "can_export": True,
                    "can_import": True
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Originator",
            "description": "Creates testing requests and raises procurement. Full access to testing requests and procurement modules.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": True,
                    "can_approve": False,
                    "can_assign": True,
                    "can_export": True,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Tester",
            "description": "Performs transformer testing and uploads results. Full access to testing and recommendations modules.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": False,
                    "can_approve": False,
                    "can_assign": False,
                    "can_export": True,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Approver",
            "description": "Reviews and approves or rejects recommendations. Approval access to testing workflow.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": True,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_approve": True,
                    "can_assign": False,
                    "can_export": True,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Department Manager",
            "description": "Manage department users and departmental resources. Can view and manage users within their department.",
            "is_org_admin": False,
            "is_dept_admin": True,
            "auto_provision": False,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": False,
                    "can_approve": True,
                    "can_assign": False,
                    "can_export": True,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Employee",
            "description": "Standard employee access. Can view organization resources and manage their own data.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": False,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_approve": False,
                    "can_assign": False,
                    "can_export": False,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Viewer",
            "description": "Read-only access to organization resources.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": False,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": False,
                    "can_edit": False,
                    "can_delete": False,
                    "can_approve": False,
                    "can_assign": False,
                    "can_export": False,
                    "can_import": False
                }
                for mid in module_ids
            ]
        },
        {
            "name": "Contributor",
            "description": "Can add and edit resources but cannot delete or approve.",
            "is_org_admin": False,
            "is_dept_admin": False,
            "auto_provision": False,
            "permissions_template": [
                {
                    "module_id": mid,
                    "can_view": True,
                    "can_add": True,
                    "can_edit": True,
                    "can_delete": False,
                    "can_approve": False,
                    "can_assign": False,
                    "can_export": True,
                    "can_import": True
                }
                for mid in module_ids
            ]
        }
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


def seed_sample_organization(session):
    """
    Create a sample organization with admin user for testing.
    """
    org_code = "SAMPLE_ORG"

    # Check if organization already exists
    existing_org = session.query(Organization).filter_by(code=org_code).first()
    if existing_org:
        print(f"[INFO] Sample organization already exists: {org_code}")
        return

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
        is_active=True,
        is_verified=False,
        plan_id=plan_id,
        settings={},
        cts=datetime.now(datetime.now().astimezone().tzinfo),
        mts=datetime.now(datetime.now().astimezone().tzinfo)
    )
    session.add(org)
    session.flush()

    # Provision default roles from templates
    templates = session.query(RoleTemplate).filter_by(auto_provision=True).all()

    provisioned_roles = []
    for template in templates:
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


def seed_kptcl_departments(session, org_id: str, excel_path: str = r"C:\Users\yesuv\Downloads\KPTCL_Substation_Mapping.xlsx"):
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


# ----------------- Run Seed -----------------

def run_seed():
    with get_db_session() as session:
        print("\n" + "=" * 80)
        print("  DATABASE SEEDING STARTED")
        print("=" * 80 + "\n")

        # Core System
        migrate_testing_request_columns(session)
        role_ids = seed_roles(session)
        new_user_ids = seed_users(session)  # 👈 capture new users
        module_ids = seed_modules(session)
        seed_privileges(session, role_ids, module_ids)
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
        seed_tester_locations(session)
        seed_sample_testing_request(session)

        # Organization Multi-Tenancy System
        print("\n--- Organization System Seeding ---")
        seed_role_templates(session)
        seed_super_admin(session)
        seed_sample_organization(session)

        print("\n" + "=" * 80)
        print("  [OK] ALL SEED DATA INSERTED SUCCESSFULLY")
        print("=" * 80)
        print("\nQuick Start:")
        print("  1. Super Admin: superadmin@system.com / Admin123!")
        print("  2. Sample Org Admin: orgadmin@sampleorg.com / OrgAdmin123!")
        print("  3. View API docs: http://localhost:8000/docs")
        print("\n" + "=" * 80 + "\n")


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
