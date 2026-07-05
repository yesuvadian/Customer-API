import datetime
from sqlalchemy.orm import Session, joinedload
from models import TestingRequest, TestResult, OrgDepartment


class TestingRequestHTMLService:
    """Generate styled HTML reports for testing requests — fully generic."""

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
        return " | ".join(parts)

    @staticmethod
    def _fmt(v) -> str:
        """Render any value to safe HTML."""
        if v is None or v == "":
            return "—"
        if isinstance(v, list) and v and isinstance(v[0], dict):
            cols = list(v[0].keys())
            header = "".join(
                f"<th style='padding:4px 8px;background:#e8f0fe;color:#1b3a6b;"
                f"font-size:11px;white-space:nowrap'>{c.replace('_',' ').title()}</th>"
                for c in cols
            )
            rows = ""
            for row in v:
                cells = "".join(
                    f"<td style='padding:4px 8px;border:1px solid #e0e0e0;font-size:11px'>"
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
                f"<td style='padding:3px 8px;color:#555;font-size:11px;white-space:nowrap'>"
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
        .body{background:white;padding:20px 24px;border-radius:0 0 10px 10px;box-shadow:0 2px 8px rgba(0,0,0,.1)}
        .meta-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:20px}
        .meta-item label{color:#666;font-size:12px;display:block;margin-bottom:3px}
        .meta-item span{font-size:14px;font-weight:600}
        .section-title{font-size:15px;font-weight:700;color:#1b3a6b;border-bottom:2px solid #e8f0fe;
          padding-bottom:6px;margin:20px 0 12px}
        table.data{width:100%;border-collapse:collapse;font-size:13px}
        table.data th{background:#1b3a6b;color:white;padding:8px 10px;text-align:left}
        table.data tr:nth-child(even){background:#f5f8ff}
        .footer{margin-top:24px;font-size:11px;color:#aaa;text-align:center}
        .np-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:16px;
          background:#eef2fb;padding:12px 16px;border-radius:8px;border:1px solid #c5d3f0}
        .np-item label{color:#555;font-size:10px;display:block;margin-bottom:2px;
          font-weight:700;text-transform:uppercase;letter-spacing:.4px}
        .np-item span{font-size:13px;font-weight:700;color:#1b3a6b}
        """

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def _nameplate_header_html(self, req) -> str:
        eq = req.equipment
        np = (eq.nameplate_data or {}) if eq else {}
        capacity = (
            np.get('rated_mva') or np.get('capacity_mva') or np.get('mva_rating') or
            np.get('rated_capacity') or np.get('capacity') or np.get('kva_rating') or ''
        )
        if capacity and 'MVA' not in str(capacity).upper() and 'KVA' not in str(capacity).upper():
            capacity = str(capacity) + ' MVA'

        station = (req.department.name if req.department else '') or '—'
        serial  = (eq.factory_serial_number if eq else '') or '—'
        make    = (eq.manufacturer if eq else '') or '—'
        yom     = str(eq.year_of_manufacture) if eq and eq.year_of_manufacture else '—'
        voltage = (eq.voltage_class if eq else '') or '—'
        doc     = '—'
        if eq and eq.commissioned_date:
            doc = eq.commissioned_date.strftime('%d-%b-%y')
        capacity = str(capacity) if capacity else '—'

        ssmd = zone = '—'
        if req.department and req.department.parent_department_id:
            parent = self.db.query(OrgDepartment).filter(
                OrgDepartment.id == req.department.parent_department_id).first()
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
            + '</div>'
        )

    def generate_html(self, request_id: str) -> str:
        req = (
            self.db.query(TestingRequest)
            .options(
                joinedload(TestingRequest.equipment_type),
                joinedload(TestingRequest.test_type),
                joinedload(TestingRequest.department),
                joinedload(TestingRequest.equipment),
            )
            .filter(TestingRequest.id == request_id)
            .first()
        )
        if not req:
            raise ValueError(f"Testing request {request_id} not found")

        result = (
            self.db.query(TestResult)
            .filter(TestResult.testing_request_id == req.id)
            .order_by(TestResult.cts.desc())
            .first()
        )

        req_num = req.request_number or "—"
        eq_name = (req.equipment_type.name if req.equipment_type else "") or "—"
        status_str = (str(req.status.value) if req.status else "—").replace("_", " ").upper()

        tested_str = "—"
        if result and result.tested_at:
            tested_str = result.tested_at.strftime("%d %b %Y %H:%M")
        elif req.scheduled_start_date:
            tested_str = req.scheduled_start_date.strftime("%d %b %Y")

        now_str = datetime.datetime.now().strftime("%d %b %Y %H:%M")

        nameplate_html = self._nameplate_header_html(req)

        meta_html = f"""
        <div class="meta-grid">
          <div class="meta-item"><label>Request #</label><span>{req_num}</span></div>
          <div class="meta-item"><label>Equipment</label><span>{eq_name}</span></div>
          <div class="meta-item"><label>Status</label><span>{status_str}</span></div>
          <div class="meta-item"><label>Tested At</label><span>{tested_str}</span></div>
        </div>"""

        body_sections = ""

        if result and result.test_data:
            scalars, tables, overall = self._split(result.test_data)

            if scalars or overall:
                kv_rows = "".join(
                    f"<tr>"
                    f"<td style='padding:6px 10px;border:1px solid #e0e0e0;color:#555;"
                    f"font-size:12px;width:35%'>{k.replace('_',' ').title()}</td>"
                    f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:13px'>"
                    f"{self._fmt(v)}</td></tr>"
                    for k, v in scalars.items()
                )
                if overall:
                    o_color = "#1a7340" if overall == "PASS" else "#b71c1c" if overall == "FAIL" else "#555"
                    o_bg = "#e8f5e9" if overall == "PASS" else "#ffebee" if overall == "FAIL" else "#f5f5f5"
                    kv_rows += (
                        f"<tr><td style='padding:6px 10px;border:1px solid #e0e0e0;color:#555;"
                        f"font-size:12px;font-weight:700'>Overall Result</td>"
                        f"<td style='padding:6px 10px;border:1px solid #e0e0e0;background:{o_bg};"
                        f"color:{o_color};font-weight:700'>{overall}</td></tr>"
                    )
                body_sections += (
                    '<div class="section-title">Test Data</div>'
                    '<table class="data"><thead><tr><th>Field</th><th>Value</th></tr></thead>'
                    f'<tbody>{kv_rows}</tbody></table>'
                )

            for field_key, rows in tables.items():
                cols = list(rows[0].keys())
                header = "".join(f"<th>{c.replace('_',' ').title()}</th>" for c in cols)
                trows = "".join(
                    "<tr>" + "".join(
                        f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:12px'>"
                        f"{row.get(c, '—') if row.get(c) not in (None, '') else '—'}</td>"
                        for c in cols
                    ) + "</tr>"
                    for row in rows
                )
                body_sections += (
                    f'<div class="section-title">{field_key.replace("_"," ").title()}</div>'
                    f'<table class="data"><thead><tr>{header}</tr></thead>'
                    f'<tbody>{trows}</tbody></table>'
                )

        if result and result.testing_kit_id and result.testing_kit:
            kit = result.testing_kit
            np = kit.nameplate_data or {}
            kit_type = np.get("kit_subtype") or kit.bay_number or (kit.equipment_type.name if kit.equipment_type else "Testing Kit")
            kit_loc = kit.department.name if kit.department else "—"
            body_sections += (
                '<div class="section-title">Testing Kit Used</div>'
                '<table class="data"><tbody>'
                f"<tr><td style='padding:6px 10px;border:1px solid #e0e0e0;color:#555;font-size:12px;width:35%'>UEIC</td>"
                f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:13px'>{kit.ueic or '—'}</td></tr>"
                f"<tr><td style='padding:6px 10px;border:1px solid #e0e0e0;color:#555;font-size:12px'>Kit Type</td>"
                f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:13px'>{kit_type}</td></tr>"
                f"<tr><td style='padding:6px 10px;border:1px solid #e0e0e0;color:#555;font-size:12px'>Manufacturer</td>"
                f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:13px'>{kit.manufacturer or '—'}</td></tr>"
                f"<tr><td style='padding:6px 10px;border:1px solid #e0e0e0;color:#555;font-size:12px'>Model Number</td>"
                f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:13px'>{kit.model_number or '—'}</td></tr>"
                f"<tr><td style='padding:6px 10px;border:1px solid #e0e0e0;color:#555;font-size:12px'>Serial Number</td>"
                f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:13px'>{kit.factory_serial_number or '—'}</td></tr>"
                f"<tr><td style='padding:6px 10px;border:1px solid #e0e0e0;color:#555;font-size:12px'>Location</td>"
                f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:13px'>{kit_loc}</td></tr>"
                '</tbody></table>'
            )

        if result and result.evaluation_result:
            er = result.evaluation_result
            fields = er.get("fields", [])
            if fields:
                eval_rows = ""
                for field in fields:
                    s = (field.get("status") or "").lower()
                    s_clr = "#1a7340" if s == "normal" else "#b71c1c" if s == "critical" else "#c75b00"
                    if field.get("type") == "table":
                        val = self._table_eval_value(field)
                    else:
                        raw_val = field.get("value")
                        unit = (field.get("unit") or "").strip()
                        val = f"{raw_val} {unit}".strip() if raw_val is not None else "—"
                    eval_rows += (
                        f"<tr>"
                        f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:12px'>"
                        f"{field.get('label', field.get('key', ''))}</td>"
                        f"<td style='padding:6px 10px;border:1px solid #e0e0e0;font-size:13px'>{val}</td>"
                        f"<td style='padding:6px 10px;border:1px solid #e0e0e0;color:{s_clr};font-weight:600'>"
                        f"{s.upper() if s else '—'}</td></tr>"
                    )
                body_sections += (
                    '<div class="section-title">Evaluation</div>'
                    '<table class="data"><thead><tr><th>Parameter</th><th>Value</th><th>Status</th></tr></thead>'
                    f'<tbody>{eval_rows}</tbody></table>'
                )

        return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Test Report — {req_num}</title>
  <style>{self._css()}</style>
</head>
<body>
  <div class="header">
    <h1>Test Report — {req_num}</h1>
    <p>Equipment: {eq_name}</p>
  </div>
  <div class="body">
    {nameplate_html}
    {meta_html}
    {body_sections if body_sections else "<p style='color:#888'>No test data available.</p>"}
    <div class="footer">Generated by SEACMS &nbsp;|&nbsp; {now_str}</div>
  </div>
</body>
</html>"""
