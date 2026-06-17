"""
Test script: run the Tan Delta PDF extractor against a real PDF and print results.

Usage (from repo root, venv active):
    python tests/test_tandelta_extractor.py "C:/Users/yesuv/Downloads/Tan Delta 1 (2).pdf"

Optional flags:
    --pages N        Only process the first N pages (faster for spot-checking)
    --debug          Dump raw OCR text files to data/raw_ocr_* for inspection
    --form           Also run _tandelta_test_data() and show the final form payload
"""

import sys
import json
import argparse
from pathlib import Path

# ── allow running from repo root or tests/ ────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _render_table(rows: list[dict], indent: int = 6) -> None:
    if not rows:
        print(" " * indent + "(empty)")
        return
    pad = " " * indent
    keys = list(rows[0].keys())
    col_w = {k: max(len(k), max((len(str(r.get(k, "") or "")) for r in rows), default=0)) for k in keys}
    header = "  ".join(k.ljust(col_w[k]) for k in keys)
    sep    = "  ".join("-" * col_w[k] for k in keys)
    print(pad + header)
    print(pad + sep)
    for row in rows:
        print(pad + "  ".join(str(row.get(k, "") or "").ljust(col_w[k]) for k in keys))


def _print_report(idx: int, r: dict) -> None:
    print(f"\n{'='*70}")
    print(f"  REPORT {idx + 1}  —  serial={r.get('serial_number')}  date={r.get('test_date')}")
    print(f"{'='*70}")

    # Scalar fields
    scalars = [
        ("Sub-station",       r.get("sub_station")),
        ("Make",              r.get("make")),
        ("Capacity MVA",      r.get("capacity_mva")),
        ("Vector group",      r.get("vector_group")),
        ("Voltage class",     r.get("voltage_class")),
        ("Test voltage kV",   r.get("test_voltage_kv")),
        ("Frequency Hz",      r.get("frequency_hz")),
        ("Ambient temp °C",   r.get("ambient_temp_c")),
        ("Oil temp °C",       r.get("oil_temp_c")),
        ("Weather",           r.get("weather_condition")),
        ("Instrument",        r.get("instrument_make")),
        ("Overall result",    r.get("overall_result")),
        ("Recommendation",    r.get("recommendation")),
    ]
    print("\n  Scalar fields:")
    for label, val in scalars:
        status = "OK" if val else "--"
        print(f"    {status}  {label:<22} {val!r}")

    # Winding table
    print(f"\n  Winding test results (ITC={r.get('winding_itc_factor')}):")
    _render_table(r.get("winding", []))

    # HV bushing
    print(f"\n  220kV Bushing (ITC={r.get('hv_bushing_itc_factor')}):")
    _render_table(r.get("hv_bushing", []))

    # LV bushing
    print(f"\n  66kV Bushing (ITC={r.get('lv_bushing_itc_factor')}):")
    _render_table(r.get("lv_bushing", []))

    # IDAX
    print(f"\n  IDAX ({r.get('idax_testing_kit', '(kit unknown)')}):")
    _render_table(r.get("idax", []))
    if r.get("idax_observation"):
        print(f"       Observation: {r['idax_observation']}")

    # Warn on empty IDAX rows
    empty_idax = [row["test_configuration"] for row in r.get("idax", [])
                  if not any(v for k, v in row.items() if k != "test_configuration")]
    if empty_idax:
        print(f"\n  WARN  IDAX rows with NO data extracted: {empty_idax}")


def _print_form(idx: int, form: dict) -> None:
    print(f"\n  --- Form payload (report {idx + 1}) ---")
    for key, val in form.items():
        if isinstance(val, list):
            print(f"    {key}:")
            _render_table(val, indent=8)
        else:
            print(f"    {key}: {val!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", help="Path to the Tan Delta PDF")
    parser.add_argument("--pages", type=int, default=None, help="Limit to first N pages")
    parser.add_argument("--debug", action="store_true", help="Save raw OCR text files")
    parser.add_argument("--form", action="store_true", help="Show final form payload")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"ERROR: file not found: {pdf_path}")
        sys.exit(1)

    print(f"\nPDF : {pdf_path.name}")
    print(f"Size: {pdf_path.stat().st_size / 1_048_576:.1f} MB")

    # ── Convert PDF pages to images ───────────────────────────────────────────
    try:
        import fitz  # PyMuPDF
    except ImportError:
        print("ERROR: PyMuPDF not installed. Run: pip install pymupdf")
        sys.exit(1)

    print("\nConverting PDF pages to images...")
    doc    = fitz.open(str(pdf_path))
    total  = len(doc)
    limit  = min(args.pages, total) if args.pages else total
    print(f"  {total} pages total, processing {limit}.")

    images = []
    from PIL import Image
    import io
    for i in range(limit):
        page = doc[i]
        mat  = fitz.Matrix(2.0, 2.0)  # 2× for OCR quality
        pix  = page.get_pixmap(matrix=mat)
        img  = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    doc.close()

    # ── Run extractor ─────────────────────────────────────────────────────────
    from seed_tandelta_from_pdf import extract_with_easyocr, _tandelta_test_data

    debug_dir = Path("data/debug_ocr") if args.debug else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Raw OCR output will be saved to: {debug_dir}/")

    print("\nRunning OCR extractor...")
    reports = extract_with_easyocr(images, workers=1, debug_dir=debug_dir)

    # ── Results ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  SUMMARY: {len(reports)} report(s) extracted from {limit} page(s)")
    print(f"{'='*70}")

    if not reports:
        print("\n  --  No reports extracted. Run with --debug to inspect raw OCR text.")
        sys.exit(1)

    for i, r in enumerate(reports):
        _print_report(i, r)

        if args.form:
            form = _tandelta_test_data(r)
            _print_form(i, form)

    # ── Coverage check ────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  FIELD COVERAGE CHECK")
    print(f"{'='*70}")

    scalar_keys = [
        "serial_number", "test_date", "sub_station", "make",
        "test_voltage_kv", "frequency_hz", "ambient_temp_c", "oil_temp_c",
        "instrument_make", "winding_itc_factor",
    ]
    table_keys = ["winding", "hv_bushing", "lv_bushing", "idax"]

    for i, r in enumerate(reports):
        print(f"\n  Report {i + 1} ({r.get('serial_number', '?')}):")
        for k in scalar_keys:
            v = r.get(k)
            print(f"    {'OK' if v else '--'}  {k}: {v!r}")
        for tk in table_keys:
            rows  = r.get(tk, [])
            filled = sum(
                1 for row in rows
                if any(v for k, v in row.items() if k != "test_configuration" and k != "bushing")
            )
            print(f"    {'OK' if filled else '--'}  {tk}: {filled}/{len(rows)} rows populated")

    print()


if __name__ == "__main__":
    main()
