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
from datetime import datetime, timezone, date
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy import text

from models import ReportDefinition, ReportLog

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


# ══════════════════════════════════════════════════════════════════════════
# ReportingService
# ══════════════════════════════════════════════════════════════════════════

class ReportingService:

    def __init__(self, db: Session, org_id: Optional[UUID] = None):
        self.db = db
        self.org_id = org_id

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

            log.status       = "completed"
            log.file_name    = filename
            log.file_size    = len(raw)
            log.row_count    = len(rows)
            log.completed_at = datetime.now(timezone.utc)
            defn.last_generated_at = datetime.now(timezone.utc)
            self.db.commit()

        except Exception as exc:
            log.status        = "failed"
            log.error_message = str(exc)
            log.completed_at  = datetime.now(timezone.utc)
            self.db.commit()
            raise

        return raw, filename, content_type

    # ── Query dispatcher ───────────────────────────────────────────────────

    def _run_query(self, query_key: str, params: dict) -> list[dict]:
        registry = {
            "equipment_condition_summary":      self._q_equipment_condition,
            "overdue_tests_report":             self._q_overdue_tests,
            "active_alerts_report":             self._q_active_alerts,
            "flagged_equipment_report":         self._q_flagged_equipment,
            "repair_progress_report":           self._q_repair_progress,
            "maintenance_overdue_report":       self._q_maintenance_overdue,
            "procurement_pipeline_report":      self._q_procurement_pipeline,
            "open_remediation_report":          self._q_open_remediation,
            "testing_request_status_report":    self._q_testing_request_status,
            "test_results_summary_report":      self._q_test_results_summary,
            "recommendation_approval_report":   self._q_recommendation_approval,
            "compliance_status_report":         self._q_compliance_status,
            "tester_performance_report":        self._q_tester_performance,
            "monthly_kpi_report":               self._q_monthly_kpi,
            # §3.3.3 Equipment Failure Registry
            "equipment_failure_annual_report":  self._q_equipment_failure_annual,
            "equipment_failure_performance_report": self._q_equipment_failure_performance,
            # §3.3.4 Failure Resolution (FR → Repair/Replacement traceability)
            "failure_resolution_report":        self._q_failure_resolution,
            # §3.5 Equipment Lifecycle
            "equipment_lifecycle_report":       self._q_equipment_lifecycle,
        }
        fn = registry.get(query_key)
        if not fn:
            raise ValueError(f"Unknown query_key: '{query_key}'")
        return fn(params)

    # ── 14 Query Functions ─────────────────────────────────────────────────

    def _q_equipment_condition(self, p: dict) -> list[dict]:
        org = _org_clause(self.org_id, "e")
        sql = text(f"""
            SELECT
                e.ueic,
                d.name                              AS department,
                cm.name                             AS equipment_type,
                e.voltage_class,
                e.status                            AS equipment_status,
                e.manufacturer,
                e.year_of_manufacture,
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
        org   = _org_clause(self.org_id, "tr")
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
                tr.title,
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
        org = _org_clause(self.org_id, "res")
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
        org = _org_clause(self.org_id, "res")
        sql = text(f"""
            SELECT DISTINCT ON (e.id)
                e.ueic,
                d.name                              AS substation,
                cm.name                             AS equipment_type,
                e.voltage_class,
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
        org = _org_clause(self.org_id, "tr")
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
        org   = _org_clause(self.org_id, "tr")
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
        org = _org_clause(self.org_id, "pr")
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
        org   = _org_clause(self.org_id, "rec")
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
        org = _org_clause(self.org_id, "tr")
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
        sql = text(f"""
            SELECT
                tr.request_number,
                tr.title,
                tr.request_category,
                tr.status,
                tr.priority,
                tr.zone,
                tr.ce_circle,
                tr.ee_subdivision,
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
            WHERE  1=1 {org} {clauses}
            ORDER  BY tr.cts DESC
        """)
        return self._exec(sql)

    def _q_test_results_summary(self, p: dict) -> list[dict]:
        org = _org_clause(self.org_id, "res")
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
        org = _org_clause(self.org_id, "rec")
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
        org         = _org_clause(self.org_id, "e")
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
        org = _org_clause(self.org_id, "tr")
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
        org    = _org_clause(self.org_id, "tr")
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

    # ── §3.3.3 Equipment Failure Registry ─────────────────────────────────────

    def _q_equipment_failure_annual(self, p: dict) -> list[dict]:
        """Annual Equipment Failure Report — grouped by type, make, model.
        Auto-generated each calendar year; also available on demand.
        Parameter: year (int, defaults to previous calendar year).
        Queries failure_registry direct submissions; failure_date is taken from
        the test_data JSONB field, not from test evaluation results.
        """
        org  = _org_clause(self.org_id, "tr")
        year = int(_p(p, "year", date.today().year - 1))
        sql  = text(f"""
            SELECT
                COALESCE(cm.name, 'Unknown Type')                               AS equipment_type,
                COALESCE(e.manufacturer, 'Unknown Make')                         AS make,
                COALESCE(e.model_number, e.voltage_class || ' kV', '—')        AS model_rating,
                COALESCE(e.voltage_class || ' kV', '—')                        AS voltage_class,
                COUNT(tr.id)                                                     AS failure_incidents,
                COUNT(DISTINCT tr.equipment_id)                                  AS units_affected,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Electrical'
                           THEN 1 END)                                           AS electrical,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Mechanical'
                           THEN 1 END)                                           AS mechanical,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Oil'
                           THEN 1 END)                                           AS oil,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Protection'
                           THEN 1 END)                                           AS protection,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Thermal'
                           THEN 1 END)                                           AS thermal,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Other'
                           THEN 1 END)                                           AS other_category,
                COUNT(CASE WHEN res.test_data->>'outcome' = 'Repair'
                           THEN 1 END)                                           AS repaired,
                COUNT(CASE WHEN res.test_data->>'outcome' = 'Replacement'
                           THEN 1 END)                                           AS replaced,
                COUNT(CASE WHEN res.test_data->>'outcome' = 'Under Investigation'
                           THEN 1 END)                                           AS under_investigation,
                ROUND(
                    AVG(NULLIF(res.test_data->>'outage_duration_hours', '')::numeric),
                1)                                                               AS avg_outage_hours,
                MAX((NULLIF(res.test_data->>'failure_date', ''))::date)         AS most_recent_failure
            FROM   public.testing_requests tr
            JOIN   public.test_results res ON res.testing_request_id = tr.id
            JOIN   public.equipment    e   ON e.id = tr.equipment_id
            LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
            WHERE  tr.request_category     = 'failure_registry'
              AND  tr.is_direct_submission  = TRUE
              AND  EXTRACT(YEAR FROM
                       (NULLIF(res.test_data->>'failure_date', ''))::date
                   ) = {year}
              {org}
            GROUP  BY cm.name, e.manufacturer, e.model_number, e.voltage_class
            ORDER  BY failure_incidents DESC NULLS LAST,
                      equipment_type, make, model_rating
        """)
        return self._exec(sql)

    def _q_equipment_failure_performance(self, p: dict) -> list[dict]:
        """On-demand Performance Analysis — failure rates across makes, types,
        voltage classes, and age bands.
        Filters: date_from, date_to, equipment_type, make, voltage_class, age_band.
        Queries failure_registry direct submissions; failure_date is taken from
        the test_data JSONB field, not from test evaluation results.
        """
        org = _org_clause(self.org_id, "tr")

        # Optional failure-date range filter (on test_data->>'failure_date')
        df = _date(_p(p, "date_from"))
        dt = _date(_p(p, "date_to"))
        date_clause = ""
        if df:
            date_clause += (
                f" AND (NULLIF(res.test_data->>'failure_date', ''))::date >= '{df}'"
            )
        if dt:
            date_clause += (
                f" AND (NULLIF(res.test_data->>'failure_date', ''))::date <= '{dt}'"
            )

        # Optional dimension filters (applied in WHERE)
        type_filter  = _p(p, "equipment_type", "")
        make_filter  = _p(p, "make", "")
        vcls_filter  = _p(p, "voltage_class", "")
        aband_filter = _p(p, "age_band", "")

        dim_clause = ""
        if type_filter:
            dim_clause += f" AND cm.name = '{type_filter}'"
        if make_filter:
            dim_clause += f" AND LOWER(e.manufacturer) LIKE LOWER('%{make_filter}%')"
        if vcls_filter:
            dim_clause += f" AND e.voltage_class = '{vcls_filter}'"
        if aband_filter:
            age_map = {
                "0-10 years":  "BETWEEN 0 AND 10",
                "10-20 years": "BETWEEN 11 AND 20",
                "20+ years":   "> 20",
            }
            if aband_filter in age_map:
                dim_clause += (
                    f" AND (EXTRACT(YEAR FROM NOW()) - e.year_of_manufacture)"
                    f" {age_map[aband_filter]}"
                )

        age_band_expr = """
            CASE
                WHEN e.year_of_manufacture IS NULL THEN 'Unknown'
                WHEN (EXTRACT(YEAR FROM NOW()) - e.year_of_manufacture) <= 10
                     THEN '0-10 years'
                WHEN (EXTRACT(YEAR FROM NOW()) - e.year_of_manufacture) <= 20
                     THEN '10-20 years'
                ELSE '20+ years'
            END"""

        sql = text(f"""
            SELECT
                COALESCE(cm.name, 'Unknown Type')                               AS equipment_type,
                COALESCE(e.manufacturer, 'Unknown Make')                         AS make,
                COALESCE(e.voltage_class || ' kV', '—')                        AS voltage_class,
                {age_band_expr}                                                  AS age_band,
                COUNT(tr.id)                                                     AS failure_incidents,
                COUNT(DISTINCT tr.equipment_id)                                  AS units_affected,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Electrical'
                           THEN 1 END)                                           AS electrical,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Mechanical'
                           THEN 1 END)                                           AS mechanical,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Oil'
                           THEN 1 END)                                           AS oil,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Protection'
                           THEN 1 END)                                           AS protection,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Thermal'
                           THEN 1 END)                                           AS thermal,
                COUNT(CASE WHEN res.test_data->>'failure_category' = 'Other'
                           THEN 1 END)                                           AS other_category,
                COUNT(CASE WHEN res.test_data->>'outcome' = 'Repair'
                           THEN 1 END)                                           AS repaired,
                COUNT(CASE WHEN res.test_data->>'outcome' = 'Replacement'
                           THEN 1 END)                                           AS replaced,
                COUNT(CASE WHEN res.test_data->>'outcome' = 'Under Investigation'
                           THEN 1 END)                                           AS under_investigation,
                ROUND(
                    COUNT(tr.id)::numeric
                    / NULLIF(COUNT(DISTINCT tr.equipment_id), 0),
                2)                                                               AS avg_failures_per_unit,
                ROUND(
                    AVG(NULLIF(res.test_data->>'outage_duration_hours', '')::numeric),
                1)                                                               AS avg_outage_hours
            FROM   public.testing_requests tr
            JOIN   public.test_results res ON res.testing_request_id = tr.id
            JOIN   public.equipment    e   ON e.id = tr.equipment_id
            LEFT JOIN public."CategoryMaster" cm ON cm.id = e.equipment_type_id
            WHERE  tr.request_category    = 'failure_registry'
              AND  tr.is_direct_submission = TRUE
              {date_clause}
              {org}
              {dim_clause}
            GROUP  BY cm.name, e.manufacturer, e.voltage_class,
                      {age_band_expr}
            ORDER  BY failure_incidents DESC NULLS LAST,
                      equipment_type, make, voltage_class
        """)
        return self._exec(sql)

    def _q_failure_resolution(self, p: dict) -> list[dict]:
        """Failure Resolution Report — one row per FR- record, joined to its
        downstream Repair Lifecycle TR (via source_failure_id) if one exists.

        Shows outcome (Repair / Replacement / Under Investigation / …),
        the linked RL- work-order status when applicable, and days-open.

        Parameters: date_from, date_to (filter on failure_date in test_data),
                    outcome ("all" | "Repair" | "Replacement" | "Under Investigation")
        """
        org = _org_clause(self.org_id, "fr")

        df = _date(_p(p, "date_from"))
        dt = _date(_p(p, "date_to"))
        date_clause = ""
        if df:
            date_clause += (
                f" AND (NULLIF(res.test_data->>'failure_date', ''))::date >= '{df}'"
            )
        if dt:
            date_clause += (
                f" AND (NULLIF(res.test_data->>'failure_date', ''))::date <= '{dt}'"
            )

        outcome_filter = _p(p, "outcome", "all")
        outcome_clause = ""
        if outcome_filter and outcome_filter != "all":
            safe = outcome_filter.replace("'", "''")
            outcome_clause = f" AND res.test_data->>'outcome' = '{safe}'"

        sql = text(f"""
            SELECT
                fr.request_number                                       AS fr_number,
                COALESCE(e.ueic, '—')                                  AS equipment_ueic,
                COALESCE(cm.name, '—')                                 AS equipment_type,
                COALESCE(e.manufacturer, '—')                          AS make,
                COALESCE(e.voltage_class || ' kV', '—')               AS voltage_class,
                COALESCE(d.name, '—')                                  AS department,
                COALESCE(org.name, '—')                                AS organization,
                COALESCE(res.test_data->>'failure_category', '—')      AS failure_category,
                (NULLIF(res.test_data->>'failure_date', ''))::date      AS failure_date,
                COALESCE(res.test_data->>'outcome', '—')               AS outcome,
                COALESCE(res.test_data->>'outage_duration_hours', '—') AS outage_hours,
                fr.status                                               AS fr_status,
                fr.cts::date                                            AS submitted_date,
                CASE
                    WHEN (NULLIF(res.test_data->>'failure_date', ''))::date IS NOT NULL
                    THEN CURRENT_DATE
                         - (NULLIF(res.test_data->>'failure_date', ''))::date
                END                                                     AS days_since_failure,
                rl.request_number                                       AS repair_tr_number,
                rl.status                                               AS repair_tr_status,
                rl.cts::date                                            AS repair_tr_created,
                TRIM(COALESCE(u.firstname, '') || ' '
                     || COALESCE(u.lastname, ''))                       AS submitted_by,
                res.remarks                                             AS remarks
            FROM   public.testing_requests fr
            JOIN   public.test_results res
                   ON res.testing_request_id = fr.id
            LEFT JOIN public.equipment         e   ON e.id   = fr.equipment_id
            LEFT JOIN public."CategoryMaster"  cm  ON cm.id  = e.equipment_type_id
            LEFT JOIN public.org_departments   d   ON d.id   = fr.department_id
            LEFT JOIN public.organizations     org ON org.id  = fr.organization_id
            LEFT JOIN public.users             u   ON u.id   = fr.originator_id
            LEFT JOIN public.testing_requests  rl
                   ON rl.source_failure_id  = fr.id
                  AND rl.request_category   = 'repair_lifecycle'
            WHERE  fr.request_category     = 'failure_registry'
              AND  fr.is_direct_submission  = TRUE
              {date_clause}
              {outcome_clause}
              {org}
            ORDER  BY failure_date DESC NULLS LAST, fr.cts DESC
        """)
        return self._exec(sql)

    # ── §3.5 Equipment Lifecycle & History ───────────────────────────────────

    def _q_equipment_lifecycle(self, p: dict) -> list[dict]:
        """Equipment Lifecycle Report — one row per equipment unit showing
        commissioned date, test count, failure count, last test date, and
        current status.  Scoped to the user's organisation.
        Parameters: department_id (UUID str), status (active|retired|under_repair),
                    voltage_class (str), date_from / date_to (commissioned date range).
        """
        org = _org_clause(self.org_id, "e")

        status_f  = _p(p, "status", "")
        vcls_f    = _p(p, "voltage_class", "")
        dept_f    = _p(p, "department_id", "")
        df        = _date(_p(p, "date_from"))
        dt        = _date(_p(p, "date_to"))

        extra = ""
        if status_f:
            extra += f" AND e.status = '{status_f}'"
        if vcls_f:
            extra += f" AND e.voltage_class = '{vcls_f}'"
        if dept_f:
            extra += f" AND e.department_id = '{dept_f}'::uuid"
        if df:
            extra += f" AND e.commissioned_date >= '{df}'"
        if dt:
            extra += f" AND e.commissioned_date <= '{dt}'"

        sql = text(f"""
            SELECT
                e.ueic,
                COALESCE(cm.name, '—')                              AS equipment_type,
                e.manufacturer,
                e.model_number,
                e.voltage_class                                     AS voltage_kv,
                e.year_of_manufacture,
                e.commissioned_date::date                           AS commissioned,
                e.status                                            AS current_status,
                COALESCE(d.name, '—')                              AS department,
                COUNT(DISTINCT tr.id)                               AS total_tests,
                COUNT(DISTINCT fr.id)                               AS total_failures,
                MAX(res.tested_at)::date                            AS last_tested,
                COALESCE(lr.overall_result, '—')                   AS last_test_result,
                e.retired_date::date                                AS retired_date,
                e.retirement_reason
            FROM   public.equipment e
            LEFT JOIN public."CategoryMaster" cm  ON cm.id  = e.equipment_type_id
            LEFT JOIN public.org_departments  d   ON d.id   = e.department_id
            LEFT JOIN public.testing_requests tr
                   ON tr.equipment_id = e.id
                  AND tr.request_category NOT IN ('failure_registry', 'taqc_inspection')
            LEFT JOIN public.testing_requests fr
                   ON fr.equipment_id = e.id
                  AND fr.request_category = 'failure_registry'
            LEFT JOIN public.test_results res ON res.testing_request_id = tr.id
            -- latest test result
            LEFT JOIN LATERAL (
                SELECT lr2.overall_result
                FROM   public.test_results lr2
                JOIN   public.testing_requests trx ON trx.id = lr2.testing_request_id
                WHERE  trx.equipment_id = e.id
                ORDER  BY lr2.tested_at DESC NULLS LAST
                LIMIT  1
            ) lr ON true
            WHERE  1=1
              {org}
              {extra}
            GROUP  BY e.id, e.ueic, cm.name, e.manufacturer, e.model_number,
                      e.voltage_class, e.year_of_manufacture, e.commissioned_date,
                      e.status, d.name, lr.overall_result,
                      e.retired_date, e.retirement_reason
            ORDER  BY e.ueic
        """)
        return self._exec(sql)

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
        ws.title = defn.name[:31]

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

        # Create table with dynamic column widths
        # Calculate rough column widths based on content
        col_count = len(headers)
        page_width = landscape(letter)[0] - 0.8*inch  # Account for margins
        col_width = page_width / col_count

        table = Table(table_data, colWidths=[col_width] * col_count)
        
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
                fmt = defn.output_format if defn.output_format in ("excel", "pdf") \
                      else "excel"
                # For annual reports auto-triggered in January, report on the previous year
                params: dict = {}
                if defn.frequency == "annual":
                    params = {"year": str(now.year - 1)}
                svc.generate(defn.id, params, fmt)
                count += 1
            except Exception as exc:
                print(f"[Reports] Scheduled '{defn.name}' failed: {exc}")
    finally:
        db.close()
    return count


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
    if defn.frequency == "annual":
        # Due on the 1st of January each year, after the previous year ends
        return (
            now.month == 1 and now.day <= 7           # first week of January
            and defn.last_generated_at.year < now.year  # not yet run this year
        )
    return False
