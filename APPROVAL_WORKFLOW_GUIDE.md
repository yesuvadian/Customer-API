# Testing Request Approval Workflow

## Overview

This workflow adds an approval step between submission and tester assignment, where approvers can:
1. Review pending testing requests
2. Select a tester role (e.g., "North Zone Tester", "Bangalore Tester")
3. See all users with that role and their current workload
4. Manually assign the request to a specific tester

---

## Workflow States

```
draft → submitted → pending_approval → assigned → accepted → in_progress → test_submitted → approved
                          ↓
                      rejected
```

### New State: `pending_approval`

- **Color:** #FFC107 (Amber/Orange)
- **Icon:** approval
- **Description:** Request submitted and awaiting approval from department/section head
- **Who can see:** Approvers, Department Heads, Section Heads, Division Heads, Admins

---

## Workflow Steps

### 1. **Requester Submits Request**
- State: `draft` → `submitted`
- Action: Requester completes form and clicks "Submit"
- Result: Automatic transition to `pending_approval`

### 2. **Automatic Transition to Approval Queue**
- State: `submitted` → `pending_approval`
- Action: Automatic (no user action)
- Result: Request appears in approvers' pending queue

### 3. **Approver Reviews Request**
- State: `pending_approval`
- Approver sees:
  - Request details
  - Equipment information
  - Department/location

### 4. **Approver Selects Tester Role**
- Approver clicks "Approve & Assign"
- System shows dropdown of tester roles:
  - "North Zone Tester" (5 users)
  - "South Zone Tester" (3 users)
  - "Bangalore City Tester" (8 users)
  - etc.

### 5. **Approver Sees Users in Selected Role**
- Approver selects role (e.g., "North Zone Tester")
- System displays table of users:

| User | Email | Department | Active Requests |
|------|-------|------------|-----------------|
| John Doe | john@example.com | North Division | 2 |
| Jane Smith | jane@example.com | North Circle | 5 |
| Bob Wilson | bob@example.com | North Zone | 1 |

- **Sorted by workload** (least loaded first)
- Shows current active request count for informed decision

### 6. **Approver Assigns to Specific User**
- Approver clicks on a user to assign
- Optional: Add approval comment
- Click "Confirm Assignment"

### 7. **Request Assigned to Tester**
- State: `pending_approval` → `assigned`
- Tester receives notification
- Request appears in tester's queue

### 8. **Rejection (Alternative Path)**
- If approver rejects:
  - State: `pending_approval` → `rejected`
  - **Must provide rejection comment**
  - Requester notified with reason

---

## API Endpoints

### 1. Get Pending Approvals
```http
GET /testing-requests/approvals/pending
Authorization: Bearer <token>
```

**Response:**
```json
[
  {
    "id": "uuid",
    "request_number": "TR-2026-001",
    "equipment_name": "Power Transformer",
    "department_id": "uuid",
    "requester_email": "requester@example.com",
    "status": "pending_approval",
    "cts": "2026-03-23T10:00:00Z"
  }
]
```

### 2. Get Available Tester Roles
```http
GET /testing-requests/approvals/{request_id}/tester-roles
Authorization: Bearer <token>
```

**Response:**
```json
[
  {
    "role_id": "uuid",
    "role_name": "North Zone Tester",
    "description": "Testers for North Zone operations",
    "user_count": 5
  },
  {
    "role_id": "uuid",
    "role_name": "Bangalore City Tester",
    "description": "Testers for Bangalore city area",
    "user_count": 8
  }
]
```

### 3. Get Users by Tester Role
```http
GET /testing-requests/approvals/{request_id}/tester-roles/{role_id}/users
Authorization: Bearer <token>
```

**Response:**
```json
[
  {
    "user_id": "uuid",
    "email": "john@example.com",
    "name": "John Doe",
    "department_id": "uuid",
    "active_requests": 2
  },
  {
    "user_id": "uuid",
    "email": "jane@example.com",
    "name": "Jane Smith",
    "department_id": "uuid",
    "active_requests": 5
  }
]
```

### 4. Approve and Assign
```http
POST /testing-requests/approvals/{request_id}/approve-and-assign
Authorization: Bearer <token>
Content-Type: application/json

{
  "tester_role_id": "uuid",
  "tester_id": "uuid",
  "comment": "Approved for testing, assigned to John Doe"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Request approved and assigned to john@example.com",
  "testing_request_id": "uuid",
  "assigned_tester_id": "uuid",
  "assigned_tester_email": "john@example.com",
  "new_status": "assigned"
}
```

### 5. Reject Request
```http
POST /testing-requests/approvals/{request_id}/reject
Authorization: Bearer <token>
Content-Type: application/json

{
  "rejection_comment": "Equipment specifications incomplete, please revise"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Request rejected successfully",
  "testing_request_id": "uuid",
  "assigned_tester_id": null,
  "assigned_tester_email": null,
  "new_status": "rejected"
}
```

---

## Database Schema Changes

### New Workflow State
```sql
INSERT INTO workflow_states (
    id, workflow_id, state_code, state_name, description,
    state_type, color, icon, display_order, is_active
) VALUES (
    uuid_generate_v4(),
    '<workflow_id>',
    'pending_approval',
    'Pending Approval',
    'Request submitted and awaiting approval',
    'intermediate',
    '#FFC107',
    'approval',
    1.5,
    TRUE
);
```

### New Transitions
1. **submitted → pending_approval** (automatic)
2. **pending_approval → assigned** (manual, with tester selection)
3. **pending_approval → rejected** (manual, with comment required)

### Permissions
Added to permission_matrix for roles:
- Approver
- Department Head
- Section Head
- Division Head
- Admin

---

## Setup Instructions

### 1. Create Multiple Tester Roles

In **Organizations → Roles** page, create roles for different locations:

```
Role: North Zone Tester
Description: Handles testing requests for North Zone
Type: Custom
```

```
Role: South Zone Tester
Description: Handles testing requests for South Zone
Type: Custom
```

```
Role: Bangalore Tester
Description: Handles testing requests for Bangalore city
Type: Custom
```

### 2. Assign Users to Tester Roles

In **Organizations → User Roles** page:
- Select "North Zone Tester" role
- Check users who should be North Zone testers
- Save

Repeat for other tester roles.

### 3. Setup Workflow

**For Fresh Database:**
The approval workflow is included in `migrations/seed_testing_request_workflow.sql`.
When you run the migration, it will create the workflow with approval step automatically.

**For Existing Database (already has workflow):**
Run the migration script to add the approval step:

```bash
cd C:\Yesu\CustomerAPI\Customer-API
python add_approval_step_to_workflow.py
```

Type `yes` when prompted.

### 4. Integrate Service Methods

Copy methods from `add_approval_service.py` into:
```
services/testing_request_workflow_service.py
```

Add these two methods to the `TestingRequestWorkflowService` class:
- `approve_and_assign_tester()`
- `reject_testing_request()`

### 5. Add Schemas

Copy schemas from `add_approval_schemas.py` into:
```
schemas.py
```

Add these three schemas:
- `TesterInfo`
- `ApproverTesterSelection`
- `ApprovalResponse`

### 6. Register Router

In `main.py`:
```python
from routers import testing_request_approvals

app.include_router(
    testing_request_approvals.router,
    prefix="/api",
    tags=["Approvals"]
)
```

---

## Flutter UI Implementation (To Do)

### 1. Pending Approvals Screen

**Location:** `lib/pages/testing/pending_approvals_screen.dart`

**Features:**
- List of all requests in `pending_approval` state
- Filter by department/date
- Click to see request details

### 2. Approval Detail Screen

**Location:** `lib/pages/testing/approval_detail_screen.dart`

**Features:**
- Show full request details
- "Approve & Assign" button
- "Reject" button

### 3. Tester Selection Dialog

**Shows when user clicks "Approve & Assign":**

**Step 1: Select Tester Role**
```dart
DropdownButtonFormField<String>(
  decoration: InputDecoration(labelText: 'Select Tester Role'),
  items: testerRoles.map((role) {
    return DropdownMenuItem(
      value: role.roleId,
      child: Text('${role.roleName} (${role.userCount} users)'),
    );
  }).toList(),
  onChanged: (roleId) {
    // Fetch users for this role
    loadUsersForRole(roleId);
  },
)
```

**Step 2: Select Specific User**
```dart
DataTable(
  columns: [
    DataColumn(label: Text('Tester')),
    DataColumn(label: Text('Email')),
    DataColumn(label: Text('Active Requests')),
    DataColumn(label: Text('Action')),
  ],
  rows: users.map((user) {
    return DataRow(cells: [
      DataCell(Text(user.name)),
      DataCell(Text(user.email)),
      DataCell(Text('${user.activeRequests}')),
      DataCell(
        ElevatedButton(
          child: Text('Assign'),
          onPressed: () => assignToTester(user.userId),
        ),
      ),
    ]);
  }).toList(),
)
```

### 4. API Service Methods

**Location:** `lib/providers/testing_approval_provider.dart`

```dart
class TestingApprovalProvider extends ChangeNotifier {
  Future<List<TestingRequest>> fetchPendingApprovals() async {
    final response = await apiClient.get(
      '$apiUrl/testing-requests/approvals/pending',
      withAuth: true,
    );
    // Parse and return
  }

  Future<List<TesterRole>> fetchTesterRoles(String requestId) async {
    final response = await apiClient.get(
      '$apiUrl/testing-requests/approvals/$requestId/tester-roles',
      withAuth: true,
    );
    // Parse and return
  }

  Future<List<TesterInfo>> fetchUsersForRole(
    String requestId,
    String roleId,
  ) async {
    final response = await apiClient.get(
      '$apiUrl/testing-requests/approvals/$requestId/tester-roles/$roleId/users',
      withAuth: true,
    );
    // Parse and return
  }

  Future<String?> approveAndAssign({
    required String requestId,
    required String testerRoleId,
    required String testerId,
    String? comment,
  }) async {
    final response = await apiClient.post(
      '$apiUrl/testing-requests/approvals/$requestId/approve-and-assign',
      body: jsonEncode({
        'tester_role_id': testerRoleId,
        'tester_id': testerId,
        'comment': comment,
      }),
      withAuth: true,
    );
    // Handle response
  }

  Future<String?> rejectRequest({
    required String requestId,
    required String comment,
  }) async {
    final response = await apiClient.post(
      '$apiUrl/testing-requests/approvals/$requestId/reject',
      body: jsonEncode({'rejection_comment': comment}),
      withAuth: true,
    );
    // Handle response
  }
}
```

---

## Benefits

### For Approvers
- ✅ Review requests before tester assignment
- ✅ See all available testers in each role
- ✅ View tester workload for balanced assignment
- ✅ Flexibility to assign based on expertise/availability

### For Testers
- ✅ Only receive approved requests
- ✅ Workload visible to approvers for balanced distribution
- ✅ Clear accountability from approval stage

### For Organization
- ✅ Quality control through approval gate
- ✅ Better resource allocation
- ✅ Audit trail of who approved what
- ✅ Role-based organization of testers

---

## Testing Checklist

- [ ] Run migration: `python add_approval_step_to_workflow.py`
- [ ] Create multiple tester roles in Organizations → Roles
- [ ] Assign users to tester roles
- [ ] Test API: Get pending approvals
- [ ] Test API: Get tester roles for a request
- [ ] Test API: Get users for a tester role
- [ ] Test API: Approve and assign
- [ ] Test API: Reject request
- [ ] Verify workflow audit logs
- [ ] Test permissions for different user roles
- [ ] Implement Flutter UI screens
- [ ] End-to-end test: Submit → Approve → Assign → Accept

---

**Status:** ✅ Backend Complete | ⏳ Flutter UI Pending
**Last Updated:** 2026-03-23
