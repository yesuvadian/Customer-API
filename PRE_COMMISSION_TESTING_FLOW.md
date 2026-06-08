# Pre-Commission QAP Module — Testing Flow

> **Organisation:** Karnataka Power Transmission Corporation Limited (KPTCL)  
> **Module:** Pre-Commission Manufacturing Quality Assurance Plan (QAP)  
> **Scope:** 110 kV / 66 kV Power Transformers rated up to 31.5 MVA  
> **Base URL:** `http://<server>/api`

---

## Test User Accounts

| Role | Email | Password | Full Name | Employee ID |
|------|-------|----------|-----------|-------------|
| Asset Data Officer | `originator@utility.com` | `admin123` | KPTCL Asset Data Officer | KPTCL-ORIG-001 |
| Reviewing Officer | `ee.tlss@utility.com` | `admin123` | EE TLSS | KPTCL-EE-TLSS-001 |
| Reviewing Officer | `ee.rt@utility.com` | `admin123` | EE RT | KPTCL-EE-RT-001 |
| Senior Management Approver | `cee.zone@utility.com` | `admin123` | CEE Transmission Zone | KPTCL-CEE-TZ-001 |
| Transformer Repair Coordinator | `wf.coordinator@utility.com` | `admin123` | Workflow Coordinator | KPTCL-WFC-001 |
| Supervisory Officer | `see.wm@utility.com` | `admin123` | SEE W&M | KPTCL-SEE-WM-001 |

---

## End-to-End Flow Overview

```
[originator@utility.com]          Creates PCR ticket
        ↓
[ee.tlss@utility.com]             Sees in Approvals → Pre-Commission tab → Approves
        ↓
                                  System auto-creates QAP workflow (PRE_COMMISSION)
        ↓
[wf.coordinator@utility.com]      Opens workflow → Assigns Reviewing Officer per stage
        ↓
[ee.tlss@utility.com]             Fills QAP check-item form → Submits
        ↓
[cee.zone@utility.com]            Approves stage → advances to next stage
        ↓
                                  (Repeat for all 9 QAP stages)
        ↓
[cee.zone@utility.com]            Downloads QAP Report (PDF/HTML) on workflow completion
        ↓
[originator@utility.com]          Registers equipment → Links PCR on registration
                                  equipment.precommission_request_id → FK stored on both sides
```

---

## Step-by-Step Testing

---

### STEP 1 — Create Pre-Commission Request

**User:** `originator@utility.com` / `admin123`  
**Role:** Asset Data Officer  
**Nav:** Pre-Commission Requests → New Request

#### What to do
1. Login as `originator@utility.com`
2. Navigate to **Pre-Commission Requests** from the left sidebar
3. Click **New Request**
4. Fill in the form:

**Procurement Details:**

| Field | Test Value |
|-------|------------|
| Vendor / Manufacturer * | BHEL Bhopal |
| Purchase Order Number * | KPTCL/T&C/110kV/2024-001 |
| PO Date | 01-06-2024 |
| Quantity | 2 |
| Proposed Inspection Date | 15-07-2024 |
| Factory Location | BHEL Bhopal, Madhya Pradesh |
| Remarks | 2 units of 110/33kV, 31.5 MVA Power Transformers |

**Transformer Details:**

| Field | Test Value |
|-------|------------|
| Voltage Class * | 110kV |
| Rated MVA * | 31.5 |
| Transformer Type | Two-winding |
| Cooling Class | ONAN |
| Vector Group | YNyn0 |

5. Click **Submit Request**

#### Expected Result
- New PCR ticket created with number `PCR-YYYYMMDD-0001`
- Status: **PENDING**
- Card visible in **All** and **Pending** tabs
- No workflow linked yet (`workflow_id = null`)

#### Verify (API)
```
GET /precommission/requests
→ Returns list with PCR-YYYYMMDD-0001, approval_status: "pending"
```

---

### STEP 2 — View Pending PCR in Approval Queue

**User:** `ee.tlss@utility.com` / `admin123`  
**Role:** Reviewing Officer  
**Nav:** Approvals → Pre-Commission tab

#### What to do
1. Logout, login as `ee.tlss@utility.com`
2. Navigate to **Approvals** from the sidebar
3. Click the **Pre-Commission** tab (should show badge count `1`)
4. Verify the PCR card shows:
   - Request number: `PCR-YYYYMMDD-0001`
   - Vendor: `BHEL Bhopal`
   - PO: `KPTCL/T&C/110kV/2024-001`
   - Voltage: `110kV`
   - MVA: `31.5 MVA`
   - Status chip: **PENDING**
5. Tap the card to open the right panel detail

#### Expected Result
- Detail panel opens showing all PCR fields in two sections:
  - **Procurement Details** (vendor, PO, dates, factory)
  - **Transformer Details** (voltage class, MVA, type, cooling, vector group)
- Bottom of panel shows **Reject** and **Approve** buttons

---

### STEP 3 — Approve the PCR Request

**User:** `ee.tlss@utility.com` / `admin123`  
**Role:** Reviewing Officer  
**Nav:** Approvals → Pre-Commission tab → detail panel

#### What to do
1. In the detail panel, click **Approve**
2. Enter approval notes: `Approved for factory inspection. KPTCL team to visit BHEL Bhopal.`
3. Click **Approve** in the dialog

#### Expected Result
- PCR status changes to **APPROVED**
- Detail panel refreshes showing:
  - Status chip: **APPROVED**
  - Approved At: today's date
  - Notes: `Approved for factory inspection...`
  - **QAP WORKFLOW ACTIVE** chip appears
  - Current stage: `RAW MATERIAL`
- PCR disappears from the **Pending** tab
- PCR appears in **Pre-Commission Requests** → **Approved** tab for `originator@utility.com`

#### Verify (API)
```
GET /precommission/requests/{id}
→ approval_status: "approved"
→ workflow_id: "<uuid>"  (auto-created)
→ current_stage_code: "QAP_RAW_MATERIAL"

GET /repair-workflows/{workflow_id}
→ workflow_code: "PRE_COMMISSION"
→ status: "active"
→ current_stage: { name: "Raw Material Inspection" }
→ assignment_pending: true
```

---

### STEP 4 — View QAP Workflow in Execution Page

**User:** `ee.tlss@utility.com` / `admin123`  
**Role:** Reviewing Officer  
**Nav:** Pre-Commission Workflows

#### What to do
1. Navigate to **Pre-Commission Workflows** from the sidebar
2. Verify the workflow card shows:
   - Number: `PCR-YYYYMMDD-0001`
   - Status: **ACTIVE**
   - Current Stage: `Raw Material Inspection`
   - Progress: `0%`
   - **ASSIGN** badge visible

#### Expected Result
- Workflow card renders with **teal accent colour** (matches PCR module)
- Progress bar at 0%
- ASSIGN badge indicating stage needs assignment

---

### STEP 5 — Assign Stage to Reviewing Officer

**User:** `wf.coordinator@utility.com` / `admin123`  
**Role:** Transformer Repair Coordinator  
**Nav:** Pre-Commission Workflows

#### What to do
1. Logout, login as `wf.coordinator@utility.com`
2. Navigate to **Pre-Commission Workflows**
3. Tap the `PCR-YYYYMMDD-0001` workflow card
4. Workflow detail sheet opens — verify:
   - Header icon: precision manufacturing icon 🏭
   - Accent colour: teal
   - Current stage: **Raw Material Inspection**
   - **Assign User** button visible
5. Click **Assign User**
6. Select `ee.tlss@utility.com` (EE TLSS) from the dropdown
7. Click **Assign**

#### Expected Result
- Stage status changes from `pending` → `assigned`
- ASSIGN badge disappears from card
- Timeline shows `assigned` event

---

### STEP 6 — Fill QAP Stage Form (Raw Material Inspection)

**User:** `ee.tlss@utility.com` / `admin123`  
**Role:** Reviewing Officer  
**Nav:** Pre-Commission Workflows

#### What to do
1. Login as `ee.tlss@utility.com`
2. Navigate to **Pre-Commission Workflows**
3. Tap the workflow card → workflow detail sheet opens
4. **Current Stage Form** section appears with the QAP check-item table
5. Verify the form has the following sections:
   - Inspection Visit Details
   - 1.1 CRGO Core Laminations
   - 1.2 Conductors (Winding Wire / Strip)
   - 1.3 Insulating Materials (Pressboard / Kraft Paper)
   - 1.4 Transformer Oil
   - 1.5 Bushings
   - 1.6 OLTC (On Load Tap Changer)
   - 1.7 Cooling Equipment
   - Overall Remarks

6. Fill Inspection Visit Details:

| Field | Value |
|-------|-------|
| Date of Inspection | 15-07-2024 |
| KPTCL Committee Members | Sri. Ravi Kumar EE (TLSS), Sri. Suresh AEE |
| Third Party Agency (B) | BVQI India Pvt. Ltd. |
| Manufacturer Representative | Mr. Ashok Kumar, BHEL |
| Place of Inspection | BHEL Works, Bhopal |

7. Fill check-item table rows (for CRGO Core Laminations):
   - Click on **Observed Value** cell for `Grade of CRGO steel` → type `M3 Grade, 0.27mm`
   - **Result** dropdown → `Pass`
   - Check **M** checkbox ✓
   - Check **B** checkbox ✓
   - Check **A** checkbox ✓
   - **Remarks** → `As per IS 3024, test certificate verified`

8. Fill remaining check items similarly

9. Fill Overall Remarks:
   - Overall Stage Result: `Pass`
   - Overall Remarks: `All raw materials inspected and found satisfactory`
   - Upload supporting document if available

10. Click **Save Form**

#### Expected Result
- Form data saved (no stage advancement yet)
- Success snackbar: `Saved`
- Stage status: still `assigned` (not yet submitted)

---

### STEP 7 — Submit Stage for Review

**User:** `ee.tlss@utility.com` / `admin123`  
**Role:** Reviewing Officer  
**Nav:** Pre-Commission Workflows → workflow detail sheet

#### What to do
1. After saving the form, click **Submit for Review**
2. Optionally enter remarks: `Raw material inspection complete. All checks passed.`
3. Click **Submit**

#### Expected Result
- Stage status: `submitted`
- Submit button disappears, Approve/Reject buttons appear (for approver)
- Timeline shows `submitted` event

---

### STEP 8 — Approve Stage (Advance to Next QAP Stage)

**User:** `cee.zone@utility.com` / `admin123`  
**Role:** Senior Management Approver  
**Nav:** Pre-Commission Workflows

#### What to do
1. Logout, login as `cee.zone@utility.com`
2. Navigate to **Pre-Commission Workflows**
3. Tap the `PCR-YYYYMMDD-0001` card
4. Verify **Approve** and **Reject** buttons are visible
5. Click **Approve**
6. Enter remarks: `Raw material inspection verified. Proceed to Core Assembly.`
7. Click **Approve**

#### Expected Result
- Stage `QAP_RAW_MATERIAL` → completed
- Workflow advances to `QAP_CORE_ASSEMBLY`
- Progress bar updates: `~11%` (1 of 9 stages done)
- Current Stage: **Core Building & Frame Assembly**
- Timeline shows approval event

---

### STEP 9 — Reject Stage (Re-inspection Scenario)

**User:** `cee.zone@utility.com` / `admin123`  
**Role:** Senior Management Approver

#### What to do
1. At any stage (e.g. QAP_WINDING), if issues found:
2. Click **Reject** in the workflow detail sheet
3. Enter reason: `Winding conductor dimensions not matching approved drawing. Re-inspection required.`
4. Click **Reject**

#### Expected Result
- Stage loops back to **same stage** (QAP_WINDING)
- Stage status: back to `pending` (needs re-assignment)
- Timeline shows rejection event with reason
- Coordinator must re-assign → inspector re-fills form → resubmits → approver reviews again

---

### STEP 10 — Repeat for All 9 QAP Stages

Repeat Steps 5–8 for each stage in sequence:

| Stage | Name | Duration (days) |
|-------|------|----------------|
| 1 | Raw Material Inspection | 3 |
| 2 | Core Building & Frame Assembly | 3 |
| 3 | Winding Inspection | 3 |
| 4 | Active Part Assembly | 3 |
| 5 | Tank & Accessories | 3 |
| 6 | Active Part in Main Tank | 3 |
| 7 | Pre-Delivery Routine Tests | 2 |
| 8 | Special / Type Tests | 2 |
| 9 | Final Inspection & Dispatch | 1 |

For **Stage 9 (Final Dispatch)**, the Overall Stage Result dropdown has extra option: `Cleared for Dispatch`. Select this to indicate the transformer is ready for delivery.

#### Expected Result after all 9 stages approved
- Workflow status: **COMPLETED**
- Progress bar: `100%`
- No more action buttons
- Full timeline visible with all 9 stage approvals

---

### STEP 11 — Register Equipment & Link to PCR

**User:** `originator@utility.com` / `admin123`  
**Role:** Asset Data Officer  
**Nav:** Equipment Register → Register Equipment

#### What to do
1. Login as `originator@utility.com`
2. Navigate to **Equipment Register**
3. Click **Register Equipment** (or the + button)
4. **Step 1 — Equipment Setup:**

| Field | Value |
|-------|-------|
| Equipment Type | Power Transformer |
| Location / Substation | (select appropriate substation) |
| Bay Number | Bay-01 |
| Voltage Class | 110 kV |

5. **PRE-COMMISSION QAP LINK section appears** (only for Power Transformer):
   - Dropdown shows: `PCR-YYYYMMDD-0001 · BHEL Bhopal · 110kV · 31.5 MVA`
   - Select `PCR-YYYYMMDD-0001`
   - Confirmation chip appears: `✓ Linked to PCR-YYYYMMDD-0001 — BHEL Bhopal (Bhopal)`

6. Click **Continue** to proceed to Step 2 (Nameplate form)
7. Fill nameplate data and save

#### Expected Result
- Equipment registered with UEIC auto-generated (e.g. `KPT-110-T-001`)
- PCR record updated: `equipment_id` = new equipment UUID
- PCR no longer appears in the **unlinked** dropdown for future equipment registrations
- PCR detail shows equipment linked

#### Verify (API)
```
GET /precommission/requests/{pcr_id}
→ equipment_id: "<equipment-uuid>"  (now filled)

GET /precommission/requests/unlinked
→ PCR-YYYYMMDD-0001 no longer appears in this list

GET /equipment/{equipment_id}
→ precommission_request_id: "<pcr-uuid>"   (FK stored on equipment record)
→ precommission_request: { request_number: "PCR-...", vendor_name: "BHEL Bhopal", ... }
```

---

### STEP 12 — Download QAP Report (PDF / HTML)

**User:** `cee.zone@utility.com` / `admin123`  
**Role:** Senior Management Approver  
**Nav:** Pre-Commission Workflows → completed workflow card

#### What to do
1. Login as `cee.zone@utility.com`
2. Navigate to **Pre-Commission Workflows**
3. Find the `PCR-YYYYMMDD-0001` workflow card with status **COMPLETED**
4. Tap the card → `WorkflowDetailSheet` opens
5. In the header row, two icon buttons appear (only for completed workflows):
   - 🌐 **HTML Report** button (teal)
   - 📄 **PDF Report** button (red)
6. Click **PDF Report** → browser downloads `QAP_PCR-YYYYMMDD-0001.pdf`
7. Click **HTML Report** → in-app web view opens the QAP report

#### Expected PDF Content
The PDF replicates the KPTCL QAP table format (A3 landscape):

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Manufacturing Quality Plan for Power Transformers                        │
├────────────────────────┬───────────────────────────┬─────────────────────┤
│ A. Manufacturer:       │ B. Third Party (BPTIO):   │ As proposed by the  │
│    M/s BHEL Bhopal     │    M/s BVQI India Pvt.Ltd │    Committee        │
├──────────┬─────────────┴──┬────────────┬────────────┬──────┬─────────────┤
│ PCR No.  │ 110kV          │ 31.5 MVA   │ Two-winding│ ONAN │ YNyn0       │
├──────────┴────────────────┴────────────┴────────────┴──────┴─────────────┤
│ Stage: RAW MATERIAL INSPECTION | Date: 15-07-2024 | ✓ Approved by EE TLSS│
├──┬──────────────────────┬──────┬────────┬───────────┬───────┬─┬─┬─┬──────┤
│# │ Components           │ Type │Quantum │Acceptance │Observed│M│B│A│Result│
├──┼──────────────────────┼──────┼────────┼───────────┼───────┼─┼─┼─┼──────┤
│1 │CRGO Grade Verification│Review│100%   │As per IS..│M3,0.27│✓│✓│✓│ PASS │
│2 │Thickness of lamination│Dim.  │Sample │As per dwg │0.27mm  │✓│ │✓│ PASS │
└──┴──────────────────────┴──────┴────────┴───────────┴───────┴─┴─┴─┴──────┘
```

- Pass rows highlighted **green**, Fail rows highlighted **red**
- Stage headers in **blue** with approval stamp
- Pending stages shown as *"Stage not yet inspected"*

#### Verify (API)
```
GET /repair-workflows/{workflow_id}/report/pdf
→ HTTP 200, Content-Type: application/pdf
→ Content-Disposition: attachment; filename="QAP_PCR-YYYYMMDD-0001.pdf"

GET /repair-workflows/{workflow_id}/report/html
→ HTTP 200, Content-Type: text/html
→ Full QAP table rendered as HTML
```

---

## Negative Test Cases

### 1. Create PCR without mandatory fields
- Login as `originator@utility.com`
- Click **New Request**, leave Vendor and PO number blank
- Click **Submit**
- **Expected:** Snackbar error — `Vendor and PO number are required`

### 2. Non-approver tries to approve
- Login as `originator@utility.com` (Asset Data Officer — no can_approve)
- Navigate to **Approvals → Pre-Commission** tab
- **Expected:** Tab shows message — `You do not have permission to approve pre-commission requests.`

### 3. Approve already-approved PCR
- Login as `ee.tlss@utility.com`
- Call `POST /precommission/requests/{id}/approve` on an already approved PCR
- **Expected:** HTTP 400 — `Request is already approved.`

### 4. Reject without reason
- In the reject dialog, leave reason blank
- Click **Reject** button
- **Expected:** Button stays disabled (requires text to be entered)

### 5. Link equipment to non-approved PCR
- Call `POST /precommission/requests/{id}/link-equipment` on a **pending** PCR
- **Expected:** HTTP 400 — `Only approved requests can be linked to equipment.`

### 6. Stage form before assignment
- Login as `ee.tlss@utility.com`
- Open unassigned workflow stage
- **Expected:** No `Submit for Review` button visible (stage not assigned yet)
- **Assign User** button visible to coordinator only

---

## Permission Matrix

| Action | Asset Data Officer | Reviewing Officer | Sr Mgmt Approver | Coordinator | Supervisory Officer |
|--------|-------------------|-------------------|------------------|-------------|---------------------|
| Create PCR | ✅ | ❌ | ❌ | ❌ | ❌ |
| View PCR list | ✅ | ✅ | ✅ | ✅ | ✅ |
| Approve PCR | ❌ | ✅ | ✅ | ❌ | ✅ |
| Reject PCR | ❌ | ✅ | ✅ | ❌ | ✅ |
| View PCR tab in Approvals | ❌ | ✅ | ✅ | ❌ | ✅ |
| View QAP Workflows | ✅ | ✅ | ✅ | ✅ | ✅ |
| Assign stage | ❌ | ❌ | ❌ | ✅ | ❌ |
| Fill & Submit stage form | ❌ | ✅ | ❌ | ❌ | ❌ |
| Approve / Reject stage | ❌ | ✅ | ✅ | ❌ | ❌ |
| Register equipment | ✅ | ❌ | ❌ | ❌ | ❌ |
| Link PCR on registration | ✅ | ❌ | ❌ | ❌ | ❌ |
| Download QAP PDF/HTML | ❌ | ✅ | ✅ | ❌ | ✅ |

---

## API Quick Reference

| Method | Endpoint | User | Description |
|--------|----------|------|-------------|
| POST | `/precommission/requests` | originator | Create PCR ticket |
| GET | `/precommission/requests?approval_status=pending` | All | List pending PCRs |
| GET | `/precommission/requests/unlinked` | All | Approved PCRs with no equipment |
| GET | `/precommission/requests/{id}` | All | Get PCR detail + workflow + timeline |
| POST | `/precommission/requests/{id}/approve` | EE/CEE | Approve → creates QAP workflow |
| POST | `/precommission/requests/{id}/reject` | EE/CEE | Reject with reason |
| POST | `/precommission/requests/{id}/link-equipment` | originator | Link onboarded equipment |
| GET | `/precommission/requests/{id}/form` | Reviewer | Get current stage form |
| POST | `/precommission/requests/{id}/save` | Reviewer | Save stage form data |
| POST | `/precommission/requests/{id}/advance` | EE/CEE | Advance or reject stage |
| GET | `/precommission/requests/{id}/timeline` | All | Full audit trail |
| GET | `/precommission/requests/{id}/actions` | All | Available actions for current user |
| GET | `/repair-workflows?status=pre_commission` | All | List QAP workflows (for execution page) |
| GET | `/category_details/details/by-master/PCR%20Voltage%20Class` | All | Voltage class dropdown options |
| GET | `/category_details/details/by-master/PCR%20Transformer%20Type` | All | Transformer type options |
| GET | `/category_details/details/by-master/PCR%20Cooling%20Class` | All | Cooling class options |
| GET | `/repair-workflows/{id}/report/pdf` | All (completed) | Download QAP PDF report |
| GET | `/repair-workflows/{id}/report/html` | All (completed) | View QAP HTML report |

---

## QAP Stage Reference

| Stage Code | Stage Name | Key Check Items |
|------------|------------|-----------------|
| `QAP_RAW_MATERIAL` | Raw Material Inspection | CRGO, conductors, insulation, oil, bushings, OLTC, cooling |
| `QAP_CORE_ASSEMBLY` | Core Building & Frame Assembly | Core stacking factor ≥ 0.96, dimensions, earthing |
| `QAP_WINDING` | Winding Inspection | LV/HV conductor dimensions, turns, axial height, transposition |
| `QAP_ACTIVE_PART` | Active Part Assembly | Inter-winding clearances, clamping, lead connections, drying |
| `QAP_TANK_FITTINGS` | Tank & Accessories | Welding, vacuum test, conservator, buchholz, radiators |
| `QAP_ACTIVE_IN_TANK` | Active Part in Main Tank | Lowering, bushing install, oil fill (BDV ≥ 60kV), sealing |
| `QAP_ROUTINE_TESTS` | Pre-Delivery Routine Tests | Ratio, resistance, impedance, no-load loss, IR test, ACPF |
| `QAP_SPECIAL_TESTS` | Special / Type Tests | Impulse, temperature rise, short circuit (if applicable) |
| `QAP_FINAL_DISPATCH` | Final Inspection & Dispatch | Nameplate, marshalling box, painting, oil leakage, documents |

---

*Document generated: 2026-06-03*  
*Module: Pre-Commission QAP (KPTCL Power Transformer Manufacturing Inspection)*
