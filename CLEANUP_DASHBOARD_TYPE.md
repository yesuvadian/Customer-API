# Removed `default_dashboard_type` Field - Cleanup Summary

## Reason for Removal
With `default_module_path` pointing directly to role-specific dashboards, the intermediary `default_dashboard_type` field (admin/supervisor/field/generic) was redundant and unnecessary.

## Changes Made

### Backend

#### 1. Models (`models.py`)
**Removed from OrgRole:**
```python
- default_dashboard_type = Column(String(50), default="generic")
```

**Removed from RoleTemplate:**
```python
- default_dashboard_type = Column(String(50), default="generic")
```

#### 2. Schemas (`schemas.py`)
**Removed from UserResponse:**
```python
- dashboard_type: Optional[str] = None
```

#### 3. Login API (`routers/auth.py`)
**Before:**
```python
SELECT oroles.default_dashboard_type, m.path
...
result["user"]["dashboard_type"] = dashboard_type
result["user"]["default_module_path"] = default_module_path
```

**After:**
```python
SELECT m.path
...
result["user"]["default_module_path"] = default_module_path
```

#### 4. Seed (`seed.py`)
- Removed all `"default_dashboard_type": "..."` lines from role templates (16 occurrences)
- Removed from seed_role_templates() function logic
- Database will no longer have these columns after reseed

### Frontend

#### 1. Models (`lib/models/models.dart`)
**Removed:**
```dart
- String? dashboardType;
- this.dashboardType,
- dashboardType: json['dashboard_type'],
- 'dashboard_type': dashboardType,
```

#### 2. Dashboard (`lib/pages/zoho/dashboard.dart`)
**Removed:**
```dart
- String _dashboardType = 'generic';
- _dashboardType = user?.dashboardType ?? 'generic';
- bool get _isAdmin => _dashboardType == 'admin';
- bool get _isOriginator => _dashboardType == 'field' && ...
```

**Replaced with role-based checks:**
```dart
bool get _isAdmin => _roles.contains('Admin');
bool get _isOriginator => _roles.contains('Originator');
bool get _isTester => _roles.any((r) => r.contains('Tester'));
bool get _isApprover => _roles.any((r) => ['AEE', 'EE', 'SEE', 'CEE', ...].any(...));
```

## New Simplified Flow

### Before (Two-Level Lookup)
1. Role → `default_dashboard_type` (admin/supervisor/field/generic)
2. `default_dashboard_type` → Generic dashboard component
3. Still hard-coded logic to switch between generic dashboards

### After (Direct Lookup)
1. Role → `default_module_path` (ee_tlss_dashboard/aee_dashboard/etc.)
2. `default_module_path` → Specific dashboard component
3. No intermediary, direct routing to custom dashboards

## Benefits

✅ **Simpler**: One field instead of two
✅ **Cleaner**: No intermediate abstraction layer
✅ **Direct**: Role directly maps to dashboard component
✅ **Maintainable**: Less code, less confusion
✅ **Flexible**: Can create unlimited dashboard types without predefined categories

## API Response Comparison

### Before
```json
{
  "user": {
    "dashboard_type": "supervisor",
    "default_module_path": "ee_tlss_dashboard"
  }
}
```

### After
```json
{
  "user": {
    "default_module_path": "ee_tlss_dashboard"
  }
}
```

## Routing Comparison

### Before
```dart
// Check dashboard_type first
if (_dashboardType == 'admin') {
  return _buildAdminDashboard();
} else if (_dashboardType == 'supervisor') {
  return _buildApproverDashboard();
}
// Then check if custom module exists
```

### After
```dart
// Check custom dashboard first
if (_defaultModulePath != null) {
  switch (_defaultModulePath) {
    case 'ee_tlss_dashboard':
      return EETLSSDashboard();
    case 'aee_dashboard':
      return AEEDashboard();
    // ...
  }
}
// Fallback to role-based generic dashboards
```

## Files Modified

### Backend
- `models.py` - Removed column from 2 tables
- `schemas.py` - Removed field from UserResponse
- `routers/auth.py` - Simplified query and response
- `seed.py` - Removed from all 16 role templates

### Frontend
- `lib/models/models.dart` - Removed dashboardType field
- `lib/pages/zoho/dashboard.dart` - Removed _dashboardType variable and logic

## Migration

Database needs to be dropped and recreated to remove the columns:
```bash
python drop_and_reseed.py
```

This will:
1. Drop schema public CASCADE
2. Recreate all tables (without default_dashboard_type columns)
3. Reseed data with only default_module_id assignments

## Result

- Cleaner codebase
- Fewer fields to maintain
- Direct role-to-dashboard mapping
- No confusion about two similar fields
- Same functionality with simpler implementation

---

**Date**: 2026-04-19
**Status**: ✅ Cleanup Complete - Database Reseeding
