"""
Build a blank report dict from a test template definition.

Used by PDF/Excel extractors so the extraction skeleton stays in sync with the
form template automatically — no manual updates when columns or rows change.

Convention (shared with _tandelta_test_data, _oil_test_data, etc.):
  - "test_date" is always present; OCR fills it from the PDF header.
  - context_binding keys are present as "" — OCR fills what it can read.
  - table fields are stored under report_list_key(field_key) as a list of rows
    whose identity columns come from default_rows and data columns are None/"".
  - calculated and readonly columns are omitted from the skeleton.
"""

import copy


def report_list_key(field_key: str) -> str:
    """Derive the report list key from a template table field key.

    'idax_test_results'    -> 'idax'
    'winding_test_results' -> 'winding'
    'oil_test_results'     -> 'oil_test'
    """
    for suffix in ("_test_results", "_results"):
        if field_key.endswith(suffix):
            return field_key[: -len(suffix)]
    return field_key


def _build_table(skeleton: dict, field: dict) -> None:
    list_key     = report_list_key(field["key"])
    columns      = field.get("columns", [])
    default_rows = field.get("default_rows", [])

    rows = []
    for dr in default_rows:
        row: dict = {}
        for col in columns:
            ck    = col.get("key", "")
            ctype = col.get("type", "text")
            if not ck or ctype == "calculated":
                continue
            if ctype == "readonly":
                row[ck] = dr.get(ck, "")   # identity value e.g. "HV-GND"
            elif ctype == "number":
                row[ck] = None
            else:
                row[ck] = ""
        rows.append(row)

    skeleton[list_key] = rows


def build_report_skeleton(template: dict) -> dict:
    """Return a blank report dict derived from *template*.

    Call empty_report() to get a fresh deep copy for each parse run.
    """
    skeleton: dict = {"test_date": "YYYY-MM-DD"}

    # Equipment fields declared in context_bindings; OCR fills what it reads.
    for key in template.get("context_bindings", {}):
        skeleton[key] = ""

    for section in template.get("sections", []):
        for field in section.get("fields", []):
            key   = field.get("key", "")
            ftype = field.get("type", "text")

            if not key or ftype == "calculated":
                continue

            if ftype == "readonly":
                # Already covered by context_bindings; skip to avoid overwriting.
                continue

            if ftype == "table":
                _build_table(skeleton, field)
            else:
                if key in skeleton:
                    continue  # context_bindings already set this
                default = field.get("default")
                if ftype == "number":
                    skeleton[key] = default          # None or a numeric default
                elif ftype == "date":
                    skeleton[key] = "YYYY-MM-DD"
                else:
                    skeleton[key] = default or ""

    return skeleton


# In empty_report(), for table fields — return [] instead of default_rows copies
# The parser will build rows dynamically from what it finds in the PDF
def empty_report(template: dict) -> dict:
    report = {}
    for section in template.get("sections", []):
        for field in section.get("fields", []):
            key   = field.get("key", "")
            ftype = field.get("type", "text")
            if ftype == "table":
                report[report_list_key(field["key"])] = []   # ← empty list, not default_rows
            elif ftype in ("calculated", "readonly"):
                pass
            else:
                report[key] = field.get("default", None)
    return report


def resolve_context_binding(binding_path: str, eq, report: dict, field_key: str) -> str:
    """Resolve a context_binding value from the equipment object or report fallback.

    binding_path examples:
      "equipment.manufacturer"          -> eq.manufacturer
      "equipment.factory_serial_number" -> eq.factory_serial_number
      "equipment.department_name"       -> eq.department.name
      "equipment.voltage_class"         -> eq.voltage_class
      "nameplate.*"                     -> falls back to report[field_key]
    """
    val = None
    if eq is not None:
        if binding_path == "equipment.department_name":
            dept = getattr(eq, "department", None)
            val  = getattr(dept, "name", None) if dept else None
        elif binding_path.startswith("equipment."):
            attr = binding_path[len("equipment."):]
            val  = getattr(eq, attr, None)
        # nameplate.* bindings come from DB relations; fall back to report below.

    if val is None or (isinstance(val, str) and not val.strip()):
        val = report.get(field_key, "")

    return str(val) if val is not None else ""
