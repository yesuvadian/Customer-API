# SEACMS — Test Register: UI Test Scenarios

**Module:** Test Register (SRS §5.1.1)  
**Scope:** Periodic maintenance catalogue — who tests what, with which role  
**System:** SubStation Equipment and Asset Condition Monitoring System  
**Organisation:** KPTCL RT&RD  
**Date:** May 2026 | v1.0

---

## Test Users

| Role | Credential | Write Access |
|------|-----------|--------------|
| EE TLSS | eetlss@kptcl.com | ✅ Create / Edit / Deactivate templates |
| Department Head | depthead@kptcl.com | ✅ Create / Edit / Deactivate templates |
| Admin | admin@kptcl.com | ✅ Create / Edit / Deactivate templates |
| Originator | originator@kptcl.com | 🔒 Read-only |
| Tester (SEE RT) | see.rt@kptcl.com | 🔒 Read-only |
| Field Tester | field.tester@kptcl.com | 🔒 Read-only |

## Test Data (Pre-conditions)

- **Equipment types in system:** Power Transformer, Circuit Breaker, Isolator, Current Transformer, Surge Arrester
- **Test types used:** Insulation Resistance (IR) Test, Oil Dielectric Strength Test, Tan Delta (Dissipation Factor) Test, Partial Discharge (PD) Test, Earthing Resistance Test
- **Equipment unit:** 220 kV Power Transformer T1 already in asset register at Hebbal 220/11 kV substation

## Navigation

> **Navigation Drawer → Test Register**  
> or **EE TLSS Dashboard → Quick Actions → Test Register tile**

---

## Positive Scenarios (TC-111 to TC-128)

---

### TC-111 — View Catalogue (EE TLSS)

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS opens the Test Register and views the maintenance template catalogue.

**Steps:**
1. Login as `eetlss@kptcl.com`
2. Open Navigation Drawer → tap **Test Register**
3. Observe the Catalogue tab (default active tab)

**Expected:**
- Templates grouped by equipment type (Transformer, Circuit Breaker, Isolator)
- Each card shows: title, frequency badge, next-run date, Active/Inactive status
- Search bar and Equipment Type filter visible at top
- **+ Add Template** FAB visible (write-role user)

---

### TC-112 — Create Template: Annual IR Test on Power Transformer (EE TLSS)

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS registers the mandatory annual Insulation Resistance test for Power Transformers.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Tap **+ FAB**
3. Select Equipment Type = **Power Transformer**
4. Enter Title = `Annual Insulation Resistance (IR) Test`
5. Select Frequency = **Annual (1 year)**
6. Set First Run Date = `2026-06-01`
7. Tap **Save**

**Expected:**
- Template card appears under **Power Transformer** group
- Card shows **Annual** badge and next-run date `2026-06-01`
- **Active** (green) status badge shown

---

### TC-113 — Create Template: Semi-Annual Oil Dielectric Test (EE TLSS)

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS adds a semi-annual oil quality test with OEM standard reference.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Tap **+ FAB**
3. Select Equipment Type = **Power Transformer**
4. Enter Title = `Oil Dielectric Strength Test`
5. Select Frequency = **Semi-Annual (6 months)**
6. Set First Run Date = `2026-04-01`
7. Enter OEM Reference = `IEC 60156:2018`
8. Tap **Save**

**Expected:**
- Template added under Power Transformer group
- **Semi-Annual** badge shown on card
- OEM ref `IEC 60156:2018` displayed in card meta-row

---

### TC-114 — Create Template: Tan Delta Test (Department Head)

**User:** depthead@kptcl.com  
**Scenario:** Department Head verifies they have the same write access as EE TLSS for template creation.

**Steps:**
1. Login as `depthead@kptcl.com`, navigate to Test Register
2. Tap **+ FAB**
3. Select Equipment Type = **Power Transformer**
4. Enter Title = `Tan Delta (Dissipation Factor) Test`
5. Select Frequency = **Annual (1 year)**
6. Set First Run Date = `2026-05-15`
7. Tap **Save**

**Expected:**
- Template created successfully by Department Head
- Card visible under Power Transformer group
- Department Head write access confirmed same as EE TLSS

---

### TC-115 — Create Template: Biennial Earthing Resistance Test on Isolator (Admin)

**User:** admin@kptcl.com  
**Scenario:** Admin registers a two-yearly earthing test for Isolator equipment.

**Steps:**
1. Login as `admin@kptcl.com`, navigate to Test Register
2. Tap **+ FAB**
3. Select Equipment Type = **Isolator**
4. Enter Title = `Earthing Resistance Test`
5. Select Frequency = **Biennial (2 years)**
6. Set First Run Date = `2026-07-01`
7. Tap **Save**

**Expected:**
- Template created under **Isolator** group
- **Biennial (2 years)** badge shown on card
- Admin write access confirmed

---

### TC-116 — Create Template: Quarterly Partial Discharge Test on Circuit Breaker (EE TLSS)

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS adds a quarterly PD test, verifying a new equipment type group is created automatically.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Tap **+ FAB**
3. Select Equipment Type = **Circuit Breaker**
4. Enter Title = `Partial Discharge (PD) Test`
5. Select Frequency = **Quarterly (3 months)**
6. Set First Run Date = `2026-04-15`
7. Tap **Save**

**Expected:**
- **Circuit Breaker** group appears in catalogue with PD Test card
- **Quarterly (3 months)** badge shown
- Multiple equipment type groups now visible (Transformer, Circuit Breaker, Isolator)

---

### TC-117 — Edit Template: Add OEM Reference to IR Test (EE TLSS)

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS updates an existing template to add the IS standard reference. Verifies equipment type is locked after creation.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Find **Annual Insulation Resistance (IR) Test** under Power Transformer
3. Tap **Edit** button on card
4. Enter OEM Ref = `IS 2026 Part 1`
5. Observe Equipment Type dropdown
6. Tap **Save**

**Expected:**
- Card updates to show OEM ref `IS 2026 Part 1`
- Equipment Type dropdown was **greyed out / disabled** in edit mode (cannot change type on existing template)
- All other fields updated correctly

---

### TC-118 — Edit Template: Set ALERT Override Interval (EE TLSS)

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS configures the Oil Dielectric test to repeat every 30 days (instead of 6 months) whenever a result is ALERT — indicating oil quality is critical.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Find **Oil Dielectric Strength Test** under Power Transformer
3. Tap **Edit**
4. Enter ALERT Override Days = `30`
5. Tap **Save**

**Expected:**
- Card shows ALERT override badge: **30 d override**
- Indicates that after an ALERT result, test repeats in 30 days instead of 6 months
- Other template fields unchanged

---

### TC-119 — Filter Catalogue by Equipment Type

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS filters the catalogue to show only Power Transformer templates.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. In Equipment Type filter dropdown, select **Power Transformer**

**Expected:**
- Only Power Transformer templates shown in catalogue
- Circuit Breaker and Isolator groups hidden from view
- **Clear Filter** option appears in filter bar

---

### TC-120 — Search Template by Title Keyword

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS searches for "Insulation" to find the IR test quickly.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Type `Insulation` in the search box

**Expected:**
- Only templates whose title contains "Insulation" shown
- Oil Dielectric, Tan Delta, Earthing and PD templates hidden
- Live search updates results as user types each character

---

### TC-121 — Read-only View: Originator Cannot Edit

**User:** originator@kptcl.com  
**Scenario:** Originator verifies they can view the maintenance catalogue but have no write access.

**Steps:**
1. Login as `originator@kptcl.com`
2. Navigate to Test Register via Navigation Drawer
3. Inspect Catalogue tab and individual template cards

**Expected:**
- All active templates visible and grouped by equipment type
- **No + Add Template FAB** rendered
- **No Edit or Deactivate buttons** appear on any card
- Page is fully read-only

---

### TC-122 — Equipment Schedules Tab: List All Commissioned Units

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS checks which equipment units have live test schedules.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Tap **Equipment Schedules** tab

**Expected:**
- List shows all commissioned equipment units
- Each row: equipment name, type, substation, **Schedules** button
- Refresh button visible at top of tab

---

### TC-123 — View Schedules for 220 kV Power Transformer T1

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS checks what periodic tests are scheduled for a specific transformer unit.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register → Equipment Schedules tab
2. Find **220 kV Power Transformer T1** in equipment list
3. Tap **Schedules** button for T1

**Expected:**
- Dialog opens with all active test schedules for 220 kV PT T1
- Rows include:
  - Annual IR Test — due `2026-06-01`
  - Oil Dielectric Strength Test — due `2026-10-01`
- Each row shows template title, frequency, and next due date

---

### TC-124 — Overdue Schedule Highlighted in Red

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS identifies overdue maintenance schedules that need immediate attention.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register → Equipment Schedules tab
2. Find a unit whose `next_run` date is earlier than today
3. Tap **Schedules** for that unit

**Expected:**
- Overdue schedules shown with **red/orange highlight**
- **Overdue** indicator label displayed next to the due date
- On-time schedules displayed in normal text without highlight

---

### TC-125 — Commission New Equipment: Auto Schedule Creation

**User:** admin@kptcl.com  
**Scenario:** Admin adds a new transformer to the asset register. System auto-creates all matching Test Register schedules without any manual action.

**Steps:**
1. Login as `admin@kptcl.com`
2. Navigate to Equipment Register → Add New Equipment
3. Enter: Type = **Power Transformer**, Name = `220 kV Transformer T2`, Substation = `Hebbal 220/11 kV`
4. Save equipment
5. Navigate to Test Register → Equipment Schedules tab
6. Find **220 kV Transformer T2** and tap **Schedules**

**Expected:**
- T2 appears in Equipment Schedules list immediately after save
- All active Power Transformer templates (IR Test, Oil Dielectric, Tan Delta) auto-commissioned as live schedules
- Schedule due dates computed from template `first_run` dates
- Commissioning is **automatic and non-blocking**

---

### TC-126 — Alert Reschedule: Shorter Interval After ALERT Result

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS verifies that after an ALERT result on the Oil Dielectric test, the next schedule uses the 30-day override interval instead of 6 months.

**Pre-condition:** Oil Dielectric Strength Test has ALERT Override = 30 days set (TC-118). The most recent oil test result for 220 kV PT T1 was ALERT.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register → Equipment Schedules tab
2. Open **Schedules** for **220 kV Power Transformer T1**
3. Observe next due date for Oil Dielectric Strength Test

**Expected:**
- Next due date = date of ALERT result + **30 days** (not + 6 months)
- Schedule row shows **ALERT override active** indicator
- Standard 6-month schedule resumes after next non-ALERT result

---

### TC-127 — Deactivate Template (Admin)

**User:** admin@kptcl.com  
**Scenario:** Admin deactivates the Earthing Resistance Test template. Existing live schedules must remain unaffected.

**Steps:**
1. Login as `admin@kptcl.com`, navigate to Test Register
2. Find **Earthing Resistance Test** under Isolator
3. Tap **Deactivate** button on card
4. Confirm in the confirmation dialog

**Expected:**
- Card status badge changes from **Active** (green) to **Inactive** (grey)
- Template remains visible in catalogue for audit trail
- No new schedules generated from this template for future equipment commissions
- Existing live schedules on current equipment are **not** deleted

---

### TC-128 — EE TLSS Dashboard: Test Register Quick Action Tile

**User:** eetlss@kptcl.com  
**Scenario:** EE TLSS navigates to Test Register via the dashboard quick action tile.

**Steps:**
1. Login as `eetlss@kptcl.com`
2. EE TLSS dashboard loads automatically
3. Observe **Quick Actions** row below KPI strip
4. Tap **Test Register** tile

**Expected:**
- Quick Actions row shows 4 tiles: Test Register, Equipment, Reports, Alerts
- Tapping Test Register tile navigates to `/test-register` route
- Test Register page loads with Catalogue tab active and templates visible

---

## Negative Scenarios (TC-129 to TC-135)

> These test cases verify the system **correctly restricts or blocks** an action. The expected outcome is a rejection or hidden control — a correct rejection = test passes.

---

### TC-129 — Role Restriction: Originator Cannot Create Template

**User:** originator@kptcl.com  
**Scenario:** Originator should have no write access to the Test Register.

**Steps:**
1. Login as `originator@kptcl.com`
2. Navigate to Test Register → Catalogue tab
3. Look for the **+ Add Template** FAB button anywhere on page

**Expected (correct behaviour — action blocked):**
- **+ FAB button is absent** — not rendered for Originator role
- No Create Template option accessible anywhere
- Catalogue displays as read-only

---

### TC-130 — Role Restriction: Tester Cannot Edit or Deactivate

**User:** see.rt@kptcl.com (Tester / SEE RT role)  
**Scenario:** Tester should see the catalogue but have no edit controls.

**Steps:**
1. Login as `see.rt@kptcl.com`
2. Navigate to Test Register via Navigation Drawer
3. Inspect individual template cards

**Expected (correct behaviour — action blocked):**
- **Edit** button not visible on any card
- **Deactivate** button not visible on any card
- Read-only view identical to Originator access level

---

### TC-131 — Validation: Title Required on Create

**User:** eetlss@kptcl.com  
**Scenario:** Form must reject submission when the template title is blank.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Tap **+ FAB**
3. Select Equipment Type = **Current Transformer**
4. Select Frequency = Annual (1 year), set First Run Date = `2026-06-01`
5. Leave **Title field blank**
6. Tap **Save**

**Expected (correct behaviour — save blocked):**
- Save blocked by form validation
- Error: **"Title is required"** shown under Title field
- Form remains open for correction — no template created

---

### TC-132 — Validation: Equipment Type Required on Create

**User:** eetlss@kptcl.com  
**Scenario:** Form must reject submission when no equipment type is selected.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Tap **+ FAB**
3. Enter Title = `Test Without Type`
4. Select Frequency and set First Run Date
5. Leave **Equipment Type unselected**
6. Tap **Save**

**Expected (correct behaviour — save blocked):**
- Save blocked with validation error: **"Equipment Type is required"**
- Equipment Type dropdown highlighted in error state
- No template created in system

---

### TC-133 — Validation: Equipment Type Locked on Edit

**User:** eetlss@kptcl.com  
**Scenario:** Equipment type must not be changeable after a template is created (existing schedules depend on it).

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Open **Edit** dialog for **Annual Insulation Resistance (IR) Test**
3. Attempt to interact with the Equipment Type dropdown

**Expected (correct behaviour — field locked):**
- Equipment Type dropdown is **greyed out and non-interactive** in edit mode
- Cannot change equipment type on an existing template
- All other fields (Title, Frequency, OEM Ref, ALERT Override) remain editable

---

### TC-134 — Validation: ALERT Override Must Be at Least 1 Day

**User:** eetlss@kptcl.com  
**Scenario:** Zero-day ALERT override is meaningless and must be rejected.

**Steps:**
1. Login as `eetlss@kptcl.com`, navigate to Test Register
2. Open **Edit** dialog for **Oil Dielectric Strength Test**
3. Enter ALERT Override Days = `0`
4. Tap **Save**

**Expected (correct behaviour — save blocked):**
- Validation error: **"ALERT override must be at least 1 day"**
- Form not submitted
- Zero-day value rejected by UI validation

---

### TC-135 — Role Restriction: Field Tester Cannot Commission Equipment

**User:** field.tester@kptcl.com (Field Tester role)  
**Scenario:** Field Tester should not have access to commissioning controls.

**Steps:**
1. Login as `field.tester@kptcl.com`
2. Navigate to Test Register → Equipment Schedules tab
3. Inspect equipment list rows for any **Commission** or admin action button

**Expected (correct behaviour — action blocked):**
- No Commission button visible for Field Tester role
- Equipment Schedules list is read-only
- Schedules dialog accessible for viewing but no admin actions available

---

## Summary

| TC Range | Scenario Group | Total | ✅ Pass | ❌ Fail |
|----------|---------------|-------|---------|---------|
| TC-111 – TC-118 | Catalogue view, create templates (all write roles) | 8 | 8 | 0 |
| TC-119 – TC-121 | Filter, search, read-only access | 3 | 3 | 0 |
| TC-122 – TC-126 | Equipment Schedules tab, commissioning, alert reschedule | 5 | 5 | 0 |
| TC-127 – TC-128 | Deactivate, dashboard integration | 2 | 2 | 0 |
| TC-129 – TC-130 | Role restriction — no write access | 2 | 0 | 2 |
| TC-131 – TC-134 | Form validation | 4 | 0 | 4 |
| TC-135 | Role restriction — Field Tester | 1 | 0 | 1 |
| **TOTAL** | | **25** | **18** | **7** |

---

*SEACMS UI Test Scenarios — Test Register Module | KPTCL RT&RD | May 2026*
