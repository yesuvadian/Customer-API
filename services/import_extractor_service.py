"""
Import Extractor Service — wraps CLI seed scripts as importable API functions.

Supports:
  PDF:   oil_test    → seed_oil_tests_from_pdf.extract_with_easyocr
         tan_delta   → seed_tandelta_from_pdf.extract_with_easyocr
  Excel: oil_test    → seed_oil_tests_from_excel.parse_excel
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from models import CategoryDetails, Equipment
from category_labels import RequestCategoryLabels
from test_templates import normalize_row_id


# ── UI category → DB category_type mapping ───────────────────────────────────
# Each key is what the Flutter UI sends; db_category_type is the value stored
# in CategoryDetails.category_type.  request_category is the TestingRequest
# enum value used when creating the TR.

CATEGORY_TYPE_MAP: dict[str, dict] = {
    "condition_monitoring": {
        "label": "Condition Monitoring",
        "db_category_type": RequestCategoryLabels.TEST.key,
        "request_category": RequestCategoryLabels.TEST.key,
    },
    "test": {
        "label": RequestCategoryLabels.TEST.value,
        "db_category_type": RequestCategoryLabels.TEST.key,
        "request_category": RequestCategoryLabels.TEST.key,
    },
    "inspection": {
        "label": RequestCategoryLabels.INSPECTION.value,
        "db_category_type": RequestCategoryLabels.INSPECTION.key,
        "request_category": RequestCategoryLabels.INSPECTION.key,
    },
    "maintenance": {
        "label": RequestCategoryLabels.MAINTENANCE.value,
        "db_category_type": RequestCategoryLabels.MAINTENANCE.key,
        "request_category": RequestCategoryLabels.MAINTENANCE.key,
    },
    "repair": {
        "label": RequestCategoryLabels.REPAIR_LIFECYCLE.value,
        "db_category_type": None,          # no category_type for repair in DB
        "request_category": RequestCategoryLabels.REPAIR_LIFECYCLE.key,
    },
}

# Keep IMPORT_CATEGORIES as an alias so the router import doesn't break.
IMPORT_CATEGORIES = CATEGORY_TYPE_MAP


# ── Extractor registry ────────────────────────────────────────────────────────
# Maps CategoryDetails.name → supported file formats and extractor type string.
# This is a code-level registry — the DB has no concept of which test types
# have PDF/Excel extractors.  Add new entries here when new seed scripts exist.

EXTRACTABLE_TEST_TYPES: dict[str, dict] = {
    # Repair — generic row-by-row Excel import; no PDF OCR
    "Repair":                                            {"excel": "repair"},
    "Transformer Oil Test":                              {"pdf": "oil_test",  "excel": "oil_test"},
    "Insulating Oil Test":                               {"pdf": "oil_test",  "excel": "oil_test"},
    "Oil BDV Test":                                      {"pdf": "oil_test",  "excel": "oil_test"},
    "Transformer Dissolved Gas Analysis (DGA)":          {"pdf": "oil_test", "excel": "oil_test"},
    "Dissolved Gas Analysis":                            {"pdf": "oil_test", "excel": "oil_test"},
    "DGA Test":                                          {"pdf": "oil_test", "excel": "oil_test"},
    "Capacitance & Tan Delta Test (Transformer)":        {"pdf": "tan_delta", "excel": "tan_delta"},
    "Tan-Delta, Capacitance & Insulation Diagnostics":   {"pdf": "tan_delta", "excel": "tan_delta"},
    "Winding Tan-Delta & Capacitance Test":              {"pdf": "tan_delta", "excel": "tan_delta"},
    "220kV Bushing Tan-Delta Test":                      {"pdf": "tan_delta", "excel": "tan_delta"},
    "66kV Bushing Tan-Delta Test":                       {"pdf": "tan_delta", "excel": "tan_delta"},
}



def get_test_types_for_category(
    category_key: str,
    db: Session,
) -> list[dict]:
    """
    Return active CategoryDetails rows for the given import category.

    Filters by CategoryDetails.category_type and is_active. The toggle endpoint
    in org_test_templates syncs CategoryDetails.is_active when a template is
    disabled, so this filter automatically reflects Template Designer state.
    """
    cfg = CATEGORY_TYPE_MAP.get(category_key)
    if not cfg:
        return []

    db_category_type: str | None = cfg["db_category_type"]
    request_category: str = cfg["request_category"]

    query = db.query(CategoryDetails).filter(CategoryDetails.is_active.is_(True))
    if db_category_type:
        query = query.filter(CategoryDetails.category_type == db_category_type)

    seen_names: set = set()
    results = []
    for ct in query.order_by(CategoryDetails.name).all():
        name = ct.name or ""
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        extractor = EXTRACTABLE_TEST_TYPES.get(name, {})
        from test_templates import get_template_for_test_type as _get_tpl
        has_template = _get_tpl(name) is not None
        results.append({
            "id": ct.id,
            "name": name,
            "description": ct.description,
            "has_pdf": "pdf" in extractor,
            "has_excel": "excel" in extractor or has_template,  # flat-schema upload supported for all
            "has_template": has_template,
            "extractor_type": extractor.get("pdf") or extractor.get("excel"),
            "request_category": request_category,
        })
    return results


# ── Extractor dispatch ────────────────────────────────────────────────────────

def _extractor_type_for(test_type_name: str, file_ext: str) -> str | None:
    """Return extractor_type string or None if not supported."""
    extractor = EXTRACTABLE_TEST_TYPES.get(test_type_name, {})
    ext = file_ext.lower().lstrip(".")
    if ext in ("xlsx", "xls"):
        ext = "excel"
    return extractor.get(ext)


def extract_records(
    file_bytes: bytes,
    filename: str,
    test_type_name: str,
) -> tuple[list[dict], list[str]]:
    """
    Extract structured report dicts from an uploaded PDF or Excel file.
    Returns (records, warnings).
    """
    ext = Path(filename).suffix.lower().lstrip(".")
    extractor_type = _extractor_type_for(test_type_name, ext)

    if ext == "pdf":
        if extractor_type is None:
            return [], [f"No PDF extractor available for '{test_type_name}'."]
        return _extract_pdf(file_bytes, extractor_type)
    elif ext in ("xlsx", "xls"):
        # Always attempt Excel extraction — flat-schema format works for any test type
        return _extract_excel(file_bytes, extractor_type or "flat_schema", test_type_name)
    else:
        return [], [f"Unsupported file format: .{ext}"]


def _extract_pdf(file_bytes: bytes, extractor_type: str) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    try:
        import fitz
        from PIL import Image

        doc = fitz.open(stream=file_bytes, filetype="pdf")
        images = []
        for page in doc:
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            images.append(img)
        doc.close()

        if not images:
            return [], ["PDF has no pages."]

        if extractor_type == "oil_test":
            from seed_oil_tests_from_pdf import extract_with_easyocr
            records = extract_with_easyocr(images, workers=1)
        elif extractor_type == "tan_delta":
            from seed_tandelta_from_pdf import extract_with_easyocr
            records = extract_with_easyocr(images, workers=1)
        else:
            return [], [f"Unknown extractor type: {extractor_type}"]

        if not records:
            warnings.append("No records could be extracted from the PDF. Check the file format.")

        return records, warnings

    except ImportError as e:
        return [], [f"OCR dependency missing: {e}. Install fitz (PyMuPDF) and easyocr."]
    except Exception as e:
        return [], [f"PDF extraction failed: {e}"]


def _is_flat_schema_format(rows: list) -> bool:
    """
    Detect the flat import schema format:
    Row 1 = visible labels, Row 2 = machine field keys, Row 3 = hints, Row 4+ = data.
    We check that row 2 (index 1) is non-empty and its cells look like snake_case keys
    rather than human labels.
    """
    if len(rows) < 2:
        return False
    key_row = rows[1]
    # Exclude hidden marker cells (start with __) before checking format
    non_empty = [v for v in key_row if v is not None and str(v).strip() and not str(v).startswith("__")]
    if not non_empty:
        return False
    # snake_case keys: lowercase letters, digits, underscores — no spaces
    import re
    return all(re.match(r"^[a-z][a-z0-9_]*$", str(v).strip()) for v in non_empty[:5])


def _parse_flat_schema(rows: list, test_type_name: str) -> list[dict]:
    """
    Parse a flat-schema Excel (generated by /data-import/schema).
    Row 1 = labels (skip), Row 2 = field keys, Row 3 = hints (skip), Row 4+ = data.
    Returns a list of report dicts compatible with build_form_data().
    """
    if len(rows) < 4:
        return []

    import datetime as _dt

    def _cell_str(v):
        if v is None:
            return None
        if isinstance(v, _dt.datetime):
            return v.strftime("%Y-%m-%d")
        if isinstance(v, _dt.date):
            return v.isoformat()
        s = str(v).strip()
        return s if s else None

    keys = [str(v).strip() if v is not None else f"col_{i}"
            for i, v in enumerate(rows[1])]

    records = []
    for row in rows[3:]:  # data starts at row index 3 (Excel row 4)
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        rec: dict = {}
        for k, v in zip(keys, row):
            if k.startswith("__"):   # skip hidden marker cells
                continue
            rec[k] = _cell_str(v)
        records.append(rec)
    return records


def _read_table_sheets(wb, main_sheet_title: str) -> dict[str, list[dict]]:
    """Read extra worksheets generated by the schema builder (one per table field)."""
    table_data: dict[str, list[dict]] = {}
    for sheet_name in wb.sheetnames:
        if sheet_name == main_sheet_title:
            continue
        tws = wb[sheet_name]
        trows = list(tws.iter_rows(values_only=True))
        if len(trows) < 2:
            continue
        t_key_row = [str(v).strip() if v is not None else "" for v in trows[1]]
        # Find the hidden marker __table_key__=<field_key>
        tbl_field_key = None
        for cell_val in t_key_row:
            if cell_val.startswith("__table_key__="):
                tbl_field_key = cell_val.split("=", 1)[1]
                break
        if not tbl_field_key:
            tbl_field_key = sheet_name.lower().replace(" ", "_")
        t_label_row = [str(v).strip() if v is not None else f"col_{i}" for i, v in enumerate(trows[0])]
        t_headers = []
        for i in range(len(t_label_row)):
            k = t_key_row[i] if i < len(t_key_row) else ""
            lbl = t_label_row[i]
            if k.startswith("__") or lbl.startswith("col_"):
                t_headers.append(None)  # sentinel: skip this column
            else:
                t_headers.append(k if k else lbl)
        t_data_start = 3 if len(trows) > 3 else 1
        tbl_rows = []
        for trow in trows[t_data_start:]:
            if all(v is None for v in trow):
                continue
            tbl_row: dict = {}
            for h, v in zip(t_headers, trow):
                if h:  # None sentinel means skip
                    cell = str(v) if v is not None else ""
                    tbl_row[h] = normalize_row_id(cell) if h == "test_configuration" else cell
            if any(v for v in tbl_row.values()):
                tbl_rows.append(tbl_row)
        if tbl_rows:
            table_data[tbl_field_key] = tbl_rows
    return table_data


def _extract_excel(file_bytes: bytes, extractor_type: str, test_type_name: str = "") -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    try:
        # ── Always attempt flat-schema detection first (works for all test types) ──
        import openpyxl as _opxl
        import tempfile as _tmp
        _tf = _tmp.NamedTemporaryFile(suffix=".xlsx", delete=False)
        _tf.write(file_bytes)
        _tf.flush()
        _tf_path = Path(_tf.name)
        _tf.close()
        try:
            _wb = _opxl.load_workbook(_tf_path, data_only=True)
            _ws = _wb.active
            _rows = list(_ws.iter_rows(values_only=True))
        finally:
            _tf_path.unlink(missing_ok=True)

        if _is_flat_schema_format(_rows):
            records = _parse_flat_schema(_rows, test_type_name)
            if not records:
                warnings.append("No data rows found in the schema template. Fill in rows from row 4 onwards.")
            else:
                table_data = _read_table_sheets(_wb, _wb.active.title)
                if table_data:
                    for rec in records:
                        rec.update(table_data)
                for rec in records:
                    rec["_flat_schema"] = True          # NEW
            return records, warnings

        if extractor_type == "oil_test":
            from seed_oil_tests_from_excel import parse_excel

            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)

            try:
                records = parse_excel(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)

            if not records:
                warnings.append("No records extracted from Excel. Check sheet layout.")
            return records, warnings
        
        elif extractor_type == "tan_delta":
            from seed_tandelta_from_excel import parse_excel

            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)

            try:
                records = parse_excel(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)

            if not records:
                warnings.append("No records extracted from Excel. Check sheet/block layout.")
            return records, warnings

        elif extractor_type == "repair":
            # Generic row-by-row Excel reader for repair records.
            # Treats each non-header row as one record; all columns become form_data fields.
            import openpyxl

            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = Path(tmp.name)

            try:
                wb = openpyxl.load_workbook(tmp_path, data_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
            finally:
                tmp_path.unlink(missing_ok=True)

            if not rows:
                return [], ["Excel file is empty."]

            # Row 1 = visible labels, Row 2 = machine keys, Row 3 = hints, Row 4+ = data
            # Prefer machine keys (row 2) when available; fall back to label row (row 1).
            label_row = [str(v).strip() if v is not None else f"col_{i}" for i, v in enumerate(rows[0])]
            key_row   = [str(v).strip() if v is not None else "" for v in rows[1]] if len(rows) > 1 else []
            headers   = [
                (key_row[i] if i < len(key_row) and key_row[i] and not key_row[i].startswith("__") else label_row[i])
                for i in range(len(label_row))
            ]
            # Data starts at row 4 (index 3) when hint row is present, else row 2 (index 1)
            data_start = 3 if len(rows) > 3 else 1

            records = []
            for row in rows[data_start:]:
                if all(v is None for v in row):
                    continue
                rec: dict = {}
                for h, v in zip(headers, row):
                    rec[h] = str(v) if v is not None else ""
                # Map common column names to standard fields
                rec.setdefault("serial_number", rec.get("serial_number", rec.get("Serial Number", rec.get("serial", ""))))
                rec.setdefault("test_date",     rec.get("test_date",     rec.get("Date of Test", rec.get("Date", ""))))
                rec.setdefault("sub_station",   rec.get("sub_station",   rec.get("Sub Station", rec.get("Substation", ""))))
                records.append(rec)

            # ── Read table sheets and merge into records ───────────────────────
            table_data = _read_table_sheets(wb, ws.title)
            for rec in records:
                rec.update(table_data)

            if not records:
                warnings.append("No data rows found in Excel. Check the file layout.")
            return records, warnings

        else:
            return [], [f"Excel extraction not supported for type: {extractor_type}"]

    except ImportError as e:
        return [], [f"Excel dependency missing: {e}. Install openpyxl."]
    except Exception as e:
        return [], [f"Excel extraction failed: {e}"]


# ── Form data builder ─────────────────────────────────────────────────────────

def build_form_data(report, test_type_name, equipment=None):
    extractor = EXTRACTABLE_TEST_TYPES.get(test_type_name, {})
    extractor_type = extractor.get("pdf") or extractor.get("excel")

    if report.get("_flat_schema"):
        clean = {k: v for k, v in report.items() if k != "_flat_schema"}
        return clean

    if extractor_type == "oil_test":
        from seed_oil_tests_from_pdf import _oil_test_data
        return _oil_test_data(report, equipment)
    elif extractor_type == "tan_delta":
        from seed_tandelta_from_pdf import _tandelta_test_data
        return _tandelta_test_data(report, equipment)
    else:
        return report


# ── Equipment resolver ────────────────────────────────────────────────────────

def resolve_equipment(serial_number: str | None, equipment_id: UUID | None, db: Session):
    """Resolve equipment from serial_number or equipment_id."""
    if equipment_id:
        return db.query(Equipment).filter(Equipment.id == equipment_id).first()
    if serial_number:
        return (
            db.query(Equipment)
            .filter(Equipment.factory_serial_number == serial_number)
            .first()
        )
    return None


# ── Template key lookup ───────────────────────────────────────────────────────

def get_template_key(test_type_name: str) -> str | None:
    from test_templates import TEST_TYPE_TO_TEMPLATE
    return TEST_TYPE_TO_TEMPLATE.get(test_type_name)


# ── Blank import-template (schema) workbook builder ───────────────────────────
# Shared by:
#   - GET /data-import/schema        (generic, no equipment context - always
#     includes every section, visibility_data=None)
#   - GET /testing/results/{id}/import-schema (scoped to one equipment - only
#     includes sections/fields applicable to its voltage_ratio)
#
# Sheet 1 ("Import Data") holds scalar fields: row 1 = visible label, row 2 =
# hidden machine key, row 3 = hint, row 4 = where the value goes. One sheet
# per table field: row 1 = label, row 2 = hidden key (+ a "__table_key__=..."
# marker cell), row 3 = hint, rows 4+ = data (pre-filled from default_rows).
# parse_structured_import_workbook() reads this exact shape back.

def build_import_schema_workbook(tpl: dict | None, visibility_data: dict | None = None):
    """Build a blank Excel import template workbook from a template
    definition dict (as returned by test_templates.get_template_for_test_type).

    visibility_data: when given (e.g. {"voltage_ratio": "400"}), sections/
    fields whose visibility_rule evaluates to False against it are omitted
    entirely - used for a single-equipment-scoped download. Pass None for
    the generic bulk-import download, which has no equipment context yet
    and so must include every section unconditionally.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from services.visibility_rule import is_template_field_visible

    def _visible(section: dict, field: dict) -> bool:
        if visibility_data is None:
            return True
        return is_template_field_visible(section, field, visibility_data)

    # Fixed identity columns always present (needed for equipment matching)
    fixed_cols = [
        ("sub_station",   "Sub Station",   "Name of substation / location"),
        ("serial_number", "Serial Number", "Equipment serial number (used to match equipment)"),
        ("test_date",     "Date of Test",  "YYYY-MM-DD format"),
    ]

    # Dynamic scalar columns + collect table field definitions
    dyn_cols: list[tuple[str, str, str]] = []
    table_fields: list[dict] = []
    if tpl:
        for sec in tpl.get("sections", []):
            sec_title = sec.get("title", "")
            for f in sec.get("fields", []):
                if not _visible(sec, f):
                    continue
                ftype = f.get("type", "text")
                if ftype == "table":
                    table_fields.append(f)
                    continue
                if ftype in ("calculated", "readonly"):
                    continue
                if f.get("import_skip"):
                    continue
                key   = f.get("key", "")
                label = f.get("label", key)
                hint  = f.get("unit", "") or f.get("hint", "") or sec_title
                if key:
                    dyn_cols.append((key, label, hint))

    all_cols = fixed_cols + dyn_cols

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Import Data"

    header_fill = PatternFill("solid", fgColor="1E3A5F")
    hint_fill   = PatternFill("solid", fgColor="EFF6FF")
    table_fill  = PatternFill("solid", fgColor="1E3A5F")
    row_fill    = PatternFill("solid", fgColor="F8FAFF")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    hint_font   = Font(italic=True, color="6B7280", size=9)
    key_font    = Font(color="FFFFFF", size=1)

    for ci, (key, label, hint) in enumerate(all_cols, start=1):
        # Row 1: visible header label
        h = ws.cell(row=1, column=ci, value=label)
        h.font      = header_font
        h.fill      = header_fill
        h.alignment = Alignment(horizontal="center", wrap_text=True)

        # Row 2: machine key (hidden — white on white)
        k = ws.cell(row=2, column=ci, value=key)
        k.font = key_font

        # Row 3: hint
        hnt = ws.cell(row=3, column=ci, value=hint)
        hnt.font      = hint_font
        hnt.fill      = hint_fill
        hnt.alignment = Alignment(wrap_text=True)

        # Column width
        ws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = max(18, len(label) + 4)

    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 0   # hide key row
    ws.row_dimensions[3].height = 20
    ws.freeze_panes = "A4"

    # ── One sheet per table field ──────────────────────────────────────────────
    for tf in table_fields:
        tbl_key   = tf.get("key", "table")
        tbl_label = tf.get("label", tbl_key)

        # Only editable, non-calculated columns
        editable_cols = [
            c for c in tf.get("columns", [])
            if c.get("type") not in ("calculated",) and not c.get("read_only")
        ]
        if not editable_cols:
            continue

        # Sheet name: strip Excel-invalid chars, truncate to 31 chars
        import re as _re
        sheet_name = _re.sub(r'[:\\/?*\[\]]', '', tbl_label)[:31]
        tws = wb.create_sheet(title=sheet_name)

        # Row 1: visible label  Row 2: machine key (hidden)  Row 3: unit hint
        for ci, col in enumerate(editable_cols, start=1):
            col_key   = col.get("key", f"col{ci}")
            col_label = col.get("label", col_key)
            col_hint  = col.get("unit", "") or col.get("placeholder", "")

            h = tws.cell(row=1, column=ci, value=col_label)
            h.font      = header_font
            h.fill      = table_fill
            h.alignment = Alignment(horizontal="center", wrap_text=True)

            k = tws.cell(row=2, column=ci, value=col_key)
            k.font = key_font

            hnt = tws.cell(row=3, column=ci, value=col_hint)
            hnt.font      = hint_font
            hnt.fill      = hint_fill
            hnt.alignment = Alignment(wrap_text=True)

            tws.column_dimensions[openpyxl.utils.get_column_letter(ci)].width = max(18, len(col_label) + 4)

        # Row 1 in col 0 (A): store table field key as a hidden marker
        meta_cell = tws.cell(row=2, column=len(editable_cols) + 1, value=f"__table_key__={tbl_key}")
        meta_cell.font = key_font

        tws.row_dimensions[1].height = 28
        tws.row_dimensions[2].height = 0
        tws.row_dimensions[3].height = 18
        tws.freeze_panes = "A4"

        # Pre-fill default rows (starting at row 4)
        default_rows = tf.get("default_rows", [])
        for ri, drow in enumerate(default_rows, start=4):
            for ci, col in enumerate(editable_cols, start=1):
                val = drow.get(col.get("key", ""), "")
                cell = tws.cell(row=ri, column=ci, value=val if val != "" else None)
                if ri % 2 == 0:
                    cell.fill = row_fill
        # Add 5 blank rows after defaults for extra data
        start_blank = max(4, 4 + len(default_rows))
        for ri in range(start_blank, start_blank + 5):
            for ci in range(1, len(editable_cols) + 1):
                cell = tws.cell(row=ri, column=ci, value=None)
                if ri % 2 == 0:
                    cell.fill = row_fill

    return wb


def parse_structured_import_workbook(file_bytes: bytes, tpl: dict | None = None) -> dict:
    """Parse an Excel file matching the exact structure
    build_import_schema_workbook() produces - i.e. the user's filled-in
    downloaded template - back into a form_data dict ready to merge into a
    live TestResultForm's state.

    Reads by the hidden machine key embedded in row 2 of every sheet, not
    by fuzzy label matching - safe to do because we control both ends of
    this round trip (unlike the messy-real-world-document OCR parsers in
    seed_tandelta_from_pdf.py / seed_tandelta_from_excel.py, which this
    function does NOT share code with).

    tpl is currently unused but accepted for symmetry with
    build_import_schema_workbook and in case future validation against the
    live schema is wanted (e.g. rejecting a stale downloaded copy).
    """
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    form_data: dict = {}

    def _row_has_data(row) -> bool:
        return any(v not in (None, "") for v in row)

    # ── Sheet 1: scalar fields ("Import Data") ──────────────────────────────
    if "Import Data" in wb.sheetnames:
        ws = wb["Import Data"]
        keys = [c.value for c in next(ws.iter_rows(min_row=2, max_row=2))]
        for row in ws.iter_rows(min_row=4, values_only=True):
            if not _row_has_data(row):
                continue
            for key, val in zip(keys, row):
                if key and val not in (None, ""):
                    form_data[str(key)] = val
            break  # exactly one data row expected for a single test result

    # ── Remaining sheets: one per table field ───────────────────────────────
    for sheet_name in wb.sheetnames:
        if sheet_name == "Import Data":
            continue
        ws = wb[sheet_name]
        key_row = next(ws.iter_rows(min_row=2, max_row=2))

        table_key = None
        marker_idx = None
        for idx, cell in enumerate(key_row):
            if isinstance(cell.value, str) and cell.value.startswith("__table_key__="):
                table_key = cell.value.split("=", 1)[1]
                marker_idx = idx
                break
        if table_key is None:
            continue  # not a sheet this format recognises - skip quietly

        col_keys = [c.value for c in key_row[:marker_idx]]
        n_cols = len(col_keys)

        rows_out: list[dict] = []
        for row in ws.iter_rows(min_row=4, max_col=n_cols, values_only=True):
            if not _row_has_data(row):
                continue
            row_dict = {}
            for key, val in zip(col_keys, row):
                if key:
                    row_dict[str(key)] = val if val is not None else ""
            rows_out.append(row_dict)

        if rows_out:
            form_data[table_key] = rows_out

    return form_data
