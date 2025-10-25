from contextlib import contextmanager
from datetime import datetime
from database import SessionLocal
from models import Country, Plan, Product, ProductCategory, ProductSubCategory, Role, RoleModulePrivilege, State, User, UserRole, Module
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

def seed_country_india(session):
    existing = session.query(Country).filter_by(name="India").first()
    if not existing:
        country = Country(
            name="India",
            code="IN"
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
        "Product Categories", "Product Subcategories", "Products", "Users", "Company Products","Plans","Dashboard"
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
            print(f"⚠️ Skipping privilege for missing role or module: {p['role']} - {p['module']}")
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


def seed_product_subcategories(session, category_ids):
    subcategories_data = [
        {"name": "Distribution Transformers", "category": "Transformers"},
        {"name": "Power Transformers", "category": "Transformers"},
        {"name": "Single Phase Meters", "category": "Meters"},
        {"name": "Three Phase Meters", "category": "Meters"},
        {"name": "XLPE Cables", "category": "Cables & Wires"},
        {"name": "PVC Wires", "category": "Cables & Wires"},
        {"name": "Overhead Conductors", "category": "Cables & Wires"},
        {"name": "Circuit Breakers", "category": "Switchgear & Panels"},
        {"name": "Panels", "category": "Switchgear & Panels"},
        {"name": "Relays", "category": "Switchgear & Panels"},
        {"name": "LED Lamps", "category": "Street Lighting"},
        {"name": "Poles", "category": "Street Lighting"},
        {"name": "Solar Street Lights", "category": "Street Lighting"},
        {"name": "Testers", "category": "Tools & Accessories"},
        {"name": "Hand Tools", "category": "Tools & Accessories"},
        {"name": "Safety Equipment", "category": "Tools & Accessories"},
    ]

    subcategory_ids = {}
    for sc in subcategories_data:
        category_id = category_ids.get(sc["category"])
        if not category_id:
            print(f"⚠️ Category not found for subcategory: {sc['name']}")
            continue

        existing = session.query(ProductSubCategory).filter_by(name=sc["name"]).first()
        if not existing:
            subcat = ProductSubCategory(
                name=sc["name"],
                description=f"{sc['name']} under {sc['category']}",
                #path=f"subcategory_{sc['name'].lower().replace(' ', '_')}",
                #group_name="Inventory",
                is_active=True
            )
            session.add(subcat)
            session.flush()
            subcategory_ids[sc["name"]] = subcat.id
        else:
            existing.description = f"{sc['name']} under {sc['category']}"
            existing.is_active = True
            subcategory_ids[sc["name"]] = existing.id

    session.commit()
    print("✅ Product subcategories seeded successfully.")
    return subcategory_ids
def seed_indian_states(session, india):
    states_data = [
        {"name": "Andhra Pradesh", "code": "AP"},
        {"name": "Arunachal Pradesh", "code": "AR"},
        {"name": "Assam", "code": "AS"},
        {"name": "Bihar", "code": "BR"},
        {"name": "Chhattisgarh", "code": "CG"},
        {"name": "Goa", "code": "GA"},
        {"name": "Gujarat", "code": "GJ"},
        {"name": "Haryana", "code": "HR"},
        {"name": "Himachal Pradesh", "code": "HP"},
        {"name": "Jharkhand", "code": "JH"},
        {"name": "Karnataka", "code": "KA"},
        {"name": "Kerala", "code": "KL"},
        {"name": "Madhya Pradesh", "code": "MP"},
        {"name": "Maharashtra", "code": "MH"},
        {"name": "Manipur", "code": "MN"},
        {"name": "Meghalaya", "code": "ML"},
        {"name": "Mizoram", "code": "MZ"},
        {"name": "Nagaland", "code": "NL"},
        {"name": "Odisha", "code": "OR"},
        {"name": "Punjab", "code": "PB"},
        {"name": "Rajasthan", "code": "RJ"},
        {"name": "Sikkim", "code": "SK"},
        {"name": "Tamil Nadu", "code": "TN"},
        {"name": "Telangana", "code": "TG"},
        {"name": "Tripura", "code": "TR"},
        {"name": "Uttar Pradesh", "code": "UP"},
        {"name": "Uttarakhand", "code": "UK"},
        {"name": "West Bengal", "code": "WB"},
        {"name": "Andaman and Nicobar Islands", "code": "AN"},
        {"name": "Chandigarh", "code": "CH"},
        {"name": "Dadra and Nagar Haveli and Daman & Diu", "code": "DN"},
        {"name": "Delhi", "code": "DL"},
        {"name": "Jammu and Kashmir", "code": "JK"},
        {"name": "Ladakh", "code": "LA"},
        {"name": "Lakshadweep", "code": "LD"},
        {"name": "Puducherry", "code": "PY"},
    ]

    for s in states_data:
        existing = session.query(State).filter_by(name=s["name"], country_id=india.id).first()
        if not existing:
            state = State(name=s["name"], code=s["code"], country_id=india.id)
            session.add(state)
    session.commit()
    print("✅ Indian states seeded successfully.")
# ----------------- Country & States Seed -----------------
def seed_india_country(session):
    india = session.query(Country).filter_by(name="India").first()
    if not india:
        india = Country(name="India", code="IN")
        session.add(india)
        session.commit()
        print("✅ India seeded successfully.")
    return session.query(Country).filter_by(name="India").first()

def seed_products(session, category_ids, subcategory_ids):
    products_data = [
        {"name": "11kV Distribution Transformer 100 kVA", "category": "Transformers", "subcategory": "Distribution Transformers", "sku": "TNEB-TR100", "description": "Oil-immersed 11kV transformer for distribution"},
        {"name": "3 Phase Energy Meter", "category": "Meters", "subcategory": "Three Phase Meters", "sku": "TNEB-MTR3P", "description": "3 phase digital energy meter"},
        {"name": "XLPE Power Cable 1.1kV 50mm²", "category": "Cables & Wires", "subcategory": "XLPE Cables", "sku": "TNEB-CBL50", "description": "XLPE insulated 1.1kV power cable"},
        {"name": "Air Circuit Breaker 400A", "category": "Switchgear & Panels", "subcategory": "Circuit Breakers", "sku": "TNEB-ACB400", "description": "400A air circuit breaker"},
        {"name": "LED Street Light 50W", "category": "Street Lighting", "subcategory": "LED Lamps", "sku": "TNEB-LED50", "description": "Energy-efficient 50W LED street lamp"},
        {"name": "Digital Clamp Meter", "category": "Tools & Accessories", "subcategory": "Testers", "sku": "TNEB-TLM01", "description": "Clamp meter for electrical measurements"},
    ]

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
                description=p["description"],
                is_active=True
            )
            session.add(product)
        else:
            existing.name = p["name"]
            existing.category_id = category_id
            existing.subcategory_id = subcategory_id
            existing.description = p["description"]
            existing.is_active = True

    session.commit()
    print("✅ Products seeded successfully.")


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
        india = seed_india_country(session)
        seed_indian_states(session, india)
        print("✅ All seed data inserted successfully.")


if __name__ == "__main__":
    try:
        run_seed()
    except Exception as e:
        import traceback
        traceback.print_exc()
