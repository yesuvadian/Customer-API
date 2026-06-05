"""
Consolidated Test Report Service
================================
Generates a single combined PDF spanning MULTIPLE equipment and MULTIPLE test
types, filtered by:
  • department subtree (user's hierarchy)
  • equipment type
  • selected test types (multi-select)
  • tested-at date range

Layout (per the KPTCL combined report style):
  TITLE
  └─ for each equipment (grouped):
       Equipment header (identity auto-pulled from Equipment register)
       └─ for each matching TestResult (deduplicated):
            Section — <test name> [status]
            (reuses ReportService._build_result_section — full tables,
             cross-session deviations, etc.)

Test-type agnostic: any test type (tan-delta, IDAX, oil BDV, DFR, future) is
rendered via the same generic section builders — no per-test code.
"""

import io
from datetime import datetime, date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session, joinedload
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle

from models import TestResult, TestingRequest, Equipment, CategoryDetails
from services.report_service import ReportService
from utils.common_service import get_dept_subtree_ids


class ConsolidatedReportService:
    def __init__(self, db: Session):
        self.db = db
        self._rs = ReportService(db)  # reuse section builders + styles

    # ─── Public entry ────────────────────────────────────────────────────────
    def _query_grouped(
        self,
        department_id: UUID,
        equipment_type_id: int,
        test_type_ids: list[int],
        date_from: Optional[date],
        date_to: Optional[date],
        equipment_ids: Optional[list[UUID]] = None,
    ) -> dict:
        """Run the filtered query and return {eq_id: {request, results}} grouped + deduped."""
        dept_ids = get_dept_subtree_ids(self.db, department_id)

        # Only include terminal states — testing is done and reviewer has approved.
        # outcome_active = approved + follow-up action dispatched (most common)
        # closed         = approved + no follow-up action needed
        # completed      = approved + equipment replacement finance-approved
        # commissioned   = TAQC inspection approved + equipment created
        from models import TestingRequestStatus as TRS
        _terminal = [
            TRS.outcome_active,
            TRS.closed,
            TRS.completed,
            TRS.commissioned,
        ]
        q = (
            self.db.query(TestResult)
            .join(TestingRequest, TestResult.testing_request_id == TestingRequest.id)
            .options(joinedload(TestResult.test_session))
            .filter(
                TestingRequest.department_id.in_(dept_ids),
                TestingRequest.equipment_type_id == equipment_type_id,
                TestingRequest.status.in_(_terminal),
            )
        )
        if test_type_ids:
            q = q.filter(TestingRequest.test_type_id.in_(test_type_ids))
        if equipment_ids:
            q = q.filter(TestingRequest.equipment_id.in_(equipment_ids))
        if date_from:
            q = q.filter(TestResult.tested_at >= datetime.combine(date_from, datetime.min.time()))
        if date_to:
            q = q.filter(TestResult.tested_at <= datetime.combine(date_to, datetime.max.time()))

        results = q.order_by(TestResult.tested_at.asc()).all()

        grouped: dict = {}
        for r in results:
            req = self.db.query(TestingRequest).filter(
                TestingRequest.id == r.testing_request_id
            ).first()
            eq_id = str(req.equipment_id) if req and req.equipment_id else "unassigned"
            grouped.setdefault(eq_id, {"request": req, "results": []})["results"].append(r)

        for g in grouped.values():
            g["results"] = self._dedup_results(g["results"])
        return grouped

    def generate(
        self,
        department_id: UUID,
        equipment_type_id: int,
        test_type_ids: list[int],
        date_from: Optional[date],
        date_to: Optional[date],
        equipment_ids: Optional[list[UUID]] = None,
    ) -> bytes:
        """Build the consolidated PDF and return raw bytes."""
        grouped = self._query_grouped(
            department_id, equipment_type_id, test_type_ids,
            date_from, date_to, equipment_ids,
        )

        # ── Build PDF ──────────────────────────────────────────────────────────
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            topMargin=15 * mm, bottomMargin=15 * mm,
            leftMargin=15 * mm, rightMargin=15 * mm,
        )
        styles = self._rs._build_styles()
        story = []

        story.extend(self._rs._build_header(styles, None))
        story.append(Paragraph(
            self._title_line(equipment_type_id, date_from, date_to),
            styles["ReportSubTitle"],
        ))
        story.append(Spacer(1, 4 * mm))

        if not grouped:
            story.append(Paragraph("No test results found for the selected criteria.", styles["Normal"]))
            doc.build(story)
            out = buffer.getvalue()
            buffer.close()
            return out

        first = True
        for eq_id, g in grouped.items():
            if not first:
                story.append(PageBreak())
            first = False

            # Equipment identity header (auto-pulled from register)
            story.extend(self._build_equipment_header(styles, eq_id, g["request"]))
            story.append(Spacer(1, 3 * mm))

            # Each test result rendered via the shared generic section builder
            for idx, result in enumerate(g["results"]):
                story.extend(self._rs._build_result_section(styles, result, idx))
                story.append(Spacer(1, 4 * mm))

        doc.build(story)
        out = buffer.getvalue()
        buffer.close()
        return out

    def generate_excel(
        self,
        department_id: UUID,
        equipment_type_id: int,
        test_type_ids: list[int],
        date_from: Optional[date],
        date_to: Optional[date],
        equipment_ids: Optional[list[UUID]] = None,
    ) -> bytes:
        """One worksheet per equipment (parameters as rows), mirroring the
        KPTCL per-equipment oil-test layout. Returns xlsx bytes."""
        import re
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        grouped = self._query_grouped(
            department_id, equipment_type_id, test_type_ids,
            date_from, date_to, equipment_ids,
        )

        wb = openpyxl.Workbook()
        wb.remove(wb.active)  # start clean — we add a sheet per equipment

        navy_fill = PatternFill("solid", fgColor="1565C0")
        sub_fill  = PatternFill("solid", fgColor="1A3A5C")
        white_b   = Font(bold=True, color="FFFFFF", size=10)
        bold9     = Font(bold=True, size=9)
        thin = Side(style="thin", color="CCCCCC")
        bdr  = Border(left=thin, right=thin, top=thin, bottom=thin)

        _tpl_cache: dict = {}
        def _template(tkey):
            if tkey not in _tpl_cache:
                from services.evaluation_service import EvaluationService
                _tpl_cache[tkey] = EvaluationService.get_template_data(tkey, self.db) or {}
            return _tpl_cache[tkey]

        _used_titles: set = set()
        def _sheet_title(raw: str) -> str:
            base = re.sub(r'[\\/*?:\[\]]', '-', raw or "Equipment")[:28] or "Equipment"
            title, n = base, 1
            while title in _used_titles:
                title = f"{base[:26]}_{n}"
                n += 1
            _used_titles.add(title)
            return title

        if not grouped:
            ws = wb.create_sheet("No Data")
            ws["A1"] = "No test results found for the selected criteria."
            buf = io.BytesIO(); wb.save(buf); return buf.getvalue()

        for eq_id, g in grouped.items():
            req = g["request"]
            eq = self.db.query(Equipment).filter(
                Equipment.id == req.equipment_id
            ).first() if req and req.equipment_id else None
            ueic = (eq.ueic if eq else None) or (str(eq_id)[:8] if eq_id != "unassigned" else "Unassigned")
            ws = wb.create_sheet(_sheet_title(ueic))
            ws.column_dimensions["A"].width = 34
            for col in "BCDEF":
                ws.column_dimensions[col].width = 18

            r = 1
            # Equipment identity header
            c = ws.cell(row=r, column=1, value=f"Equipment: {ueic}")
            c.font = Font(bold=True, size=12, color="1565C0"); r += 1
            nd = (eq.nameplate_data or {}) if eq else {}
            ident = [
                ("Substation", req.department.name if req and req.department else "-"),
                ("Make", (eq.manufacturer if eq else None) or nd.get("manufacturer_name", "-")),
                ("Capacity (MVA)", nd.get("rated_mva_onan", "-")),
                ("Vector Group", (eq.vector_group if eq else None) or nd.get("vector_group", "-")),
                ("Serial Number", (eq.factory_serial_number if eq else None) or "-"),
                ("Year of Mfg", (eq.year_of_manufacture if eq else None) or "-"),
            ]
            for label, val in ident:
                ws.cell(row=r, column=1, value=label).font = bold9
                ws.cell(row=r, column=2, value=str(val))
                r += 1
            r += 1  # spacer

            # Each test result → sub-table(s)
            for result in g["results"]:
                tpl = _template(result.template_key)
                # field label + table-column lookup from template
                field_labels, table_cols = {}, {}
                for sec in tpl.get("sections", []):
                    for fld in sec.get("fields", []):
                        field_labels[fld["key"]] = fld.get("label", fld["key"])
                        if fld.get("type") == "table":
                            table_cols[fld["key"]] = fld.get("columns", [])

                # Test heading
                tname = result.test_name or result.template_key or "Test"
                tested = result.tested_at.strftime("%d-%b-%Y") if result.tested_at else "-"
                hc = ws.cell(row=r, column=1,
                             value=f"{tname}   (tested {tested}, result: "
                                   f"{result.overall_result or '-'})")
                hc.font = white_b; hc.fill = navy_fill
                ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=6)
                r += 1

                td = result.test_data or {}
                # Scalars first, then tables
                scalar_keys = [k for k, v in td.items()
                               if not (isinstance(v, list) and v and isinstance(v[0], dict))
                               and k not in ("overall_result",)]
                for k in scalar_keys:
                    ws.cell(row=r, column=1, value=field_labels.get(k, k.replace("_", " ").title())).font = bold9
                    ws.cell(row=r, column=2, value=str(td.get(k)) if td.get(k) is not None else "-")
                    r += 1

                # Table fields (BDV/IFT/FP/moisture/DGA etc.)
                for k, v in td.items():
                    if not (isinstance(v, list) and v and isinstance(v[0], dict)):
                        continue
                    r += 1
                    ws.cell(row=r, column=1, value=field_labels.get(k, k.replace("_", " ").title())).font = bold9
                    r += 1
                    cols = table_cols.get(k) or [{"key": ck, "label": ck} for ck in v[0].keys()]
                    cols = [c for c in cols if not c.get("hidden")]
                    # header row
                    for ci, col in enumerate(cols, 1):
                        cc = ws.cell(row=r, column=ci, value=col.get("label", col["key"]))
                        cc.font = Font(bold=True, color="FFFFFF", size=9)
                        cc.fill = sub_fill; cc.border = bdr
                    r += 1
                    for row_dict in v:
                        for ci, col in enumerate(cols, 1):
                            val = row_dict.get(col["key"], "")
                            cc = ws.cell(row=r, column=ci, value=str(val) if val is not None else "")
                            cc.border = bdr; cc.font = Font(size=9)
                        r += 1
                r += 1  # spacer between tests

        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    # ─── Helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _dedup_results(results: list) -> list:
        """Keep the latest result per (template_key, voltage_level) key.
        Combined results and individual results for the same equipment+key
        collapse to the most recent, preventing double-rendering.
        """
        latest: dict = {}
        for r in results:
            vlevel = ""
            if isinstance(r.test_data, dict):
                vlevel = str(r.test_data.get("voltage_level", ""))
            key = (r.template_key or r.test_name or "", vlevel)
            cur = latest.get(key)
            if cur is None or (r.tested_at or r.cts) > (cur.tested_at or cur.cts):
                latest[key] = r
        # Preserve chronological order
        return sorted(latest.values(), key=lambda x: (x.tested_at or x.cts))

    def _title_line(self, equipment_type_id, date_from, date_to) -> str:
        cd = self.db.query(CategoryDetails).filter(CategoryDetails.id == equipment_type_id).first()
        et = cd.name if cd else "Equipment"
        rng = ""
        if date_from or date_to:
            rng = f"  |  {date_from or '…'} to {date_to or '…'}"
        return f"Consolidated Test Report — {et}{rng}"

    def _build_equipment_header(self, styles, eq_id: str, request):
        """Equipment identity block — pulled from the Equipment register."""
        elements = [Paragraph("Equipment Details", styles["SectionHeader"])]

        if eq_id == "unassigned" or not request or not request.equipment_id:
            elements.append(Paragraph("Unlinked equipment", styles["CellValue"]))
            return elements

        eq = self.db.query(Equipment).filter(Equipment.id == request.equipment_id).first()
        nd = (eq.nameplate_data or {}) if eq else {}

        def _v(*vals):
            for v in vals:
                if v not in (None, "", "-"):
                    return str(v)
            return "-"

        ueic = eq.ueic if eq else "-"
        substation = request.department.name if request and request.department else "-"
        capacity = _v(nd.get("rated_mva_onan"))
        capacity = f"{capacity} MVA" if capacity != "-" else "-"
        v_ratio = "-"
        if nd.get("hv_voltage"):
            v_ratio = "/".join(str(x) for x in [nd.get("hv_voltage"), nd.get("mv_voltage"), nd.get("lv_voltage")] if x) + " kV"
        doc_date = "-"
        if eq and eq.commissioned_date:
            doc_date = eq.commissioned_date.strftime("%d.%m.%Y")

        data = [
            ["UEIC", ueic, "Substation", substation],
            ["Make", _v(eq.manufacturer if eq else None, nd.get("manufacturer_name")),
             "Capacity", capacity],
            ["Voltage Ratio", v_ratio,
             "Vector Group", _v(eq.vector_group if eq else None, nd.get("vector_group"))],
            ["Serial Number", _v(eq.factory_serial_number if eq else None, nd.get("factory_serial_number")),
             "Year of Mfg", _v(eq.year_of_manufacture if eq else None, nd.get("year_of_manufacture"))],
            ["DOC", doc_date, "", ""],
        ]
        elements.append(self._rs._detail_table(data, styles))

        # Bushing details (identity) — from the equipment nameplate register
        bushings = nd.get("bushing_details")
        if isinstance(bushings, list) and bushings:
            elements.append(Spacer(1, 2 * mm))
            elements.append(Paragraph("Bushing Details", styles.get("SmallNote", styles["CellLabel"])))
            elements.extend(self._rs._build_list_table(
                "Bushing Details",
                bushings,
                [
                    {"key": "winding",   "label": "Winding / Level"},
                    {"key": "phase",     "label": "Phase"},
                    {"key": "make",      "label": "Make"},
                    {"key": "serial_no", "label": "Sl. No."},
                    {"key": "yo_mfg",    "label": "Y.O. Mfg."},
                ],
            ))
        return elements
