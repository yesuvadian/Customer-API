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


# ── UI category → DB category_type mapping ───────────────────────────────────
# Each key is what the Flutter UI sends; db_category_type is the value stored
# in CategoryDetails.category_type.  request_category is the TestingRequest
# enum value used when creating the TR.

CATEGORY_TYPE_MAP: dict[str, dict] = {
    "condition_monitoring": {
        "label": "Condition Monitoring",
        "db_category_type": "test",
        "request_category": "test",
    },
    "test": {
        "label": "Test",
        "db_category_type": "test",
        "request_category": "test",
    },
    "inspection": {
        "label": "Inspection",
        "db_category_type": "inspection",
        "request_category": "inspection",
    },
    "maintenance": {
        "label": "Maintenance",
        "db_category_type": "maintenance",
        "request_category": "maintenance",
    },
    "repair": {
        "label": "Repair",
        "db_category_type": None,          # no category_type for repair in DB
        "request_category": "repair_lifecycle",
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
    "Transformer Dissolved Gas Analysis (DGA)":          {"pdf": "oil_test"},
    "Dissolved Gas Analysis":                            {"pdf": "oil_test"},
    "DGA Test":                                          {"pdf": "oil_test"},
    "Capacitance & Tan Delta Test (Transformer)":        {"pdf": "tan_delta"},
    "Tan-Delta, Capacitance & Insulation Diagnostics":   {"pdf": "tan_delta"},
    "Winding Tan-Delta & Capacitance Test":              {"pdf": "tan_delta"},
    "220kV Bushing Tan-Delta Test":                      {"pdf": "tan_delta"},
    "66kV Bushing Tan-Delta Test":                       {"pdf": "tan_delta"},
}


def get_test_types_for_category(category_key: str, db: Session) -> list[dict]:
    """
    Return active CategoryDetails rows for the given import category.

    Filters by CategoryDetails.category_type (DB column) rather than
    keyword guessing.  Each row is annotated with has_pdf / has_excel
    flags derived from the EXTRACTABLE_TEST_TYPES code registry.
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
    non_empty = [v for v in key_row if v is not None and str(v).strip()]
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

    keys = [str(v).strip() if v is not None else f"col_{i}"
            for i, v in enumerate(rows[1])]

    records = []
    for row in rows[3:]:  # data starts at row index 3 (Excel row 4)
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        rec: dict = {}
        for k, v in zip(keys, row):
            rec[k] = str(v).strip() if v is not None and str(v).strip() else None
        records.append(rec)
    return records


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

            # ── Read table sheets (one per table field) ────────────────────────
            # Each table sheet has row1=labels, row2=machine keys, row3=hints, row4+=data
            # A hidden cell in row2 at the last column+1 stores __table_key__=<field_key>
            table_data: dict[str, list[dict]] = {}
            for sheet_name in wb.sheetnames:
                if sheet_name == ws.title:
                    continue
                tws = wb[sheet_name]
                trows = list(tws.iter_rows(values_only=True))
                if len(trows) < 2:
                    continue
                t_key_row = [str(v).strip() if v is not None else "" for v in trows[1]]
                # Find the table field key from the hidden marker
                tbl_field_key = None
                for cell_val in t_key_row:
                    if cell_val.startswith("__table_key__="):
                        tbl_field_key = cell_val.split("=", 1)[1]
                        break
                if not tbl_field_key:
                    # Fall back: use sheet name as key (spaces → underscores)
                    tbl_field_key = sheet_name.lower().replace(" ", "_")
                t_label_row = [str(v).strip() if v is not None else f"col_{i}" for i, v in enumerate(trows[0])]
                t_headers   = [
                    (t_key_row[i] if i < len(t_key_row) and t_key_row[i] and not t_key_row[i].startswith("__") else t_label_row[i])
                    for i in range(len(t_label_row))
                ]
                t_data_start = 3 if len(trows) > 3 else 1
                tbl_rows = []
                for trow in trows[t_data_start:]:
                    if all(v is None for v in trow):
                        continue
                    tbl_row: dict = {}
                    for h, v in zip(t_headers, trow):
                        if h and not h.startswith("__"):
                            tbl_row[h] = str(v) if v is not None else ""
                    if any(v for v in tbl_row.values()):
                        tbl_rows.append(tbl_row)
                if tbl_rows:
                    table_data[tbl_field_key] = tbl_rows

            # Merge table data into every record
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

def build_form_data(
    report: dict,
    test_type_name: str,
    equipment: Optional[object] = None,
) -> dict:
    """
    Build test_data matching the Flutter form's _collectData() output.
    Mirrors what the seed scripts do before create_structured_result().
    """
    extractor = EXTRACTABLE_TEST_TYPES.get(test_type_name, {})
    extractor_type = extractor.get("pdf") or extractor.get("excel")

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
