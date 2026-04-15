# SEACMS-AI SRS v1.3 — Gap Analysis & Implementation Recommendations

**Date:** April 2026
**Prepared By:** Development Team
**Reference:** SEACMS-AI SRS v1.3 (KPTCL/RT&R&D/SRS/SEACMS-AI/001)

---

## 1. Executive Summary

This document analyses the SEACMS-AI SRS v1.3 against our existing platform capabilities and provides implementation recommendations. Our platform already covers **testing workflows, equipment/test type hierarchy, dynamic JSONB templates, multi-session testing, recurring schedules, role-based assignments, procurement (RFQ → Quote → Sales Order → Payment), vendor directory, RBAC, and PDF generation**.

By reusing existing patterns (OrgDepartment hierarchy, OrgTestTemplate JSONB, TestingRequest workflow, multi-session/readings, Recommendation → ProcurementRequest chain), the full SRS can be delivered with **9 new tables, 3 new columns, and zero new workflow engines**.

---

## 2. SRS Document Integrity Issues

| # | Issue | Location | Severity |
|---|-------|----------|----------|
| 1 | **Version mismatch**: filename says v1.3 but cover page and Appendix B show 1.0. No revision entries for 1.1/1.2/1.3. | Cover, Appendix B | Medium |
| 2 | **Section numbering error**: Section 12 (User Management & Security) subsections numbered as 10.1 and 10.2. | Section 12 | High |
| 3 | **Document overview incorrect**: Section 1.5 says "Sections 12 and 13 introduce Procurement and AI" — actual sections are 10 and 11. | Section 1.5 | Medium |
| 4 | **Approval column blank**: Appendix B shows "Approved By: Pending" for a document labelled as procurement baseline. | Appendix B | Medium |

---

## 3. What Our Platform Already Covers

| SRS Requirement | Our Implementation |
|---|---|
| Testing workflow (create → assign → test → approve) | `TestingRequest` with full status machine, `testing_requests.py`, `testing.py`, `approvals.py` |
| Equipment types & test types hierarchy | `CategoryMaster` → `CategoryDetails` (13 equipment types, 30+ test types) |
| Dynamic test templates (JSONB) | `OrgTestTemplate` with `test_templates.py` (1844 lines, per-test-type form definitions) |
| Multi-session testing | `TestSession` + `TestSessionReading` + `AutoStatusTransitionService` |
| Recurring/scheduled testing | `TestRequestSchedule` with daily/weekly/biweekly/monthly/quarterly/yearly |
| Role-based tester assignment | Two-step role → user selection with workload balancing |
| Procurement trigger from test results | `ProcurementRequest` linked to `TestingRequest` + `Recommendation` |
| RFQ & vendor selection | `quotes.py` — multi-vendor RFQ, vendor assignment, quote comparison |
| Quote approval workflow | Customer review → approve → accept → sales order (Zoho Books) |
| Payment processing | `payments.py` — payment recording against invoices |
| Vendor directory & documents | `vendor_directory.py` — vendor listing, document downloads |
| PDF report generation | Testing request PDF, recommendation PDF, quote PDF |
| Image attachments on results | `TestResultImage`, `TestSessionReadingImage` |
| RBAC with module-level permissions | `OrgRole` + `OrgRolePermission` with 6 permission flags per module |
| Recommendation types | `Recommendation` model: pass/fail/conditional/retest + `replacement_products` JSONB |
| Remedial action → procurement chain | `Recommendation` (summary + replacement_products) → approval → `ProcurementRequest` → RFQ → Quote → SO → Payment |
| Department hierarchy | `OrgDepartment` with parent-child tree (Zone → Circle → Division → Sub-Div → Substation) |
| Session comments | `SessionComment` for collaborative feedback during testing |
| Auto-assignment strategies | `TesterAutoAssignmentService` (least_loaded, round_robin, random, priority) |

---

## 4. Gaps & Recommendations by SRS Section

---

### 4.1 Equipment Asset Register (UEIC) — SRS Section 3

**Gap:** We have equipment **types** (`CategoryMaster`) but not individual equipment **instances** with unique IDs, nameplate data, and lifecycle tracking.

**Recommendation: New `Equipment` model linked to `OrgDepartment`.**

#### Design

```
OrgDepartment (tree)                         Equipment (new)
─────────────────                            ─────────────
KPTCL (org)
 └── Bangalore Zone (dept)
      └── BMAZ North Circle (dept)
           └── Bangalore Urban Div (dept)
                └── TL&SS Sub-Div 1 (dept)
                     └── 220kV SS Peenya (dept) ←── department_id
                          ├── BZ-PNYA-220-01-PT-01  (Power Transformer)
                          ├── BZ-PNYA-220-01-CB-01  (Circuit Breaker)
                          └── BZ-PNYA-220-02-CT-01  (Current Transformer)
```

#### Model

```python
class Equipment(Base):
    __tablename__ = "equipment"

    id            = Column(UUID, primary_key=True, default=uuid.uuid4)
    ueic          = Column(String(50), unique=True, nullable=False)  # auto-generated

    organization_id   = Column(UUID, ForeignKey("organizations.id"), nullable=False)
    department_id     = Column(UUID, ForeignKey("org_departments.id"), nullable=False)  # substation level
    equipment_type_id = Column(Integer, ForeignKey("CategoryMaster.id"), nullable=False)

    voltage_class     = Column(String(10))    # "220", "110", "66"
    bay_number        = Column(String(10))    # "01", "02"
    serial_in_bay     = Column(String(10))    # "01"

    nameplate_data    = Column(JSONB)         # fields vary by equipment_type (template-driven)

    status                = Column(String(20), default="active")  # active, retired, scrapped
    replaces_equipment_id = Column(UUID, ForeignKey("equipment.id"), nullable=True)
    commissioned_date     = Column(DateTime)
    retired_date          = Column(DateTime, nullable=True)

    created_by = Column(UUID, ForeignKey("users.id"))
    cts        = Column(DateTime, server_default=func.now())
    mts        = Column(DateTime, server_default=func.now(), onupdate=func.now())
```

#### UEIC Auto-Generation

```
Format: {zone_code}-{substation_code}-{voltage}-{bay}-{type_code}-{serial}
Example: BZ-PNYA-220-01-CB-01

zone_code       = 2 letters from ancestor OrgDepartment at zone level
substation_code = 4 chars from OrgDepartment.code at substation level
type_code       = from CategoryMaster equipment type code (Appendix A of SRS)
```

#### Test Request Form — New Flow

```
Step 1: User drills OrgDepartment tree (already built)
        Zone → Circle → Division → Sub-Div → Substation

Step 2: GET /equipment?department_id={substation_id}
        → returns equipment list at that location

Step 3: User picks equipment
        → auto-fills: equipment_type_id, nameplate fields, hierarchy strings

Step 4: GET /category_details/details/by-master/{equipment_type_name}
        → returns applicable test types for that equipment

Step 5: User picks test type → template loads (existing flow)
```

#### Nameplate Templates

Reuse `OrgTestTemplate` pattern with `template_category: "nameplate"`. One nameplate template per equipment type. KPTCL admins manage fields in the same template builder UI.

#### Replacement Workflow

- Soft-retire old UEIC: `status = "retired"`, `retired_date = now()`
- Create new Equipment with `replaces_equipment_id` FK to retired unit
- All historical data stays linked to the retired UEIC permanently

#### New API Endpoints

```
POST   /equipment/                                — register new equipment (auto-generates UEIC)
GET    /equipment/                                — list with filters (department_id, equipment_type_id, status)
GET    /equipment/{id}                            — get single equipment with nameplate
PUT    /equipment/{id}                            — update nameplate data
GET    /equipment/{id}/history                    — full lifecycle (tests, maintenance, failures)
GET    /equipment?department_id={substation_id}   — equipment at a location (for form auto-populate)
GET    /equipment/{id}/applicable-tests           — test types for this equipment type
```

**Impact:** 1 new table (`equipment`), 1 new column (`testing_requests.equipment_id`)

---

### 4.2 Maintenance Activity Monitoring — SRS Section 4

**Gap:** We have testing workflows but not routine/preventive maintenance checklists, scheduling, and overdue tracking.

**Recommendation: Reuse existing template + testing request workflow with a `request_category` flag.**

Maintenance checklists are structurally identical to test templates — dynamic JSONB forms with sections and fields. No parallel system needed.

#### Changes

- Add `request_category` to `TestingRequest`: `"test"` | `"maintenance"` | `"inspection"`
- Maintenance templates go into `OrgTestTemplate` with `template_category: "maintenance"`
- Scheduling uses existing `TestRequestSchedule` (monthly, quarterly, annual)
- Overdue tracking: query `TestingRequest` where `request_category = "maintenance"` and `due_date < now()` and `status != completed`

#### Cumulative Operations Counter (CB / OLTC)

- Add fields to equipment `nameplate_data` JSONB: `cumulative_ops`, `overhaul_threshold`
- Monthly counter reading = a recurring maintenance test type
- When reading value >= threshold → evaluation engine flags CRITICAL → auto-creates recommendation for overhaul via existing `Recommendation` model

#### Maintenance Templates (JSONB seed data)

- Routine maintenance checklist per equipment type (Yes/No, Pass/Fail, Measurement fields)
- Power Transformer major maintenance (oil replacement, filtration, OLTC overhaul, gasket replacement, bushing replacement)
- Circuit Breaker major maintenance (limb overhaul, mechanism overhaul, SF6 refill)
- C&R Panel maintenance (relay testing, wiring inspection, DC supply check, annunciation check)
- Battery Set maintenance (capacity test, cell voltage, electrolyte levels, charger check)
- Generic major maintenance (free-text + mandatory document upload)

**Impact:** 1 new column (`testing_requests.request_category`), 0 new tables. Just template seed data.

---

### 4.3 Automated Test Result Evaluation — SRS Section 5.2

**Gap:** We capture structured test results in JSONB but don't auto-evaluate against acceptance criteria.

**Recommendation: Inline evaluation criteria in existing `OrgTestTemplate` field definitions.**

#### Extended Template Field Schema

```json
{
  "key": "ir_value_hv_lv",
  "label": "IR Value HV-LV",
  "type": "number",
  "unit": "MΩ",
  "required": true,
  "evaluation": {
    "enabled": true,
    "normal_min": 500,
    "normal_max": null,
    "alert_min": 200,
    "alert_max": 499,
    "critical_below": 200,
    "critical_above": null,
    "trend_watch": true,
    "revised_interval_days": 90,
    "remedial_action_text": "IR value critically low. Inspect winding insulation.",
    "suggested_products": ["Transformer Bushing HV Side", "Insulating Oil"]
  }
}
```

#### Evaluation Result Stored on TestResult

```json
{
  "overall": "ALERT",
  "evaluated_at": "2026-04-14T10:30:00Z",
  "fields": [
    {"key": "ir_value_hv_lv", "label": "IR Value HV-LV", "value": 350, "unit": "MΩ", "status": "ALERT"},
    {"key": "ir_value_hv_e", "label": "IR Value HV-E", "value": 800, "unit": "MΩ", "status": "NORMAL"}
  ]
}
```

#### Evaluation Triggers

| Result | Action |
|--------|--------|
| NORMAL | No action. Next test at default periodicity. |
| ALERT | Auto-shorten next test interval using `revised_interval_days`. Flag equipment on dashboard. |
| CRITICAL | Pre-fill `Recommendation.summary` from `remedial_action_text`. Pre-fill `replacement_products` from `suggested_products`. Fire high-priority notification. |

#### Why Inline is Better Than a Separate Table

| Separate AcceptanceCriteria table | Inline in template |
|---|---|
| FK sync between criteria rows and template fields | Criteria lives with the field — one source of truth |
| Admin edits criteria in a different screen | Admin sets criteria in the same template builder |
| Must match by parameter_key string — fragile | Part of the field object — cannot mismatch |
| Separate migration, model, router, service | Zero new tables, just richer JSONB |

**Impact:** 1 new column (`test_results.evaluation_result` JSONB), 0 new tables.

---

### 4.4 Remedial Action Workflow — SRS Section 5.2.4

**Gap:** None. Already implemented.

**Our existing chain:**

```
Test Result (tester submits)
    ↓ auto-creates
Recommendation (type: pass/fail/conditional/retest)
    ├── summary + detailed_notes         ← the "remedial action"
    ├── replacement_products (JSONB)      ← the "what needs to be procured"
    ↓ approver reviews
Approval (approved/rejected)
    ↓ if approved + has replacement_products
ProcurementRequest (auto-created, linked to recommendation_id)
    ↓
RFQ → Quotes → Sales Order → Payment
```

**Enhancement from Section 4.3:** Auto-evaluation pre-fills recommendation from template criteria instead of tester writing manually.

**Impact:** Nothing to build. Already done.

---

### 4.5 TA&QC Module — SRS Section 6

**Gap:** No inspection observation capture, compliance tracking, or TA&QC dashboards.

**Recommendation: Another `request_category` on the existing workflow.**

- `request_category: "inspection"` on `TestingRequest`
- TA&QC template in `OrgTestTemplate` with sections: observation category (dropdown: Electrical Safety / Civil / Fire Safety / Documentation / Environmental / General Maintenance), severity (major/minor/advisory), description, photos, target compliance date
- Compliance response = a session reading by substation staff (action taken, date, photos)
- TA&QC reviewer uses existing approval flow to close or reopen
- Compliance dashboard: query `TestingRequest` where `request_category = "inspection"` grouped by substation, count open/closed/overdue

**Impact:** 0 new tables, 0 new columns. Reuses `request_category` from Section 4.2. Just template seed data.

---

### 4.6 Power Transformer Repair Lifecycle — SRS Section 7

**Gap:** No 10-stage repair tracking, delay monitoring, or post-commissioning surveillance.

**Recommendation: A multi-session test type. 10 sessions = 10 repair stages.**

#### Mapping

```
TestingRequest: "Transformer Repair Lifecycle"
  equipment_type: Power Transformer
  is_multi_session: true
  total_sessions_planned: 10

  Session 1  (Stage 1:  Failure Report)           → Reading: failure details + doc upload
  Session 2  (Stage 2:  Repair Committee)          → Reading: committee minutes upload
  Session 3  (Stage 3:  Allotment to Repairer)     → Reading: repairer name, communication upload
  Session 4  (Stage 4:  Lifting by Repairer)       → Reading: vehicle details, dispatch doc
  Session 5  (Stage 5:  Joint Physical Inspection)  → Reading: inspection report upload
  Session 6  (Stage 6:  Estimate & Work Award)     → Reading: estimate amount, award letter
  Session 7  (Stage 7:  Stage Inspections)          → Reading 1, 2, 3... (multiple sub-inspections)
  Session 8  (Stage 8:  Final Inspection)           → Reading: final report upload
  Session 9  (Stage 9:  Dispatch)                   → Reading: transport details, insurance doc
  Session 10 (Stage 10: Erection & Commissioning)   → Reading: test results, commissioning report
```

#### Delay Tracking Fields (per session template)

```json
{
  "key": "contracted_date",
  "label": "Contracted Completion Date",
  "type": "date",
  "required": true
},
{
  "key": "actual_date",
  "label": "Actual Completion Date",
  "type": "date",
  "required": true
},
{
  "key": "delay_attribution",
  "label": "Delay Attributable To",
  "type": "dropdown",
  "options": ["No Delay", "Vendor", "KPTCL"],
  "required": true
},
{
  "key": "delay_reason",
  "label": "Delay Reason",
  "type": "textarea",
  "required": false
}
```

#### What Already Works

| SRS Requirement | Handled By |
|---|---|
| 10-stage tracking | 10 sessions, each with template fields |
| Document upload per stage | Session reading image attachments |
| Progress % | `completed_sessions / total_sessions_planned × 100` |
| Per-stage timestamps | `session.started_at`, `session.completed_at` |
| Multiple sub-inspections (Stage 7) | Multiple readings per session |
| Comments per stage | `SessionComment` on each session |
| Auto-transition on all stages complete | `AutoStatusTransitionService` |
| Final recommendation | `Recommendation` auto-created |
| Procurement trigger | `ProcurementRequest` from recommendation |

#### Post-Commissioning Surveillance

On Session 10 completion + Recommendation approved with `recommendation_type: "conditional"`:
- Auto-create a new recurring `TestingRequest` for the same equipment
- Test types: DGA + BDV + IR (enhanced monitoring)
- Schedule: monthly for 24 months using existing `TestRequestSchedule`
- Any ALERT/CRITICAL result during surveillance links back to the repair record

#### Repairer Scoring

Aggregate from completed repair lifecycle JSONB data:
- Total vendor-attributed delay days (from `delay_attribution` fields)
- Post-repair test result quality (from `evaluation_result.overall`)
- Re-failure count (new repair lifecycle created for same equipment within surveillance period)

**Impact:** 0 new tables, 0 new code. Just seed 1 new `CategoryDetails` + 1 new `OrgTestTemplate`.

---

### 4.7 Vendor/Repairer Performance Scoring — SRS Section 6.2

**Gap:** Vendor directory exists but no automated performance scoring.

**Recommendation: Computed scoring engine over existing data.**

#### Scoring Dimensions

| Dimension | Data Source |
|---|---|
| Equipment failure rate | `evaluation_result.overall == "CRITICAL"` count per vendor's supplied equipment |
| Repair delay (vendor-attributed) | Repair lifecycle session JSONB: `delay_attribution == "Vendor"` |
| Delivery timeliness | Quote accepted date vs actual delivery (from Zoho sales order) |
| Post-repair test quality | `evaluation_result.overall` for equipment under post-repair surveillance |
| Inspection pass rate | MRN inspection results (Section 4.11) |

#### Model

```python
class VendorScore(Base):
    __tablename__ = "vendor_scores"

    id               = Column(UUID, primary_key=True, default=uuid.uuid4)
    vendor_id        = Column(String(255), nullable=False)
    equipment_type   = Column(String(100), nullable=True)
    evaluation_period = Column(String(20))          # "2026-Q1"
    dimension_scores = Column(JSONB)                 # {failure_rate: 85, delay: 70, delivery: 90, ...}
    composite_score  = Column(Float)
    rank             = Column(Integer)
    cts              = Column(DateTime, server_default=func.now())
```

- Weights configurable by org admin via settings JSONB
- Scheduled job recomputes quarterly
- Historical scores retained for trend comparison

**Impact:** 1 new table (`vendor_scores`)

---

### 4.8 Notification & Alert Engine — SRS Section 8

**Gap:** No centralized email/SMS/in-app notification system.

**Recommendation: Central notification service. Build early — most modules depend on it.**

#### Tables

```python
class NotificationTemplate(Base):
    __tablename__ = "notification_templates"
    id              = Column(UUID, primary_key=True)
    event_type      = Column(String(100), unique=True)    # "test_overdue", "critical_result", etc.
    channel         = Column(String(20))                   # "email", "sms", "in_app"
    subject_template = Column(Text)
    body_template   = Column(Text)
    recipient_roles = Column(JSONB)                        # ["EE TLSS", "SEE W&M"]

class NotificationLog(Base):
    __tablename__ = "notification_log"
    id           = Column(UUID, primary_key=True)
    event_type   = Column(String(100))
    recipient_id = Column(UUID, ForeignKey("users.id"))
    channel      = Column(String(20))
    status       = Column(String(20))                      # queued, sent, failed, retried
    sent_at      = Column(DateTime)
    retry_count  = Column(Integer, default=0)
    cts          = Column(DateTime, server_default=func.now())

class UserNotification(Base):
    __tablename__ = "user_notifications"
    id         = Column(UUID, primary_key=True)
    user_id    = Column(UUID, ForeignKey("users.id"))
    title      = Column(String(255))
    message    = Column(Text)
    is_read    = Column(Boolean, default=False)
    source_type = Column(String(50))                       # "test_result", "recommendation", etc.
    source_id  = Column(UUID)
    cts        = Column(DateTime, server_default=func.now())
```

#### Trigger Points (hook into existing flows)

| Trigger | When |
|---|---|
| `evaluate_result()` returns ALERT/CRITICAL | After test result save |
| `TestRequestSchedule.next_run_date` approaching | 15 days and 7 days before |
| `TestingRequest.due_date` passed | Daily check |
| `Recommendation` approved with `replacement_products` | After approval |
| Equipment replacement recorded | After new UEIC created |
| Maintenance overdue | `request_category = "maintenance"` past due_date |
| TA&QC observation overdue | `request_category = "inspection"` past target date |
| Repair stage delayed | `actual_date > contracted_date` in repair lifecycle session |

#### Features

- Retry: 3 attempts, 5 min apart. Failed → logged as failed.
- Digest mode: batch >10 same-type alerts within 5 min into one message.
- In-app bell icon: badge count from `UserNotification` where `is_read = false`.

**Impact:** 3 new tables (`notification_templates`, `notification_log`, `user_notifications`)

---

### 4.9 Dashboards & KPIs — SRS Section 8.3

**Gap:** No role-specific KPI dashboards.

**Recommendation: API endpoints returning widget data. Build incrementally as modules ship.**

#### Approach

- Each KPI = one GET endpoint returning `{label, value, trend, colour}`
- Cache in Redis (already in use) with 15-min TTL
- Role-based filtering via existing `OrgRole` permissions
- Build one widget per module as it ships — not a big-bang dashboard

#### Priority Widgets

| Widget | Query Source |
|---|---|
| Test compliance % | `completed on time / total due` from `TestingRequest` |
| Overdue count (test/maintenance/inspection) | `request_category` + `due_date < now()` + `status != completed` |
| ALERT/CRITICAL equipment count | `evaluation_result.overall` from `TestResult` |
| Open recommendations pending approval | `Recommendation.approval_status = "pending"` |
| Transformer repair progress by zone | `completed_sessions / total_sessions_planned` for repair lifecycle requests |
| Vendor performance snapshot | Latest `VendorScore.composite_score` top/bottom 5 |

**Impact:** 0 new tables. Query existing data, cache in Redis.

---

### 4.10 Reporting Suite — SRS Section 9

**Gap:** PDF generation exists for individual records but no periodic standard reports or ad-hoc report builder.

**Recommendation: Generic report engine. 14 SRS reports = 14 config rows, not 14 code paths.**

#### Model

```python
class ReportDefinition(Base):
    __tablename__ = "report_definitions"

    id              = Column(UUID, primary_key=True)
    name            = Column(String(255))
    query_key       = Column(String(100))                  # maps to a report query function
    parameters      = Column(JSONB)                        # {date_range, zone, equipment_type, ...}
    output_format   = Column(String(10), default="pdf")    # pdf, excel
    frequency       = Column(String(20), nullable=True)    # monthly, quarterly, annual, on_demand
    recipient_roles = Column(JSONB)
    last_generated  = Column(DateTime, nullable=True)
    is_active       = Column(Boolean, default=True)
    cts             = Column(DateTime, server_default=func.now())
```

#### Approach

- Report service: takes definition → runs query → renders PDF (WeasyPrint) or Excel (openpyxl)
- Scheduling: cron job checks `frequency` + `last_generated` → generates + dispatches via notification engine
- Ad-hoc builder: UI exposes parameters (module, fields, filters, date range). Save as new `ReportDefinition` row.
- 14 SRS standard reports = 14 seed rows

#### SRS Standard Reports

| # | Report | Frequency | Query Source |
|---|--------|-----------|-------------|
| 1 | Equipment Failure Report | Annual | `evaluation_result.overall == "CRITICAL"` grouped by type, make, year |
| 2 | Transformer Repair Status | Monthly/Quarterly/Annual | Repair lifecycle sessions progress |
| 3 | Test Compliance Status | Monthly | `completed on time / total due` |
| 4 | Overdue Test Report | Monthly + on-demand | `due_date < now()` and not completed |
| 5 | ALERT/CRITICAL Equipment | Weekly + on-demand | `evaluation_result.overall` in (ALERT, CRITICAL) |
| 6 | Remedial Action Pending | Monthly + on-demand | `Recommendation.approval_status = "pending"` |
| 7 | Vendor Performance Ranking | Quarterly + Annual | `VendorScore` table |
| 8 | Repairer Performance Ranking | Annual | Repair lifecycle delay aggregation |
| 9 | TA&QC Observation Compliance | Monthly + Annual | `request_category = "inspection"` open/closed |
| 10 | Preventive Maintenance Compliance | Monthly | `request_category = "maintenance"` compliance |
| 11 | Equipment Inventory | On-demand | `Equipment` table grouped by type, substation |
| 12 | Equipment Performance Analysis | On-demand | Test trends + failure rates per UEIC |
| 13 | OLTC/CB Operations Count | Monthly | Counter readings from maintenance results |
| 14 | Post-Repair Evaluation | On surveillance completion | Test trends during surveillance period |

**Impact:** 1 new table (`report_definitions`)

---

### 4.11 Procurement Extensions — SRS Section 10

**Gap:** Core RFQ → Quote → SO → Payment flow exists via Zoho. Missing: item master, formal comparative statement, MRN, inspection, payment advice.

**Recommendation: Extend existing Zoho-integrated flow.**

| Sub-feature | Approach |
|---|---|
| **Item master** | New `ProcurementItem` table with specs, OEM refs. Link to `CategoryDetails` for auto-populate from recommendation `suggested_products`. |
| **Comparative statement** | Auto-generate view from multi-vendor quote data. L1 highlight + deviation column. PDF export. |
| **PO/WO document** | Template-based PDF from accepted quote data. Sequential numbering. |
| **MRN** | New `MaterialReceipt` model linked to PO: qty received, condition, date, receiving officer. |
| **Technical inspection** | Inspection checklist = another `OrgTestTemplate` with `template_category: "procurement_inspection"`. |
| **Payment advice** | Pre-populate from MRN + quote, add deduction fields (advance, LD). Approval workflow. |
| **Vendor delivery tracking** | Dispatch date fields on PO. Vendor portal update endpoint. |
| **Auto-trigger** | CRITICAL evaluation with `suggested_products` → auto-create `ProcurementRequest` pre-populated. |

**Impact:** 2 new tables (`procurement_items`, `material_receipts`)

---

### 4.12 SCADA Integration — SRS Section 13.1

**Gap:** Not implemented.

**Recommendation: Build data model and ingest API now. Protocol adapter later.**

#### Model

```python
class ScadaReading(Base):
    __tablename__ = "scada_readings"

    id           = Column(UUID, primary_key=True, default=uuid.uuid4)
    equipment_id = Column(UUID, ForeignKey("equipment.id"), nullable=False)
    parameter    = Column(String(100))    # "loading_mva", "winding_temp", "oltc_position"
    value        = Column(Float)
    timestamp    = Column(DateTime, nullable=False)
    source       = Column(String(50))     # "scada", "manual", "iot_sensor"
    cts          = Column(DateTime, server_default=func.now())
```

#### Approach

- REST endpoint: `POST /scada/readings` (batch ingest). Decouples from SCADA protocol.
- Evaluation engine queries latest SCADA reading for context (e.g., loading at DGA test time).
- Actual SCADA protocol adapter (IEC 61850/DNP3/OPC-UA) deferred to Phase 4. Middleware translates to REST.

**Impact:** 1 new table (`scada_readings`)

---

### 4.13 AI Readiness — SRS Section 11

**Gap:** AI is Phase 2. Need data architecture readiness only.

**Recommendation: No AI code. Just structured data + export API.**

- JSONB test results with `evaluation_result` + UEIC linkage already create structured time-series data
- Build one data export endpoint: `GET /data-export?ueic=X&parameter=Y&from=&to=` → CSV/JSON
- Data readiness dashboard: count years of data per equipment type, display as % of SRS minimum
- All test results enforce mandatory metadata via template fields: timestamp, ambient conditions, equipment loading, instrument details

**Impact:** 0 new tables. 1 API endpoint.

---

### 4.14 Other Items

| Feature | SRS Section | Approach | Impact |
|---|---|---|---|
| **MFA** | 12 (10.1) | `pyotp` library + SMS gateway. OTP on login for supervisory roles. | Config change |
| **Audit log** | 12 (10.1) | `AuditLog` table. Middleware captures all write ops. Immutable (no UPDATE/DELETE). | 1 new table |
| **Data correction workflow** | 12 (10.2) | When locked result needs editing: `CorrectionRequest` → reviewer approves → single edit → re-lock. Same approval pattern. | Part of existing workflow |
| **Offline mode** | 2.4 | PWA service worker for test result entry. IndexedDB draft queue. Sync on reconnect. Scope: test/maintenance entry only. | Frontend only |
| **Bulk Excel import** | 13.3 | Upload Excel → validate against schema → preview errors → confirm → batch insert. openpyxl. | 1 utility service |
| **Kannada labels** | 2.5 | `field_labels` JSONB locale overrides on templates. Frontend checks locale and shows Kannada if available. | JSONB extension |
| **Relay calibration** | 5.3 | Test type under Protection Relay. Same template + testing request flow. | Seed data only |
| **ETV meter calibration** | 5.4 | Test type under ETV Meter. Same template + testing request flow. | Seed data only |

---

## 5. Total Build Impact

| Category | Count |
|---|---|
| **New database tables** | 9 |
| **New columns on existing tables** | 3 |
| **New workflow engines** | 0 |
| **New template seed data** | Maintenance checklists, TA&QC observations, transformer repair lifecycle, nameplate templates, procurement inspection |

### New Tables Summary

| # | Table | Purpose |
|---|-------|---------|
| 1 | `equipment` | Asset register with UEIC, nameplate JSONB, linked to OrgDepartment |
| 2 | `vendor_scores` | Computed vendor performance scores |
| 3 | `notification_templates` | Event-type → channel → recipients mapping |
| 4 | `notification_log` | Delivery tracking with retry |
| 5 | `user_notifications` | In-app bell icon notifications |
| 6 | `report_definitions` | Generic report engine config |
| 7 | `procurement_items` | Item master with specs and OEM refs |
| 8 | `material_receipts` | MRN linked to PO |
| 9 | `scada_readings` | Time-series equipment readings |

### New Columns Summary

| # | Table | Column | Type |
|---|-------|--------|------|
| 1 | `testing_requests` | `equipment_id` | UUID FK → equipment |
| 2 | `testing_requests` | `request_category` | String: test / maintenance / inspection |
| 3 | `test_results` | `evaluation_result` | JSONB |

---

## 6. Recommended Build Order

| Phase | What | Why | New Tables |
|---|---|---|---|
| **Phase 1** | Equipment model + UEIC + link to OrgDepartment + audit log | Everything references equipment | 2 (equipment, audit_log) |
| **Phase 2** | Template evaluation criteria + `evaluation_result` on TestResult | Transforms data into actionable intelligence | 0 |
| **Phase 3** | Notification engine | Most features need alerts | 3 (notification_templates, notification_log, user_notifications) |
| **Phase 4** | `request_category` flag + maintenance/TA&QC templates | Unlocks 2 SRS modules with 1 column | 0 |
| **Phase 5** | Transformer repair lifecycle template | Zero code — just seed data | 0 |
| **Phase 6** | Vendor scoring service | Needs data from Phases 2–5 | 1 (vendor_scores) |
| **Phase 7** | Report engine + 14 report definitions | Needs data from all modules | 1 (report_definitions) |
| **Phase 8** | Procurement extensions (item master, MRN) | Formalises existing Zoho flow | 2 (procurement_items, material_receipts) |
| **Phase 9** | SCADA data model + ingest endpoint | Integration — defer protocol adapter | 1 (scada_readings) |
| **Phase 10** | MFA, offline mode, bulk import, Kannada labels | Polish and compliance | 0 |

---

## 7. SRS Gaps That Remain in the Document (Require KPTCL Clarification)

These are issues in the SRS text itself that should be raised with KPTCL regardless of implementation:

### Regulatory/Compliance

| # | Gap |
|---|-----|
| 1 | **No GeM compliance.** Government e-Marketplace is mandatory for Indian government procurement above threshold values. |
| 2 | **No tender type classification.** Open/limited/single-source tender have different GFR requirements. |
| 3 | **No GST e-invoicing.** IRP verification required under Indian GST regime. |
| 4 | **No EMD/bank guarantee tracking.** Standard in government procurement. |
| 5 | **No liquidated damages formula.** Mentioned in PO template but no rate/cap specified. |
| 6 | **No WCAG accessibility compliance.** Increasingly required for government systems. |

### Operational

| # | Gap |
|---|-----|
| 7 | **No delegate/proxy approvals.** When officer is on leave, no temporary delegation workflow. |
| 8 | **No public holiday calendar.** "First working day of month" has no definition of working days. |
| 9 | **No alert batching spec.** Bulk uploads could trigger hundreds of individual SMS. |
| 10 | **No SCADA protocol specified.** IEC 61850? DNP3? Modbus? OPC-UA? |
| 11 | **No offline mode detail.** One mention in Section 2.4, never specified. |
| 12 | **Performance inconsistency.** Page load tested at 100 users but system must support 500. |
| 13 | **Phase 6 AI timeline.** Says "Month 6" but Section 11 requires 3–5 years of historical data first. |

### Ambiguities

| # | Ambiguity |
|---|-----------|
| 14 | "Designated Officer" used 20+ times without mapping to specific roles from Section 2.3. |
| 15 | "Abnormal observation" in maintenance checklists has no threshold definition. |
| 16 | OLTC "operation" undefined — one tap change or a raise+lower sequence? |
| 17 | "Digital authentication via user login" — session action or legally-valid digital signature? |
| 18 | Emergency urgency "<30 days" — delivery needed in <30 days, or requirement arose <30 days before needed? |

---

## 8. Architecture Principle

**One workflow engine. Multiple categories.**

```
                    ┌── test (condition monitoring, healthiness tests)
TestingRequest ─────┼── maintenance (routine, preventive, major maintenance)
  + OrgTestTemplate ├── inspection (TA&QC observations, compliance)
  + Multi-session   └── repair_lifecycle (transformer repair 10-stage)
  + Evaluation
  + Recommendation
  + Procurement
```

Every SRS module maps to a `request_category` + a `template_key`. The workflow engine (create → assign → execute → evaluate → recommend → approve → procure) stays the same. Templates define the data shape. Evaluation criteria live inside the templates. No parallel systems.

---

*End of Document*
