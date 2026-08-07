"""
Repair / Breakdown / Overhaul / Annual-Audit / Calibration Workflow PDF Report
Generates a stage-by-stage summary + dynamic form data for any RepairWorkflow.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    KeepTogether,
)
from sqlalchemy.orm import Session

from models import (
    Equipment,
    OrgTestTemplate,
    RepairStageAuditLog,
    RepairStageData,
    RepairStageDefinition,
    RepairStageInstance,
    RepairStageTemplate,
    RepairWorkflow,
    User,
)
from services.nameplate_helper import get_capacity, get_voltage_ratio

# ── Brand colours ─────────────────────────────────────────────────────────────
NAVY   = colors.HexColor("#0F2B6B")
BLUE   = colors.HexColor("#1A56DB")
GREEN  = colors.HexColor("#057A55")
ORANGE = colors.HexColor("#B45309")
RED    = colors.HexColor("#C81E1E")
GREY   = colors.HexColor("#6B7280")
LIGHT  = colors.HexColor("#F3F4F6")
LIGHT2 = colors.HexColor("#EFF6FF")
WHITE  = colors.white

STATUS_COLOR_HEX = {
    "completed":   "057A55",
    "approved":    "057A55",
    "submitted":   "1A56DB",
    "in_progress": "1A56DB",
    "pending":     "B45309",
    "rejected":    "C81E1E",
}

WORKFLOW_LABEL = {
    "BREAKDOWN":      "Breakdown Repair Workflow",
    "OVERHAUL":       "Transformer Overhauling Workflow",
    "ANNUAL_AUDIT":   "Annual Inspection & Audit Workflow",
    "CALIBRATION":    "Calibration Workflow",
    "PRE_COMMISSION": "Pre-Commission QAP Workflow",
    "SURVEILLANCE":   "Post-Commissioning Surveillance Workflow",
}


class RepairWorkflowReportService:
    def generate_html(self, workflow_id):
        wf = self._get_workflow(workflow_id)
        data = self._collect(wf)

        return f"""
        <html>
        <head>
            <title>{data['workflow_label']}</title>
        </head>
        <body>
            <h2>{data['workflow_label']}</h2>

            <p><b>Workflow No:</b> {data['workflow_number']}</p>
            <p><b>Status:</b> {data['status']}</p>
            <p><b>Equipment:</b> {data['equipment_name']}</p>

            <table border="1" cellpadding="5" cellspacing="0">
                <tr>
                    <th>Stage</th>
                    <th>Status</th>
                    <th>Assigned To</th>
                    <th>Completed By</th>
                </tr>

                {''.join(
                    f'''
                    <tr>
                        <td>{s['name']}</td>
                        <td>{s['status']}</td>
                        <td>{s['assigned_to']}</td>
                        <td>{s['completed_by']}</td>
                    </tr>
                    '''
                    for s in data["stages"]
                )}

            </table>
        </body>
        </html>
        """
    
    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Public API ─────────────────────────────────────────────────────────────

    def generate_pdf(self, workflow_id: UUID) -> bytes:
        wf = self._get_workflow(workflow_id)
        data = self._collect(wf)
        return self._build_pdf(data)

    # ── Data collection ────────────────────────────────────────────────────────

    def _get_workflow(self, workflow_id: UUID) -> RepairWorkflow:
        wf = self.db.query(RepairWorkflow).filter(RepairWorkflow.id == workflow_id).first()
        if not wf:
            raise ValueError(f"Workflow {workflow_id} not found.")
        return wf

    def _collect(self, wf: RepairWorkflow) -> dict:
        # Equipment
        equip = self.db.query(Equipment).filter(Equipment.id == wf.equipment_id).first()
        equip_name, equip_ueic = "", ""
        equip_capacity, equip_voltage_class, equip_voltage_ratio, equip_yom = "-", "-", "-", "-"
        if equip:
            equip_ueic = equip.ueic
            np = equip.nameplate_data or {}
            equip_name = (
                np.get("equipment_name") or np.get("substation_name")
                or (equip.equipment_type.name if equip.equipment_type else None)
                or (equip.department.name if equip.department else None)
                or str(equip.id)
            )
            equip_ueic = equip.ueic or ""
            equip_capacity = get_capacity(np)
            equip_voltage_class = equip.voltage_class or "-"
            equip_voltage_ratio = get_voltage_ratio(np, equip.voltage_class)
            equip_yom = str(equip.year_of_manufacture) if equip.year_of_manufacture else "-"

        # Stage instances
        instances = (
            self.db.query(RepairStageInstance)
            .filter(RepairStageInstance.workflow_id == wf.id)
            .all()
        )
        stage_ids = [i.stage_id for i in instances]
        stage_defs = {
            s.id: s
            for s in self.db.query(RepairStageDefinition)
            .filter(RepairStageDefinition.id.in_(stage_ids))
            .all()
        }
        instances.sort(key=lambda i: stage_defs[i.stage_id].sequence if i.stage_id in stage_defs else 999)

        # Stage templates (stage_id → template_data)
        stage_templates: dict[UUID, dict] = {}
        st_links = (
            self.db.query(RepairStageTemplate)
            .filter(RepairStageTemplate.stage_id.in_(stage_ids))
            .all()
        )
        tmpl_ids = [st.template_id for st in st_links if st.template_id]
        tmpl_map = {
            t.id: t.template_data
            for t in self.db.query(OrgTestTemplate).filter(OrgTestTemplate.id.in_(tmpl_ids)).all()
        }
        for st in st_links:
            if st.template_id and st.template_id in tmpl_map:
                stage_templates[st.stage_id] = tmpl_map[st.template_id]

        # Stage form data (instance_id → form_data)
        instance_ids = [i.id for i in instances]
        form_data_map: dict[UUID, dict] = {}
        for sd in self.db.query(RepairStageData).filter(RepairStageData.stage_instance_id.in_(instance_ids)).all():
            if sd.form_data:
                form_data_map[sd.stage_instance_id] = sd.form_data

        # Audit logs
        logs = (
            self.db.query(RepairStageAuditLog)
            .filter(RepairStageAuditLog.workflow_id == wf.id)
            .order_by(RepairStageAuditLog.performed_at)
            .all()
        )
        log_by_stage: dict[UUID, list] = {}
        for lg in logs:
            log_by_stage.setdefault(lg.stage_id, []).append(lg)

        # User cache
        all_user_ids = {i.completed_by for i in instances if i.completed_by} | \
                       {i.assigned_user_id for i in instances if i.assigned_user_id} | \
                       {lg.performed_by for lg in logs if lg.performed_by}
        users = {
            u.id: u
            for u in self.db.query(User).filter(User.id.in_(all_user_ids)).all()
        } if all_user_ids else {}

        def _uname(uid) -> str:
            if not uid: return "-"
            u = users.get(uid)
            if not u: return str(uid)[:8]
            return f"{u.firstname or ''} {u.lastname or ''}".strip() or u.email

        stages_out = []
        for inst in instances:
            sd = stage_defs.get(inst.stage_id)
            template = stage_templates.get(inst.stage_id)
            form_data = form_data_map.get(inst.id, {})
            stage_logs = log_by_stage.get(inst.stage_id, [])

            stages_out.append({
                "sequence":     sd.sequence if sd else 0,
                "name":         sd.name if sd else "Unknown",
                "code":         sd.code if sd else "",
                "status":       inst.status or "-",
                "assigned_to":  _uname(inst.assigned_user_id),
                "completed_by": _uname(inst.completed_by),
                "started_at":   self._fmt(inst.started_at),
                "completed_at": self._fmt(inst.completed_at),
                "remarks":      inst.remarks or "",
                "template":     template,   # full template JSON (sections/fields)
                "form_data":    form_data,  # submitted values {field_key: value}
                "logs": [
                    {
                        "action":       lg.action,
                        "performed_by": _uname(lg.performed_by),
                        "note":         lg.note or "",
                        "at":           self._fmt(lg.performed_at),
                    }
                    for lg in stage_logs
                ],
            })

        workflow_number = getattr(wf, "workflow_number", None) \
            or getattr(wf, "workflow_no", None) \
            or getattr(wf, "workflow_code", None) \
            or str(wf.id)

        workflow_code = getattr(wf, "workflow_code", "")

        workflow_label = WORKFLOW_LABEL.get(
            getattr(wf, "workflow_type", ""),
            getattr(wf, "workflow_type", "Repair Workflow")
        )

        status = getattr(wf, "status", "-")

        progress = getattr(wf, "progress", 0)

        priority = getattr(wf, "priority", None)

        created_at = self._fmt(getattr(wf, "created_at", None))

        generated_at = datetime.now().strftime("%d %b %Y %H:%M")

        stages = stages_out

        return {
            "workflow_number": wf.workflow_number or str(wf.id)[:8],
            "workflow_code":   wf.workflow_code or "",
            "workflow_label":  WORKFLOW_LABEL.get(wf.workflow_code or "", "Workflow Report"),
            "status":          (wf.status or "").upper(),
            "progress":        wf.progress or 0,
            "priority":        (wf.priority or "").capitalize(),
            "created_at":      self._fmt(wf.created_at),
            "equipment_name":  equip_name,
            "equipment_ueic":  equip_ueic,
            "equipment_capacity":       equip_capacity,
            "equipment_voltage_class":  equip_voltage_class,
            "equipment_voltage_ratio":  equip_voltage_ratio,
            "equipment_yom":            equip_yom,
            "stages":          stages_out,
            "generated_at":    datetime.now(timezone.utc).strftime("%d %b %Y  %H:%M UTC"),
        }

    @staticmethod
    def _fmt(dt) -> str:
        if dt is None:
            return "-"
        try:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%d %b %Y  %H:%M")
        except Exception:
            return str(dt)

    # ── PDF builder ────────────────────────────────────────────────────────────

    def _build_pdf(self, d: dict) -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=15 * mm, rightMargin=15 * mm,
            topMargin=15 * mm,  bottomMargin=15 * mm,
            title=f"{d['workflow_label']} – {d['workflow_number']}",
        )

        W = doc.width

        # ── Styles ────────────────────────────────────────────────────────────
        normal  = ParagraphStyle("n",  fontName="Helvetica",      fontSize=8,  leading=11)
        bold    = ParagraphStyle("b",  fontName="Helvetica-Bold", fontSize=8,  leading=11)
        small   = ParagraphStyle("s",  fontName="Helvetica",      fontSize=7,  leading=9,  textColor=GREY)
        white_b = ParagraphStyle("wb", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=WHITE)
        white_n = ParagraphStyle("wn", fontName="Helvetica",      fontSize=9,  leading=12, textColor=WHITE)
        section = ParagraphStyle("sc", fontName="Helvetica-Bold", fontSize=9,  leading=12, textColor=NAVY)
        subsec  = ParagraphStyle("ss", fontName="Helvetica-Bold", fontSize=8,  leading=11, textColor=BLUE)
        foot    = ParagraphStyle("ft", fontName="Helvetica",      fontSize=7,  leading=9,
                                 textColor=GREY, alignment=TA_CENTER)

        story = []

        # ── Header banner ──────────────────────────────────────────────────────
        hdr = Table([[
            Paragraph(d["workflow_label"], white_b),
            Paragraph(
                f"Workflow No: <b>{d['workflow_number']}</b><br/>"
                f"Status: {d['status']}  •  Progress: {d['progress']}%<br/>"
                f"Generated: {d['generated_at']}",
                white_n,
            ),
        ]], colWidths=[W * 0.55, W * 0.45])
        hdr.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), NAVY),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING",   (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 10),
        ]))
        story.append(hdr)
        story.append(Spacer(1, 4 * mm))

        # ── Equipment / meta ──────────────────────────────────────────────────
        meta = Table([[
            Paragraph(f"<b>Equipment</b><br/>{d['equipment_name']}", normal),
            Paragraph(f"<b>UEIC</b><br/>{d['equipment_ueic'] or '-'}", normal),
            Paragraph(f"<b>Priority</b><br/>{d['priority'] or '-'}", normal),
            Paragraph(f"<b>Created</b><br/>{d['created_at']}", normal),
        ]], colWidths=[W * 0.35, W * 0.2, W * 0.15, W * 0.3])
        meta.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), LIGHT),
            ("BOX",          (0, 0), (-1, -1), 0.5, GREY),
            ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#D1D5DB")),
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ]))
        story.append(meta)
        story.append(Spacer(1, 2 * mm))

        # ── Equipment nameplate row ────────────────────────────────────────────
        nameplate = Table([[
            Paragraph(f"<b>Capacity</b><br/>{d['equipment_capacity']}", normal),
            Paragraph(f"<b>Voltage Class</b><br/>{d['equipment_voltage_class']}", normal),
            Paragraph(f"<b>Voltage Ratio</b><br/>{d['equipment_voltage_ratio']}", normal),
            Paragraph(f"<b>Year of Mfg</b><br/>{d['equipment_yom']}", normal),
        ]], colWidths=[W * 0.25] * 4)
        nameplate.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), LIGHT),
            ("BOX",          (0, 0), (-1, -1), 0.5, GREY),
            ("GRID",         (0, 0), (-1, -1), 0.3, colors.HexColor("#D1D5DB")),
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ]))
        story.append(nameplate)
        story.append(Spacer(1, 5 * mm))

        # ── Stage summary table ────────────────────────────────────────────────
        story.append(Paragraph("STAGE SUMMARY", section))
        story.append(Spacer(1, 2 * mm))

        col_w = [8*mm, W*0.22, W*0.10, W*0.15, W*0.15, W*0.13, W*0.13]
        tbl_data = [[
            Paragraph("<b>#</b>", bold),
            Paragraph("<b>Stage</b>", bold),
            Paragraph("<b>Status</b>", bold),
            Paragraph("<b>Assigned To</b>", bold),
            Paragraph("<b>Completed By</b>", bold),
            Paragraph("<b>Started</b>", bold),
            Paragraph("<b>Completed</b>", bold),
        ]]
        for st in d["stages"]:
            hex_c = STATUS_COLOR_HEX.get(st["status"].lower(), "374151")
            name_p = f"<b>{st['name']}</b>"
            if st["remarks"]:
                name_p += f"<br/><font color='#6B7280' size='7'>{st['remarks'][:100]}</font>"
            tbl_data.append([
                Paragraph(str(st["sequence"]), normal),
                Paragraph(name_p, normal),
                Paragraph(f"<font color='#{hex_c}'><b>{st['status'].upper()}</b></font>", normal),
                Paragraph(st["assigned_to"], small),
                Paragraph(st["completed_by"], small),
                Paragraph(st["started_at"], small),
                Paragraph(st["completed_at"], small),
            ])
        summary_tbl = Table(tbl_data, colWidths=col_w, repeatRows=1)
        summary_tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0), NAVY),
            ("TEXTCOLOR",      (0, 0), (-1, 0), WHITE),
            ("FONTNAME",       (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",       (0, 0), (-1, -1), 7.5),
            ("GRID",           (0, 0), (-1, -1), 0.3, colors.HexColor("#D1D5DB")),
            ("VALIGN",         (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING",    (0, 0), (-1, -1), 5),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 5),
            ("TOPPADDING",     (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
        ]))
        story.append(summary_tbl)
        story.append(Spacer(1, 8 * mm))

        # ── Per-stage form data ────────────────────────────────────────────────
        for st in d["stages"]:
            template = st.get("template")
            form_data = st.get("form_data") or {}
            if not template or not form_data:
                continue

            block = []
            # Stage header
            hex_c = STATUS_COLOR_HEX.get(st["status"].lower(), "374151")
            block.append(Paragraph(
                f"<font color='#0F2B6B'>Stage {st['sequence']}: {st['name']}</font>  "
                f"<font color='#{hex_c}' size='7'>({st['status'].upper()})</font>",
                section,
            ))
            block.append(Spacer(1, 2 * mm))

            sections = template.get("sections", [])
            for sec in sections:
                sec_title = sec.get("title", "")
                fields = sec.get("fields", [])
                if not fields:
                    continue

                if sec_title:
                    block.append(Paragraph(sec_title, subsec))
                    block.append(Spacer(1, 1 * mm))

                for field in fields:
                    fkey   = field.get("key", "")
                    flabel = field.get("label", fkey)
                    ftype  = field.get("type", "text")
                    value  = form_data.get(fkey)

                    if value is None or value == "":
                        continue

                    if ftype == "table":
                        # Render as a sub-table
                        columns = field.get("columns", [])
                        if columns and isinstance(value, list) and value:
                            block.append(Paragraph(flabel, bold))
                            block.append(Spacer(1, 1 * mm))
                            col_labels = [c.get("label", c.get("key", "")) for c in columns]
                            col_keys   = [c.get("key", "") for c in columns]
                            n_cols = len(col_labels)
                            col_w_inner = [W / n_cols] * n_cols

                            inner_data = [[Paragraph(f"<b>{lbl}</b>", bold) for lbl in col_labels]]
                            for row in value:
                                if not isinstance(row, dict):
                                    continue
                                inner_data.append([
                                    Paragraph(str(row.get(k, "-")), normal) for k in col_keys
                                ])
                            inner_tbl = Table(inner_data, colWidths=col_w_inner, repeatRows=1)
                            inner_tbl.setStyle(TableStyle([
                                ("BACKGROUND",    (0, 0), (-1, 0), LIGHT2),
                                ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                                ("FONTSIZE",      (0, 0), (-1, -1), 7),
                                ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#BFDBFE")),
                                ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING",   (0, 0), (-1, -1), 4),
                                ("RIGHTPADDING",  (0, 0), (-1, -1), 4),
                                ("TOPPADDING",    (0, 0), (-1, -1), 3),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LIGHT]),
                            ]))
                            block.append(inner_tbl)
                            block.append(Spacer(1, 2 * mm))

                    elif ftype == "boolean":
                        val_str = "Yes" if value else "No"
                        block.append(Table(
                            [[Paragraph(flabel, bold), Paragraph(val_str, normal)]],
                            colWidths=[W * 0.35, W * 0.65],
                        ))

                    else:
                        # text / number / dropdown / textarea / date
                        val_str = str(value)
                        row_tbl = Table(
                            [[Paragraph(flabel, bold), Paragraph(val_str, normal)]],
                            colWidths=[W * 0.35, W * 0.65],
                        )
                        row_tbl.setStyle(TableStyle([
                            ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#E5E7EB")),
                            ("LEFTPADDING",   (0, 0), (-1, -1), 5),
                            ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
                            ("TOPPADDING",    (0, 0), (-1, -1), 3),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                            ("ROWBACKGROUNDS",(0, 0), (-1, -1), [WHITE, LIGHT]),
                        ]))
                        block.append(row_tbl)

                block.append(Spacer(1, 2 * mm))

            block.append(HRFlowable(width=W, thickness=0.3, color=GREY))
            block.append(Spacer(1, 4 * mm))
            story.append(KeepTogether(block[:6]))  # keep stage header + first few fields together
            story.extend(block[6:])

        # ── Audit trail ───────────────────────────────────────────────────────
        has_logs = any(st["logs"] for st in d["stages"])
        if has_logs:
            story.append(Paragraph("AUDIT TRAIL", section))
            story.append(Spacer(1, 2 * mm))
            audit_w = [W * 0.22, 22 * mm, W * 0.18, W * 0.35]
            audit_data = [[
                Paragraph("<b>Stage</b>", bold),
                Paragraph("<b>Action</b>", bold),
                Paragraph("<b>By</b>", bold),
                Paragraph("<b>Note</b>", bold),
            ]]
            for st in d["stages"]:
                for lg in st["logs"]:
                    audit_data.append([
                        Paragraph(st["name"], small),
                        Paragraph(f"<b>{lg['action'].upper()}</b>", small),
                        Paragraph(lg["performed_by"], small),
                        Paragraph(lg["note"][:200] if lg["note"] else "-", small),
                    ])
            if len(audit_data) > 1:
                audit_tbl = Table(audit_data, colWidths=audit_w, repeatRows=1)
                audit_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, 0), NAVY),
                    ("TEXTCOLOR",     (0, 0), (-1, 0), WHITE),
                    ("FONTNAME",      (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE",      (0, 0), (-1, -1), 7),
                    ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#D1D5DB")),
                    ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
                    ("TOPPADDING",    (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LIGHT]),
                ]))
                story.append(audit_tbl)

        # ── Footer ────────────────────────────────────────────────────────────
        story.append(Spacer(1, 6 * mm))
        story.append(HRFlowable(width=W, thickness=0.5, color=GREY))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(
            f"CogniWatt Nexus  •  {d['workflow_label']}  •  {d['workflow_number']}  •  {d['generated_at']}",
            foot,
        ))

        doc.build(story)
        buf.seek(0)
        return buf.read()
