import datetime
from sqlalchemy.orm import Session
from models import RepairWorkflow, OrgDepartment
from services.repair_report_service import RepairWorkflowReportService
from services.nameplate_helper import resolve_capacity, resolve_voltage_ratio


class RepairWorkflowHTMLService:
    """Generate styled HTML reports for repair workflows."""

    def __init__(self, db: Session):
        self.db = db

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _table_eval_value(field: dict) -> str:
        """
        For a table-type evaluation field, derive a human-readable value string
        from column_results — showing actual measured values per flagged column.
        Falls back to aggregate_result, then '—'.
        """
        agg = field.get("aggregate_result")
        if agg is not None:
            return str(agg)

        col_results = field.get("column_results") or []
        flagged = [r for r in col_results if r.get("status") in ("ALERT", "CRITICAL")]
        source = flagged if flagged else col_results
        if not source:
            return "—"

        # Group values by column key
        by_col: dict = {}
        for r in source:
            col = r.get("column", "")
            val = r.get("value")
            if val is not None:
                by_col.setdefault(col, []).append(val)

        if not by_col:
            return "—"

        parts = []
        for col, vals in by_col.items():
            label = " ".join(w.capitalize() for w in col.split("_"))
            vals_str = ", ".join(str(v) for v in vals)
            parts.append(f"{label}: {vals_str}")
        return "<br>".join(parts)

    @staticmethod
    def _fmt(v) -> str:
        """Render any value to safe HTML."""
        if v is None or v == "":
            return "—"
        if isinstance(v, list) and v and isinstance(v[0], dict):
            cols = list(v[0].keys())
            header = "".join(
                f"<th style='padding:4px 8px;background:#e8f0fe;color:#1b3a6b;"
                f"font-size:11px;white-space:normal;word-break:break-word'>{c.replace('_',' ').title()}</th>"
                for c in cols
            )
            rows = ""
            for row in v:
                cells = "".join(
                    f"<td style='padding:4px 8px;border:1px solid #e0e0e0;font-size:11px;white-space:normal;word-break:break-word'>"
                    f"{row.get(c, '—') if row.get(c) not in (None, '') else '—'}</td>"
                    for c in cols
                )
                rows += f"<tr>{cells}</tr>"
            return (
                f"<table style='border-collapse:collapse;width:100%;margin:2px 0'>"
                f"<tr>{header}</tr>{rows}</table>"
            )
        if isinstance(v, list):
            return ", ".join(str(i) for i in v) if v else "—"
        if isinstance(v, dict):
            rows = "".join(
                f"<tr>"
                f"<td style='padding:3px 8px;color:#555;font-size:11px;white-space:normal;word-break:break-word'>"
                f"{k.replace('_',' ').title()}</td>"
                f"<td style='padding:3px 8px;font-size:11px'>"
                f"{v2 if v2 not in (None, '') else '—'}</td></tr>"
                for k, v2 in v.items()
            )
            return f"<table style='border-collapse:collapse;margin:2px 0'>{rows}</table>"
        return str(v)

    @staticmethod
    def _split(td: dict):
        """Split test_data into (scalars, table_fields, overall_result)."""
        scalars, tables, overall = {}, {}, None
        for k, v in td.items():
            if k == "overall_result":
                overall = str(v).upper() if v else None
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                tables[k] = v
            else:
                scalars[k] = v
        return scalars, tables, overall

    @staticmethod
    def _css() -> str:
        return """
        body{font-family:Arial,sans-serif;margin:0;padding:20px;color:#333;background:#f9f9f9}
        .header{background:#1b3a6b;color:white;padding:20px 24px;border-radius:10px 10px 0 0}
        .header h1{margin:0;font-size:20px}
        .header p{margin:6px 0 0;font-size:13px;opacity:.8}
        .body{
            background:white;
            padding:20px 24px;
            border-radius:0 0 10px 10px;
            box-shadow:0 2px 8px rgba(0,0,0,.1);
            width:100%;
            max-width:100%;
            overflow-x:auto;
            box-sizing:border-box;
        }

        .meta-item label{color:#666;font-size:12px;display:block;margin-bottom:3px}
        .meta-item span{font-size:14px;font-weight:600}
        .section-title{font-size:15px;font-weight:700;color:#1b3a6b;border-bottom:2px solid #e8f0fe;
          padding-bottom:6px;margin:20px 0 12px}
        table.data{
            width:100%;
            border-collapse:collapse;
            margin:10px 0;
            font-size:13px;
            table-layout:auto;
        }

        table.data th{
            background:#1b3a6b;
            color:white;
            padding:8px 10px;
            text-align:left;
            border:1px solid #d0d7e2;
        }

        table.data td{
            padding:8px 10px;
            border:1px solid #d0d7e2;
            vertical-align:top;
            white-space: normal;
            overflow-wrap: anywhere;
            word-break: break-word;
        }

        table.data tr:nth-child(even){
            background:#f5f8ff;
        }
        .footer{margin-top:24px;font-size:11px;color:#aaa;text-align:center}
        .np-item label{color:#555;font-size:10px;display:block;margin-bottom:2px;
          font-weight:700;text-transform:uppercase;letter-spacing:.4px}
        .np-item span{
            font-size:13px;
            font-weight:700;
            color:#1b3a6b;
        }

        h3{
            margin:18px 0 8px;
            color:#1b3a6b;
        }

        h4{
            margin:10px 0 6px;
            color:#444;
        }

        p{
            margin:4px 0;
        }
        """

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def _nameplate_header_html(self, data) -> str:
        eq = data.get('equipment')
        np = (eq.nameplate_data or {}) if eq else {}
        fallback = {}
        voltage  = (eq.voltage_class if eq else '') or '—'
        capacity = resolve_capacity(np, fallback, blank='—')
        v_ratio  = resolve_voltage_ratio(np, fallback, voltage_class=eq.voltage_class if eq else None, blank='—')

        station = (data.get('department_name') if data.get('department_name') else '') or '—'
        serial  = (eq.factory_serial_number if eq else '') or '—'
        make    = (eq.manufacturer if eq else '') or '—'
        yom     = str(eq.year_of_manufacture) if eq and eq.year_of_manufacture else '—'
        ueic    = (eq.ueic if eq else '') or '—'
        doc     = '—'
        if eq and eq.commissioned_date:
            doc = eq.commissioned_date.strftime('%d-%b-%y')

        ssmd = zone = '—'
        if data.get('department_name'):
            parent = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == data.get('parent_department_id')).first()
            if parent:
                ssmd = parent.name or '—'
                if parent.parent_department_id:
                    gp = self.db.query(OrgDepartment).filter(
                        OrgDepartment.id == parent.parent_department_id).first()
                    zone = (gp.name if gp else '—') or '—'

        def _cell(label, value):
            return (
                '<div class="np-item">'
                '<label>' + label + '</label>'
                '<span>' + str(value) + '</span>'
                '</div>'
            )

        return (
            '<div class="np-grid">'
            + _cell('Name Of Station', station)
            + _cell('Capacity', capacity)
            + _cell('Serial Number', serial)
            + _cell('SSMD', ssmd)
            + _cell('Voltage Class', voltage)
            + _cell('Date Of Commission', doc)
            + _cell('Zone', zone)
            + _cell('Make', make)
            + _cell('YOM', yom)
            + _cell('UEIC', ueic)
            + _cell('Voltage Ratio', v_ratio)
            + '</div>'
        )

    def generate_html(self, request_id: str) -> str:
        workflow = (
            self.db.query(RepairWorkflow)
            .filter(RepairWorkflow.id == request_id)
            .first()
        )
        if not workflow:
            raise ValueError("Workflow not found")

        data = RepairWorkflowReportService(self.db)._collect(workflow)
        now_str = datetime.datetime.now().strftime("%d %b %Y %H:%M")
        nameplate_html = self._nameplate_header_html(data)

        meta_html = f"""
        <table class="data" style="margin-bottom:20px">
        <tr>
            <th>Workflow #</th>
            <td>{data["workflow_number"]}</td>
        </tr>
        <tr>
            <th>Equipment</th>
            <td>{data["equipment_name"]}</td>
        </tr>
        <tr>
            <th>Status</th>
            <td>{data["status"]}</td>
        </tr>
        <tr>
            <th>Workflow</th>
            <td>{data["workflow_label"]}</td>
        </tr>
        </table>
        """

        rows = ""

        for i, stage in enumerate(data["stages"], start=1):
            rows += f"""
            <tr>
                <td>{i}</td>
                <td>
                    <b>{stage.get('name','-')}</b><br>
                    <small>{stage.get('remarks') or '-'}</small>
                </td>
                <td>{stage.get('status','-')}</td>
                <td>{stage.get('assigned_to','-')}</td>
                <td>{stage.get('completed_by','-')}</td>
                <td>{stage.get('started_at','-')}</td>
                <td>{stage.get('completed_at','-')}</td>
            </tr>
            """

        body_sections = f'''
        <div class="section-title">Workflow Stages</div>
        <table class="data">
        <thead>
        <tr>
            <th>#</th>
            <th>Stage</th>
            <th>Status</th>
            <th>Assigned To</th>
            <th>Completed By</th>
            <th>Started</th>
            <th>Completed</th>
        </tr>
        </thead>
        <tbody>{rows}</tbody>
        </table>
        '''

        # -----------------------------------------------------------------
        # Stage form data (same concept as PDF)
        # -----------------------------------------------------------------

        for stage in data["stages"]:
            template = stage.get("template")
            form_data = stage.get("form_data") or {}

            if not template or not form_data:
                continue

            body_sections += f"""
            <div class="section-title">
                Stage {stage['sequence']} : {stage['name']}
                ({stage['status']})
            </div>
            """

            for section in template.get("sections", []):

                if section.get("title"):
                    body_sections += f"<h3>{section['title']}</h3>"

                for field in section.get("fields", []):

                    key = field.get("key")
                    label = field.get("label", key)
                    ftype = field.get("type", "text")

                    value = form_data.get(key)
                    

                    if value in (None, "", []):
                        continue
                    print("=" * 80)
                    print("Stage:", stage["name"])
                    print("Form Data Keys:", list(form_data.keys()))
                    print("Template Keys:", [f.get("key") for f in section.get("fields", [])])
                    print("=" * 80)

                    if ftype == "table":
                        body_sections += f"""
                        <h4>{label}</h4>
                        {self._fmt(value)}
                        """
                    else:
                        body_sections += f"""
                        <table class="data" style="margin-bottom:10px">
                        <tr>
                            <th style="width:35%">{label}</th>
                            <td>{self._fmt(value)}</td>
                        </tr>
                        </table>
                        """

        has_logs = any(stage.get("logs") for stage in data["stages"])

        if has_logs:

            body_sections += """
            <div class="section-title">Audit Trail</div>

            <table class="data">
            <thead>
            <tr>
                <th>Stage</th>
                <th>Action</th>
                <th>Performed By</th>
                <th>Note</th>
            </tr>
            </thead>
            <tbody>
            """

            for stage in data["stages"]:
                for log in stage.get("logs", []):

                    body_sections += f"""
                    <tr>
                        <td>{stage['name']}</td>
                        <td>{log['action']}</td>
                        <td>{log['performed_by']}</td>
                        <td>{log['note'] or '-'}</td>
                    </tr>
                    """

            body_sections += """
            </tbody>
            </table>
            """
        
        return f'''<!DOCTYPE html>
    <html>
    <head>
    <meta charset="utf-8">
    <title>Workflow Report — {data["workflow_number"]}</title>
    <style>{self._css()}</style>
    </head>
    <body>
    <div class="header">
    <h1>{data["workflow_label"]}</h1>
    <p>Workflow No: {data["workflow_number"]}</p>
    </div>
    <div class="body">
    {nameplate_html}
    {meta_html}
    {body_sections}
    <div class="footer">Generated by SEACMS | {now_str}</div>
    </div>
    </body>
    </html>'''
