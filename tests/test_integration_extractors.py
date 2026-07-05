"""
Integration tests: run PDF extractors against real source files and assert
coverage thresholds.

Usage (from repo root, venv active):
    python tests/test_integration_extractors.py
    python tests/test_integration_extractors.py --verbose
    python tests/test_integration_extractors.py --pages 5   # quick smoke run

Source folders (edit if paths change):
    TAN DELTA : C:/Yesu/KPTCL/source/tandelta
    OIL BGV   : C:/Yesu/KPTCL/source/oilbgv
"""

import argparse
import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Thresholds ─────────────────────────────────────────────────────────────────
# At least this fraction of rows must have at least one data value populated.
WINDING_ROW_FILL   = 0.80   # 80 % of winding rows
BUSHING_ROW_FILL   = 0.80
IDAX_ROW_FILL      = 0.60   # IDAX can have blanks (e.g. HV-TV not tested)
OIL_ROW_FILL       = 0.70   # oil test rows
SCALAR_FILL        = 0.60   # fraction of key scalar fields present

TAN_DELTA_SCALARS = ["serial_number", "test_date", "sub_station", "make",
                     "frequency_hz", "ambient_temp_c", "winding_itc_factor"]
OIL_SCALARS       = ["serial_number", "test_date", "sub_station", "make"]

SOURCE_FOLDERS = {
    "tan_delta": Path("C:/Yesu/KPTCL/source/tandelta"),
    "oil_bgv":   Path("C:/Yesu/KPTCL/source/oilbgv"),
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _pdf_to_images(pdf_path: Path, page_limit: int | None = None):
    import fitz
    from PIL import Image
    doc   = fitz.open(str(pdf_path))
    total = len(doc)
    limit = min(page_limit, total) if page_limit else total
    images = []
    for i in range(limit):
        pix = doc[i].get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
        images.append(Image.open(io.BytesIO(pix.tobytes("png"))))
    doc.close()
    return images


def _row_fill_rate(rows: list[dict], skip_keys: set) -> float:
    if not rows:
        return 1.0
    filled = sum(
        1 for row in rows
        if any(v for k, v in row.items() if k not in skip_keys and v is not None and v != "")
    )
    return filled / len(rows)


def _scalar_fill_rate(report: dict, keys: list[str]) -> float:
    present = sum(1 for k in keys if report.get(k))
    return present / len(keys)


class TestResult:
    def __init__(self, pdf: str, report_idx: int, report: dict):
        self.pdf        = pdf
        self.report_idx = report_idx
        self.report     = report
        self.failures: list[str] = []

    def check(self, condition: bool, msg: str):
        if not condition:
            self.failures.append(msg)

    @property
    def passed(self):
        return not self.failures


# ── Tan Delta assertions ────────────────────────────────────────────────────────

def _assert_tan_delta(tr: TestResult, verbose: bool):
    r = tr.report

    scalar_rate = _scalar_fill_rate(r, TAN_DELTA_SCALARS)
    tr.check(scalar_rate >= SCALAR_FILL,
             f"scalar fill {scalar_rate:.0%} < {SCALAR_FILL:.0%}  (present: "
             f"{[k for k in TAN_DELTA_SCALARS if r.get(k)]})")

    for table_key, threshold, label in [
        ("winding",    WINDING_ROW_FILL, "winding"),
        ("hv_bushing", BUSHING_ROW_FILL, "hv_bushing"),
        ("lv_bushing", BUSHING_ROW_FILL, "lv_bushing"),
        ("idax",       IDAX_ROW_FILL,    "idax"),
    ]:
        rows = r.get(table_key, [])
        skip = {"test_configuration", "bushing"}
        rate = _row_fill_rate(rows, skip)
        tr.check(rate >= threshold,
                 f"{label}: row fill {rate:.0%} < {threshold:.0%}  "
                 f"({sum(1 for row in rows if any(v for k,v in row.items() if k not in skip and v))}"
                 f"/{len(rows)} rows)")

    # IDAX rows must use HV-GND / HV-LV etc. (not old CHG/CHL codes)
    idax_configs = [row.get("test_configuration", "") for row in r.get("idax", [])]
    old_codes = [c for c in idax_configs if c in ("CHG","CHL","CLG","CLT","CTG","CTH")]
    tr.check(not old_codes, f"IDAX still uses old short codes: {old_codes}")

    expected_configs = {"HV-GND", "HV-LV", "LV-GND", "LV-TV", "TV-GND", "HV-TV"}
    actual_configs   = set(idax_configs)
    tr.check(actual_configs == expected_configs,
             f"IDAX configs mismatch: expected {expected_configs}, got {actual_configs}")

    if verbose:
        _print_tan_delta(r)


def _print_tan_delta(r: dict):
    print(f"    serial={r.get('serial_number')}  date={r.get('test_date')}")
    for k in TAN_DELTA_SCALARS:
        print(f"      {k}: {r.get(k)!r}")
    for tk in ("winding", "hv_bushing", "lv_bushing", "idax"):
        rows = r.get(tk, [])
        skip = {"test_configuration", "bushing"}
        filled = sum(1 for row in rows if any(v for k,v in row.items() if k not in skip and v))
        print(f"      {tk}: {filled}/{len(rows)} rows populated")
    print(f"      idax configs: {[r2.get('test_configuration') for r2 in r.get('idax', [])]}")


# ── Oil BGV assertions ──────────────────────────────────────────────────────────

def _assert_oil(tr: TestResult, verbose: bool):
    r = tr.report

    scalar_rate = _scalar_fill_rate(r, OIL_SCALARS)
    tr.check(scalar_rate >= SCALAR_FILL,
             f"scalar fill {scalar_rate:.0%} < {SCALAR_FILL:.0%}")

    oil_rows = r.get("oil") or []
    filled_oil = [row for row in oil_rows if row.get("measured_value") is not None]
    tr.check(len(filled_oil) >= 3,
             f"oil: only {len(filled_oil)}/{len(oil_rows)} rows have measured_value (expected >= 3)")

    if verbose:
        print(f"    serial={r.get('serial_number')}  date={r.get('test_date')}")
        for k in OIL_SCALARS:
            print(f"      {k}: {r.get(k)!r}")
        print(f"      oil rows filled: {len(filled_oil)}/{len(oil_rows)}")
        dga_rows = r.get("dga") or []
        dga_filled = [(row.get("gas"), row.get("value_bottom")) for row in dga_rows if row.get("value_bottom") is not None]
        print(f"      dga values: {dga_filled}")


# ── Runner ─────────────────────────────────────────────────────────────────────

def run_tan_delta(folder: Path, page_limit: int | None, verbose: bool) -> list[TestResult]:
    from seed_tandelta_from_pdf import extract_with_easyocr
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"  [SKIP] no PDFs in {folder}")
        return []

    results = []
    for pdf in pdfs:
        print(f"  PDF: {pdf.name}")
        images  = _pdf_to_images(pdf, page_limit)
        reports = extract_with_easyocr(images, workers=1)
        if not reports:
            tr = TestResult(pdf.name, 0, {})
            tr.failures.append("no reports extracted")
            results.append(tr)
            continue
        for i, r in enumerate(reports):
            tr = TestResult(pdf.name, i, r)
            _assert_tan_delta(tr, verbose)
            results.append(tr)
    return results


def run_oil(folder: Path, page_limit: int | None, verbose: bool) -> list[TestResult]:
    from seed_oil_tests_from_pdf import extract_with_easyocr
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        print(f"  [SKIP] no PDFs in {folder}")
        return []

    results = []
    for pdf in pdfs:
        print(f"  PDF: {pdf.name}")
        images  = _pdf_to_images(pdf, page_limit)
        reports = extract_with_easyocr(images, workers=1)
        if not reports:
            tr = TestResult(pdf.name, 0, {})
            tr.failures.append("no reports extracted")
            results.append(tr)
            continue
        for i, r in enumerate(reports):
            tr = TestResult(pdf.name, i, r)
            _assert_oil(tr, verbose)
            results.append(tr)
    return results


def _print_summary(label: str, results: list[TestResult]):
    passed = sum(1 for r in results if r.passed)
    total  = len(results)
    status = "PASS" if passed == total else "FAIL"
    print(f"\n{'='*65}")
    print(f"  {label}  [{status}]  {passed}/{total} reports passed")
    print(f"{'='*65}")
    for tr in results:
        tag = "PASS" if tr.passed else "FAIL"
        print(f"  [{tag}] {tr.pdf}  report #{tr.report_idx + 1}")
        for f in tr.failures:
            print(f"         -- {f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pages",   type=int, default=None,
                        help="Limit each PDF to first N pages (faster spot check)")
    parser.add_argument("--verbose", action="store_true",
                        help="Print extracted field values for each report")
    parser.add_argument("--only",    choices=["tan_delta", "oil_bgv"],
                        help="Run only one extractor")
    args = parser.parse_args()

    all_results: dict[str, list[TestResult]] = {}

    if args.only in (None, "tan_delta"):
        folder = SOURCE_FOLDERS["tan_delta"]
        if folder.exists():
            print(f"\n[TAN DELTA]  {folder}")
            all_results["Tan Delta"] = run_tan_delta(folder, args.pages, args.verbose)
        else:
            print(f"\n[TAN DELTA]  folder not found: {folder}")

    if args.only in (None, "oil_bgv"):
        folder = SOURCE_FOLDERS["oil_bgv"]
        if folder.exists():
            print(f"\n[OIL BGV]  {folder}")
            all_results["Oil BGV"] = run_oil(folder, args.pages, args.verbose)
        else:
            print(f"\n[OIL BGV]  folder not found: {folder}")

    overall_pass = True
    for label, results in all_results.items():
        _print_summary(label, results)
        if any(not r.passed for r in results):
            overall_pass = False

    print(f"\n{'='*65}")
    print(f"  OVERALL: {'PASS' if overall_pass else 'FAIL'}")
    print(f"{'='*65}\n")
    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
