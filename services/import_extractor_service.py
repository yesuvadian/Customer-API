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
        results.append({
            "id": ct.id,
            "name": name,
            "description": ct.description,
            "has_pdf": "pdf" in extractor,
            "has_excel": "excel" in extractor,
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

    if extractor_type is None:
        return [], [f"No extractor available for '{test_type_name}' with .{ext} files."]

    if ext == "pdf":
        return _extract_pdf(file_bytes, extractor_type)
    elif ext in ("xlsx", "xls"):
        return _extract_excel(file_bytes, extractor_type)
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


def _extract_excel(file_bytes: bytes, extractor_type: str) -> tuple[list[dict], list[str]]:
    warnings: list[str] = []
    try:
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
