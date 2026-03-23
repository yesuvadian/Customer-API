# Organization Multi-Tenancy System - Setup Guide

## Overview

This system implements a complete multi-tenant organization management solution with:
- **Organizations** - Isolated tenant entities
- **Departments** - Hierarchical departmental structure within organizations
- **Users** - Users scoped to organizations and departments
- **Roles** - Organization-specific roles with fine-grained permissions
- **Auto-provisioning** - Automatic creation of default roles for new organizations

---

## Installation Steps

### 1. Run Database Migration

Execute the SQL migration script to create all necessary tables:

```bash
# Connect to your PostgreSQL database
psql -U your_username -d your_database -f migrations/001_add_organization_multi_tenancy.sql
```

Or if using a database client, run the contents of:
```
migrations/001_add_organization_multi_tenancy.sql
```

**Tables Created:**
- `organizations` - Organization entities
- `org_departments` - Departments within organizations
- `org_roles` - Organization-scoped roles
- `org_user_roles` - User-role assignments
- `org_role_permissions` - Role permissions per module
- `role_templates` - System-level role templates
- `org_invitations` - User invitation system

**Users Table Updated:**
- Added `organization_id` column
- Added `employee_id` column
- Added `department_id` column

---

### 2. Seed Role Templates

Run the seed script to create default role templates:

```bash
cd C:\Yesu\CustomerAPI\Customer-API
python seed_role_templates.py
```

**Default Templates Created:**
1. **Organization Admin** (auto-provision) - Full access to everything
2. **Department Manager** (auto-provision) - Department-level management
3. **Employee** (auto-provision) - Standard read access
4. **Viewer** - Read-only access
5. **Contributor** - Add and edit capabilities

---

### 3. Restart API Server

After running migrations and seeds, restart your FastAPI server:

```bash
# If using uvicorn directly
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Or your preferred method
python main.py
```

---

## API Endpoints

### Organizations

```
POST   /organizations                    - Create organization (super admin only)
POST   /organizations/with-admin         - Create org with admin user (super admin only)
GET    /organizations                    - List all organizations (super admin only)
GET    /organizations/{org_id}           - Get organization details
PUT    /organizations/{org_id}           - Update organization (org admin)
DELETE /organizations/{org_id}           - Delete organization (super admin)
POST   /organizations/{org_id}/verify    - Verify organization (super admin)
GET    /organizations/code/{code}        - Get organization by code (super admin)
```

### Departments

```
POST   /organizations/{org_id}/departments                     - Create department
GET    /organizations/{org_id}/departments                     - List departments
GET    /organizations/{org_id}/departments/{dept_id}           - Get department
PUT    /organizations/{org_id}/departments/{dept_id}           - Update department
DELETE /organizations/{org_id}/departments/{dept_id}           - Delete department
POST   /organizations/{org_id}/departments/{dept_id}/users     - Assign users
GET    /organizations/{org_id}/departments/{dept_id}/users     - Get dept users
```

### Users

```
POST   /organizations/{org_id}/users                           - Create user
GET    /organizations/{org_id}/users                           - List users
GET    /organizations/{org_id}/users/{user_id}                 - Get user
PUT    /organizations/{org_id}/users/{user_id}                 - Update user
DELETE /organizations/{org_id}/users/{user_id}                 - Delete user
POST   /organizations/{org_id}/users/{user_id}/roles           - Assign role
DELETE /organizations/{org_id}/users/{user_id}/roles/{role_id} - Remove role
GET    /organizations/{org_id}/users/{user_id}/roles           - Get user roles
GET    /organizations/{org_id}/users/me                        - Get current user
```

### Roles

```
POST   /organizations/{org_id}/roles                           - Create role
GET    /organizations/{org_id}/roles                           - List roles
GET    /organizations/{org_id}/roles/{role_id}                 - Get role
PUT    /organizations/{org_id}/roles/{role_id}                 - Update role
DELETE /organizations/{org_id}/roles/{role_id}                 - Delete role
POST   /organizations/{org_id}/roles/{role_id}/permissions     - Set permissions
GET    /organizations/{org_id}/roles/{role_id}/permissions     - Get permissions
PUT    /organizations/{org_id}/roles/{role_id}/permissions/{module_id} - Update permission
GET    /organizations/{org_id}/roles/name/{role_name}          - Get role by name
GET    /organizations/{org_id}/roles/check-permission/{user_id}/{module_id}/{type} - Check permission
GET    /organizations/{org_id}/roles/user-permissions/{user_id} - Get all user permissions
```

---

## Usage Examples

### 1. Create Organization with Admin User

```python
POST /organizations/with-admin

{
  "organization": {
    "name": "ACME Corporation",
    "code": "ACME_CORP",
    "display_name": "ACME Corp.",
    "organization_type": "vendor",
    "industry": "Technology",
    "website": "https://acmecorp.com",
    "primary_email": "info@acmecorp.com",
    "primary_phone": "+1234567890",
    "is_active": true,
    "settings": {}
  },
  "admin_email": "admin@acmecorp.com",
  "admin_password": "SecurePass123!",
  "admin_firstname": "John",
  "admin_lastname": "Doe",
  "admin_phone": "+1234567890"
}
```

**What happens:**
1. Organization is created
2. Default roles are provisioned (Org Admin, Dept Manager, Employee)
3. Admin user is created
4. Org Admin role is assigned to the admin user

---

### 2. Create Department

```python
POST /organizations/{org_id}/departments

{
  "organization_id": "{org_id}",
  "name": "Engineering",
  "code": "ENG",
  "description": "Engineering Department",
  "parent_department_id": null,
  "manager_id": "{user_id}",
  "is_active": true
}
```

---

### 3. Create User in Organization

```python
POST /organizations/{org_id}/users

{
  "email": "employee@acmecorp.com",
  "password": "Pass123!",
  "firstname": "Jane",
  "lastname": "Smith",
  "phone_number": "+1987654321",
  "employee_id": "EMP001",
  "department_id": "{dept_id}",
  "role_ids": ["{employee_role_id}"],
  "isactive": true
}
```

---

### 4. Set Role Permissions

```python
POST /organizations/{org_id}/roles/{role_id}/permissions

{
  "permissions": [
    {
      "module_id": 1,
      "can_view": true,
      "can_add": true,
      "can_edit": true,
      "can_delete": false,
      "can_approve": false,
      "can_assign": false,
      "can_export": true,
      "can_import": false
    },
    {
      "module_id": 2,
      "can_view": true,
      "can_add": false,
      "can_edit": false,
      "can_delete": false,
      "can_approve": false,
      "can_assign": false,
      "can_export": false,
      "can_import": false
    }
  ]
}
```

---

## Authorization Middleware

The system provides several authorization dependencies:

### `require_org_member`
Verifies user belongs to the organization in the URL path.

```python
@router.get("/resources")
def get_resources(
    org_id: UUID,
    current_user: User = Depends(require_org_member)
):
    ...
```

### `require_org_admin`
Verifies user has organization admin role.

```python
@router.post("/users")
def create_user(
    org_id: UUID,
    current_user: User = Depends(require_org_admin)
):
    ...
```

### `require_dept_admin`
Verifies user has department admin role for the specified department.

```python
@router.put("/departments/{dept_id}")
def update_department(
    org_id: UUID,
    dept_id: UUID,
    current_user: User = Depends(require_dept_admin)
):
    ...
```

### `require_org_admin_or_dept_admin`
Verifies user has either org admin or dept admin role.

### `require_super_admin`
Verifies user is a system-level super admin.

```python
@router.post("/organizations")
def create_organization(
    current_user: User = Depends(require_super_admin)
):
    ...
```

### `require_module_permission(module_id, permission_type)`
Checks specific module-level permissions.

```python
@router.get("/products", dependencies=[
    Depends(require_module_permission(1, "can_view"))
])
def list_products():
    ...
```

---

## Data Model Overview

### Organization
- Multi-tenant root entity
- Has plan/subscription
- Contains departments, roles, users
- Can be verified by super admin

### Department
- Hierarchical structure (parent-child)
- Has a manager (user)
- Users belong to departments
- Roles can be scoped to departments

### User
- Belongs to one organization
- Can belong to one department
- Has multiple roles (via OrgUserRole)
- Has employee_id within organization

### Role
- Scoped to organization
- Can be org admin, dept admin, or regular role
- Has permissions per module
- Can be "default" (auto-provisioned) or "custom"

### Permission
- Granular per module
- 8 permission types: view, add, edit, delete, approve, assign, export, import
- Aggregated across all user roles (OR logic)

---

## Migration Rollback

If you need to rollback the migration:

```bash
psql -U your_username -d your_database -f migrations/001_rollback_organization_multi_tenancy.sql
```

**Warning:** This will delete all organization data!

---

## Testing

### 1. Test Organization Creation

```bash
curl -X POST http://localhost:8000/organizations/with-admin \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SUPER_ADMIN_TOKEN" \
  -d '{
    "organization": {
      "name": "Test Org",
      "code": "TEST_ORG",
      "is_active": true
    },
    "admin_email": "admin@testorg.com",
    "admin_password": "TestPass123!",
    "admin_firstname": "Admin",
    "admin_lastname": "User",
    "admin_phone": "+1234567890"
  }'
```

### 2. Test Login as Org Admin

```bash
curl -X POST http://localhost:8000/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@testorg.com&password=TestPass123!"
```

### 3. Test Creating Department

```bash
curl -X POST http://localhost:8000/organizations/{org_id}/departments \
  -H "Authorization: Bearer YOUR_ORG_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "organization_id": "{org_id}",
    "name": "Sales",
    "code": "SALES",
    "description": "Sales Department",
    "is_active": true
  }'
```

---

## Common Issues & Solutions

### Issue: "Super admin privileges required"
**Solution:** Ensure the user has `usertype = 'super_admin'` or `'system_admin'` in the users table.

### Issue: "Organization not found"
**Solution:** Check that the `org_id` in the URL matches the user's `organization_id`.

### Issue: "Department not found in this organization"
**Solution:** Verify the department belongs to the same organization as specified in the URL.

### Issue: "Role not found in this organization"
**Solution:** Ensure the role exists and belongs to the correct organization.

### Issue: Migration fails
**Solution:** Check that:
1. All dependent tables exist (users, plans, modules)
2. No circular FK constraints
3. Database user has sufficient privileges

---

## Next Steps

1. **Update Frontend**: Add UI for organization management
2. **Create Super Admin**: Update a user to have `usertype = 'super_admin'`
3. **Test Workflows**: Create org → departments → users → assign roles
4. **Configure Permissions**: Set up role permissions per module
5. **Document Custom Roles**: Define org-specific roles as needed

---

## File Structure

```
Customer-API/
├── models.py                           # Updated with org models
├── schemas.py                          # Org schemas added
├── main.py                             # Routers registered
├── seed_role_templates.py              # Seed script
├── migrations/
│   ├── 001_add_organization_multi_tenancy.sql
│   └── 001_rollback_organization_multi_tenancy.sql
├── middleware/
│   └── org_auth.py                     # Authorization middleware
├── services/
│   ├── organization_service.py         # Org CRUD + provisioning
│   ├── org_department_service.py       # Department CRUD
│   ├── org_user_service.py             # User management
│   └── org_role_service.py             # Role & permission management
└── routers/
    ├── organizations.py                # Org endpoints
    ├── org_departments.py              # Department endpoints
    ├── org_users.py                    # User endpoints
    └── org_roles.py                    # Role endpoints
```

---

## Support

For issues or questions about the organization system:
1. Check this documentation
2. Review the API endpoint documentation
3. Check the migration script for database schema
4. Review the service layer for business logic

---

## KPTCL Department Hierarchy Seeding

### Overview

A specialized seeding function is available to populate department hierarchy from the KPTCL Substation Mapping Excel file.

**Hierarchy Structure (6 levels):**
1. Zone (e.g., Bengaluru Zone)
2. Circle (e.g., Bengaluru Transmission Circle)
3. Division (e.g., RT North Division)
4. Sub Division (e.g., RT North SD1 Yelahanka)
5. Section (e.g., Yelahanka Section)
6. Substation (e.g., 220kV Yelahanka)

### Prerequisites

1. Install required Python packages:
```bash
pip install pandas openpyxl
```

2. Place the Excel file in the project root:
```
C:\Yesu\CustomerAPI\Customer-API\KPTCL_Substation_Mapping.xlsx
```

### Usage

#### Option 1: Seed KPTCL Departments Only

Use this to populate departments for an existing organization:

```bash
cd C:\Yesu\CustomerAPI\Customer-API
python seed.py --kptcl <organization_id>
```

**Example:**
```bash
python seed.py --kptcl 550e8400-e29b-41d4-a716-446655440000
```

**What this does:**
- Deletes all existing departments in the organization
- Reads the KPTCL Excel file (888 rows)
- Creates ~500+ departments in 6-level hierarchy
- Maintains parent-child relationships

#### Option 2: Full Seed + KPTCL Departments

Run the complete database seed AND populate KPTCL departments:

```bash
python seed.py --with-kptcl <organization_id>
```

### Excel File Structure

The script expects these columns:
- `Zone` - Top level (e.g., Bengaluru Zone)
- `Circle` - Second level
- `Division` - Third level
- `Sub Division` - Fourth level
- `Section` - Fifth level
- `Substation` - Bottom level (e.g., 220kV Yelahanka)

### Example Output

```
================================================================================
  KPTCL DEPARTMENT SEEDING
================================================================================

--- KPTCL Department Hierarchy Seeding ---
[INFO] Deleting existing departments for organization: KPTCL
[OK] Deleted 0 existing departments
[INFO] Reading Excel file: C:\Users\yesuv\Downloads\KPTCL_Substation_Mapping.xlsx
[OK] Loaded 888 rows with columns: ['Zone', 'Circle', 'Division', 'Sub Division', 'Section', 'Substation']

============================================================
Creating Zone departments...
============================================================
Found 11 unique Zone departments
[OK] Created 11 Zone departments

============================================================
Creating Circle departments...
============================================================
Found 27 unique Circle departments
[OK] Created 27 Circle departments

...

============================================================
[OK] COMPLETED: Created 523 total departments
============================================================

================================================================================
  [OK] KPTCL DEPARTMENTS SEEDED SUCCESSFULLY
================================================================================
```

### Important Notes

⚠️ **Warning:**
- This will DELETE all existing departments in the organization before creating new ones
- Make sure you have the correct organization ID
- Backup your data if needed

### Customization

The Excel file is automatically detected in the project root directory. To use a different path, pass it explicitly:

```python
seed_kptcl_departments(session, org_id, excel_path="/path/to/file.xlsx")
```

### Troubleshooting

**Issue: "Organization not found"**
- Verify the organization ID exists in the database
- Check UUID format is correct

**Issue: "Failed to read Excel file"**
- Ensure openpyxl is installed: `pip install openpyxl`
- Verify the Excel file path exists
- Check file permissions

**Issue: "Parent not found for X"**
- This indicates data integrity issues in the Excel file
- Check that all parent levels exist for each row

---

**Implementation Date:** 2026-03-21
**Version:** 1.0.0
**Status:** ✅ Complete & Ready for Use
