# SEACMS — Complete UI Test Scenarios
## Equipment Flow · Notification Template Configuration · Template Design

**System URL:** `http://localhost:53232`  
**API Base:** `http://127.0.0.1:8000`  
**Org:** Karnataka Power Transmission Corporation Limited (KPTCL)  
**Password (all users):** `admin123`

---

## 👤 Users, Roles & Permissions Matrix

| Login Email | Role | Equipment | Notification Templates | In-App Bell |
|---|---|---|---|---|
| `orgadmin@kptcl.com` | **Org Admin** | view + add + edit + delete + export | ✅ Full CRUD | ✅ |
| `originator@kptcl.com` | Originator | view + add + edit + export | ❌ 403 | ✅ |
| `ee.tlss@kptcl.com` | EE TLSS | view + export | ❌ 403 | ✅ |
| `see.wm@kptcl.com` | SEE W&M | view only | ❌ 403 | ✅ |
| `cee.zone@kptcl.com` | CEE Transmission Zone | view only | ❌ 403 | ✅ |
| `aee.maintenance@kptcl.com` | AEE Maintenance | view only | ❌ 403 | ✅ |
| `depthead@kptcl.com` | Department Head | view only | ❌ 403 | ✅ |
| `fieldtester1@kptcl.com` | Field Tester | ❌ No access | ❌ 403 | ✅ |
| `testassigner@kptcl.com` | Test Assigner | view only | ❌ 403 | ✅ |

### RBAC Quick Reference

| Permission | Admin | Originator | EE TLSS | SEE W&M | CEE Zone | AEE Maint | Dept Head | Field Tester |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| View equipment | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Add equipment | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Edit equipment | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Retire equipment | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Replace equipment | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Export CSV | ✅ | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Manage notif templates | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Receive in-app notifs | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 🏷️ Seeded Equipment Reference (KPTCL)

| UEIC | Type | Substation | Status |
|---|---|---|---|
| `ZO-1A-220-01-PT-01` | Power Transformer | 110kV Adaki | active |
| `ZO-1A-110-02-PT-01` | Power Transformer | 110kV Adaki | active |
| `ZO-1AN-220-01-CT-01` | Current Transformer | 220kV Annigeri | active |
| `ZO-1AN-220-01-CVT-01` | Capacitive Voltage Transformer | 220kV Annigeri | active |
| `ZO-1A-220-01-CB-01` | Circuit Breaker | 110kV Adaki | active |
| `ZO-1A-220-01-DS-01` | Disconnect Switch | 110kV Adaki | active |

---

## ═══════════════════════════════════════
## PART A — EQUIPMENT FLOW
## ═══════════════════════════════════════

---

### TS-EQ-01 · View Equipment Register (Read-Only Role)

**Login:** `ee.tlss@kptcl.com` / `admin123`  
**Role:** EE TLSS — view + export only

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in → navigate to **Equipment** module | Equipment list loads; cards show UEIC, type, department, status chip |
| 2 | Observe card for `ZO-1A-220-01-PT-01` | Shows `Power Transformer · 110kV Adaki` · status = **active** (green) |
| 3 | Check action buttons on card | **No** ✏️ Edit, 📥 Retire, or 🔄 Replace buttons visible |
| 4 | Tap the card to open detail panel | Detail panel slides in from right — Info tab active |
| 5 | Info tab — scroll Nameplate Data section | Manufacturer, Model Number, Year, Commissioned Date displayed |
| 6 | Switch to **History** tab | Audit entries listed (or empty state "No history yet") |
| 7 | Tap **Export CSV** button in top bar | Button hidden or returns 403 — EE TLSS has no `can_export` |
| 8 | Use **Status** filter chip → select `retired` | List re-filters; retired equipment appears with orange status chip |
| 9 | Clear filter → apply **Search** by UEIC `ZO-1AN` | Only Annigeri substation equipment shown |

**Pass criteria:** Read-only view loads correctly. Zero write-action buttons. Export blocked.

---

### TS-EQ-02 · Create New Equipment (Admin)

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Equipment module → tap **+** (FAB or Add button) | Equipment creation form / bottom sheet opens |
| 2 | **Department:** tap hierarchy → select `110kV Adaki` | Department field filled |
| 3 | **Equipment Type:** select `Power Transformer` | Type set; nameplate template loads |
| 4 | **Voltage Class:** `220` | Accepted |
| 5 | **Bay Number:** `Bay-03` | Accepted |
| 6 | **Manufacturer:** `Siemens` | Accepted |
| 7 | **Model Number:** `PTX-220-S` | Accepted |
| 8 | **Factory Serial Number:** `SIE-2026-003` | Accepted |
| 9 | **Year of Manufacture:** `2026` | Accepted |
| 10 | **Commissioned Date:** `2026-05-04` | Date picker → date accepted |
| 11 | Tap **Save** | Success snackbar; new card appears at top of list |
| 12 | Verify auto-generated UEIC | Format: `ZO-1A-220-03-PT-01` (zone·substation·voltage·bay·type·seq) |
| 13 | Tap new card → detail panel | All entered fields shown; status = **active** |

**Pass criteria:** Equipment created with correct auto-UEIC. All fields persisted.

---

### TS-EQ-03 · Edit Equipment (Originator Role)

**Login:** `originator@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Equipment list → find `ZO-1A-220-01-PT-01` | Card visible; ✏️ Edit icon present |
| 2 | Tap ✏️ **Edit** | Edit form pre-populated with current values |
| 3 | Change **Manufacturer** to `ABB` | Field updated |
| 4 | Change **Year of Manufacture** to `2020` | Field updated |
| 5 | Tap **Save** | Success snackbar |
| 6 | Open equipment detail | Updated fields: `ABB` · `2020` |
| 7 | Check card action buttons | **No** 📥 Retire or 🔄 Replace — Originator has no `can_delete` |

**Pass criteria:** Edit persists. Retire/Replace buttons absent for Originator.

---

### TS-EQ-04 · Retire Equipment (Admin)

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Find active equipment `ZO-1A-110-02-PT-01` | Status chip = **active** (green) |
| 2 | Tap 📥 **Retire** icon on card | Retirement confirmation dialog appears with Reason text field |
| 3 | Tap **Confirm** with reason field blank | Validation error: "Reason is required" |
| 4 | Enter reason: `End of planned service life — 25-year cycle` | Text accepted |
| 5 | Tap **Confirm** | Success snackbar: "Equipment retired successfully" |
| 6 | List auto-refreshes | Card status chip → **retired** (orange) |
| 7 | Open detail panel | **Retirement** section shows: Retired Date + Reason text |
| 8 | Check card action buttons | **No** ✏️ Edit, 🔄 Replace buttons — retired equipment locked |

**Pass criteria:** Status → retired. Reason stored. Card locked from further edits.

---

### TS-EQ-05 · Replace Equipment — Reason Type `other` (Admin)

**Login:** `orgadmin@kptcl.com` / `admin123`  
**Prerequisite:** `ZO-1AN-220-01-CT-01` is active

| # | Step | Expected Result |
|---|---|---|
| 1 | Find `ZO-1AN-220-01-CT-01` (Current Transformer) | Card with 🔄 **Replace** button |
| 2 | Tap 🔄 **Replace** | Replace Equipment dialog opens — Step 1 of 2 |
| 3 | **Step 1 — Reason Type:** select `Other reason` | PDF upload field appears (marked required *) |
| 4 | Tap **Next** without uploading PDF | Validation error: "Analysis report PDF is required for this reason type" |
| 5 | Tap **Choose PDF** → pick `analysis_report.pdf` | File chip appears: `📎 analysis_report.pdf (42 KB) ×` |
| 6 | **Reason / Notes:** `IR test failed — measured 42 MΩ, threshold 100 MΩ` | Text accepted |
| 7 | Tap **Next** → Step 2 of 2 | New equipment nameplate form |
| 8 | **Manufacturer:** `Alstom` | Accepted |
| 9 | **Model Number:** `CT-220-ALT` | Accepted |
| 10 | **Factory Serial:** `ALT-2026-007` | Accepted |
| 11 | **Year of Manufacture:** `2026` | Accepted |
| 12 | **Commissioned Date:** `2026-05-04` | Date picker accepted |
| 13 | Tap **Submit Replace** | Loading spinner; API call made |
| 14 | Success dialog appears | Header: ✅ Equipment Replaced |
| 15 | Dialog — Retired row | 🟠 **Retired:** `ZO-1AN-220-01-CT-01` (orange box) |
| 16 | Dialog — New row | 🟢 **Replacement:** `ZO-1AN-220-01-CT-02` (green box) |
| 17 | Dialog — report button | **Download Replacement Report** button visible (purple outline) |
| 18 | Tap **Download Replacement Report** | PDF download starts; snackbar: "Report downloaded (XXXX bytes)" |
| 19 | Tap **OK** | Dialog closes; list refreshes |
| 20 | Find `ZO-1AN-220-01-CT-01` | Status = **retired** (orange); green badge `→ ZO-1AN-220-01-CT-02` |
| 21 | Find `ZO-1AN-220-01-CT-02` | Status = **active** (green); purple badge `↩ ZO-1AN-220-01-CT-01` |
| 22 | Open retired unit detail → **REPLACEMENT CHAIN** section | Shows: "Replaced By (New): `ZO-1AN-220-01-CT-02`" |
| 23 | Open new unit detail → **REPLACEMENT CHAIN** section | Shows: "Replaces (Retired): `ZO-1AN-220-01-CT-01`" + **Download Report** button |

**Pass criteria:** Both chain directions in cards and detail. PDF downloadable from dialog and detail panel. Both UEICs shown.

---

### TS-EQ-06 · Replace Equipment — Reason Type `recommendation_compliance`

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Find `ZO-1A-220-01-CB-01` (Circuit Breaker, active) | 🔄 Replace button present |
| 2 | Tap Replace | Step 1 dialog |
| 3 | **Reason Type:** select `Based on test recommendation` | Report upload field not required (optional) |
| 4 | **Recommendation ID:** `REC-2026-001` | Field accepted |
| 5 | **Reason / Notes:** `Breakdown mechanism worn — per REC-2026-001` | Accepted |
| 6 | Tap **Next** without uploading PDF | Proceeds to Step 2 (PDF optional for this reason type) |
| 7 | Fill new equipment nameplate fields | All accepted |
| 8 | Tap **Submit Replace** | Success dialog |

**Pass criteria:** PDF not required for `recommendation_compliance`. Recommendation ID saved.

---

### TS-EQ-07 · Replacement Notification Delivery (Multi-Role)

**Login sequence:** Trigger as Admin → verify as recipient roles  
**Prerequisite:** `equipment_replacement` In-App channel enabled; roles: `EE TLSS`, `SEE W&M`, `CEE Transmission Zone`, `Department Head`

| # | User | Step | Expected Result |
|---|---|---|---|
| 1 | `orgadmin@kptcl.com` | Complete TS-EQ-05 replacement | Replace succeeds |
| 2 | `ee.tlss@kptcl.com` | Log in → tap 🔔 bell | Unread badge count > 0 |
| 3 | `ee.tlss@kptcl.com` | Open notification list | Entry: Equipment Replacement — `CT-01 → CT-02` |
| 4 | `see.wm@kptcl.com` | Log in → 🔔 bell | Same replacement notification |
| 5 | `cee.zone@kptcl.com` | Log in → 🔔 bell | Same replacement notification |
| 6 | `depthead@kptcl.com` | Log in → 🔔 bell | Same replacement notification |
| 7 | `fieldtester1@kptcl.com` | Log in → 🔔 bell | **No** replacement notification — Field Tester not in recipient roles |
| 8 | `aee.maintenance@kptcl.com` | Log in → 🔔 bell | **No** notification unless AEE Maintenance added to roles |

**Pass criteria:** Only configured recipient roles receive notification. No leakage to excluded roles.

---

### TS-EQ-08 · Export Equipment CSV

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Equipment list → tap **Export CSV** | File download begins |
| 2 | Open CSV | Headers: `UEIC, Equipment Type, Department, Status, Voltage Class, Bay, Manufacturer, Model, Serial, Year, Commissioned Date` |
| 3 | Count data rows | ≥ 27 rows matching seeded data |
| 4 | Apply filter `Status = retired` → Export | CSV contains only retired equipment rows |
| 5 | Log out → log in as `fieldtester1@kptcl.com` → attempt Export | Export button absent OR 403 returned |

**Pass criteria:** CSV headers correct; row count ≥ 27; RBAC enforced on export.

---

### TS-EQ-09 · Equipment Stats Counts Widget

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Equipment list top bar | Stats row: **Total · Active · Repair · Retired · Scrapped** |
| 2 | Note current Active count (e.g. 24) | Baseline recorded |
| 3 | Retire one equipment (TS-EQ-04) | **Retired** counter +1; **Active** −1 |
| 4 | Replace one equipment (TS-EQ-05) | **Retired** +1; **Active** unchanged (new unit added = net zero) |

**Pass criteria:** Counters reflect actual state changes after each lifecycle operation.

---

### TS-EQ-10 · RBAC — No Equipment Access (Field Tester)

**Login:** `fieldtester1@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in | Dashboard loads |
| 2 | Look for Equipment in navigation | Equipment module not visible in nav menu |
| 3 | Attempt direct URL navigation to Equipment page | 403 screen or redirect to dashboard |
| 4 | Tap 🔔 bell icon | In-app notifications panel opens (Field Tester receives notifications) |

**Pass criteria:** Equipment module inaccessible. Bell/notifications accessible.

---

### TS-EQ-11 · Equipment Detail — Nameplate File Preview

**Login:** `orgadmin@kptcl.com` / `admin123`  
**Prerequisite:** Equipment has a nameplate file attached (e.g. uploaded during creation)

| # | Step | Expected Result |
|---|---|---|
| 1 | Open equipment detail panel | Info tab visible |
| 2 | Scroll to **Nameplate Files** section | File rows listed: `nameplate_scan.pdf (120 KB)` |
| 3 | Tap 👁️ **Preview** icon | Dialog opens with file content |
| 4 | File is image (jpg/png) | Image renders with `InteractiveViewer` (pinch-to-zoom) |
| 5 | File is PDF | PDF icon + filename + "PDF preview not available in this view" message |
| 6 | File size shown in header | `(120.4 KB)` |
| 7 | Tap ✕ close | Dialog dismisses |

**Pass criteria:** Image files render inline. PDF shows placeholder. Size visible in header.

---

## ═══════════════════════════════════════
## PART B — NOTIFICATION TEMPLATE CONFIGURATION UI
## ═══════════════════════════════════════

### Navigation
```
Login as orgadmin@kptcl.com → My Organization → Notifications tab (4th tab)
```

---

### TS-NT-01 · Non-Admin Blocked from Notification Templates

**Login:** `ee.tlss@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in → My Organization | Org Detail page opens |
| 2 | 4 tabs visible | Departments · Users · Roles · **Notifications** |
| 3 | Tap **Notifications** tab | Spinner → error state |
| 4 | Error message shown | "Only org admins can manage notification templates." |
| 5 | No event cards rendered | Content area shows access-denied message |
| 6 | Repeat with `fieldtester1@kptcl.com` | Same result — tab visible but content blocked |

**Pass criteria:** Tab is visible to all users. Content requires admin role.

---

### TS-NT-02 · Admin Loads Event Type Catalogue

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in → My Organization → Notifications tab | Spinner → list renders |
| 2 | Info banner at top | "Tap any event to configure its channels…" (blue info bar) |
| 3 | Section headers visible | **EQUIPMENT · EVALUATION · TEST WORKFLOW · SCHEDULING · RECOMMENDATIONS** |
| 4 | Count event cards | 11 total across 5 groups |
| 5 | `Equipment Replacement` card | Channel badges: **● Email · ● SMS · ● In-App** (all seeded) |
| 6 | `recommendation_approved` card | Shows orange "Not configured" text — no templates yet |
| 7 | Configured events show icon | `notifications_active` icon (filled); unconfigured shows `notifications_none` (outline) |

**Pass criteria:** 11 events visible, grouped correctly. Pre-seeded channels shown as badges.

---

### TS-NT-03 · Open Template Editor — Equipment Replacement

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Equipment Replacement** card | Bottom sheet slides up (DraggableScrollableSheet) |
| 2 | Sheet header | Title: "Equipment Replacement" · sub-label: `equipment_replacement` |
| 3 | **CHANNELS** section | 3 toggle buttons: **Email · SMS · In-App** |
| 4 | All 3 toggles active `●` | Pre-populated from global default templates |
| 5 | **Email** section visible below toggles | Subject + Body (HTML) fields |
| 6 | Subject field pre-filled | e.g. `[KPTCL] Equipment Replacement Notice` |
| 7 | **SMS** section visible | Single body field |
| 8 | **In-App** section visible | Body field |
| 9 | **RECIPIENTS** section | Role checkboxes: `EE TLSS`, `SEE W&M`, `CEE Transmission Zone` pre-checked |
| 10 | **EXTRA EMAIL RECIPIENTS** | Empty input row + existing chips (if any) |
| 11 | **CONTEXT VARIABLES** hint box at bottom | Shows: `{{old_ueic}}`, `{{new_ueic}}`, `{{replaced_by}}`, `{{replaced_on}}`, `{{reason}}` etc. |
| 12 | Tap **Cancel** | Sheet dismisses; no save occurs |

**Pass criteria:** All 3 channels pre-loaded. Context hint shows event-specific vars. Cancel is safe.

---

### TS-NT-04 · Toggle Channels (Enable/Disable)

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open `Equipment Replacement` editor | All 3 channels `●` active |
| 2 | Tap **SMS** toggle | SMS → `○` off; SMS body section collapses with animation |
| 3 | Tap **SMS** toggle again | SMS → `●` on; SMS body section expands |
| 4 | Tap **Email** toggle off | Email section collapses (subject + body hidden) |
| 5 | Tap **In-App** toggle off | In-App section collapses |
| 6 | All 3 now `○` off | Orange warning box: "Enable at least one channel above…" |
| 7 | Tap **Email** back on | Warning box disappears; Email section re-appears |
| 8 | Save with only Email enabled | Saves; SMS + In-App deactivated for org |
| 9 | Equipment Replacement card | Shows only **● Email** badge |

**Pass criteria:** Toggles animate smoothly. Warning shows when all off. Badge reflects saved state.

---

### TS-NT-05 · Edit Email Subject and Body

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open `Equipment Replacement` editor → Email enabled | Subject + Body fields visible |
| 2 | Clear subject; type: `[KPTCL Alert] {{old_ueic}} Replaced at {{equipment.department}}` | Subject updated |
| 3 | Clear body; type HTML (see template reference in Part D) | Multi-line editor accepts HTML |
| 4 | Verify `{{old_ueic}}` and `{{new_ueic}}` appear in body | Typed correctly |
| 5 | Tap **Save Templates** | Success snackbar: "Notification templates saved." |
| 6 | Re-open editor | Subject and body preserved exactly |

**Pass criteria:** HTML body with `{{}}` syntax saved and reloaded correctly.

---

### TS-NT-06 · Variable Picker — Insert at Cursor

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open `Test Request Submitted` editor → enable Email | Body field visible |
| 2 | Tap inside body field, position cursor mid-text | Cursor placed |
| 3 | Tap **+ Insert Variable** (next to "Body (HTML)" label) | Variable picker modal slides up |
| 4 | Picker shows accordion groups | Reports · Equipment · Replacement · Test Request · Evaluation · Organisation · System |
| 5 | Expand **Test Request** group | Variables listed: `{{request.number}}`, `{{request.title}}` etc.; each shows sample value |
| 6 | Tap `{{request.number}}` | Picker closes; variable inserted at cursor position |
| 7 | Tap **+ Insert Variable** again | Picker reopens |
| 8 | Type `ueic` in search bar | Filters to: `{{equipment.ueic}}`, `{{old_ueic}}`, `{{new_ueic}}` |
| 9 | Tap `{{equipment.ueic}}` | Inserted after previous insertion |
| 10 | Type `xyz_none` in search | "No variables found." empty state |
| 11 | Clear search | All groups restore |

**Pass criteria:** Insertion at exact cursor. Search filter works. Empty state shown.

---

### TS-NT-07 · Preview Mode

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open any event editor with body: `Equipment {{old_ueic}} replaced by {{new_ueic}} on {{replaced_on}}.` | Edit mode |
| 2 | Tap **Preview** button (top-right) | Button label changes to **Edit**; icon → pencil |
| 3 | Subject area | Blue preview box renders: e.g. `[KPTCL Alert] ZO-1AN-220-01-CT-01 Replaced at 110kV Adaki` |
| 4 | Body area | Preview box: `Equipment ZO-1AN-220-01-CT-01 replaced by ZO-1AN-220-01-CT-02 on 2026-05-04.` |
| 5 | Unknown var `{{unknown.key}}` in body | Rendered as-is: `{{unknown.key}}` |
| 6 | Tap **Edit** button | Returns to editable fields; `{{old_ueic}}` syntax intact |
| 7 | Save | Saved with `{{}}` placeholders, not sample values |

**Pass criteria:** Preview substitutes sample values. Edit restores raw templates. Save keeps `{{}}` syntax.

---

### TS-NT-08 · Recipient Role Selection

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open `Equipment Replacement` editor | Recipient chips visible |
| 2 | Pre-selected: `EE TLSS`, `SEE W&M`, `CEE Transmission Zone` | 3 blue chips |
| 3 | Tap `EE TLSS` chip | Deselects — turns grey border |
| 4 | Tap `AEE Maintenance` chip | Selects — turns blue border with checkmark |
| 5 | Tap `Department Head` | Selects |
| 6 | Final selection: `SEE W&M`, `CEE Transmission Zone`, `AEE Maintenance`, `Department Head` | 4 selected |
| 7 | Save | Success |
| 8 | Re-open editor | 4 chips selected — persisted |
| 9 | Trigger replacement | Notification sent to 4 new roles; EE TLSS receives no notification |

**Pass criteria:** Role chips toggle correctly. Persist across save. Delivery matches new selection.

---

### TS-NT-09 · Extra Email Recipients

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open `Critical Test Result` editor | Extra Email Recipients section visible |
| 2 | Type `station.manager@kptcl.com` → tap **+** | Email chip added; input cleared |
| 3 | Type `zone.ee@kptcl.gov.in` → press **Enter** | Second chip added |
| 4 | Type `not-an-email` (no `@`) → tap **+** | Input stays; no chip added (invalid email rejected) |
| 5 | Tap `×` on first chip | `station.manager@kptcl.com` chip removed |
| 6 | Save | `zone.ee@kptcl.gov.in` persisted as extra recipient |
| 7 | Trigger eval_critical | Email sent to role recipients + `zone.ee@kptcl.gov.in` |

**Pass criteria:** Valid emails chip; invalid rejected. Extra recipients receive email on notification fire.

---

### TS-NT-10 · Configure Unconfigured Event (Recommendation Approved)

**Login:** `orgadmin@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap **Recommendation Approved** card | Editor opens; all toggles `○` off |
| 2 | Orange warning visible | "Enable at least one channel above to configure this notification." |
| 3 | Enable **In-App** | Section expands |
| 4 | Body: `Recommendation for {{equipment.ueic}} approved by {{approved_by}}.` | Text entered |
| 5 | Recipients: check `Originator` and `AEE Maintenance` | Both selected |
| 6 | Save | Success |
| 7 | Card now shows | **● In-App** badge; "Not configured" gone |

**Pass criteria:** First-time configuration creates org override. Card updates immediately.

---

### TS-NT-11 · Reset to Global Default

**Login:** `orgadmin@kptcl.com` / `admin123`  
**Prerequisite:** Equipment Replacement has an org-specific override (from earlier saves)

| # | Step | Expected Result |
|---|---|---|
| 1 | Open `Equipment Replacement` editor | Channel config shows org override values |
| 2 | Observe `org override` sub-label on Email toggle | Confirms org-specific template active |
| 3 | Disable all 3 channels → Save | All org overrides deactivated |
| 4 | Re-open editor | Channels show `●` again but with `default` sub-label (global fallback active) |
| 5 | Trigger replacement | Global default template fires; original roles (EE TLSS, SEE W&M, CEE Zone) receive notification |

**Pass criteria:** Disabling org overrides restores global default behaviour.

---

### TS-NT-12 · Configure All Test Workflow Events

**Login:** `orgadmin@kptcl.com` / `admin123`

| Event | Channels | Recipients | Key Variables |
|---|---|---|---|
| `request_submitted` | Email + In-App | `EE TLSS`, `Department Head` | `{{request.number}}`, `{{request.title}}`, `{{equipment.ueic}}` |
| `request_assigned` | Email + In-App | `Field Tester`, `Lab Tester` | `{{request.number}}`, `{{request.assigned_to}}`, `{{request.due_date}}` |
| `test_submitted` | Email + In-App | `EE TLSS`, `Department Head` | `{{request.number}}`, `{{eval.overall}}`, `{{report.retriepdf}}` |
| `request_approved` | Email + In-App | `Originator`, `AEE Maintenance` | `{{request.number}}`, `{{report.retriepdf}}`, `{{report.retriexls}}` |
| `request_rejected` | Email + SMS + In-App | `Originator`, `Field Tester` | `{{request.number}}`, `{{reason}}` |

For each row:

| # | Step | Expected Result |
|---|---|---|
| 1 | Tap event card | Editor opens |
| 2 | Enable listed channels | Sections expand |
| 3 | Set subject + body using variables from list | Content entered via keyboard or variable picker |
| 4 | Select recipient roles | Chips checked |
| 5 | Save | Success; card shows channel badges |

**Pass criteria:** All 5 workflow events configured. Card badges reflect chosen channels.

---

## ═══════════════════════════════════════
## PART C — IN-APP NOTIFICATION CENTRE
## ═══════════════════════════════════════

---

### TS-IN-01 · Bell Badge Count

**Login:** `ee.tlss@kptcl.com` / `admin123`  
**Prerequisite:** Equipment Replacement triggered (EE TLSS is recipient)

| # | Step | Expected Result |
|---|---|---|
| 1 | Log in | 🔔 bell shows red badge with unread count (e.g. `3`) |
| 2 | Tap bell | Notification list slides in; entries newest first |
| 3 | Each entry shows | Event icon · title · body preview · time ago |
| 4 | Unread entries | Bold title; distinct background |
| 5 | Tap one notification | Marked read; badge decrements by 1 |
| 6 | Tap **Mark All Read** | Badge drops to `0`; all entries muted style |

**Pass criteria:** Badge reflects unread count. Individual + bulk mark-read work.

---

### TS-IN-02 · Severity Filter

**Login:** `ee.tlss@kptcl.com` / `admin123`

| # | Step | Expected Result |
|---|---|---|
| 1 | Open notification list | Mix of severities: 🔴 critical · 🟠 alert · 🔵 info |
| 2 | Filter by `critical` | Only critical notifications listed (red chip) |
| 3 | Filter by `alert` | Only alert notifications (orange chip) |
| 4 | Filter by `info` | Equipment replacement notifications shown (blue chip) |
| 5 | Clear filter | All notifications shown again |

**Pass criteria:** Severity filter isolates entries correctly.

---

## ═══════════════════════════════════════
## PART D — TEMPLATE DESIGN REFERENCE
## ═══════════════════════════════════════

### D-1 · Equipment Replacement — All 3 Channels

**Subject (Email):**
```
[KPTCL Alert] Equipment {{old_ueic}} Replaced at {{equipment.department}}
```

**Body (Email HTML):**
```html
<div style="font-family:Arial,sans-serif;max-width:600px;">
  <h2 style="color:#d97706;">⚡ Equipment Replacement Notice</h2>
  <p>Dear {{org.name}} Team,</p>
  <p>Equipment <b>{{old_ueic}}</b> ({{equipment.type}}) at
  <i>{{equipment.department}}</i> has been retired and replaced.</p>

  <table border="1" cellpadding="8" cellspacing="0"
         style="border-collapse:collapse;width:100%;font-size:14px;">
    <tr style="background:#f3f4f6;">
      <td width="40%"><b>Retired UEIC</b></td><td>{{old_ueic}}</td>
    </tr>
    <tr>
      <td><b>Replacement UEIC</b></td><td>{{new_ueic}}</td>
    </tr>
    <tr style="background:#f3f4f6;">
      <td><b>Equipment Type</b></td><td>{{equipment.type}}</td>
    </tr>
    <tr>
      <td><b>Location</b></td><td>{{equipment.department}}</td>
    </tr>
    <tr style="background:#f3f4f6;">
      <td><b>Replaced By</b></td><td>{{replaced_by}}</td>
    </tr>
    <tr>
      <td><b>Date</b></td><td>{{replaced_on}}</td>
    </tr>
    <tr style="background:#f3f4f6;">
      <td><b>Reason</b></td><td>{{reason}}</td>
    </tr>
  </table>

  <p style="margin-top:16px;">
    📄 <a href="{{report.retriepdf}}">Download Replacement Report (PDF)</a><br/>
    📊 <a href="{{report.retriexls}}">Download Replacement Report (Excel)</a>
  </p>
  <p style="color:#6b7280;font-size:12px;">
    — {{system.app_name}} · {{system.date}} · {{system.time}}
  </p>
</div>
```

**SMS (≤160 chars):**
```
[KPTCL] {{old_ueic}} retired. New: {{new_ueic}}. Date: {{replaced_on}}. Ref: {{report.ref}}
```

**In-App:**
```
[Replacement] {{old_ueic}} → {{new_ueic}} at {{equipment.department}} ({{replaced_on}})
```

**Recipients:** `EE TLSS`, `SEE W&M`, `CEE Transmission Zone`

---

### D-2 · Critical Test Result — Email + In-App

**Subject (Email):**
```
[CRITICAL ALERT] {{equipment.ueic}} — {{eval.test_type}} Result: {{eval.overall}}
```

**Body (Email HTML):**
```html
<div style="font-family:Arial,sans-serif;max-width:600px;">
  <h2 style="color:#dc2626;">⚠ CRITICAL TEST RESULT</h2>
  <p>A critical test result has been detected. <b>Immediate attention required.</b></p>

  <table border="1" cellpadding="8" cellspacing="0"
         style="border-collapse:collapse;width:100%;font-size:14px;">
    <tr style="background:#fef2f2;">
      <td width="40%"><b>Equipment UEIC</b></td><td>{{equipment.ueic}}</td>
    </tr>
    <tr>
      <td><b>Type</b></td><td>{{equipment.type}}</td>
    </tr>
    <tr style="background:#fef2f2;">
      <td><b>Location</b></td><td>{{equipment.department}}</td>
    </tr>
    <tr>
      <td><b>Test Type</b></td><td>{{eval.test_type}}</td>
    </tr>
    <tr style="background:#fef2f2;">
      <td><b>Overall Result</b></td>
      <td><b style="color:#dc2626;">{{eval.overall}}</b></td>
    </tr>
    <tr>
      <td><b>Evaluated At</b></td><td>{{eval.evaluated_at}}</td>
    </tr>
  </table>

  <p style="margin-top:16px;">
    📄 <a href="{{report.retriepdf}}">View Full Test Report (PDF)</a>
  </p>
  <p style="color:#6b7280;font-size:12px;">
    — {{system.app_name}} · {{system.date}}
  </p>
</div>
```

**In-App:**
```
⚠ CRITICAL: {{equipment.ueic}} ({{eval.test_type}}) — {{eval.overall}}. Immediate action required.
```

**Recipients:** `EE TLSS`, `SEE W&M`, `CEE Transmission Zone`, `AEE Maintenance`

---

### D-3 · Test Request Submitted — Email + In-App

**Subject (Email):**
```
[SEACMS] New Test Request {{request.number}} — Priority: {{request.priority}}
```

**Body (Email HTML):**
```html
<p>A new test request has been submitted and requires assignment.</p>
<table border="1" cellpadding="6" style="border-collapse:collapse;">
  <tr><td><b>Request #</b></td><td>{{request.number}}</td></tr>
  <tr><td><b>Title</b></td><td>{{request.title}}</td></tr>
  <tr><td><b>Priority</b></td><td>{{request.priority}}</td></tr>
  <tr><td><b>Equipment</b></td><td>{{equipment.ueic}}</td></tr>
  <tr><td><b>Location</b></td><td>{{equipment.department}}</td></tr>
  <tr><td><b>Submitted By</b></td><td>{{request.submitted_by}}</td></tr>
</table>
<p>Please log in to assign a tester. — {{system.app_name}}</p>
```

**In-App:**
```
New request {{request.number}}: {{request.title}} ({{request.priority}}) — {{equipment.ueic}}
```

**Recipients:** `EE TLSS`, `Department Head`

---

### D-4 · Test Request Rejected — Email + SMS + In-App

**Subject (Email):**
```
[Action Required] Test Request {{request.number}} Rejected / Returned
```

**Body (Email HTML):**
```html
<p>Your test request has been rejected or returned for rework.</p>
<p><b>Request:</b> {{request.number}} — {{request.title}}<br/>
<b>Equipment:</b> {{equipment.ueic}}<br/>
<b>Rejection Reason:</b> {{reason}}</p>
<p>Please review the feedback and resubmit. — {{system.app_name}}</p>
```

**SMS:**
```
[SEACMS] Request {{request.number}} rejected. Reason: {{reason}}. Log in to resubmit.
```

**In-App:**
```
Request {{request.number}} returned for rework. Reason: {{reason}}
```

**Recipients:** `Originator`, `Field Tester`, `Lab Tester`

---

### D-5 · Test Request Approved with Report Links — Email + In-App

**Subject (Email):**
```
[SEACMS] Test Request {{request.number}} Approved — Reports Ready
```

**Body (Email HTML):**
```html
<p>The test request has been approved. Your reports are ready for download.</p>
<p><b>Request:</b> {{request.number}} — {{request.title}}<br/>
<b>Equipment:</b> {{equipment.ueic}}<br/>
<b>Submitted By:</b> {{request.submitted_by}}</p>
<p>
  📄 <a href="{{report.retriepdf}}">Download PDF Report</a><br/>
  📊 <a href="{{report.retriexls}}">Download Excel Report</a>
</p>
<p>— {{system.app_name}} · {{system.date}}</p>
```

**In-App:**
```
Request {{request.number}} approved. Reports ready: {{report.ref}}
```

**Recipients:** `Originator`, `AEE Maintenance`

---

## ═══════════════════════════════════════
## PART E — END-TO-END INTEGRATION
## ═══════════════════════════════════════

---

### TS-E2E-01 · Full Equipment Lifecycle with Notifications

**Users involved:** Admin (orgadmin) · Originator · EE TLSS · SEE W&M

| # | User | Action | Expected Notification |
|---|---|---|---|
| 1 | `originator@kptcl.com` | Creates new equipment `ZO-1A-220-03-PT-01` | — (no notification for creation) |
| 2 | `originator@kptcl.com` | Submits test request for `ZO-1A-220-03-PT-01` | `request_submitted` → EE TLSS + Dept Head bell 🔔 |
| 3 | `orgadmin@kptcl.com` | Assigns `fieldtester1` to request | `request_assigned` → Field Tester bell 🔔 |
| 4 | `fieldtester1@kptcl.com` | Submits test results (IR = 60 MΩ — CRITICAL) | `eval_critical` → EE TLSS, SEE W&M, CEE Zone, AEE Maint bell 🔔 + email |
| 5 | `orgadmin@kptcl.com` | Approves test result | `request_approved` → Originator + AEE Maintenance bell 🔔 |
| 6 | `orgadmin@kptcl.com` | Replaces `ZO-1A-220-03-PT-01` due to critical result | `equipment_replacement` → EE TLSS, SEE W&M, CEE Zone bell 🔔 |
| 7 | `ee.tlss@kptcl.com` | Opens bell → sees 2 entries | Critical test result + Equipment replacement notifications |

**Pass criteria:** Each workflow event fires correct notification to correct roles only.

---

### TS-E2E-02 · Notification Template Change Affects Next Notification

| # | User | Step | Expected |
|---|---|---|---|
| 1 | `orgadmin@kptcl.com` | Open `equipment_replacement` → remove `SEE W&M` from recipients → Save | Override saved |
| 2 | `originator@kptcl.com` | Trigger another equipment replacement | Notification fires |
| 3 | `see.wm@kptcl.com` | Check bell 🔔 | **No** new notification — SEE W&M removed from template |
| 4 | `ee.tlss@kptcl.com` | Check bell 🔔 | New notification present — EE TLSS still in template |

**Pass criteria:** Template change takes effect on the very next `fire()` call. Existing delivered notifications unchanged.

---

## ═══════════════════════════════════════
## ✅ MASTER TEST CHECKLIST
## ═══════════════════════════════════════

### Equipment Flow

| ID | Scenario | Login | Pass |
|---|---|---|---|
| TS-EQ-01 | View equipment register (read-only) | `ee.tlss@kptcl.com` | ☐ |
| TS-EQ-02 | Create new equipment | `orgadmin@kptcl.com` | ☐ |
| TS-EQ-03 | Edit equipment | `originator@kptcl.com` | ☐ |
| TS-EQ-04 | Retire equipment | `orgadmin@kptcl.com` | ☐ |
| TS-EQ-05 | Replace equipment (reason=other + PDF) | `orgadmin@kptcl.com` | ☐ |
| TS-EQ-06 | Replace (reason=recommendation) | `orgadmin@kptcl.com` | ☐ |
| TS-EQ-07 | Replacement notification multi-role | Multiple | ☐ |
| TS-EQ-08 | Export CSV + RBAC | `orgadmin@kptcl.com` | ☐ |
| TS-EQ-09 | Stats counters | `orgadmin@kptcl.com` | ☐ |
| TS-EQ-10 | RBAC no access (Field Tester) | `fieldtester1@kptcl.com` | ☐ |
| TS-EQ-11 | Nameplate file preview | `orgadmin@kptcl.com` | ☐ |

### Notification Template Configuration UI

| ID | Scenario | Login | Channels | Pass |
|---|---|---|---|---|
| TS-NT-01 | Non-admin blocked | `ee.tlss@kptcl.com` | — | ☐ |
| TS-NT-02 | Admin loads event catalogue | `orgadmin@kptcl.com` | — | ☐ |
| TS-NT-03 | Open template editor (equipment_replacement) | `orgadmin@kptcl.com` | Email·SMS·In-App | ☐ |
| TS-NT-04 | Toggle channels on/off | `orgadmin@kptcl.com` | All | ☐ |
| TS-NT-05 | Edit email subject + body | `orgadmin@kptcl.com` | Email | ☐ |
| TS-NT-06 | Variable picker — insert at cursor | `orgadmin@kptcl.com` | Email | ☐ |
| TS-NT-07 | Preview mode — sample value render | `orgadmin@kptcl.com` | Email | ☐ |
| TS-NT-08 | Recipient role checkboxes | `orgadmin@kptcl.com` | — | ☐ |
| TS-NT-09 | Extra email chips | `orgadmin@kptcl.com` | — | ☐ |
| TS-NT-10 | Configure unconfigured event | `orgadmin@kptcl.com` | In-App | ☐ |
| TS-NT-11 | Reset to global default | `orgadmin@kptcl.com` | — | ☐ |
| TS-NT-12 | Configure all 5 test workflow events | `orgadmin@kptcl.com` | Email·In-App | ☐ |

### In-App Notification Centre

| ID | Scenario | Login | Pass |
|---|---|---|---|
| TS-IN-01 | Bell badge count + mark read | `ee.tlss@kptcl.com` | ☐ |
| TS-IN-02 | Severity filter (critical/alert/info) | `ee.tlss@kptcl.com` | ☐ |

### End-to-End Integration

| ID | Scenario | Users Involved | Pass |
|---|---|---|---|
| TS-E2E-01 | Full equipment lifecycle with notifications | Admin · Originator · EE TLSS · Field Tester | ☐ |
| TS-E2E-02 | Template change affects next notification | Admin · SEE W&M · EE TLSS | ☐ |

---

*Generated: 2026-05-04 · SEACMS Master Test Suite v2*  
*Covers: Equipment Flow (11) · Notification Template UI (12) · In-App Centre (2) · E2E (2) = **27 scenarios***
