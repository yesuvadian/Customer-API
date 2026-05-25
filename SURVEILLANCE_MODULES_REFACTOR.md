# Surveillance Modules Refactoring

## Overview

Extracted surveillance workflow endpoints from `repair_workflow.py` into dedicated modules following the same pattern as existing repair workflow structure.

**Date:** 2026-05-24  
**Reason:** Separation of concerns, better organization, easier to maintain

---

## New Module Structure

### Before (Old Structure)
```
routers/
  repair_workflow.py                # 766 lines
    ├── Admin Config (lines 36-152)
    ├── Workflow Execution (lines 159-451)
    ├── Timeliness (lines 458-504)
    └── Surveillance (lines 511-766)    ← Mixed with repair endpoints
```

### After (New Structure)
```
routers/
  repair_workflow.py                # Repair-specific endpoints only
  surveillance_workflow.py          # NEW: Surveillance execution
  surveillance_dashboard.py         # NEW: Surveillance analytics
  workflow_dashboard.py             # Existing: Unified dashboard
```

---

## New Modules

### 1. `surveillance_workflow.py` (450 lines)

**Purpose:** Surveillance workflow execution and operations

**Endpoints:**

| Method | Path | Description | Permission |
|--------|------|-------------|------------|
| GET | `/surveillance-workflows` | List workflows | Org/Dept scoped |
| GET | `/surveillance-workflows/{id}` | Get workflow detail | Access check |
| GET | `/surveillance-workflows/{id}/tests` | Get testing requests | Access check |
| GET | `/surveillance-workflows/{id}/quarter/{n}/tests` | Get tests for quarter with completion status | Access check |
| GET | `/surveillance-workflows/{id}/quarter/{n}/review-data` | Get pre-populated quarterly form | Access check + Role |
| GET | `/surveillance-workflows/{id}/final-evaluation-data` | Get pre-populated final form | Access check + Role |
| GET | `/surveillance-workflows/{id}/summary` | Get comprehensive summary | Access check |
| GET | `/surveillance-workflows/{id}/current-form` | Get current stage form | Access check |
| GET | `/surveillance-workflows/{id}/timeline` | Get audit trail | Access check |
| GET | `/surveillance-workflows/{id}/progress` | Get progress % | Access check |

**Security Features:**
- ✅ Organization scoping (user.organization_id)
- ✅ Department scoping (if not org admin)
- ✅ Access verification on every endpoint (`_check_workflow_access`)
- ✅ Uses `repair_stage_roles` for stage-level permissions

**Key Functions:**
```python
def _check_workflow_access(db, workflow_id, user) -> RepairWorkflow:
    """
    Verify user has access to workflow.
    - Checks organization match
    - Checks department scope (if not org admin)
    - Raises 403/404 if access denied
    """

def _serialize_workflow(wf, current_stage) -> dict:
    """Consistent workflow serialization"""

def _serialize_test(test) -> dict:
    """Consistent test serialization"""
```

---

### 2. `surveillance_dashboard.py` (450 lines)

**Purpose:** Surveillance analytics and dashboard metrics

**Endpoints:**

| Method | Path | Description | Scoping |
|--------|------|-------------|---------|
| GET | `/surveillance-dashboard/` | Main dashboard | Org/Dept |
| GET | `/surveillance-dashboard/trends` | Quality trends over time | Org/Dept |
| GET | `/surveillance-dashboard/equipment/{id}` | Equipment surveillance history | Access check |

**Dashboard Sections:**

1. **Workflow Summary**
   - Active/completed/on_hold/cancelled counts
   - Distribution by current quarter (Q1-Q4, Final)
   - Total workflows

2. **Quality Metrics**
   - Distribution: Excellent/Good/Fair/Poor
   - Total evaluated workflows
   - Based on abnormal test rates

3. **Test Statistics**
   - Total tests conducted
   - Completed vs pending
   - Abnormal test count and rate
   - Overall completion rate

4. **Recent Activities**
   - Latest 10 workflows
   - Current stage and progress
   - Last updated timestamp

5. **Alerts**
   - Failed tests needing attention
   - Incomplete tests blocking submission
   - Overdue reviews (future enhancement)

**Example Response:**
```json
{
  "workflow_summary": {
    "by_status": {
      "active": 25,
      "completed": 15,
      "on_hold": 2,
      "cancelled": 1
    },
    "by_quarter": {
      "Q1": 8,
      "Q2": 6,
      "Q3": 5,
      "Q4": 4,
      "Final": 2
    },
    "total": 43
  },
  "quality_metrics": {
    "distribution": {
      "Excellent": 5,
      "Good": 8,
      "Fair": 2,
      "Poor": 0
    },
    "total_evaluated": 15
  },
  "test_statistics": {
    "total_tests": 400,
    "completed_tests": 350,
    "pending_tests": 50,
    "abnormal_tests": 45,
    "abnormal_rate": 12.86,
    "completion_rate": 87.5
  },
  "recent_activities": [...],
  "alerts": [...]
}
```

---

## Permission Model (Using `repair_stage_roles`)

### How It Works

Surveillance workflows use the **same permission system** as repair workflows:

1. **Table:** `repair_stage_roles`
   - Links stages to organization roles
   - Defines `can_edit` and `can_approve` permissions

2. **Workflow Creation:** Surveillance stage definitions seeded with roles
   ```json
   // SURVEILLANCE_STAGE_ROLES.json
   {
     "stage_code": "Q1_SURVEILLANCE",
     "roles": ["Reviewing Officer", "Maintenance Officer"],
     "assign_also": ["Reviewing Officer"],
     "assignment_role": "Transformer Repair Coordinator"
   }
   ```

3. **Runtime Checks:**
   - **List/View:** Organization + Department scoping
   - **Form Access:** `RepairWorkflowService.get_current_form()` checks `can_edit`
   - **Submit:** `RepairWorkflowService.submit_stage()` checks `can_edit`
   - **Approve:** `RepairWorkflowService.advance_stage()` checks `can_approve`

### Security Layers

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Authentication                                      │
│   dependencies=[Depends(get_current_user)]                  │
│   ✓ User must be logged in                                  │
└─────────────────────┬───────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Organization Scoping                                │
│   RepairWorkflow.organization_id == user.organization_id     │
│   ✓ User can only see their org's workflows                 │
└─────────────────────┬───────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Department Scoping                                  │
│   RepairWorkflow.department_id == user.department_id         │
│   ✓ Non-admin users see only their dept (if org admin: all) │
└─────────────────────┬───────────────────────────────────────┘
                      ↓
┌─────────────────────────────────────────────────────────────┐
│ Layer 4: Role-Based Permissions (via repair_stage_roles)    │
│   RepairStageRole.can_edit / can_approve                     │
│   ✓ User's role must have permission for current stage      │
└─────────────────────────────────────────────────────────────┘
```

---

## Migration from Old Endpoints

### Old URLs (Deprecated)
```
GET  /repair-workflows/surveillance
GET  /repair-workflows/surveillance/{id}
GET  /repair-workflows/surveillance/{id}/tests
GET  /repair-workflows/surveillance/{id}/summary
GET  /repair-workflows/surveillance/{id}/quarter/{n}/review-data
GET  /repair-workflows/surveillance/{id}/final-evaluation-data
```

### New URLs (Current)
```
GET  /surveillance-workflows
GET  /surveillance-workflows/{id}
GET  /surveillance-workflows/{id}/tests
GET  /surveillance-workflows/{id}/summary
GET  /surveillance-workflows/{id}/quarter/{n}/review-data
GET  /surveillance-workflows/{id}/final-evaluation-data
```

### New Endpoints (Added)
```
GET  /surveillance-workflows/{id}/quarter/{n}/tests    # NEW
GET  /surveillance-workflows/{id}/current-form         # NEW
GET  /surveillance-workflows/{id}/timeline             # NEW
GET  /surveillance-workflows/{id}/progress             # NEW

GET  /surveillance-dashboard/                          # NEW
GET  /surveillance-dashboard/trends                    # NEW
GET  /surveillance-dashboard/equipment/{id}            # NEW
```

---

## Code Comparison

### Before: Mixed in `repair_workflow.py`

```python
# Lines 511-766: Surveillance endpoints mixed with repair endpoints

@router.get("/surveillance")  # ❌ No organization scoping
def list_surveillance_workflows(...):
    query = db.query(RepairWorkflow).filter(
        RepairWorkflow.workflow_type == 'surveillance'
    )
    # ❌ Missing organization/department filtering
    # ❌ Missing access checks
    # ❌ N+1 query problem
```

### After: Dedicated `surveillance_workflow.py`

```python
# Dedicated module with proper security

@router.get("")  # ✅ Clean URL structure
def list_surveillance_workflows(
    ...,
    user: User = Depends(get_current_user),
):
    # ✅ Get user's scope
    is_org_admin, user_dept_id = get_user_dept_scope(db, user.id, None)
    
    # ✅ Eager loading (no N+1)
    query = db.query(RepairWorkflow).options(
        joinedload(RepairWorkflow.equipment),
        joinedload(RepairWorkflow.current_stage_instance)
    ).filter(
        RepairWorkflow.workflow_type == 'surveillance',
        RepairWorkflow.organization_id == user.organization_id,  # ✅ Org filter
    )
    
    # ✅ Department filter
    if not is_org_admin and user_dept_id:
        query = query.filter(RepairWorkflow.department_id == user_dept_id)
```

---

## Benefits

### 1. **Separation of Concerns**
- Repair endpoints: `repair_workflow.py`
- Surveillance endpoints: `surveillance_workflow.py`
- Surveillance analytics: `surveillance_dashboard.py`
- Each module has clear, focused responsibility

### 2. **Better Security**
- ✅ Organization scoping on all endpoints
- ✅ Department scoping for non-admin users
- ✅ Access verification before data access
- ✅ Role-based permissions via `repair_stage_roles`

### 3. **Improved Performance**
- ✅ Eager loading (no N+1 queries)
- ✅ Optimized database queries
- ✅ Indexed columns used for filtering

### 4. **Easier Maintenance**
- Smaller, focused files
- Clear naming conventions
- Consistent patterns
- Easier to test

### 5. **Better API Design**
- RESTful URL structure
- Consistent response formats
- Proper HTTP status codes
- Clear error messages

---

## Testing Checklist

### Security Tests

- [ ] User from Org A cannot access Org B's workflows
- [ ] Non-admin user cannot access other departments
- [ ] User without role permission cannot submit/approve
- [ ] Access check returns 403 for unauthorized access

### Functional Tests

- [ ] List workflows returns correct filtered results
- [ ] Get workflow detail includes surveillance summary
- [ ] Get tests returns tests for correct quarter
- [ ] Pre-populated form data is accurate
- [ ] Dashboard metrics calculate correctly

### Performance Tests

- [ ] List 100 workflows completes in <500ms
- [ ] Dashboard loads in <1s with eager loading
- [ ] No N+1 queries (check SQL logs)

---

## Deployment Steps

1. **Deploy code**
   ```bash
   git pull
   # New files:
   #   - routers/surveillance_workflow.py
   #   - routers/surveillance_dashboard.py
   # Modified files:
   #   - main.py (router registration)
   ```

2. **Restart application**
   ```bash
   systemctl restart customer-api
   ```

3. **Verify new endpoints**
   ```bash
   curl http://localhost:8000/surveillance-workflows
   curl http://localhost:8000/surveillance-dashboard/
   ```

4. **Update frontend** (if applicable)
   ```javascript
   // Old
   fetch('/repair-workflows/surveillance')
   
   // New
   fetch('/surveillance-workflows')
   ```

---

## Backward Compatibility

### Option 1: Keep Old Endpoints (Recommended for Transition)

Keep old endpoints in `repair_workflow.py` but mark as deprecated:

```python
@router.get("/surveillance")
@deprecated(
    "Use /surveillance-workflows instead. This endpoint will be removed in v2.0"
)
def list_surveillance_workflows_deprecated(...):
    # Redirect to new module
    from routers.surveillance_workflow import list_surveillance_workflows
    return list_surveillance_workflows(...)
```

### Option 2: Remove Old Endpoints (Clean Break)

Remove lines 511-766 from `repair_workflow.py`. Clients must update to new URLs.

**Recommendation:** Option 1 for 1-2 months, then Option 2.

---

## Next Steps

1. **Immediate:**
   - ✅ Create `surveillance_workflow.py`
   - ✅ Create `surveillance_dashboard.py`
   - ✅ Register routers in `main.py`
   - [ ] Test all endpoints
   - [ ] Update API documentation

2. **Short-term:**
   - [ ] Add unit tests
   - [ ] Add integration tests
   - [ ] Update frontend to use new endpoints
   - [ ] Add response caching for dashboard

3. **Long-term:**
   - [ ] Remove deprecated endpoints from `repair_workflow.py`
   - [ ] Add more dashboard metrics (vendor performance, equipment health trends)
   - [ ] Add export functionality (PDF reports, Excel exports)

---

## Summary

**Created:**
- `routers/surveillance_workflow.py` (450 lines, 10 endpoints)
- `routers/surveillance_dashboard.py` (450 lines, 3 endpoints)

**Updated:**
- `main.py` - Registered new routers

**Benefits:**
- ✅ Proper organization/department scoping
- ✅ Role-based permissions via `repair_stage_roles`
- ✅ Better performance (eager loading)
- ✅ Cleaner code organization
- ✅ Easier to maintain and test

**Security:** All endpoints now enforce proper access controls matching repair workflow pattern.
