# SEACMS — Failure Registry & Repair/Replacement Workflow
## UI Test Case Scenarios

**System:** SEACMS (SubStation Equipment and Asset Condition Monitoring System)  
**Feature:** Equipment Failure Registry → Approval → Repair Lifecycle / Procurement  
**Date:** 2026-05-01  
**Base URL:** http://localhost:8000  

---

## Test Users

| Role | Email | Password |
|------|-------|----------|
| AEE Maintenance | aee.maintenance@kptcl.com | admin123 |
| EE TLSS | ee.tlss@kptcl.com | admin123 |
| Originator | originator@kptcl.com | admin123 |
| TA&QC Officer | (org role) | admin123 |
| Department Head | depthead@kptcl.com | admin123 |
| Super Admin / Approver | superadmin@system.com | Admin123! |
| Purchaser (blocked) | purchaser@kptcl.com | admin123 |
| Doc Viewer (blocked) | docviewer@kptcl.com | admin123 |

---

## TC-FR-01 — Submit Failure Registry (Outcome: Repair)

**User:** aee.maintenance@kptcl.com  
**Role:** AEE Maintenance  
**Pre-condition:** At least one equipment exists in the system  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | Login | Dashboard loads |
| 2 | Sidebar → **Failure Registry** | FR list panel opens |
| 3 | Click **+ New Failure Report** | Form panel slides open (6 sections) |
| 4 | Section 1: Select equipment from dropdown | Equipment UEIC auto-fills |
| 5 | Section 2: Failure Date = `2026-04-20`, Category = `Electrical` | Fields accept input |
| 6 | Section 3: Description = "Primary winding insulation breakdown" | Text field accepts |
| 7 | Section 4: Outage Duration = `6` hours, Affected Feeder = "Feeder-3" | Numeric + text accept |
| 8 | Section 5: Outcome = **Repair**, Corrective Action = "Rewinding required" | Dropdown selects Repair |
| 9 | Section 6: Click **Upload** → pick a JPG file | File chip shows filename + size |
| 10 | Click **Submit** | Spinner → toast "Submitted for approval" |
| 11 | List refreshes | New card shows `FR-YYYYMMDD-XXXX`, status `under_approval`, Repair badge |

**Pass Criteria:** FR record created, status = `under_approval`, file attached  

---

## TC-FR-02 — Submit Failure Registry (Outcome: Replacement)

**User:** ee.tlss@kptcl.com  
**Role:** EE TLSS  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | Login → Sidebar → **Failure Registry** | FR list opens |
| 2 | Click **+ New Failure Report** | Form opens |
| 3 | Failure Date = `2026-04-22`, Category = `Mechanical` | Fields accept |
| 4 | Description = "Tank rupture, oil spillage — beyond repair" | Text field |
| 5 | Outage Duration = `24` hours | Numeric field |
| 6 | Outcome = **Replacement**, Corrective Action = "Full unit replacement needed" | Dropdown |
| 7 | Click **Submit** | FR created, status `under_approval` |
| 8 | Tap new card in list | Detail panel opens, all fields visible, outcome = Replacement |

**Pass Criteria:** FR record created with outcome = Replacement  

---

## TC-FR-03 — Submit Failure Registry (Outcome: Under Investigation)

**User:** originator@kptcl.com  
**Role:** Originator (allowed for failure_registry)  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | Login → **Failure Registry** | FR list |
| 2 | **+ New Failure Report** | Form |
| 3 | Failure Date, Category = `Protection`, Outcome = **Under Investigation** | Fields accept |
| 4 | Leave Section 6 (file upload) blank | No attachment |
| 5 | Click **Submit** | FR created, status `under_approval` |
| 6 | Tap card | Detail panel: has_attachment = false, no file section shown |

**Pass Criteria:** FR created without attachment, outcome = Under Investigation  

---

## TC-FR-04 — Role Blocked: Purchaser Cannot Submit

**User:** purchaser@kptcl.com  
**Role:** Purchaser (not in allowed roles for failure_registry)  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | Login → **Failure Registry** | FR list opens (read access) |
| 2 | Click **+ New Failure Report** | Form may open |
| 3 | Fill all fields, click **Submit** | Error toast: "Your role (Purchaser) is not permitted to submit failure_registry records." |
| 4 | List check | No new FR record created |

**Pass Criteria:** 403 returned, no record created  

---

## TC-FR-05 — Approve FR (Repair) → Auto Repair Work Order Created

**User:** superadmin@system.com  
**Role:** Super Admin / Approver  
**Pre-condition:** TC-FR-01 completed — FR with Repair outcome is pending  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | Login → Sidebar → **Approvals** | Pending list shows FR card with `FAIL` recommendation chip |
| 2 | Tap the FR-Repair card | Right panel: Approval Review opens |
| 3 | Scroll — Recommendation section | Summary: "[Direct Submission] Failure Registry — …" |
| 4 | Scroll — Testing Request section | Equipment UEIC, department visible |
| 5 | Scroll — Test Results section | failure_date, failure_category, outcome = Repair, outage_hours all displayed |
| 6 | Click **Preview Report** (PDF icon top-right) | PDF opens in new tab |
| 7 | Click **Approve** | Spinner |
| 8 | Toast: "Approved successfully" (green) | Panel closes, list refreshes |
| 9 | Toast (teal, 4 sec): "Repair work order **RL-YYYYMMDD-XXXX** created & sent to assigner queue." | Teal snackbar visible |
| 10 | Sidebar → **Testing Requests** | RL- record visible, status = `submitted` |
| 11 | Tap RL- record | Detail: Title = "[Repair] …", description includes source FR number, failure category, failure date |

**Pass Criteria:** RL- auto-created with status=submitted, source FR linked  

---

## TC-FR-06 — Approve FR (Replacement) → Procurement Prompt → Quote Form

**User:** superadmin@system.com  
**Role:** Super Admin / Approver  
**Pre-condition:** TC-FR-02 completed — FR with Replacement outcome is pending  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | Login → **Approvals** | Pending list |
| 2 | Tap FR-Replacement card | Approval Review panel |
| 3 | Scroll Test Results | outcome = Replacement, failure_category = Mechanical visible |
| 4 | Click **Approve** | Spinner → panel closes |
| 5 | Toast: "Approved successfully" | Green snackbar |
| 6 | Dialog appears (within 300ms): **"Initiate Procurement?"** | Modal with cart icon |
| 7 | Dialog body shows: Failure Report / Equipment UEIC / Failure Category / Date of Failure | All FR details pre-loaded in dialog |
| 8 | Click **Not Now** | Dialog closes, stays on Approvals screen, no navigation |
| 9 | Repeat approval on another replacement FR → click **Go to Quote Form** | Dialog closes |
| 10 | App navigates to **Request Quote** screen | Quote form loads |
| 11 | Notes field pre-filled: `[Equipment Replacement Request]\nFailure Report: FR-…\nEquipment UEIC: …\nFailure Category: Mechanical\nDate of Failure: 2026-04-22\n---\nPlease select replacement equipment/parts below.` | Notes textarea populated |
| 12 | Select products from dropdown, adjust quantities | Cart builds |
| 13 | Click **Submit Quote** | Quote submitted to Zoho |

**Pass Criteria:** Pre-filled notes carried to Quote form; no RL- work order created for Replacement  

---

## TC-FR-07 — Reject FR (Invalid Data)

**User:** superadmin@system.com  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | **Approvals** → tap any FR card | Review panel |
| 2 | Click **Reject** | Dialog opens with "Rejection Reason" field |
| 3 | Leave reason blank → click Reject | Validation: "Reason is required" |
| 4 | Enter "Incomplete data — please resubmit with photos" → click Reject | Panel closes |
| 5 | FR status → `rejected` | No RL- work order created |
| 6 | Sidebar → **Failure Registry** → find the FR | Status chip = `rejected` |

**Pass Criteria:** FR rejected, no RL- created, reason stored  

---

## TC-FR-08 — Attach File to Existing FR Record (Post-Submission)

**User:** aee.maintenance@kptcl.com  
**Pre-condition:** An FR exists without an attachment  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | **Failure Registry** → tap FR card (no attachment icon) | Detail panel |
| 2 | Scroll to **Supporting Document** section | Shows "No attachment", Upload button visible |
| 3 | Click **Upload Attachment** | File picker opens |
| 4 | Select a PDF file | |
| 5 | Spinner → toast "File uploaded" | Card shows: file icon, filename, size |
| 6 | Click download icon (↓) | File downloads / opens in viewer |
| 7 | Click **Replace Attachment** → pick different file | Previous file replaced, new file shown |

**Pass Criteria:** File stored, downloadable, replaceable  

---

## TC-FR-09 — FR List — View & Card Indicators

**User:** ee.tlss@kptcl.com  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | **Failure Registry** | List shows all org FR records, newest first |
| 2 | Cards with attachment | Show `📎` (cyan) indicator icon on card |
| 3 | Tap approved FR (Repair) | Detail: status = `approved`, test_data fields displayed |
| 4 | Tap approved FR (Replacement) | Status = `approved`, outcome = Replacement, no linked RL- shown |
| 5 | Tap under_approval FR | Status chip = `under_approval` |
| 6 | Tap rejected FR | Status chip = `rejected` |

**Pass Criteria:** All status states render correctly with correct chips and indicators  

---

## TC-FR-10 — Reports: Failure Resolution Report

**User:** superadmin@system.com  
**Pre-condition:** At least one Repair FR and one Replacement FR are approved  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | Sidebar → **Reports** | Report definition cards list |
| 2 | Find **"Failure Resolution Report"** card | Shows: On Demand, Excel |
| 3 | Click **Run** | Spinner on card |
| 4 | File auto-downloads: `Failure_Resolution_Report_YYYYMMDD_HHMMSS.xlsx` | Download triggers |
| 5 | Open file — verify columns present | `Fr Number`, `Equipment Ueic`, `Equipment Type`, `Make`, `Voltage Class`, `Department`, `Organization`, `Failure Category`, `Failure Date`, `Outcome`, `Outage Hours`, `Fr Status`, `Submitted Date`, `Days Since Failure`, `Repair Tr Number`, `Repair Tr Status`, `Repair Tr Created`, `Submitted By`, `Remarks` |
| 6 | Repair row | `Repair Tr Number` = `RL-YYYYMMDD-XXXX`, `Repair Tr Status` = `submitted` |
| 7 | Replacement row | `Repair Tr Number` blank, `Outcome` = Replacement |
| 8 | Under Investigation row | `Repair Tr Number` blank, `Outcome` = Under Investigation |

**Pass Criteria:** All 19 columns present, repair linkage correct, replacement/investigation rows have no RL-  

---

## TC-FR-11 — Reports: Equipment Failure Annual Report

**User:** superadmin@system.com  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | **Reports** → **Equipment Failure Annual Report** → **Run** | Excel downloads |
| 2 | Open file | Columns: `Equipment Type`, `Make`, `Model Rating`, `Voltage Class`, `Failure Incidents`, `Units Affected`, `Electrical`, `Mechanical`, `Oil`, `Protection`, `Thermal`, `Other Category`, `Repaired`, `Replaced`, `Under Investigation`, `Avg Outage Hours`, `Most Recent Failure` |
| 3 | Verify counts | Electrical column shows count of Electrical failures, Repaired column shows Repair outcomes |

**Pass Criteria:** Report generated, data grouped by equipment type/make  

---

## TC-FR-12 — Reports: Equipment Failure Performance Analysis

**User:** superadmin@system.com  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | **Reports** → **Equipment Failure Performance Analysis** → **Run** | Excel downloads |
| 2 | Open file | Columns include `Age Band`, `Avg Failures Per Unit`, `Avg Outage Hours` |
| 3 | Age band grouping visible | 0-10 years / 10-20 years / 20+ years / Unknown |

**Pass Criteria:** Report generated with age band grouping  

---

## TC-FR-13 — Reports: Repair Lifecycle Progress

**User:** superadmin@system.com  
**Pre-condition:** TC-FR-05 completed — RL- record auto-created  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | **Reports** → **Repair Lifecycle Progress** → **Run** | Excel downloads |
| 2 | Open file | Auto-created RL- record appears with status = `submitted` |
| 3 | Title column | `[Repair] Power Transformer Winding Failure…` |

**Pass Criteria:** RL- created from FR approval visible in repair progress report  

---

## TC-FR-14 — TA&QC Inspection (Separate Category, No Procurement Prompt)

**User:** aee.maintenance@kptcl.com  

| # | Module / Click | Expected Result |
|---|---------------|-----------------|
| 1 | Sidebar → **TA&QC Inspections** | TQ- list |
| 2 | **+ New Inspection** | Form opens (template_key = taqc_inspection) |
| 3 | Fill inspection fields, Overall Result = `advisory` | |
| 4 | Submit | TQ-YYYYMMDD-XXXX created, status `under_approval` |
| 5 | **Approvals** → approve the TQ- record | Panel closes, toast "Approved successfully" |
| 6 | No procurement dialog | No "Initiate Procurement?" prompt appears |
| 7 | No RL- work order | Testing Requests list has no new RL- for this TQ- |

**Pass Criteria:** TQ- approval does not trigger repair or procurement flow  

---

## TC-FR-15 — Role Matrix Verification

**Pre-condition:** One of each role logged in separately  

| User | Failure Registry Submit | TA&QC Submit | Approve | Expected |
|------|:---:|:---:|:---:|---------|
| aee.maintenance@kptcl.com | Yes | Yes | No | 201 / 201 / 403 on approve |
| ee.tlss@kptcl.com | Yes | Yes | No | 201 / 201 |
| originator@kptcl.com | Yes | No | No | 201 / 403 |
| depthead@kptcl.com | Yes | Yes | No | 201 / 201 |
| superadmin@system.com | Yes | Yes | Yes | All pass |
| purchaser@kptcl.com | **No** | **No** | No | 403 / 403 |
| docviewer@kptcl.com | **No** | **No** | No | 403 / 403 |

**Steps per user:**
1. Login with credentials above
2. **Failure Registry** → **+ New Failure Report** → fill → Submit
3. Verify 201 (allowed) or error toast (blocked)

**Pass Criteria:** All role permissions match the matrix above  

---

## Summary

| TC | Scenario | Role | Pass Criteria |
|----|----------|------|---------------|
| FR-01 | Submit FR — Repair + file upload | AEE Maintenance | FR created, file attached |
| FR-02 | Submit FR — Replacement | EE TLSS | FR created, outcome=Replacement |
| FR-03 | Submit FR — Under Investigation | Originator | FR created, no file |
| FR-04 | Role blocked — Purchaser | Purchaser | 403, no record |
| FR-05 | Approve Repair FR → RL- auto-created | Super Admin | RL- in submitted queue |
| FR-06 | Approve Replacement → procurement dialog → Quote form pre-filled | Super Admin | Notes pre-filled in quote |
| FR-07 | Reject FR | Super Admin | FR rejected, no RL- |
| FR-08 | Attach file post-submission | AEE Maintenance | File uploaded, downloadable |
| FR-09 | FR list — card states & attachment indicator | EE TLSS | Chips and icons correct |
| FR-10 | Failure Resolution Report | Super Admin | 19 columns, repair linkage |
| FR-11 | Annual Failure Report | Super Admin | Grouped by type/make |
| FR-12 | Performance Analysis Report | Super Admin | Age band grouping |
| FR-13 | Repair Lifecycle Progress Report | Super Admin | Auto RL- visible |
| FR-14 | TA&QC — no procurement prompt on approval | AEE Maintenance | No dialog, no RL- |
| FR-15 | Role matrix full verification | All roles | Matrix matches |
