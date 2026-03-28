# CogniWatt Portal - Quick Reference Guide

## 🔑 Login Credentials

| User | Email | Password | Role |
|------|-------|----------|------|
| Org Admin | `orgadmin@kptcl.com` | `admin123` | Organization Admin |
| Dept Head | `depthead@kptcl.com` | `admin123` | Department Head |
| Tester 1 | `tester1@kptcl.com` | `admin123` | Tester |
| Tester 2 | `tester2@kptcl.com` | `admin123` | Tester |
| Engineer | `engineer@kptcl.com` | `admin123` | Engineer |

---

## 🔄 Workflow Quick View

```
Draft → Submitted → Assigned → Accepted → In Progress → Test Submitted → Approved
          (auto)      (tester)   (tester)    (tester)      (dept head)
```

---

## 🎯 Quick Actions by Role

### 👷 Engineer
1. Login: `engineer@kptcl.com`
2. Create Request → Fill Details → **Submit** (no tester selection needed!)
3. Track in "My Requests"

### 🔬 Tester
1. Login: `tester1@kptcl.com` or `tester2@kptcl.com`
2. View "Assigned to Me"
3. **Accept** → **Start Testing** → **Submit Results**

### 👔 Department Head
1. Login: `depthead@kptcl.com`
2. View "Pending Approvals"
3. Review Results → **Approve** or **Reject**

### 👨‍💼 Org Admin
1. Login: `orgadmin@kptcl.com`
2. Manage Organizations → Departments → Users → Roles

---

## 📊 Workflow States

| State | Who Acts | Action Button |
|-------|----------|---------------|
| **Draft** | Engineer | Submit |
| **Submitted** | System | Auto-assign |
| **Assigned** | Tester | Accept / Reject |
| **Accepted** | Tester | Start Testing |
| **In Progress** | Tester | Submit Results |
| **Test Submitted** | Dept Head | Approve / Reject |
| **Approved** | - | (Final) |

---

## 🏢 Department Hierarchy

```
KPTCL
└─ Bangalore Zone
   └─ Bangalore Transmission Circle
      └─ RT North Division (depthead@kptcl.com)
         └─ RT North SD1 Yelahanka (tester2@kptcl.com)
            └─ Yelahanka Section (tester1@kptcl.com)
               └─ 220kV Yelahanka Substation (engineer@kptcl.com)
```

---

## ⚡ Testing Process Flow

### Step 1: Engineer Creates Request
```
Login → Testing Requests → Create New
Fill: Equipment Type, Test Type, Title, Description, Priority
Submit (no tester selection!)
```

### Step 2: System Auto-Assigns
```
System finds eligible tester based on:
- Same organization
- Department hierarchy match
- Least workload
- Availability
```

### Step 3: Tester Accepts & Tests
```
Login → Assigned to Me → Accept
Start Testing → Conduct Tests
Submit Results → Upload Reports
```

### Step 4: Dept Head Approves
```
Login → Pending Approvals → Review
Approve (with comments) or Reject (with reason)
```

---

## 🔧 Common Operations

### Create Testing Request
```
Path: Testing Requests → Create New
Required: Equipment Type, Test Type, Title, Transformer Rating
Optional: Description, Priority, Due Date
Submit: Auto-assigns tester
```

### Accept Testing Assignment
```
Path: Dashboard → Assigned to Me → [Request]
Action: Click "Accept Assignment"
Result: State → Accepted, can start testing
```

### Submit Test Results
```
Path: My Tests → [Request] → Submit Results
Required: Test Date, Test Data, Recommendation
Upload: Test report PDF, images
Submit: Goes to Dept Head for approval
```

### Approve/Reject Results
```
Path: Pending Approvals → [Request] → Review
Approve: Click "Approve" → Add comments → Confirm
Reject: Click "Reject" → Enter reason → Confirm
```

---

## 🚀 Quick Tips

### Auto-Assignment
- ✅ Works automatically on submit
- ✅ Based on workload balancing
- ✅ Max 5 concurrent requests per tester
- ✅ Respects department hierarchy

### Permissions
- **Org Admin**: See everything
- **Dept Head**: See department tree
- **Tester**: See assigned requests
- **Engineer**: See own requests

### Best Practices
- 📝 Provide complete equipment details
- 📅 Set realistic deadlines
- 📸 Upload clear test images
- 💬 Add detailed observations
- ✓ Review results thoroughly before approval

---

## 🐛 Quick Troubleshooting

| Issue | Solution |
|-------|----------|
| Can't login | Check email & password (admin123) |
| No requests visible | Check role & department |
| Auto-assign not working | Check tester availability |
| Can't submit results | Fill all required fields |
| Can't approve | Check role & department scope |

---

## 📞 Quick Contacts

| Need | Contact |
|------|---------|
| Account issues | `orgadmin@kptcl.com` |
| Technical support | support@cogniwatt.com |
| Training | [Training portal URL] |

---

**Last Updated:** March 22, 2026
