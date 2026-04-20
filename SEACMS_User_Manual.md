# SEACMS-AI User Manual
### Smart Equipment Asset & Compliance Management System — AI Edition
**Karnataka Power Transmission Corporation Limited (KPTCL)**
Version 1.3 · April 2026

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [SRS Designation Roles](#2-srs-designation-roles)
3. [KPTCL User Credentials](#3-kptcl-user-credentials)
4. [Equipment Inventory](#4-equipment-inventory)
5. [Test Request Categories](#5-test-request-categories)
6. [End-to-End Workflow](#6-end-to-end-workflow)
7. [Template System](#7-template-system)
8. [Template Rule Evaluation Engine](#8-template-rule-evaluation-engine)
9. [Template Evaluation Scenarios](#9-template-evaluation-scenarios)
10. [Scheduling — Recurring Requests](#10-scheduling--recurring-requests)
11. [Multi-Session Testing](#11-multi-session-testing)
12. [Scenario: CVT Dielectric Test (Single Session)](#12-scenario-cvt-dielectric-test-single-session)
13. [Scenario: Power Transformer Maintenance (Scheduled + Recurring)](#13-scenario-power-transformer-maintenance-scheduled--recurring)
14. [Scenario: Substation Inspection (Multi-Day, Multi-Session)](#14-scenario-substation-inspection-multi-day-multi-session)
15. [Scenario: Circuit Breaker Repair Lifecycle (Multi-Session, 10 Stages)](#15-scenario-circuit-breaker-repair-lifecycle-multi-session-10-stages)
16. [Dashboards & KPI Cards](#16-dashboards--kpi-cards)
17. [Notifications](#17-notifications)
18. [Reports (14 Built-In)](#18-reports-14-built-in)
19. [Org Admin Tasks](#19-org-admin-tasks)
20. [Quick Reference](#20-quick-reference)

---

## 1. System Overview

SEACMS-AI is a web-based platform used by KPTCL to manage the full lifecycle of equipment testing, maintenance, inspection, and repair across transmission substations. It replaces paper-based processes with structured digital workflows, role-based access, automated scheduling, and AI-assisted analysis.

**Core capabilities:**
- Raise and track test requests from field to approval
- Assign the right tester role for each job
- Fill structured digital test templates (replaces forms & registers)
- Schedule recurring maintenance automatically
- Run multi-session/multi-day tests (e.g., 10-stage repair lifecycle)
- Generate 14 built-in operational reports (Excel / PDF)
- Full audit trail: who did what and when

**Technology stack (for reference):**
- Backend: FastAPI + PostgreSQL
- Frontend: Flutter (web + Android)
- AI features: recommendation engine, workload balancing

---

## 2. SRS Designation Roles

SEACMS-AI v1.3 defines seven official designation roles per SRS Section 2.3 plus supporting system roles. Each role maps to a specific KPTCL designation.

### 2.1 SRS Designation Roles

| # | Role Name | Full Designation | Level | Key Responsibilities |
|---|-----------|-----------------|-------|---------------------|
| 1 | **AEE Maintenance** | Assistant Executive Engineer – Maintenance | Field Supervisor | Raises test requests from the field; records findings; views dashboards and reports |
| 2 | **EE TLSS** | Executive Engineer – Transmission Line & Substation | Division Primary Reviewer | Reviews requests, assigns testers, runs test sessions, manages equipment register; accesses procurement/quote workflow |
| 3 | **SEE W&M** | Superintending Engineer – Works & Maintenance | Circle Supervisor | Approves/assigns requests at circle level; approves quotes; accesses vendor directory |
| 4 | **EE RT** | Executive Engineer – Research & Testing | R&T Division | Runs and edits tests; manages test templates; full equipment add/edit |
| 5 | **SEE RT** | Superintending Engineer – Research & Testing | Senior R&T | Approves test results; edits templates; views vendor directory |
| 6 | **CEE Transmission Zone** | Chief Engineer – Transmission Zone | Zonal Management | Approves requests and quotes at zone level; executive-level dashboard; read-only on all modules |
| 7 | **CEE RT&R&D** | Chief Engineer – Research, Testing & R&D | R&D Chief | Full control over test templates; add/edit equipment; high-level reporting |

### 2.2 Supporting System Roles

| Role | Purpose | Notes |
|------|---------|-------|
| **Org Admin** | Manages users, roles, departments; system configuration | One per organisation |
| **Field Tester** | Performs on-site testing; records readings | Assigned by EE TLSS / AEE Maintenance |
| **Lab Tester** | Performs lab-based testing | Assigned by EE RT |
| **SuperAdmin** | Manages all organisations | Relu/platform team only |

### 2.3 Module Permissions by SRS Role

| Module | AEE Maintenance | EE TLSS | SEE W&M | EE RT | SEE RT | CEE Zone | CEE RT&R&D |
|--------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| Dashboard | View | View+Edit | View | View | View | View+Edit | View |
| EE TLSS Dashboard | — | View | View | — | — | View | — |
| Testing Requests | View+Add+Edit+Approve | View+Add+Edit | View+Approve+Assign | View+Add+Approve+Assign | View+Approve+Assign | View+Approve+Assign | View+Approve+Assign |
| Testing Request Approvals | View+Approve | View+Approve+Assign | View+Approve | View+Approve | View+Approve | View+Approve | View |
| Testing (Sessions) | View+Add | View+Add+Edit | View | View+Add+Edit | View | View | View |
| Equipment Register | View+Search | View+Add+Edit+Search | View+Search | View+Add+Edit+Search | View+Search | View+Search | View+Add+Edit+Search |
| Test Template Mgmt | — | — | — | View+Edit | View+Edit | — | Full (Add/Edit/Delete) |
| Reports | View+Export | View+Export | View+Export | View+Export | View+Export | View+Export | View+Export |
| Notifications | View | View | View | — | — | View | — |
| Request Quote | — | View | View+Add | — | — | View+Approve | — |
| Quotes | — | View | View+Approve | — | — | View+Approve | — |
| Sales Orders | — | View | — | — | — | View | — |
| Vendor Directory | — | — | View | — | View | View | View |

---

## 3. KPTCL User Credentials

> **Default password for all SRS designation users:** `admin123`

| Role | Email | Employee ID | Password |
|------|-------|-------------|----------|
| Org Admin | `kptcl.admin@kptcl.com` | KPTCL-ADMIN-001 | `admin123` |
| AEE Maintenance | `aee.maintenance@kptcl.com` | KPTCL-AEE-M-001 | `admin123` |
| EE TLSS | `ee.tlss@kptcl.com` | KPTCL-EE-TLSS-001 | `admin123` |
| SEE W&M | `see.wm@kptcl.com` | KPTCL-SEE-WM-001 | `admin123` |
| EE RT | `ee.rt@kptcl.com` | KPTCL-EE-RT-001 | `admin123` |
| SEE RT | `see.rt@kptcl.com` | KPTCL-SEE-RT-001 | `admin123` |
| CEE Transmission Zone | `cee.zone@kptcl.com` | KPTCL-CEE-TZ-001 | `admin123` |
| CEE RT&R&D | `cee.rtrd@kptcl.com` | KPTCL-CEE-RTRD-001 | `admin123` |
| Field Tester | `field.tester@kptcl.com` | KPTCL-FT-001 | `Tester123!` |
| Lab Tester | `lab.tester@kptcl.com` | KPTCL-LT-001 | `Tester123!` |
| Doc Viewer | `doc.viewer@kptcl.com` | KPTCL-DOC-001 | `admin123` |

---

## 4. Equipment Inventory

Equipment is registered in the **Equipment Register** (UEIC auto-generated unique code). Each equipment type maps to allowed test types per category.

### 4.1 Equipment Types & Test Mapping

#### Power Transformer

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Power Transformer Nameplate Details, Transformer Physical Inspection, Ratio Test HV-IV, Ratio Test HV-LV, Short Circuit Test HV-IV, Short Circuit Test HV-LV, Magnetic Balance Test HV, Magnetic Balance Test IV, Magnetic Balance Test LV, Open Circuit Test HV-IV (1Ph), Open Circuit Test HV-IV (3Ph), Open Circuit Test HV-LV (1Ph), Open Circuit Test HV-LV (3Ph), Open Circuit Test IV-LV (1Ph), Open Circuit Test IV-LV (3Ph), Capacitance & Tan Delta Test (Transformer), Capacitance & Tan Delta Comparison |
| **maintenance** | Routine Preventive Maintenance, Power Transformer Major Maintenance |
| **inspection** | Electrical Safety, Civil, Fire Safety, Documentation, Environmental, General Maintenance |
| **repair_lifecycle** | S1: Failure Report, S2: Repair Committee, S3: Allotment to Repairer, S4: Lifting by Repairer, S5: Joint Inspection at Vendor, S6: Estimate & Revised Work Award, S7: Stage Inspections, S8: Final Inspection, S9: Dispatch, S10: Erection Testing & Commissioning |

#### Circuit Breaker

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Contact Resistance Test, Insulation Resistance Test, SF6 Gas Pressure Test, SF6 Gas Purity Test, Travel and Timing Test, Minimum Trip Voltage Test |
| **maintenance** | Routine Preventive Maintenance, Circuit Breaker Major Maintenance |
| **inspection** | Electrical Safety, Civil, Fire Safety, Documentation, Environmental, General Maintenance |
| **repair_lifecycle** | S1: Failure Report, S2: Repair Committee, S3: Allotment to Repairer, S4: Lifting by Repairer, S5: Joint Inspection at Vendor, S6: Estimate & Revised Work Award, S7: Stage Inspections, S8: Final Inspection, S9: Dispatch, S10: Erection Testing & Commissioning |

#### Current Transformer (CT)

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Insulation Resistance (IR) Test, CT Ratio Test, Core Insulation Test, CT Insulation Test, CT Ratio Test (Detailed), Capacitance & Tan Delta Test (CT), Tan Delta NCT Test |

#### Capacitor Voltage Transformer (CVT)

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | CVT Test Report |

#### Feeder Protection Relay

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Relay Testing Report |

#### Protection Relay (General)

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Protection Relay Functional Test |

#### Transformer Differential Relay

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Stability / Bias Test |

#### Relay

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Relay Testing |

#### Meter

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Meter Testing |

#### Feeder Metering

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Energy Meter Accuracy Test |

#### Protection System

| Category | Available Test / Work Types |
|----------|----------------------------|
| **test** | Transformer Protection Commissioning |

### 4.2 Equipment Register Fields

When registering equipment in the system (**Equipment → Add New**):

| Field | Description |
|-------|-------------|
| Equipment Name | Descriptive name (e.g., "220kV Power Transformer – Bay 3") |
| UEIC | Auto-generated Unique Equipment Identification Code |
| Equipment Type | Select from list above |
| Manufacturer | Brand / OEM |
| Model / Serial No. | For traceability |
| Rating / Capacity | e.g., 100 MVA, 220/132 kV |
| Installation Date | Commissioning date |
| Location | Substation / Bay / Panel |
| Department | Linked org department |
| Status | Active / Under Maintenance / Decommissioned |
| Last Test Date | Auto-updated on test completion |
| Next Due Date | Auto-calculated from schedule |

---

## 5. Test Request Categories

Each test request belongs to one of four categories. Category selection determines which template is loaded and which workflow stages apply.

| Category | Value | Description | Multi-Session? | Typical Duration |
|----------|-------|-------------|:-:|:---:|
| **Test** | `test` | Routine or scheduled equipment testing (electrical / functional) | No | Hours to 1 day |
| **Maintenance** | `maintenance` | Preventive / corrective maintenance work | Optional | 1–3 days |
| **Inspection** | `inspection` | Site or equipment safety inspections | Optional (multi-day sites) | Half day to 2 days |
| **Repair Lifecycle** | `repair_lifecycle` | Full 10-stage repair and reinstatement process | **Yes (mandatory)** | Weeks to months |

---

## 6. End-to-End Workflow

### 6.1 Request Status Lifecycle

```
draft → submitted → pending_approval → assigned → accepted
      → scheduled → in_progress → test_submitted → under_approval
      → approved / rejected
      → procurement_initiated → completed
```

### 6.2 Stage-by-Stage Actions by Role

| Stage | Status | Who Acts | UI Action |
|-------|--------|----------|-----------|
| 1 · Create Request | `draft` | AEE Maintenance / EE TLSS / EE RT | Testing Requests → **New Request** → fill equipment, category, type, due date → **Submit** |
| 2 · Review & Approve | `pending_approval` | EE TLSS / SEE W&M / SEE RT | Testing Request Approvals → open request → review → **Approve & Assign Tester** |
| 3 · Tester Accepts | `assigned` → `accepted` | Field Tester / Lab Tester | My Assignments → open → **Accept** |
| 4 · Schedule Date | `accepted` → `scheduled` | Field Tester / EE TLSS | Open request → **Set Schedule Date** → confirm |
| 5 · Conduct Test | `scheduled` → `in_progress` | Field Tester / Lab Tester | Open request → **Start Test** → fill template form → **Save Readings** |
| 6 · Submit Results | `in_progress` → `test_submitted` | Field Tester / Lab Tester | Open request → **Submit Test Results** → add recommendation |
| 7 · Second Approval | `test_submitted` → `under_approval` | SEE W&M / SEE RT / CEE Zone | Testing Request Approvals → review results → **Approve** or **Reject** |
| 8 · Complete | `under_approval` → `approved` → `completed` | System / Org Admin | Auto-transition on final approval; report generated |

### 6.3 Repair Lifecycle Variant

For `repair_lifecycle`, Stage 5 runs 10 times (S1–S10). Each stage is a separate session. The request stays `in_progress` until all 10 sessions are marked **completed**.

---

## 7. Template System

### 7.1 How Templates Are Selected

When a tester opens a request and clicks **Start Test**, the system auto-loads the template based on this priority order:

```
1. Org-specific override (configured by Org Admin or CEE RT&R&D)
   ↓ if not found
2. Global default for the test type (seeded from SRS)
   ↓ if not found
3. Fallback: blank form (manual entry)
```

### 7.2 Built-In Templates

| Template Key | Used For | Multi-Session |
|---|---|:-:|
| `relay_testing_report` | Feeder Protection Relay – Test | No |
| `differential_protection_test` | Power Transformer – Differential Test | No |
| `stability_bias_test` | Transformer Differential Relay | No |
| `protection_relay_functional_test` | Protection Relays | No |
| `dielectric_test_report` | CT / CVT Dielectric Testing | No |
| `ct_ratio_test` | Current Transformer Ratio | No |
| `cvt_test_report` | CVT Testing | No |
| `breaker_maintenance` | Circuit Breaker Maintenance | **Yes** |
| `transformer_maintenance` | Power Transformer Maintenance | **Yes** |
| `substation_inspection` | Substation Inspection | No |
| `equipment_inspection` | General Equipment Inspection | No |
| `transformer_repair_lifecycle` | Repair Lifecycle (all 10 stages) | **Yes** |
| `overall_assessment` | Auto-appended to every form | — |

### 7.3 Template Field Types

| Field Type | Description | Example |
|---|---|---|
| `text` | Free-text entry | Manufacturer name, remarks |
| `number` | Numeric value with unit | Insulation resistance (MΩ) |
| `dropdown` | Select from predefined list | Pass / Fail / Conditional |
| `boolean` | Yes / No toggle | Earthing provided? |
| `checkbox` | Multi-select checklist | Safety checks completed |
| `textarea` | Long text / observations | Detailed findings |
| `date` | Date picker | Test conducted date |
| `table` | Multi-row data grid | Ratio test readings per tap |

### 7.4 Customising Templates (CEE RT&R&D / EE RT)

1. Navigate to **Test Template Management**
2. Select the template to edit
3. Add / remove / reorder fields
4. Set field-level validation (min, max, required)
5. **Save** — changes apply to all new requests immediately
6. Org Admin can create org-specific overrides without touching global templates

---

## 8. Template Rule Evaluation Engine

When a tester submits a completed test form, SEACMS-AI automatically evaluates every field that has evaluation rules defined. The result appears as a coloured badge on the request and drives the auto-generated recommendation.

### 8.1 Status Hierarchy

```
NORMAL  (green)   — values within acceptable range
  ↓
ALERT   (amber)   — degraded but not immediately dangerous
  ↓
CRITICAL (red)    — action required; remedial recommendation auto-generated
```

The **overall status** of the entire test result is the highest severity found across all evaluated fields. One CRITICAL field turns the whole result CRITICAL.

### 8.2 Four Evaluation Rule Types

#### Type 1 — NUMBER field

Applies threshold bands to a single numeric measurement.

```json
"evaluation": {
  "enabled": true,
  "normal_min": 1000,
  "normal_max": null,
  "alert_min": 100,
  "alert_max": null,
  "critical_below": 50,
  "critical_above": null,
  "trend_watch": true,
  "revised_interval_days": 90,
  "remedial_action_text": "Immediate drying-out treatment required",
  "suggested_products": ["Insulation drying equipment"]
}
```

**Decision logic (priority order):**

| Check | Condition | Status |
|-------|-----------|--------|
| 1st | value < `critical_below` OR value > `critical_above` | **CRITICAL** |
| 2nd | value < `alert_min` OR value > `alert_max` | **ALERT** |
| 3rd | value < `normal_min` OR value > `normal_max` | **ALERT** |
| 4th | all within normal | **NORMAL** |

**Extra ALERT behaviour:**
- If `trend_watch: true` — field is flagged for historical trending on the dashboard
- If `revised_interval_days` set — system shortens the next scheduled test interval to this value (e.g., 90 days instead of the standard 365)

---

#### Type 2 — TABLE field

A table collects multiple rows of measurements. Two independent sub-rules run on each table field.

**Sub-rule A — Aggregate rule** (whole-table aggregate vs. one threshold):

```json
"table_evaluation": {
  "enabled": true,
  "aggregate_type": "average",
  "aggregate_column": "tan_delta",
  "aggregate_threshold": 0.5,
  "threshold_condition": "gte",
  "remedial_action_text": "Tan delta exceeds 0.5% — schedule capacitor replacement",
  "suggested_products": ["Capacitor stack replacement kit"]
}
```

Aggregate functions available:

| `aggregate_type` | Computes |
|-----------------|---------|
| `sum` | Total of all values in the column |
| `average` | Mean of all values in the column |
| `count` | Number of non-null rows in the column |
| `max` | Highest value in the column |
| `min` | Lowest value in the column |

Threshold conditions:

| `threshold_condition` | Triggers CRITICAL when |
|----------------------|----------------------|
| `gte` | aggregate ≥ threshold |
| `gt` | aggregate > threshold |
| `lte` | aggregate ≤ threshold |
| `lt` | aggregate < threshold |

**Sub-rule B — Per-column row evaluation** (each cell vs. numeric bands):

```json
"column_evaluations": {
  "pickup_current": {
    "normal_min": 4.8,
    "normal_max": 5.2,
    "alert_min": 4.5,
    "critical_below": 4.0
  },
  "error_percent": {
    "critical_above": 5.0,
    "alert_max": 3.0
  }
}
```

Every row × column combination is checked. If any single cell breaches CRITICAL, the table field status becomes CRITICAL (even if the aggregate is NORMAL).

**Overall table field status = worst status across both sub-rules.**

---

#### Type 3 — DROPDOWN / RADIO field

Maps each selectable option directly to a severity level.

```json
"dropdown_evaluation": {
  "enabled": true,
  "value_severities": {
    "Good":   "NORMAL",
    "Fair":   "ALERT",
    "Poor":   "CRITICAL",
    "Failed": "CRITICAL"
  },
  "remedial_action_text": "Equipment condition critical — initiate repair lifecycle"
}
```

The tester picks a value from the dropdown; the system immediately resolves the severity from the mapping. Any value not listed defaults to NORMAL.

---

#### Type 4 — DATE field

Evaluates whether a date (e.g., next calibration due, oil sample date) is approaching or overdue.

```json
"date_evaluation": {
  "enabled": true,
  "warning_days_before": 30,
  "alert_days_before": 15,
  "critical_when_overdue": true,
  "remedial_action_text": "Calibration certificate expired — test results invalid"
}
```

| Days Until Date | Status |
|----------------|--------|
| > `warning_days_before` | NORMAL |
| ≤ `warning_days_before` | ALERT |
| ≤ `alert_days_before` | ALERT |
| Past (negative) + `critical_when_overdue: true` | CRITICAL |

---

### 8.3 Evaluation Output Structure

After submission the system returns (and stores in `evaluation_result` JSONB column):

```json
{
  "overall": "CRITICAL",
  "evaluated_at": "2026-04-20T10:32:00Z",
  "fields": [
    {
      "key": "ir_hv_to_earth_mohm",
      "label": "IR — HV to Earth",
      "type": "number",
      "value": 42.0,
      "unit": "MOhm",
      "status": "CRITICAL",
      "thresholds": {
        "normal_min": 1000,
        "critical_below": 50
      },
      "trend_watch": true,
      "remedial_action_text": "Immediate drying-out required",
      "suggested_products": ["Insulation drying equipment"],
      "revised_interval_days": 90
    },
    {
      "key": "tan_delta_readings",
      "label": "Tan Delta Table",
      "type": "table",
      "status": "ALERT",
      "aggregate_result": {
        "aggregate_type": "average",
        "column": "tan_delta",
        "value": 0.38,
        "threshold": 0.5,
        "condition": "gte",
        "threshold_met": false
      },
      "column_results": [
        {"column": "tan_delta", "row": 2, "value": 0.48, "status": "ALERT"}
      ]
    }
  ]
}
```

### 8.4 What Happens After Evaluation

| Outcome | System Action |
|---------|--------------|
| Any CRITICAL field | Auto-generates recommendation text from `remedial_action_text` |
| Any ALERT field | Flags field in UI with amber highlight; shows remedial text on hover |
| Suggested products | Added to the procurement suggestion list on the request |
| `revised_interval_days` set (ALERT) | Next scheduled test date shortened to the minimum revised interval |
| `trend_watch: true` | Field value stored in trending history; appears in dashboard trend chart |
| CRITICAL overall | Dashboard KPI "Critical Alerts" counter incremented; notification sent to EE TLSS and SEE W&M |

### 8.5 How Evaluation Appears in the UI

After the tester submits the test:

1. **Result badge** on request card — green `NORMAL` / amber `ALERT` / red `CRITICAL`
2. **Field-level highlight** inside the filled form — each evaluated field shows its status colour
3. **Evaluation Summary panel** — collapsible, shows all evaluated fields with their values, thresholds, and status
4. **Auto-recommendation** — pre-filled in the recommendation box, tester can edit before final submission
5. **Suggested products** — shown as a clickable list; clicking "Raise Procurement" starts a new procurement request pre-filled with those items

---

## 9. Template Evaluation Scenarios

### Scenario A — CT Ratio Test: Table Per-Column Rule (CRITICAL)

**Template:** `ct_ratio_test`
**Table field:** `ratio_readings`
**Columns:** primary_current, secondary_current, measured_ratio, error_percent, row_result

**Evaluation rule on `error_percent` column:**
```json
"column_evaluations": {
  "error_percent": {
    "critical_above": 5.0,
    "alert_max": 3.0,
    "normal_max": 1.0
  }
}
```

**Tester enters these readings:**

| Row | Primary (A) | Secondary (A) | Measured Ratio | Error (%) | Row Result |
|-----|------------|---------------|----------------|-----------|------------|
| 1 | 200 | 1.00 | 200.0 | 0.0 | Pass |
| 2 | 100 | 0.50 | 200.0 | 0.5 | Pass |
| 3 | 50 | 0.26 | 192.3 | **6.2** | Fail |

**Evaluation result:**

- Row 1: error_percent = 0.0 → NORMAL
- Row 2: error_percent = 0.5 → NORMAL
- Row 3: error_percent = 6.2 → **CRITICAL** (> `critical_above: 5.0`)
- Table field overall → **CRITICAL**
- Overall test result → **CRITICAL**

**UI outcome:**
- Row 3 highlighted red in the table
- Auto-recommendation: _"[CT Ratio Error] Ratio error exceeds 5% — CT winding may be damaged. Schedule replacement."_
- EE TLSS receives CRITICAL alert notification

---

### Scenario B — CVT Tan Delta Test: Aggregate Average Rule (ALERT)

**Template:** `cvt_test_report`
**Table field:** `tan_delta_readings`
**Aggregate rule:**
```json
"table_evaluation": {
  "enabled": true,
  "aggregate_type": "average",
  "aggregate_column": "tan_delta_percent",
  "aggregate_threshold": 0.5,
  "threshold_condition": "gte",
  "remedial_action_text": "Average tan delta ≥ 0.5% — plan capacitor stack replacement within 6 months"
}
```

**Tester enters:**

| Measurement Point | C1 (pF) | Tan Delta (%) |
|-------------------|---------|---------------|
| HV to Ground | 12500 | 0.35 |
| Stack 1 | 6200 | 0.42 |
| Stack 2 | 6250 | 0.48 |
| Neutral | 6180 | 0.38 |

**Evaluation:**
- Average tan_delta = (0.35 + 0.42 + 0.48 + 0.38) / 4 = **0.4075**
- 0.4075 < 0.5 → threshold NOT met → aggregate status = **NORMAL**

*(No aggregate CRITICAL. But if Stack 2 had been 0.52:)*
- Average = (0.35 + 0.42 + 0.52 + 0.38) / 4 = **0.4675** — still NORMAL
- Average = (0.55 + 0.62 + 0.68 + 0.59) / 4 = **0.61** → **CRITICAL** (≥ 0.5)

**UI outcome (NORMAL case):** Green badge. No auto-recommendation. Tester still enters manual overall result.

**UI outcome (CRITICAL case):** Red badge. Auto-recommendation: _"Average tan delta ≥ 0.5% — plan capacitor stack replacement."_ Suggested product added to procurement list.

---

### Scenario C — Transformer Differential Test: Dropdown Rule (CRITICAL)

**Template:** `differential_protection_test`
**Field:** `stability_result` (dropdown)
**Evaluation rule:**
```json
"dropdown_evaluation": {
  "enabled": true,
  "value_severities": {
    "Stable (No Trip)": "NORMAL",
    "Unstable (Tripped)": "CRITICAL"
  },
  "remedial_action_text": "Relay operated during through-fault — protection coordination review required"
}
```

**Tester selects:** `Unstable (Tripped)`

**Evaluation result:**
- Value → `Unstable (Tripped)` → **CRITICAL**
- Auto-recommendation: _"[Stability Test Result] Relay operated during through-fault — protection coordination review required"_

**UI outcome:** Entire request flagged CRITICAL immediately on dropdown selection (live feedback). EE TLSS and SEE W&M notified.

---

### Scenario D — Protection Relay: Number Rule + Trend Watch (ALERT)

**Template:** `protection_relay_functional_test`
**Field:** `pickup_current` (number, unit: A)
**Evaluation rule:**
```json
"evaluation": {
  "enabled": true,
  "normal_min": 4.8,
  "normal_max": 5.2,
  "alert_min": 4.5,
  "alert_max": 5.5,
  "critical_below": 4.0,
  "critical_above": 6.0,
  "trend_watch": true,
  "revised_interval_days": 90,
  "remedial_action_text": "Pickup current drifted — relay calibration required"
}
```

**Tester measures:** `4.6 A`

**Decision walk-through:**
1. Is 4.6 < `critical_below` (4.0)? → No
2. Is 4.6 > `critical_above` (6.0)? → No
3. Is 4.6 < `alert_min` (4.5)? → No
4. Is 4.6 < `normal_min` (4.8)? → **Yes** → **ALERT**

**UI outcome:**
- Field highlighted amber
- Remedial text shown: _"Pickup current drifted — relay calibration required"_
- Next test schedule compressed to 90 days (instead of normal annual interval)
- Value stored in trend history — dashboard shows drift chart over time

---

### Scenario E — Instrument Calibration: Date Rule (CRITICAL)

**Template:** Any (field added by org admin)
**Field:** `megger_calibration_due` (date)
**Evaluation rule:**
```json
"date_evaluation": {
  "enabled": true,
  "warning_days_before": 30,
  "alert_days_before": 15,
  "critical_when_overdue": true,
  "remedial_action_text": "Test instrument calibration certificate expired — results not valid"
}
```

**Test conducted on:** 2026-04-20
**Calibration due date entered by tester:** `2026-04-10` (10 days ago)

**Days until:** -10 (overdue)
- `critical_when_overdue: true` → **CRITICAL**

**UI outcome:**
- Field highlighted red
- Warning banner shown: _"Calibration certificate expired — test results may be invalid"_
- Request cannot be approved until tester provides explanation or updated certificate

---

### Scenario F — Substation Inspection: Combined Evaluation (Multi-Field)

**Template:** `substation_inspection`
**Three evaluated fields:**

| Field | Type | Rule | Entered Value | Status |
|-------|------|------|---------------|--------|
| `earthing_resistance` | number | critical_above: 1.0 Ω | 0.8 Ω | NORMAL |
| `overall_condition` | dropdown | Poor → CRITICAL, Fair → ALERT | `Fair` | **ALERT** |
| `last_maintenance_date` | date | critical_when_overdue, alert_before 30d | 2 months ago | **CRITICAL** |

**Evaluation result:**
- Field 1: NORMAL
- Field 2: ALERT
- Field 3: CRITICAL
- **Overall: CRITICAL** (highest wins)

**Auto-recommendation built from CRITICAL fields only:**
> `[AUTO-EVAL CRITICAL] Substation Inspection — [Last Maintenance Date] Maintenance overdue — immediate scheduling required`

**Suggested products from ALERT fields also appended** to procurement list.

---

### 9.1 Evaluation Scenario Summary Table

| Scenario | Equipment | Rule Type | Trigger | Outcome |
|----------|-----------|-----------|---------|---------|
| A — CT Ratio Error | Current Transformer | Table per-column | error_percent row > 5% | CRITICAL, auto-recommendation |
| B — CVT Tan Delta | CVT | Table aggregate average | avg tan delta ≥ 0.5% | CRITICAL, procurement suggestion |
| C — Differential Stability | Power Transformer | Dropdown severity map | Unstable (Tripped) selected | CRITICAL, immediate notification |
| D — Relay Pickup Drift | Protection Relay | Number threshold + trend | 4.6A < normal_min 4.8A | ALERT, 90-day revised interval, trend chart |
| E — Calibration Expired | Any equipment | Date overdue | certificate date in past | CRITICAL, approval blocked |
| F — Substation Inspection | Substation | Multi-field combined | one date overdue | CRITICAL (highest wins) |

---

## 10. Scheduling — Recurring Requests

The **Schedule** feature lets a test request automatically repeat at a fixed frequency, creating a new child request before the due date arrives.

### 10.1 How to Enable a Schedule

**Who can do this:** AEE Maintenance, EE TLSS, EE RT (roles with `can_add` on Testing Requests)

1. Open a **completed** or **approved** test request
2. Click **Enable Schedule** (top-right action menu)
3. Fill the schedule form:

| Field | Description | Example |
|-------|-------------|---------|
| Frequency | How often to repeat | Monthly |
| Start Date | First repetition date (defaults to original due date) | 2026-05-01 |
| End Date | Optional — stop repeating after this date | 2027-04-30 |
| Advance Days | How many days before due date to auto-create the new request | 7 |

4. Click **Save Schedule**
5. The schedule badge appears on the request card

### 10.2 Frequency Options

| Frequency | Interval | Typical Use |
|-----------|----------|-------------|
| `daily` | Every day | Ongoing high-frequency meter checks |
| `weekly` | Every 7 days | Weekly relay log check |
| `biweekly` | Every 14 days | Fortnightly oil level inspection |
| `monthly` | Every 30 days | Monthly preventive maintenance |
| `quarterly` | Every 90 days | Quarterly transformer maintenance |
| `yearly` | Every 365 days | Annual type test / overhaul |

### 10.3 Schedule Management

| Action | How |
|--------|-----|
| View schedule | Open request → **Schedule** tab |
| Pause schedule | Schedule tab → **Pause** (stops new requests being created) |
| Resume schedule | Schedule tab → **Resume** |
| Edit frequency / dates | Schedule tab → **Edit** |
| Delete schedule | Schedule tab → **Delete Schedule** |
| View history | Schedule tab → **Logs** (shows each run: success / failed, generated request ID) |

### 10.4 What Happens Automatically

When `next_run_date` arrives (system runs nightly at midnight IST):
1. A new testing request is cloned from the template request
2. Status set to `submitted`
3. Due date = next_run_date + frequency
4. Originator receives a **notification**: _"Recurring test request auto-created: [Request ID]"_
5. Schedule log entry created (success / failed)

### 10.5 Schedule Scenario — Monthly Transformer PMC

**Context:** Substation XYZ has a 220/132 kV Power Transformer. AEE Maintenance wants routine monthly preventive maintenance checks.

| Step | Actor | Action |
|------|-------|--------|
| 1 | AEE Maintenance | Raises a Maintenance request for the Power Transformer, type: "Routine Preventive Maintenance", due: 2026-05-01 |
| 2 | EE TLSS | Approves & assigns Field Tester |
| 3 | Field Tester | Completes the maintenance using `transformer_maintenance` template |
| 4 | SEE W&M | Approves the result |
| 5 | AEE Maintenance | Opens the completed request → **Enable Schedule** → Frequency: Monthly, Advance Days: 5 |
| 6 | System (2026-04-26) | Auto-creates new Maintenance request due 2026-06-01, sends notification |
| 7 | Cycle repeats | Every month, a new request is auto-raised 5 days before the due date |

---

## 11. Multi-Session Testing

Multi-session testing allows a single test request to span **multiple days or sessions**, each with its own readings, environmental conditions, and pass/fail status.

### 11.1 When to Use Multi-Session

| Use Case | Sessions | Template |
|----------|----------|----------|
| Repair lifecycle (S1–S10) | 10 fixed stages | `transformer_repair_lifecycle` |
| Multi-day maintenance overhaul | 2–5 days | `breaker_maintenance`, `transformer_maintenance` |
| Multi-point substation inspection | Per inspection bay | `substation_inspection` |
| Long-duration stability test | Periodic readings over days | Any template |

### 11.2 Enabling Multi-Session on a Request

**Who can do this:** EE TLSS, EE RT (when creating or editing a request before assignment)

1. Navigate to **Testing Requests → New Request**
2. Select equipment, category, and test type
3. Toggle **Multi-Session** ON
4. Fill:
   - **Total Sessions Planned** (e.g., 10 for repair lifecycle)
   - **Session Interval Days** (e.g., 7 = one session per week)
   - **Scheduled Start Date** (first session date)
5. Submit

### 11.3 Session States

```
scheduled → in_progress → completed
                        → skipped   (session not conducted, documented reason)
```

### 11.4 Working with Sessions (Tester View)

After accepting a multi-session request:

1. Open the request → **Sessions** tab
2. Click **Auto-Generate Sessions** (creates all sessions at once based on interval) or create manually
3. For each session:

| Action | UI Element |
|--------|-----------|
| View session details | Click session row |
| Start session | **Start Session** button — status → `in_progress` |
| Enter environmental conditions | Temperature, humidity, weather fields |
| Add readings | **+ Add Reading** — enter data in template grid |
| Upload photos | Reading row → **Attach Images** |
| Mark witness | **Witnessed By** field (external name) |
| Complete session | **Complete Session** — prompts for sign-off notes |
| Skip session | **Skip** — requires reason |

### 11.5 Session Reading Structure

Each reading within a session captures:
- **Reading Number** (auto-increment within session)
- **Reading Time** (timestamp)
- **Reading Data** (all template fields filled)
- **Equipment Serial** (instrument used)
- **Calibration Date** (instrument calibration)
- **Result Status:** `pass` / `fail` / `conditional` / `warning`
- **Remarks**
- **Photos** (multiple images per reading)

### 11.6 Multi-Session Progress View

The request card shows a **Session Progress Bar:**

```
[███████░░░░░░░░]  7 / 10 sessions completed
```

Tapping the bar opens the full session timeline with dates and statuses.

---

## 12. Scenario: CVT Dielectric Test (Single Session)

**Equipment:** 220 kV CVT (UEIC: KPT-CVT-220-001)
**Category:** Test · **Test Type:** CVT Test Report
**Actors:** AEE Maintenance → EE TLSS → Field Tester → SEE W&M

### Step-by-Step

| Step | Actor | Screen / Action | Detail |
|------|-------|-----------------|--------|
| 1 | **AEE Maintenance** | Testing Requests → New Request | Equipment: CVT · Category: Test · Type: CVT Test Report · Due: 2026-04-25 · Notes: "220kV CVT Bay 3 annual dielectric check" |
| 2 | **AEE Maintenance** | Submit | Status → `submitted` |
| 3 | **EE TLSS** | Testing Request Approvals → open request | Reviews equipment details and priority |
| 4 | **EE TLSS** | Approve & Assign Tester | Tester Role: Field Tester · Tester: field.tester@kptcl.com · Comment: "Carry Megger" |
| 5 | **Field Tester** | My Assignments → accept | Status → `accepted` |
| 6 | **Field Tester** | Set Scheduled Date: 2026-04-25 08:00 | Status → `scheduled` |
| 7 | **Field Tester** | Start Test | Template `cvt_test_report` loads · Status → `in_progress` |
| 8 | **Field Tester** | Fill template | CVT nameplate, capacitance values (C1, C2), tan delta (δ), IR values at 1kV / 5kV / 10kV, temperature compensation, photos |
| 9 | **Field Tester** | Overall Assessment | Result: Pass / Fail / Conditional · Recommendation: "Replace capacitor stack if δ > 0.5%" |
| 10 | **Field Tester** | Submit Test | Status → `test_submitted` |
| 11 | **SEE W&M** | Testing Request Approvals → review results | Verifies pass/fail criteria |
| 12 | **SEE W&M** | Approve | Status → `approved` → `completed` · PDF report auto-generated |

---

## 13. Scenario: Power Transformer Maintenance (Scheduled + Recurring)

**Equipment:** 100 MVA 220/132 kV Power Transformer (UEIC: KPT-PT-220-003)
**Category:** Maintenance · **Type:** Routine Preventive Maintenance
**Actors:** AEE Maintenance → EE TLSS → Field Tester → SEE W&M
**Special feature:** Recurring monthly schedule

### Step-by-Step

| Step | Actor | Screen / Action | Detail |
|------|-------|-----------------|--------|
| 1 | **AEE Maintenance** | New Request | Equipment: Power Transformer · Category: Maintenance · Type: Routine Preventive Maintenance · Due: 2026-05-01 |
| 2 | **EE TLSS** | Approve & Assign | Field Tester assigned · Comment: "May shutdown window confirmed" |
| 3 | **Field Tester** | Accept → Schedule Date → Start | Template `transformer_maintenance` loads |
| 4 | **Field Tester** | Fill template | Oil level, buchholz relay, PRD, silica gel condition, cooling fans, tap changer operation, earthing, IR test readings |
| 5 | **Field Tester** | Submit | Status → `test_submitted` |
| 6 | **SEE W&M** | Approve | Report generated |
| 7 | **AEE Maintenance** | Enable Schedule | Frequency: Monthly · Start: 2026-05-01 · End: 2027-04-30 · Advance Days: 5 |
| 8 | **System** | Auto-runs 2026-04-26 | New request created due 2026-06-01 · AEE Maintenance notified |
| 9 | Cycle | Repeats monthly | 12 requests over 1 year; each goes through same approval → test → approval flow |

### Schedule Log View

Navigate to the original request → **Schedule** tab → **Logs:**

| Run Date | Status | Generated Request |
|----------|--------|-------------------|
| 2026-04-26 | Success | REQ-2026-0524 |
| 2026-05-26 | Success | REQ-2026-0611 |
| 2026-06-26 | Failed | — (error: no tester available) |

---

## 14. Scenario: Substation Inspection (Multi-Day, Multi-Session)

**Equipment:** 220 kV Substation – Entire yard
**Category:** Inspection · **Type:** Electrical Safety, Civil, Fire Safety
**Actors:** AEE Maintenance → EE TLSS → Field Tester
**Special feature:** Multi-session (3 days, one inspection type per day)

### Step-by-Step

| Step | Actor | Action | Detail |
|------|-------|--------|--------|
| 1 | **AEE Maintenance** | New Request — Inspection | Equipment: Substation · Type: Electrical Safety · Toggle Multi-Session ON · Total Sessions: 3 · Interval: 1 day · Start: 2026-04-28 |
| 2 | **EE TLSS** | Approve & Assign | Field Tester assigned |
| 3 | **Field Tester** | Accept → Sessions tab → Auto-Generate | 3 sessions created: Day 1 (28 Apr), Day 2 (29 Apr), Day 3 (30 Apr) |
| 4 | **Field Tester (Day 1)** | Start Session 1 — "Electrical Safety" | Enter: Temperature 32°C, Humidity 68% · Fill safety checklist: earthing continuity, cable tray condition, switchgear IR, panel labelling · Result: Pass · Attach photos |
| 5 | **Field Tester (Day 1)** | Complete Session 1 | Status → `completed` |
| 6 | **Field Tester (Day 2)** | Start Session 2 — "Civil" | Civil inspection: building cracks, cable trenches, drain condition, cable tray covers · Result: Conditional (one cracked slab noted) |
| 7 | **Field Tester (Day 3)** | Start Session 3 — "Fire Safety" | Fire extinguisher expiry, sand buckets, emergency exits, smoke detectors · Result: Fail (2 extinguishers expired) |
| 8 | **Field Tester** | Submit overall test | Overall: Conditional — remedial action required |
| 9 | **EE TLSS** | Approve | Generates inspection report with all 3 session findings |
| 10 | **AEE Maintenance** | Raise new requests | Separate repair requests raised for cracked slab and expired extinguishers |

### Session Progress View

```
Session 1 – Electrical Safety  [✓ completed]  28 Apr
Session 2 – Civil              [✓ completed]  29 Apr
Session 3 – Fire Safety        [✓ completed]  30 Apr
─────────────────────────────────────────────
Overall: 3/3 sessions · Status: test_submitted
```

---

## 15. Scenario: Circuit Breaker Repair Lifecycle (Multi-Session, 10 Stages)

**Equipment:** 132 kV SF6 Circuit Breaker (UEIC: KPT-CB-132-007)
**Category:** Repair Lifecycle
**Template:** `transformer_repair_lifecycle` (maps for all repair lifecycle requests)
**Actors:** AEE Maintenance → EE TLSS → SEE W&M → Field Tester → CEE Transmission Zone
**Special feature:** 10 fixed stages, multi-week timeline

### Stage Map

| Stage | Session | Description | Typical Actor |
|-------|---------|-------------|---------------|
| S1 | Session 1 | Failure Report | AEE Maintenance (template section) |
| S2 | Session 2 | Repair Committee Review | SEE W&M / CEE Zone |
| S3 | Session 3 | Allotment to Repairer (vendor awarded) | EE TLSS |
| S4 | Session 4 | Lifting by Repairer (CB taken from site) | Field Tester |
| S5 | Session 5 | Joint Inspection at Vendor's Works | EE RT / Field Tester |
| S6 | Session 6 | Estimate & Revised Work Award | SEE W&M |
| S7 | Session 7 | Stage Inspections at vendor (during repair) | EE RT |
| S8 | Session 8 | Final Inspection before dispatch | EE RT / SEE RT |
| S9 | Session 9 | Dispatch from vendor | Field Tester |
| S10 | Session 10 | Erection, Testing & Commissioning | Field Tester + EE TLSS witness |

### Step-by-Step

| Step | Actor | Action |
|------|-------|--------|
| 1 | **AEE Maintenance** | New Request · Equipment: CB · Category: Repair Lifecycle · Multi-Session ON · Total: 10 · Interval: variable (manual scheduling) |
| 2 | **EE TLSS** | Approve & Assign Field Tester |
| 3 | **Field Tester** | Accept → Sessions tab → Create Session 1 manually with date |
| 4 | **Field Tester (S1)** | Start Session 1 "S1: Failure Report" · Fill failure description, date of failure, fault nature, protection operated, photos of damaged parts · Complete |
| 5 | **SEE W&M (S2)** | Start Session 2 "S2: Repair Committee" · Record committee members, decision: repair vs. scrap, repair scope · Complete |
| 6 | **EE TLSS (S3)** | Start Session 3 "S3: Allotment" · Vendor name, PO number, delivery schedule · Complete |
| 7 | **Field Tester (S4)** | Start Session 4 "S4: Lifting" · Date of removal from site, transport details, receipt at vendor confirmed · Complete |
| 8 | **EE RT (S5)** | Start Session 5 "S5: Joint Inspection" · Defect list, agreed repair scope, revised estimate · Complete |
| 9 | **SEE W&M (S6)** | Start Session 6 "S6: Revised Award" · Revised PO value, approval reference · Complete |
| 10 | **EE RT (S7)** | Start Session 7 "S7: Stage Inspections" · SF6 drying result, main contacts replaced (photo), piping pressure test · Complete |
| 11 | **EE RT + SEE RT (S8)** | Start Session 8 "S8: Final Inspection" · Full functional test at vendor works, travel/timing test, SF6 fill pressure · Result: Pass · Witnessed by SEE RT |
| 12 | **Field Tester (S9)** | Start Session 9 "S9: Dispatch" · Dispatch date, transport vehicle, packing condition, GRN at site · Complete |
| 13 | **Field Tester + EE TLSS (S10)** | Start Session 10 "S10: ETC" · Erection checklist, SF6 refill at site, contact resistance test, travel & timing, protection relay coordination test · Result: Pass · Commissioned |
| 14 | **EE TLSS** | Submit all sessions · Overall: Pass |
| 15 | **CEE Transmission Zone** | Final approval · Repair lifecycle report auto-generated (PDF) |

### Session Timeline View

```
S1  Failure Report           [✓]  2026-01-15   Field Tester
S2  Repair Committee         [✓]  2026-01-22   SEE W&M
S3  Allotment to Repairer    [✓]  2026-02-01   EE TLSS
S4  Lifting by Repairer      [✓]  2026-02-08   Field Tester
S5  Joint Inspection         [✓]  2026-02-20   EE RT
S6  Revised Work Award       [✓]  2026-03-01   SEE W&M
S7  Stage Inspections        [✓]  2026-03-20   EE RT
S8  Final Inspection         [✓]  2026-04-05   EE RT + SEE RT
S9  Dispatch                 [✓]  2026-04-10   Field Tester
S10 Erection, Test & Comm.   [✓]  2026-04-18   Field Tester + EE TLSS
────────────────────────────────────────────────────────────
10/10 sessions · Overall: PASS · CEE Zone approved
```

---

## 16. Dashboards & KPI Cards

### AEE Maintenance Dashboard

| KPI Card | Description |
|----------|-------------|
| My Open Requests | Requests raised by this user still in progress |
| Pending My Action | Requests waiting on this user's next step |
| Overdue | Requests past due date |
| This Month's Completed | Tests completed in current month |

### EE TLSS Dashboard (Primary Operational View)

| KPI Card | Description |
|----------|-------------|
| Pending Approval | Requests waiting for EE TLSS review |
| Assigned — Awaiting Acceptance | Requests assigned but tester not yet accepted |
| In Progress | Tests currently running |
| Scheduled | Requests with a future test date set |
| Overdue | Requests past due date |
| Completed This Month | Completed test count |
| Equipment Due Soon | Equipment with test due within 30 days |
| Test Pass Rate | % of tests passing first submission |

### SEE W&M / CEE Zone Dashboard

| KPI Card | Description |
|----------|-------------|
| Pending Second Approval | Results awaiting SEE / CEE approval |
| Monthly Test Volume | Total tests in current month across division |
| Overdue Escalations | Requests overdue by > 7 days |
| Vendor Quotes Pending | Open procurement items |

### EE RT / SEE RT Dashboard

| KPI Card | Description |
|----------|-------------|
| Template Customisations | Templates modified in last 30 days |
| Lab Tests In Progress | Active lab-based test sessions |
| Multi-Session Completion Rate | % of multi-session tests completed on schedule |

---

## 17. Notifications

All users receive in-app and email notifications for events relevant to their role.

| Event | Who Is Notified |
|-------|----------------|
| New request submitted | EE TLSS, SEE W&M (approvers) |
| Request approved & tester assigned | Assigned tester |
| Tester accepted | Originator, EE TLSS |
| Test submitted for review | SEE W&M, SEE RT, CEE Zone |
| Test approved (final) | Originator, AEE Maintenance |
| Test rejected | Originator, assigned tester |
| Recurring request auto-created | Originator |
| Session completed (multi-session) | EE TLSS, originator |
| Equipment due for test (≤ 30 days) | AEE Maintenance, EE TLSS |
| Schedule run failed | Org Admin |
| Report generated | Requester, approver |

---

## 18. Reports (14 Built-In)

Navigate to **Reports** → select report → set filters → **Export PDF** or **Export Excel**.

| # | Report Name | Description | Key Filters |
|---|-------------|-------------|-------------|
| 1 | Test Request Summary | All requests with status, equipment, tester | Date range, status, category |
| 2 | Pending Approvals | Requests awaiting approval action | Role, overdue flag |
| 3 | Overdue Requests | Requests past due date | Department, priority |
| 4 | Tester Workload | Open assignments per tester | Tester, date range |
| 5 | Equipment Test History | All test history for one equipment | UEIC, date range |
| 6 | Equipment Due Schedule | Equipment due for testing in next N days | Days ahead, equipment type |
| 7 | Test Pass / Fail Rate | Pass/fail statistics by equipment type | Month, category, type |
| 8 | Maintenance Compliance | PMC done vs. scheduled | Department, frequency |
| 9 | Inspection Findings | Inspection results with action items | Substation, date range |
| 10 | Repair Lifecycle Status | Status of all repair lifecycle requests by stage | Stage, equipment type |
| 11 | Template Usage | Which templates are used and how often | Template key, month |
| 12 | Recurring Schedule Log | History of auto-created requests | Schedule ID, status |
| 13 | User Activity Audit | Login history, actions taken | User, date range |
| 14 | Equipment Asset Register | Full equipment inventory with status | Department, equipment type, status |

---

## 19. Org Admin Tasks

Login: `kptcl.admin@kptcl.com` / `admin123`

### User Management
1. **Users → Invite User** — enter email, select org role (from SRS designation list)
2. **Users → Edit** — change role, department, employee ID
3. **Users → Deactivate** — revoke access without deleting history

### Department Setup
1. **Departments → Add** — create zones, circles, divisions
2. **Departments → Assign Head** — link a SEE/EE role user as dept head

### Role & Permission Customisation
1. **Roles → View Roles** — see all provisioned SRS designation roles
2. **Roles → Edit Permissions** — add or remove module access per role
3. **Roles → Create Custom Role** — derive a new role from a template

### Template Override
1. **Test Template Management → Org Override**
2. Select base template (e.g., `cvt_test_report`)
3. Add org-specific fields without changing the global template

### Provisioning Global Templates
If templates are missing: **Settings → Templates → Provision Global Defaults**
This re-seeds all 13 SRS built-in templates from the system defaults.

---

## 20. Quick Reference

### Request Status Reference

| Status | Meaning | Who Can Move Forward |
|--------|---------|---------------------|
| `draft` | Being composed | Creator |
| `submitted` | Waiting for approval | EE TLSS / SEE W&M |
| `pending_approval` | Formal review in progress | Approver |
| `assigned` | Tester designated | Tester (must accept) |
| `accepted` | Tester confirmed | Tester |
| `scheduled` | Test date fixed | Tester |
| `in_progress` | Test underway | Tester |
| `test_submitted` | Results uploaded, awaiting review | SEE W&M / CEE Zone |
| `under_approval` | Senior review in progress | Senior Approver |
| `approved` | Passed review | System |
| `rejected` | Rejected at any stage | — (re-submit required) |
| `procurement_initiated` | Repair/procurement triggered | Purchaser / SEE W&M |
| `completed` | Fully closed | System |

### Session Status Reference

| Status | Meaning |
|--------|---------|
| `scheduled` | Session planned, not yet started |
| `in_progress` | Tester currently filling readings |
| `completed` | All readings recorded, session closed |
| `skipped` | Session not conducted (documented reason required) |

### Schedule Frequency Reference

| Frequency | Interval | Next Run Calculation |
|-----------|----------|---------------------|
| `daily` | 1 day | last_run_date + 1 day |
| `weekly` | 7 days | last_run_date + 7 days |
| `biweekly` | 14 days | last_run_date + 14 days |
| `monthly` | 30 days | last_run_date + 30 days |
| `quarterly` | 90 days | last_run_date + 90 days |
| `yearly` | 365 days | last_run_date + 365 days |

### Frequently Asked Questions

**Q: I submitted a request but it's not showing up for approval.**
A: Confirm the status is `submitted` (not `draft`). Only submitted requests appear in the approvals queue. Also check the approver has permission for the request's equipment category.

**Q: The tester assignment page shows no eligible testers.**
A: Tester eligibility is determined by role-module permissions. Ensure the Field Tester / Lab Tester org role has full permissions on the required modules. Contact Org Admin to verify role configuration.

**Q: Can I modify a template for just one request without changing the global template?**
A: No — templates apply at org level. To customise, use the org-override feature in Test Template Management. For a one-off change, use the **Remarks / Notes** field on the request.

**Q: How do I handle a skipped session in a repair lifecycle?**
A: Open the session → click **Skip** → enter the reason (mandatory). The skipped session is documented in the final report. The request continues to the next session.

**Q: Why did the schedule auto-create fail?**
A: Check the Schedule Logs (request → Schedule tab → Logs). Common causes: no active approver for the org, equipment decommissioned, or organisation subscription expired. Org Admin receives a failure notification.

**Q: Who can export reports?**
A: All SRS designation roles have `can_export` on the Reports module. Reports are exported as PDF (formatted) or Excel (raw data).

---

*SEACMS-AI User Manual · KPTCL · Version 1.3 · Generated 2026-04-20*
*For technical support contact: support@relu.com*
