# seed.py
from contextlib import contextmanager
from datetime import datetime
from database import SessionLocal
from models import Role, RoleModulePrivilege, User, UserRole, Module
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


def seed_modules(session):
    modules_data = [
        {"name": "Roles", "description": "Manage roles", "path": "roles", "group_name": "User & Access"},
        {"name": "App Modules", "description": "Manage application modules", "path": "modules", "group_name": "User & Access"},
        {"name": "User Roles", "description": "Assign roles to users", "path": "user_roles", "group_name": "User & Access"},
        {"name": "Role Permissions", "description": "Configure role-based privileges", "path": "role_privileges", "group_name": "User & Access"},
        {"name": "Login Sessions", "description": "Track user login sessions", "path": "user_sessions", "group_name": "User & Access"},
        {"name": "Countries", "description": "Manage country list", "path": "countries", "group_name": "Geography"},
        {"name": "States", "description": "Manage state list", "path": "states", "group_name": "Geography"},
        {"name": "Addresses", "description": "User address book", "path": "user_addresses", "group_name": "User & Access"},
        {"name": "Tax Information", "description": "Company tax registration details", "path": "company_tax_info", "group_name": "Company"},
        {"name": "Tax Documents", "description": "Upload company tax documents", "path": "company_tax_documents", "group_name": "Company"},
        {"name": "Product Categories", "description": "Define product categories", "path": "product_categories", "group_name": "Inventory"},
        {"name": "Product Subcategories", "description": "Define product subcategories", "path": "product_subcategories", "group_name": "Inventory"},
        {"name": "Products", "description": "Manage product master", "path": "products", "group_name": "Inventory"},
        {"name": "Users", "description": "Manage users", "path": "user", "group_name": "User & Access"},
        {"name": "Company Products", "description": "Company-specific product inventory", "path": "company_products", "group_name": "Inventory"},
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
            session.flush()  # get module.id before commit
            module_ids[m["name"]] = module.id
        else:
            # Update existing module if description or group changed
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
        "Product Categories", "Product Subcategories", "Products", "Users", "Company Products"
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


# ----------------- Run Seed -----------------

def run_seed():
    with get_db_session() as session:
        role_ids = seed_roles(session)
        seed_users(session)
        module_ids = seed_modules(session)
        seed_privileges(session, role_ids, module_ids)
        seed_user_roles(session, role_ids)
        print("✅ All seed data inserted successfully.")


if __name__ == "__main__":
    try:
        run_seed()
    except Exception as e:
        import traceback
        traceback.print_exc()
