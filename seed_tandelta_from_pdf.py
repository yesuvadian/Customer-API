import argparse
import io
import json
import re
import sys
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
from report_skeleton import empty_report, resolve_context_binding


# ── Template loader ────────────────────────────────────────────────────────────

def _load_template() -> dict:
    from test_templates import TEST_TEMPLATES
    return TEST_TEMPLATES.get("capacitance_tandelta_transformer", {})

_TEMPLATE = _load_template()


# ── OCR number helpers ─────────────────────────────────────────────────────────

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
    if not raw:
        return None
    raw = raw.replace("O", "0")
    raw = re.sub(r"^L(\d{2})$", r"1.\1", raw)
    raw = re.sub(r"^L(\d)$",    r"1.\1", raw)
    return _num(raw)


def _find_itc(block: str) -> float | None:
    """Find ITC/Correction factor in any of the common KPTCL formats."""
    m = re.search(r"Factor\s+([0-9L\.]+)", block, re.I)
    if m:
        return _itc_num(m.group(1))
    m = re.search(r"(?:ITC|Correction)[^)]*\(([0-9\.]+)\)", block, re.I)
    if m:
        return _itc_num(m.group(1))
    m = re.search(r"(?:ITC|Correction)\s+(?:Factor\s+)?([0-9]\.[0-9]+)", block, re.I)
    if m:
        return _itc_num(m.group(1))
    return None


def _find(pattern: str, text: str, group: int = 1) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE)
    return m.group(group).strip() if m else None


def _normalize_serial(serial: str | None) -> str:
    """Normalize OCR-spaced transformer serials like 'HT-1690/ 12569'."""
    if not serial:
        return ""
    serial = re.sub(r"\s+", "", serial.upper())
    serial = re.sub(r"^(HT|KT)(\d)", r"\1-\2", serial)
    return serial


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


# ── NEW: previous-test-date helper ─────────────────────────────────────────────
# Picks up the date hidden in the 4th-column header of winding/bushing tables,
# e.g. "% DF after Temp- Correction on 19.05.2017 (Eltel)".
# Pass in the *specific section block* (winding_block, or the bushing block)
# rather than the whole document wherever possible, in case a report someday
# contains more than one previous-test date for different sections.

_PREV_DATE_PAT = re.compile(
    r"(\d{1,2}[.\-/]\d{1,2}[.\-/]\d{2,4})"
)

def _find_previous_test_date(block: str) -> str | None:
    """
    Find the previous-test date that appears near the '...Correction on ...'
    table-header phrase. OCR layout varies a lot between report formats —
    sometimes the date follows immediately, sometimes it's preceded by a
    stray unit token like '(nF)' / 'C (pF)' / 'Factor 0.8921' on intervening
    lines. Rather than trying to match the exact token sequence, we locate
    "...on" (from "Correction on") and then take the first date-shaped token
    within a generous window after it.
    """
    m = re.search(r"correct\w*\s*on\b", block, re.I)
    if not m:
        return None
    window = block[m.end(): m.end() + 120]
    dm = _PREV_DATE_PAT.search(window)
    if dm:
        return _parse_date_str(dm.group(1))
    return None


# ── Window cleaning helpers ────────────────────────────────────────────────────

def _extract_voltage_kv(window: str) -> float | None:
    """
    Extract test voltage from a small window (≤60 chars) right after the row label.

    Strategy (in priority order):
      1. "NNN kV" token  — covers "10 kV", "5kV", "2 kV" etc.
      2. OCR letter-misread fallback — EasyOCR sometimes reads a single
         voltage digit as a similarly-shaped letter when it's immediately
         followed by "kV" with no space, e.g. "5kV" -> "SkV", "0kV" -> "OkV".
         Without this, those rows lose their voltage value entirely even
         though every other column extracts fine.
      3. Bare integer on its own line — covers OCR that strips the "kV"
         suffix from the voltage column (e.g. just "10" on a line by itself).
         Only accepted in the 1–500 range to avoid mistaking capacitance for voltage.
    """
    # Primary: number followed by kV/KV
    m = re.search(r'(?<![\d.])\b(\d+(?:\.\d+)?)\s*[kK][vV]\b', window)
    if m:
        return float(m.group(1))

    # OCR letter-misread fallback: single letter immediately before kV/KV
    # where that letter is a common misread of a digit.
    m = re.search(r'\b([A-Za-z])\s*[kK][vV]\b', window)
    if m:
        _OCR_DIGIT_MAP = {
            "S": "5", "s": "5",
            "O": "0", "o": "0",
            "I": "1", "i": "1", "l": "1", "L": "1",
            "Z": "2", "z": "2",
            "G": "6", "g": "9",
            "B": "8",
        }
        digit = _OCR_DIGIT_MAP.get(m.group(1))
        if digit is not None:
            return float(digit)

    # Fallback: bare integer alone on its own line (OCR dropped the "kV" suffix)
    m = re.search(r'(?:^|\n)\s*(\d{1,3})\s*(?:\n|$)', window.strip())
    if m:
        val = float(m.group(1))
        if 1 <= val <= 500:
            return val
    return None


def _strip_voltage_from_window(window: str, volt: float | None) -> str:
    """
    Remove the bare voltage integer from the measurement window after it has
    been extracted.  Only needed when the voltage appeared as a bare integer
    (no kV suffix) — if it had a kV suffix, _strip_kv_noise() already removes it.
    """
    if volt is None:
        return window
    v_str = str(int(volt)) if volt == int(volt) else str(volt)
    # Remove a line that contains ONLY this integer (with optional whitespace)
    return re.sub(rf'(?:^|\n)\s*{re.escape(v_str)}\s*(?=\n|$)', '\n', window)


def _strip_kv_noise(window: str) -> str:
    """
    Remove kV-tagged tokens and parenthetical previous-test notes so only
    the numeric measurement values remain.

    NOTE: This intentionally does NOT strip the bare numeric value inside
    "(For 5 kV)" annotations — only the "kV" unit token itself is removed by
    the second regex below. The leading number (e.g. the previous-test %D.F
    value that sits right before "(For 5 kV)") is preserved so it can be
    captured as the 4th measurement number (df_previous_corrected).
    """
    window = re.sub(r'\(For\s+\d+(?:\.\d+)?\s*[kK][vV]\)', '', window, flags=re.I)
    window = re.sub(r'\b\d+(?:\.\d+)?\s*[kK][vV]\b', '', window, flags=re.I)
    return window

def _extract_measurement_nums_with_units(window: str) -> list[float]:
    """
    Variant of _extract_measurement_nums for reports where capacitance is
    written as e.g. '6.657nf' / '137.4pf' with NO space before the unit
    (so the plain \b...\b number regex can't match — digit->letter is not
    a word boundary), and where OCR sometimes renders the decimal point as
    a space ('351 6pf' -> '351.6pf'). nF values are converted to pF (×1000)
    to match the template's pF-only capacitance field.
    Only used by fallback parsers for unusual report layouts; does not
    replace or alter _extract_measurement_nums used elsewhere.
    """
    cleaned = window
    # Repair OCR-mangled decimal point before nf/pf units: "351 6pf" -> "351.6pf"
    cleaned = re.sub(r'(\d+)\s+(\d)\s*(nf|pf)\b', r'\1.\2\3', cleaned, flags=re.I)
    nums: list[float] = []
    # Capacitance values explicitly tagged with nf/pf
    for m in re.finditer(r'(\d+(?:\.\d+)?)\s*(nf|pf)\b', cleaned, re.I):
        val = float(m.group(1))
        if m.group(2).lower() == "nf":
            val *= 1000.0   # nF -> pF
        nums.append(val)
        cleaned = cleaned.replace(m.group(0), " ", 1)
    # Remaining plain decimals (DF measured / corrected values)
    cleaned = _strip_kv_noise(cleaned).replace(',', '')
    for nm in re.finditer(r'\b(\d+\.\d+)\b', cleaned):
        nums.append(float(nm.group(1)))
    return nums

def _extract_measurement_nums(window: str) -> list[float]:
    """
    Clean a measurement window and return only plausible measurement values.

    Steps:
      1. Strip kV-tagged tokens and previous-test parentheticals.
      2. Strip comma thousand-separators (e.g. "4,208.07" → "4208.07").
         Without this, "4,208.07" tokenises as [4, 208.07] and shifts every
         downstream column one position to the left.
      3. Collect all remaining numbers, rejecting 6+-digit plain integers
         (serial / asset numbers).

    Column order (voltage already extracted separately):
      [0] Capacitance C (pF or nF — stored as pF regardless of PDF unit label)
      [1] % D.F Measured
      [2] % D.F @ 20°C (ITC Corrected)
      [3] % D.F @ 20°C from the previous test report (df_previous_corrected)
    """
    cleaned = _strip_kv_noise(window)
    cleaned = cleaned.replace(',', '')          # FIX-1: strip thousand-separators
    nums: list[float] = []
    for nm in re.finditer(r'\b(\d+(?:\.\d+)?)\b', cleaned):
        raw = nm.group(1)
        val = float(raw)
        if val >= 100_000 and '.' not in raw:
            continue   # serial / asset number
        nums.append(val)
    return nums


def _assign_measurement_row(row: dict, nums: list[float]) -> None:
    """
    Assign measurement nums into a row dict (voltage already in row).

    FIX-5: a 4th number is now recognised as the previous-test corrected
    %D.F value (df_previous_corrected) instead of being silently dropped.
    """
    if len(nums) >= 4:
        row["capacitance_pf"]       = nums[0]
        row["df_measured"]          = nums[1]
        row["df_corrected_20c"]     = nums[2]
        row["df_previous_corrected"] = nums[3]
    elif len(nums) == 3:
        row["capacitance_pf"]   = nums[0]
        row["df_measured"]      = nums[1]
        row["df_corrected_20c"] = nums[2]
    elif len(nums) == 2:
        row["df_measured"]      = nums[0]
        row["df_corrected_20c"] = nums[1]
    elif len(nums) == 1:
        row["df_corrected_20c"] = nums[0]


# ── Quote-agnostic phase pattern helpers ──────────────────────────────────────
# Covers: 'R' Phase  "R" Phase  "R" Phase  R Phase  (R) Phase  R' Phase
# Unicode quotes: \u2018\u2019 (single), \u201c\u201d (double)

_Q  = r"""[\s'\u2018\u2019\u201c\u201d"(]*"""
_QC = r"""[\s'\u2018\u2019\u201c\u201d")]*"""

_PHASE_STOP         = re.compile(rf"""{_Q}[RYB]{_QC}\s*[Pp]hase""", re.I)
_PHASE_STOP_WIDENED = re.compile(rf"""{_Q}[RYB]?{_QC}\s*[Pp]hase""", re.I)


def _phase_pat(letter: str) -> str:
    return rf"""{_Q}{letter}{_QC}\s*[Pp]hase"""


def _phase_pat_fallback(letter: str) -> str:
    return rf"""(?:^|\n)[A-Za-z]?{letter}["'\u2018\u2019\u201c\u201d]+"""


_BARE_PHASE_WORD = re.compile(r"""(?:^|\n)\s*[Pp]hase\b""", re.I)


# ── Bushing section parser ─────────────────────────────────────────────────────

def _parse_bushing_details_section(block: str) -> list[dict]:
    """
    Extract Make / Sl. No. / Y.O. Mfg. nameplate rows from the "Bushing
    Details" nameplate sub-section that precedes the numeric test-results
    table in a bushing block (see _parse_bushing_section, which locates
    that same sub-section only to skip past it).

    Returns rows in the template's detail/r_phase/y_phase/b_phase shape
    (one row per detail type, one column per phase) -- matching
    bushing_{kv}kv_details in test_templates.py.

    Values are assigned to phase columns in left-to-right OCR reading
    order (each Make/Sl.No/Y.O.Mfg line lists R, Y, B phase values in that
    order), since -- unlike the numeric test-results table -- these rows
    don't carry per-phase position markers we can anchor on.
    """
    labels = [
        ("Make",      r"Make"),
        ("Sl. No.",   r"Sl\.?\s*No\.?"),
        ("Y.O. Mfg.", r"Y\.?\s*O\.?\s*Mfg\.?|Year\s*of\s*Mfg\.?"),
    ]
    rows: list[dict] = []
    for detail_label, pat in labels:
        row = {"detail": detail_label, "r_phase": "", "y_phase": "", "b_phase": ""}
        m = re.search(rf"(?:{pat})\s*[:\.]?\s*(.+?)(?:\n|$)", block, re.I)
        if m:
            raw = m.group(1).strip()
            tokens = [t.strip() for t in re.split(r"\s{2,}|\t|\|", raw) if t.strip()]
            if len(tokens) <= 1:
                tokens = raw.split()
            for col, val in zip(("r_phase", "y_phase", "b_phase"), tokens):
                row[col] = val
        rows.append(row)
    return rows


def _parse_bushing_section(block: str, voltage_label: str) -> tuple[float | None, list[dict], str | None]:
    """
    Extract ITC factor, R/Y/B phase test rows, and the previous-test date
    from one bushing block.

    Returns (itc_factor, rows, previous_test_date_iso_or_None).
    """
    itc = _find_itc(block)
    prev_date = _find_previous_test_date(block)   # NEW

    # Locate test-data table start (skip Details/nameplate sub-section)
    search_start = 0
    for hdr_m in re.finditer(
        r"ITC|Correction\s*Factor|%\s*D\.?F|Capacitance\s*\(pF\)|Test\s*Voltage",
        block, re.I
    ):
        search_start = hdr_m.end()

    details_end = 0
    for dm in re.finditer(
        r"(?:Y\.?O\.?\s*Mfg|Year\s*of\s*Mfg|Sl\.?\s*No\.?|Make)\s*[:\.]?[^\n]*\n",
        block, re.I
    ):
        details_end = dm.end()
    if details_end > search_start:
        after = block[details_end:]
        next_sep = re.search(r"\n\s*\n|ITC|%\s*D\.?F|Correction", after, re.I)
        if next_sep:
            search_start = max(search_start, details_end + next_sep.end())
        else:
            search_start = max(search_start, details_end)

    # Find phase label positions
    positions: dict[str, int] = {}
    for phase in ("R", "Y", "B"):
        m = re.search(_phase_pat(phase), block[search_start:], re.I)
        if not m:
            m = re.search(_phase_pat_fallback(phase), block[search_start:], re.I)
        if m:
            positions[phase] = search_start + m.end()

    # Positional fallback for missing Y phase
    if "Y" not in positions and "R" in positions and "B" in positions:
        lo   = positions["R"]
        hi_m = re.search(_phase_pat("B"), block[search_start:], re.I) \
               or re.search(_phase_pat_fallback("B"), block[search_start:], re.I)
        hi   = (search_start + hi_m.start()) if hi_m else None
        region = block[lo:hi] if hi else block[lo:lo + 250]
        bare = _BARE_PHASE_WORD.search(region)
        if bare:
            positions["Y"] = lo + bare.end()

    rows: list[dict] = []
    for phase in ("R", "Y", "B"):
        if phase not in positions:
            continue
        abs_start  = positions[phase]
        window_end = abs_start + 300

        stop = _PHASE_STOP_WIDENED.search(block, abs_start + 2)
        if stop and stop.start() < window_end:
            window_end = stop.start()

        small_win   = block[abs_start: abs_start + 60]
        voltage_val = _extract_voltage_kv(small_win)

        window = block[abs_start:window_end]
        window = _strip_voltage_from_window(window, voltage_val)   # FIX-2+3
        nums   = _extract_measurement_nums(window)
        if not nums:
     
            nums = _extract_measurement_nums_with_units(window)

        row: dict = {
            "bushing":               f"'{phase}' Phase",
            "voltage_kv":            voltage_val,
            "capacitance_pf":        None,
            "df_measured":           None,
            "df_corrected_20c":      None,
            "df_previous_corrected": None,   # NEW default
        }
        _assign_measurement_row(row, nums)
        rows.append(row)

    return itc, rows, prev_date


# ── Winding row extractor ──────────────────────────────────────────────────────

def _extract_winding_row(
    label: str,
    winding_block: str,
    match_end: int,
    all_stop_pats: list[str],
) -> dict:
    """
    Extract one winding row given the position after its config label matched.

    Voltage is extracted from a small local window (60 chars) with a fallback
    for bare integers (FIX-2).  The bare integer is then stripped from the
    wider measurement window before collecting nums (FIX-3).
    """
    small_win   = winding_block[match_end: match_end + 60]
    voltage_val = _extract_voltage_kv(small_win)

    window = winding_block[match_end: match_end + 300]
    for stop_pat in all_stop_pats:
        stop_m = re.search(stop_pat, window, re.I)
        if stop_m:
            window = window[:stop_m.start()]

    window = _strip_voltage_from_window(window, voltage_val)   # FIX-2+3
    nums   = _extract_measurement_nums(window)

    row: dict = {
        "test_configuration":    label,
        "voltage_kv":            voltage_val,
        "capacitance_pf":        None,
        "df_measured":           None,
        "df_corrected_20c":      None,
        "df_previous_corrected": None,   # NEW default
    }
    _assign_measurement_row(row, nums)
    return row

def _parse_single_phase_repeat_bushing(block: str) -> tuple[float | None, list[dict], str | None]:
    """
    Fallback for 'repeat test' bushing reports that test only ONE phase
    across multiple test-voltage steps (e.g. 0.25/2/5/10 kV), instead of the
    usual three-phase-at-one-voltage layout. Produces one row per voltage step.
    Only called when _parse_bushing_section finds zero rows, so it never
    affects the standard multi-phase report formats.
    """
    itc = _find_itc(block)
    prev_date = _find_previous_test_date(block)

    phase_letter = None
    for p in ("R", "Y", "B"):
        if re.search(_phase_pat(p), block, re.I):
            phase_letter = p
            break
    if not phase_letter:
        return itc, [], prev_date

    header_m = re.search(r"correct\w*\s*on\b", block, re.I)
    data_region = block[header_m.end():] if header_m else block

    raw_tokens = re.findall(r"\d+(?:\.\d+)?", data_region.replace(",", ""))
    nums = [float(t) for t in raw_tokens]

    rows: list[dict] = []
    i = 0
    while i <= len(nums) - 4:
        v, c, d1, d2 = nums[i:i + 4]
        # Plausibility filter: capacitance is large (pF), %D.F values are
        # small percentages, voltage is a realistic test-step value.
        if 100 <= c <= 2000 and 0 <= d1 < 10 and 0 <= d2 < 10 and 0 <= v <= 500:
            rows.append({
                "bushing":               f"'{phase_letter}' Phase",
                "voltage_kv":            v,
                "capacitance_pf":        c,
                "df_measured":           d1,
                "df_corrected_20c":      d2,
                "df_previous_corrected": None,
            })
            i += 4
        else:
            i += 1   # skip stray OCR token (e.g. Sl.No counters) and retry

    # A leftover trailing %D.F number (e.g. the previous-test value that only
    # appears once, for one row) is attached to the last extracted row.
    if rows and i < len(nums) and 0 <= nums[i] < 10:
        rows[-1]["df_previous_corrected"] = nums[i]

    return itc, rows, prev_date
# ── OCR parser ─────────────────────────────────────────────────────────────────
_COMBINED_BUSHING_ROW_PAT = re.compile(
    r"""(\d{5,7})\s*\(\s*(\d{2,3})\s*K\.?V\.?\s*[-–_~]*\s*
        [\"'\u2018\u2019\u201c\u201d]?\s*([RYB])\s*[\"'\u2018\u2019\u201c\u201d]?\s*\)?""",
    re.I | re.X,
)

def _parse_combined_bushing_table(full: str, target_kv: str) -> tuple[float | None, list[dict], str | None]:
    """
    Fallback for older single-table bushing layouts where ALL voltage
    classes' R/Y/B phase rows are listed together (identified per-row by
    '<bushing serial> (<kv>KV – "<phase>")') rather than in separate
    per-voltage blocks. Only called when the normal block_pat/
    _parse_bushing_section search finds no block for `target_kv`, so it
    never affects reports using the standard layout.
    """
    itc = _find_itc(full)
    prev_date = _find_previous_test_date(full)
    rows: list[dict] = []
    matches = list(_COMBINED_BUSHING_ROW_PAT.finditer(full))
    for i, m in enumerate(matches):
        kv, phase = m.group(2), m.group(3).upper()
        if kv != target_kv:
            continue
        win_end = matches[i + 1].start() if i + 1 < len(matches) else m.end() + 150
        window = full[m.end(): win_end]
        nums = _extract_measurement_nums_with_units(window)
        row: dict = {
            "bushing":               f"'{phase}' Phase",
            "voltage_kv":            None,
            "capacitance_pf":        None,
            "df_measured":           None,
            "df_corrected_20c":      None,
            "df_previous_corrected": None,
        }
        _assign_measurement_row(row, nums)
        rows.append(row)
    return itc, rows, prev_date

_EQUIPMENT_HEADER_PAT = re.compile(
    r"(?:[TIl]an.?Delta|Capacitance\s*&\s*[TIl]an.?Delta)"   # tolerates I/T OCR swap
    r"[\s\S]{0,40}?"
    r"(?:M\.?V\.?A|MVA|MA)\b"                                  # tolerates "MA" for "MVA"
    r"[\s\S]{0,80}?"
    r"Power\s*Trans\w*[\s\-–_]*\d*",                           # tolerates "Power_Transformer"
    re.I,
)

_EQUIPMENT_HEADER_PAT_LOOSE = re.compile(
    r"[TIl]an[\s_\-]{0,4}Delt[a4]"                    # tolerates "Tan _ Delta", "Delt4"
    r"[\s\S]{0,60}?"
    r"(?:M\.?V\.?A|MVA|MA)\b"
    r"[\s\S]{0,100}?"
    r"Power[\s_]*[TIl]r[ua]ns\w*[\s\-–_]*\d*",        # tolerates "Power_Transformcr", "Irunsformer"
    re.I,
)

def _split_combined_multi_equipment_report(full_text: str) -> list[str]:
    """
    Splits a combined OCR text that covers multiple transformers, each
    introduced by its own 'Tan-Delta Test on <X> MVA ... Power Transformer-N'
    section header. Only invoked as a fallback when normal parse fails.
    Returns the original list with one element if no split points found.
    """
    matches = list(_EQUIPMENT_HEADER_PAT.finditer(full_text))
    if len(matches) < 2:
        matches = list(_EQUIPMENT_HEADER_PAT_LOOSE.finditer(full_text))
    if len(matches) < 2:
        return [full_text]
    chunks = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        chunks.append(full_text[m.start(): end])
    return chunks

def _is_old_format_winding_page(text: str) -> bool:
    """
    Detects older-format winding-test reports (e.g. pre-2015 Tan-Delta
    reports) where OCR line-breaks separate the word "Winding" from
    "Test"/"Results", so the page never satisfies _is_primary_page's
    stricter winding-marker regex from FIX-15. Falls back to requiring
    "Winding" followed reasonably closely by "Capacitance" — a
    combination that only appears in a genuine winding results table
    header, never in a bushing or IDAX table. Only used as a last-resort
    fallback in _group_pages, so it can't affect any report that already
    groups correctly via the normal primary/secondary page path.
    """
    return bool(_has_serial(text)) and bool(
        re.search(r"winding[\s\S]{0,100}?capacitance", text, re.I)
    )

def _transformer_details_block(full: str) -> str:
    """
    Restrict serial-number (and similarly nameplate-only fields) extraction
    to the Transformer/Name-Plate Details section, BEFORE any "Bushing
    Details" heading. Bushing tables also contain their own "Sl. No" /
    "Sl.No." rows (the bushing's own nameplate serial, e.g. "1544038"),
    which is NOT the transformer's equipment serial and must never be
    picked up by the serial-number fallbacks. Without this scoping, a
    generic whole-document search could match whichever "Sl. No" occurs
    first in OCR text order — correct only by coincidence.
    Falls back to the full document if no "Bushing Details" heading is
    found (so reports without a bushing section still work normally).
    """
    bushing_m = re.search(r"bushing\s*det\w{2,6}", full, re.I)
    return full[: bushing_m.start()] if bushing_m else full

def parse_ocr_text(ocr_text: str) -> dict | None:
    """Parse raw OCR text from one KPTCL Tan Delta / Capacitance test report."""
    lines = [l.strip() for l in ocr_text.splitlines() if l.strip()]
    full  = "\n".join(lines)

    if not re.search(
        r"(tan.?delta|dissipation.?factor|capacitance.*test|bushing.*test|winding.*test|idax)",
        full, re.I
    ):
        return None

    report = empty_report(_TEMPLATE)
    report["winding"]       = []
    report["idax"]          = []
    report["bushing_400kv"] = []
    report["bushing_220kv"] = []
    report["bushing_66kv"]  = []
    report["bushing_33kv"]  = []
    report["bushing_11kv"]  = []

    # ── Equipment / Header ─────────────────────────────────────────────────
    report["sub_station"] = (
        _find(r"sub[- ]?station\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or _find(r"\bR/S\s+([A-Za-z][A-Za-z\s]{2,30?})(?:\s+in\b|\n|$)", full)
        or ""
    )

    _date_pat    = r"([\d]{1,2}[/\-\.][\d]{1,2}[/\-\.][\d]{2,4})"
    _date_strict = r"(\d{1,2}([-./])\d{1,2}\2\d{4})"

    def _find_date(pattern, text):
        s = _find(pattern, text)
        return _parse_date_str(s) if s else None

    report["test_date"] = (
        _find_date(r"date\s*of\s*test(?:ing)?\s*[:\.]?\s*" + _date_pat, full)
        or _find_date(r"(?:^|\n)\s*date\s*[:\.]?\s*" + _date_pat, full)
        or _find_date(r"\bdt[:\.]?\s*" + _date_pat, full)
        or _find_date(r"conducted\s+(?:on\s+)?" + _date_pat, full)
        or _find_date(_date_strict, "\n".join(lines[:20]))
        or _find_date(_date_strict, full)
    ) or ""
    if not report["test_date"]:
        print("  [DEBUG] date not found. First 20 OCR lines:")
        for i, l in enumerate(lines[:20]):
            print(f"    {i:02d}: {l}")
    
    _tx_block = _transformer_details_block(full)

    serial = _find(r"serial\s*(?:number|no\.?)\s*[:\.]?\s*([A-Za-z]{2,3}[-\s]?\d{3,}\s*[/\-]\s*\d+)", _tx_block)
    if not serial:
        serial = _find(r"\b((?:HT|KT)\s*-?\s*\d{3,}\s*[/\-]\s*\d+)\b", _tx_block)
    if not serial:
        serial = _find(r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*\s*(\d{4,}[-/]\d+)", _tx_block)
    if not serial:
        serial = _find(
            r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*(\d{4,}[-/]\d+)",
            _tx_block
        )
    if not serial:
        serial = _find(r"S[Il1l][,\.:]*\s*[Nn]o[,\._]?\s*[:\.]*[\s_\-]*\s*(\d{4,}[-/]\d+)", _tx_block)
    if not serial:
        serial = _find(r"\b(S-\d{6,})\b", _tx_block)
    if not serial:
        serial = _find(r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*([A-Za-z]\d{3,}\s*/\s*\d+)", _tx_block)
    if not serial:
        serial = _find(
            r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*(\d{1,3}-\d{3,6}\s*/\s*\d{1,3})",
            _tx_block
        )
    if not serial:
        serial = _find(r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*(\d{6,})\b", _tx_block)
    if not serial:
        serial = _find(
            r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*([A-Za-z]\s*-\s*\d{4,6})\b",
            _tx_block
        )
    if not serial:
        serial = _find(
            r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*"
            r"([A-Za-z]\s*-?\s*\d{3,}\s*/\s*[A-Za-z]?\s*-?\s*\d{3,})",
            _tx_block
        )
    if not serial:
        serial = _find(
            r"Voltage\s*Ratio\s*[\s\S]{0,5}?\d+\s*/\s*\d+(?:/\d+)?\s*k\.?V\.?\s*\n*\s*"
            r"([A-Za-z0-9][A-Za-z0-9\-/]{4,})\s*\n*\s*(?:M[Il]g|Y\.?O\.?)",
            _tx_block, group=1
        )
    if not serial:
        serial = _find(
            r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*(ITK\s*\d{5,})",
            _tx_block
        )
    if not serial:
        serial = _find(r"\b(S-\d{6,})\b", _tx_block)
    if not serial:
        serial = _find(r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*\s*(\d{4,}[-/]\d+)", _tx_block)


    report["serial_number"] = _normalize_serial(serial)

    report["make"] = (
        _find(r"make\s*[:\.]?\s*([A-Za-z][\w\s\-&]{1,30}?)(?:\n|$)", full)
        or _find(r"\b(emco|bhel|abb|siemens|crompton|areva|alstom|cpri)\b", full)
        or ""
    )

    _cap_raw = (
        _find(r"capacity\s*[:\.]?\s*(\d+(?:\.\d+)?)\s*mva", full)
        or _find(r"(\d{2,}(?:\.\d+)?)\s*mva", full)
        or _find(r"capacity\s*[:\.]?\s*([0-9oOlL]{2,})\s*mva", full)
    )
    if _cap_raw and not re.fullmatch(r"\d+(?:\.\d+)?", _cap_raw):
        _cap_raw = _cap_raw.replace("O","0").replace("o","0").replace("l","1").replace("L","1")
    report["capacity_mva"] = _cap_raw if (_cap_raw and float(_cap_raw) >= 1) else ""

    report["voltage_ratio"] = _find(r"(\d+\s*/\s*\d+(?:\s*/\s*\d+)?)\s*kv", full) or ""

    _vg = _find(r"vector\s*group\s*[:\.]?\s*([A-Za-z0-9]{3,})", full)
    if _vg and re.search(r"\d", _vg):
        report["vector_group"] = re.sub(r"O", "0", _vg)
    else:
        report["vector_group"] = ""

    doc_str = _find(r"date\s*of\s*comm(?:ission)?\s*[:\.]?\s*" + _date_pat, full)
    report["date_of_commission"] = _parse_date_str(doc_str)

    # ── Test Conditions ────────────────────────────────────────────────────
    report["test_voltage_kv"] = _num(
        _find(r"(?:test|applied)\s*voltage\s*[:\.]?\s*(\d+(?:\.\d+)?)", full)
        or _find(r"test\s*voltage\s*[:\.]?\s*(\d+(?:\.\d+)?)\s*kv", full)
    )
    report["frequency_hz"] = _num(
        _find(r"freq(?:uency)?\s*[:\.]?\s*(\d+(?:\.\d+)?)", full)
    ) or 50

    report["ambient_temp_c"] = _num(
        _find(r"ambient\s*temp(?:erature)?\s*[:\.]?\s*(\d+(?:\.\d+)?)\s*[*°]?[Cc]", full)
        or _find(r"ambient\s*temp(?:erature)?\s*[:\.]?\s*(\d+(?:\.\d+)?)", full)
    )
    report["oil_temp_c"] = _num(
        _find(r"oil\s*temp(?:erature)?\s*[:\._]?\s*(\d+(?:\.\d+)?)\s*[*°]?[Cc]", full)
        or _find(r"oil\s*temp(?:erature)?\s*[:\._]?\s*(\d+(?:\.\d+)?)", full)
    )

    _wc = (
        _find(r"weather\s*(?:condition)?\s*[:\.]?\s*(.+?)(?=\s*(?:ambient|condition\s*of|kit|instrument|\n|$))", full)
        or _find(r"weather\s*(?:condition)?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or ""
    )
    report["weather_condition"] = _wc.strip(" ,")

    report["bushing_condition"] = (
        _find(r"condition\s*of\s*bu(?:sh|eh)(?:ing)?[s]?\s*[:\.]?\s*(.+?)(?=\s*(?:kit|instrument|\n|,|$))", full)
        or _find(r"condition\s*of\s*bu(?:sh|eh)(?:ing)?[s]?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or ""
    )
    report["instrument_make"] = (
        _find(r"k[il]t\s*used\s*[:\.]?\s*(.+?)(?:\n|,|$)", full)
        or _find(r"instrument(?:\s*(?:make|model|used))?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or _find(r"(megger\s*IDAX\s*\d+|IDAX[\s\-]\d+)", full)
        or ""
    )

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

    # ── Winding Test ───────────────────────────────────────────────────────
    _winding_area = (
        full[max(0, full.lower().find("winding")):full.lower().find("winding") + 3000]
        if "winding" in full.lower() else full
    )
    report["winding_itc_factor"] = (
        _num(_find(r"winding[^\n]*(?:ITC|itc|correction)\s*factor\s*[:\.]?\s*(\d+(?:\.\d+)?)", full))
        or _num(_find(r"(?:ITC|itc)\s*correction\s*factor\s*[:\.]?\s*(\d+(?:\.\d+)?)", full))
        or _find_itc(_winding_area)
    )

    winding_block_m = re.search(
        r"winding\s*test[\s\S]{0,5000}?"
        r"(?=(?:400|220|hv)\s*k\.?v\.?\s*bushing|66\s*k\.?v\.?\s*bushing|idax|$)",
        full, re.I
    )
    winding_block = winding_block_m.group(0) if winding_block_m else full

    # NEW: previous-test date for the winding table.
    # Search winding_block first (most precise); fall back to the whole
    # document if the table header text fell just outside the captured block.
    report["winding_previous_test_date"] = (
        _find_previous_test_date(winding_block) or _find_previous_test_date(full)
    )

    _WINDING_CFG_PATTERNS = [
        ("HV-GND",      r"(?:CHG\b|HV\s*[-–&]\s*(?:GND|Grd|Grnd|Ground))"),
        ("HV-LV",       r"(?:CHL\b|HV\s*[-–&]\s*(?:LV|IV|MV))"),
        ("LV-GND",      r"(?:CLG\b|(?:LV|IV|MV)\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("LV-TV",       r"(?:CLT\b|(?:LV|IV|MV)\s*[-–]\s*TV)"),
        ("TV-GND",      r"(?:CTG\b|TV\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("HV-TV",       r"(?:CTH\b|(?:HV|TV)\s*[-–]\s*(?:TV|HV))"),
        ("(HV+LV)-GND", r"\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*(?:GND|Grd|Grnd|Ground)"),
        ("(HV+LV)-TV",  r"\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*TV"),
        ("Winding-GND", r"Winding\s*[-–]\s*(?:GND|Grd|Grnd|Ground)"),
    ]

    _WINDING_CFG_PATTERNS_IV = [
    ("HV-IV",  r"\bHV\s*[-–&]\s*IV\b"),
    ("IV-LV",  r"\bIV\s*[-–&]\s*LV\b|\bI\s*&\s*LV\b"),  # FIX-10: '&' added; bare "I & LV" covers OCR dropping the V in "IV & LV"
    ("IV-GND", r"\bIV\s*[-–]\s*(?:GND|Grd|Grnd|Ground)\b"),
    ]
    all_winding_pats = [pat for _, pat in _WINDING_CFG_PATTERNS]
    all_stop_pats    = all_winding_pats + [p for _, p in _WINDING_CFG_PATTERNS_IV]

    _claimed: list[tuple[int, int]] = []

    def _claimed_at(pos: int) -> bool:
        return any(s <= pos < e for s, e in _claimed)

    # Pass 1: IV-specific patterns
    for label, cfg_pat in _WINDING_CFG_PATTERNS_IV:
        m = re.search(cfg_pat, winding_block, re.I)
        if not m or _claimed_at(m.start()):
            continue
        _claimed.append((m.start(), m.end()))
        report["winding"].append(
            _extract_winding_row(label, winding_block, m.end(), all_stop_pats)
        )

    # Pass 2: standard patterns
    for label, cfg_pat in _WINDING_CFG_PATTERNS:
        chosen = None
        for m in re.finditer(cfg_pat, winding_block, re.I):
            if not _claimed_at(m.start()):
                chosen = m
                break
        if not chosen:
            continue
        report["winding"].append(
            _extract_winding_row(label, winding_block, chosen.end(), all_stop_pats)
        )

    report["winding_observations"] = (
        _find(r"observation[s]?\s*(?:\(winding\))?\s*[:\.]?\s*(.+?)(?:\n|$)", full) or ""
    )

    # ── Transformer type ───────────────────────────────────────────────────
    is_400kv = bool(re.search(r"400\s*k\.?v", full, re.I))
    report["transformer_type"] = "400/220/33 kV" if is_400kv else "220/66/11 kV"

    # ── Bushing sections ───────────────────────────────────────────────────
    _BUSHING_SECTIONS = [
        ("bushing_400kv", "400", ["220", "66", "33", "11"]),
        ("bushing_220kv", "220", ["66",  "33", "11"]),
        ("bushing_66kv",  "66",  ["33",  "11"]),
        ("bushing_33kv",  "33",  ["11"]),
        ("bushing_11kv",  "11",  []),
    ]
    _ITC_KEY = {
        "bushing_400kv": "bushing_400kv_itc_factor",
        "bushing_220kv": "bushing_220kv_itc_factor",
        "bushing_66kv":  "bushing_66kv_itc_factor",
        "bushing_33kv":  "bushing_33kv_itc_factor",
        "bushing_11kv":  "bushing_11kv_itc_factor",
    }
    # NEW: maps section key -> the report field that holds its previous-test date
    _PREV_DATE_KEY = {
        "bushing_400kv": "bushing_400kv_previous_test_date",
        "bushing_220kv": "bushing_220kv_previous_test_date",
        "bushing_66kv":  "bushing_66kv_previous_test_date",
        "bushing_33kv":  "bushing_33kv_previous_test_date",
        "bushing_11kv":  "bushing_11kv_previous_test_date",
    }
    # maps section key -> the report field that holds its nameplate details table
    _DETAILS_KEY = {
        "bushing_400kv": "bushing_400kv_details",
        "bushing_220kv": "bushing_220kv_details",
        "bushing_66kv":  "bushing_66kv_details",
        "bushing_33kv":  "bushing_33kv_details",
        "bushing_11kv":  "bushing_11kv_details",
    }

    kv_unit_pat = r"[kKlLeE*]\.?\s*[vV]"
    for rep_key, kv, end_kvs in _BUSHING_SECTIONS:
        end_alts  = [rf"{e}\s*{kv_unit_pat}\.?\s*bu" for e in end_kvs]
        end_alts += [r"idax", r"overall", r"assessment"]
        end_pat   = "(?=" + "|".join(end_alts) + r"|\Z)"
        block_pat = (
            rf"{kv}\s*{kv_unit_pat}\.?"
            # NEW: optional phase label between "kV" and "Bushing", e.g.
            # "220 kV 'Y' Phase\nBushing Details" (single-phase repeat-test reports)
            rf"(?:{_Q}[RYB]{_QC}\s*[Pp]hase)?\s*"
            rf"bu(?:sh|gh|sl)\w*"
            rf"[\s\S]{{0,2500}}?"
            + end_pat
        )
        bm = re.search(block_pat, full, re.I)
        if bm:
            itc, rows, prev_date = _parse_bushing_section(bm.group(0), kv)
            if not rows:
                # NEW: fallback for single-phase / multi-voltage-step format
                fb_itc, fb_rows, fb_prev_date = _parse_single_phase_repeat_bushing(bm.group(0))
                if fb_rows:
                    itc, rows, prev_date = (fb_itc or itc), fb_rows, (fb_prev_date or prev_date)
            report[_ITC_KEY[rep_key]]       = itc
            report[rep_key]                = rows
            report[_PREV_DATE_KEY[rep_key]] = prev_date
            report[_DETAILS_KEY[rep_key]]   = _parse_bushing_details_section(bm.group(0))
        else:
            itc, rows, prev_date = _parse_combined_bushing_table(full, kv)
            report[_ITC_KEY[rep_key]]       = itc
            report[rep_key]                = rows
            report[_PREV_DATE_KEY[rep_key]] = prev_date
            report[_DETAILS_KEY[rep_key]]   = []
            if rows:
                print(f"  [BUSHING] {kv}kV - {len(rows)} phase row(s) extracted")
            else:
                print(f"  [BUSHING] {kv}kV - section not found, skipped")

    # ── IDAX ───────────────────────────────────────────────────────────────
    report["idax_testing_kit"] = (
        _find(r"testing\s*kit\s*(?:used)?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or _find(r"(megger\s*IDAX\s*\d+|IDAX\s*\d+)", full)
        or ""
    )

    _MOISTURE_CATS = ["Moderately Wet", "Very Wet", "As new", "Dry", "Wet"]
    _OIL_CATS      = ["As new", "Acceptable", "Good", "Poor", "Bad"]

    _IDAX_CFG_PATTERNS = [
        ("HV-GND",      r"(?:CHG\b|HV\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("HV-LV",       r"(?:CHL\b|HV\s*[-–]\s*(?:LV|IV|MV))"),
        ("LV-GND",      r"(?:CLG\b|(?:LV|IV|MV)\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("LV-TV",       r"(?:CLT\b|(?:LV|IV|MV)\s*[-–]\s*TV)"),
        ("TV-GND",      r"(?:CTG\b|TV\s*[-–]\s*(?:GND|Grd|Grnd|Ground))"),
        ("HV-TV",       r"(?:CTH\b|(?:TV|HV)\s*[-–]\s*(?:HV|TV))"),
        ("(HV+LV)-GND", r"\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*(?:GND|Grd|Grnd|Ground)"),
        ("(HV+LV)-TV",  r"\(HV\s*\+\s*(?:LV|MV)\)\s*[-–]\s*TV"),
    ]
    all_idax_pats     = [pat for _, pat in _IDAX_CFG_PATTERNS]
    _BUSHING_IDAX_PAT = re.compile(r"(\d+)\s*kv\s*([RYB])(?:'?\s*phase)?\s*bushing", re.I)

    def _extract_idax_row(label: str, window: str) -> dict:
        row: dict = {
            "test_configuration":      label,
            "moisture_percent":        None,
            "moisture_percent_previous": None,   # NEW default (no source col in this PDF format)
            "tr_analysis_moisture":    None,
            "oil_conductivity_psm":    None,
            "tr_analysis_oil":         None,
        }
        moisture_m = re.search(r"(\d+(?:\.\d+)?)\s*%", window)
        if moisture_m:
            row["moisture_percent"] = _num(moisture_m.group(1))
        decimal_matches = list(re.finditer(r"\b\d+\.\d+\b", window))
        decimals = [_num(m.group(0)) for m in decimal_matches]
        decimals = [n for n in decimals if n is not None]
        if len(decimals) >= 2:
            row["moisture_percent"]     = decimals[0]
            row["oil_conductivity_psm"] = decimals[-1]
        elif len(decimals) == 1:
            row["oil_conductivity_psm"] = decimals[0]

        def _find_category(segment: str, categories: list[str]) -> str | None:
            for cat in categories:
                if re.search(rf"\b{re.escape(cat)}\b", segment, re.I):
                    return cat
            return None

        if len(decimal_matches) >= 2:
            moisture_segment = window[decimal_matches[0].end(): decimal_matches[-1].start()]
            oil_segment      = window[decimal_matches[-1].end():]
            row["tr_analysis_moisture"] = _find_category(moisture_segment, _MOISTURE_CATS)
            row["tr_analysis_oil"]      = _find_category(oil_segment, _OIL_CATS)
        else:
            row["tr_analysis_moisture"] = _find_category(window, _MOISTURE_CATS)
            row["tr_analysis_oil"]      = _find_category(window, _OIL_CATS)
        return row

    idax_block = ""
    idax_candidates = list(re.finditer(
        r"(?:IDAX\W*Test|INSULATION\s+\w*\s*TEST\s+REP|Testing\s+Kit\s+Used:\s*IDAX)",
        full,
        re.I,
    ))
    for cand in reversed(idax_candidates):
        window = full[cand.start(): cand.start() + 3500]
        if re.search(r"moisture", window, re.I) and re.search(r"oil\s+conductivity", window, re.I):
            end_m = re.search(r"(?=overall|assessment|recommendation|SFRA\s+Test|$)", window, re.I)
            idax_block = window[:end_m.start()] if end_m and end_m.start() > 0 else window
            break

    # NEW: previous-test date for IDAX, in case some report formats include it
    # (none observed in current samples, so this will resolve to None there).
    report["idax_previous_test_date"] = (
        _find_previous_test_date(idax_block) if idax_block else None
    )

    if idax_block:
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

        for bm in _BUSHING_IDAX_PAT.finditer(idax_block):
            b_label = f"{bm.group(1)}kV {bm.group(2).upper()} Phase Bushing"
            abs_end = bm.end()
            window  = idax_block[abs_end: abs_end + 300]
            stop_b  = _BUSHING_IDAX_PAT.search(window)
            if stop_b:
                window = window[:stop_b.start()]
            report["idax"].append(_extract_idax_row(b_label, window))

    report["idax_observation"] = (
        _find(r"idax.*?observation[s]?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or _find(r"(?<!bushing\s)observation[s]?\s*[:\.]?\s*(.+?)(?:\n|$)", full)
        or ""
    )

    # ── Overall ────────────────────────────────────────────────────────────
    overall = _find(r"overall\s*result\s*[:\.]?\s*(PASS|FAIL|CONDITIONAL)", full)
    if overall:
        report["overall_result"] = overall.upper()
    report["recommendation"] = (
        _find(r"recommendation\s*[:\.]?\s*(.+?)(?:\n|$)", full) or ""
    )

    if not report.get("serial_number"):
        print("  [INFO] No serial number found — report will be saved for manual linking.")

    return report


# ── Raw OCR debug helper ───────────────────────────────────────────────────────

_raw_ocr_dir: Path | None = None

def _save_raw_ocr(text: str, page_idx: int) -> None:
    base = _raw_ocr_dir or Path("data")
    base.mkdir(parents=True, exist_ok=True)
    ts  = datetime.now().strftime("%d%m%Y_%H%M%S")
    out = base / f"raw_ocr_p{page_idx + 1}_{ts}.txt"
    out.write_text(text, encoding="utf-8")
    print(f"  [RAW OCR] saved -> {out}")


# ── PDF helpers ────────────────────────────────────────────────────────────────

def pdf_to_pil_images(pdf_path: Path) -> list:
    doc    = fitz.open(str(pdf_path))
    images = []
    for page in doc:
        mat = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=mat)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    doc.close()
    return images


def _ocr_page_worker(args):
    import sys as _sys, io as _io, warnings
    warnings.filterwarnings("ignore")
    page_idx, img_bytes = args
    import easyocr, numpy as np
    buf = _io.StringIO()
    _sys.stdout = buf
    try:
        reader   = easyocr.Reader(["en"], gpu=False, verbose=False)
        img      = Image.open(io.BytesIO(img_bytes))
        result   = reader.readtext(np.array(img), detail=0, paragraph=False)
        ocr_text = "\n".join(result)
        parsed   = parse_ocr_text(ocr_text)
    finally:
        _sys.stdout = _sys.__stdout__
    return page_idx, ocr_text, parsed, buf.getvalue().strip()


def _has_serial(text: str) -> bool:
    if re.search(r"\b(?:HT|KT)\s*-?\s*\d{3,}\s*[/\-]\s*\d+", text, re.I):
        return True
    if re.search(r"\bS[Il1l][,\.:]*\s*[Nn]o[,\._]?\s*[:\.]*[\s_\-]*\s*\d{4,}\s*[-/]\s*\d+", text, re.I):
        return True
    if re.search(r"\bS[Il1l][,\.]?\s*[Nn]o[,\._]?\s*[:\.]*[\s_\-]*\s*\d{4,}\s*[-/]\s*\d+", text, re.I):
        return True
    if re.search(r"\bS[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*\s*\d{4,}\s*[-/]\s*\d+", text, re.I):
        return True
    if re.search(r"\bS-\d{6,}\b", text):
        return True
    if re.search(r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*(\d{4,}[-/]\d+)", text, re.I):
        return True
    if re.search(r"\bS[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*\d{6,}\b", text, re.I):
        return True
    if re.search(
        r"S[Il1l]\.?\s*[Nn]o\.?\s*[:\.]*[\s_\-]*\s*[A-Za-z]\s*-?\s*\d{4,}",
        text, re.I
    ):
        return True
    return False


def _is_primary_page(text: str) -> bool:
    return _has_serial(text) and bool(re.search(
        r"winding\s*test|winding\s*[-–]*\s*results|dissipation\s*factor",
        text, re.I
        ))


def _is_secondary_page(text: str) -> bool:
    return not _has_serial(text) and bool(re.search(
        r"bushing\s*test"
        r"|(?:400|220|66|33|11)\s*kv.*bushing"
        r"|idax\s*test"
        # FIX-20: OCR frequently drops characters from "IDAX", reading it
        # as "JAX", "AX", or "DAX". "Insulation Diagnostics" is the
        # section heading that reliably survives even degraded OCR.
        r"|[IJ]AX\s*Test\s*Results?"
        r"|insulation\s*diagnostics",
        text, re.I
    ))
def _is_bushing_repeat_test_page(text: str) -> bool:
    """
    Detects single-phase 'repeat test' bushing reports (voltage-stepped
    bushing test, no Winding Test section) that _is_primary_page/
    _is_secondary_page miss entirely — the former needs a winding section,
    the latter is excluded because the bushing's own nameplate serial
    ("S-XXXXXXX") trips _has_serial(). Only used as a last-resort fallback
    in _group_pages, so it never affects normal multi-section reports.
    """
    return bool(
        re.search(r"repeated\s+on", text, re.I)
        and re.search(r"bushing", text, re.I)
        and re.search(r"bushing\s*test\s*results|date\s*of\s*previous\s*test", text, re.I)
    )

def _group_pages(page_texts: list[str]) -> list[str]:
    """Merge primary page (serial + winding) with following secondary pages (bushing/IDAX)."""
    groups: list[str] = []
    i = 0
    while i < len(page_texts):
        if _is_primary_page(page_texts[i]):
            combined = page_texts[i]
            j = i + 1
            while j < len(page_texts):
                if _is_primary_page(page_texts[j]):
                    break
                if _is_secondary_page(page_texts[j]):
                    combined += "\n\n" + page_texts[j]
                j += 1
            groups.append(combined)
            i = j
        else:
            i += 1

    if not groups:
        # FIX-21: single-phase repeat-test bushing reports (no winding
        # section, and a bushing serial that trips _has_serial()) fall
        # through the loop above entirely. Only fires when nothing else
        # matched, so it can't affect any format that already groups fine.
        combined_all = "\n\n".join(page_texts)
        if _is_bushing_repeat_test_page(combined_all):
            groups.append(combined_all)
        elif any(_is_old_format_winding_page(t) for t in page_texts):
            # FIX-25: older-format report where the winding-table page's
            # "Winding" heading is OCR-line-split from "Test"/"Results",
            # so it never satisfies the normal _is_primary_page check.
            # Treat all pages of this document as one combined group,
            # since normal primary/secondary classification can't split
            # them reliably here.
            groups.append(combined_all)

    return groups


def extract_with_easyocr(images: list, workers: int = 1, debug_dir: Path | None = None) -> list[dict]:
    import numpy as np
    global _raw_ocr_dir
    _raw_ocr_dir = debug_dir or Path("data")

    if workers <= 1:
        import warnings, easyocr
        warnings.filterwarnings("ignore")
        print("  Loading EasyOCR model...", flush=True)
        reader     = easyocr.Reader(["en"], gpu=False, verbose=False)
        page_texts: list[str] = []
        for i, img in enumerate(images):
            print(f"  Page {i+1}/{len(images)}...", end=" ", flush=True)
            result   = reader.readtext(np.array(img), detail=0, paragraph=False)
            ocr_text = "\n".join(result)
            _save_raw_ocr(ocr_text, i)
            page_texts.append(ocr_text)
            print("done")
    else:
        page_args = []
        for i, img in enumerate(images):
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            page_args.append((i, buf.getvalue()))
        raw_texts: dict[int, str] = {}
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for fut in as_completed({ex.submit(_ocr_page_worker, a): a[0] for a in page_args}):
                idx, ocr_text, _, _ = fut.result()
                raw_texts[idx] = ocr_text
        page_texts = [raw_texts.get(i, "") for i in range(len(images))]

    full_ocr = "\n\n".join(page_texts)
    pre_split_chunks = _split_combined_multi_equipment_report(full_ocr)
    if len(pre_split_chunks) > 1:
        print(f"  {len(page_texts)} pages -> combined report, {len(pre_split_chunks)} equipment section(s) detected.")
        reports: list[dict] = []
        for sc_idx, chunk in enumerate(pre_split_chunks):
            print(f"  Parsing section {sc_idx+1}/{len(pre_split_chunks)}...", end=" ", flush=True)
            sub_parsed = parse_ocr_text(chunk)
            if sub_parsed:
                print(f"OK - serial={sub_parsed.get('serial_number')}  date={sub_parsed.get('test_date')}")
                reports.append(sub_parsed)
            else:
                print("skipped (no serial/date).")
        return reports

    # Normal single-transformer flow
    groups = _group_pages(page_texts)
    print(f"  {len(page_texts)} pages -> {len(groups)} transformer group(s).")

    reports: list[dict] = []
    for g_idx, combined in enumerate(groups):
        print(f"  Parsing group {g_idx+1}/{len(groups)}...", end=" ", flush=True)
        parsed = parse_ocr_text(combined)
        if parsed:
            print(f"OK - serial={parsed.get('serial_number')}  date={parsed.get('test_date')}")
            reports.append(parsed)
        else:
            print("skipped.")
    return reports


# ── Template-driven test_data builder ─────────────────────────────────────────

_TABLE_KEY_MAP: dict[str, str] = {
    "winding_test_results":       "winding",
    "idax_test_results":          "idax",
    "bushing_400kv_test_results": "bushing_400kv",
    "bushing_220kv_test_results": "bushing_220kv",
    "bushing_66kv_test_results":  "bushing_66kv",
    "bushing_33kv_test_results":  "bushing_33kv",
    "bushing_11kv_test_results":  "bushing_11kv",
}
_ITC_FIELD_MAP: dict[str, str] = {
    "bushing_400kv_itc_factor": "bushing_400kv_itc_factor",
    "bushing_220kv_itc_factor": "bushing_220kv_itc_factor",
    "bushing_66kv_itc_factor":  "bushing_66kv_itc_factor",
    "bushing_33kv_itc_factor":  "bushing_33kv_itc_factor",
    "bushing_11kv_itc_factor":  "bushing_11kv_itc_factor",
    "winding_itc_factor":       "winding_itc_factor",
    # NEW: previous-test-date fields map straight through (key == report_key),
    # listed here explicitly for clarity/documentation even though the
    # generic fallback (`_ITC_FIELD_MAP.get(key, key)`) would resolve them
    # the same way without this entry.
    "winding_previous_test_date":       "winding_previous_test_date",
    "bushing_400kv_previous_test_date": "bushing_400kv_previous_test_date",
    "bushing_220kv_previous_test_date": "bushing_220kv_previous_test_date",
    "bushing_66kv_previous_test_date":  "bushing_66kv_previous_test_date",
    "bushing_33kv_previous_test_date":  "bushing_33kv_previous_test_date",
    "bushing_11kv_previous_test_date":  "bushing_11kv_previous_test_date",
    "idax_previous_test_date":          "idax_previous_test_date",
}


def _backfill_itc_factor(rows: list[dict] | None) -> float | None:
    """When a report's ITC/correction factor wasn't stated in the source
    (PDF OCR text or Excel), recover it from the section's own rows: factor =
    avg(df_corrected_20c / df_measured) across rows where both are present.
    Mirrors the back-calculation used for the historical Excel imports and
    the Import Data review UI, so a seeded record doesn't persist a blank
    correction factor whenever it's mathematically recoverable from readings
    already on the row -- 2 decimals under 1.0, 3 decimals at/above (matches
    the precision convention seen across these reports' own stated factors).
    """
    ratios = []
    for row in rows or []:
        measured  = row.get("df_measured")
        corrected = row.get("df_corrected_20c")
        if measured in (None, 0) or corrected is None:
            continue
        try:
            ratios.append(float(corrected) / float(measured))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
    if not ratios:
        return None
    avg = sum(ratios) / len(ratios)
    return round(avg, 3 if avg >= 1 else 2)


def _tandelta_test_data(r: dict, eq=None) -> dict:
    """
    Build test_data matching capacitance_tandelta_transformer form output.

    FIX-4: For "calculated" columns (df_corrected_20c, condition), we now
    preserve any parsed value from the source row rather than unconditionally
    writing None.  The EvaluationService can still recompute if needed, but
    having the OCR-read ITC-corrected value avoids blank cells in the UI when
    the service hasn't run yet or the ITC factor wasn't parsed.

    FIX-5: df_previous_corrected (table column) and moisture_percent_previous
    (IDAX table column) are plain (non-calculated) columns, so they're
    already copied through by the generic `elif ck in src and src[ck] is not
    None:` branch below as long as the OCR parser populates them on the row
    dict — which it now does (see _assign_measurement_row / _extract_idax_row).

    FIX-6: *_previous_test_date fields are plain "date" type top-level fields
    (not table, not calculated), so they're picked up by the generic
    scalar-field branch at the bottom of the field loop, via _ITC_FIELD_MAP.
    """
    from test_templates import TEST_TEMPLATES, normalize_row_id
    template  = TEST_TEMPLATES.get("capacitance_tandelta_transformer", {})
    test_data: dict = {}

    def _str(v) -> str:
        return "" if v is None else str(v)

    def _report_list_key(field_key: str) -> str:
        if field_key in _TABLE_KEY_MAP:
            return _TABLE_KEY_MAP[field_key]
        for suffix in ("_test_results", "_results"):
            if field_key.endswith(suffix):
                return field_key[: -len(suffix)]
        return field_key

    for section in template.get("sections", []):
        for field in section.get("fields", []):
            key   = field.get("key", "")
            ftype = field.get("type", "text")

            if ftype == "table":
                columns     = field.get("columns", [])
                source_rows = r.get(_report_list_key(key), [])
                rows: list[dict] = []

                if source_rows:
                    for src in source_rows:
                        row: dict = {}
                        for col in columns:
                            ck    = col.get("key", "")
                            ctype = col.get("type", "text")
                            if ctype == "calculated":
                                # FIX-4: preserve parsed value if present; only
                                # fall back to None when the parser found nothing
                                parsed_val = src.get(ck)
                                row[ck] = _str(parsed_val) if parsed_val is not None else None
                            elif ck in src and src[ck] is not None:
                                val = _str(src[ck])
                                row[ck] = normalize_row_id(val) if ck == "test_configuration" else val
                            else:
                                row[ck] = ""
                        rows.append(row)
                else:
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
                report_key = _ITC_FIELD_MAP.get(key, key)
                val = r.get(report_key)
                if val is None and key.endswith("_itc_factor"):
                    val = _backfill_itc_factor(r.get(key[: -len("_itc_factor")]))
                if val is not None:
                    test_data[key] = _str(val)
                elif field.get("default") is not None:
                    test_data[key] = field["default"]

    for field_key, binding_path in template.get("context_bindings", {}).items():
        test_data[field_key] = resolve_context_binding(binding_path, eq, r, field_key)

    if "transformer_type" in r:
        test_data["transformer_type"] = r["transformer_type"]

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
    for kw in ("KPTCL", "Karnataka Power Transmission", "Karnataka"):
        org = session.query(Organization).filter(Organization.name.ilike(f"%{kw}%")).first()
        if org:
            return org
    return None


def seed_reports(session, reports: list[dict], dry_run: bool = False):
    org = _find_org(session)
    if not org:
        print("[ERROR] Organisation not found.")
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

    td_type = (
        session.query(CategoryDetails).filter(CategoryDetails.name.ilike("%tan delta%")).first()
        or session.query(CategoryDetails).filter(CategoryDetails.name.ilike("%capacitance%")).first()
        or session.query(CategoryDetails).filter(CategoryDetails.name.ilike("%insulation%")).first()
    )
    if not td_type:
        print("[ERROR] No matching test type found.")
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
        print(f"  [DEPT] '{sub_station}' -> {dept.name if dept else 'null'}")
        return dept

    created = 0
    for r in reports:
        serial    = r.get("serial_number", "").strip()
        raw_date  = r.get("test_date") or ""
        tested_at = _parse_date(raw_date) or datetime.now(timezone.utc)

        eq = None
        if serial:
            eq = session.query(Equipment).filter(Equipment.factory_serial_number == serial).first()

        if not eq:
            reason = "no serial extracted" if not serial else f"serial '{serial}' not matched"
            print(f"  [SKIP] {reason} — not seeded via CLI. "
                  f"Use the /data-import API flow to review and link this record.")
            continue

        dept       = eq.department or _resolve_dept(r.get("sub_station", ""))
        req_number = f"TR-HIST-{tested_at.strftime('%Y%m%d')}-{serial}-TDELTA"
        
        if session.query(TestingRequest).filter(
            TestingRequest.request_number == req_number
        ).first():
            print(f"  [SKIP] {req_number} already seeded.")
            continue

        print(f"  {'[DRY]' if dry_run else '[SEED]'} {req_number} - {serial} {tested_at.date()}")
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
                "title":                (
                    f"Capacitance & Tan Delta Test - "
                    f"{eq.factory_serial_number or eq.ueic}"
                ),
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

        overall_raw = r.get("overall_result", "PASS")
        overall_str = (
            "pass"        if overall_raw.upper() == "PASS"
            else "fail"   if overall_raw.upper() == "FAIL"
            else "conditional"
        )
        remarks = (
            r.get("recommendation", "")
            or "Seeded from historical KPTCL tan delta report."
        )

        try:
            tst_svc.create_structured_result(
                request_id=tr.id,
                template_key="capacitance_tandelta_transformer",
                test_data=_tandelta_test_data(r, eq),
                overall_result=overall_str,
                remarks=remarks,
                tester_id=system_user.id,
            )
        except InvalidRequestError:
            session.expire_all()

        session.execute(
            text(
                "UPDATE public.test_results "
                "SET tested_at = :d WHERE testing_request_id = :rid"
            ),
            {"d": tested_at, "rid": tr.id},
        )
        session.flush()

        # create_structured_result() already ran analytics once using
        # tested_at=now() (it always stamps current time; the raw UPDATE
        # above backdates it afterward without going through the ORM), so
        # TestAnalytics/ParameterAnalytics from that first pass are keyed to
        # the wrong date. Rerun with the corrected date so trend/history and
        # equipment-level health aggregation (both keyed off tested_at) are
        # right immediately rather than only after the next full recompute.
        session.expire_all()
        seeded_result = (
            session.query(TestResult)
            .filter(TestResult.testing_request_id == tr.id)
            .first()
        )
        if seeded_result:
            try:
                from services.analytics_engine import AnalyticsEngine
                AnalyticsEngine(session).run_for_test(seeded_result.id)
                session.commit()
            except Exception as _analytics_err:
                print(f"[WARN] Post-seed analytics re-run failed for {seeded_result.id}: {_analytics_err}")

        rec = rec_svc.create_recommendation(
            testing_request_id=tr.id,
            recommendation_type=overall_str,
            summary=f"{overall_raw} - seeded from historical KPTCL tan delta report.",
            submitted_by=system_user.id,
            next_action="none",
        )
        tr.status           = TestingRequestStatus.closed
        rec.approval_status = "approved"
        rec.approved_by     = system_user.id
        rec.approved_at     = tested_at
        session.commit()
        created += 1

    if not dry_run:
        print(f"\nDone. {created} record(s) seeded.")


# ── JSON / PDF collection helpers ──────────────────────────────────────────────

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
            print(f"  [WARN] Skipping {inp}")
    return pdfs


def _save_json(reports, output, source_hint, output_dir=None) -> Path:
    if output:
        out_path = Path(output)
    else:
        stem     = Path(source_hint).stem if source_hint else "tandelta"
        ts       = datetime.now().strftime("%d%m%Y_%H%M%S")
        folder   = output_dir if output_dir else Path("data")
        out_path = folder / f"{stem}_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(reports, f, indent=2, default=str, ensure_ascii=False)
    return out_path


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Seed Capacitance & Tan Delta test results.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--from-json", metavar="PATH")
    group.add_argument("--from-pdf",  metavar="INPUT", nargs="+")
    group.add_argument("--template",  action="store_true")
    parser.add_argument("--output",    metavar="FILE")
    parser.add_argument("--emit-only", action="store_true")
    parser.add_argument("--dry-run",   action="store_true")
    parser.add_argument("--workers",   type=int, default=1)
    args = parser.parse_args()

    if args.template:
        print(json.dumps([empty_report(_TEMPLATE)], indent=2, default=str, ensure_ascii=False))
        return

    all_reports: list[dict] = []

    if args.from_json:
        json_path = Path(args.from_json)
        if not json_path.exists():
            print(f"[ERROR] Not found: {json_path}")
            sys.exit(1)
        if json_path.is_dir():
            for jf in sorted(json_path.glob("*.json")):
                with open(jf, encoding="utf-8") as f:
                    data = json.load(f)
                all_reports.extend(data if isinstance(data, list) else [data])
        else:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            all_reports = data if isinstance(data, list) else [data]
        print(f"[OK] Loaded {len(all_reports)} report(s)")

    elif args.from_pdf:
        pdfs = collect_pdfs(args.from_pdf)
        if not pdfs:
            print("[ERROR] No PDF files found.")
            sys.exit(1)
        for pdf_path in pdfs:
            print(f"\n-- {pdf_path.name} --")
            images = pdf_to_pil_images(pdf_path)
            all_reports.extend(extract_with_easyocr(images, args.workers, Path("data")))

        if not all_reports:
            print("[DONE] Nothing extracted.")
            return

        pdf_root = (
            Path(args.from_pdf[0]) if Path(args.from_pdf[0]).is_dir()
            else Path(args.from_pdf[0]).parent
        )
        out_path = _save_json(
            all_reports, args.output,
            args.from_pdf[0] if len(args.from_pdf) == 1 else "tandelta",
            pdf_root / "data",
        )
        print(f"\n[SAVED] {out_path}")
        if args.emit_only:
            return

    if not all_reports:
        return

    print("\n[3/3] Seeding to database...")
    with _SessionLocal() as session:
        seed_reports(session, all_reports, dry_run=args.dry_run)


if __name__ == "__main__":
    main()