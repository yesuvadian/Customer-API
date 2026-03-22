# Testing Request Department Hierarchy - Changes Summary

## ✅ Completed Changes

### 1. Database Migration

**File:** `migrations/002_testing_request_department_hierarchy.sql`

**Changes Made:**
- ✅ Added `organization_id` (UUID) to `testing_requests`
- ✅ Added `department_id` (UUID) to `testing_requests`
- ✅ Added `department_id` (UUID) to `tester_locations`
- ✅ Created foreign key constraints
- ✅ Created indexes for performance
- ✅ Kept legacy fields (zone, ce_circle, etc.) for backward compatibility

**Migration Status:** ✅ **APPLIED SUCCESSFULLY**

**Verification:**
```
[OK] New columns added to testing_requests:
  • department_id (uuid) - Nullable: YES
  • organization_id (uuid) - Nullable: YES

[OK] Indexes created:
  • idx_testing_requests_department_id
```

---

### 2. Models Updated

**File:** `models.py`

**TestingRequest Model:**
```python
# New fields
organization_id = Column(UUID(as_uuid=True), ForeignKey("public.organizations.id"), nullable=True)
department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id"), nullable=True)

# New relationships
organization = relationship("Organization", foreign_keys=[organization_id])
department = relationship("OrgDepartment", foreign_keys=[department_id])
```

**TesterLocation Model:**
```python
# New field
department_id = Column(UUID(as_uuid=True), ForeignKey("public.org_departments.id"), nullable=True)

# New relationship
department = relationship("OrgDepartment", foreign_keys=[department_id])
```

---

### 3. Schemas Updated

**File:** `schemas.py`

**TestingRequestCreate:**
- ✅ Added `organization_id: Optional[UUID]`
- ✅ Added `department_id: Optional[UUID]`

**TestingRequestUpdate:**
- ✅ Added `organization_id: Optional[UUID]`
- ✅ Added `department_id: Optional[UUID]`

**TestingRequestResponse:**
- ✅ Added `organization_id: Optional[UUID]`
- ✅ Added `department_id: Optional[UUID]`
- ✅ Added `department_name: Optional[str]` (computed field)

---

### 4. API Endpoints

**File:** `routers/testing_requests.py`

#### New Endpoint: Department Hierarchy

```python
GET /testing_requests/department_hierarchy
```

**Usage:**

1. **Get all organizations:**
   ```
   GET /testing_requests/department_hierarchy
   ```
   Returns list of organizations

2. **Get root departments:**
   ```
   GET /testing_requests/department_hierarchy?org_id=<uuid>
   ```
   Returns top-level departments for organization

3. **Get child departments:**
   ```
   GET /testing_requests/department_hierarchy?org_id=<uuid>&parent_id=<uuid>
   ```
   Returns children of specified department

#### Updated Enrichment Function

```python
def _enrich(req):
    # ... existing code ...
    req.department_name = req.department.name if req.department else None
    # ... rest of code ...
```

---

## 📁 New Files Created

1. **migrations/002_testing_request_department_hierarchy.sql**
   - Forward migration script

2. **migrations/002_rollback_testing_request_department_hierarchy.sql**
   - Rollback script (if needed)

3. **run_migration_002.py**
   - Python script to run migration
   - Includes verification

4. **TESTING_REQUEST_DEPARTMENT_MIGRATION.md**
   - Complete migration guide
   - Frontend implementation examples
   - API usage examples

5. **TESTING_REQUEST_CHANGES_SUMMARY.md**
   - This file - quick reference

---

## 🔄 Frontend Changes Needed

### Replace Location Dropdowns

**Before (Old UI):**
```
Zone: [Dropdown with string values]
CE Circle: [Dropdown with string values]
SE Division: [Dropdown with string values]
EE Subdivision: [Dropdown with string values]
AEE Section: [Dropdown with string values]
AE/JE: [Dropdown with string values]
```

**After (New UI):**
```
Organization: [Dropdown of organizations]
Department: [Hierarchical tree or cascading dropdowns]
  └─ Zone
      └─ Circle
          └─ Division
              └─ Sub Division
                  └─ Section
                      └─ Substation
```

### API Integration

#### 1. Load Organizations
```dart
GET /testing_requests/department_hierarchy
```

#### 2. Load Department Hierarchy
```dart
// Root level
GET /testing_requests/department_hierarchy?org_id=<uuid>

// Children
GET /testing_requests/department_hierarchy?org_id=<uuid>&parent_id=<uuid>
```

#### 3. Create Testing Request
```dart
POST /testing_requests/
{
  "title": "...",
  "organization_id": "<selected org uuid>",
  "department_id": "<selected dept uuid>",
  // ... other fields
}
```

---

## 🧪 Testing the Changes

### 1. Test Department Hierarchy API

```bash
# Get organizations
curl http://localhost:8000/testing_requests/department_hierarchy

# Get root departments for KPTCL org
curl "http://localhost:8000/testing_requests/department_hierarchy?org_id=e4972e8a-83b5-47a6-86dd-ab28e2f9fe6a"

# Get children (replace with actual parent UUID)
curl "http://localhost:8000/testing_requests/department_hierarchy?org_id=e4972e8a-83b5-47a6-86dd-ab28e2f9fe6a&parent_id=<parent-uuid>"
```

### 2. Create Testing Request with Department

```bash
curl -X POST http://localhost:8000/testing_requests/ \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <your-token>" \
  -d '{
    "title": "Test Request",
    "organization_id": "e4972e8a-83b5-47a6-86dd-ab28e2f9fe6a",
    "department_id": "<selected-department-uuid>",
    "equipment_type_id": 1,
    "test_type_id": 1
  }'
```

### 3. Verify Response Includes Department Name

The response should include:
```json
{
  "id": "...",
  "organization_id": "e4972e8a-83b5-47a6-86dd-ab28e2f9fe6a",
  "department_id": "...",
  "department_name": "220kV Yelahanka",
  ...
}
```

---

## 📊 Database Verification

Run these queries to verify the migration:

```sql
-- Check new columns exist
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'testing_requests'
AND column_name IN ('organization_id', 'department_id');

-- Check foreign keys
SELECT constraint_name, table_name, constraint_type
FROM information_schema.table_constraints
WHERE table_schema = 'public'
AND table_name = 'testing_requests'
AND constraint_type = 'FOREIGN KEY';

-- Check indexes
SELECT indexname, indexdef
FROM pg_indexes
WHERE tablename = 'testing_requests'
AND indexname LIKE '%department%';
```

---

## ⚠️ Important Notes

1. **Backward Compatibility:**
   - Legacy fields (zone, ce_circle, etc.) are **NOT** dropped
   - Old API calls will continue to work
   - New code should use `organization_id` + `department_id`

2. **Migration Strategy:**
   - Phase 1: Both old and new fields available (CURRENT)
   - Phase 2: Deprecate old fields
   - Phase 3: Remove old fields

3. **Data Consistency:**
   - When creating new requests, use `department_id`
   - Legacy `zone`, `ce_circle` fields can be populated for backward compatibility if needed

---

## 🚀 Next Steps

### Backend (Completed ✅)
- [x] Database migration
- [x] Model updates
- [x] Schema updates
- [x] API endpoint for hierarchy
- [x] Documentation

### Frontend (TODO)
- [ ] Update Testing Request form UI
- [ ] Replace location dropdowns with department selector
- [ ] Implement cascading department selection
- [ ] Or implement tree view for department selection
- [ ] Test creating requests with new fields
- [ ] Update testing request list view to show department names
- [ ] Update filters to use department hierarchy

---

## 📞 Support

For questions or issues:
1. Check `TESTING_REQUEST_DEPARTMENT_MIGRATION.md` for detailed guide
2. Test the `/testing_requests/department_hierarchy` endpoint
3. Verify department data with organization ID: `e4972e8a-83b5-47a6-86dd-ab28e2f9fe6a`
4. Check that you have 2,059 departments seeded in the database

---

**Date:** 2026-03-22
**Status:** ✅ Backend Complete - Ready for Frontend Integration
