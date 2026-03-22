# Organization System - Quick Start Guide

## Step-by-Step Setup

### 1. Run Database Migration

```bash
psql -U postgres -d your_database_name -f migrations/001_add_organization_multi_tenancy.sql
```

### 2. Seed Role Templates

```bash
python seed_role_templates.py
```

Expected output:
```
================================================================================
  ROLE TEMPLATE SEEDER
================================================================================

🌱 Seeding role templates...
Creating new template: Organization Admin
Creating new template: Department Manager
Creating new template: Employee
Creating new template: Viewer
Creating new template: Contributor

✅ Role template seeding complete!
   - Created: 5 new templates
   - Updated: 0 existing templates
   - Total: 5 templates in database
```

### 3. Create a Super Admin User

Option A - Update an existing user:
```sql
UPDATE users
SET usertype = 'super_admin'
WHERE email = 'your-email@example.com';
```

Option B - Create a new super admin:
```sql
-- Insert into users table (password hash for "Admin123!")
INSERT INTO public.users (
    id,
    email,
    password_hash,
    firstname,
    lastname,
    phone_number,
    isactive,
    usertype,
    cts,
    mts
) VALUES (
    gen_random_uuid(),
    'superadmin@system.com',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewY5K7gqsC0zcmDe', -- Password: Admin123!
    'Super',
    'Admin',
    '+1234567890',
    true,
    'super_admin',
    NOW(),
    NOW()
);
```

### 4. Get Super Admin Token

```bash
curl -X POST http://localhost:8000/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=superadmin@system.com&password=Admin123!"
```

Save the returned `access_token` for use in subsequent requests.

### 5. Create Your First Organization

```bash
curl -X POST http://localhost:8000/organizations/with-admin \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SUPER_ADMIN_TOKEN" \
  -d '{
    "organization": {
      "name": "ACME Corporation",
      "code": "ACME",
      "display_name": "ACME Corp",
      "organization_type": "vendor",
      "industry": "Technology",
      "primary_email": "info@acme.com",
      "primary_phone": "+1234567890",
      "is_active": true
    },
    "admin_email": "admin@acme.com",
    "admin_password": "AcmeAdmin123!",
    "admin_firstname": "John",
    "admin_lastname": "Doe",
    "admin_phone": "+1234567890"
  }'
```

Response will include the organization details with:
- Organization ID
- Auto-provisioned roles (Organization Admin, Department Manager, Employee)
- Admin user created and assigned Organization Admin role

### 6. Login as Organization Admin

```bash
curl -X POST http://localhost:8000/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin@acme.com&password=AcmeAdmin123!"
```

### 7. Create a Department

```bash
curl -X POST http://localhost:8000/organizations/{ORG_ID}/departments \
  -H "Authorization: Bearer ORG_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "organization_id": "{ORG_ID}",
    "name": "Engineering",
    "code": "ENG",
    "description": "Engineering Department",
    "is_active": true
  }'
```

### 8. Create a User in the Organization

```bash
curl -X POST http://localhost:8000/organizations/{ORG_ID}/users \
  -H "Authorization: Bearer ORG_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "email": "john.engineer@acme.com",
    "password": "Engineer123!",
    "firstname": "John",
    "lastname": "Engineer",
    "phone_number": "+1987654321",
    "employee_id": "EMP001",
    "department_id": "{DEPT_ID}",
    "role_ids": ["{EMPLOYEE_ROLE_ID}"],
    "isactive": true
  }'
```

### 9. Verify Setup

List organizations:
```bash
curl -X GET http://localhost:8000/organizations \
  -H "Authorization: Bearer SUPER_ADMIN_TOKEN"
```

List departments in org:
```bash
curl -X GET http://localhost:8000/organizations/{ORG_ID}/departments \
  -H "Authorization: Bearer ORG_ADMIN_TOKEN"
```

List users in org:
```bash
curl -X GET http://localhost:8000/organizations/{ORG_ID}/users \
  -H "Authorization: Bearer ORG_ADMIN_TOKEN"
```

List roles in org:
```bash
curl -X GET http://localhost:8000/organizations/{ORG_ID}/roles \
  -H "Authorization: Bearer ORG_ADMIN_TOKEN"
```

---

## Common SQL Queries

### Check Role Templates

```sql
SELECT id, name, is_org_admin, is_dept_admin, auto_provision
FROM role_templates
ORDER BY name;
```

### Check Organizations

```sql
SELECT id, name, code, is_active, is_verified
FROM organizations
ORDER BY cts DESC;
```

### Check Users by Organization

```sql
SELECT u.id, u.email, u.firstname, u.lastname, u.employee_id,
       o.name as org_name, d.name as dept_name
FROM users u
LEFT JOIN organizations o ON u.organization_id = o.id
LEFT JOIN org_departments d ON u.department_id = d.id
WHERE u.organization_id = '{ORG_ID}'
ORDER BY u.firstname;
```

### Check User Roles

```sql
SELECT u.email, r.name as role_name, r.is_org_admin, r.is_dept_admin,
       d.name as department_name
FROM org_user_roles ur
JOIN users u ON ur.user_id = u.id
JOIN org_roles r ON ur.org_role_id = r.id
LEFT JOIN org_departments d ON ur.department_id = d.id
WHERE ur.is_active = true
  AND u.organization_id = '{ORG_ID}'
ORDER BY u.email, r.name;
```

### Check Role Permissions

```sql
SELECT r.name as role_name, m.name as module_name,
       p.can_view, p.can_add, p.can_edit, p.can_delete,
       p.can_approve, p.can_assign, p.can_export, p.can_import
FROM org_role_permissions p
JOIN org_roles r ON p.org_role_id = r.id
JOIN modules m ON p.module_id = m.id
WHERE r.organization_id = '{ORG_ID}'
ORDER BY r.name, m.name;
```

---

## Troubleshooting

### "Module not found" errors when seeding
**Problem:** No modules in the database yet.
**Solution:** The seed script will create templates without permissions. Add permissions later via API.

### "Super admin privileges required"
**Problem:** User doesn't have super_admin usertype.
**Solution:** Run: `UPDATE users SET usertype = 'super_admin' WHERE email = 'your@email.com';`

### "Organization already exists"
**Problem:** Organization code is not unique.
**Solution:** Use a different code or check existing orgs: `SELECT code FROM organizations;`

### Can't login with org admin
**Problem:** User might not have the org admin role.
**Solution:** Check:
```sql
SELECT ur.*, r.is_org_admin
FROM org_user_roles ur
JOIN org_roles r ON ur.org_role_id = r.id
WHERE ur.user_id = '{USER_ID}';
```

---

## Testing Checklist

- [ ] Database migration completed successfully
- [ ] Role templates seeded (5 templates)
- [ ] Super admin user created
- [ ] Can get super admin token
- [ ] Organization created with admin
- [ ] Can login as org admin
- [ ] Department created
- [ ] Regular user created in org
- [ ] User assigned to department
- [ ] User has employee role
- [ ] Can list all entities via API

---

## Next Steps

1. **Configure Permissions**: Use the `/roles/{role_id}/permissions` endpoint to set module permissions
2. **Create More Departments**: Build your organizational hierarchy
3. **Invite Users**: Create invitation flow for new users
4. **Build UI**: Implement frontend for org management
5. **Test Workflows**: Test full user lifecycle within organization

---

## Quick Reference - Default Roles

After organization creation, these roles are automatically created:

| Role Name | is_org_admin | is_dept_admin | Permissions |
|-----------|--------------|---------------|-------------|
| Organization Admin | ✅ Yes | No | All permissions |
| Department Manager | No | ✅ Yes | View, Add, Edit, Approve, Export |
| Employee | No | No | View only |

---

**Last Updated:** 2026-03-21
