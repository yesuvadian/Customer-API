"""
Pre-Commission QAP Report Generator
Generates PDF and HTML reports replicating the KPTCL Manufacturing Quality Plan
table format for Power Transformers.
"""

import io
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy.orm import Session

from models import (
    PreCommissionRequest,
    RepairStageAuditLog,
    RepairStageData,
    RepairStageDefinition,
    RepairStageInstance,
    RepairWorkflow,
    User,
)

# ── Stage display order ───────────────────────────────────────────────────────
STAGE_CODES_ORDER = [
    "QAP_RAW_MATERIAL",
    "QAP_CORE_ASSEMBLY",
    "QAP_WINDING",
    "QAP_ACTIVE_PART",
    "QAP_TANK_FITTINGS",
    "QAP_ACTIVE_IN_TANK",
    "QAP_ROUTINE_TESTS",
    "QAP_SPECIAL_TESTS",
    "QAP_FINAL_DISPATCH",
]

# Table field keys that contain check-item rows (match PRECOMMISSION_STAGE_TEMPLATES.json)
CHECK_TABLE_KEYS = [
    "crgo_checks", "conductor_checks", "insulation_checks",
    "oil_checks", "bushing_checks", "oltc_checks", "cooling_checks",
    "core_checks", "winding_checks", "active_part_checks",
    "tank_checks", "assembly_checks", "routine_test_checks",
    "special_test_checks", "dispatch_checks",
]

# ── Colours ───────────────────────────────────────────────────────────────────
KPTCL_BLUE   = colors.HexColor("#003087")
HEADER_GREY  = colors.HexColor("#D9D9D9")
ALT_ROW      = colors.HexColor("#F5F5F5")
PASS_GREEN   = colors.HexColor("#C6EFCE")
FAIL_RED     = colors.HexColor("#FFC7CE")
SECTION_BG   = colors.HexColor("#BDD7EE")


class PreCommissionReportService:

    def __init__(self, db: Session):
        self.db = db

    # ── Public API ────────────────────────────────────────────────────────────

    def generate_pdf(self, workflow_id: UUID) -> bytes:
        data = self._collect(workflow_id)
        return self._build_pdf(data)

    def generate_html(self, workflow_id: UUID) -> str:
        data = self._collect(workflow_id)
        return self._build_html(data)

    # ── Data collection ───────────────────────────────────────────────────────

    def _collect(self, workflow_id: UUID) -> dict:
        workflow = self.db.query(RepairWorkflow).filter(
            RepairWorkflow.id == workflow_id
        ).first()
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found.")
        if workflow.workflow_code != "PRE_COMMISSION":
            raise ValueError("This report is only available for PRE_COMMISSION workflows.")

        # PCR record
        pcr = self.db.query(PreCommissionRequest).filter(
            PreCommissionRequest.workflow_id == workflow_id
        ).first()

        # Collect stage data in order
        stages_data = []
        for code in STAGE_CODES_ORDER:
            stage_def = self.db.query(RepairStageDefinition).filter(
                RepairStageDefinition.code == code
            ).first()
            if not stage_def:
                continue

            instance = self.db.query(RepairStageInstance).filter(
                RepairStageInstance.workflow_id == workflow_id,
                RepairStageInstance.stage_id    == stage_def.id,
            ).first()

            form_data = {}
            if instance:
                saved = self.db.query(RepairStageData).filter(
                    RepairStageData.stage_instance_id == instance.id
                ).order_by(RepairStageData.created_at.desc()).first()
                if saved and saved.form_data:
                    form_data = saved.form_data

            # Collect approval info from audit log
            approval_log = self.db.query(RepairStageAuditLog).filter(
                RepairStageAuditLog.workflow_id == workflow_id,
                RepairStageAuditLog.stage_id    == stage_def.id,
                RepairStageAuditLog.action      == "approve",
            ).order_by(RepairStageAuditLog.performed_at.desc()).first()

            approved_by_name = None
            approved_at      = None
            if approval_log:
                approver = self.db.query(User).filter(
                    User.id == approval_log.performed_by
                ).first()
                approved_by_name = f"{approver.firstname or ''} {approver.lastname or ''}".strip() if approver else None
                approved_at      = approval_log.performed_at

            stages_data.append({
                "code":             code,
                "name":             stage_def.name,
                "status":           instance.status if instance else "not_started",
                "form_data":        form_data,
                "approved_by":      approved_by_name,
                "approved_at":      approved_at,
                "completed_at":     instance.completed_at if instance else None,
            })

        return {
            "workflow":    workflow,
            "pcr":         pcr,
            "stages":      stages_data,
            "generated_at": datetime.now(timezone.utc),
        }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _fmt_date(self, dt) -> str:
        if not dt:
            return "—"
        try:
            return dt.strftime("%d-%m-%Y")
        except Exception:
            return str(dt)[:10]

    def _tick(self, value) -> str:
        """Convert bool/string to ✓ or blank."""
        if value is True or str(value).lower() in ("true", "yes", "1"):
            return "✓"
        return ""

    def _user_name(self, user_id) -> str:
        if not user_id:
            return "—"
        u = self.db.query(User).filter(User.id == user_id).first()
        if u:
            return f"{u.firstname or ''} {u.lastname or ''}".strip() or u.email
        return "—"

    def _extract_check_rows(self, form_data: dict) -> list[dict]:
        """Pull all check-item table rows from saved form_data."""
        rows = []
        for key in CHECK_TABLE_KEYS:
            if key in form_data and isinstance(form_data[key], list):
                rows.extend(form_data[key])
        return rows

    def _visit_info(self, form_data: dict) -> dict:
        return {
            "inspection_date":    form_data.get("inspection_date", ""),
            "kptcl_members":      form_data.get("kptcl_members", ""),
            "third_party_agency": form_data.get("third_party_agency", ""),
            "manufacturer_rep":   form_data.get("manufacturer_rep", ""),
            "place":              form_data.get("place_of_inspection", ""),
            "overall_result":     form_data.get("overall_result", ""),
            "overall_remarks":    form_data.get("overall_remarks", ""),
        }

    # ── PDF ───────────────────────────────────────────────────────────────────

    def _build_pdf(self, data: dict) -> bytes:
        pcr      = data["pcr"]
        workflow = data["workflow"]
        stages   = data["stages"]

        buf = io.BytesIO()
        # Use A3 landscape to give enough horizontal space for all columns
        doc = SimpleDocTemplate(
            buf,
            pagesize=landscape(A3),
            topMargin=12 * mm,
            bottomMargin=12 * mm,
            leftMargin=10 * mm,
            rightMargin=10 * mm,
        )

        styles = getSampleStyleSheet()
        cell   = ParagraphStyle("cell",   fontName="Helvetica",      fontSize=7,  leading=9)
        cell_b = ParagraphStyle("cell_b", fontName="Helvetica-Bold", fontSize=7,  leading=9)
        sec    = ParagraphStyle("sec",    fontName="Helvetica-Bold", fontSize=8,  leading=10, textColor=KPTCL_BLUE)
        h1     = ParagraphStyle("h1",     fontName="Helvetica-Bold", fontSize=11, leading=14, alignment=TA_CENTER)
        h2     = ParagraphStyle("h2",     fontName="Helvetica",      fontSize=8,  leading=10, alignment=TA_CENTER)
        small  = ParagraphStyle("small",  fontName="Helvetica",      fontSize=7,  leading=9,  textColor=colors.grey)

        story = []

        # ── Title block ───────────────────────────────────────────────────────
        story.append(Paragraph(
            "Manufacturing Quality Plan for Power Transformers",
            h1
        ))
        story.append(Spacer(1, 2 * mm))

        # Sub-header: Manufacturer / Third party / KPTCL
        # Pull from first completed stage with visit info
        manufacturer_name = pcr.vendor_name if pcr else "—"
        third_party       = "—"
        for s in stages:
            vi = self._visit_info(s["form_data"])
            if vi["third_party_agency"]:
                third_party = vi["third_party_agency"]
                break

        sub_data = [[
            Paragraph(f"<b>A. Manufacturer:</b> M/s {manufacturer_name}", h2),
            Paragraph(f"<b>B. Third Party Inspection Agency (BPTIO):</b> M/s {third_party}", h2),
            Paragraph("<b>As proposed by the Committee</b>", h2),
        ]]
        sub_table = Table(sub_data, colWidths=["33%", "34%", "33%"])
        sub_table.setStyle(TableStyle([
            ("BOX",         (0, 0), (-1, -1), 0.5, KPTCL_BLUE),
            ("INNERGRID",   (0, 0), (-1, -1), 0.5, KPTCL_BLUE),
            ("TOPPADDING",  (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ]))
        story.append(sub_table)
        story.append(Spacer(1, 4 * mm))

        # PCR details block
        if pcr:
            meta = [
                ["Request No.", pcr.request_number or "—",
                 "Voltage Class", pcr.voltage_class or "—",
                 "Rated MVA", str(pcr.rated_mva) if pcr.rated_mva else "—"],
                ["PO Number", pcr.purchase_order_number or "—",
                 "Transformer Type", pcr.transformer_type or "—",
                 "Cooling Class", pcr.cooling_class or "—"],
                ["PO Date", self._fmt_date(pcr.po_date),
                 "Vector Group", pcr.vector_group or "—",
                 "Quantity", str(pcr.quantity) if pcr.quantity else "1"],
            ]
            meta_table = Table(
                [[Paragraph(str(c), cell_b if i % 2 == 0 else cell) for i, c in enumerate(row)]
                 for row in meta],
                colWidths=[28*mm, 50*mm, 35*mm, 50*mm, 28*mm, 40*mm],
            )
            meta_table.setStyle(TableStyle([
                ("BOX",          (0, 0), (-1, -1), 0.5, colors.black),
                ("INNERGRID",    (0, 0), (-1, -1), 0.3, colors.lightgrey),
                ("BACKGROUND",   (0, 0), (0, -1), HEADER_GREY),
                ("BACKGROUND",   (2, 0), (2, -1), HEADER_GREY),
                ("BACKGROUND",   (4, 0), (4, -1), HEADER_GREY),
                ("TOPPADDING",   (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
                ("FONTSIZE",     (0, 0), (-1, -1), 7),
            ]))
            story.append(meta_table)
            story.append(Spacer(1, 4 * mm))

        # ── Column header row ─────────────────────────────────────────────────
        col_header = [
            Paragraph("<b>Sl. No.</b>", cell_b),
            Paragraph("<b>Components and Operations</b>", cell_b),
            Paragraph("<b>Type of Check</b>", cell_b),
            Paragraph("<b>Quantum of Check</b>", cell_b),
            Paragraph("<b>Acceptance Norms</b>", cell_b),
            Paragraph("<b>Observed Value</b>", cell_b),
            Paragraph("<b>M</b>", cell_b),
            Paragraph("<b>B</b>", cell_b),
            Paragraph("<b>A</b>", cell_b),
            Paragraph("<b>Result</b>", cell_b),
            Paragraph("<b>Remarks</b>", cell_b),
        ]

        # Column widths (A3 landscape ~400mm usable)
        COL_W = [14*mm, 70*mm, 22*mm, 22*mm, 60*mm, 40*mm, 8*mm, 8*mm, 8*mm, 18*mm, 40*mm]

        table_data    = [col_header]
        table_styles  = [
            ("BACKGROUND",   (0, 0), (-1, 0), KPTCL_BLUE),
            ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
            ("BOX",          (0, 0), (-1, -1), 0.5, colors.black),
            ("INNERGRID",    (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ("TOPPADDING",   (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN",        (6, 0), (8, -1),  "CENTER"),
            ("ALIGN",        (9, 0), (9, -1),  "CENTER"),
        ]

        row_idx = 1  # 0 = header

        # ── Stage rows ────────────────────────────────────────────────────────
        for stage in stages:
            # Stage section header
            vi    = self._visit_info(stage["form_data"])
            rows  = self._extract_check_rows(stage["form_data"])

            # Stage name row (spans all columns)
            stage_label = f"{stage['name'].upper()}"
            if vi["inspection_date"]:
                stage_label += f"  |  Inspection Date: {vi['inspection_date']}"
            if vi["kptcl_members"]:
                stage_label += f"  |  KPTCL: {vi['kptcl_members']}"
            if stage["approved_by"]:
                stage_label += f"  |  Approved by: {stage['approved_by']}  ({self._fmt_date(stage['approved_at'])})"

            table_data.append([
                Paragraph(stage_label, sec),
                "", "", "", "", "", "", "", "", "", ""
            ])
            table_styles.append(
                ("SPAN",       (0, row_idx), (-1, row_idx))
            )
            table_styles.append(
                ("BACKGROUND", (0, row_idx), (-1, row_idx), SECTION_BG)
            )
            table_styles.append(
                ("TOPPADDING", (0, row_idx), (-1, row_idx), 3)
            )
            row_idx += 1

            if not rows:
                # Stage not yet filled
                table_data.append([
                    Paragraph("—", cell),
                    Paragraph("Stage not yet inspected", cell),
                    "", "", "", "", "", "", "", "", "",
                ])
                table_styles.append(
                    ("SPAN", (1, row_idx), (-1, row_idx))
                )
                row_idx += 1
            else:
                for i, row in enumerate(rows):
                    result     = str(row.get("result", "")).strip()
                    bg         = PASS_GREEN if result == "Pass" else (FAIL_RED if result == "Fail" else colors.white)
                    even_bg    = ALT_ROW if i % 2 == 0 else colors.white

                    table_data.append([
                        Paragraph(str(i + 1), cell),
                        Paragraph(str(row.get("check_item", "—")), cell),
                        Paragraph(str(row.get("type_of_check", "—")), cell),
                        Paragraph(str(row.get("quantum", "—")), cell),
                        Paragraph(str(row.get("acceptance", "—")), cell),
                        Paragraph(str(row.get("observed", "—")), cell),
                        Paragraph(self._tick(row.get("witness_m")), cell),
                        Paragraph(self._tick(row.get("witness_b")), cell),
                        Paragraph(self._tick(row.get("witness_a")), cell),
                        Paragraph(result or "—", cell),
                        Paragraph(str(row.get("remarks", "")), cell),
                    ])

                    # Alternate row background; override with result colour for result cell
                    table_styles.append(("BACKGROUND", (0, row_idx), (5, row_idx), even_bg))
                    table_styles.append(("BACKGROUND", (6, row_idx), (8, row_idx), even_bg))
                    table_styles.append(("BACKGROUND", (9, row_idx), (9, row_idx), bg))
                    table_styles.append(("BACKGROUND", (10, row_idx), (10, row_idx), even_bg))
                    row_idx += 1

            # Overall result row for stage
            if vi["overall_result"]:
                ov_result = vi["overall_result"]
                ov_bg     = PASS_GREEN if "Pass" in ov_result or "Clear" in ov_result else (
                    FAIL_RED if "Fail" in ov_result or "Hold" in ov_result else HEADER_GREY
                )
                table_data.append([
                    Paragraph("", cell),
                    Paragraph(f"Overall Stage Result: {ov_result}", cell_b),
                    "", "", "",
                    Paragraph(vi["overall_remarks"] or "", cell),
                    "", "", "",
                    Paragraph(ov_result, cell_b),
                    "",
                ])
                table_styles += [
                    ("SPAN",       (1, row_idx), (4, row_idx)),
                    ("SPAN",       (5, row_idx), (8, row_idx)),
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), ov_bg),
                ]
                row_idx += 1

        # Build table
        main_table = Table(table_data, colWidths=COL_W, repeatRows=1)
        main_table.setStyle(TableStyle(table_styles))
        story.append(main_table)

        story.append(Spacer(1, 6 * mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=KPTCL_BLUE))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            f"Generated: {data['generated_at'].strftime('%d-%m-%Y %H:%M')} UTC  |  "
            f"Workflow: {workflow.workflow_number}  |  "
            f"Status: {workflow.status.upper()}",
            small
        ))

        doc.build(story)
        return buf.getvalue()

    # ── HTML ─────────────────────────────────────────────────────────────────

    def _build_html(self, data: dict) -> str:
        pcr    = data["pcr"]
        stages = data["stages"]

        manufacturer_name = pcr.vendor_name if pcr else "—"
        third_party       = "—"
        for s in stages:
            vi = self._visit_info(s["form_data"])
            if vi["third_party_agency"]:
                third_party = vi["third_party_agency"]
                break

        def esc(v) -> str:
            if v is None:
                return "—"
            return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        def tick(v) -> str:
            return "&#10003;" if v is True or str(v).lower() in ("true", "yes", "1") else ""

        rows_html = ""

        for stage in stages:
            vi         = self._visit_info(stage["form_data"])
            check_rows = self._extract_check_rows(stage["form_data"])

            # Visit detail subtitle
            visit_detail = " | ".join(filter(None, [
                f"Date: {vi['inspection_date']}" if vi['inspection_date'] else "",
                f"KPTCL: {vi['kptcl_members']}" if vi['kptcl_members'] else "",
                f"Third Party: {vi['third_party_agency']}" if vi['third_party_agency'] else "",
                f"Manufacturer Rep: {vi['manufacturer_rep']}" if vi['manufacturer_rep'] else "",
            ]))

            rows_html += f"""
            <tr class="stage-header">
                <td colspan="11">
                    {esc(stage['name'].upper())}
                    {'<span class="visit-detail"> | ' + esc(visit_detail) + '</span>' if visit_detail else ''}
                    {'<span class="approved-badge">&#10003; Approved by ' + esc(stage['approved_by']) + ' (' + self._fmt_date(stage['approved_at']) + ')</span>' if stage['approved_by'] else ''}
                </td>
            </tr>"""

            if not check_rows:
                rows_html += f"""
                <tr><td></td>
                    <td colspan="10" style="color:#999;font-style:italic;">Stage not yet inspected</td>
                </tr>"""
            else:
                for i, row in enumerate(check_rows):
                    result   = esc(row.get("result", ""))
                    result_cls = ("pass" if result == "Pass" else
                                  "fail" if result == "Fail" else "")
                    alt_cls  = "alt" if i % 2 == 0 else ""
                    rows_html += f"""
                    <tr class="{alt_cls}">
                        <td class="center">{i+1}</td>
                        <td>{esc(row.get('check_item', ''))}</td>
                        <td class="center">{esc(row.get('type_of_check', ''))}</td>
                        <td class="center">{esc(row.get('quantum', ''))}</td>
                        <td>{esc(row.get('acceptance', ''))}</td>
                        <td>{esc(row.get('observed', ''))}</td>
                        <td class="center witness">{tick(row.get('witness_m'))}</td>
                        <td class="center witness">{tick(row.get('witness_b'))}</td>
                        <td class="center witness">{tick(row.get('witness_a'))}</td>
                        <td class="center {result_cls}">{result}</td>
                        <td>{esc(row.get('remarks', ''))}</td>
                    </tr>"""

            # Overall result
            if vi["overall_result"]:
                ov     = esc(vi["overall_result"])
                ov_cls = ("pass" if "Pass" in vi["overall_result"] or "Clear" in vi["overall_result"]
                          else "fail" if "Fail" in vi["overall_result"] or "Hold" in vi["overall_result"]
                          else "")
                rows_html += f"""
                <tr class="overall-row">
                    <td></td>
                    <td colspan="4"><b>Overall Stage Result: {ov}</b></td>
                    <td colspan="4">{esc(vi['overall_remarks'])}</td>
                    <td class="center {ov_cls}"><b>{ov}</b></td>
                    <td></td>
                </tr>"""

        pcr_rows = ""
        if pcr:
            pcr_rows = f"""
            <tr>
                <th>Request No.</th><td>{esc(pcr.request_number)}</td>
                <th>Voltage Class</th><td>{esc(pcr.voltage_class)}</td>
                <th>Rated MVA</th><td>{esc(str(pcr.rated_mva) if pcr.rated_mva else '—')}</td>
            </tr>
            <tr>
                <th>PO Number</th><td>{esc(pcr.purchase_order_number)}</td>
                <th>Transformer Type</th><td>{esc(pcr.transformer_type)}</td>
                <th>Cooling Class</th><td>{esc(pcr.cooling_class)}</td>
            </tr>
            <tr>
                <th>PO Date</th><td>{esc(self._fmt_date(pcr.po_date))}</td>
                <th>Vector Group</th><td>{esc(pcr.vector_group)}</td>
                <th>Quantity</th><td>{esc(str(pcr.quantity))}</td>
            </tr>"""

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>QAP Report — {esc(pcr.request_number if pcr else 'Pre-Commission')}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: Arial, sans-serif; font-size: 11px; color: #333; background:#fff; padding:16px; }}
  h1 {{ font-size:15px; text-align:center; color:#003087; margin-bottom:4px; }}
  h2 {{ font-size:11px; text-align:center; color:#555; margin-bottom:10px; }}
  .sub-header {{ display:flex; justify-content:space-between; border:1px solid #003087;
                 padding:6px 10px; background:#f0f4ff; margin-bottom:10px; font-size:11px; }}
  .meta-table {{ width:100%; border-collapse:collapse; margin-bottom:12px; font-size:11px; }}
  .meta-table th {{ background:#D9D9D9; padding:4px 8px; text-align:left; border:1px solid #ccc; font-weight:bold; }}
  .meta-table td {{ padding:4px 8px; border:1px solid #ccc; }}
  .qap-table {{ width:100%; border-collapse:collapse; font-size:10px; }}
  .qap-table th {{ background:#003087; color:#fff; padding:5px 4px; text-align:center;
                   border:1px solid #000; font-weight:bold; position:sticky; top:0; }}
  .qap-table td {{ padding:3px 4px; border:1px solid #ccc; vertical-align:top; }}
  .qap-table tr.alt td {{ background:#f5f5f5; }}
  .stage-header td {{ background:#BDD7EE; font-weight:bold; color:#003087;
                      padding:5px 6px; border:1px solid #999; font-size:11px; }}
  .overall-row td {{ background:#e8f0fe; font-size:10px; border:1px solid #999; padding:3px 4px; }}
  .center {{ text-align:center; }}
  .witness {{ font-size:13px; color:#003087; font-weight:bold; }}
  .pass {{ background:#C6EFCE !important; color:#276221; font-weight:bold; }}
  .fail {{ background:#FFC7CE !important; color:#9C0006; font-weight:bold; }}
  .visit-detail {{ font-weight:normal; font-size:10px; color:#555; }}
  .approved-badge {{ margin-left:12px; background:#C6EFCE; color:#276221;
                     padding:2px 6px; border-radius:4px; font-size:10px; }}
  .footer {{ margin-top:12px; text-align:center; font-size:10px; color:#999; border-top:1px solid #ccc; padding-top:6px; }}
  @media print {{ .qap-table th {{ position:static; }} body {{ padding:4px; }} }}
</style>
</head>
<body>
  <h1>Manufacturing Quality Plan for Power Transformers</h1>
  <h2>{esc(pcr.voltage_class + ' Voltage Class' if pcr and pcr.voltage_class else 'Power Transformer')}</h2>

  <div class="sub-header">
    <span><b>A. Manufacturer:</b> M/s {esc(manufacturer_name)}</span>
    <span><b>B. Third Party Inspection Agency (BPTIO):</b> M/s {esc(third_party)}</span>
    <span><b>As proposed by the Committee</b></span>
  </div>

  <table class="meta-table">
    {pcr_rows}
  </table>

  <table class="qap-table">
    <thead>
      <tr>
        <th style="width:4%">Sl. No.</th>
        <th style="width:18%">Components and Operations</th>
        <th style="width:7%">Type of Check</th>
        <th style="width:7%">Quantum of Check</th>
        <th style="width:16%">Acceptance Norms</th>
        <th style="width:11%">Observed Value</th>
        <th style="width:3%">M</th>
        <th style="width:3%">B</th>
        <th style="width:3%">A</th>
        <th style="width:5%">Result</th>
        <th style="width:13%">Remarks</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>

  <div class="footer">
    Generated: {data['generated_at'].strftime('%d-%m-%Y %H:%M')} UTC &nbsp;|&nbsp;
    Workflow: {esc(data['workflow'].workflow_number)} &nbsp;|&nbsp;
    Status: {esc(data['workflow'].status.upper())} &nbsp;|&nbsp;
    Karnataka Power Transmission Corporation Limited
  </div>
</body>
</html>"""
