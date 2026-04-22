# PDF & HTML Rendering Rules for Test Data

**Date**: 2026-04-21  
**Status**: ✅ IMPLEMENTED

---

## Rendering Logic

Both PDF and HTML preview now intelligently render `test_data` JSON based on structure:

### **Rule 1: List of Dicts → Table**

**When**: `value` is a list of dictionaries with consistent keys

**Example JSON**:
```json
{
  "readings": [
    {"phase": "R", "current": "5.2A", "voltage": "230V"},
    {"phase": "Y", "current": "5.1A", "voltage": "228V"},
    {"phase": "B", "current": "5.3A", "voltage": "232V"}
  ]
}
```

**Renders As**:
```
┌─────────────────────────────────────┐
│ READINGS                            │
├─────────┬───────────┬───────────────┤
│ Phase   │ Current   │ Voltage       │
├─────────┼───────────┼───────────────┤
│ R       │ 5.2A      │ 230V          │
│ Y       │ 5.1A      │ 228V          │
│ B       │ 5.3A      │ 232V          │
└─────────┴───────────┴───────────────┘
```

**Features**:
- Headers extracted from first dict keys
- Alternating row colors
- Centered alignment
- Auto column widths

---

### **Rule 2: Simple Key-Value Dict → Two-Column Layout**

**When**: `value` is a dict with **no nested** structures (all values are primitives)

**Example JSON**:
```json
{
  "equipment_details": {
    "manufacturer": "ABB",
    "model_number": "CT-500",
    "serial_number": "SN123456",
    "rated_current": "500A"
  }
}
```

**Renders As**:
```
┌─────────────────────────────────────┐
│ EQUIPMENT DETAILS                   │
├─────────────────────┬───────────────┤
│ Manufacturer        │ ABB           │
│ Model Number        │ CT-500        │
│ Serial Number       │ SN123456      │
│ Rated Current       │ 500A          │
└─────────────────────┴───────────────┘
```

**Features**:
- Left column: field names (bold)
- Right column: values
- Alternating row backgrounds
- Grid lines

---

### **Rule 3: Nested Structure → Section Heading + Recursive**

**When**: `value` is a dict containing **nested** dicts or lists

**Example JSON**:
```json
{
  "ct_ratio_test": {
    "test_parameters": {
      "primary_current": "400A",
      "secondary_current": "5A"
    },
    "measurements": [
      {"reading_no": 1, "ratio": "80.1", "error": "0.125%"},
      {"reading_no": 2, "ratio": "80.0", "error": "0.100%"}
    ]
  }
}
```

**Renders As**:
```
┌─────────────────────────────────────┐
│ CT RATIO TEST                       │  ← Section heading
│                                     │
│ Test Parameters                     │  ← Subsection
│ ├─────────────────┬─────────────┤  │
│ │ Primary Current │ 400A         │  │
│ │ Secondary Curr. │ 5A           │  │
│ └─────────────────┴─────────────┘  │
│                                     │
│ Measurements                        │  ← Subsection
│ ├──────────┬───────┬───────────┤  │
│ │ Reading  │ Ratio │ Error     │  │
│ ├──────────┼───────┼───────────┤  │
│ │ 1        │ 80.1  │ 0.125%    │  │
│ │ 2        │ 80.0  │ 0.100%    │  │
│ └──────────┴───────┴───────────┘  │
└─────────────────────────────────────┘
```

**Features**:
- Section heading styled as subheading
- Recursively processes nested data
- Each subsection follows Rules 1-2

---

## Implementation Details

### **PDF Service** (`services/test_result_pdf_service.py`)

**New Methods**:
```python
def _render_test_data_structure(self, data, story, heading_style, subheading_style, normal_style):
    """Main recursive renderer - determines structure and delegates"""

def _render_table_from_list(self, data_list, story):
    """Renders list of dicts as ReportLab Table"""

def _render_two_column_layout(self, data_dict, story):
    """Renders key-value pairs as 2-column ReportLab Table"""
```

**Before**:
```python
# Old code - everything as 2-column
for key, value in test_data.items():
    test_data_rows.append([field_name, formatted_value])
```

**After**:
```python
# New code - intelligent structure detection
if test_data:
    self._render_test_data_structure(test_data, story, heading_style, subheading_style, normal_style)
```

---

### **HTML Preview** (`routers/testing.py`)

**New Functions**:
```python
def render_test_data_structure(data: dict, depth: int = 0) -> str:
    """Main recursive renderer - returns HTML string"""

def render_table_from_list(data_list: list) -> str:
    """Returns HTML <table> element"""

def render_two_column_layout(data_dict: dict) -> str:
    """Returns HTML <div class="fields"> with 2-column grid"""
```

**Before**:
```python
# Old code - everything as grid fields
for key, value in test_data.items():
    fields_html += f'<div class="field">...</div>'
```

**After**:
```python
# New code - intelligent structure detection
fields_html += '<div class="section"><h3>Test Data</h3>'
fields_html += render_test_data_structure(test_data)
fields_html += '</div>'
```

---

## CSS Styling (HTML)

**Table Styles** (already in CSS):
```css
.data-table {
    width: 100%;
    border-collapse: collapse;
    margin: 15px 0;
}
.data-table th {
    background: #1e3c72;
    color: white;
    padding: 10px;
    text-align: center;
    font-weight: 600;
}
.data-table td {
    padding: 10px;
    text-align: center;
    border: 1px solid #ddd;
}
.data-table tbody tr:nth-child(even) {
    background: #f8f9fa;
}
```

**Two-Column Grid** (already in CSS):
```css
.fields {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 20px;
}
.field {
    background: #f8f9fa;
    padding: 15px;
    border-radius: 8px;
    border-left: 3px solid #667eea;
}
```

---

## Example Test Data Structures

### **CT Ratio Test (Detailed)**
```json
{
  "equipment_info": {
    "manufacturer": "ABB",
    "rated_primary": "400A",
    "rated_secondary": "5A"
  },
  "test_conditions": {
    "temperature": "25°C",
    "humidity": "60%"
  },
  "ratio_measurements": [
    {"load": "100%", "actual_ratio": "80.1", "rated_ratio": "80", "error": "0.125%"},
    {"load": "50%", "actual_ratio": "80.0", "rated_ratio": "80", "error": "0.100%"}
  ]
}
```

**Renders**:
- `equipment_info` → Two-column layout (Rule 2)
- `test_conditions` → Two-column layout (Rule 2)
- `ratio_measurements` → Table (Rule 1)

### **IR Test Template**
```json
{
  "meter_details": {
    "make": "Fluke",
    "model": "1587",
    "calibration_date": "2026-01-15"
  },
  "readings": [
    {"conductor": "R-E", "resistance": "500MΩ", "result": "PASS"},
    {"conductor": "Y-E", "resistance": "480MΩ", "result": "PASS"},
    {"conductor": "B-E", "resistance": "520MΩ", "result": "PASS"}
  ],
  "summary": {
    "minimum_reading": "480MΩ",
    "average_reading": "500MΩ",
    "overall_result": "PASS"
  }
}
```

**Renders**:
- Section "Meter Details" → Two-column (Rule 2)
- Section "Readings" → Table (Rule 1)
- Section "Summary" → Two-column (Rule 2)

---

## Testing

### **Backend Test**:
```bash
# Start backend
cd C:\Yesu\CustomerAPI\Customer-API
uvicorn main:app --reload

# Test PDF
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/testing/results/{result_id}/pdf \
  -o test_result.pdf

# Test HTML
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/testing/results/{result_id}/preview \
  > test_result.html
```

### **Flutter Test**:
```bash
cd C:\Yesu\coginiwattcustomer
flutter run -d chrome

# In app:
1. Navigate to test result
2. Tap 📕 PDF icon → Check table/two-column rendering
3. Tap 📄 HTML icon → Check table/two-column rendering
```

---

## Summary

✅ **Rule 1**: List of dicts → Table with headers  
✅ **Rule 2**: Simple dict → Two-column key-value layout  
✅ **Rule 3**: Nested dict → Section heading + recursive  
✅ **Consistent**: Same logic in PDF and HTML  
✅ **Professional**: Tables and grids properly styled  
✅ **Flexible**: Handles any JSON structure  

**Test data now renders intelligently based on structure!** 🎉
