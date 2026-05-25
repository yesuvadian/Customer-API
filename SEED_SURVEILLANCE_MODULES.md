# Seed.py Updates - Surveillance Modules & Privileges

## Summary

Updated `seed.py` to include surveillance workflow modules and configure role-based permissions following the same pattern as existing workflow modules (Breakdown, Calibration, Overhaul, Annual Audit).

**Date:** 2026-05-24  
**Files Modified:** `seed.py`

---

## Changes Made

### 1. Added Surveillance Modules (Lines ~1418-1437)

Added two new modules to `modules_data` array in `seed_modules()` function:

```python
# ✅ SURVEILLANCE WORKFLOW MODULE (SRS §7.3)
{"name": "Surveillance Workflows",
 "description": "Post-commissioning surveillance workflow — 24-month monitoring period with quarterly testing (Q1-Q4) and final evaluation. "
                "Tracks enhanced test frequency (DGA, BDV, IR, Oil Quality) and quality ratings. "
                "Stage-role RBAC driven; each stage locks to authorised roles only.",
 "path": "surveillance-workflows",
 "group_name": "Field Operations"},

# ✅ SURVEILLANCE DASHBOARD MODULE
{"name": "Surveillance Dashboard",
 "description": "Surveillance analytics dashboard — organization-wide surveillance metrics including "
                "quality ratings distribution, abnormal test rates, quarterly completion status, "
                "and equipment health trends.",
 "path": "surveillance-dashboard",
 "group_name": "Field Operations"},
```

**Effect:**
- Creates `Surveillance Workflows` module entry in `modules` table
- Creates `Surveillance Dashboard` module entry in `modules` table
- Both modules appear in "Field Operations" group
- URLs: `/surveillance-workflows` and `/surveillance-dashboard`

---

### 2. Added Global Role Privileges (Lines ~1905-1930)

Added surveillance privileges to `testing_privileges` array in `seed_privileges()` function:

```python
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
```

**Effect:**
- Global roles (Admin, Viewer, etc.) get surveillance module access
- Surveillance-specific roles get appropriate permissions
- Dashboard is view + export only (no edit/approve)

---

### 3. Added Organization Role Permissions (Lines ~5838-5841, ~5863-5877)

#### 3.1 Updated Module Dictionary

Added surveillance modules to `mods` dictionary in `seed_missing_role_permissions()`:

```python
mods = {
    # ... existing modules ...
    "Breakdown Workflows":      _get_mod("Breakdown Workflows"),
    "Calibration Workflows":    _get_mod("Calibration Workflows"),
    "Annual Audit Workflows":   _get_mod("Annual Audit Workflows"),
    "Surveillance Workflows":   _get_mod("Surveillance Workflows"),      # NEW
    "Surveillance Dashboard":   _get_mod("Surveillance Dashboard"),      # NEW
}
```

#### 3.2 Updated Role Permission Sets

Added surveillance permissions to organization roles in `ROLE_PERMS` dictionary:

**Reviewing Officer:**
```python
"Reviewing Officer": [
    # ... existing permissions ...
    ("Breakdown Workflows",      True, False, False, True, True, True),
    ("Calibration Workflows",    True, False, False, True, True, True),
    ("Annual Audit Workflows",   True, False, False, True, True, True),
    ("Surveillance Workflows",   True, True,  True,  True, True, True),  # NEW
    ("Surveillance Dashboard",   True, False, False, False, False, True),  # NEW
    # ... rest ...
],
```

**Test Engineer:**
```python
"Test Engineer": [
    ("Testing Requests", True, False, False, False, False, False),
    ("Testing",          True, True,  True,  False, False, True),
    ("Equipment",        True, False, False, False, False, False),
    ("Surveillance Workflows",   True, True,  True,  False, False, False),  # NEW
    ("Surveillance Dashboard",   True, False, False, False, False, False),  # NEW
],
```

**Permission Matrix:**

| Role | Module | View | Add | Edit | Approve | Assign | Export |
|------|--------|------|-----|------|---------|--------|--------|
| **Reviewing Officer** | Surveillance Workflows | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Reviewing Officer** | Surveillance Dashboard | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| **Test Engineer** | Surveillance Workflows | ✅ | ✅ | ✅ | ❌ | ❌ | ❌ |
| **Test Engineer** | Surveillance Dashboard | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |

**Effect:**
- Reviewing Officer can approve quarterly reviews and final evaluations
- Test Engineer can view and fill surveillance forms but not approve
- Both can view analytics dashboard
- Reviewing Officer can export reports

---

### 4. Added Module Variables (Lines ~3089-3095)

Added module variables for easy reference:

```python
breakdown_workflows_module      = [mid for mid in [modules_by_name.get("Breakdown Workflows")] if mid]
overhaul_workflows_module       = [mid for mid in [modules_by_name.get("Overhaul Workflows")] if mid]
calibration_workflows_module    = [mid for mid in [modules_by_name.get("Calibration Workflows")] if mid]
annual_audit_workflows_module   = [mid for mid in [modules_by_name.get("Annual Audit Workflows")] if mid]
surveillance_workflows_module   = [mid for mid in [modules_by_name.get("Surveillance Workflows")] if mid]  # NEW
surveillance_dashboard_module   = [mid for mid in [modules_by_name.get("Surveillance Dashboard")] if mid]  # NEW
schedule_compliance_module      = [mid for mid in [modules_by_name.get("Test Schedules")] if mid]
```

**Effect:**
- Module IDs can be referenced by variable name elsewhere in seed script
- Consistent with existing workflow module pattern

---

## Permission Architecture

### Stage-Level RBAC (via `repair_stage_roles`)

Surveillance workflows use the **same stage permission system** as repair workflows:

```sql
-- repair_stage_roles table
SELECT stage_id, org_role_id, can_edit, can_approve
FROM repair_stage_roles
WHERE stage_id IN (SELECT id FROM repair_stage_definitions WHERE workflow_code = 'SURVEILLANCE');
```

**Configuration:** Loaded from `SURVEILLANCE_STAGE_ROLES.json` by seed script

### Module-Level RBAC (via `role_module_privilege` and `org_role_permission`)

Controls who can see the module in navigation:

```sql
-- Global roles (Admin, Viewer, etc.)
SELECT role_id, module_id, can_view, can_add, can_edit, can_approve
FROM role_module_privilege
WHERE module_id IN (SELECT id FROM modules WHERE name = 'Surveillance Workflows');

-- Organization-specific roles (Reviewing Officer, Test Engineer, etc.)
SELECT org_role_id, module_id, can_view, can_add, can_edit, can_approve
FROM org_role_permission
WHERE module_id IN (SELECT id FROM modules WHERE name = 'Surveillance Workflows');
```

### Permission Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Module Access (seed.py)                            │
│   Can user see "Surveillance Workflows" in menu?            │
│   Controlled by: role_module_privilege / org_role_permission│
└─────────────────────┬───────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Organization/Department Scoping (router)           │
│   workflow.organization_id == user.organization_id          │
│   workflow.department_id == user.department_id (if not admin│
└─────────────────────┬───────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Stage-Level RBAC (service layer)                   │
│   repair_stage_roles.can_edit / can_approve                 │
│   Checked by RepairWorkflowService methods                   │
└─────────────────────────────────────────────────────────────┘
```

---

## Testing After Seed

### 1. Verify Modules Created

```sql
SELECT id, name, path, group_name, is_active, is_menu
FROM modules
WHERE name IN ('Surveillance Workflows', 'Surveillance Dashboard');

-- Expected: 2 rows
-- Surveillance Workflows | /surveillance-workflows | Field Operations | true | true
-- Surveillance Dashboard | /surveillance-dashboard | Field Operations | true | true
```

### 2. Verify Global Role Privileges

```sql
SELECT r.name AS role, m.name AS module, 
       p.can_view, p.can_add, p.can_edit, p.can_approve
FROM role_module_privilege p
JOIN roles r ON r.id = p.role_id
JOIN modules m ON m.id = p.module_id
WHERE m.name IN ('Surveillance Workflows', 'Surveillance Dashboard')
ORDER BY r.name, m.name;

-- Expected: Multiple rows for Admin, Viewer, Maintenance Officer, etc.
```

### 3. Verify Organization Role Permissions

```sql
SELECT r.name AS role, m.name AS module,
       p.can_view, p.can_add, p.can_edit, p.can_approve, p.can_assign, p.can_export
FROM org_role_permission p
JOIN org_roles r ON r.id = p.org_role_id
JOIN modules m ON m.id = p.module_id
WHERE m.name IN ('Surveillance Workflows', 'Surveillance Dashboard')
  AND r.organization_id = '<your-org-id>'
ORDER BY r.name, m.name;

-- Expected: Rows for Reviewing Officer, Test Engineer, etc.
```

### 4. Verify Stage Role Mappings

```sql
SELECT sd.name AS stage, sd.code, r.name AS role, sr.can_edit, sr.can_approve
FROM repair_stage_roles sr
JOIN repair_stage_definitions sd ON sd.id = sr.stage_id
JOIN org_roles r ON r.id = sr.org_role_id
WHERE sd.workflow_code = 'SURVEILLANCE'
ORDER BY sd.stage_number, r.name;

-- Expected: Rows for Q1-Q4 surveillance stages + final evaluation
-- Each stage should have Reviewing Officer with can_edit=true, can_approve=true
```

---

## Deployment Steps

### 1. Backup Database

```bash
pg_dump -h localhost -U postgres -d customer_api > backup_before_surveillance_seed.sql
```

### 2. Run Seed Script

```bash
cd C:\Yesu\CustomerAPI\Customer-API
python seed.py
```

**Expected Output:**
```
[OK] Modules: created Surveillance Workflows
[OK] Modules: created Surveillance Dashboard
[OK] Privileges: inserted 12 rows for Surveillance Workflows
[OK] Privileges: inserted 6 rows for Surveillance Dashboard
[OK] Missing role permissions backfilled for all orgs: 10 new row(s) inserted.
```

### 3. Verify in UI

**Admin User:**
1. Login as admin
2. Navigate to sidebar
3. Under "Field Operations" group, verify:
   - ✅ "Surveillance Workflows" appears
   - ✅ "Surveillance Dashboard" appears

**Reviewing Officer:**
1. Login as user with "Reviewing Officer" role
2. Verify surveillance modules visible
3. Create test surveillance workflow
4. Try to submit quarterly review (should have permission)

**Test Engineer:**
1. Login as user with "Test Engineer" role
2. Verify surveillance modules visible
3. Open surveillance workflow
4. Try to approve stage (should be blocked - no approve permission)

---

## Rollback Plan

If issues occur, restore from backup:

```bash
# Stop application
systemctl stop customer-api

# Restore database
psql -h localhost -U postgres -d customer_api < backup_before_surveillance_seed.sql

# Restart application
systemctl start customer-api
```

Alternatively, manually remove entries:

```sql
-- Remove surveillance modules
DELETE FROM modules WHERE name IN ('Surveillance Workflows', 'Surveillance Dashboard');

-- Cascade will remove:
-- - role_module_privilege entries
-- - org_role_permission entries
```

---

## Summary

**Files Modified:** `seed.py` (4 sections updated)

**Database Impact:**
- **Modules table:** +2 rows
- **role_module_privilege table:** ~12 rows (6 global roles × 2 modules)
- **org_role_permission table:** ~10 rows per organization (5 org roles × 2 modules)

**Roles with Access:**
- **Full Access:** Admin, Maintenance Officer, Reviewing Officer, Supervisory Officer, Senior Management Approver, TRC Member
- **Limited Access:** Test Engineer (can view/edit, cannot approve)
- **Dashboard Only:** All roles with surveillance workflow access can view dashboard

**Stage-Level Control:**
- Uses existing `repair_stage_roles` table
- Configured via `SURVEILLANCE_STAGE_ROLES.json`
- Same pattern as Breakdown/Calibration/Annual Audit workflows

**Next Steps:**
1. Run seed script: `python seed.py`
2. Verify modules appear in UI
3. Test role-based access
4. Update frontend if needed (surveillance module icons, labels)
