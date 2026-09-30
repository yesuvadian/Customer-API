"""
Reporting Service
=================
Generic report engine: 14 SRS reports = 14 query_key values, not 14 code paths.

Flow
----
  1.  Router calls ReportingService.generate(definition_id, params, format, user_id)
  2.  Service fetches the ReportDefinition row -> reads query_key
  3.  _run_query() dispatches to the matching SQL function -> list[dict]
  4.  _render_excel() or _render_pdf() converts to bytes (in-memory, no disk I/O)
  5.  Router returns Response(content=bytes, media_type=...)
  6.  ReportLog row is written for audit trail

All queries are org-scoped when org_id is provided.
"""

from __future__ import annotations

import io
import os
import re
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import text

from models import ReportDefinition, ReportLog

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "reports")

# ── Optional rendering deps ────────────────────────────────────────────────

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    _HAS_OPENPYXL = True
except ImportError:
    _HAS_OPENPYXL = False

try:
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    _HAS_REPORTLAB = True
except ImportError:
    _HAS_REPORTLAB = False


# ── Helpers ────────────────────────────────────────────────────────────────

def _p(params: dict, key: str, default=None):
    v = params.get(key, default)
    return v if v not in (None, "", "null") else default


def _date(val) -> Optional[date]:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    try:
        return date.fromisoformat(str(val)[:10])
    except Exception:
        return None


def _org_clause(org_id, alias: str = "tr") -> str:
    return f" AND {alias}.organization_id = '{org_id}'" if org_id else ""


# How each report query alias reaches a department, for department-scoped
# users (see ReportingService._scope). Aliases are the ones the built-in
# queries and the ReportQueryKey.sql_template rows use:
#   "direct"  — the aliased table has its own department_id
#   "via_tr"  — table has testing_request_id → testing_requests.department_id
#   "via_eq"  — table has equipment_id       → equipment.department_id
_ALIAS_DEPT_LINK = {
    "tr":  "direct",   # testing_requests
    "fr":  "direct",   # testing_requests (failure_resolution_report)
    "e":   "direct",   # equipment
    "ea":  "direct",   # equipment_analytics
    "tai": "direct",   # taqc_annual_inspections
    "res": "via_tr",   # test_results
    "rec": "via_tr",   # recommendations
    "pr":  "via_tr",   # procurement_requests
    "wf":  "via_eq",   # repair_workflows
    "s":   "direct",   # test_request_schedules (missed_schedules_report)
    "car": "direct",   # corrective_action_requests (open_car_report)
    "pc":  "direct",   # precommission_requests (vendor_performance_report; dept_id exposed as department_id)
}


# ══════════════════════════════════════════════════════════════════════════
# ReportingService
# ══════════════════════════════════════════════════════════════════════════

class ReportingService:

    def __init__(self, db: Session, org_id: Optional[UUID] = None,
                 dept_ids: Optional[list] = None):
        self.db = db
        self.org_id = org_id
        # Department subtree the caller may see; None = no department
        # restriction (org admins, scheduled jobs). Set by routers/reporting.py
        # from the logged-in user's own department scope.
        self.dept_ids = [str(d) for d in dept_ids] if dept_ids else None

    def _scope(self, alias: str) -> str:
        """Org clause plus, for a department-scoped caller, a restriction of
        `alias`'s rows to the caller's department subtree. Fails closed: an
        alias with no known department link raises rather than silently
        returning every department's rows."""
        clause = _org_clause(self.org_id, alias)
        if not self.dept_ids:
            return clause
        ids = ", ".join(f"'{UUID(d)}'" for d in self.dept_ids)   # UUID() validates
        link = _ALIAS_DEPT_LINK.get(alias)
        if link == "direct":
            return clause + f" AND {alias}.department_id IN ({ids})"
        if link == "via_tr":
            return clause + (f" AND {alias}.testing_request_id IN (SELECT id FROM "
                             f"public.testing_requests WHERE department_id IN ({ids}))")
        if link == "via_eq":
            return clause + (f" AND {alias}.equipment_id IN (SELECT id FROM "
                             f"public.equipment WHERE department_id IN ({ids}))")
        raise ValueError(
            f"This report can't be limited to your department yet (alias '{alias}'). "
            f"Ask an org admin to run it."
        )

    # ── Public ─────────────────────────────────────────────────────────────

    def list_definitions(self, active_only: bool = True) -> list[ReportDefinition]:
        q = self.db.query(ReportDefinition)
        if active_only:
            q = q.filter(ReportDefinition.is_active.is_(True))
        if self.org_id:
            q = q.filter(
                (ReportDefinition.organization_id == self.org_id)
                | ReportDefinition.organization_id.is_(None)
            )
        return q.order_by(ReportDefinition.name).all()

    def get_definition(self, definition_id: UUID) -> Optional[ReportDefinition]:
        return self.db.query(ReportDefinition).filter_by(id=definition_id).first()

    def list_logs(
        self,
        definition_id: Optional[UUID] = None,
        limit: int = 50,
    ) -> list[ReportLog]:
        q = self.db.query(ReportLog)
        if definition_id:
            q = q.filter(ReportLog.definition_id == definition_id)
        if self.org_id:
            q = q.filter(ReportLog.organization_id == self.org_id)
        return q.order_by(ReportLog.cts.desc()).limit(limit).all()

    def create_definition(self, data: dict, user_id: Optional[UUID] = None) -> ReportDefinition:
        defn = ReportDefinition(
            organization_id = self.org_id,
            name            = data["name"],
            description     = data.get("description"),
            query_key       = data["query_key"],
            parameters      = data.get("parameters", {}),
            output_format   = data.get("output_format", "excel"),
            frequency       = data.get("frequency", "on_demand"),
            recipient_roles = data.get("recipient_roles", []),
            is_active       = True,
            is_system       = False,
            created_by      = user_id,
        )
        self.db.add(defn)
        self.db.commit()
        self.db.refresh(defn)
        return defn

    def update_definition(self, definition_id: UUID, data: dict,
                          user_id: Optional[UUID] = None) -> ReportDefinition:
        defn = self.get_definition(definition_id)
        if not defn:
            raise ValueError("Not found")
        for field in ("name", "description", "parameters", "output_format",
                      "frequency", "recipient_roles", "is_active"):
            if field in data:
                setattr(defn, field, data[field])
        defn.modified_by = user_id
        self.db.commit()
        self.db.refresh(defn)
        return defn

    def delete_definition(self, definition_id: UUID,
                          user_id: Optional[UUID] = None) -> None:
        """Soft delete (is_active=False): ReportLog rows cascade on a hard
        delete, which would wipe the report's generation history. Inactive
        definitions already drop out of list_definitions and the scheduler.
        System definitions and other organisations' definitions are refused.
        """
        defn = self.get_definition(definition_id)
        if not defn or not defn.is_active:
            raise ValueError("Not found")
        if defn.is_system:
            raise PermissionError("System report definitions cannot be deleted")
        if self.org_id and defn.organization_id != self.org_id:
            raise PermissionError("Report definition belongs to another organisation")
        defn.is_active = False
        defn.modified_by = user_id
        self.db.commit()

    def generate(
        self,
        definition_id: UUID,
        parameters: dict,
        output_format: str,          # "excel" | "pdf"
        user_id: Optional[UUID] = None,
    ) -> tuple[bytes, str, str]:
        """Returns (raw_bytes, filename, content_type)."""
        defn = self.get_definition(definition_id)
        if not defn:
            raise ValueError(f"ReportDefinition {definition_id} not found")

        log = ReportLog(
            definition_id   = definition_id,
            organization_id = self.org_id,
            generated_by    = user_id,
            parameters_used = parameters,
            output_format   = output_format,
            status          = "generating",
            started_at      = datetime.now(timezone.utc),
        )
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)

        try:
            rows = self._run_query(defn.query_key, parameters)
            ts        = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            safe_name = defn.name.replace(" ", "_").replace("/", "-")

            if output_format == "pdf":
                raw, content_type = self._render_pdf(rows, defn)
                filename = f"{safe_name}_{ts}.pdf"
            else:
                raw, content_type = self._render_excel(rows, defn)
                filename = f"{safe_name}_{ts}.xlsx"

            os.makedirs(REPORTS_DIR, exist_ok=True)
            with open(os.path.join(REPORTS_DIR, filename), "wb") as f:
                f.write(raw)

            log.status       = "completed"
            log.file_name    = filename
            log.file_size    = len(raw)
            log.row_count    = len(rows)
            log.completed_at = datetime.now(timezone.utc)
            defn.last_generated_at = datetime.now(timezone.utc)
            self.db.commit()

        except Exception as exc:
            # A failed SQL statement leaves the transaction aborted — roll it
            # back first, or recording the failure itself raises
            # InFailedSqlTransaction and the caller gets a bare 500 instead
            # of the real reason.
            self.db.rollback()
            log = self.db.get(ReportLog, log.id) or log
            log.status        = "failed"
            log.error_message = str(exc)[:2000]
            log.completed_at  = datetime.now(timezone.utc)
            self.db.commit()
            if isinstance(exc, (ValueError, RuntimeError)):
                raise
            # Database/other errors → RuntimeError, which routers/reporting.py
            # returns as a readable 422 rather than an unhandled 500.
            first_line = str(exc).split("\n")[0]
            raise RuntimeError(f"Report '{defn.name}' failed: {first_line}") from exc

        return raw, filename, content_type

    # ── Query dispatcher ───────────────────────────────────────────────────

    def _run_query(self, query_key: str, params: dict) -> list[dict]:
        registry = {
            "equipment_condition_summary":    self._q_equipment_condition,
            "overdue_tests_report":           self._q_overdue_tests,
            "active_alerts_report":           self._q_active_alerts,
            "flagged_equipment_report":       self._q_flagged_equipment,
            "repair_progress_report":         self._q_repair_progress,
            "maintenance_overdue_report":     self._q_maintenance_overdue,
            "procurement_pipeline_report":    self._q_procurement_pipeline,
            "open_remediation_report":        self._q_open_remediation,
            "testing_request_status_report":  self._q_testing_request_status,
            "test_results_summary_report":    self._q_test_results_summary,
            "recommendation_approval_report": self._q_recommendation_approval,
            "compliance_status_report":       self._q_compliance_status,
            "tester_performance_report":          self._q_tester_performance,
            "monthly_kpi_report":                 self._q_monthly_kpi,
            "dga_trend_report":                   self._q_dga_trend_report,
            # Reports mirroring Notification Center topics whose logic lives
            # in Python (not expressible as one sql_template).
            "workflow_stage_delays_report":       self._q_workflow_stage_delays,
            "kit_calibration_due_report":         self._q_kit_calibration_due,
            "deterioration_watch_report":         self._q_deterioration_watch,
        }
        fn = registry.get(query_key)
        if fn:
            return fn(params)
        return self._run_dynamic_query(query_key, params)

    def _run_dynamic_query(self, query_key: str, params: dict) -> list[dict]:
        """
        Fallback for any query_key not hardcoded above: execute the
        ReportQueryKey.sql_template directly. This is the architecture the
        model docstring describes — "adding a new report type = one new
        row here, zero Python code change" — previously unimplemented.
        """
        from models import ReportQueryKey
        qk = (
            self.db.query(ReportQueryKey)
            .filter_by(key=query_key, is_active=True)
            .first()
        )
        if not qk or not qk.sql_template:
            raise ValueError(f"Unknown query_key: '{query_key}'")

        if qk.org_alias:
            org_clause = self._scope(qk.org_alias)
        elif self.dept_ids:
            # No alias to hang a department filter on — fail closed.
            raise ValueError("This report can't be limited to your department yet. "
                             "Ask an org admin to run it.")
        else:
            org_clause = ""
        sql = qk.sql_template.replace("{org_clause}", org_clause)
        # SQLAlchemy's text() bind-parameter tokenizer misreads ":name::type"
        # (no space) as a syntax error — insert a space so the Postgres cast
        # stays semantically identical but parses correctly.
        sql = re.sub(r"(:\w+)::", r"\1 ::", sql)

        bind = {}
        for pname, ptype in (qk.parameters_schema or {}).items():
            raw = _p(params, pname)
            if ptype == "date":
                bind[pname] = _date(raw)
            elif ptype == "int" and raw is not None:
                bind[pname] = int(raw)
            else:
                bind[pname] = raw

        result = self.db.execute(text(sql), bind)
        keys = list(result.keys())
        return [dict(zip(keys, row)) for row in result.fetchall()]

    # ── 14 Query Functions ─────────────────────────────────────────────────

    def _q_equipment_condition(self, p: dict) -> list[dict]:
        org = self._scope("e")
        # Capacity and voltage ratio live in nameplate_data (JSONB) under a
        # handful of different key names depending on which template was used
        # at onboarding — mirrors services/nameplate_helper.py's key list so
        # this report shows the same values the PDF/HTML reports do.
        sql = text(f"""
            SELECT
                e.ueic,
                d.name                              AS department,
                cm.name                             AS equipment_type,
                e.voltage_class,
                e.status                            AS equipment_status,
                e.manufacturer,
                e.factory_serial_number             AS serial_number,
                e.year_of_manufacture,
                COALESCE(
                    e.nameplate_data->>'rated_mva',
                    e.nameplate_data->>'rated_mva_onan',
                    e.nameplate_data->>'rated_mva_onan_mva',
                    e.nameplate_data->>'capacity_mva',
                    e.nameplate_data->>'mva_rating',
                    e.nameplate_data->>'rated_capacity',
                    e.nameplate_data->>'capacity',
                    e.nameplate_data->>'kva_rating'
                )                                    AS capacity,
                COALESCE(
                    e.nameplate_data->>'voltage_ratio',
                    NULLIF(concat_ws('/',
                        e.nameplate_data->>'hv_voltage',
                        e.nameplate_data->>'mv_voltage',
                        e.nameplate_data->>'lv_voltage'), ''),
                    e.voltage_class
                )                                    AS voltage_ratio,
                COALESCE(tr_latest.evaluation_result->>'overall', 'NOT_TESTED') AS condition,
                tr_latest.tested_at                 AS last_tested_at,
                tr_latest.test_name                 AS last_test_name
            FROM   public.equipment e
            LEFT JOIN public.org_departments  d  ON d.id  = e.department_id
            LEFT JOIN public."CategoryMaster"  cm ON cm.id = e.equipment_type_id
            LEFT JOIN LATERAL (
                SELECT res.evaluation_result, res.tested_at, res.test_name
                FROM   public.test_results res
                JOIN   public.testing_requests req ON req.id = res.testing_request_id
                WHERE  req.equipment_id = e.id AND res.evaluation_result IS NOT NULL
                ORDER  BY res.tested_at DESC NULLS LAST
                LIMIT  1
            ) tr_latest ON true
            WHERE  e.status != 'retired' {org}
            ORDER  BY e.ueic
        """)
        return self._exec(sql)

    def _q_overdue_tests(self, p: dict) -> list[dict]:
        org   = self._scope("tr")
        today = date.today()
        df = _date(_p(p, "date_from"))
        dt = _date(_p(p, "date_to"))
        extra = ""
        if df:
            extra += f" AND tr.due_date >= '{df}'"
        if dt:
            extra += f" AND tr.due_date <= '{dt}'"
        sql = text(f"""
            SELECT
                tr.request_number,
                -- Title is optional on the request form: blank ones (or the
                -- old "  -  Test Name" shape) fall back to the test name.
                COALESCE(
                    NULLIF(regexp_replace(COALESCE(tr.title, ''), '^[[:space:]-]+', ''), ''),
                    cd.name
                )                                         AS title,
                tr.zone,
                tr.ce_circle,
                tr.ee_subdivision,
                tr.status,
                tr.priority,
                tr.due_date::date                         AS due_date,
                ('{today}'::date - tr.due_date::date)     AS days_overdue,
                e.ueic,
                cm.name                                   AS equipment_type,
                cd.name                                   AS test_type
            FROM   public.testing_requests tr
            LEFT JOIN public.equipment        e  ON e.id  = tr.equipment_id
            LEFT JOIN public."CategoryMaster"  cm ON cm.id = tr.equipment_type_id
            LEFT JOIN public."CategoryDetails" cd ON cd.id = tr.test_type_id
            WHERE  tr.request_category = 'test'
              AND  tr.due_date IS NOT NULL
              AND  tr.due_date < NOW()
              AND  tr.status IN ('submitted','assigned','accepted','in_progress',
                                 'test_submitted','under_approval')
              {org} {extra}
            ORDER  BY tr.due_date ASC
        """)
        return self._exec(sql)

    def _q_active_alerts(self, p: dict) -> list[dict]:
        org = self._scope("res")
        sev = _p(p, "severity", "all")
        sev_clause = (
            f" AND res.evaluation_result->>'overall' = '{sev}'"
            if sev in ("CRITICAL", "ALERT")
            else " AND res.evaluation_result->>'overall' IN ('CRITICAL','ALERT')"
        )
        df = _date(_p(p, "date_from"))
        dt = _date(_p(p, "date_to"))
        extra = ""
        if df:
            extra += f" AND res.tested_at >= '{df}'"
        if dt:
            extra += f" AND res.tested_at <= '{dt}'"
        sql = text(f"""
            SELECT
                tr.request_number,
                e.ueic,
                cm.name                                 AS equipment_type,
                tr.zone,
                tr.ee_subdivision,
                res.test_name,
                res.evaluation_result->>'overall'       AS severity,
                res.tested_at,
                u.email                                 AS tested_by
            FROM   public.test_results res
            JOIN   public.testing_requests  tr ON tr.id  = res.testing_request_id
            LEFT JOIN public.equipment       e  ON e.id  = tr.equipment_id
            LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
            LEFT JOIN public.users           u  ON u.id  = res.tested_by
            WHERE  res.evaluation_result IS NOT NULL
              {sev_clause} {org} {extra}
            ORDER  BY res.tested_at DESC
            LIMIT  500
        """)
        return self._exec(sql)

    def _q_flagged_equipment(self, p: dict) -> list[dict]:
        org = self._scope("res")
        # Same COALESCE key list as _q_equipment_condition / nameplate_helper.py
        sql = text(f"""
            SELECT DISTINCT ON (e.id)
                e.ueic,
                d.name                              AS substation,
                cm.name                             AS equipment_type,
                e.manufacturer,
                e.factory_serial_number             AS serial_number,
                e.year_of_manufacture,
                e.voltage_class,
                COALESCE(
                    e.nameplate_data->>'rated_mva',
                    e.nameplate_data->>'rated_mva_onan',
                    e.nameplate_data->>'rated_mva_onan_mva',
                    e.nameplate_data->>'capacity_mva',
                    e.nameplate_data->>'mva_rating',
                    e.nameplate_data->>'rated_capacity',
                    e.nameplate_data->>'capacity',
                    e.nameplate_data->>'kva_rating'
                )                                    AS capacity,
                COALESCE(
                    e.nameplate_data->>'voltage_ratio',
                    NULLIF(concat_ws('/',
                        e.nameplate_data->>'hv_voltage',
                        e.nameplate_data->>'mv_voltage',
                        e.nameplate_data->>'lv_voltage'), ''),
                    e.voltage_class
                )                                    AS voltage_ratio,
                res.evaluation_result->>'overall'   AS condition,
                res.tested_at                       AS last_tested_at,
                tr.zone,
                tr.ee_subdivision
            FROM   public.test_results res
            JOIN   public.testing_requests  tr ON tr.id = res.testing_request_id
            JOIN   public.equipment         e  ON e.id  = tr.equipment_id
            LEFT JOIN public.org_departments d  ON d.id  = e.department_id
            LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
            WHERE  res.evaluation_result IS NOT NULL
              AND  res.evaluation_result->>'overall' IN ('CRITICAL','ALERT')
              {org}
            ORDER  BY e.id, res.tested_at DESC
        """)
        return self._exec(sql)

    def _q_repair_progress(self, p: dict) -> list[dict]:
        org = self._scope("tr")
        sql = text(f"""
            SELECT
                tr.request_number,
                e.ueic,
                cm.name                             AS equipment_type,
                tr.title,
                tr.status,
                tr.total_sessions_planned,
                tr.requested_date::date             AS requested_date,
                tr.due_date::date                   AS due_date,
                tr.zone,
                tr.ee_subdivision,
                COUNT(ts.id)                        AS sessions_completed
            FROM   public.testing_requests tr
            LEFT JOIN public.equipment       e  ON e.id  = tr.equipment_id
            LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
            LEFT JOIN public.test_sessions   ts
                   ON ts.testing_request_id = tr.id AND ts.status = 'completed'
            WHERE  tr.request_category = 'repair_lifecycle'
              AND  tr.status IN ('submitted','assigned','accepted','in_progress',
                                 'test_submitted','under_approval')
              {org}
            GROUP  BY tr.id, e.ueic, cm.name
            ORDER  BY tr.cts DESC
        """)
        return self._exec(sql)

    def _q_maintenance_overdue(self, p: dict) -> list[dict]:
        org   = self._scope("tr")
        today = date.today()
        sql = text(f"""
            SELECT
                tr.request_number,
                tr.title,
                tr.zone,
                tr.ee_subdivision,
                tr.status,
                tr.due_date::date                         AS due_date,
                ('{today}'::date - tr.due_date::date)     AS days_overdue,
                e.ueic,
                cm.name                                   AS equipment_type
            FROM   public.testing_requests tr
            LEFT JOIN public.equipment       e  ON e.id  = tr.equipment_id
            LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
            WHERE  tr.request_category = 'maintenance'
              AND  tr.due_date IS NOT NULL
              AND  tr.due_date < NOW()
              AND  tr.status IN ('submitted','assigned','accepted','in_progress',
                                 'test_submitted','under_approval')
              {org}
            ORDER  BY tr.due_date ASC
        """)
        return self._exec(sql)

    def _q_procurement_pipeline(self, p: dict) -> list[dict]:
        org = self._scope("pr")
        st  = _p(p, "status", "all")
        st_clause = f" AND pr.status = '{st}'" if st and st != "all" else ""
        sql = text(f"""
            SELECT
                pr.procurement_number,
                pr.title,
                pr.status,
                pr.estimated_cost,
                pr.quantity,
                pr.raised_at::date  AS raised_date,
                tr.request_number   AS linked_request,
                u.email             AS raised_by
            FROM   public.procurement_requests pr
            LEFT JOIN public.testing_requests tr ON tr.id = pr.testing_request_id
            LEFT JOIN public.users            u  ON u.id  = pr.raised_by
            WHERE  1=1 {org} {st_clause}
            ORDER  BY pr.raised_at DESC
        """)
        return self._exec(sql)

    def _q_open_remediation(self, p: dict) -> list[dict]:
        org   = self._scope("rec")
        today = date.today()
        sql = text(f"""
            SELECT
                tr.request_number,
                e.ueic,
                cm.name                                 AS equipment_type,
                rec.recommendation_type,
                rec.approval_status,
                rec.summary,
                rec.cts::date                           AS raised_date,
                ('{today}'::date - rec.cts::date)       AS days_open,
                u.email                                 AS submitted_by,
                tr.due_date::date                       AS due_date
            FROM   public.recommendations rec
            JOIN   public.testing_requests  tr ON tr.id  = rec.testing_request_id
            LEFT JOIN public.equipment       e  ON e.id  = tr.equipment_id
            LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
            LEFT JOIN public.users           u  ON u.id  = rec.submitted_by
            WHERE  rec.approval_status = 'pending'
              {org}
            ORDER  BY rec.cts ASC
        """)
        return self._exec(sql)

    def _q_testing_request_status(self, p: dict) -> list[dict]:
        org = self._scope("tr")
        clauses = ""
        st  = _p(p, "status")
        cat = _p(p, "category")
        df  = _date(_p(p, "date_from"))
        dt  = _date(_p(p, "date_to"))
        if st  and st  != "all":
            clauses += f" AND tr.status = '{st}'"
        if cat and cat != "all":
            clauses += f" AND tr.request_category = '{cat}'"
        if df:
            clauses += f" AND tr.cts >= '{df}'"
        if dt:
            clauses += f" AND tr.cts <= '{dt}'"
        # Outcome filter: every finished ticket has status 'closed', so the
        # status filter alone can't tell completed / rejected / cancelled /
        # auto-closed apart.
        outcome_labels = {"open": "Open", "completed": "Completed", "rejected": "Rejected",
                          "cancelled": "Cancelled", "auto_closed": "Auto-closed",
                          "closed": "Closed"}
        oc = (_p(p, "outcome") or "all").lower().replace("-", "_").replace(" ", "_")
        outcome_where = f"WHERE outcome = '{outcome_labels[oc]}'" if oc in outcome_labels else ""
        sql = text(f"""
            SELECT * FROM (
            SELECT
                tr.request_number,
                -- Title is optional on the request form: blank ones (or the
                -- old "  -  Test Name" shape) fall back to the test name.
                COALESCE(
                    NULLIF(regexp_replace(COALESCE(tr.title, ''), '^[[:space:]-]+', ''), ''),
                    cd.name
                )                   AS title,
                tr.request_category,
                tr.status,
                -- Real result of a finished ticket (status is just 'closed'
                -- for all of them): equipment-driven auto-close is marked in
                -- rejection_reason; the rest come from the workflow's
                -- terminal status code — same rule as the dashboard's
                -- Rejected/Cancelled tile.
                CASE
                    WHEN tr.rejection_reason ILIKE 'Auto-closed%%'           THEN 'Auto-closed'
                    WHEN tr.current_status_code = 'wf_rejected'
                      OR tr.status::text = 'rejected'                         THEN 'Rejected'
                    WHEN tr.current_status_code = 'wf_cancelled'             THEN 'Cancelled'
                    WHEN tr.current_status_code = 'wf_completed'
                      OR tr.status::text = 'completed'                        THEN 'Completed'
                    WHEN tr.status::text = 'closed'                           THEN 'Closed'
                    ELSE 'Open'
                END                 AS outcome,
                COALESCE(NULLIF(TRIM(term.comment), ''), tr.rejection_reason)
                                    AS closure_reason,
                CASE WHEN tr.status::text IN ('closed', 'completed', 'rejected')
                     THEN COALESCE(term.created_at, tr.completed_at, tr.mts)::date
                END                 AS closed_on,
                CASE WHEN tr.status::text IN ('closed', 'completed', 'rejected')
                     THEN COALESCE(u_c.email, u_cb.email)
                END                 AS closed_by,
                tr.priority,
                -- Zone → CE Circle → EE Subdivision → Substation, read top-down
                -- from the ticket's department chain (the free-text zone /
                -- ce_circle / ee_subdivision columns on the ticket are mostly
                -- empty); those typed values are only the fallback.
                COALESCE(h.path[1], NULLIF(tr.zone, ''))            AS zone,
                COALESCE(h.path[2], NULLIF(tr.ce_circle, ''))       AS ce_circle,
                COALESCE(h.path[3], NULLIF(tr.ee_subdivision, ''))  AS ee_subdivision,
                CASE WHEN array_length(h.path, 1) >= 4
                     THEN h.path[array_length(h.path, 1)] END        AS substation,
                tr.cts::date        AS created_date,
                tr.due_date::date   AS due_date,
                tr.completed_at::date AS completed_date,
                e.ueic,
                cm.name             AS equipment_type,
                cd.name             AS test_type,
                u_o.email           AS originator,
                u_t.email           AS assigned_tester
            FROM   public.testing_requests tr
            LEFT JOIN public.equipment        e     ON e.id    = tr.equipment_id
            LEFT JOIN public."CategoryMaster"  cm    ON cm.id   = tr.equipment_type_id
            LEFT JOIN public."CategoryDetails" cd    ON cd.id   = tr.test_type_id
            LEFT JOIN public.users            u_o   ON u_o.id  = tr.originator_id
            LEFT JOIN public.users            u_t   ON u_t.id  = tr.assigned_tester_id
            -- Last terminal workflow step: who closed it, when, and their comment.
            LEFT JOIN LATERAL (
                SELECT a.comment, a.created_at, a.performed_by
                FROM   public.tr_wf_audit_logs a
                WHERE  a.testing_request_id = tr.id AND a.is_terminal
                ORDER  BY a.created_at DESC LIMIT 1
            ) term ON true
            LEFT JOIN public.users            u_c   ON u_c.id  = term.performed_by
            LEFT JOIN public.users            u_cb  ON u_cb.id = tr.completed_by_id
            -- Department chain, root first: path[1] = zone ... last = own dept.
            LEFT JOIN LATERAL (
                WITH RECURSIVE up AS (
                    SELECT d.name, d.parent_department_id, 1 AS depth
                    FROM   public.org_departments d
                    WHERE  d.id = COALESCE(tr.department_id, e.department_id)
                    UNION ALL
                    SELECT p.name, p.parent_department_id, up.depth + 1
                    FROM   public.org_departments p
                    JOIN   up ON p.id = up.parent_department_id
                    WHERE  up.depth < 10
                )
                SELECT array_agg(name ORDER BY depth DESC) AS path FROM up
            ) h ON true
            WHERE  1=1 {org} {clauses}
            ) x
            {outcome_where}
            ORDER  BY created_date DESC
        """)
        return self._exec(sql)

    def _q_test_results_summary(self, p: dict) -> list[dict]:
        org = self._scope("res")
        sev = _p(p, "severity", "all")
        df  = _date(_p(p, "date_from"))
        dt  = _date(_p(p, "date_to"))
        clauses = ""
        if sev and sev != "all":
            clauses += f" AND res.evaluation_result->>'overall' = '{sev}'"
        if df:
            clauses += f" AND res.tested_at >= '{df}'"
        if dt:
            clauses += f" AND res.tested_at <= '{dt}'"
        sql = text(f"""
            SELECT
                tr.request_number,
                e.ueic,
                cm.name                                 AS equipment_type,
                res.test_name,
                res.template_key,
                res.overall_result,
                res.evaluation_result->>'overall'       AS evaluation_overall,
                res.pass_fail,
                res.tested_at,
                u.email                                 AS tested_by,
                tr.zone,
                tr.ee_subdivision
            FROM   public.test_results res
            JOIN   public.testing_requests  tr ON tr.id  = res.testing_request_id
            LEFT JOIN public.equipment       e  ON e.id  = tr.equipment_id
            LEFT JOIN public."CategoryMaster" cm ON cm.id = tr.equipment_type_id
            LEFT JOIN public.users           u  ON u.id  = res.tested_by
            WHERE  1=1 {org} {clauses}
            ORDER  BY res.tested_at DESC
            LIMIT  1000
        """)
        return self._exec(sql)

    def _q_recommendation_approval(self, p: dict) -> list[dict]:
        org = self._scope("rec")
        st  = _p(p, "status")
        clauses = ""
        if st and st != "all":
            clauses += f" AND rec.approval_status = '{st}'"
        sql = text(f"""
            SELECT
                tr.request_number,
                e.ueic,
                cm.name             AS equipment_type,
                rec.recommendation_type,
                rec.approval_status,
                rec.summary,
                rec.cts::date       AS submitted_date,
                rec.approved_at::date AS approved_date,
                rec.approval_notes,
                u_s.email           AS submitted_by,
                u_a.email           AS approved_by
            FROM   public.recommendations rec
            JOIN   public.testing_requests  tr  ON tr.id   = rec.testing_request_id
            LEFT JOIN public.equipment       e   ON e.id   = tr.equipment_id
            LEFT JOIN public."CategoryMaster" cm  ON cm.id  = tr.equipment_type_id
            LEFT JOIN public.users           u_s ON u_s.id = rec.submitted_by
            LEFT JOIN public.users           u_a ON u_a.id = rec.approved_by
            WHERE  1=1 {org} {clauses}
            ORDER  BY rec.cts DESC
        """)
        return self._exec(sql)

    def _q_compliance_status(self, p: dict) -> list[dict]:
        org         = self._scope("e")
        period_days = int(_p(p, "period_days", 365))
        sql = text(f"""
            SELECT
                d.name                              AS substation,
                tr_agg.zone,
                COUNT(DISTINCT e.id)                AS total_equipment,
                COUNT(DISTINCT CASE
                    WHEN latest_tr.completed_at >= NOW() - INTERVAL '{period_days} days'
                    THEN e.id END)                  AS tested_in_period,
                ROUND(
                    100.0 * COUNT(DISTINCT CASE
                        WHEN latest_tr.completed_at >= NOW() - INTERVAL '{period_days} days'
                        THEN e.id END)
                    / NULLIF(COUNT(DISTINCT e.id), 0), 1
                )                                   AS compliance_pct,
                COUNT(DISTINCT CASE
                    WHEN latest_res.condition = 'CRITICAL' THEN e.id END) AS critical_count,
                COUNT(DISTINCT CASE
                    WHEN latest_res.condition = 'ALERT'    THEN e.id END) AS alert_count
            FROM   public.equipment e
            LEFT JOIN public.org_departments  d      ON d.id = e.department_id
            LEFT JOIN public.testing_requests tr_agg ON tr_agg.equipment_id = e.id
            LEFT JOIN LATERAL (
                SELECT completed_at FROM public.testing_requests
                WHERE  equipment_id = e.id AND status = 'completed'
                ORDER  BY completed_at DESC LIMIT 1
            ) latest_tr ON true
            LEFT JOIN LATERAL (
                SELECT res.evaluation_result->>'overall' AS condition
                FROM   public.test_results res
                JOIN   public.testing_requests req ON req.id = res.testing_request_id
                WHERE  req.equipment_id = e.id AND res.evaluation_result IS NOT NULL
                ORDER  BY res.tested_at DESC LIMIT 1
            ) latest_res ON true
            WHERE  e.status = 'active' {org}
            GROUP  BY d.name, tr_agg.zone
            ORDER  BY compliance_pct ASC NULLS FIRST
        """)
        return self._exec(sql)

    def _q_tester_performance(self, p: dict) -> list[dict]:
        org = self._scope("tr")
        df  = _date(_p(p, "date_from"))
        dt  = _date(_p(p, "date_to"))
        clauses = ""
        if df:
            clauses += f" AND tr.cts >= '{df}'"
        if dt:
            clauses += f" AND tr.cts <= '{dt}'"
        sql = text(f"""
            SELECT
                u.email                                 AS tester_email,
                TRIM(COALESCE(u.firstname,'') || ' ' || COALESCE(u.lastname,'')) AS tester_name,
                COUNT(tr.id)                            AS total_assigned,
                COUNT(CASE WHEN tr.status='completed'   THEN 1 END) AS completed,
                COUNT(CASE WHEN tr.status='in_progress' THEN 1 END) AS in_progress,
                COUNT(CASE WHEN tr.status='rejected'    THEN 1 END) AS rejected,
                ROUND(AVG(CASE
                    WHEN tr.status='completed' AND tr.completed_at IS NOT NULL
                         AND tr.assigned_at IS NOT NULL
                    THEN EXTRACT(EPOCH FROM (tr.completed_at - tr.assigned_at)) / 86400.0
                END), 1)                                AS avg_days_to_complete
            FROM   public.testing_requests tr
            JOIN   public.users u ON u.id = tr.assigned_tester_id
            WHERE  tr.assigned_tester_id IS NOT NULL
              {org} {clauses}
            GROUP  BY u.id, u.email, u.firstname, u.lastname
            ORDER  BY completed DESC
        """)
        return self._exec(sql)

    def _q_monthly_kpi(self, p: dict) -> list[dict]:
        org    = self._scope("tr")
        months = int(_p(p, "months", 12))
        sql = text(f"""
            SELECT
                TO_CHAR(DATE_TRUNC('month', tr.cts), 'YYYY-MM') AS month,
                COUNT(tr.id)                                      AS requests_raised,
                COUNT(CASE WHEN tr.status='completed' THEN 1 END) AS completed,
                COUNT(CASE
                    WHEN tr.status IN ('submitted','assigned','accepted','in_progress',
                                       'test_submitted','under_approval')
                         AND tr.due_date IS NOT NULL
                         AND tr.due_date < NOW() THEN 1 END)      AS overdue,
                COUNT(DISTINCT CASE
                    WHEN res.evaluation_result->>'overall'='CRITICAL'
                    THEN res.id END)                              AS critical_findings,
                COUNT(DISTINCT CASE
                    WHEN res.evaluation_result->>'overall'='ALERT'
                    THEN res.id END)                              AS alert_findings,
                COUNT(DISTINCT rec.id)                            AS recommendations_raised,
                COUNT(DISTINCT CASE WHEN rec.approval_status='approved'
                    THEN rec.id END)                              AS recommendations_approved
            FROM   public.testing_requests tr
            LEFT JOIN public.test_results    res ON res.testing_request_id = tr.id
            LEFT JOIN public.recommendations rec ON rec.testing_request_id = tr.id
            WHERE  tr.cts >= NOW() - INTERVAL '{months} months'
              {org}
            GROUP  BY DATE_TRUNC('month', tr.cts)
            ORDER  BY month DESC
        """)
        return self._exec(sql)

    def _q_workflow_stage_delays(self, p: dict) -> list[dict]:
        """Workflow stages running past their configured time limit — the
        report behind the "Workflow Stage SLA Breach" and "<X> Stage Delayed"
        notifications. Two sources: test-request workflow stages
        (tr_wf_stage_instances; hours take precedence over days, same rule
        as the notification job) and repair-type workflows' current stage
        (repair, calibration, overhaul, pre-commission, surveillance,
        annual audit; repair_stage_definitions.default_duration_days)."""
        tr_sql = text(f"""
            SELECT
                'Test Request'                         AS workflow,
                tr.request_number                      AS reference,
                st.name                                AS stage,
                e.ueic,
                d.name                                 AS substation,
                si.started_at                          AS stage_started,
                si.started_at + INTERVAL '1 hour' *
                    COALESCE(st.default_duration_hours, st.default_duration_days * 24)
                                                       AS stage_deadline,
                ROUND((EXTRACT(EPOCH FROM NOW() - (si.started_at + INTERVAL '1 hour' *
                    COALESCE(st.default_duration_hours, st.default_duration_days * 24)))
                    / 86400)::numeric, 1)              AS days_over
            FROM   public.tr_wf_stage_instances si
            JOIN   public.tr_wf_stages     st ON st.id = si.stage_id
            JOIN   public.tr_wf_instances  wi ON wi.id = si.wf_instance_id
            JOIN   public.testing_requests tr ON tr.id = wi.testing_request_id
            LEFT JOIN public.equipment       e ON e.id = tr.equipment_id
            LEFT JOIN public.org_departments d ON d.id = tr.department_id
            WHERE  si.status = 'in_progress'
              AND  si.started_at IS NOT NULL
              AND  COALESCE(st.default_duration_hours, st.default_duration_days * 24) IS NOT NULL
              AND  si.started_at + INTERVAL '1 hour' *
                   COALESCE(st.default_duration_hours, st.default_duration_days * 24) < NOW()
              {self._scope("tr")}
        """)
        wf_sql = text(f"""
            SELECT
                COALESCE(wf.workflow_code, wf.workflow_type, 'Repair') AS workflow,
                wf.workflow_number                     AS reference,
                rsd.name                               AS stage,
                e.ueic,
                d.name                                 AS substation,
                rsi.started_at                         AS stage_started,
                rsi.started_at + INTERVAL '1 day' * rsd.default_duration_days
                                                       AS stage_deadline,
                ROUND((EXTRACT(EPOCH FROM NOW() - (rsi.started_at
                    + INTERVAL '1 day' * rsd.default_duration_days)) / 86400)::numeric, 1)
                                                       AS days_over
            FROM   public.repair_workflows wf
            JOIN   public.repair_stage_instances   rsi ON rsi.id = wf.current_stage_instance_id
            JOIN   public.repair_stage_definitions rsd ON rsd.id = rsi.stage_id
            LEFT JOIN public.equipment       e ON e.id = wf.equipment_id
            LEFT JOIN public.org_departments d ON d.id = e.department_id
            WHERE  rsi.completed_at IS NULL
              AND  rsi.started_at IS NOT NULL
              AND  rsd.default_duration_days IS NOT NULL
              AND  rsi.started_at + INTERVAL '1 day' * rsd.default_duration_days < NOW()
              AND  LOWER(COALESCE(wf.status, '')) NOT IN ('completed', 'cancelled', 'closed')
              {self._scope("wf")}
        """)
        rows = self._exec(tr_sql) + self._exec(wf_sql)
        return sorted(rows, key=lambda r: r.get("days_over") or 0, reverse=True)

    def _q_kit_calibration_due(self, p: dict) -> list[dict]:
        """Calibration status of every equipment/testing kit with a
        calibration configuration — the report behind the "Test Kit
        Calibration Due Soon / Overdue" notifications. Uses
        CalibrationService.get_calibration_status, the same status the
        calibration scheduler and those notifications use."""
        from models import Equipment, EquipmentCalibrationConfig, OrgDepartment, CategoryMaster
        from services.calibration_service import CalibrationService

        q = (
            self.db.query(Equipment)
            .join(EquipmentCalibrationConfig, EquipmentCalibrationConfig.equipment_id == Equipment.id)
        )
        if self.org_id:
            q = q.filter(Equipment.organization_id == self.org_id)
        if self.dept_ids:
            q = q.filter(Equipment.department_id.in_(self.dept_ids))
        equipment = q.all()

        dept_names = {d.id: d.name for d in self.db.query(OrgDepartment).all()}
        type_names = {c.id: c.name for c in self.db.query(CategoryMaster).all()}
        cal = CalibrationService(self.db)
        state_label = {"OVERDUE": "Overdue", "DUE_SOON": "Due soon",
                       "NORMAL": "OK", "NOT_CALIBRATED": "Not calibrated"}
        rows = []
        for eq in equipment:
            st = cal.get_calibration_status(eq.id)
            rows.append({
                "ueic":                  eq.ueic,
                "equipment_type":        type_names.get(eq.equipment_type_id),
                "substation":            dept_names.get(eq.department_id),
                "calibration_status":    state_label.get(st.get("state"), st.get("state")),
                "last_calibration_date": st.get("last_calibration_date"),
                "next_due_date":         st.get("next_due_date"),
                "days_until_due":        st.get("days_until_due"),
                "calibrated_by":         st.get("calibrated_by"),
                "certificate_number":    st.get("certificate_number"),
            })
        # Overdue first, then soonest due; never-calibrated last.
        return sorted(rows, key=lambda r: (r["days_until_due"] is None,
                                           r["days_until_due"] if r["days_until_due"] is not None else 0))

    def _q_deterioration_watch(self, p: dict) -> list[dict]:
        """Equipment parameters on the deterioration watch list (predicted to
        breach a threshold) and whether each has been reviewed — the report
        behind the "Deterioration Watch Escalated / Overdue Review"
        notifications. Reuses routers.analytics.get_deterioration_watch_list,
        the same list the watch dashboard and those notifications use."""
        from routers.analytics import get_deterioration_watch_list
        from models import OrgDepartment

        result = get_deterioration_watch_list(
            department_id=None, db=self.db,
            user={"organization_id": self.org_id, "id": None},
        )
        allowed = set(self.dept_ids) if self.dept_ids else None
        dept_names = {str(d.id): d.name for d in self.db.query(OrgDepartment).all()}
        today = date.today()
        rows = []
        for eq in result.get("equipment", []):
            dept = str(eq.get("department_id")) if eq.get("department_id") else None
            if allowed is not None and dept not in allowed:
                continue
            for prm in eq.get("parameters", []):
                tested = prm.get("tested_at")
                try:
                    pending = (today - date.fromisoformat(tested[:10])).days if tested else None
                except ValueError:
                    pending = None
                rows.append({
                    "ueic":               eq.get("equipment_label"),
                    "equipment_type":     eq.get("equipment_type"),
                    "substation":         dept_names.get(dept),
                    "risk_level":         eq.get("risk_level"),
                    "health_score":       eq.get("health_score"),
                    "parameter":          prm.get("parameter_label"),
                    "current_value":      prm.get("current_value"),
                    "unit":               prm.get("unit"),
                    "breach_threshold":   prm.get("breach_threshold"),
                    "days_to_breach":     prm.get("days_to_breach"),
                    "last_tested":        tested[:10] if tested else None,
                    "reviewed":           "Yes" if prm.get("is_reviewed") else "No",
                    "days_pending_review": None if prm.get("is_reviewed") else pending,
                    "review_disposition": prm.get("review_disposition"),
                })
        return sorted(rows, key=lambda r: (r["days_to_breach"] is None, r["days_to_breach"] or 0))

    def _q_dga_trend_report(self, p: dict) -> list[dict]:
        """DGA gas readings per transformer over the trailing N months, with
        month-over-month generation rate (ppm/month) and Duval Triangle
        fault-type classification per KPTCL spec Part II §3 / §12.x — a
        Python function, not a sql_template, because the readings live
        inside TestResult.test_data's dga_results JSON array (one row per
        gas per test), not flat columns a single SQL statement can
        conveniently pivot and diff against the equipment's own prior
        reading in one pass.

        See services/duval_triangle.py's module docstring for this
        classification's validation status — every row here carries that
        same "AI Advisory, not yet RT&R&D-validated" caveat via the
        duval_advisory column.
        """
        from models import TestResult, TestingRequest, Equipment, CategoryMaster, OrgDepartment
        from services.duval_triangle import classify_duval_triangle, gas_values_from_test_data

        months = int(_p(p, "months", 12))
        cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)

        q = (
            self.db.query(TestResult, TestingRequest, Equipment)
            .join(TestingRequest, TestingRequest.id == TestResult.testing_request_id)
            .join(Equipment, Equipment.id == TestingRequest.equipment_id)
            .filter(TestResult.template_key == "transformer_dga")
            .filter(TestResult.tested_at >= cutoff)
        )
        if self.org_id:
            q = q.filter(TestResult.organization_id == self.org_id)
        if self.dept_ids:
            q = q.filter(TestingRequest.department_id.in_(self.dept_ids))
        rows = q.order_by(TestResult.tested_at.asc()).all()

        eq_type_names = {c.id: c.name for c in self.db.query(CategoryMaster).all()}
        dept_names = {d.id: d.name for d in self.db.query(OrgDepartment).all()}

        # Sort per-equipment so consecutive readings can be diffed for a
        # ppm/month generation rate and an acceleration flag (this test's
        # rate vs. that same equipment's own previous rate) — both
        # impossible to compute from a single row in isolation.
        by_equipment: dict = {}
        for tr_result, tr_req, eq in rows:
            by_equipment.setdefault(eq.id, []).append((tr_result, tr_req, eq))

        out_rows = []
        for eq_id, eq_rows in by_equipment.items():
            prev_gas_values = None
            prev_tested_at = None
            prev_rates = {}
            for tr_result, tr_req, eq in eq_rows:
                gas_values = gas_values_from_test_data(tr_result.test_data)
                duval = classify_duval_triangle(
                    gas_values.get("ch4") or 0,
                    gas_values.get("c2h4") or 0,
                    gas_values.get("c2h2") or 0,
                )

                rates = {}
                accelerating_gases = []
                if prev_gas_values is not None and prev_tested_at and tr_result.tested_at:
                    days = (tr_result.tested_at - prev_tested_at).days or 1
                    for key in ("ch4", "c2h4", "c2h2"):
                        cur = gas_values.get(key)
                        prev = prev_gas_values.get(key)
                        if cur is None or prev is None:
                            continue
                        rate = (cur - prev) / days * 30.0  # ppm/month
                        rates[key] = round(rate, 2)
                        prior_rate = prev_rates.get(key)
                        # Acceleration = generation rate itself increasing
                        # test-over-test, independent of whether any single
                        # concentration has crossed an absolute threshold
                        # yet — the spec's own framing for this flag.
                        if prior_rate is not None and prior_rate > 0 and rate > prior_rate * 1.25:
                            accelerating_gases.append(key)

                out_rows.append({
                    "equipment_ueic": eq.ueic,
                    "equipment_type": eq_type_names.get(eq.equipment_type_id),
                    "department":     dept_names.get(eq.department_id),
                    "tested_at":      tr_result.tested_at.isoformat() if tr_result.tested_at else None,
                    "ch4_ppm":        gas_values.get("ch4"),
                    "c2h4_ppm":       gas_values.get("c2h4"),
                    "c2h2_ppm":       gas_values.get("c2h2"),
                    "ch4_rate_ppm_per_month":  rates.get("ch4"),
                    "c2h4_rate_ppm_per_month": rates.get("c2h4"),
                    "c2h2_rate_ppm_per_month": rates.get("c2h2"),
                    "accelerating_gases": ", ".join(accelerating_gases) if accelerating_gases else None,
                    "duval_zone":     duval["zone"] if duval["zone"] is not None else "No Bottom (ppm) reading",
                    "duval_meaning":  duval["meaning"],
                    "duval_pct_ch4":  duval["pct_ch4"],
                    "duval_pct_c2h4": duval["pct_c2h4"],
                    "duval_pct_c2h2": duval["pct_c2h2"],
                    "duval_advisory": duval["advisory"],
                })

                prev_gas_values = gas_values
                prev_tested_at = tr_result.tested_at
                prev_rates = rates

        out_rows.sort(key=lambda r: r["tested_at"] or "", reverse=True)
        return out_rows

    # ── Executor ───────────────────────────────────────────────────────────

    def _exec(self, sql) -> list[dict]:
        result = self.db.execute(sql)
        keys   = list(result.keys())
        return [dict(zip(keys, row)) for row in result.fetchall()]

    # ── Excel renderer ─────────────────────────────────────────────────────

    def _render_excel(self, rows: list[dict],
                      defn: ReportDefinition) -> tuple[bytes, str]:
        if not _HAS_OPENPYXL:
            raise RuntimeError("openpyxl not installed. Run: pip install openpyxl")

        wb = openpyxl.Workbook()
        ws = wb.active
        import re
        safe_title = re.sub(r'[\/\\\?\*\[\]\:]', '-', defn.name)[:31]
        ws.title = safe_title

        if not rows:
            ws["A1"] = "No data found for the selected parameters."
            buf = io.BytesIO()
            wb.save(buf)
            return (buf.getvalue(),
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # Styles
        hdr_fill  = PatternFill("solid", fgColor="1565C0")
        hdr_font  = Font(bold=True, color="FFFFFF", size=10)
        hdr_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        thin      = Side(style="thin", color="CCCCCC")
        bdr       = Border(left=thin, right=thin, top=thin, bottom=thin)
        alt_fill  = PatternFill("solid", fgColor="EBF2FB")

        # Row 1: report title
        cols = len(rows[0])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=cols)
        c = ws.cell(row=1, column=1, value=defn.name)
        c.font      = Font(bold=True, size=13, color="1565C0")
        c.alignment = Alignment(horizontal="center")
        ws.row_dimensions[1].height = 28

        # Row 2: generated timestamp + description
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=cols)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        desc_part = f"  |  {defn.description}" if defn.description else ""
        ws.cell(row=2, column=1, value=f"Generated: {ts}{desc_part}")
        ws.row_dimensions[2].height = 16

        # Row 3: headers
        headers = list(rows[0].keys())
        for ci, h in enumerate(headers, 1):
            c = ws.cell(row=3, column=ci,
                        value=h.replace("_", " ").title())
            c.fill      = hdr_fill
            c.font      = hdr_font
            c.alignment = hdr_align
            c.border    = bdr
        ws.row_dimensions[3].height = 20

        # Data rows
        for ri, row in enumerate(rows, 4):
            fill = alt_fill if ri % 2 == 0 else None
            for ci, key in enumerate(headers, 1):
                val = row.get(key)
                if isinstance(val, datetime):
                    val = val.replace(tzinfo=None)
                elif val is not None and not isinstance(
                        val, (str, int, float, bool, date, Decimal)):
                    # UUIDs, dicts/lists (JSON columns), etc. — openpyxl
                    # rejects them ("Cannot convert UUID(...) to Excel"),
                    # which failed the whole run with a misleading 404.
                    val = str(val)
                cell = ws.cell(row=ri, column=ci, value=val)
                if fill:
                    cell.fill = fill
                cell.border    = bdr
                cell.alignment = Alignment(wrap_text=False)

        # Auto-width
        for ci, h in enumerate(headers, 1):
            col_vals = [str(row.get(h) or "") for row in rows]
            max_len  = max(len(h.replace("_", " ").title()),
                           max((len(v) for v in col_vals), default=0))
            ws.column_dimensions[get_column_letter(ci)].width = min(max_len + 4, 50)

        ws.freeze_panes = "A4"

        buf = io.BytesIO()
        wb.save(buf)
        return (buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ── PDF renderer (ReportLab) ─────────────────────────────────────────────

    def _render_pdf(self, rows: list[dict],
                    defn: ReportDefinition) -> tuple[bytes, str]:
        if not _HAS_REPORTLAB:
            raise RuntimeError(
                "ReportLab is not installed. Run: pip install reportlab"
            )

        buffer = io.BytesIO()
        # Use landscape orientation for better table fit
        doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), 
                                topMargin=0.4*inch, bottomMargin=0.4*inch,
                                leftMargin=0.4*inch, rightMargin=0.4*inch)
        story = []

        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            textColor=colors.HexColor('#1565C0'),
            alignment=TA_CENTER,
            spaceAfter=12,
        )
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=11,
            textColor=colors.HexColor('#1565C0'),
            spaceAfter=8,
        )

        # Title
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        title = f"{defn.name} — Generated {ts}"
        story.append(Paragraph(title, title_style))
        
        # Description if present
        if defn.description:
            story.append(Paragraph(f"<i>{defn.description}</i>", 
                                  ParagraphStyle('Italic', parent=styles['Normal'], 
                                                fontSize=9, textColor=colors.grey)))
        
        story.append(Spacer(1, 0.15*inch))

        if not rows:
            story.append(Paragraph("No data found for the selected parameters.", 
                                  styles['Normal']))
            doc.build(story)
            buffer.seek(0)
            return buffer.getvalue(), "application/pdf"

        # Prepare table data with headers
        headers = list(rows[0].keys())
        table_data = [
            [h.replace("_", " ").title() for h in headers]  # Header row
        ]
        
        # Add data rows with formatting
        for row in rows:
            row_data = []
            for h in headers:
                val = row.get(h)
                # Format dates
                if isinstance(val, datetime):
                    val = val.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")
                # Format booleans and None
                elif val is None:
                    val = ""
                else:
                    val = str(val)
                row_data.append(val)
            table_data.append(row_data)

        # Column widths proportional to content (header + longest value in the
        # first rows), clamped so one long column can't starve the rest.
        # Plain strings in a reportlab Table never wrap — they spilled into
        # the neighbouring column — so every cell becomes a Paragraph that
        # wraps inside its column (long unbroken values like UUIDs included).
        from xml.sax.saxutils import escape as _esc
        from reportlab.lib.pagesizes import A3, A2
        col_count = len(headers)
        font_size = 8 if col_count <= 8 else 7
        char_w = font_size * 0.55          # average Helvetica glyph width
        pad = 10                           # left + right cell padding
        # Per column: the width it needs to show its longest single word
        # unbroken (dates, request numbers, "Completed") and the width for
        # its longest whole value on one line. Every column gets its minimum
        # first; leftover page width goes to the longer ones.
        mins, naturals = [], []
        for i in range(col_count):
            cells = [str(table_data[0][i])] + [str(r[i]) for r in table_data[1:51]]
            longest_word = max((len(w) for c in cells for w in c.split()), default=4)
            longest_value = max((len(c) for c in cells), default=4)
            mins.append(min(max(longest_word, 4), 24) * char_w + pad)
            naturals.append(min(max(longest_value, 4), 60) * char_w + pad)
        # Page size: the smallest landscape page on which every column fits
        # its longest word. Wide reports (e.g. Testing Request Status, 22
        # columns) squeezed onto Letter got words chopped mid-way
        # ("Outco|me", "Devan|ahalli").
        margins = 0.8 * inch
        page_size = landscape(A2)
        for candidate in (landscape(letter), landscape(A3), landscape(A2)):
            if sum(mins) <= candidate[0] - margins:
                page_size = candidate
                break
        doc.pagesize = page_size
        doc.width  = page_size[0] - doc.leftMargin - doc.rightMargin
        doc.height = page_size[1] - doc.topMargin - doc.bottomMargin
        page_width = page_size[0] - margins
        if sum(naturals) <= page_width:
            scale = page_width / sum(naturals)
            col_widths = [n * scale for n in naturals]
        elif sum(mins) >= page_width:
            col_widths = [m * page_width / sum(mins) for m in mins]
        else:
            k = (page_width - sum(mins)) / (sum(naturals) - sum(mins))
            col_widths = [m + (n - m) * k for m, n in zip(mins, naturals)]
        head_style = ParagraphStyle('CellHead', parent=styles['Normal'],
                                    fontName='Helvetica-Bold', fontSize=font_size,
                                    leading=font_size + 2, textColor=colors.whitesmoke,
                                    alignment=TA_CENTER, splitLongWords=1)
        cell_style = ParagraphStyle('Cell', parent=styles['Normal'],
                                    fontName='Helvetica', fontSize=font_size,
                                    leading=font_size + 2,
                                    textColor=colors.HexColor('#333333'),
                                    alignment=TA_LEFT, splitLongWords=1)
        table_data = [
            [Paragraph(_esc(str(v)), head_style if r_i == 0 else cell_style) for v in row]
            for r_i, row in enumerate(table_data)
        ]

        table = Table(table_data, colWidths=col_widths, repeatRows=1)
        
        # Style the table
        table.setStyle(TableStyle([
            # Header row
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1565C0')),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, 0), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            
            # Data rows
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#333333')),
            ('ALIGN', (0, 1), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 1), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            
            # Alternate row colors
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#EBF2FB')]),
            
            # Grid
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        
        story.append(table)
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        return buffer.getvalue(), "application/pdf"


# ── Scheduled runner (called from APScheduler) ─────────────────────────────

def run_scheduled_reports(db_factory) -> int:
    """Check all scheduled ReportDefinitions and generate those that are due."""
    db = db_factory()
    count = 0
    try:
        now  = datetime.now(timezone.utc)
        defs = db.query(ReportDefinition).filter(
            ReportDefinition.is_active.is_(True),
            ReportDefinition.frequency != "on_demand",
        ).all()
        for defn in defs:
            if not _is_due(defn, now):
                continue
            try:
                svc = ReportingService(db, defn.organization_id)
                # "both" → one Excel + one PDF, sent together in one email
                # (it used to fall back to Excel only).
                if defn.output_format == "both":
                    fmts = ["excel", "pdf"]
                else:
                    fmts = [defn.output_format if defn.output_format in ("excel", "pdf") else "excel"]
                files = [svc.generate(defn.id, {}, f)[1] for f in fmts]
                filename = files[0]
                count += 1
                try:
                    fire_report_ready(db, defn, filename, extra_filenames=files[1:])
                except Exception as notif_exc:
                    print(f"[Reports] Notification for '{defn.name}' failed: {notif_exc}")
            except Exception as exc:
                print(f"[Reports] Scheduled '{defn.name}' failed: {exc}")
    finally:
        db.close()
    return count


def fire_report_ready(db: Session, defn: ReportDefinition, filename: str,
                      organization_id: Optional[UUID] = None,
                      department_id: Optional[UUID] = None,
                      event_type: Optional[str] = None,
                      extra_filenames: Optional[list] = None) -> None:
    """
    Notify defn.notification_event's recipients that a report just finished
    generating — opt-in per definition (no-ops if notification_event isn't
    set). Called from both the scheduled job (run_scheduled_reports) and the
    on-demand "Run" endpoint (routers/reporting.py) — same event either way,
    since a recipient doesn't care whether the report ran on a timer or was
    triggered manually.

    Per-org fan-out: the 14 SRS report definitions are seeded once globally
    (organization_id IS NULL) rather than one row per org — but
    NotificationService recipient resolution requires an organization_id to
    look up OrgRole/OrgUserRole rows, so firing with org_id=None silently
    resolves to zero recipients. Fire once per active organization in that
    case; definitions that already carry their own organization_id (ad-hoc/
    per-org reports) fire once, as normal.

    source_type/source_id point at the ReportLog generate() just committed
    (looked up by definition_id + filename, so a concurrent generation of
    the same definition can't be mismatched) — this is what lets
    _generate_attachment_bytes()'s report_log branch attach the actual file,
    and what _enrich_context_from_source()'s report_log branch fills
    {{report.*}} variables from.
    """
    # event_type overrides the definition's own event (Run now uses the
    # generic scheduled_report_ready for definitions that have none).
    event = event_type or defn.notification_event
    if not event:
        return

    from services.notification_service import NotificationService
    from models import Organization, ReportLog

    log = (
        db.query(ReportLog)
        .filter(ReportLog.definition_id == defn.id, ReportLog.file_name == filename)
        .order_by(ReportLog.completed_at.desc())
        .first()
    )
    if not log or log.status != "completed":
        return

    # Both naming schemes populated — {{report.*}} (dotted, matches the
    # convention _enrich_context_from_source already uses for every other
    # source_type, and what this event's seeded templates reference) plus
    # the flat names, in case anything else ends up referencing those.
    context = {
        "report.name":         defn.name,
        "report.description":  defn.description or "",
        "report.frequency":    defn.frequency,
        "report.format":       log.output_format or "",
        "report.row_count":    str(log.row_count or 0),
        "report.file_name":    log.file_name or "",
        "report.generated_at": str(log.completed_at)[:19] if log.completed_at else "",
        "report_name":   defn.name,
        "report_period": datetime.now(timezone.utc).strftime("%B %Y"),
        "download_url":  f"/reports/download/{filename}",
        "format":        log.output_format or "",
    }

    # "Both" (Excel + PDF): the other file(s) of the same run ride along in
    # the same email instead of a second, separate email.
    extras = []
    for extra_name in (extra_filenames or []):
        extra_log = (
            db.query(ReportLog)
            .filter(ReportLog.definition_id == defn.id, ReportLog.file_name == extra_name)
            .order_by(ReportLog.completed_at.desc())
            .first()
        )
        if extra_log and extra_log.status == "completed":
            extras.append({
                "type": "pdf" if extra_name.lower().endswith(".pdf") else "excel",
                "var_key": "report_attachment_extra",
                "source_type": "report_log",
                "source_id": str(extra_log.id),
            })
    if extras:
        context["_extra_attachments"] = extras

    # A department-scoped run (routers/reporting.py passes the runner's org +
    # department) only contains that department's rows, so it's only sent to
    # that org, with recipients limited to that department — not fanned out
    # to every org's role holders as an org-wide scheduled report is.
    if organization_id:
        org_ids = [organization_id]
    elif defn.organization_id:
        org_ids = [defn.organization_id]
    else:
        org_ids = [
            o.id for o in
            db.query(Organization).filter(Organization.is_active.is_(True)).all()
        ]

    nsvc = NotificationService(db)
    for org_id in org_ids:
        try:
            nsvc.fire(
                event_type=event,
                context=context,
                organization_id=org_id,
                source_type="report_log",
                source_id=log.id,
                recipient_roles_override=defn.recipient_roles or None,
                department_id=department_id,
            )
        except Exception as exc:
            print(f"[Reports] notification_event '{event}' fire "
                  f"failed for '{defn.name}' org={org_id}: {exc}")


def _is_due(defn: ReportDefinition, now: datetime) -> bool:
    if defn.last_generated_at is None:
        return True
    delta = (now - defn.last_generated_at).total_seconds()
    if defn.frequency == "daily":
        return delta >= 86_400
    if defn.frequency == "weekly":
        return delta >= 7 * 86_400
    if defn.frequency == "monthly":
        return (now - defn.last_generated_at).days >= 28
    # Quarterly/annual were offered in the report editor (and seeded, e.g.
    # Equipment Failure Annual / Repairer Performance) but never matched
    # here, so those reports were never generated on schedule at all.
    if defn.frequency == "quarterly":
        return (now - defn.last_generated_at).days >= 90
    if defn.frequency == "annual":
        return (now - defn.last_generated_at).days >= 365
    return False
