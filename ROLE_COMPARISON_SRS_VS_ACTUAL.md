# SEACMS-AI Role Comparison: SRS vs Current Implementation

## SRS Roles (Section 2.3 - User Classes and Characteristics)

| User Class | Designation Examples | Primary Responsibilities |
|---|---|---|
| **Field / Data Entry** | AE Maintenance, Junior Engineers, Substation Operators | Enter test results, maintenance records, compliance uploads |
| **Zone / Circle Officer** | AEE Maintenance, Nodal Officer, EE TLSS | Review results, suggest remedial action, approve maintenance data |
| **Supervisory Officer** | SEE W&M Circle, EE RT, SEE RT | Trend analysis, schedule modification, vendor tracking |
| **Senior Management** | CEE Transmission Zone, CEE RT & R&D | Zone-level reports, policy-level analysis, exception management |
| **System Administrator** | RT & R&D Wing, Designated Admin Officer | User management, system configuration, master data setup |

### Additional SRS Role References
- **Responsible Officer Role** - Officer responsible for getting the test done
- **Reviewing Officer Role** - Officer responsible for analyzing results
- **EE TLSS** - Mentioned 10+ times in notification recipients
- **SEE W&M** - Mentioned 8+ times in notification recipients
- **CEE Transmission Zone** - Mentioned 5+ times in escalations
- **CEE RT&R&D** - Mentioned in repair tracking
- **AEE Maintenance** - Field-level responsible officer

---

## Current Implementation Roles

### Global Roles (applies to all organizations)
1. **Admin** - Full access to all modules
2. **Viewer** - Read-only access
3. **Operator** - Can scan and submit inventory
4. **Auditor** - Can view scan history and audit trails
5. **Vendor** - Can have access over products
6. **ERP_SERVICE** - Automated ERP sync service
7. **Originator** - Creates testing requests and raises procurement
8. **Tester** - Performs transformer testing and uploads results
9. **Approver** - Reviews and approves or rejects recommendations

### KPTCL Organization-Specific Roles (from seed.py)
1. **Admin** (orgadmin@kptcl.com)
2. **Originator** (originator@kptcl.com)
3. **Test Assigner** (testassigner@kptcl.com)
4. **Department Head** (depthead@kptcl.com)
5. **Purchaser** (purchaser@kptcl.com)
6. **Field Tester** (fieldtester1-5@kptcl.com)
7. **Lab Tester** (labtester1-5@kptcl.com)

---

## Gap Analysis

### ✅ COVERED (Functionally Equivalent)

| SRS Role | Our Role | Mapping Notes |
|---|---|---|
| Field / Data Entry | **Field Tester / Lab Tester** | Enter test results, upload compliance data |
| Zone / Circle Officer | **Test Assigner** | Reviews and assigns tests, suggests remedial actions |
| System Administrator | **Admin** | User management, system configuration, master data |
| Responsible Officer | **Originator** | Initiates testing requests |
| Reviewing Officer | **Approver / Test Assigner** | Reviews and approves test results |

### ❌ MISSING (Not Implemented)

| SRS Role | Designation | Why Missing |
|---|---|---|
| **Supervisory Officer** | SEE W&M Circle, EE RT, SEE RT | Trend analysis, schedule modification, vendor tracking |
| **Senior Management** | CEE Transmission Zone, CEE RT & R&D | Zone-level reports, policy-level analysis |
| **AEE Maintenance** | AEE (Assistant Executive Engineer) | Field-level responsible officer for maintenance |
| **EE TLSS** | EE (Executive Engineer) Transmission Line & Sub-Station | Primary reviewing officer, appears in 10+ notification templates |
| **SEE W&M** | SEE (Superintending Engineer) Works & Maintenance | Circle-level supervision, appears in 8+ reports |
| **CEE Transmission Zone** | CEE (Chief Engineer Executive) Transmission | Zone-level management, escalation recipient |
| **CEE RT&R&D** | CEE Research Testing & R&D | Repair tracking, transformer lifecycle management |

### ⚠️ PARTIAL COVERAGE

| Role Aspect | SRS Requirement | Current Implementation | Gap |
|---|---|---|---|
| **Hierarchy Levels** | 5 levels (Field → AEE → EE → SEE → CEE) | 3 levels (Tester → Assigner → Department Head) | Missing 2 intermediate supervisory levels |
| **Notification Recipients** | Role-based (EE TLSS, SEE W&M, CEE Zone) | Generic (Originator, Approver) | Cannot map to specific designations |
| **Report Access** | Role-specific (SEE W&M sees monthly, CEE sees quarterly) | Permission-based (can_view flag) | No role-specific report filtering |
| **Escalation Chain** | 4-level escalation (EE → SEE → CEE → RT&R&D) | Single-level approval | No multi-level escalation workflow |

---

## Recommendations

### Priority 1: Add Missing Supervisory Roles
```python
MISSING_ROLES = [
    {"name": "AEE Maintenance", "description": "Assistant Executive Engineer - Field maintenance responsible officer"},
    {"name": "EE TLSS", "description": "Executive Engineer - Transmission Line & Substation primary reviewer"},
    {"name": "SEE W&M", "description": "Superintending Engineer - Works & Maintenance circle supervisor"},
    {"name": "EE RT", "description": "Executive Engineer - Research & Testing"},
    {"name": "SEE RT", "description": "Superintending Engineer - Research & Testing"},
    {"name": "CEE Transmission Zone", "description": "Chief Engineer Executive - Transmission zone management"},
    {"name": "CEE RT&R&D", "description": "Chief Engineer Executive - Research Testing & R&D"},
]
```

### Priority 2: Update Notification Templates
Replace generic "Originator" / "Approver" with role-specific recipients:
- Test Due Reminder → **EE TLSS, AEE Maintenance**
- Test Overdue → **EE TLSS, SEE W&M**
- Test Overdue Escalation → **CEE Transmission Zone**
- CRITICAL Result → **EE TLSS, SEE W&M, CEE Zone**

### Priority 3: Implement Multi-Level Approval Chain
Current: `Originator → Approver (single step)`

SRS: `Field → AEE → EE → SEE → CEE (4-level escalation)`

### Priority 4: Role-Based Report Access
Map report frequency and access by designation:
- **Monthly**: AEE, EE TLSS, SEE W&M
- **Quarterly**: SEE W&M, CEE Zone
- **Annual**: CEE Zone, CEE RT&R&D

---

## Implementation Impact

| Change | Tables Affected | Estimated Effort |
|---|---|---|
| Add 7 new roles | `OrgRole`, `OrgRolePermission` | Low - seed data only |
| Update notification templates | `notification_templates.recipient_roles` | Medium - update 8 templates |
| Multi-level approval | `TestingRequest.approval_chain` JSONB | High - workflow logic change |
| Role-based report filtering | `report_definitions.recipient_roles` | Low - query filter |

---

## Current State Summary

**Roles Implemented**: 9 global + 7 KPTCL-specific = **16 roles**

**SRS Requirements**: 5 user classes + 7 specific designations = **12 distinct roles**

**Coverage**: ~60% functionally equivalent, 40% missing designation-specific roles

**Recommendation**: Add the 7 missing supervisory roles and update notification/report mappings to match SRS designation structure.
