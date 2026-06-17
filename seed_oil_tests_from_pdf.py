"""
Reusable pipeline: KPTCL Transformer Oil Test PDF → DB seed.

Usage:
    # Extract PDFs, save JSON AND seed DB (default)
    python seed_oil_tests_from_pdf.py --from-pdf report.pdf
    python seed_oil_tests_from_pdf.py --from-pdf /folder/

    # Extract PDFs, save JSON only — no DB writes
    python seed_oil_tests_from_pdf.py --from-pdf /folder/ --emit-only

    # Seed from a previously saved / edited JSON
    python seed_oil_tests_from_pdf.py --from-json reports.json
    python seed_oil_tests_from_pdf.py --from-json reports.json --dry-run

    # Print a blank JSON template
    python seed_oil_tests_from_pdf.py --template > reports.json

Pipeline (--from-pdf):
    1. PDF pages → PIL images       (fitz / PyMuPDF)
    2. Images → raw text            (EasyOCR)
    3. Raw text → structured JSON   (regex parser, always saved to data/)
    4. JSON → DB records            (SQLAlchemy, status=closed) — skipped with --emit-only

Supports any KPTCL R&D Centre oil test report layout.
Idempotent — skips reports already seeded (matched by request_number).
"""

import argparse
import io
import json
import re
import sys
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image
from database import VendorSessionLocal as _SessionLocal
from sqlalchemy import text
from sqlalchemy.exc import InvalidRequestError
from models import (
    CategoryDetails,
    Equipment,
    OrgDepartment,
    Organization,
    TestingRequest,
    TestingRequestStatus,
    TestResult,
    User,
)
from report_skeleton import build_report_skeleton, resolve_context_binding


# ── Template-derived skeleton ──────────────────────────────────────────────────

def _load_template() -> dict:
    from test_templates import TEST_TEMPLATES
    return TEST_TEMPLATES.get("transformer_oil_test", {})

_TEMPLATE = _load_template()

# The skeleton is fully derived from the template.
# oil_test_results → report_list_key strips "_test_results" → list key "oil"
# dga_results      → report_list_key strips "_results"      → list key "dga"
# The OCR parser fills measured_value / value_bottom directly into those rows.
_SKELETON = build_report_skeleton(_TEMPLATE)
_SKELETON.update({"sample_no": "", "standard": "IS 10593:2017"})

def _empty_report() -> dict:
    import copy
    return copy.deepcopy(_SKELETON)


# ── OCR helpers ───────────────────────────────────────────────────────────────

def _num(s: str) -> float | None:
    """Parse a number string, handling scientific notation like 121.32X10E12."""
    if not s:
        return None
    s = s.strip().upper().replace(",", "").replace("O", "0")
    # e.g. 121.32X10E12 ohm-cm → convert to G ohm m
    m = re.match(r"([\d.]+)[X*](10E?(\d+))", s)
    if m:
        base = float(m.group(1))
        exp  = int(m.group(3))
        ohm_cm = base * (10 ** exp)
        return round(ohm_cm / 100 / 1e9, 3)  # ohm-cm → G ohm m
    try:
        return float(re.sub(r"[^\d.\-]", "", s))
    except ValueError:
        return None


def _find(pattern: str, text: str, group: int = 1) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(group).strip() if m else None


def _parse_date_str(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d-%b-%y", "%d-%b-%Y",
                "%d/%m/%y", "%d\\%m\\%y", "%d\\%m\\%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_ocr_text(text: str) -> dict | None:
    """Parse raw OCR text from one KPTCL oil test report page into a report dict."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    full  = "\n".join(lines)

    # Must contain oil test indicators to be a valid report page
    if not re.search(r"(acidity|break down|interfacial|dissolved gas)", full, re.I):
        return None

    report = _empty_report()

    # ── Header fields ──────────────────────────────────────────────────────────
    report["sample_no"]  = _find(r"sample\s*no[:\.]?\s*(\d+)", full) or ""
    report["sub_station"] = _find(r"sub[- ]?station\s*[:\.]?\s*(.+?)(?:\n|$)", full) or ""

    # Try multiple label variants for test date
    _date_pat = r"([\d]{1,2}[/\-\\][\d]{1,2}[/\-\\][\d]{2,4})"
    date_str = (
        _find(r"date\s*of\s*test(?:ing)?\s*[:\.]?\s*" + _date_pat, full)
        or _find(r"date\s*of\s*analys[ie]s\s*[:\.]?\s*" + _date_pat, full)
        or _find(r"(?:^|\n)\s*date\s*[:\.]?\s*" + _date_pat, full)
        or _find(r"\bdt[:\.]?\s*" + _date_pat, full)
        or _find(r"tested\s*on\s*[:\.]?\s*" + _date_pat, full)
        # fallback: grab first date-like token in the header (first 20 lines)
        or _find(_date_pat, "\n".join(lines[:20]))
    )
    report["test_date"] = _parse_date_str(date_str) or ""
    if not report["test_date"]:
        print("  [DEBUG] date not found. First 25 OCR lines:")
        for i, l in enumerate(lines[:25]):
            print(f"    {i:02d}: {l}")

    # Serial numbers: try label match first, then known KPTCL serial patterns
    serial = _find(r"serial\s*(?:number|no\.?)\s*[:\.]?\s*([A-Za-z]{2,3}[-\s]?\d{3,}[/\-]\d+)", full)
    if not serial:
        # HT-1690/12569, KT-100000/51 — HT/KT prefix, optional dash, digits/slash/digits
        serial = _find(r"\b((?:HT|KT)-?\d{3,}[/\-]\d+)\b", full)
    # Normalise: insert dash if missing (HT1690/12569 → HT-1690/12569)
    if serial:
        import re as _re
        serial = _re.sub(r'^(HT|KT)(\d)', r'\1-\2', serial)
    report["serial_number"] = serial or ""
    report["make"]          = _find(r"\b(emco|bhel|abb|siemens|crompton)\b", full) or ""
    report["capacity_mva"]  = _find(r"(\d+)\s*mva", full) or ""
    report["voltage_class"] = _find(r"(\d+\s*/\s*\d+)\s*kv", full) or ""

    doc_str = _find(r"date\s*of\s*comm[:\.]?\s*([\d/\-\w]+)", full)
    report["date_of_commission"] = _parse_date_str(doc_str)

    if re.search(r"10593.?2017", full):
        report["standard"] = "IS 10593:2017"
    elif re.search(r"10593.?2000", full):
        report["standard"] = "IS 10593:2000"
    elif re.search(r"60599", full):
        report["standard"] = "IEC 60599:2022"
    else:
        report["standard"] = "IS 10593:2017"

    # ── Oil test values ────────────────────────────────────────────────────────
    # The test result value always appears immediately before Good/Fair/Poor/Ok
    # Pattern: <label row text> ... <value>  Good|Fair|Poor|Ok
    def result_before_rating(label: str) -> float | None:
        m = re.search(
            label + r"[\s\S]{0,300}?([\d.]+(?:[xX*]10E?\d+)?)\s*(?:Good|Fair|Poor|Ok)\b",
            full, re.I
        )
        return _num(m.group(1)) if m else None

    # Fill directly into the template-derived row list (report["oil"]).
    def _set_oil(name_fragment: str, ocr_pat: str, remark: str = "") -> None:
        val = result_before_rating(ocr_pat)
        for row in report.get("oil", []):
            if name_fragment.lower() in row.get("test_name", "").lower():
                row["measured_value"] = val
                if remark:
                    row["remarks"] = remark
                break

    _set_oil("Acidity",             r"acidity")
    _set_oil("Resistivity",         r"resistivity|specific\s*resistance")
    _set_oil("Tan Delta",           r"dielectric\s*dissipation|tan.?delta")
    _set_oil("BDV Bottom",          r"break\s*down\s*voltage")
    _set_oil("Interfacial Tension", r"interfacial\s*tension")
    _set_oil("Flash Point",         r"flash\s*point")
    _set_oil("Water Content",       r"water\s*content")

    bdv_remark = _find(r"break\s*down\s*voltage.*?(\bsampling\s*error[^\n]*)", full)
    if bdv_remark:
        _set_oil("BDV Bottom", r"break\s*down\s*voltage", bdv_remark.strip())

    # ── DGA values ─────────────────────────────────────────────────────────────
    # Each gas row: <Gas Name> <Formula> <permissible limits...> <Top (empty)> <Bottom value>
    # The Bottom value is the LAST number in the row before the next gas row starts.
    # We match from the gas label up to the next gas label or end of DGA section,
    # then take the last number found — this skips permissible limit numbers.
    GAS_ANCHORS = (
        r"methane", r"ethane", r"ethylene", r"acetylene",
        r"hydrogen", r"carbon.?di.?oxide", r"carbon\s*monoxide", r"TGC",
        r"remarks", r"note"
    )
    next_gas_pat = "(?:" + "|".join(GAS_ANCHORS) + ")"

    def gas_bottom(label: str, next_labels: str) -> float | None:
        # Find block from this gas label to the next
        m = re.search(label + r"[\s\S]{0,200}?" + next_labels, full, re.I)
        if not m:
            # Last row — take everything after the label
            m2 = re.search(label + r"([\s\S]{0,200})", full, re.I)
            block = m2.group(1) if m2 else ""
        else:
            block = full[m.start():m.end()]
        # ND / not detected → None
        if re.search(r"\bND\b", block, re.I):
            return None
        # Top/Bottom columns appear AFTER all permissible limit columns.
        # Strategy: take the last two numbers in the block — they map to Top, Bottom.
        # If only one trailing number exists, it is the Bottom value.
        # Permissible limit ranges (e.g. "50-70") are split into ints by findall;
        # actual readings are either decimals (4.26) or 0.
        all_nums = re.findall(r"\b(\d+(?:\.\d+)?)\b", block)
        candidates = [_num(n) for n in all_nums if _num(n) is not None]
        if not candidates:
            return None
        # If the last value is a decimal it is almost certainly the reading
        if len(candidates) >= 1 and '.' in str(all_nums[-1]):
            return candidates[-1]
        # Otherwise take the last value (handles integer readings like 0, 52, 164)
        return candidates[-1]

    # Fill directly into the template-derived row list (report["dga"]).
    def _set_dga(gas_fragment: str, ocr_pat: str) -> None:
        val = gas_bottom(ocr_pat, next_gas_pat)
        for row in report.get("dga", []):
            if gas_fragment.lower() in row.get("gas", "").lower():
                row["value_bottom"] = val
                break

    _set_dga("Methane",         r"methane\s*(?:CH4)?")
    _set_dga("Ethane",          r"ethane\s*(?:C2H6)?")
    _set_dga("Ethylene",        r"ethylene\s*(?:C2H4)?")
    _set_dga("Acetylene",       r"acetylene\s*(?:C2H2)?")
    _set_dga("Hydrogen",        r"hydrogen\s*(?:H2)?")
    _set_dga("Carbon Dioxide",  r"carbon.?di.?oxide\s*(?:CO2)?")
    _set_dga("Carbon Monoxide", r"carbon\s*monoxide\s*(?:CO)?")
    _set_dga("TGC",             r"TGC")

    # DGA scalar fields (stored at top level, not in rows)
    if re.search(r"within\s*limits?", full, re.I):
        report["dga_overall"]  = "Normal — Gases within limits"
        report["dga_remarks"]  = "The gases are within limits."
    elif re.search(r"alert|monitor", full, re.I):
        report["dga_overall"]  = "Alert — Monitor closely"

    # Determine if DGA section exists
    has_dga = any(row.get("value_bottom") is not None for row in report.get("dga", []))
    if not has_dga:
        report["dga"] = None

    # Skip page if no meaningful data extracted
    if not report.get("serial_number") and not report.get("sample_no"):
        return None

    return report


def pdf_to_pil_images(pdf_path: Path) -> list:
    """Convert each PDF page to a PIL Image."""
    doc = fitz.open(str(pdf_path))
    images = []
    for page in doc:
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    doc.close()
    return images


def _ocr_page_worker(args):
    """Worker function: OCR a single page (runs in a subprocess)."""
    import sys, io as _io, warnings
    warnings.filterwarnings("ignore")
    page_idx, img_bytes = args
    import easyocr
    import numpy as np
    from PIL import Image

    # Capture prints from parse_ocr_text so they surface in the main process
    buf = _io.StringIO()
    sys.stdout = buf
    try:
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        img = Image.open(io.BytesIO(img_bytes))
        result = reader.readtext(np.array(img), detail=0, paragraph=True)
        text = "\n".join(result)
        parsed = parse_ocr_text(text)
    finally:
        sys.stdout = sys.__stdout__
    logs = buf.getvalue().strip()
    return page_idx, parsed, logs


def extract_with_easyocr(images: list, workers: int = 1) -> list[dict]:
    """Run EasyOCR on a list of PIL images and parse each into a report dict."""
    import numpy as np

    # Serialize images to bytes so they can be sent to subprocesses
    page_args = []
    for i, img in enumerate(images):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        page_args.append((i, buf.getvalue()))

    results = {}  # page_idx → parsed dict or None

    if workers <= 1:
        import warnings, easyocr
        warnings.filterwarnings("ignore")
        print("  Loading EasyOCR model (first run downloads ~200MB)...", flush=True)
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        for i, img in enumerate(images):
            print(f"  Page {i + 1}/{len(images)}...", end=" ", flush=True)
            result = reader.readtext(np.array(img), detail=0, paragraph=True)
            text = "\n".join(result)
            parsed = parse_ocr_text(text)
            results[i] = parsed
            if parsed:
                print(f"OK — serial={parsed.get('serial_number')} sample={parsed.get('sample_no')}")
            else:
                print("no report data found, skipped.")
    else:
        print(f"  Using {workers} parallel worker(s)...", flush=True)
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_ocr_page_worker, arg): arg[0] for arg in page_args}
            completed = 0
            for future in as_completed(futures):
                page_idx, parsed, logs = future.result()
                results[page_idx] = parsed
                completed += 1
                status = f"OK — serial={parsed.get('serial_number')} sample={parsed.get('sample_no')}" if parsed else "skipped"
                print(f"  Page {page_idx + 1}/{len(images)} [{completed} done] {status}", flush=True)
                if logs:
                    for line in logs.splitlines():
                        print(f"    {line}", flush=True)

    # Return in original page order, filtered to valid reports
    return [results[i] for i in sorted(results) if results[i]]


# ── Template-driven data builder ──────────────────────────────────────────────
# Mirrors the UI's _collectData() — walks the template sections/fields and
# populates values from the extracted report dict, so the seeded test_data
# always matches what the form would produce.

def _oil_test_data(r: dict, eq=None) -> dict:
    """Build test_data matching the UI form's _collectData() output exactly.

    The report dict uses the same structure as the template (flat row lists),
    so tables are merged generically by matching the first readonly column.
    """
    from report_skeleton import report_list_key
    template  = _TEMPLATE
    test_data: dict = {}

    eq_vc = ""
    if eq is not None and getattr(eq, "voltage_class", None):
        eq_vc = eq.voltage_class.split("/")[0].strip()

    def _str(v) -> str:
        return "" if v is None else str(v)

    for section in template.get("sections", []):
        for field in section.get("fields", []):
            key   = field.get("key", "")
            ftype = field.get("type", "text")

            if ftype in ("calculated", "readonly"):
                continue

            if ftype == "table":
                columns      = field.get("columns", [])
                default_rows = field.get("default_rows", [])
                src_key      = report_list_key(key)
                source_rows  = r.get(src_key) or []

                # Excel extractor returns oil_test as a flat dict — convert to row list
                if isinstance(source_rows, dict) and src_key == "oil_test":
                    _flat = source_rows
                    _remarks = _flat.get("remarks") or {}
                    _key_map = [
                        ("Acidity",             "acidity"),
                        ("Resistivity at 90C",  "resistivity"),
                        ("Tan Delta at 90C",    "tan_delta"),
                        ("BDV Top (T)",         "bdv_top"),
                        ("BDV Bottom (B)",      "bdv_bottom"),
                        ("Interfacial Tension", "interfacial_tension"),
                        ("Flash Point",         "flash_point"),
                        ("Water Content",       "water_content"),
                    ]
                    source_rows = [
                        {
                            "test_name":     tname,
                            "measured_value": _flat.get(fkey),
                            "remarks":        _remarks.get(fkey, ""),
                        }
                        for tname, fkey in _key_map
                    ]

                # first readonly column is the identity key (test_name / gas)
                mk = next((c["key"] for c in columns if c.get("type") == "readonly"), "")
                rows = []
                for dr in default_rows:
                    row = {c["key"]: "" for c in columns if c.get("key") and c.get("type") != "calculated"}
                    for k, v in dr.items():
                        if k in row:
                            row[k] = v or ""
                    # mark calculated columns null
                    for col in columns:
                        if col.get("type") == "calculated":
                            row[col["key"]] = None
                    # merge matching source row
                    if mk:
                        match_val = dr.get(mk, "")
                        for src in source_rows:
                            if src.get(mk) == match_val:
                                for col in columns:
                                    ck = col.get("key", "")
                                    if col.get("type") in ("calculated", "readonly") or not ck:
                                        continue
                                    if src.get(ck) is not None:
                                        row[ck] = _str(src[ck])
                                break
                    rows.append(row)
                test_data[key] = rows

            else:
                val = r.get(key)
                if val is not None:
                    test_data[key] = _str(val)
                elif field.get("default") is not None:
                    test_data[key] = field["default"]

    # transformer_voltage: first voltage level only (e.g. "220" from "220/66/11")
    test_data["transformer_voltage"] = eq_vc or r.get("transformer_voltage", "").split("/")[0].strip()

    # Context-bound readonly fields
    for field_key, binding_path in template.get("context_bindings", {}).items():
        test_data[field_key] = resolve_context_binding(binding_path, eq, r, field_key)
    if eq_vc:
        test_data["transformer_voltage"] = eq_vc

    # Recommendation wizard fields
    dga_remarks = r.get("dga_remarks", "") or "Seeded from historical KPTCL report."
    test_data.update({
        "recommendation_type": "Pass",
        "next_action":         "None",
        "overall_result":      "pass",
        "overall_remarks":     dga_remarks,
    })

    return test_data


def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# ── DB seed ───────────────────────────────────────────────────────────────────

def _find_org(session, reports: list[dict]):
    """Resolve org — KPTCL is the organisation that owns these substations."""
    for keyword in ("KPTCL", "Karnataka Power Transmission", "Karnataka"):
        org = session.query(Organization).filter(Organization.name.ilike(f"%{keyword}%")).first()
        if org:
            return org
    return None


def seed_reports(session, reports: list[dict], dry_run: bool = False):
    org = _find_org(session, reports)
    if not org:
        # Last resort: list orgs so user can identify correct one
        orgs = session.query(Organization).limit(10).all()
        print("[ERROR] Organisation not found. Available orgs:")
        for o in orgs:
            print(f"        {o.id}  {o.name}")
        sys.exit(1)
    print(f"[OK] Org: {org.name}")

    system_user = (
        session.query(User).filter(User.email.ilike("%admin%")).first()
        or session.query(User).first()
    )
    if not system_user:
        print("[ERROR] No users found.")
        sys.exit(1)
    print(f"[OK] Originator: {system_user.email}")

    oil_type = session.query(CategoryDetails).filter(CategoryDetails.name == "Transformer Oil Test").first()
    if not oil_type:
        print("[ERROR] 'Transformer Oil Test' CategoryDetails not found. Run seed.py first.")
        sys.exit(1)

    # Department cache — sub_station name → OrgDepartment
    _dept_cache: dict[str, OrgDepartment | None] = {}

    def _resolve_dept(sub_station: str) -> OrgDepartment | None:
        """Match sub_station string to the substation-level OrgDepartment (leaf node)."""
        key = (sub_station or "").strip().lower()
        if key in _dept_cache:
            return _dept_cache[key]
        dept = None
        if key:
            # The seeded substation names are like "220kV BIAL Begur" — match on key words
            # Try exact name first, then partial
            dept = (
                session.query(OrgDepartment)
                .filter(OrgDepartment.organization_id == org.id)
                .filter(OrgDepartment.name.ilike(f"%{key[:40]}%"))
                .first()
            )
            if not dept:
                # Try individual significant words (skip short/common ones)
                for word in key.split():
                    if len(word) > 3:
                        dept = (
                            session.query(OrgDepartment)
                            .filter(OrgDepartment.organization_id == org.id)
                            .filter(OrgDepartment.name.ilike(f"%{word}%"))
                            .first()
                        )
                        if dept:
                            break
        _dept_cache[key] = dept
        if dept:
            print(f"  [DEPT] '{sub_station}' → {dept.name}")
        else:
            print(f"  [WARN] '{sub_station}' — no matching department, department_id will be null.")
        return dept

    created_requests = 0
    created_results  = 0

    for r in reports:
        serial    = r.get("serial_number", "").strip()
        sample_no = r.get("sample_no", "").strip()
        raw_date  = r.get("test_date") or ""
        tested_at = _parse_date(raw_date) or datetime.now(timezone.utc)
        if not _parse_date(raw_date):
            print(f"  [WARN] Could not parse test_date '{raw_date}' for sample {sample_no} — using today")

        eq = session.query(Equipment).filter(Equipment.factory_serial_number == serial).first()
        if not eq:
            print(f"  [SKIP] Equipment {serial} not found in DB.")
            continue

        # Prefer the equipment's own department; fall back to OCR sub_station text
        dept = eq.department or _resolve_dept(r.get("sub_station", ""))

        # One request per report — transformer_oil_test template includes DGA section
        req_number = f"TR-HIST-{tested_at.strftime('%Y%m%d')}-{sample_no}-OIL"

        existing = (
            session.query(TestingRequest)
            .filter(TestingRequest.request_number == req_number)
            .first()
        )
        if existing:
            print(f"  [SKIP] {req_number} already seeded.")
            continue

        print(f"  {'[DRY]' if dry_run else '[SEED]'} {req_number} — {serial} {tested_at.date()}")
        if dry_run:
            continue

        from services.testing_request_service import TestingRequestService
        from services.testing_service import TestingService
        from services.recommendation_service import RecommendationService

        tr_svc  = TestingRequestService(session)
        tst_svc = TestingService(session)
        rec_svc = RecommendationService(session)

        tr = tr_svc.create_request(
            data={
                "title":               f"Transformer Oil Test — {eq.factory_serial_number or eq.ueic} (Sample {sample_no})",
                "description":         f"Historical KPTCL R&D Centre report. Sample No: {sample_no}.",
                "equipment_id":        eq.id,
                "equipment_type_id":   eq.equipment_type_id,
                "test_type_id":        oil_type.id,
                "organization_id":     org.id,
                "department_id":       dept.id if dept else None,
                "assigned_tester_id":  system_user.id,
                "requested_date":      tested_at,
                "scheduled_start_date": tested_at,
                "notes":               f"Seeded from historical KPTCL report. Sample No: {sample_no}.",
            },
            originator_id=system_user.id,
        )
        # Override auto-generated number and backdate; set in_progress for downstream services.
        tr.request_number = req_number
        tr.completed_at   = tested_at
        tr.status         = TestingRequestStatus.in_progress
        session.flush()

        result_data = _oil_test_data(r, eq)
        remarks = result_data.get("overall_remarks") or "Seeded from historical KPTCL report."
        try:
            tst_svc.create_structured_result(
                request_id=tr.id,
                template_key="transformer_oil_test",
                test_data=result_data,
                overall_result="pass",
                remarks=remarks,
                tester_id=system_user.id,
            )
        except InvalidRequestError:
            # create_structured_result commits before calling refresh() — the
            # TestResult is persisted. The analytics engine can leave the session
            # in a state where refresh() fails; reset and continue.
            session.expire_all()

        # Backdate tested_at on the test result to the historical test date
        session.execute(
            text("UPDATE public.test_results SET tested_at = :d WHERE testing_request_id = :rid"),
            {"d": tested_at, "rid": tr.id},
        )
        session.flush()

        rec = rec_svc.create_recommendation(
            testing_request_id=tr.id,
            recommendation_type="pass",
            summary="Pass — no further action (seeded from historical KPTCL report).",
            submitted_by=system_user.id,
            next_action="none",
        )
        # Services committed; finalize: close the request and mark recommendation approved.
        tr.status         = TestingRequestStatus.closed
        rec.approval_status = "approved"
        rec.approved_by   = system_user.id
        rec.approved_at   = tested_at
        session.commit()
        created_requests += 1
        created_results  += 1

    if not dry_run:
        print(f"\nDone. {created_requests} TestingRequests + {created_results} TestResults seeded.")


# ── Entry point ───────────────────────────────────────────────────────────────

def collect_pdfs(inputs: list[str]) -> list[Path]:
    """Expand a mix of file paths and folder paths into a flat list of PDFs."""
    pdfs = []
    for inp in inputs:
        p = Path(inp)
        if p.is_dir():
            found = sorted(p.glob("**/*.pdf"))
            print(f"  Folder {p}: {len(found)} PDF(s) found.")
            pdfs.extend(found)
        elif p.is_file() and p.suffix.lower() == ".pdf":
            pdfs.append(p)
        else:
            print(f"  [WARN] Skipping {inp} — not a PDF or folder.")
    return pdfs


REPORT_TEMPLATE = {
    "sub_station": "",
    "sample_no": "",
    "test_date": "YYYY-MM-DD",
    "capacity_mva": "",
    "voltage_class": "",
    "make": "",
    "serial_number": "",
    "date_of_commission": "YYYY-MM-DD",
    "standard": "IS 10593:2017",
    "oil_test": {
        "acidity": None,
        "resistivity": None,
        "tan_delta": None,
        "bdv_top": None,
        "bdv_bottom": None,
        "interfacial_tension": None,
        "flash_point": None,
        "water_content": None,
        "remarks": {
            "acidity": "",
            "resistivity": "",
            "tan_delta": "",
            "bdv_top": "",
            "bdv_bottom": "",
            "interfacial_tension": "",
            "flash_point": "",
            "water_content": ""
        }
    },
    "dga": {
        "methane": None,
        "ethane": None,
        "ethylene": None,
        "acetylene": None,
        "hydrogen": None,
        "co2": None,
        "co": None,
        "tgc": None,
        "sample_location": "Bottom",
        "overall": "Normal — Gases within limits",
        "remarks": ""
    }
}


def _save_json(reports: list[dict], output: str | None, source_hint: str, output_dir: Path | None = None) -> Path:
    """Save reports to a JSON file. Auto-names if output is None."""
    if output:
        out_path = Path(output)
    else:
        stem = Path(source_hint).stem if source_hint else "extracted"
        ts = datetime.now().strftime("%d%m%Y_%H%M%S")
        folder = output_dir if output_dir else Path("data")
        out_path = folder / f"{stem}_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, default=str, ensure_ascii=False)
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Seed oil test results from KPTCL reports.",
        epilog=(
            "Modes:\n"
            "  --from-pdf   Extract via EasyOCR → always saves JSON → seeds DB (default)\n"
            "  --from-json  Seed directly from a previously saved JSON file\n"
            "  --template   Print a blank JSON template to stdout\n\n"
            "Examples:\n"
            "  # Extract from folder, save JSON, AND seed DB\n"
            "  python seed_oil_tests_from_pdf.py --from-pdf C:\\path\\to\\pdfs\\\n\n"
            "  # Extract only — save JSON for review, no DB writes\n"
            "  python seed_oil_tests_from_pdf.py --from-pdf C:\\path\\to\\pdfs\\ --emit-only\n\n"
            "  # Seed from previously saved / edited JSON\n"
            "  python seed_oil_tests_from_pdf.py --from-json data/report.json\n"
            "  python seed_oil_tests_from_pdf.py --from-json data/report.json --dry-run\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-json", metavar="FILE",   help="Path to JSON file with report data")
    group.add_argument("--from-pdf",  metavar="INPUT",  nargs="+", help="PDF file(s) or folder(s)")
    group.add_argument("--template",  action="store_true", help="Print blank JSON template and exit")
    parser.add_argument("--output",    metavar="FILE",  help="Save extracted JSON to this path (--from-pdf only)")
    parser.add_argument("--emit-only", action="store_true", help="Extract and save JSON only, skip DB seed (--from-pdf only)")
    parser.add_argument("--dry-run",   action="store_true", help="Parse/load without writing to DB")
    parser.add_argument("--workers",   type=int, default=1, metavar="N",
                        help="Parallel OCR workers (default 1). Use 2-4 to speed up large PDFs.")
    args = parser.parse_args()

    # ── Template mode ─────────────────────────────────────────────────────────
    if args.template:
        print(json.dumps([REPORT_TEMPLATE], indent=2))
        return

    # ── JSON mode ─────────────────────────────────────────────────────────────
    if args.from_json:
        json_path = Path(args.from_json)
        if not json_path.exists():
            print(f"[ERROR] Path not found: {json_path}")
            sys.exit(1)
        if json_path.is_dir():
            json_files = sorted(json_path.glob("*.json"))
            if not json_files:
                print(f"[ERROR] No .json files found in {json_path}")
                sys.exit(1)
            print(f"[OK] Found {len(json_files)} JSON file(s) in {json_path.name}/")
            all_reports = []
            for jf in json_files:
                with open(jf, encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    data = [data]
                print(f"     {jf.name}: {len(data)} report(s)")
                all_reports.extend(data)
        else:
            with open(json_path, encoding="utf-8") as f:
                all_reports = json.load(f)
            if not isinstance(all_reports, list):
                all_reports = [all_reports]
            print(f"[OK] Loaded {len(all_reports)} report(s) from {json_path.name}")
        print(f"     Total: {len(all_reports)} report(s)")

    # ── PDF mode ──────────────────────────────────────────────────────────────
    elif args.from_pdf:
        pdfs = collect_pdfs(args.from_pdf)
        if not pdfs:
            print("[ERROR] No PDF files found.")
            sys.exit(1)
        print(f"[1/3] {len(pdfs)} PDF file(s) to process.")

        print("\n[2/3] Extracting data with EasyOCR...")
        all_reports = []
        for pdf_path in pdfs:
            print(f"\n── {pdf_path.name} ──")
            images = pdf_to_pil_images(pdf_path)
            print(f"  {len(images)} page(s) found.")
            reports = extract_with_easyocr(images, workers=args.workers)
            all_reports.extend(reports)
        print(f"\n      Total: {len(all_reports)} report(s) extracted across {len(pdfs)} file(s).")

        if not all_reports:
            print("[DONE] Nothing extracted.")
            return

        # Always save JSON after extraction — into <pdf_source>/data/
        source_hint = args.from_pdf[0] if len(args.from_pdf) == 1 else "extracted"
        pdf_root = Path(args.from_pdf[0]) if Path(args.from_pdf[0]).is_dir() else Path(args.from_pdf[0]).parent
        out_path = _save_json(all_reports, args.output, source_hint, output_dir=pdf_root / "data")
        print(f"\n[SAVED] Extracted data written to: {out_path}")
        print(f"        Review/edit the file, then run:")
        print(f"        python seed_oil_tests_from_pdf.py --from-json \"{out_path}\"")

        if args.emit_only:
            print("\n[--emit-only] JSON saved. Skipping DB seed.")
            print(f"             To seed later: python seed_oil_tests_from_pdf.py --from-json \"{out_path}\"")
            return

    if not all_reports:
        print("[DONE] Nothing to seed.")
        return

    if args.dry_run:
        print("\n[DRY RUN] Report data:\n")
        print(json.dumps(all_reports, indent=2, default=str))
        return

    print("\nSeeding to database...")
    with _SessionLocal() as session:
        seed_reports(session, all_reports, dry_run=False)


if __name__ == "__main__":
    main()
