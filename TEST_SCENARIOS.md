# SEACMS — UI Test Scenarios
## Equipment Flow · Test Template · Notification Configuration

**System URL:** `http://localhost:53232` (or configured Flutter app URL)  
**API Base:** `http://127.0.0.1:8000`  
**Org:** Karnataka Power Transmission Corporation Limited (KPTCL)  
**Password (all users):** `admin123`

---

## 👤 Test Users & Roles

| Login Email | Role | Equipment Access |
|---|---|---|
| `orgadmin@kptcl.com` | Admin | view + add + edit + delete + export |
| `originator@kptcl.com` | Originator | view + add + edit + export |
| `ee.tlss@kptcl.com` | EE TLSS | view only |
| `see.wm@kptcl.com` | SEE W&M | view only |
| `cee.zone@kptcl.com` | CEE Transmission Zone | view only |
| `aee.maintenance@kptcl.com` | AEE Maintenance | view only |
| `depthead@kptcl.com` | Department Head | view only |
| `fieldtester1@kptcl.com` | Field Tester | no equipment access |
| `testassigner@kptcl.com` | Test Assigner | view only |

---

## 🔷 PART A — EQUIPMENT FLOW

---

### TS-EQ-01 · View Equipment Register (Read-Only Role)

**Login:** `ee.tlss@kptcl.com`  
**Expected role privileges:** view only (no Edit / Retire / Replace buttons)

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in → navigate to **Equipment** module | Equipment list loads; shows cards with UEIC, type, department, status chips |
| 2 | Observe card for `ZO-1A-220-01-PT-01` | Shows `Power Transformer · 110kV Adaki`, status = **active** |
| 3 | Check action buttons on cards | **No** edit ✏️, retire 📥, or replace 🔄 buttons visible |
| 4 | Tap the card | Detail panel slides in with Info + History tabs |
| 5 | Info tab: scroll through Nameplate Data section | Manufacturer, Model, Year, Commissioned Date displayed |
| 6 | Switch to **History** tab | Audit history entries listed (or empty state if no events yet) |
| 7 | Tap **Export CSV** (top bar) | 403 Forbidden or button hidden (EE TLSS has no `can_export`) |
| 8 | Use **Status** filter → select `retired` | List re-filters; previously retired equipment appears |

**Pass criteria:** List, detail view, history tab all load correctly. No write-action buttons visible.

---

### TS-EQ-02 · Create New Equipment (Admin)

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in → Equipment module → tap **+** (Add) | Equipment creation form opens |
| 2 | **Department:** pick `110kV Adaki` from hierarchy | Department selected |
| 3 | **Equipment Type:** select `Power Transformer` | Type set |
| 4 | **Voltage Class:** enter `220` | Accepted |
| 5 | **Bay Number:** enter `Bay-03` | Accepted |
| 6 | **Manufacturer:** `Siemens` | Accepted |
| 7 | **Model Number:** `PTX-220` | Accepted |
| 8 | **Factory Serial:** `SIE-2026-003` | Accepted |
| 9 | **Year of Manufacture:** `2026` | Accepted |
| 10 | **Commissioned Date:** `2026-05-04` | Date accepted |
| 11 | Tap **Save** | Success toast; new equipment appears in list |
| 12 | Verify UEIC auto-generated | UEIC format: `ZO-1A-220-03-PT-01` (zone-substation-voltage-bay-type-seq) |
| 13 | Tap the new card | Detail shows all entered fields; status = `active` |

**Pass criteria:** Equipment created with auto-UEIC. All fields saved correctly.

---

### TS-EQ-03 · Edit Equipment (Originator Role)

**Login:** `originator@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Navigate to Equipment → find `ZO-1A-220-01-PT-01` | Card visible; ✏️ Edit button present |
| 2 | Tap **Edit** | Edit form pre-populated with existing values |
| 3 | Change **Manufacturer** to `ABB` | Field updated |
| 4 | Change **Year of Manufacture** to `2020` | Field updated |
| 5 | Tap **Save** | Success toast |
| 6 | Open equipment detail | Updated manufacturer `ABB` and year `2020` shown |
| 7 | Check that **Retire** and **Replace** are absent | Originator has no `can_delete` — buttons should be hidden |

**Pass criteria:** Edit persists. Retire/Replace hidden for Originator.

---

### TS-EQ-04 · Retire Equipment (Admin)

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Find active equipment `ZO-1A-110-02-PT-01` | Status = `active` |
| 2 | Tap 📥 **Retire** icon on card | Confirmation dialog with Reason text field appears |
| 3 | Leave reason blank → tap **Confirm** | Validation error: reason is required |
| 4 | Enter reason: `End of planned service life` | Text accepted |
| 5 | Tap **Confirm** | Success snackbar: "Equipment retired successfully" |
| 6 | List auto-refreshes | Card now shows status chip = **retired** (orange) |
| 7 | Open detail panel | **Retirement** section shows: Retired Date + Reason |
| 8 | Confirm `retired` equipment has no Replace/Edit buttons | Retired equipment cannot be modified further |

**Pass criteria:** Equipment status flips to retired. Retirement section shows in detail.

---

### TS-EQ-05 · Replace Equipment — reason_type = `other` (Admin)

**Login:** `orgadmin@kptcl.com`  
**Prerequisite:** At least one active equipment in list (e.g. `ZO-1AN-220-01-CT-01`)

| # | Step | Expected Result |
|---|---|---|
| 1 | Find `ZO-1AN-220-01-CT-01` (Current Transformer, active) | Card with 🔄 Replace button |
| 2 | Tap **Replace** | Replace Equipment dialog opens |
| 3 | **Reason Type:** select `Other (with Analysis Report)` | Report upload field appears (required) |
| 4 | Attempt to submit without uploading report | Validation error: analysis report required |
| 5 | Upload a PDF file (`analysis_report.pdf`) | File name shown; upload indicator clears |
| 6 | **Reason text:** `IR test failed — IR value: 42 MΩ (threshold: 100 MΩ)` | Text accepted |
| 7 | **Manufacturer (new unit):** `Alstom` | Accepted |
| 8 | **Model Number:** `CT-220-ALT` | Accepted |
| 9 | **Year of Manufacture:** `2026` | Accepted |
| 10 | **Commissioned Date:** `2026-05-04` | Accepted |
| 11 | Tap **Submit** | Loading spinner; success dialog appears |
| 12 | Success dialog shows | **Retired:** `ZO-1AN-220-01-CT-01` (orange) + **New UEIC:** `ZO-1AN-220-01-CT-02` (green) |
| 13 | Dialog has **Download Replacement Report** button | Button visible (purple outline) |
| 14 | Tap **Download Replacement Report** | PDF download starts; snackbar: "Replacement report downloaded (XXXX bytes)" |
| 15 | Tap **OK** | Dialog closes; list refreshes |
| 16 | Find `ZO-1AN-220-01-CT-01` in list | Status = **retired** (orange); shows `→ ZO-1AN-220-01-CT-02` green badge |
| 17 | Find `ZO-1AN-220-01-CT-02` in list | Status = **active**; shows `↩ ZO-1AN-220-01-CT-01` purple badge |
| 18 | Open retired unit detail | **Replacement Chain** section shows: "Replaced By (New): `ZO-1AN-220-01-CT-02`" |
| 19 | Open new unit detail | **Replacement Chain** section shows: "Replaces (Retired): `ZO-1AN-220-01-CT-01`"; **Download Replacement Report** button visible |

**Pass criteria:** Both chain directions visible in cards and detail panel. PDF report downloadable. Both UEICs shown in success dialog.

---

### TS-EQ-06 · Replacement Notification — Email/SMS/In-App

**Login sequence:** Trigger replace as Admin, then check notifications as role recipients.

| # | User | Step | Expected Result |
|---|---|---|---|
| 1 | `orgadmin@kptcl.com` | Complete replacement (TS-EQ-05) | Replace succeeds |
| 2 | `ee.tlss@kptcl.com` | Log in → Bell icon 🔔 | Unread badge shows new count |
| 3 | `ee.tlss@kptcl.com` | Open Notifications | Entry: "Equipment replaced — CT-01 → CT-02" or similar |
| 4 | `ee.tlss@kptcl.com` | Tap notification | Navigates to equipment or shows detail |
| 5 | `see.wm@kptcl.com` | Log in → Bell 🔔 | Same replacement notification present |
| 6 | `cee.zone@kptcl.com` | Log in → Bell 🔔 | Same replacement notification present |
| 7 | `depthead@kptcl.com` | Log in → Bell 🔔 | Same replacement notification present |
| 8 | `fieldtester1@kptcl.com` | Log in → Bell 🔔 | **No** replacement notification (Field Tester not in recipient roles) |
| 9 | — | Check server notification_log | 4 email rows (EE TLSS, SEE W&M, CEE Zone, Dept Head) + 3 SMS rows (status=skipped if no phone) — all bodies rendered with real UEICs, no `{{}}` placeholders |

**Pass criteria:** Only configured recipient roles receive notifications. In-app bell shows for all 4 roles.

---

### TS-EQ-07 · Export Equipment CSV

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Equipment list → tap **Export CSV** | File download starts |
| 2 | Open CSV | Headers: `UEIC, Equipment Type, Department, Status, Voltage Class, Bay Number, Manufacturer, Model, Serial, Year, Commissioned Date` |
| 3 | Verify row count ≥ 27 | Matches seeded data |
| 4 | Filter by `status = retired` → Export | CSV contains only retired equipment |
| 5 | Log out; log in as `fieldtester1@kptcl.com` → try Export | Export button hidden or returns 403 |

---

### TS-EQ-08 · Stats Counts Widget

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Equipment list top bar | Stats row: Total · Active · Repair · Retired · Scrapped |
| 2 | Retire one equipment (TS-EQ-04) | **Retired** counter increments by 1 |
| 3 | Replace one equipment (TS-EQ-05) | **Retired** +1, **Active** stays same (new unit added) |
| 4 | Filter by `active` | List shows only active; counts reflect total (not filtered) |

---

### TS-EQ-09 · RBAC — No Access (Field Tester)

**Login:** `fieldtester1@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Navigate to Equipment module | Access denied screen OR Equipment not in nav menu |
| 2 | Attempt direct URL navigation | 403 / redirect |
| 3 | Bell 🔔 icon | In-app notifications visible (Field Tester has notification access) |

---

## 🔷 PART B — TEST TEMPLATE MODIFICATION

---

### TS-TT-01 · View and Edit Equipment Test Template (Admin)

**Login:** `orgadmin@kptcl.com`  
**Navigate to:** Settings → Test Templates (or Organisation → Test Templates)

| # | Step | Expected Result |
|---|---|---|
| 1 | Open Test Templates list | Shows seeded templates: IR Test, PI Test, HV Test, CT Ratio, etc. |
| 2 | Find template for **Power Transformer – IR Test** | Template listed with equipment type, test type, parameters |
| 3 | Tap to open template | Shows parameter list: each parameter has name, unit, min/max thresholds, eval bands (NORMAL / ALERT / CRITICAL) |
| 4 | Tap **Edit** | Template edit form opens |
| 5 | Locate **IR Value** parameter | Shows current threshold: ALERT < 100 MΩ, CRITICAL < 50 MΩ |
| 6 | Change CRITICAL threshold to `75` MΩ | Value updated in form |
| 7 | Change ALERT threshold to `150` MΩ | Value updated |
| 8 | Tap **Save** | Success toast |
| 9 | Reopen template | Updated thresholds (75 / 150 MΩ) persisted |
| 10 | Submit a test result with IR = 80 MΩ | Evaluation result = **ALERT** (80 < 150 but > 75) |
| 11 | Submit a test result with IR = 60 MΩ | Evaluation result = **CRITICAL** (60 < 75) |

**Pass criteria:** Threshold changes take effect on next evaluation run.

---

### TS-TT-02 · Add New Parameter to Template

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open Power Transformer IR Test template → Edit | Template edit form |
| 2 | Tap **+ Add Parameter** | New parameter row appears |
| 3 | Name: `Absorption Ratio`, Unit: `ratio`, Min: `0`, Max: `10` | Fields accepted |
| 4 | Set eval bands: ALERT < 1.0, CRITICAL < 0.8 | Bands set |
| 5 | Save template | Success |
| 6 | Navigate to new testing request for a Power Transformer | Test form shows the new `Absorption Ratio` parameter field |

---

### TS-TT-03 · Clone Template for Different Equipment Type

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open CT Ratio Test template | Template displayed |
| 2 | Tap **Clone / Duplicate** | New template form pre-filled with same parameters |
| 3 | Change equipment type to `Current Transformer` | Type selected |
| 4 | Modify a threshold | Value updated |
| 5 | Save | New template saved; original unchanged |
| 6 | List templates | Both original and clone listed |

---

## 🔷 PART C — NOTIFICATION TEMPLATE CONFIGURATION

---

### TS-NT-01 · View Default Notification Templates (Admin)

**Login:** `orgadmin@kptcl.com`  
**Navigate to:** Settings → Notifications → Templates

| # | Step | Expected Result |
|---|---|---|
| 1 | Open Notification Templates | List of 11 event types; each shows channel toggles [Email] [SMS] [In-App] |
| 2 | Find **Equipment Replacement** event | Shows Email ● / SMS ● / In-App ● all enabled (global defaults) |
| 3 | Find **Eval Critical** event | Email ● / In-App ● enabled; SMS ○ (no SMS template) |
| 4 | Check "Global" badge on each template | All show "Global Default" — no org override yet |
| 5 | Open variable picker (system variables list) | 29 variables shown grouped: Reports, Equipment, Replacement, Test Request, Evaluation, Organisation, System |

---

### TS-NT-02 · Edit Equipment Replacement Template — Change Recipients

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open **Equipment Replacement** template | Shows Email + SMS + In-App channels |
| 2 | Current recipient roles: `EE TLSS, SEE W&M, CEE Transmission Zone, Department Head` | Roles shown as chips |
| 3 | **Remove** `Department Head` from roles | Chip removed |
| 4 | **Add** `AEE Maintenance` to roles | New chip added |
| 5 | Extra emails: add `audit@kptcl.com` | Email chip added |
| 6 | Tap **Save** | Org-specific override created |
| 7 | Template now shows "Org Override" badge | Override indicator visible |
| 8 | Trigger a replacement (TS-EQ-05) | Notifications sent to: EE TLSS, SEE W&M, CEE Zone, AEE Maintenance + audit@kptcl.com |
| 9 | Log in as `depthead@kptcl.com` → Bell | **No** replacement notification (Department Head removed) |
| 10 | Log in as `aee.maintenance@kptcl.com` → Bell | **Yes** replacement notification (AEE Maintenance added) |

**Pass criteria:** Role change in template immediately affects who receives the next notification.

---

### TS-NT-03 · Customize Equipment Replacement Email Body

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open **Equipment Replacement** → Email channel | Body editor shows current HTML template |
| 2 | Tap **Variable Picker** | Picker opens showing groups: Reports, Equipment, Replacement, Test Request, Evaluation, System |
| 3 | Expand **Reports** group | Shows `{{report.retriepdf}}`, `{{report.retriexls}}`, `{{report.ref}}`, `{{report.generated_on}}` |
| 4 | Tap `{{report.retriepdf}}` | Variable inserted at cursor in body editor |
| 5 | Expand **Replacement** group | Shows `{{old_ueic}}`, `{{new_ueic}}`, `{{replaced_by}}`, `{{replaced_on}}`, `{{reason}}` |
| 6 | Add custom text: `"Report available at: {{report.retriepdf}}"` | Inserted in body |
| 7 | Preview tab | Shows rendered preview with sample values: `Report available at: https://app.seacms.in/reports/REQ-001.pdf` |
| 8 | Save template | Override saved |
| 9 | Trigger replacement | Email body contains rendered PDF URL (not raw `{{report.retriepdf}}`) |

---

### TS-NT-04 · Disable SMS Channel for Equipment Replacement

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open Equipment Replacement template | All channels enabled: [● Email] [● SMS] [● In-App] |
| 2 | Toggle **SMS** off → [○ SMS] | SMS disabled |
| 3 | Save | Org override with email + inapp only |
| 4 | Trigger replacement | notification_log: email rows (status=pending→sent); **no** SMS rows for this org |

---

### TS-NT-05 · Add Custom Notification Variable

**Login:** `orgadmin@kptcl.com`  
**Navigate to:** Settings → Notifications → Variables

| # | Step | Expected Result |
|---|---|---|
| 1 | Variables list | Shows 29 system variables with group tabs; system vars have lock icon 🔒 |
| 2 | Tap **+ Add Variable** | Create variable form opens |
| 3 | **Variable Key:** `custom.zone_officer` | Accepted |
| 4 | **Label:** `Zone Officer Name` | Accepted |
| 5 | **Group:** `Custom` | Group set |
| 6 | **Description:** `Name of the responsible Zone Officer` | Accepted |
| 7 | **Sample Value:** `Mr. Venkatesh (EE TLSS)` | Accepted |
| 8 | Save | New variable appears in list; no 🔒 icon (deletable) |
| 9 | Open Equipment Replacement email template → Variable Picker | `Custom` group appears with `{{custom.zone_officer}}` |
| 10 | Insert `{{custom.zone_officer}}` in body | Inserted; preview shows sample value |

---

### TS-NT-06 · System Variable — Cannot Delete

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Variables list → find `{{report.retriepdf}}` (system var) | Row has 🔒 lock icon; **no** delete button |
| 2 | Tap row → Edit | Can edit `sample_value` and `description` only; key/group locked |
| 3 | Change sample value to `https://seacms.kptcl.gov.in/reports/sample.pdf` | Saved |
| 4 | Open template Variable Picker → hover/tap `{{report.retriepdf}}` | Updated sample value shown in preview |

---

### TS-NT-07 · Reset Org Template to Global Default

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Equipment Replacement template shows "Org Override" badge | Org-specific version active |
| 2 | Tap **Reset to Global Default** / **Delete Override** | Confirmation dialog |
| 3 | Confirm | Org override deactivated; global default active again |
| 4 | Template badge changes back to "Global Default" | Original roles / body restored |
| 5 | Trigger replacement | Notifications sent per global default roles (EE TLSS, SEE W&M, CEE Zone, Dept Head) |

---

### TS-NT-08 · In-App Notification Centre (Mark Read / Unread Count)

**Login:** `ee.tlss@kptcl.com`  
**Prerequisite:** TS-EQ-05 replacement triggered (ee.tlss gets notification)

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in | Bell 🔔 shows badge with unread count (e.g. `2`) |
| 2 | Tap bell | Notifications list: severity chips (CRITICAL=red, ALERT=orange, INFO=blue) |
| 3 | Tap one notification | Marked as read; badge decrements |
| 4 | Tap **Mark All Read** | Badge goes to `0` |
| 5 | Filter by `severity = critical` | Only critical-level notifications shown |
| 6 | Filter by `severity = info` | Equipment replacement notifications shown |
| 7 | Scroll to bottom | Older notifications paginated |

---

### TS-NT-09 · Eval Critical Notification — End-to-End

**Login sequence:** Admin submits test → eval fires notification → role users see alert

| # | User | Step | Expected Result |
|---|---|---|---|
| 1 | `originator@kptcl.com` | Submit testing request for `ZO-1A-220-01-PT-01` | Request created |
| 2 | `orgadmin@kptcl.com` | Assign tester | `fieldtester1@kptcl.com` assigned |
| 3 | `fieldtester1@kptcl.com` | Submit test results with IR = 40 MΩ (< CRITICAL 50 MΩ threshold) | Test submitted; evaluation runs |
| 4 | System | `eval_critical` notification fired | notification_log: email to Dept Head, Approver, Originator |
| 5 | `depthead@kptcl.com` | Bell 🔔 | New notification: "⚠️ CRITICAL — `ZO-1A-220-01-PT-01`" |
| 6 | `originator@kptcl.com` | Bell 🔔 | Same critical notification |
| 7 | `ee.tlss@kptcl.com` | Bell 🔔 | **No** notification (EE TLSS not in eval_critical recipient roles) |

---

## 🔷 PART D — CROSS-CUTTING SCENARIOS

---

### TS-CC-01 · Notification Digest (High Volume)

| # | Step | Expected Result |
|---|---|---|
| 1 | Trigger 11+ replacements within 5 minutes (admin) | After 10 replacements, digest threshold hit |
| 2 | Background job runs | Individual pending emails collapsed into 1 digest email per recipient |
| 3 | notification_log | Individual rows status = `digested`; digest row status = `sent` |

---

### TS-CC-02 · Notification Retry on Email Failure

| # | Step | Expected Result |
|---|---|---|
| 1 | Temporarily set invalid SMTP password in `.env` | Misconfigured mail server |
| 2 | Trigger replacement | email log rows created with status = `pending` |
| 3 | 1-minute job runs | Status flips to `failed`; `retry_count = 1`; `next_retry_at` set |
| 4 | Restore correct SMTP password | — |
| 5 | 5-minute retry job runs | Status flips to `sent` |

---

### TS-CC-03 · Equipment History Trail

**Login:** `orgadmin@kptcl.com`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open equipment `ZO-1AN-220-01-CT-01` (was replaced in TS-EQ-05) | Detail panel |
| 2 | History tab | Entries: Created → Retired (with replacement reference) |
| 3 | Open replacement `ZO-1AN-220-01-CT-02` → History tab | Entries: Created (as replacement) |
| 4 | Verify old UEIC (`CT-01`) data still accessible | Retired equipment fully readable; no data loss |

---

## 📋 SUMMARY TABLE

| Scenario | Area | Login | Key Assertion |
|---|---|---|---|
| TS-EQ-01 | Equipment list / detail | `ee.tlss@kptcl.com` | View-only; no write buttons |
| TS-EQ-02 | Create equipment | `orgadmin@kptcl.com` | Auto-UEIC generated |
| TS-EQ-03 | Edit equipment | `originator@kptcl.com` | Edit persists; retire hidden |
| TS-EQ-04 | Retire equipment | `orgadmin@kptcl.com` | Status = retired; reason stored |
| TS-EQ-05 | Replace equipment | `orgadmin@kptcl.com` | Chain badges, PDF report download |
| TS-EQ-06 | Replacement notification | All roles | Correct roles receive; no leakage |
| TS-EQ-07 | CSV export | `orgadmin@kptcl.com` | Correct headers & data |
| TS-EQ-08 | Stats widget | `orgadmin@kptcl.com` | Counts update after lifecycle events |
| TS-EQ-09 | RBAC no access | `fieldtester1@kptcl.com` | Equipment module blocked |
| TS-TT-01 | Edit test template thresholds | `orgadmin@kptcl.com` | Thresholds affect evaluation |
| TS-TT-02 | Add parameter | `orgadmin@kptcl.com` | New param appears in test form |
| TS-TT-03 | Clone template | `orgadmin@kptcl.com` | Clone independent of original |
| TS-NT-01 | View default templates | `orgadmin@kptcl.com` | 11 event types; 29 variables |
| TS-NT-02 | Edit recipient roles | `orgadmin@kptcl.com` | Role change takes effect immediately |
| TS-NT-03 | Customize email body | `orgadmin@kptcl.com` | `{{variables}}` rendered in email |
| TS-NT-04 | Disable SMS channel | `orgadmin@kptcl.com` | No SMS rows in log for org |
| TS-NT-05 | Custom variable | `orgadmin@kptcl.com` | Appears in variable picker |
| TS-NT-06 | System variable — no delete | `orgadmin@kptcl.com` | 🔒 lock; key non-editable |
| TS-NT-07 | Reset to global default | `orgadmin@kptcl.com` | Org override removed |
| TS-NT-08 | In-app notification centre | `ee.tlss@kptcl.com` | Badge, read/unread, severity filter |
| TS-NT-09 | Eval critical end-to-end | Multiple | Only configured roles notified |
| TS-CC-01 | Digest on high volume | Admin | Digest collapses >10 notifications |
| TS-CC-02 | Email retry on failure | Admin | Retry after SMTP restore |
| TS-CC-03 | Equipment history trail | Admin | Full audit trail; retired data accessible |

---

*Generated: 2026-05-04 · SEACMS Equipment & Notification Test Suite*
