"""
KPTCL Capacitance & Tan Delta Test PDF / JSON → DB seed.

Usage:
    # Extract PDFs, save JSON AND seed DB (default)
    python seed_tandelta_from_pdf.py --from-pdf "Tan Delta 2 (1).pdf"
    python seed_tandelta_from_pdf.py --from-pdf /folder/

    # Extract PDFs, save JSON only — no DB writes
    python seed_tandelta_from_pdf.py --from-pdf /folder/ --emit-only

    # Seed from a previously saved / edited JSON
    python seed_tandelta_from_pdf.py --from-json data/tandelta.json
    python seed_tandelta_from_pdf.py --from-json data/tandelta.json --dry-run

    # Print a blank JSON template (fill and re-run with --from-json)
    python seed_tandelta_from_pdf.py --template > tandelta_template.json

Pipeline (--from-pdf):
    1. PDF pages → PIL images       (fitz / PyMuPDF)
    2. Images → raw text            (EasyOCR)
    3. Raw text → structured JSON   (regex parser, always saved to data/)
    4. JSON → DB records            (SQLAlchemy, status=closed) — skipped with --emit-only

Supports KPTCL R&D Centre Capacitance & Tan Delta test report layout.
Idempotent — skips reports already seeded (matched by request_number).
Template used: capacitance_tandelta_transformer
"""

import argparse
import io
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, report
from torch import full
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
    User,
)
from report_skeleton import empty_report, resolve_context_binding


# ── Template-derived report skeleton ──────────────────────────────────────────
# Loaded once at import time; empty_report() returns a fresh deep copy per run.

def _load_template() -> dict:
    from test_templates import TEST_TEMPLATES
    return TEST_TEMPLATES.get("capacitance_tandelta_transformer", {})

_TEMPLATE = _load_template()


# ── OCR helpers ────────────────────────────────────────────────────────────────

def _num(s) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace(",", "").replace("O", "0")
    try:
        v = re.sub(r"[^\d.\-]", "", s)
        return float(v) if v else None
    except ValueError:
        return None


def _itc_num(raw: str | None) -> float | None:
    """Parse an ITC factor string, normalising OCR artefacts (L→1, O→0)."""
    if not raw:
        return None
    # "L06" → "1.06": leading L followed by digits, missing decimal
    raw = raw.replace("O", "0")
    raw = re.sub(r"^L(\d{2})$", r"1.\1", raw)  # L06 → 1.06, L12 → 1.12
    raw = re.sub(r"^L(\d)$",    r"1.\1", raw)   # L6  → 1.6
    return _num(raw)


def _find_itc(block: str) -> float | None:
    """Find 'Factor X.XX' in a text block, handling OCR typos."""
    m = re.search(r"Factor\s+([0-9L\.]+)", block, re.I)
    return _itc_num(m.group(1)) if m else None


def _find(pattern: str, text: str, group: int = 1) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(group).strip() if m else None


def _parse_date_str(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%d-%b-%y", "%d-%b-%Y",
                "%d/%m/%y", "%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_bushing_details(block: str, details_list: list) -> None:
    """Parse bushing detail rows (Make / Sl.No. / Y.O.Mfg) from a block."""
    for row in details_list:
        detail = row["detail"]
        pat = re.sub(r"\s+", r"\\s*", re.escape(detail))
        m = re.search(pat + r"\s*[:\.]?\s*(.+?)(?:\n|$)", block, re.I)
        if not m:
            continue
        # Split on vertical-bar, slash, tab, or two+ spaces
        parts = re.split(r"\s*[|/]\s*|\t+|\s{2,}", m.group(1).strip())
        if len(parts) >= 1:
            row["r_phase"] = parts[0].strip()
        if len(parts) >= 2:
            row["y_phase"] = parts[1].strip()
        if len(parts) >= 3:
            row["b_phase"] = parts[2].strip()


def _parse_bushing_test_rows(block: str, rows_list: list) -> None:
    """Parse bushing test rows (R/Y/B Phase) from a block.

    With paragraph=False, numbers may be on separate lines after the label.
    OCR may preserve the apostrophe in "R' Phase" — make it optional.

    The block may begin with a "Details" (nameplate) section that also has
    phase labels ("220 kV 'R' Phase"). We skip past the ITC table header to
    start searching only in the test-results portion.
    """
    # Skip past the last ITC/Correction header (table header precedes data rows)
    itc_m = re.search(r"ITC|Correction\s*Factor|% DF", block, re.I)
    search_start = itc_m.start() if itc_m else 0

    _PHASE_STOP = re.compile(r"(?:[RYB])'?\s*Phase", re.I)

    for row in rows_list:
        phase_letter = row["bushing"].replace("'", "")[0]   # R, Y, or B
        bushing_pat = rf"{phase_letter}'?\s*Phase"
        m_start = re.search(bushing_pat, block[search_start:], re.I)
        if not m_start:
            continue
        abs_start = search_start + m_start.end()
        window_end = abs_start + 250
        # Stop at the next phase label to avoid stealing next row's numbers
        stop = _PHASE_STOP.search(block, abs_start + 2)
        if stop and stop.start() < window_end:
            window_end = stop.start()
        window = block[abs_start:window_end]

        nums = [_num(n) for n in re.findall(r"\d+(?:\.\d+)?", window)]
        nums = [n for n in nums if n is not None]
        if len(nums) >= 4:
            row["voltage_kv"]       = nums[0]
            row["capacitance_pf"]   = nums[1]
            row["df_measured"]      = nums[2]
            row["df_corrected_20c"] = nums[3]
        elif len(nums) >= 2:
            row["df_measured"]      = nums[-2]
            row["df_corrected_20c"] = nums[-1]
        elif len(nums) == 1:
            row["df_corrected_20c"] = nums[0]


# ── OCR parser ─────────────────────────────────────────────────────────────────

def parse_ocr_text(text: str) -> dict | None:
    """Parse raw OCR text from one KPTCL Tan Delta / Capacitance test report page."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    full  = "\n".join(lines)

    # Must look like a tan delta report
    if not re.search(
        r"(tan.?delta|dissipation.?factor|capacitance.*test|bushing.*test|winding.*test|idax)",
        full, re.I
    ):
        return None

    report = empty_report(_TEMPLATE)

    # ── Equipment / Header ─────────────────────────────────────────────────────
    report["sub_station"] = (
        _find(r"sub[- ]?station\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or _find(r"\bR/S\s+([A-Za-z][A-Za-z\s]{2,30?})(?:\s+in\b|\n|$)", full)
        or ""
    )

    # Date separators: / - .  (KPTCL uses DD.MM.YYYY in table headers)
    _date_pat    = r"([\d]{1,2}[/\-\.][\d]{1,2}[/\-\.][\d]{2,4})"
    # Consistent-separator strict form — backreference ensures no mixed sep like "10-11/2871"
    _date_strict = r"(\d{1,2}([-./])\d{1,2}\2\d{4})"

    def _find_date(pattern, text):
        """Like _find but only returns the match if _parse_date_str succeeds."""
        s = _find(pattern, text)
        return _parse_date_str(s) if s else None

    report["test_date"] = (
        _find_date(r"date\s*of\s*test(?:ing)?\s*[:\.]?\s*" + _date_pat, full)
        or _find_date(r"(?:^|\n)\s*date\s*[:\.]?\s*" + _date_pat, full)
        or _find_date(r"\bdt[:\.]?\s*" + _date_pat, full)
        # "conducted on DD-MM-YYYY" pattern (e.g. "test conducted ... on 10-08-2012")
        or _find_date(r"conducted\s+(?:on\s+)?" + _date_pat, full)
        or _find_date(_date_strict, "\n".join(lines[:20]))  # strict match in header lines
        or _find_date(_date_strict, full)                    # last resort: anywhere in doc
    ) or ""
    if not report["test_date"]:
        print("  [DEBUG] date not found. First 20 OCR lines:")
        for i, l in enumerate(lines[:20]):
            print(f"    {i:02d}: {l}")

    serial = _find(r"serial\s*(?:number|no\.?)\s*[:\.]?\s*([A-Za-z]{2,3}[-\s]?\d{3,}[/\-]\d+)", full)
    if not serial:
        serial = _find(r"\b((?:HT|KT)-?\d{3,}[/\-]\d+)\b", full)
    if not serial:
        # Manufacturer serial: "Sl. No. 13068-005" or "S1. No.\n13068-005"
        serial = _find(r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]?\s*(\d{4,}[-/]\d+)", full)
    if serial:
        serial = re.sub(r"^(HT|KT)(\d)", r"\1-\2", serial)
    report["serial_number"] = serial or ""

    report["make"] = (
        _find(r"make\s*[:\.]?\s*([A-Za-z][\w\s\-&]{1,30}?)(?:\n|$)", full)
        or _find(r"\b(emco|bhel|abb|siemens|crompton|areva|alstom|cpri)\b", full)
        or ""
    )

    # capacity: require meaningful number (≥1 MVA) to avoid picking up "0" from stray text
    _cap_raw = _find(r"capacity\s*[:\.]?\s*(\d+(?:\.\d+)?)\s*mva", full) \
               or _find(r"(\d{2,}(?:\.\d+)?)\s*mva", full)
    report["capacity_mva"] = _cap_raw if (_cap_raw and float(_cap_raw) >= 1) else ""

    report["voltage_ratio"] = _find(r"(\d+\s*/\s*\d+(?:\s*/\s*\d+)?)\s*kv", full) or ""

    # vector group: valid formats start with Y/D/Z and contain digits (e.g. YNyn0d11, Dyn11)
    # OCR often reads '0' as 'O' — replace capital O in vector group with 0
    _vg = _find(r"vector\s*group\s*[:\.]?\s*([A-Za-z0-9]{3,})", full)
    if _vg and re.search(r"\d", _vg):
        _vg = re.sub(r"O", "0", _vg)   # O (letter) → 0 (digit) — never valid in vector group
        report["vector_group"] = _vg
    else:
        report["vector_group"] = ""

    doc_str = _find(r"date\s*of\s*comm(?:ission)?\s*[:\.]?\s*" + _date_pat, full)
    report["date_of_commission"] = _parse_date_str(doc_str)

    # ── Test Conditions ────────────────────────────────────────────────────────
    # EasyOCR paragraph mode often merges test-condition fields into one line.
    # Strategy: try label-based search on full text first; then fall back to
    # parsing the merged weather_condition blob for embedded fields.

    report["test_voltage_kv"] = _num(
        _find(r"(?:test|applied)\s*voltage\s*[:\.]?\s*(\d+(?:\.\d+)?)", full)
        or _find(r"test\s*voltage\s*[:\.]?\s*(\d+(?:\.\d+)?)\s*kv", full)
    )
    report["frequency_hz"] = _num(_find(r"freq(?:uency)?\s*[:\.]?\s*(\d+(?:\.\d+)?)", full)) or 50

    # Ambient temp: handle both "°C" and "*C" (common OCR substitution)
    report["ambient_temp_c"] = _num(
        _find(r"ambient\s*temp(?:erature)?\s*[:\.]?\s*(\d+(?:\.\d+)?)\s*[*°]?[Cc]", full)
        or _find(r"ambient\s*temp(?:erature)?\s*[:\.]?\s*(\d+(?:\.\d+)?)", full)
    )
    # Oil temp: handle "Oil Temp_" (OCR underscore for colon/period)
    report["oil_temp_c"] = _num(
        _find(r"oil\s*temp(?:erature)?\s*[:\._]?\s*(\d+(?:\.\d+)?)\s*[*°]?[Cc]", full)
        or _find(r"oil\s*temp(?:erature)?\s*[:\._]?\s*(\d+(?:\.\d+)?)", full)
    )

    # Weather: stop before known sibling keywords so we don't capture the whole line
    _wc = (
        _find(r"weather\s*(?:condition)?\s*[:\.]?\s*(.+?)(?=\s*(?:ambient|condition\s*of|kit|instrument|\n|$))", full)
        or _find(r"weather\s*(?:condition)?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or ""
    )
    report["weather_condition"] = _wc.strip(" ,")

    # Bushing condition: "Buehings" is a common OCR typo for "Bushings"
    report["bushing_condition"] = (
        _find(r"condition\s*of\s*bu(?:sh|eh)(?:ing)?[s]?\s*[:\.]?\s*(.+?)(?=\s*(?:kit|instrument|\n|,|$))", full)
        or _find(r"condition\s*of\s*bu(?:sh|eh)(?:ing)?[s]?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or ""
    )

    # Instrument / kit used: several OCR variants ("Kit used", "Klt used", "Instrument")
    report["instrument_make"] = (
        _find(r"k[il]t\s*used\s*[:\.]?\s*(.+?)(?:\n|,|$)", full)
        or _find(r"instrument(?:\s*(?:make|model|used))?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or _find(r"(megger\s*IDAX\s*\d+|IDAX[\s\-]\d+)", full)
        or ""
    )

    # If fields still empty, try parsing from the merged weather_condition blob
    wc_blob = report["weather_condition"]
    if wc_blob:
        if not report["ambient_temp_c"]:
            _at = re.search(r"ambient\s*temp(?:erature)?\s*[:\.]?\s*(\d+)", wc_blob, re.I)
            if _at:
                report["ambient_temp_c"] = _num(_at.group(1))
        if not report["bushing_condition"]:
            _bc = re.search(r"condition\s*of\s*bush\w*\s*[:\.]?\s*([^,\n]+)", wc_blob, re.I)
            if _bc:
                report["bushing_condition"] = _bc.group(1).strip()
        if not report["instrument_make"]:
            _im = re.search(r"k[il]t\s*used\s*[:\.]?\s*([^,\n]+)", wc_blob, re.I)
            if _im:
                report["instrument_make"] = _im.group(1).strip()

    # ── Winding Test ───────────────────────────────────────────────────────────
    # ITC factor: try explicit label first, then "Factor X.XX" near winding section
    # ── Winding Test ───────────────────────────────────────────────────────────────
    _winding_area = full[max(0, full.lower().find("winding")):full.lower().find("winding") + 3000] \
        if "winding" in full.lower() else full
    report["winding_itc_factor"] = (
        _num(_find(r"winding[^\n]*(?:ITC|itc|correction)\s*factor\s*[:\.]?\s*(\d+(?:\.\d+)?)", full))
        or _num(_find(r"(?:ITC|itc)\s*correction\s*factor\s*[:\.]?\s*(\d+(?:\.\d+)?)", full))
        or _find_itc(_winding_area)
    )

    winding_block_m = re.search(
        r"winding\s*test[\s\S]{0,5000}?"
        r"(?=(?:220|400|hv)\s*k\.?v\.?\s*bushing|66\s*k\.?v\.?\s*bushing|idax|$)",
        full, re.I
    )
    winding_block = winding_block_m.group(0) if winding_block_m else full

    # All known config labels across all PDF form variants (from Excel mapping)
    # Each tuple: (canonical_label, regex_pattern)
    _WINDING_CFG_PATTERNS = [
        ("HV-GND",        r"(?:CHG\b|HV\s*[-–&]\s*(?:GND|Grd|Grnd|Ground))"),
        ("HV-LV",         r"(?:CHL\b|HV\s*[-–&]\s*(?:LV|IV|MV))"),
        ("LV-GND",        r"(?:CLG\b|(?:LV|IV|MV)\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("LV-TV",         r"(?:CLT\b|(?:LV|IV|MV)\s*[-–]\s*TV)"),
        ("TV-GND",        r"(?:CTG\b|TV\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("HV-TV",         r"(?:CTH\b|(?:HV|TV)\s*[-–]\s*(?:TV|HV))"),
        ("(HV+LV)-GND",   r"\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*(?:GND|Grd|Grnd|Ground)"),
        ("(HV+LV)-TV",    r"\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*TV"),
        ("Winding-GND",   r"Winding\s*[-–]\s*(?:GND|Grd|Grnd|Ground)"),   # form 7 variant
    ]

    all_winding_pats = [pat for _, pat in _WINDING_CFG_PATTERNS]

    report["winding"] = []
    for label, cfg_pat in _WINDING_CFG_PATTERNS:
        m_win = re.search(cfg_pat + r"([\s\S]{0,300})", winding_block, re.I)
        if not m_win:
            continue
        window = m_win.group(1)
        # Stop at the next config label
        for other_pat in all_winding_pats:
            stop = re.search(other_pat, window, re.I)
            if stop:
                window = window[:stop.start()]
        nums = [_num(n) for n in re.findall(r"[\d]+(?:\.\d+)?", window)]
        nums = [n for n in nums if n is not None]
        row = {"test_configuration": label, "voltage_kv": None, "capacitance_nf": None,
            "df_measured": None, "df_corrected_20c": None}
        if len(nums) >= 4:
            row["voltage_kv"]       = nums[0]
            row["capacitance_nf"]   = nums[1]
            row["df_measured"]      = nums[2]
            row["df_corrected_20c"] = nums[3]
        elif len(nums) >= 2:
            row["df_measured"]      = nums[-2]
            row["df_corrected_20c"] = nums[-1]
        elif len(nums) == 1:
            row["df_corrected_20c"] = nums[0]
        report["winding"].append(row)

    report["winding_observations"] = (
        _find(r"observation[s]?\s*(?:\(winding\))?\s*[:\.]?\s*(.+?)(?:\n|$)", full) or ""
    )

    # ── 220kV Bushing Test ─────────────────────────────────────────────────────
    # OCR may give "220 kV Bushing", "220 LV Bughieg" — allow for common typos
    # ── Bushing detection: determine transformer type first ───────────────────────
    # 400kV presence → 400/220/33kV transformer; else → 220/66/11kV
    is_400kv = bool(re.search(r"400\s*k\.?v", full, re.I))

    # Bushing voltage labels used in regex and in report keys
    _HV_KV  = "400" if is_400kv else "220"
    _MV_KV  = "220" if is_400kv else "66"
    _LV_KV  = "33"  if is_400kv else "11"

    report["transformer_type"]       = "400/220/33 kV" if is_400kv else "220/66/11 kV"
    report["hv_bushing_voltage_class"] = f"{_HV_KV} kV"
    report["mv_bushing_voltage_class"] = f"{_MV_KV} kV"
    report["lv_bushing_voltage_class"] = f"{_LV_KV} kV"

    def _parse_bushing_section(block: str, voltage_label: str) -> tuple[float | None, list[dict]]:
        """Extract ITC factor and R/Y/B phase rows from a bushing block."""
        itc = _find_itc(block)
        rows = []
        for phase in ("R", "Y", "B"):
            phase_pat = rf"{phase}'?\s*Phase"
            m_start = re.search(phase_pat, block, re.I)
            if not m_start:
                continue
            abs_start = m_start.end()
            window_end = abs_start + 250
            stop = re.search(r"[RYB]'?\s*Phase", block[abs_start + 2:], re.I)
            if stop:
                window_end = min(window_end, abs_start + 2 + stop.start())
            window = block[abs_start:window_end]
            nums = [_num(n) for n in re.findall(r"\d+(?:\.\d+)?", window)]
            nums = [n for n in nums if n is not None]
            row = {"bushing": f"'{phase}' Phase", "voltage_kv": None,
                "capacitance_pf": None, "df_measured": None, "df_corrected_20c": None}
            if len(nums) >= 4:
                row["voltage_kv"]       = nums[0]
                row["capacitance_pf"]   = nums[1]
                row["df_measured"]      = nums[2]
                row["df_corrected_20c"] = nums[3]
            elif len(nums) >= 2:
                row["df_measured"]      = nums[-2]
                row["df_corrected_20c"] = nums[-1]
            elif len(nums) == 1:
                row["df_corrected_20c"] = nums[0]
            rows.append(row)
        return itc, rows

    # ── HV Bushing (220kV or 400kV) ───────────────────────────────────────────────
    hv_end_pat = rf"{_MV_KV}\s*k\.?v\.?\s*bu|idax|$"
    hv_m = re.search(
        rf"{_HV_KV}\s*k\.?[vV]\.?\s*bu(?:sh|gh)\w*[\s\S]{{0,2500}}?(?={hv_end_pat})",
        full, re.I
    )
    report["hv_bushing"] = []
    if hv_m:
        itc, rows = _parse_bushing_section(hv_m.group(0), _HV_KV)
        report["hv_bushing_itc_factor"] = itc
        report["hv_bushing"] = rows

    # ── MV Bushing (66kV or 220kV) ───────────────────────────────────────────────
    mv_end_pat = rf"{_LV_KV}\s*k\.?v\.?\s*bu|idax|overall|$" if _LV_KV != "11" \
        else r"idax|overall|assessment|$"
    mv_m = re.search(
        rf"{_MV_KV}\s*k\.?[vV]\.?\s*bu(?:sh|gh|sl)\w*[\s\S]{{0,2500}}?(?={mv_end_pat})",
        full, re.I
    )
    report["mv_bushing"] = []
    if mv_m:
        itc, rows = _parse_bushing_section(mv_m.group(0), _MV_KV)
        report["mv_bushing_itc_factor"] = itc
        report["mv_bushing"] = rows

    # ── LV Bushing (11kV or 33kV) — only some PDFs have this ─────────────────────
    report["lv_bushing"] = []
    if _LV_KV != "11":   # 33kV bushing section present in 400/220/33kV PDFs
        lv_m = re.search(
            rf"{_LV_KV}\s*k\.?[vV]\.?\s*bu(?:sh|gh|sl)\w*[\s\S]{{0,2500}}?(?=idax|overall|$)",
            full, re.I
        )
        if lv_m:
            itc, rows = _parse_bushing_section(lv_m.group(0), _LV_KV)
            report["lv_bushing_itc_factor"] = itc
            report["lv_bushing"] = rows

    # ── IDAX ───────────────────────────────────────────────────────────────────────
    report["idax_testing_kit"] = (
        _find(r"testing\s*kit\s*(?:used)?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or _find(r"(megger\s*IDAX\s*\d+|IDAX\s*\d+)", full)
        or ""
    )

    _MOISTURE_CATS = ["As new", "Dry", "Moderately Wet", "Wet", "Very Wet"]
    _OIL_CATS      = ["As new", "Acceptable", "Poor", "Bad"]

    # All IDAX config variants from Excel mapping (forms 1-5 + bushing rows)
    _IDAX_CFG_PATTERNS = [
        ("HV-GND",   r"(?:CHG\b|HV\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("HV-LV",    r"(?:CHL\b|HV\s*[-–]\s*(?:LV|IV|MV))"),
        ("LV-GND",   r"(?:CLG\b|(?:LV|IV|MV)\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("LV-TV",    r"(?:CLT\b|(?:LV|IV|MV)\s*[-–]\s*TV)"),
        ("TV-GND",   r"(?:CTG\b|TV\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("HV-TV",    r"(?:CTH\b|(?:TV|HV)\s*[-–]\s*(?:HV|TV))"),
        # Extra rows seen in some forms (from Excel mapping)
        ("(HV+LV)-GND", r"\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*(?:GND|Grd|Grnd|Ground)"),
        ("(HV+LV)-TV",  r"\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*TV"),
    ]

    # Bushing IDAX rows: "66kV R phase bushing" style (form 5 in Excel)
    _BUSHING_IDAX_PAT = re.compile(
        r"(\d+)\s*kv\s*([RYB])(?:'?\s*phase)?\s*bushing", re.I
    )

    idax_m = re.search(r"IDAX[\s\S]{0,3000}?(?=overall|assessment|recommendation|$)", full, re.I)
    report["idax"] = []

    if idax_m:
        idax_block = idax_m.group(0)
        all_idax_pats = [pat for _, pat in _IDAX_CFG_PATTERNS]

        def _extract_idax_row(label: str, window: str) -> dict:
            row = {
                "test_configuration": label,
                "moisture_percent": None,
                "tr_analysis_moisture": None,
                "oil_conductivity_psm": None,
                "tr_analysis_oil": None,
            }
            moisture_m = re.search(r"(\d+(?:\.\d+)?)\s*%", window)
            if moisture_m:
                row["moisture_percent"] = _num(moisture_m.group(1))
            decimals = [_num(n) for n in re.findall(r"\b\d+\.\d+\b", window)]
            decimals = [n for n in decimals if n is not None]
            if len(decimals) >= 2:
                row["moisture_percent"]     = decimals[0]
                row["oil_conductivity_psm"] = decimals[-1]
            elif len(decimals) == 1:
                row["oil_conductivity_psm"] = decimals[0]
            for cat in _MOISTURE_CATS:
                if cat.lower() in window.lower():
                    row["tr_analysis_moisture"] = cat
                    break
            for cat in _OIL_CATS:
                if cat.lower() in window.lower():
                    row["tr_analysis_oil"] = cat
                    break
            return row

        # Standard winding configuration rows
        for label, cfg_pat in _IDAX_CFG_PATTERNS:
            win_m = re.search(cfg_pat + r"([\s\S]{0,300})", idax_block, re.I)
            if not win_m:
                continue
            window = win_m.group(1)
            for other_pat in all_idax_pats:
                stop_m = re.search(other_pat, window, re.I)
                if stop_m:
                    window = window[:stop_m.start()]
            report["idax"].append(_extract_idax_row(label, window))

        # Bushing IDAX rows (e.g. "66kV R phase bushing" — form 5 in Excel)
        for bm in _BUSHING_IDAX_PAT.finditer(idax_block):
            b_label = f"{bm.group(1)}kV {bm.group(2).upper()} Phase Bushing"
            abs_end = bm.end()
            window  = idax_block[abs_end: abs_end + 300]
            # Stop at next bushing label or config label
            stop_b = _BUSHING_IDAX_PAT.search(window)
            if stop_b:
                window = window[:stop_b.start()]
            report["idax"].append(_extract_idax_row(b_label, window))

    report["idax_observation"] = (
        _find(r"idax.*?observation[s]?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or _find(r"(?<!bushing\s)observation[s]?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or ""
    )

    # ── Overall ────────────────────────────────────────────────────────────────
    overall = _find(r"overall\s*result\s*[:\.]?\s*(PASS|FAIL|CONDITIONAL)", full)
    if overall:
        report["overall_result"] = overall.upper()
    report["recommendation"] = _find(r"recommendation\s*[:\.]?\s*(.+?)(?:\n|$)", full) or ""

    # Skip if no usable identifier
    if not report.get("serial_number"):
        print("  [SKIP] No serial number found in this page.")
        return None

    return report


# ── Raw OCR debug helper ───────────────────────────────────────────────────────

_raw_ocr_dir: Path | None = None  # set by extract_with_easyocr before first use

def _save_raw_ocr(text: str, page_idx: int) -> None:
    base = _raw_ocr_dir or Path("data")
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%d%m%Y_%H%M%S")
    out = base / f"raw_ocr_p{page_idx + 1}_{ts}.txt"
    out.write_text(text, encoding="utf-8")
    print(f"  [RAW OCR] saved -> {out}")


# ── PDF helpers ────────────────────────────────────────────────────────────────

def pdf_to_pil_images(pdf_path: Path) -> list:
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
    import sys, io as _io, warnings
    warnings.filterwarnings("ignore")
    page_idx, img_bytes = args

    import easyocr
    import numpy as np

    buf = _io.StringIO()
    sys.stdout = buf
    try:
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        img = Image.open(io.BytesIO(img_bytes))
        result = reader.readtext(np.array(img), detail=0, paragraph=False)
        text = "\n".join(result)
        parsed = parse_ocr_text(text)
    finally:
        sys.stdout = sys.__stdout__
    logs = buf.getvalue().strip()
    return page_idx, parsed, logs


def _has_serial(text: str) -> bool:
    """True if the text contains any recognisable transformer serial number."""
    # KPTCL asset format:  HT-1234/56, KT-001/2
    if re.search(r"\b(?:HT|KT)\s*[-]?\s*\d{3,}[/\-]\d+", text, re.I):
        return True
    # Manufacturer format: 13068-005, 12345/006 (4+ digits, dash/slash, 2+ digits)
    if re.search(r"\bS[Il1l]\.?\s*[Nn]o\.?\s*[:\.]?\s*\d{4,}[-/]\d+", text, re.I):
        return True
    return False


def _is_primary_page(text: str) -> bool:
    """True if page has a transformer serial number AND winding/tan-delta test."""
    has_content = bool(re.search(r"winding\s*test|tan[- ]?delta|dissipation\s*factor", text, re.I))
    return _has_serial(text) and has_content


def _is_secondary_page(text: str) -> bool:
    """True if page has bushing/IDAX test data but no transformer serial."""
    has_bushing = bool(re.search(r"bushing\s*test|(?:220|66)\s*kv.*bushing|idax\s*test", text, re.I))
    return has_bushing and not _has_serial(text)


def _group_pages(page_texts: list[str]) -> list[str]:
    """Return a list of combined text blobs — one per transformer report.

    Primary page (serial + winding) is merged with immediately following
    secondary pages (bushing/IDAX, no serial) so parse_ocr_text sees the
    full document section for a single transformer.
    """
    groups: list[str] = []
    i = 0
    while i < len(page_texts):
        text = page_texts[i]
        if _is_primary_page(text):
            combined = text
            j = i + 1
            while j < len(page_texts):
                if _is_primary_page(page_texts[j]):
                    break  # next transformer starts
                if _is_secondary_page(page_texts[j]):
                    combined += "\n\n" + page_texts[j]
                j += 1
            groups.append(combined)
            i = j
        else:
            i += 1
    return groups


def extract_with_easyocr(images: list, workers: int = 1, debug_dir: Path | None = None) -> list[dict]:
    import numpy as np
    global _raw_ocr_dir
    _raw_ocr_dir = debug_dir or Path("data")

    if workers <= 1:
        import warnings, easyocr
        warnings.filterwarnings("ignore")
        print("  Loading EasyOCR model (first run downloads ~200MB)...", flush=True)
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
        page_texts: list[str] = []
        for i, img in enumerate(images):
            print(f"  Page {i + 1}/{len(images)}...", end=" ", flush=True)
            result = reader.readtext(np.array(img), detail=0, paragraph=False)
            text = "\n".join(result)
            _save_raw_ocr(text, i)
            page_texts.append(text)
            print("done")
    else:
        page_args = []
        for i, img in enumerate(images):
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            page_args.append((i, buf.getvalue()))

        raw_texts: dict[int, str] = {}
        print(f"  Using {workers} parallel worker(s)...", flush=True)
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_ocr_page_worker, arg): arg[0] for arg in page_args}
            for future in as_completed(futures):
                page_idx, _parsed, _logs = future.result()
                # We only need raw text here — re-run raw extraction is not
                # available in worker; fall back to single-threaded for grouping.
                raw_texts[page_idx] = ""
        page_texts = [raw_texts.get(i, "") for i in range(len(images))]

    # Group primary + secondary pages, then parse each group
    groups = _group_pages(page_texts)
    print(f"  Page grouping: {len(page_texts)} pages -> {len(groups)} transformer group(s).")

    reports: list[dict] = []
    for g_idx, combined in enumerate(groups):
        print(f"  Parsing group {g_idx + 1}/{len(groups)}...", end=" ", flush=True)
        parsed = parse_ocr_text(combined)
        if parsed:
            print(f"OK — serial={parsed.get('serial_number')}  date={parsed.get('test_date')}")
            reports.append(parsed)
        else:
            print("no report data found, skipped.")

    return reports


# ── Template-driven test_data builder ─────────────────────────────────────────

def _tandelta_test_data(r: dict, eq=None) -> dict:
    from test_templates import TEST_TEMPLATES
    template = TEST_TEMPLATES.get("capacitance_tandelta_transformer", {})
    test_data: dict = {}

    def _str(v) -> str:
        return "" if v is None else str(v)

    # Table field key → report dict key
    # e.g. "winding_test_results" → "winding", "hv_bushing_test_results" → "hv_bushing"
    def _report_list_key(field_key: str) -> str:
        for suffix in ("_test_results", "_results"):
            if field_key.endswith(suffix):
                return field_key[: -len(suffix)]
        return field_key

    for section in template.get("sections", []):
        for field in section.get("fields", []):
            key   = field.get("key", "")
            ftype = field.get("type", "text")

            if ftype == "table":
                columns      = field.get("columns", [])
                r_list_key   = _report_list_key(key)
                source_rows  = r.get(r_list_key, [])
                rows         = []

                if source_rows:
                    # ── Dynamic: use whatever rows the extractor actually found ──
                    for src in source_rows:
                        row = {}
                        for col in columns:
                            ck    = col.get("key", "")
                            ctype = col.get("type", "text")
                            if ctype == "calculated":
                                row[ck] = None          # computed server-side
                            elif ck in src and src[ck] is not None:
                                row[ck] = _str(src[ck])
                            else:
                                row[ck] = ""
                        rows.append(row)
                else:
                    # ── Fallback: empty default_rows skeleton (no data available) ──
                    for dr in field.get("default_rows", []):
                        row = {c.get("key", ""): "" for c in columns if c.get("key")}
                        for k, v in dr.items():
                            if k in row:
                                row[k] = v or ""
                        for col in columns:
                            if col.get("type") == "calculated":
                                row[col["key"]] = None
                        rows.append(row)

                test_data[key] = rows

            elif ftype in ("calculated", "readonly"):
                pass

            else:
                val = r.get(key)
                if val is not None:
                    test_data[key] = _str(val)
                elif field.get("default") is not None:
                    test_data[key] = field["default"]

    # Context bindings (sub_station, make, serial_number, etc.)
    for field_key, binding_path in template.get("context_bindings", {}).items():
        test_data[field_key] = resolve_context_binding(binding_path, eq, r, field_key)

    # Pass through transformer type and bushing voltage class selections
    for passthrough_key in (
        "transformer_type",
        "hv_bushing_voltage_class",
        "mv_bushing_voltage_class",
        "lv_bushing_voltage_class",
    ):
        if passthrough_key in r:
            test_data[passthrough_key] = r[passthrough_key]

    return test_data

# ── DB seed ────────────────────────────────────────────────────────────────────

def _parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%b-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _find_org(session):
    for keyword in ("KPTCL", "Karnataka Power Transmission", "Karnataka"):
        org = session.query(Organization).filter(Organization.name.ilike(f"%{keyword}%")).first()
        if org:
            return org
    return None


def seed_reports(session, reports: list[dict], dry_run: bool = False):
    org = _find_org(session)
    if not org:
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

    # Look up the Tan Delta / Capacitance test type
    td_type = (
        session.query(CategoryDetails).filter(CategoryDetails.name.ilike("%tan delta%")).first()
        or session.query(CategoryDetails).filter(CategoryDetails.name.ilike("%capacitance%")).first()
        or session.query(CategoryDetails).filter(CategoryDetails.name.ilike("%insulation%")).first()
    )
    if not td_type:
        cats = session.query(CategoryDetails).limit(15).all()
        print("[ERROR] No matching test type found. Available CategoryDetails:")
        for c in cats:
            print(f"        {c.id}  {c.name}")
        sys.exit(1)
    print(f"[OK] Test type: {td_type.name}")

    _dept_cache: dict[str, OrgDepartment | None] = {}

    def _resolve_dept(sub_station: str) -> OrgDepartment | None:
        key = (sub_station or "").strip().lower()
        if key in _dept_cache:
            return _dept_cache[key]
        dept = None
        if key:
            dept = (
                session.query(OrgDepartment)
                .filter(OrgDepartment.organization_id == org.id)
                .filter(OrgDepartment.name.ilike(f"%{key[:40]}%"))
                .first()
            )
            if not dept:
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
            print(f"  [WARN] '{sub_station}' — no matching department, will be null.")
        return dept

    created_requests = 0
    created_results  = 0

    for r in reports:
        serial   = r.get("serial_number", "").strip()
        raw_date = r.get("test_date") or ""
        tested_at = _parse_date(raw_date) or datetime.now(timezone.utc)
        if not _parse_date(raw_date):
            print(f"  [WARN] Could not parse test_date '{raw_date}' for serial {serial} — using today")

        eq = session.query(Equipment).filter(Equipment.factory_serial_number == serial).first()
        if not eq:
            print(f"  [SKIP] Equipment '{serial}' not found in DB.")
            continue

        # Prefer the equipment's own department; fall back to OCR sub_station text
        dept = eq.department or _resolve_dept(r.get("sub_station", ""))

        req_number = f"TR-HIST-{tested_at.strftime('%Y%m%d')}-{serial}-TDELTA"

        existing = (
            session.query(TestingRequest)
            .filter(TestingRequest.request_number == req_number)
            .first()
        )
        if existing:
            print(f"  [SKIP] {req_number} already seeded.")
            continue

        print(f"  {'[DRY]' if dry_run else '[SEED]'} {req_number} — {serial}  {tested_at.date()}")
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
                "title":                f"Capacitance & Tan Delta Test — {eq.factory_serial_number or eq.ueic}",
                "description":          "Historical KPTCL R&D Centre capacitance & tan delta report.",
                "equipment_id":         eq.id,
                "equipment_type_id":    eq.equipment_type_id,
                "test_type_id":         td_type.id,
                "organization_id":      org.id,
                "department_id":        dept.id if dept else None,
                "assigned_tester_id":   system_user.id,
                "requested_date":       tested_at,
                "scheduled_start_date": tested_at,
                "notes":                "Seeded from historical KPTCL tan delta report.",
            },
            originator_id=system_user.id,
        )
        tr.request_number = req_number
        tr.completed_at   = tested_at
        tr.status         = TestingRequestStatus.in_progress
        session.flush()

        result_data = _tandelta_test_data(r, eq)

        overall_raw = r.get("overall_result", "PASS")
        overall_str = (
            "pass"        if overall_raw.upper() == "PASS"
            else "fail"   if overall_raw.upper() == "FAIL"
            else "conditional"
        )
        remarks = r.get("recommendation", "") or "Seeded from historical KPTCL tan delta report."

        try:
            tst_svc.create_structured_result(
                request_id=tr.id,
                template_key="capacitance_tandelta_transformer",
                test_data=result_data,
                overall_result=overall_str,
                remarks=remarks,
                tester_id=system_user.id,
            )
        except InvalidRequestError:
            session.expire_all()

        # Backdate the test result to the historical test date
        session.execute(
            text("UPDATE public.test_results SET tested_at = :d WHERE testing_request_id = :rid"),
            {"d": tested_at, "rid": tr.id},
        )
        session.flush()

        rec = rec_svc.create_recommendation(
            testing_request_id=tr.id,
            recommendation_type=overall_str,
            summary=f"{overall_raw} — seeded from historical KPTCL tan delta report.",
            submitted_by=system_user.id,
            next_action="none",
        )
        tr.status           = TestingRequestStatus.closed
        rec.approval_status = "approved"
        rec.approved_by     = system_user.id
        rec.approved_at     = tested_at
        session.commit()
        created_requests += 1
        created_results  += 1

    if not dry_run:
        print(f"\nDone. {created_requests} TestingRequests + {created_results} TestResults seeded.")


# ── JSON helpers ───────────────────────────────────────────────────────────────

def collect_pdfs(inputs: list[str]) -> list[Path]:
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


def _save_json(
    reports: list[dict],
    output: str | None,
    source_hint: str,
    output_dir: Path | None = None,
) -> Path:
    if output:
        out_path = Path(output)
    else:
        stem = Path(source_hint).stem if source_hint else "tandelta"
        ts = datetime.now().strftime("%d%m%Y_%H%M%S")
        folder = output_dir if output_dir else Path("data")
        out_path = folder / f"{stem}_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, default=str, ensure_ascii=False)
    return out_path


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Seed Capacitance & Tan Delta test results from KPTCL PDF reports.",
        epilog=(
            "Modes:\n"
            "  --from-pdf   Extract via EasyOCR → saves JSON → seeds DB\n"
            "  --from-json  Seed directly from a previously saved JSON file\n"
            "  --template   Print a blank JSON template to stdout\n\n"
            "Examples:\n"
            '  python seed_tandelta_from_pdf.py --from-pdf "Tan Delta 2 (1).pdf"\n'
            "  python seed_tandelta_from_pdf.py --from-pdf /folder/ --emit-only\n"
            "  python seed_tandelta_from_pdf.py --from-json data/tandelta.json\n"
            "  python seed_tandelta_from_pdf.py --from-json data/tandelta.json --dry-run\n"
            "  python seed_tandelta_from_pdf.py --template > tandelta_template.json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-json", metavar="PATH", help="JSON file or folder with report data")
    group.add_argument("--from-pdf",  metavar="INPUT", nargs="+", help="PDF file(s) or folder(s)")
    group.add_argument("--template",  action="store_true", help="Print blank JSON template and exit")
    parser.add_argument("--output",    metavar="FILE", help="Save extracted JSON to this path")
    parser.add_argument("--emit-only", action="store_true", help="Extract JSON only, skip DB seed")
    parser.add_argument("--dry-run",   action="store_true", help="Parse/load without writing to DB")
    parser.add_argument("--workers",   type=int, default=1, metavar="N",
                        help="Parallel OCR workers (default 1, use 2-4 for large batches).")
    args = parser.parse_args()

    # ── Template mode ──────────────────────────────────────────────────────────
    if args.template:
        print(json.dumps([REPORT_TEMPLATE], indent=2))
        return

    # ── JSON mode ──────────────────────────────────────────────────────────────
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
            all_reports: list[dict] = []
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

    # ── PDF mode ───────────────────────────────────────────────────────────────
    elif args.from_pdf:
        pdfs = collect_pdfs(args.from_pdf)
        if not pdfs:
            print("[ERROR] No PDF files found.")
            sys.exit(1)
        print(f"[1/3] {len(pdfs)} PDF file(s) to process.")

        print("\n[2/3] Extracting data with EasyOCR...")
        all_reports = []
        for pdf_path in pdfs:
            print(f"\n-- {pdf_path.name} --")
            images = pdf_to_pil_images(pdf_path)
            print(f"  {len(images)} page(s) found.")
            reports = extract_with_easyocr(images, workers=args.workers, debug_dir=Path("data"))
            all_reports.extend(reports)
        print(f"\n      Total: {len(all_reports)} report(s) across {len(pdfs)} file(s).")

        if not all_reports:
            print("[DONE] Nothing extracted.")
            return

        source_hint = args.from_pdf[0] if len(args.from_pdf) == 1 else "tandelta"
        pdf_root    = (
            Path(args.from_pdf[0]) if Path(args.from_pdf[0]).is_dir()
            else Path(args.from_pdf[0]).parent
        )
        out_path = _save_json(all_reports, args.output, source_hint, output_dir=pdf_root / "data")
        print(f"\n[SAVED] Extracted data written to: {out_path}")
        print(f"        Review/edit the file, then run:")
        print(f'        python seed_tandelta_from_pdf.py --from-json "{out_path}"')

        if args.emit_only:
            print("\n[--emit-only] JSON saved. Skipping DB seed.")
            return

    if not all_reports:
        print("[DONE] Nothing to seed.")
        return

    print("\n[3/3] Seeding to database...")
    from database import VendorSessionLocal as _SessionLocal
    with _SessionLocal() as session:
        seed_reports(session, all_reports, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
