# CogniWatt Customer Portal - User Manual

## Table of Contents
1. [System Overview](#system-overview)
2. [Login Credentials](#login-credentials)
3. [User Roles & Permissions](#user-roles--permissions)
4. [Getting Started](#getting-started)
5. [Testing Request Workflow](#testing-request-workflow)
6. [User Guides by Role](#user-guides-by-role)
7. [Department Hierarchy](#department-hierarchy)
8. [Troubleshooting](#troubleshooting)

---

## System Overview

**CogniWatt Customer Portal** is an equipment testing management system for KPTCL (Karnataka Power Transmission Corporation Limited). The system manages the complete lifecycle of testing requests from submission to approval with automated tester assignment.

### Key Features
- ✅ Multi-tenant organization support
- ✅ Hierarchical department structure (6 levels)
- ✅ Role-based access control
- ✅ Automated tester assignment with workload balancing
- ✅ Complete workflow engine with 9 states
- ✅ Testing request tracking and approval
- ✅ Department-scoped permissions

---

## Login Credentials

### Default Password
**All users have the default password:** `admin123`

⚠️ **Security Note:** Please change your password after first login.

### Sample User Accounts

| Email | Role | Department | Password |
|-------|------|------------|----------|
| `orgadmin@kptcl.com` | Organization Admin | Organization Level | `admin123` |
| `depthead@kptcl.com` | Department Head | RT North Division | `admin123` |
| `tester1@kptcl.com` | Tester | Yelahanka Section | `admin123` |
| `tester2@kptcl.com` | Tester | RT North SD1 Yelahanka | `admin123` |
| `engineer@kptcl.com` | Engineer | 220kV Yelahanka Substation | `admin123` |

---

## User Roles & Permissions

### 1. Organization Admin (`orgadmin@kptcl.com`)

**Scope:** Full organization access

**Permissions:**
- ✅ View all departments and users
- ✅ Create/edit departments at all levels
- ✅ Manage roles and permissions
- ✅ View all testing requests across the organization
- ✅ Assign/reassign testers
- ✅ Configure workflow and permission matrix
- ✅ Access analytics and reports

**Typical Tasks:**
- Organization setup and configuration
- User management
- Department hierarchy management
- System administration

---

### 2. Department Head (`depthead@kptcl.com`)

**Department:** RT North Division

**Scope:** Department tree access (can see all child departments)

**Permissions:**
- ✅ View all requests in their department hierarchy
- ✅ Approve/reject test results
- ✅ View workload statistics for testers
- ✅ Assign/reassign testers within department scope
- ✅ View department dashboard
- ✅ Manage users within department

**Typical Tasks:**
- Review and approve test results
- Monitor testing progress
- Manage department resources
- Workload balancing

---

### 3. Tester (`tester1@kptcl.com`, `tester2@kptcl.com`)

**Departments:**
- Tester 1: Yelahanka Section
- Tester 2: RT North SD1 Yelahanka

**Scope:** Department-specific access

**Permissions:**
- ✅ View assigned testing requests
- ✅ Accept/reject testing assignments
- ✅ Start testing
- ✅ Submit test results
- ✅ Upload test reports and images
- ✅ View testing history
- ✅ Update testing status

**Typical Tasks:**
- Accept testing assignments (auto-assigned by system)
- Conduct equipment tests
- Record test results
- Submit test reports
- Upload test documentation

---

### 4. Engineer (`engineer@kptcl.com`)

**Department:** 220kV Yelahanka Substation

**Scope:** Department-specific access

**Permissions:**
- ✅ Create testing requests
- ✅ View own testing requests
- ✅ View test results and reports
- ✅ Cancel draft requests
- ✅ Track request status
- ✅ View testing history

**Typical Tasks:**
- Create new testing requests
- Track testing progress
- View test results
- Download test reports

---

### 5. Section Head

**Scope:** Section and sub-department access

**Permissions:**
- ✅ View requests in section hierarchy
- ✅ Monitor testing activities
- ✅ Assign testers within section
- ✅ View section analytics

---

## Getting Started

### First Login

1. **Access the Portal**
   ```
   URL: http://localhost:8000 (or your deployment URL)
   ```

2. **Login Steps:**
   - Enter your email address
   - Enter password: `admin123`
   - Click "Login"

3. **Change Password (Recommended):**
   - Go to Profile → Security Settings
   - Click "Change Password"
   - Enter current password and new password
   - Save changes

---

## Testing Request Workflow

### Workflow States

```
Draft → Submitted → Assigned → Accepted → In Progress → Test Submitted → Approved
                                    ↓                                        ↓
                                Rejected                                Rejected
                                    ↓
                                Cancelled
```

#### State Descriptions

| State | Description | Who Can See | Actions Available |
|-------|-------------|-------------|-------------------|
| **Draft** | Request being prepared | Requester only | Submit, Cancel |
| **Submitted** | Awaiting tester assignment | Requester, Dept Head, Admin | Auto-assign tester |
| **Assigned** | Tester assigned | Tester, Requester, Dept Head | Accept, Reject |
| **Accepted** | Tester accepted assignment | Tester, Requester, Dept Head | Start Testing |
| **In Progress** | Testing underway | Tester, Requester, Dept Head | Submit Results |
| **Test Submitted** | Results awaiting approval | Tester, Dept Head, Admin | Approve, Reject |
| **Approved** | Final approval (completed) | All | View, Download |
| **Rejected** | Rejected at any stage | All | View reason |
| **Cancelled** | Cancelled by requester | All | View |

---

## User Guides by Role

### 🔧 Engineer Guide: Creating a Testing Request

**Login:** `engineer@kptcl.com` / `admin123`

#### Step 1: Navigate to Create Request
1. Login to the portal
2. Go to **Testing Requests** → **Create New Request**

#### Step 2: Fill Request Details
```
Equipment Details:
- Equipment Type: Select from dropdown (e.g., Transformer, Circuit Breaker)
- Test Type: Select test to perform
- Transformer Type: Power Transformer / Distribution Transformer
- Transformer Rating: e.g., 100 MVA, 11/0.433 kV
- Manufacturer: Equipment manufacturer name
- Serial Number: Manufacturer serial number

Request Information:
- Title: Brief description (e.g., "Transformer Testing - 220kV Substation")
- Description: Detailed testing requirements
- Priority: Normal / High / Urgent
- Requested Date: When testing should be done
- Due Date: Deadline for completion

Location:
- Department: Auto-filled (220kV Yelahanka Substation)
```

#### Step 3: Submit Request
- Click **"Submit Request"**
- ✅ **No need to select a tester** - the system will auto-assign based on:
  - Tester availability
  - Current workload
  - Department hierarchy matching
  - Tester expertise

#### Step 4: Track Progress
- Go to **My Requests** to view status
- Click on request to see details
- View assigned tester
- Track state changes in real-time

---

### 🔬 Tester Guide: Processing Testing Requests

**Login:** `tester1@kptcl.com` or `tester2@kptcl.com` / `admin123`

#### Step 1: View Assigned Requests
1. Login to portal
2. Go to **Dashboard** → **Assigned to Me**
3. View list of pending assignments

#### Step 2: Accept Assignment
```
- Click on the assigned request
- Review equipment details and requirements
- Click "Accept Assignment"
- Or click "Reject Assignment" with reason if unable to test
```

#### Step 3: Start Testing
```
- Once accepted, click "Start Testing"
- Status changes to "In Progress"
- Conduct the equipment tests as per specifications
```

#### Step 4: Submit Test Results
```
1. Click "Submit Test Results"
2. Fill in the test results form:
   - Test Date & Time
   - Test Location
   - Test Equipment Used
   - Test Parameters (voltage, current, resistance, etc.)
   - Test Observations
   - Recommendation: Pass / Fail / Conditional / Retest

3. Upload Supporting Documents:
   - Test report PDF
   - Test images
   - Equipment photos
   - Measurement screenshots

4. Add Notes/Comments
5. Click "Submit Results"
```

#### Step 5: Track Submitted Results
- Results go to Department Head for approval
- View status in **My Testing History**
- Receive notification when approved/rejected

---

### 👔 Department Head Guide: Approval Process

**Login:** `depthead@kptcl.com` / `admin123`

#### Step 1: View Pending Approvals
1. Login to portal
2. Go to **Dashboard** → **Pending Approvals**
3. View all test results awaiting approval

#### Step 2: Review Test Results
```
- Click on the request
- Review:
  ✓ Equipment details
  ✓ Test parameters
  ✓ Test results
  ✓ Uploaded reports and images
  ✓ Tester recommendations
```

#### Step 3: Approve or Reject
```
Option A: Approve
- Click "Approve"
- Add approval comments (optional)
- Click "Confirm"
- Status changes to "Approved"

Option B: Reject
- Click "Reject"
- Enter rejection reason (mandatory)
- Specify what needs to be corrected
- Click "Confirm"
- Status changes to "Rejected"
- Tester is notified
```

#### Step 4: Monitor Department Workload
```
- Go to "Department Analytics"
- View:
  - Active testing requests by tester
  - Average completion time
  - Pending vs completed requests
  - Workload distribution chart
```

#### Step 5: Manual Tester Assignment (if needed)
```
- Go to request details
- Click "Reassign Tester"
- Select new tester from department
- Enter reassignment reason
- Click "Assign"
- New tester receives notification
```

---

### 👨‍💼 Organization Admin Guide: System Management

**Login:** `orgadmin@kptcl.com` / `admin123`

#### Step 1: Manage Organization
```
1. Go to "Organizations" → "KPTCL"
2. View/edit organization details:
   - Organization name
   - Industry
   - Contact information
   - Settings
```

#### Step 2: Manage Departments
```
1. Go to "Organizations" → "Departments"
2. View department hierarchy tree
3. Add new department:
   - Click "Add Department"
   - Select parent department
   - Select department type
   - Enter name and code
   - Assign manager (optional)
   - Save

4. Edit existing department:
   - Click department name
   - Update details
   - Save changes
```

#### Step 3: Manage Users
```
1. Go to "Users"
2. View all users in organization
3. Create new user:
   - Click "Add User"
   - Enter email, name, phone
   - Select department
   - Assign role(s)
   - Set status (active/inactive)
   - Send invitation

4. Edit user:
   - Click user email
   - Update details, department, or roles
   - Deactivate if needed
```

#### Step 4: Manage Roles & Permissions
```
1. Go to "Roles & Permissions"
2. View existing roles
3. Create custom role:
   - Click "Create Role"
   - Enter role name and description
   - Set permissions by module
   - Define department scope
   - Save

4. Configure Permission Matrix:
   - Go to "Workflow" → "Permissions"
   - Set role-based transition permissions
   - Define scope (exact, department_tree, organization)
   - Set priorities
```

#### Step 5: View Analytics
```
- Go to "Analytics Dashboard"
- View organization-wide metrics:
  ✓ Total testing requests
  ✓ Completion rate
  ✓ Average turnaround time
  ✓ Department performance
  ✓ Tester workload distribution
  ✓ Approval rates
```

---

## Department Hierarchy

### KPTCL Organization Structure

```
Karnataka Power Transmission Corporation Limited (KPTCL)
│
└── Bangalore Zone
    │
    └── Bangalore Transmission Circle
        │
        └── RT North Division
            │
            └── RT North SD1 Yelahanka (Subdivision)
                │
                ├── Yelahanka Section
                │   │
                │   └── 220kV Yelahanka Substation
                │
                └── (Other sections...)
```

### Department Types

| Level | Type | Code | Example |
|-------|------|------|---------|
| 1 | Zone | ZONE | Bangalore Zone |
| 2 | Circle | CIRCLE | Bangalore Transmission Circle |
| 3 | Division | DIVISION | RT North Division |
| 4 | Subdivision | SUBDIVISION | RT North SD1 Yelahanka |
| 5 | Section | SECTION | Yelahanka Section |
| 6 | Substation | SUBSTATION | 220kV Yelahanka Substation |

### Department Codes

| Department | Code |
|------------|------|
| Bangalore Zone | `BLR_ZONE` |
| Bangalore Transmission Circle | `BLR_TRANS_CIRCLE` |
| RT North Division | `RT_NORTH_DIV` |
| RT North SD1 Yelahanka | `RT_NORTH_SD1` |
| Yelahanka Section | `YLK_SECTION` |
| 220kV Yelahanka Substation | `220KV_YLK` |

---

## Auto-Assignment System

### How Tester Auto-Assignment Works

When an engineer submits a testing request:

1. **System analyzes eligible testers:**
   - Same organization (KPTCL)
   - Has "Tester" role
   - Department hierarchy matching (parent/child/sibling departments)
   - Active status

2. **Workload balancing strategies:**

   **Strategy A: Least Loaded (Default)**
   - Counts active assignments per tester
   - Assigns to tester with fewest active requests
   - Fair distribution of work

   **Strategy B: Round Robin**
   - Rotates assignments among testers
   - Ensures equal distribution over time

   **Strategy C: Priority-Based**
   - Assigns based on tester skill/experience level
   - Matches equipment type expertise

   **Strategy D: Random**
   - Random selection from eligible testers
   - Useful for training scenarios

3. **Availability check:**
   - Max concurrent assignments: 5 (configurable)
   - Checks tester is not on leave
   - Verifies active status

4. **Automatic assignment:**
   - Tester auto-assigned to request
   - State changes: Submitted → Assigned
   - Tester receives notification
   - Requester sees assigned tester

---

## Common Workflows

### Workflow 1: Successful Testing Request

```
Engineer creates request
    ↓
Engineer submits request (Draft → Submitted)
    ↓
System auto-assigns tester (Submitted → Assigned)
    ↓
Tester accepts assignment (Assigned → Accepted)
    ↓
Tester starts testing (Accepted → In Progress)
    ↓
Tester submits results (In Progress → Test Submitted)
    ↓
Dept Head approves (Test Submitted → Approved)
    ↓
✓ Request completed
```

### Workflow 2: Request Rejected by Tester

```
System assigns tester (Submitted → Assigned)
    ↓
Tester rejects with reason (Assigned → Rejected)
    ↓
System auto-reassigns to next available tester
    ↓
New tester accepts...
```

### Workflow 3: Results Rejected by Dept Head

```
Tester submits results (In Progress → Test Submitted)
    ↓
Dept Head reviews and rejects (Test Submitted → Rejected)
    ↓
Dept Head specifies corrections needed
    ↓
Tester makes corrections and resubmits
```

---

## API Endpoints Reference

### Authentication
```
POST /auth/login
Body: { email, password }
Returns: { access_token, user_details }
```

### Testing Requests
```
GET  /testing-requests/                    # List all requests
POST /testing-requests/                    # Create new request
GET  /testing-requests/{id}                # Get request details
PUT  /testing-requests/{id}                # Update request
DELETE /testing-requests/{id}              # Delete draft request

GET  /testing-requests/my-requests         # My requests (engineer)
GET  /testing-requests/assigned-to-me      # Assigned to me (tester)
GET  /testing-requests/pending-approval    # Pending approval (dept head)
```

### Workflow Actions
```
POST /testing-requests/{id}/submit         # Submit request (draft → submitted)
POST /testing-requests/{id}/accept         # Accept assignment (assigned → accepted)
POST /testing-requests/{id}/reject         # Reject assignment
POST /testing-requests/{id}/start          # Start testing (accepted → in_progress)
POST /testing-requests/{id}/submit-results # Submit results (in_progress → test_submitted)
POST /testing-requests/{id}/approve        # Approve results (test_submitted → approved)
POST /testing-requests/{id}/cancel         # Cancel request
```

### Tester Assignment
```
POST /tester-assignment/auto-assign        # Auto-assign tester
POST /tester-assignment/assign             # Manual assignment
POST /tester-assignment/reassign           # Reassign tester
GET  /tester-assignment/workload-stats     # Tester workload dashboard
GET  /tester-assignment/availability/{id}  # Check tester availability
GET  /tester-assignment/eligible-testers/{request_id}  # List eligible testers
```

### Organizations & Departments
```
GET  /organizations/                       # List organizations
GET  /organizations/{id}/departments/      # Get department hierarchy
POST /organizations/{id}/departments/      # Create department
PUT  /departments/{id}                     # Update department
```

---

## Troubleshooting

### Issue: Cannot Login

**Problem:** "Invalid credentials" error

**Solutions:**
1. ✓ Check email is correct (including @kptcl.com domain)
2. ✓ Verify password is `admin123` (case-sensitive)
3. ✓ Check CAPS LOCK is off
4. ✓ Clear browser cache and cookies
5. ✓ Contact admin to verify account is active

---

### Issue: Cannot See Testing Requests

**Problem:** Request list is empty

**Solutions:**
1. ✓ Check you have correct role permissions
2. ✓ Verify department assignment
3. ✓ Check filter settings (status, date range)
4. ✓ Engineers: Go to "My Requests" tab
5. ✓ Testers: Go to "Assigned to Me" tab
6. ✓ Dept Heads: Check "Department Requests" view

---

### Issue: Auto-Assignment Not Working

**Problem:** Request stuck in "Submitted" state

**Solutions:**
1. ✓ Verify testers exist in same organization
2. ✓ Check testers have "Tester" role assigned
3. ✓ Ensure testers are in matching department hierarchy
4. ✓ Verify testers are active (not on leave)
5. ✓ Check tester workload < 5 active requests
6. ✓ Contact admin for manual assignment

---

### Issue: Cannot Submit Test Results

**Problem:** "Submit Results" button disabled

**Solutions:**
1. ✓ Verify request is in "In Progress" state
2. ✓ Check you started testing first
3. ✓ Fill all required fields in the form
4. ✓ Upload at least one test report
5. ✓ Select recommendation (Pass/Fail/Conditional)

---

### Issue: Cannot Approve Results

**Problem:** "Approve" button not visible

**Solutions:**
1. ✓ Verify you have "Department Head" or "Admin" role
2. ✓ Check request is in "Test Submitted" state
3. ✓ Ensure request is within your department scope
4. ✓ Check you have approve permission in permission matrix

---

## Best Practices

### For Engineers (Requesters)

✅ **DO:**
- Provide complete equipment details
- Set realistic due dates
- Add clear testing requirements in description
- Attach equipment specifications if available
- Track request progress regularly

❌ **DON'T:**
- Submit incomplete requests
- Set impossible deadlines
- Create duplicate requests
- Cancel requests unnecessarily

---

### For Testers

✅ **DO:**
- Accept assignments promptly
- Start testing on scheduled date
- Document all test parameters
- Upload clear test reports
- Add detailed observations
- Submit results with recommendations

❌ **DON'T:**
- Accept more assignments than you can handle
- Delay testing without communication
- Submit incomplete test results
- Skip uploading test documentation

---

### For Department Heads

✅ **DO:**
- Review test results thoroughly
- Provide clear rejection reasons
- Monitor department workload
- Balance tester assignments
- Track approval turnaround time

❌ **DON'T:**
- Approve without reviewing test data
- Reject without clear reasons
- Overload specific testers
- Delay approvals unnecessarily

---

## Support & Contact

### Technical Support
- **Email:** support@cogniwatt.com
- **Phone:** +91-XXXX-XXXXX
- **Hours:** Monday - Friday, 9:00 AM - 6:00 PM IST

### System Administrator
- **Name:** Organization Admin
- **Email:** orgadmin@kptcl.com
- **For:** User account issues, permissions, system configuration

### Training & Documentation
- **User Manual:** This document
- **Video Tutorials:** [Link to training videos]
- **FAQ:** [Link to FAQ page]
- **Release Notes:** [Link to release notes]

---

## Appendix

### A. Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl + N` | New testing request |
| `Ctrl + S` | Save draft |
| `Ctrl + Enter` | Submit form |
| `Esc` | Close modal |
| `Ctrl + F` | Search requests |

### B. Status Color Codes

| Status | Color | Icon |
|--------|-------|------|
| Draft | Gray | ✏️ |
| Submitted | Blue | 📤 |
| Assigned | Orange | 👤 |
| Accepted | Green | ✓ |
| In Progress | Cyan | ⚙️ |
| Test Submitted | Purple | 📋 |
| Approved | Green | ✅ |
| Rejected | Red | ❌ |
| Cancelled | Dark Gray | 🚫 |

### C. File Upload Limits

| File Type | Max Size | Allowed Formats |
|-----------|----------|-----------------|
| Test Reports | 10 MB | PDF, DOC, DOCX |
| Images | 5 MB | JPG, PNG, JPEG |
| Attachments | 20 MB | PDF, DOC, XLS, ZIP |

### D. System Requirements

**Supported Browsers:**
- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

**Screen Resolution:**
- Minimum: 1280 x 720
- Recommended: 1920 x 1080

**Internet Connection:**
- Minimum: 2 Mbps
- Recommended: 10 Mbps

---

## Document Information

**Version:** 1.0
**Last Updated:** March 22, 2026
**Document Owner:** CogniWatt Development Team
**Next Review Date:** June 22, 2026

---

**End of User Manual**

For the latest version of this manual, visit: [Documentation Portal URL]
