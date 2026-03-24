# Database Reset and Seed Instructions

## Quick Start (Windows)

### Option 1: Using Batch Script (Easiest)

```bash
cd C:\Yesu\CustomerAPI\Customer-API\migrations
reset_and_seed.bat
```

### Option 2: Using Git Bash

```bash
cd /c/Yesu/CustomerAPI/Customer-API/migrations
bash reset_and_seed.sh
```

---

## Manual Steps (If Scripts Don't Work)

### Prerequisites

- PostgreSQL installed
- Database name: `cogniwatt_db` (or your database name)
- User: `postgres` (or your username)

### Step-by-Step Commands

#### 1. Drop All Tables

```bash
psql -U postgres -d cogniwatt_db -f 000_drop_all_tables.sql
```

**What this does:**
- Drops all workflow tables
- Drops testing request tables
- Drops organization/department tables
- Drops all functions and triggers
- ⚠️ DELETES ALL DATA

#### 2. Run All Migrations

```bash
psql -U postgres -d cogniwatt_db -f run_all_migrations.sql
```

**What this does:**
- Creates organization multi-tenancy tables
- Creates department hierarchy with triggers
- Creates testing request tables
- Creates workflow engine tables
- Sets up all indexes and constraints

#### 3. Seed Complete System

```bash
psql -U postgres -d cogniwatt_db -f seed_complete_system.sql
```

**What this does:**
- Creates KPTCL organization
- Creates 6 department types (Zone, Circle, Division, Subdivision, Section, Substation)
- Creates 6-level department hierarchy
- Creates 5 roles (Org Admin, Dept Head, Tester, Engineer, Section Head)
- Creates 5 sample users
- Creates testing request workflow with 9 states
- Creates 9 workflow transitions

---

## Sample Data Created

### Organization
- **KPTCL** (Karnataka Power Transmission Corporation Limited)

### Department Hierarchy
```
KPTCL
└── Bangalore Zone
    └── Bangalore Transmission Circle
        └── RT North Division
            └── RT North SD1 Yelahanka
                └── Yelahanka Section
                    └── 220kV Yelahanka Substation
```

### Roles Created
1. **Organization Admin** - Full org access
2. **Department Head** - Department management
3. **Tester** - Testing personnel
4. **Engineer** - Request testing
5. **Section Head** - Section supervisor

### Sample Users (Password: `admin123` for all)

| Email                   | Role            | Department                |
|-------------------------|-----------------|---------------------------|
| orgadmin@kptcl.com      | Org Admin       | (Organization level)      |
| depthead@kptcl.com      | Dept Head       | RT North Division         |
| tester1@kptcl.com       | Tester          | Yelahanka Section         |
| tester2@kptcl.com       | Tester          | RT North SD1 Yelahanka    |
| engineer@kptcl.com      | Engineer        | 220kV Yelahanka Substation|

### Workflow States

1. **draft** - Initial state
2. **submitted** - User submitted
3. **assigned** - Tester assigned
4. **accepted** - Tester accepted
5. **in_progress** - Testing ongoing
6. **test_submitted** - Results submitted
7. **approved** - Final approval
8. **rejected** - Rejected
9. **cancelled** - Cancelled

---

## Testing the System

### 1. Login as Engineer

```
Email: engineer@kptcl.com
Password: admin123
```

### 2. Create Testing Request

- Fill out equipment details
- Department auto-populated: **220kV Yelahanka Substation**
- Submit request
- ✅ Request auto-assigns to available tester

### 3. Login as Tester

```
Email: tester1@kptcl.com
Password: admin123
```

- View assigned requests
- Accept assignment
- Start testing
- Submit results

### 4. Login as Department Head

```
Email: depthead@kptcl.com
Password: admin123
```

- View all requests in department tree
- Approve/reject results
- View workload statistics

---

## Troubleshooting

### Error: "psql: command not found"

**Solution:** Add PostgreSQL bin folder to PATH:
```
C:\Program Files\PostgreSQL\16\bin
```

### Error: "database does not exist"

**Solution:** Create the database first:
```bash
psql -U postgres
CREATE DATABASE cogniwatt_db;
\q
```

### Error: "permission denied"

**Solution:** Run as administrator or set PGPASSWORD:
```bash
set PGPASSWORD=your_password
```

### Error: "relation already exists"

**Solution:** Drop tables first:
```bash
psql -U postgres -d cogniwatt_db -f 000_drop_all_tables.sql
```

---

## Verify Installation

### Check Tables Created

```sql
-- Connect to database
psql -U postgres -d cogniwatt_db

-- List all tables
\dt

-- Should see:
-- organizations
-- org_departments
-- org_department_types
-- org_roles
-- user_roles
-- workflows
-- workflow_states
-- workflow_transitions
-- permission_matrix
-- workflow_audit_log
-- testing_requests
-- etc.
```

### Check Sample Data

```sql
-- Check organizations
SELECT * FROM organizations;

-- Check departments
SELECT id, name, hierarchy_level, hierarchy_path
FROM org_departments
ORDER BY hierarchy_level;

-- Check roles
SELECT * FROM org_roles;

-- Check users
SELECT email, firstname, lastname FROM users;

-- Check workflow
SELECT * FROM workflows;

-- Check workflow states
SELECT state_code, state_name FROM workflow_states ORDER BY display_order;
```

---

## Next Steps After Seeding

1. ✅ **Configure Permission Matrix**
   - Set role-based transition permissions
   - Configure department scopes

2. ✅ **Test Auto-Assignment**
   - Create request as engineer
   - Verify auto-assignment to tester

3. ✅ **Test Workflow Transitions**
   - Submit → Assign → Accept → Start → Submit Results → Approve

4. ✅ **View Audit Logs**
   - Check workflow_audit_log table
   - Verify all transitions are logged

---

## Reset Again

To reset and reseed again:

```bash
cd C:\Yesu\CustomerAPI\Customer-API\migrations
reset_and_seed.bat
```

---

**Done! Your system is now ready for testing with a complete hierarchical organization setup.**
