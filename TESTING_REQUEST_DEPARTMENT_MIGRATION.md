# Testing Request Department Migration Guide

## Overview

This migration replaces the legacy string-based location fields in Testing Requests with a proper department hierarchy system using foreign keys to the `org_departments` table.

### What Changed?

**Before (Legacy):**
- `zone` (String)
- `ce_circle` (String)
- `se_division` (String)
- `ee_subdivision` (String)
- `aee_section` (String)
- `ae_je` (String)

**After (New):**
- `organization_id` (UUID FK → organizations)
- `department_id` (UUID FK → org_departments)

**Note:** Legacy fields are kept for backward compatibility but should not be used in new code.

---

## Database Migration

### 1. Run the Migration

```bash
psql -U your_username -d your_database -f migrations/002_testing_request_department_hierarchy.sql
```

Or manually execute the SQL in your database client.

### 2. What Gets Created

- `testing_requests.organization_id` - Links request to an organization
- `testing_requests.department_id` - Links request to a specific department
- `tester_locations.department_id` - Links tester to a department
- Foreign key constraints and indexes

### 3. Rollback (if needed)

```bash
psql -U your_username -d your_database -f migrations/002_rollback_testing_request_department_hierarchy.sql
```

---

## API Changes

### New Endpoint: Department Hierarchy

**Get Organizations:**
```http
GET /testing_requests/department_hierarchy
```

Response:
```json
[
  {
    "id": "e4972e8a-83b5-47a6-86dd-ab28e2f9fe6a",
    "name": "KPTCL",
    "code": "KPTCL",
    "type": "organization"
  }
]
```

**Get Root Departments for Organization:**
```http
GET /testing_requests/department_hierarchy?org_id=<uuid>
```

Response:
```json
[
  {
    "id": "dept-uuid-1",
    "name": "Zone",
    "code": "ZONE",
    "parent_department_id": null,
    "has_children": true,
    "type": "department"
  }
]
```

**Get Children Departments:**
```http
GET /testing_requests/department_hierarchy?org_id=<uuid>&parent_id=<dept-uuid>
```

Response:
```json
[
  {
    "id": "child-dept-uuid-1",
    "name": "Bengaluru Zone",
    "code": "BZ",
    "parent_department_id": "dept-uuid-1",
    "has_children": true,
    "type": "department"
  },
  {
    "id": "child-dept-uuid-2",
    "name": "Mysuru Zone",
    "code": "MZ",
    "parent_department_id": "dept-uuid-1",
    "has_children": true,
    "type": "department"
  }
]
```

### Updated Schemas

**TestingRequestCreate:**
```json
{
  "title": "Test Request",
  "description": "...",
  "organization_id": "e4972e8a-83b5-47a6-86dd-ab28e2f9fe6a",
  "department_id": "dept-uuid-here",
  // ... other fields
}
```

**TestingRequestResponse:**
```json
{
  "id": "...",
  "organization_id": "...",
  "department_id": "...",
  "department_name": "220kV Yelahanka",  // ← Computed field
  // ... other fields
}
```

---

## Frontend Implementation (Flutter)

### 1. Cascading Dropdowns

Replace the old location dropdowns with a cascading department hierarchy:

```dart
// Step 1: Select Organization
DropdownButton<String>(
  items: organizations.map((org) => DropdownMenuItem(
    value: org['id'],
    child: Text(org['name']),
  )).toList(),
  onChanged: (orgId) {
    setState(() {
      selectedOrgId = orgId;
      selectedDepartmentId = null;
      loadRootDepartments(orgId);
    });
  },
)

// Step 2: Navigate Department Hierarchy
// Use the TreeView or cascading dropdowns to navigate:
// Zone → Circle → Division → Sub Division → Section → Substation
```

### 2. API Calls

```dart
// Load organizations
Future<List<Map>> loadOrganizations() async {
  final response = await http.get(
    Uri.parse('$baseUrl/testing_requests/department_hierarchy'),
  );
  return jsonDecode(response.body);
}

// Load root departments
Future<List<Map>> loadRootDepartments(String orgId) async {
  final response = await http.get(
    Uri.parse('$baseUrl/testing_requests/department_hierarchy?org_id=$orgId'),
  );
  return jsonDecode(response.body);
}

// Load child departments
Future<List<Map>> loadChildDepartments(String orgId, String parentId) async {
  final response = await http.get(
    Uri.parse('$baseUrl/testing_requests/department_hierarchy?org_id=$orgId&parent_id=$parentId'),
  );
  return jsonDecode(response.body);
}
```

### 3. Creating Testing Request

```dart
// When user selects the final department (e.g., "220kV Yelahanka")
Future<void> createTestingRequest() async {
  final requestData = {
    'title': titleController.text,
    'description': descriptionController.text,
    'organization_id': selectedOrgId,
    'department_id': selectedDepartmentId, // Final selected department
    // ... other fields
  };

  await http.post(
    Uri.parse('$baseUrl/testing_requests/'),
    headers: {'Content-Type': 'application/json'},
    body: jsonEncode(requestData),
  );
}
```

---

## Migration Strategy

### Phase 1: Dual Support (Current)

- Both legacy and new fields are available
- New code should use `organization_id` + `department_id`
- Old code can continue using string fields temporarily

### Phase 2: Deprecation (Future)

- Mark legacy fields as deprecated
- Update all existing code to use new fields
- Display migration warnings

### Phase 3: Removal (Final)

- Drop legacy columns from database
- Remove from schemas and models
- Update all documentation

---

## Benefits of New System

✅ **Data Integrity:**
- Foreign key constraints ensure valid departments
- Cannot reference non-existent locations

✅ **Flexibility:**
- Easy to add/rename/reorganize departments
- Supports any hierarchy depth

✅ **Multi-Tenancy:**
- Each organization has its own department structure
- Clean separation of data

✅ **Reporting:**
- Easy to aggregate by department hierarchy
- Join with department metadata (managers, codes, etc.)

✅ **Maintenance:**
- No duplicate location strings
- Single source of truth for organizational structure

---

## Example: Complete Flow

### 1. User Creates Testing Request

**UI Flow:**
1. Select Organization: "KPTCL"
2. Navigate hierarchy:
   - Zone
   - → Bengaluru Zone
   - → Bengaluru Transmission Circle
   - → RT North Division
   - → RT North SD1 Yelahanka
   - → Yelahanka Section
   - → **220kV Yelahanka** ← Final selection

**API Call:**
```json
POST /testing_requests/
{
  "title": "Transformer Testing Request",
  "organization_id": "e4972e8a-83b5-47a6-86dd-ab28e2f9fe6a",
  "department_id": "uuid-of-220kV-Yelahanka",
  "equipment_type_id": 1,
  "test_type_id": 5,
  ...
}
```

### 2. System Assigns Tester

- Query testers with `department_id` matching "220kV Yelahanka" or parent departments
- Assign based on location and availability

### 3. Display Request

**Response includes:**
```json
{
  "id": "...",
  "title": "Transformer Testing Request",
  "organization_id": "e4972e8a-83b5-47a6-86dd-ab28e2f9fe6a",
  "department_id": "uuid-of-220kV-Yelahanka",
  "department_name": "220kV Yelahanka",  // Computed
  ...
}
```

---

## Testing Checklist

- [ ] Run database migration
- [ ] Verify foreign key constraints
- [ ] Test department hierarchy endpoint
- [ ] Update frontend to use new fields
- [ ] Test creating testing request with department
- [ ] Test tester assignment by department
- [ ] Verify backward compatibility (legacy fields still work)
- [ ] Update UI/UX to show department hierarchy
- [ ] Test department filtering in list views
- [ ] Verify reporting with new structure

---

## Support

For questions or issues with the migration:
1. Check this documentation
2. Review migration SQL scripts
3. Test with `/testing_requests/department_hierarchy` endpoint
4. Verify department data is properly seeded

---

**Migration Date:** 2026-03-22
**Version:** 1.0.0
**Status:** ✅ Ready for Implementation
