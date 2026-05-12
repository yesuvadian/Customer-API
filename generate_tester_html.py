"""
Generate a tester-friendly HTML from SEACMS_UI_TestCases.docx
- Flutter UI language (no HTTP codes, no API paths)
- Interactive Pass/Fail toggle per TC
- Notes field per TC
- Mobile-responsive, printable
"""
import re, xml.etree.ElementTree as ET

DOC  = r"C:\Yesu\CustomerAPI\Customer-API\unpacked_extract\word\document.xml"
OUT  = r"C:\Yesu\CustomerAPI\Customer-API\SEACMS_UI_TestScenarios.html"

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

# ── XML helpers ───────────────────────────────────────────────────────────────
def text_of(elem):
    return ''.join(t.text or '' for t in elem.iter(f'{{{W}}}t')).strip()

def cell_texts(tc):
    return [text_of(p) for p in tc.findall(f'{{{W}}}p') if text_of(p)]

def table_rows(tbl):  return tbl.findall(f'{{{W}}}tr')
def row_cells(tr):    return tr.findall(f'{{{W}}}tc')
def get_style(p):
    pPr = p.find(f'{{{W}}}pPr')
    if pPr is None: return ''
    ps = pPr.find(f'{{{W}}}pStyle')
    return ps.get(f'{{{W}}}val','') if ps is not None else ''

# ── Cleanup: make steps Flutter-UI-friendly ───────────────────────────────────
REPLACEMENTS = [
    # ── API / HTTP references → Flutter UI outcomes ───────────────────────────
    (r'Save returns HTTP 200',                  'Tap Save — success toast appears'),
    (r'returns? HTTP 200',                      'success — confirmation toast shown'),
    (r'HTTP 200',                               'success (green toast shown)'),
    (r'HTTP 4\d\d',                             'error message shown on screen'),
    (r'HTTP \d+',                               'server response received'),
    (r'No API call made',                       'No server request is sent'),
    (r'API call',                               'server request'),
    (r'returns HTTP',                           'shows'),
    (r'snackbar',                               'toast notification'),
    (r'GET /[a-zA-Z0-9/_-]+',                  'page loads'),
    (r'POST /[a-zA-Z0-9/_-]+',                 'form submitted'),
    (r'PUT /[a-zA-Z0-9/_-]+',                  'changes saved'),
    (r'DELETE /[a-zA-Z0-9/_-]+',               'item deleted'),

    # ── Real Flutter navigation paths ─────────────────────────────────────────
    # Settings > Test Templates (Template Designer)
    (r'Navigate to: Settings &gt; Test Templates &gt; select insulation_resistance_test &gt; Edit',
     'Open the side menu → tap "Test Template Management" → find "Insulation Resistance (IR) Test" → tap Edit'),
    (r'Navigate to: Settings > Test Templates > select insulation_resistance_test > Edit',
     'Open the side menu → tap "Test Template Management" → find "Insulation Resistance (IR) Test" → tap Edit'),
    (r'Settings &gt; Test Templates',           'side menu → Test Template Management'),
    (r'Settings > Test Templates',              'side menu → Test Template Management'),
    (r'Test Templates',                         'Test Template Management'),

    # Testing Requests navigation
    (r'Testing Requests &gt; \+ New Request',   'side menu → Testing Requests → tap + (New Request)'),
    (r'Testing Requests > \+ New Request',      'side menu → Testing Requests → tap + (New Request)'),
    (r'Testing Requests &gt; filter by Submitted status',
     'side menu → Testing Requests → tap "All Active" tab → filter by Submitted'),
    (r'Testing Requests > filter by Submitted status',
     'side menu → Testing Requests → tap "All Active" tab → filter by Submitted'),
    (r'Testing Requests &gt;',                  'Testing Requests →'),
    (r'Testing Requests >',                     'Testing Requests →'),

    # My Assignments / Approvals
    (r'My Assignments in the sidebar',          'side menu → Testing Requests → tap "Assigned to Me" tab'),
    (r'Approvals in the sidebar',               'side menu → Test Approvals'),
    (r'open request &gt; Enter Test Results',   'open the request → tap "Enter Test Results"'),
    (r'open request > Enter Test Results',      'open the request → tap "Enter Test Results"'),

    # Equipment
    (r'Equipment Register &gt; Add New Equipment',  'Asset Register → tap "+ Register Asset"'),
    (r'Equipment Register > Add New Equipment',     'Asset Register → tap "+ Register Asset"'),
    (r'Equipment Register',                         'Asset Register'),
    (r'Navigate to Equipment Register',             'Open side menu → tap "Equipment" (Asset Register)'),
    (r'navigate to Equipment Schedules tab',        'tap the "Equipment Schedules" tab'),
    (r'Navigate to Equipment Schedules tab',        'Tap the "Equipment Schedules" tab'),

    # Generic navigation
    (r'Navigate to: Testing Requests',          'Open side menu → tap "Testing Requests"'),
    (r'Navigate to: Test Register',             'Open side menu → tap "Test Register"'),
    (r'Navigate to: Dashboard',                 'Open side menu → tap "Dashboard"'),
    (r'Navigate to:',                           'Go to:'),
    (r'navigate to Test Register',              'open side menu → tap "Test Register"'),
    (r'Navigate to Test Register',              'Open side menu → tap "Test Register"'),
    (r'Dashboard in the sidebar',               'side menu → Dashboard'),
    (r'in the sidebar',                         'in the side menu'),
    (r'Navigation Drawer &gt;',                 'side menu →'),
    (r'Navigation Drawer >',                    'side menu →'),
    (r'Navigation Drawer',                      'side menu (hamburger icon ☰)'),
    (r'sidebar',                                'side menu'),
    (r'/test-register',                         '"Test Register" screen'),
    (r'/equipment',                             '"Asset Register" screen'),
    (r'/notifications',                         '"Notifications" screen'),
    (r'/reports',                               '"Reports" screen'),

    # Dashboard names
    (r'EE TLSS dashboard',                      'EE TLSS Dashboard screen'),
    (r'EE TLSS-role dashboard',                 'EE TLSS Dashboard (loads automatically after login)'),
    (r'AEE dashboard',                          'Dashboard screen'),

    # ── Touch / interaction verbs ─────────────────────────────────────────────
    (r'\bClick on\b',   'Tap'),
    (r'\bclick on\b',   'tap'),
    (r'\bClick\b',      'Tap'),
    (r'\bclick\b',      'tap'),

    # ── Real Flutter field / button labels ────────────────────────────────────
    # Template Designer fields
    (r'ratio\(ir_value_10min, ir_value_1min\)', 'IR(10 min) ÷ IR(1 min)'),
    (r'\bpi_value\b',           '"PI Value" column'),
    (r'\bir_value_1min\b',      '"IR Value (1 min)" column'),
    (r'\bir_value_10min\b',     '"IR Value (10 min)" column'),
    (r'\bir_readings\b',        '"IR Readings" table'),
    (r'\binsulation_resistance_test\b', '"Insulation Resistance (IR) Test"'),
    (r'Column editor panel',    'field editor panel'),
    (r'Type dropdown shows: Text / Number / Calculated', '"Type" dropdown shows options: Text, Number, Calculated'),
    (r'type dropdown',          '"Type" dropdown'),
    (r'Formula field',          '"Formula" field'),
    (r'Formula input field',    '"Formula" input field'),

    # Test Register form fields (exact Flutter labels)
    (r'ALERT Override Days',    '"ALERT Override Interval \(days\)"'),
    (r'ALERT Override =',       '"ALERT Override Interval \(days\)" ='),
    (r'ALERT override = (\d+) days', r'"ALERT Override Interval (days)" = \1'),
    (r'ALERT override of (\d+) days', r'\1-day "ALERT Override Interval (days)"'),
    (r'ALERT Override',         '"ALERT Override Interval \(days\)"'),
    (r'OEM Reference =',        '"OEM Reference / Standard" ='),
    (r'OEM Ref =',              '"OEM Reference / Standard" ='),
    (r'OEM ref',                '"OEM Reference / Standard"'),
    (r'OEM Reference',          '"OEM Reference / Standard"'),
    (r'First Run Date',         '"First Run Date \*"'),
    (r'Equipment Type \*',      '"Equipment Type \*"'),
    (r'Equipment Type =',       '"Equipment Type \*" ='),
    (r'Title =',                '"Test / Maintenance Title \*" ='),
    (r'\bTitle field\b',        '"Test / Maintenance Title \*" field'),
    (r'Enter Title',            'Enter "Test / Maintenance Title \*"'),
    (r'Frequency =',            '"Frequency \*" ='),
    (r'Select Frequency',       'Choose "Frequency \*"'),
    (r'\+ FAB\b',               '"Add Template" button \(+ floating button\)'),
    (r'Tap \+ FAB',             'Tap the "Add Template" + button'),
    (r'\+ FAB',                 '"Add Template" + button'),
    (r'Tap Save\b',             'Tap "Save Changes" \(or "Create"\)'),
    (r'\bTap Save\b',           'Tap "Save Changes" / "Create"'),
    (r'Schedules button',       '"Schedules" button'),
    (r'Deactivate button',      '"Deactivate" button'),
    (r'Edit button',            '"Edit" button'),
    (r'Tap Edit\b',             'Tap "Edit"'),
    (r'Tap Deactivate\b',       'Tap "Deactivate"'),

    # Equipment (Asset Register) form fields
    (r'Add New Equipment',          'tap "+ Register Asset"'),
    (r'Register Asset',             '"Register Asset" form'),
    (r'Equipment name',             'equipment name field'),
    (r'Name = ',                    '"Name" field = '),
    (r'Substation = ',              '"Substation" field = '),

    # Testing request form fields
    (r'New Request form',           '"New Testing Request" form'),
    (r'Title is required to save a draft', '"Title is required to save a draft" error'),
    (r'Due date is required to submit', '"Due date is required to submit" error'),
    (r'\bDraft saved successfully\b', '"Draft saved successfully" toast'),

    # Status labels — exact Flutter UI text
    (r'\bin_progress\b',        'In Progress'),
    (r'\bunder_approval\b',     'Under Approval'),
    (r'\btest_submitted\b',     'Test Submitted'),
    (r'\bprocurement_initiated\b', 'Procurement Initiated'),
    (r'\bprocurement\b',        'Procurement'),

    # ── Technical jargon → plain UI language ─────────────────────────────────
    (r'PI =',                   'Polarisation Index (PI) ='),
    (r'cache\b',                'local data refresh'),
    (r'\bTTL\b',                'refresh interval'),
    (r'\bXSS\b',                'HTML/script injection'),
    (r'dark_green',             'dark green'),
    (r'next_run',               'next due date'),
    (r'first_run',              'first run date'),
    (r'revised_periodicity_days', '"ALERT Override Interval (days)"'),
    (r'is_schedule_template',   'maintenance template'),
    (r'org_id',                 'organisation'),
    (r'equipment_type_id',      'equipment type'),
    (r'tolerance threshold',    'acceptable range'),
    (r'PDF\b',                  'PDF report'),

    # ── Role credentials ──────────────────────────────────────────────────────
    (r'orgadmin@kptcl\.com',        '👤 orgadmin@kptcl.com  (Result Approver)'),
    (r'testassigner@kptcl\.com',    '👤 testassigner@kptcl.com  (Test Assigner)'),
    (r'originator@kptcl\.com',      '👤 originator@kptcl.com  (Originator)'),
    (r'see\.rt@kptcl\.com',         '👤 see.rt@kptcl.com  (SEE RT / Tester)'),
    (r'eetlss@kptcl\.com',          '👤 eetlss@kptcl.com  (EE TLSS)'),
    (r'depthead@kptcl\.com',        '👤 depthead@kptcl.com  (Department Head)'),
    (r'admin@kptcl\.com',           '👤 admin@kptcl.com  (Admin)'),
    (r'field\.tester@kptcl\.com',   '👤 field.tester@kptcl.com  (Field Tester)'),
    (r'Login as ',                  'Login with: '),
]

def clean(text):
    import html as html_mod
    text = html_mod.escape(text)
    for pat, rep in REPLACEMENTS:
        text = re.sub(pat, rep, text)
    return text

# ── Parse document ─────────────────────────────────────────────────────────────
tree = ET.parse(DOC)
body = tree.getroot().find('w:body', {'w': W})
children = list(body)

TC_RE = re.compile(r'^TC-\d+$')

# Summary table (first w:tbl before any Heading1)
summary_rows = []
for child in children:
    if child.tag == f'{{{W}}}tbl':
        for tr in table_rows(child):
            cells = row_cells(tr)
            summary_rows.append([' '.join(cell_texts(c)) for c in cells])
        break

# Sections
sections = []
i = 0
while i < len(children):
    child = children[i]
    if child.tag == f'{{{W}}}p' and get_style(child) == 'Heading1':
        heading = text_of(child)
        ctx, j = [], i + 1
        while j < len(children) and children[j].tag != f'{{{W}}}tbl':
            t = text_of(children[j])
            if t and get_style(children[j]) != 'Heading1':
                ctx.append(t)
            j += 1
        tbl = children[j] if j < len(children) and children[j].tag == f'{{{W}}}tbl' else None
        sections.append((heading, ctx, tbl))
        i = j + 1 if tbl is not None else j
        continue
    i += 1

# Extract TCs per section
parsed_sections = []
for heading, ctx, tbl in sections:
    if 'Summary' in heading: continue
    if tbl is None: continue
    tcs = []
    for tr in table_rows(tbl)[1:]:   # skip header
        cells = row_cells(tr)
        if len(cells) < 5: continue
        tc_num   = ' '.join(cell_texts(cells[0]))
        module   = ' '.join(cell_texts(cells[1]))
        steps    = cell_texts(cells[2])
        expected = cell_texts(cells[3])
        status   = ' '.join(cell_texts(cells[4]))
        if not TC_RE.match(tc_num.strip()): continue
        tcs.append({'id': tc_num, 'module': module, 'steps': steps,
                    'expected': expected, 'status': status})
    parsed_sections.append({'heading': heading, 'ctx': ctx, 'tcs': tcs})

# ── Role detection ─────────────────────────────────────────────────────────────
ROLE_COLORS = {
    'Admin':            '#1B3A6B',
    'SuperAdmin':       '#1B3A6B',
    'SEE RT':           '#00695C',
    'EE TLSS':          '#00695C',
    'Department Head':  '#00695C',
    'Originator':       '#6A1B9A',
    'Test Assigner':    '#E65100',
    'Tester':           '#4527A0',
    'Result Approver':  '#BF360C',
    'Field Tester':     '#37474F',
    'All roles':        '#455A64',
}
def role_badge(text):
    for role, col in ROLE_COLORS.items():
        if role.lower() in text.lower():
            return f'<span class="role-badge" style="background:{col}">{role}</span>'
    return ''

# ── Section color map ──────────────────────────────────────────────────────────
SEC_COLORS = [
    '#1B3A6B','#00695C','#E65100','#4527A0','#4527A0',
    '#4527A0','#BF360C','#455A64','#37474F','#B71C1C','#006064',
]

# ── Build HTML ─────────────────────────────────────────────────────────────────
def tc_html(tc, idx):
    sid = tc['id'].replace('-','_')
    is_fail = tc['status'].upper() == 'FAIL'
    badge_cls = 'status-fail' if is_fail else 'status-pass'
    badge_txt = '❌ Negative Test' if is_fail else '✅ Positive Test'

    steps_html = ''.join(
        f'<li>{clean(s)}</li>' for s in tc['steps']
    )
    exp_html = ''.join(
        f'<li><label><input type="checkbox" class="chk"> {clean(e)}</label></li>'
        for e in tc['expected']
    )
    return f'''
    <div class="tc-card" id="{sid}">
      <div class="tc-header">
        <span class="tc-num">{tc["id"]}</span>
        <span class="tc-module">{clean(tc["module"])}</span>
        <span class="tc-badge {badge_cls}">{badge_txt}</span>
      </div>
      <div class="tc-body">
        <div class="tc-col">
          <div class="col-label">Steps</div>
          <ol class="step-list">{steps_html}</ol>
        </div>
        <div class="tc-col">
          <div class="col-label">Expected Result <small>(tick each item when confirmed)</small></div>
          <ul class="exp-list">{exp_html}</ul>
        </div>
      </div>
      <div class="tc-footer">
        <div class="result-row">
          <span class="result-label">Result:</span>
          <label class="result-btn pass-btn">
            <input type="radio" name="result_{sid}" value="pass" onchange="markResult(this)"> PASS
          </label>
          <label class="result-btn fail-btn">
            <input type="radio" name="result_{sid}" value="fail" onchange="markResult(this)"> FAIL
          </label>
          <label class="result-btn skip-btn">
            <input type="radio" name="result_{sid}" value="skip" onchange="markResult(this)"> SKIP
          </label>
        </div>
        <textarea class="notes-box" placeholder="Notes / defects / observations…" rows="2"
          oninput="saveNote('{sid}', this.value)"></textarea>
      </div>
    </div>'''

def section_html(sec, color):
    heading = sec['heading']
    ctx_html = ''.join(f'<p class="ctx-p">{clean(c)}</p>' for c in sec['ctx'])
    tcs_html = ''.join(tc_html(tc, i) for i, tc in enumerate(sec['tcs']))
    safe_id  = re.sub(r'[^a-z0-9]', '_', heading.lower())
    count    = len(sec['tcs'])
    neg      = sum(1 for t in sec['tcs'] if t['status'].upper() == 'FAIL')
    pos      = count - neg
    return f'''
  <section class="tc-section" id="{safe_id}">
    <div class="section-header" style="border-left:6px solid {color}">
      <h2>{clean(heading)}</h2>
      <div class="section-meta">
        <span class="meta-chip">{count} TCs</span>
        <span class="meta-chip pos">{pos} positive</span>
        <span class="meta-chip neg">{neg} negative</span>
      </div>
    </div>
    {ctx_html}
    {tcs_html}
  </section>'''

# Nav links
nav_links = ''.join(
    f'<a href="#{re.sub(r"[^a-z0-9]","_",s["heading"].lower())}" '
    f'style="border-left:3px solid {SEC_COLORS[i % len(SEC_COLORS)]}">'
    f'{s["heading"]}</a>'
    for i, s in enumerate(parsed_sections)
)

# Summary table
sum_hdr = summary_rows[0] if summary_rows else []
sum_data = summary_rows[1:] if summary_rows else []
sum_html = ''
if sum_hdr:
    th = ''.join(f'<th>{h}</th>' for h in sum_hdr)
    rows_html = ''
    for r in sum_data:
        cls = 'total-row' if r and r[0].strip().upper() == 'TOTAL' else ''
        rows_html += f'<tr class="{cls}">' + ''.join(f'<td>{clean(c)}</td>' for c in r) + '</tr>'
    sum_html = f'<table class="summary-tbl"><thead><tr>{th}</tr></thead><tbody>{rows_html}</tbody></table>'

# Sections
body_html = ''.join(
    section_html(s, SEC_COLORS[i % len(SEC_COLORS)])
    for i, s in enumerate(parsed_sections)
)

HTML = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEACMS — UI Test Scenarios</title>
<style>
  :root {{
    --blue: #1B3A6B; --teal: #006064; --green: #2E7D32;
    --red: #B71C1C;  --grey: #455A64; --bg: #F5F7FA;
    --card: #FFFFFF; --border: #E0E0E0;
    --font: 'Segoe UI', Arial, sans-serif;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: var(--font); background: var(--bg); color: #222; font-size: 14px; }}

  /* Layout */
  .app {{ display: flex; min-height: 100vh; }}
  .sidebar {{
    width: 240px; min-width: 240px; background: var(--blue); color: #fff;
    position: sticky; top: 0; height: 100vh; overflow-y: auto;
    padding: 0; flex-shrink: 0;
  }}
  .sidebar-title {{
    padding: 16px 14px 12px; font-size: 13px; font-weight: 700;
    letter-spacing: .5px; color: #90CAF9; border-bottom: 1px solid rgba(255,255,255,.15);
    text-transform: uppercase;
  }}
  .sidebar a {{
    display: block; padding: 9px 14px; color: rgba(255,255,255,.85);
    text-decoration: none; font-size: 12.5px; border-bottom: 1px solid rgba(255,255,255,.07);
    transition: background .15s;
  }}
  .sidebar a:hover {{ background: rgba(255,255,255,.12); color: #fff; }}
  .progress-bar {{
    height: 4px; background: rgba(255,255,255,.2); margin: 4px 14px 0;
    border-radius: 2px; overflow: hidden;
  }}
  .progress-fill {{ height: 100%; background: #4FC3F7; width: 0%; transition: width .3s; }}

  main {{ flex: 1; padding: 24px 28px; max-width: 1100px; }}

  /* Cover */
  .cover {{
    background: var(--blue); color: #fff; border-radius: 12px;
    padding: 32px 36px; margin-bottom: 32px;
  }}
  .cover h1 {{ font-size: 26px; margin-bottom: 6px; }}
  .cover p  {{ color: rgba(255,255,255,.75); font-size: 13px; margin-top: 4px; }}
  .cover-meta {{ display: flex; gap: 24px; margin-top: 16px; flex-wrap: wrap; }}
  .cover-meta span {{ font-size: 12px; background: rgba(255,255,255,.15);
    padding: 4px 10px; border-radius: 20px; }}

  /* Summary table */
  .summary-tbl {{ width: 100%; border-collapse: collapse; margin-bottom: 32px;
    background: var(--card); border-radius: 8px; overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .summary-tbl th {{ background: var(--blue); color: #fff; padding: 10px 12px;
    font-size: 12px; text-align: left; }}
  .summary-tbl td {{ padding: 9px 12px; border-bottom: 1px solid var(--border);
    font-size: 13px; }}
  .summary-tbl tr.total-row td {{ background: #E8EAF6; font-weight: 700; }}
  .summary-tbl tr:hover td {{ background: #F0F4FF; }}

  /* Section */
  .tc-section {{ margin-bottom: 48px; }}
  .section-header {{
    padding: 14px 18px; background: var(--card); border-radius: 8px;
    margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.07);
    display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;
  }}
  .section-header h2 {{ font-size: 17px; color: var(--blue); }}
  .section-meta {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .meta-chip {{
    font-size: 11px; padding: 3px 10px; border-radius: 12px;
    background: #E8EAF6; color: var(--blue); font-weight: 600;
  }}
  .meta-chip.pos {{ background: #E8F5E9; color: var(--green); }}
  .meta-chip.neg {{ background: #FFEBEE; color: var(--red); }}
  .ctx-p {{ color: #555; font-size: 13px; margin-bottom: 10px;
    padding: 10px 14px; background: #FFF8E1; border-left: 3px solid #FFC107;
    border-radius: 4px; }}

  /* TC Card */
  .tc-card {{
    background: var(--card); border-radius: 8px; margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,.07); border: 1px solid var(--border);
    overflow: hidden; transition: box-shadow .15s;
  }}
  .tc-card:hover {{ box-shadow: 0 3px 10px rgba(0,0,0,.12); }}
  .tc-card.result-pass {{ border-left: 4px solid var(--green); }}
  .tc-card.result-fail {{ border-left: 4px solid var(--red); }}
  .tc-card.result-skip {{ border-left: 4px solid #9E9E9E; }}

  .tc-header {{
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    padding: 10px 14px; background: #F8F9FF; border-bottom: 1px solid var(--border);
  }}
  .tc-num  {{ font-weight: 800; color: var(--blue); font-size: 14px; min-width: 60px; }}
  .tc-module {{ font-weight: 600; color: #333; font-size: 13px; flex: 1; }}
  .tc-badge {{ font-size: 11px; padding: 3px 9px; border-radius: 10px; font-weight: 600; }}
  .status-pass {{ background: #E8F5E9; color: var(--green); }}
  .status-fail {{ background: #FFEBEE; color: var(--red); }}
  .role-badge {{ font-size: 11px; padding: 2px 8px; border-radius: 10px;
    color: #fff; font-weight: 600; }}

  .tc-body {{ display: flex; gap: 0; }}
  .tc-col {{ flex: 1; padding: 12px 14px; border-right: 1px solid var(--border); }}
  .tc-col:last-child {{ border-right: none; }}
  .col-label {{ font-size: 11px; font-weight: 700; text-transform: uppercase;
    color: #888; margin-bottom: 8px; letter-spacing: .5px; }}
  .col-label small {{ text-transform: none; font-weight: 400; color: #aaa; }}

  .step-list {{ padding-left: 18px; }}
  .step-list li {{ margin-bottom: 5px; line-height: 1.5; color: #333; }}
  .exp-list  {{ list-style: none; padding: 0; }}
  .exp-list li {{ margin-bottom: 6px; }}
  .exp-list label {{ display: flex; align-items: flex-start; gap: 8px;
    cursor: pointer; line-height: 1.5; color: #333; }}
  .exp-list input[type=checkbox] {{ margin-top: 3px; flex-shrink: 0;
    width: 15px; height: 15px; accent-color: var(--green); }}

  .tc-footer {{
    padding: 10px 14px; background: #FAFAFA; border-top: 1px solid var(--border);
    display: flex; gap: 12px; align-items: flex-start; flex-wrap: wrap;
  }}
  .result-row {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  .result-label {{ font-size: 12px; font-weight: 700; color: #666; }}
  .result-btn {{ display: flex; align-items: center; gap: 5px; cursor: pointer;
    padding: 5px 12px; border-radius: 16px; font-size: 12px; font-weight: 700;
    border: 2px solid transparent; transition: all .15s; user-select: none; }}
  .pass-btn {{ border-color: var(--green); color: var(--green); }}
  .fail-btn {{ border-color: var(--red);   color: var(--red);   }}
  .skip-btn {{ border-color: #9E9E9E;      color: #666;         }}
  .pass-btn:has(input:checked) {{ background: var(--green); color: #fff; }}
  .fail-btn:has(input:checked) {{ background: var(--red);   color: #fff; }}
  .skip-btn:has(input:checked) {{ background: #9E9E9E;       color: #fff; }}
  input[type=radio] {{ display: none; }}
  .notes-box {{
    flex: 1; min-width: 200px; border: 1px solid #DDD; border-radius: 6px;
    padding: 6px 10px; font-size: 12px; font-family: var(--font); resize: vertical;
    background: #fff; color: #333;
  }}
  .notes-box:focus {{ outline: none; border-color: var(--blue); }}

  /* Stats bar */
  .stats-bar {{
    position: sticky; top: 0; z-index: 10;
    background: var(--card); border-bottom: 1px solid var(--border);
    padding: 8px 28px; display: flex; gap: 20px; align-items: center;
    box-shadow: 0 2px 6px rgba(0,0,0,.06); flex-wrap: wrap;
    margin: 0 -28px 24px; padding: 10px 28px;
  }}
  .stat-pill {{ font-size: 12px; font-weight: 700; padding: 4px 12px;
    border-radius: 14px; }}
  .stat-total {{ background: #E8EAF6; color: var(--blue); }}
  .stat-pass  {{ background: #E8F5E9; color: var(--green); }}
  .stat-fail  {{ background: #FFEBEE; color: var(--red); }}
  .stat-skip  {{ background: #F5F5F5; color: #666; }}
  .stat-pct   {{ font-size: 12px; color: #888; }}

  /* Print */
  @media print {{
    .sidebar, .stats-bar {{ display: none; }}
    .app {{ display: block; }}
    main {{ padding: 0; max-width: 100%; }}
    .tc-card {{ break-inside: avoid; box-shadow: none; }}
    .tc-footer {{ display: none; }}
  }}

  /* Responsive */
  @media (max-width: 900px) {{
    .sidebar {{ display: none; }}
    .tc-body {{ flex-direction: column; }}
    .tc-col  {{ border-right: none; border-bottom: 1px solid var(--border); }}
    main {{ padding: 12px 14px; }}
  }}
</style>
</head>
<body>
<div class="app">
  <nav class="sidebar">
    <div class="sidebar-title">Sections</div>
    {nav_links}
    <div style="padding:14px;">
      <div class="progress-bar"><div class="progress-fill" id="globalProgress"></div></div>
      <p style="font-size:11px;color:rgba(255,255,255,.5);margin-top:6px;" id="progressLabel">0 / 135 done</p>
    </div>
  </nav>
  <main>
    <div class="cover">
      <h1>SEACMS — UI Test Scenarios</h1>
      <p>SubStation Equipment and Asset Condition Monitoring System</p>
      <div class="cover-meta">
        <span>KPTCL RT&amp;RD</span>
        <span>Flutter Web / Mobile App</span>
        <span>135 Test Cases</span>
        <span>May 2026 · v1.1</span>
      </div>
    </div>

    <div class="stats-bar">
      <span class="stat-pill stat-total" id="s-total">135 total</span>
      <span class="stat-pill stat-pass"  id="s-pass">0 pass</span>
      <span class="stat-pill stat-fail"  id="s-fail">0 fail</span>
      <span class="stat-pill stat-skip"  id="s-skip">0 skip</span>
      <span class="stat-pct" id="s-pct">0% complete</span>
      <button onclick="exportResults()"
        style="margin-left:auto;padding:6px 14px;background:var(--blue);color:#fff;
               border:none;border-radius:6px;cursor:pointer;font-size:12px;font-weight:700;">
        Export Results
      </button>
    </div>

    <h3 style="margin-bottom:12px;color:var(--blue);">Summary</h3>
    {sum_html}
    {body_html}
  </main>
</div>

<script>
  const TOTAL = 135;
  const results = {{}};
  const notes   = {{}};

  function markResult(radio) {{
    const sid = radio.name.replace('result_', '');
    results[sid] = radio.value;
    const card = document.getElementById(sid);
    card.classList.remove('result-pass','result-fail','result-skip');
    if (radio.value) card.classList.add('result-' + radio.value);
    localStorage.setItem('seacms_results', JSON.stringify(results));
    updateStats();
  }}

  function saveNote(sid, val) {{
    notes[sid] = val;
    localStorage.setItem('seacms_notes', JSON.stringify(notes));
  }}

  function updateStats() {{
    const vals = Object.values(results);
    const pass = vals.filter(v=>v==='pass').length;
    const fail = vals.filter(v=>v==='fail').length;
    const skip = vals.filter(v=>v==='skip').length;
    const done = pass + fail + skip;
    document.getElementById('s-pass').textContent = pass + ' pass';
    document.getElementById('s-fail').textContent = fail + ' fail';
    document.getElementById('s-skip').textContent = skip + ' skip';
    const pct = Math.round(done / TOTAL * 100);
    document.getElementById('s-pct').textContent = pct + '% complete (' + done + '/' + TOTAL + ')';
    document.getElementById('globalProgress').style.width = pct + '%';
    document.getElementById('progressLabel').textContent = done + ' / ' + TOTAL + ' done';
  }}

  function exportResults() {{
    const lines = ['TC,Result,Notes'];
    for (const [sid, res] of Object.entries(results)) {{
      const tc = sid.replace('_','-');
      const note = (notes[sid] || '').replace(/,/g,'|').replace(/\\n/g,' ');
      lines.push(tc + ',' + res + ',' + note);
    }}
    // Include untouched TCs
    document.querySelectorAll('.tc-card').forEach(card => {{
      const id = card.id;
      if (!results[id]) {{
        const tc = id.replace('_','-');
        lines.push(tc + ',pending,');
      }}
    }});
    const blob = new Blob([lines.join('\\n')], {{type:'text/csv'}});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'SEACMS_TestResults_' + new Date().toISOString().slice(0,10) + '.csv';
    a.click();
  }}

  // Restore saved state
  (function() {{
    const saved = localStorage.getItem('seacms_results');
    const savedNotes = localStorage.getItem('seacms_notes');
    if (saved) {{
      const r = JSON.parse(saved);
      for (const [sid, val] of Object.entries(r)) {{
        const radio = document.querySelector(`input[name="result_${{sid}}"][value="${{val}}"]`);
        if (radio) {{
          radio.checked = true;
          results[sid] = val;
          const card = document.getElementById(sid);
          if (card) card.classList.add('result-' + val);
        }}
      }}
    }}
    if (savedNotes) {{
      const n = JSON.parse(savedNotes);
      for (const [sid, val] of Object.entries(n)) {{
        const ta = document.querySelector(`#${{sid}} .notes-box`);
        if (ta) {{ ta.value = val; notes[sid] = val; }}
      }}
    }}
    updateStats();
  }})();
</script>
</body>
</html>'''

with open(OUT, 'w', encoding='utf-8') as f:
    f.write(HTML)

tc_count = HTML.count('class="tc-card"')
print(f"Written {len(HTML):,} chars — {tc_count} TC cards — {OUT}")
