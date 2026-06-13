from dotenv import load_dotenv
load_dotenv()  # ✅ MUST be first before any other import

import os
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer
from database import Base, engine, SessionLocal
from middleware.auth_privilege import auth_and_privilege_middleware
from routers.file_download import router as file_download_router
from routers import (
    repair_workflow,
    surveillance_workflow,
    surveillance_dashboard,
    websocket_routes,
    workflow_dashboard,
)
from apscheduler.schedulers.background import BackgroundScheduler
from services.test_request_schedule_service import TestRequestScheduleService

logger = logging.getLogger(__name__)

# Routers
from routers import (
    auth,
    bank_document,
    bank_info,
    categories,
    company_product_certificates,
    company_product_supply_references,
    company_products,
    contacts,
    dashboard,
    divisions,
    erp_router,
    invoices,
    module,
    mongo_router,
    payments,
    plan,
    products,
    quotes,
    register,
    retainerinvoices,
    role,
    role_module_privileges,
    sales_orders,
    statements,
    subcategories,
    sync_full_erp,
    token,
    totp,
    user_addresses,
    userdocument,
    userrole,
    users,
    countries,
    states,
    company_tax_infos,
    company_tax_documents,
    category_master,
    category_details,
    cities,
    webhook_zoho,
    zoho_auth,
    zoho_dashboard,
    zoho_items,
    zoho_register,
)
from routers.kyc_router import router as kyc_router
from routers.customer_care import router as customer_care_router
from routers.vendor_directory import router as vendor_directory_router  # ✅ NEW

# Testing Request System
from routers import (
    testing_requests,
    testing,
    recommendations,
    approvals,
    procurement,
    testing_request_approvals,
    admin_tester_config,
    tester_assignment,
    org_test_templates,
    test_request_schedules,
    test_sessions,  # NEW: Multi-session testing
    session_comments,  # NEW: Session comments for approvers
    tester_locations,  # Tester-to-zone mapping
    direct_submissions,  # NEW: Failure Registry & TA&QC direct-submit modules
    annual_audits,       # Annual Audit observation workflow module
    test_register,       # NEW: Test Register — periodic maintenance catalogue
    test_schedule_dashboard,  # Test Schedule compliance matrix dashboard
)
from routers import cumulative  # Cumulative / Overhaul lifecycle module
from routers import calibration as calibration_router  # Calibration lifecycle module
from routers import precommission as precommission_router  # Pre-Commission QAP module

# Organization Multi-Tenancy
from routers import organizations, org_departments, org_users, org_roles

# Equipment Asset Register
from routers import equipment
from routers import equipment_type_kit_mappings

# Notification & Alert Engine
from routers import notifications as notifications_router
from routers import admin_notifications as admin_notifications_router
from routers import admin_notification_events as admin_notification_events_router

# Dashboard KPIs
from routers import dashboard_kpi
from routers import dashboard_role_kpi

# Reporting Suite
from routers import reporting as reporting_router
# Analytics Engine
from routers import analytics as analytics_router

# Workflow Engine
from routers import workflows

# ── APScheduler ──────────────────────────────────────────────────────────────
scheduler = BackgroundScheduler(timezone="UTC")

def _run_schedule_job():
    db = SessionLocal()
    try:
        result = TestRequestScheduleService.run_daily_scheduler(db)
        logger.info(
            f"[Scheduler] Test request schedule job: "
            f"created={result['created']} failed={result['failed']}"
        )
    except Exception as e:
        logger.error(f"[Scheduler] Job error: {e}")
    finally:
        db.close()

scheduler.add_job(
    _run_schedule_job,
    trigger="cron",
    hour=0,
    minute=0,
    id="daily_test_scheduler",
)

# Auto-transition elapsed multi-session tests (runs every hour)
def _check_elapsed_multi_session_tests():
    """Check for multi-session tests with elapsed end dates and auto-submit them."""
    db = SessionLocal()
    try:
        from services.auto_status_transition_service import AutoStatusTransitionService
        svc = AutoStatusTransitionService(db)
        count = svc.check_all_pending_multi_session_tests()
        if count > 0:
            logger.info(f"Auto-submitted {count} tests due to elapsed deadlines")
    except Exception as e:
        logger.error(f"Error in elapsed test check: {e}", exc_info=True)
    finally:
        db.close()

scheduler.add_job(
    _check_elapsed_multi_session_tests,
    trigger="cron",
    minute=0,  # Run at the start of every hour
    id="hourly_elapsed_test_check",
)


# ── Dispatch pending email/SMS notifications (every 1 minute) ────────────────
# fire() only enqueues (status='pending'); this job does the actual sending.
# Keeps notification logic completely out of the core API request path.
def _process_pending_notifications():
    db = SessionLocal()
    try:
        from services.notification_service import NotificationService
        result = NotificationService(db).process_pending_notifications()
        if result["total"]:
            logger.info(
                f"[Notif] Pending dispatch — "
                f"sent={result['sent']} failed={result['failed']} skipped={result['skipped']}"
            )
    except Exception as e:
        logger.error(f"[Notif] process_pending job error: {e}")
    finally:
        db.close()


scheduler.add_job(
    _process_pending_notifications,
    trigger="interval",
    minutes=1,
    id="notification_pending_job",
    max_instances=1,    # never run concurrently — prevents duplicate sends
    coalesce=True,      # if missed fires pile up, run once not multiple times
)


# ── Retry failed notifications (every 5 minutes) ─────────────────────────────
def _retry_failed_notifications():
    db = SessionLocal()
    try:
        from services.notification_service import NotificationService
        count = NotificationService(db).retry_failed()
        if count:
            logger.info(f"[Notif] Retried {count} failed notification(s)")
    except Exception as e:
        logger.error(f"[Notif] Retry job error: {e}")
    finally:
        db.close()


scheduler.add_job(
    _retry_failed_notifications,
    trigger="interval",
    minutes=5,
    id="notification_retry_job",
    max_instances=1,
    coalesce=True,
)


# Overdue & due-reminder check (runs daily at 07:00 UTC)
def _check_schedule_notifications():
    """
    Fully config-driven scheduler job.

    Reads every active NotificationScheduleRule row and evaluates each open TR.

    Supported trigger_type values (SRS §8.x):
      "due_soon"          — fires when due_date is within offset_days of today
      "overdue"           — fires when due_date < today
      "escalation"        — fires when due_date < today - offset_days
      "status_transition" — fires when req.status == rule.trigger_on_status
      "both"              — fires when BOTH time condition AND status condition match
                           (e.g. overdue by 5 days AND status still 'in_progress')

    If rule.advanced_conditions (JSONB) is set, it is evaluated as a JSON rule
    with AND/OR logic, overriding the simple column-based matching.

    applicable_categories  : restrict to matching request_category values; [] = all
    applicable_workflow_types: restrict to matching workflow/request_type values; [] = all

    Adding a new scheduler-based notification = INSERT a row into notification_schedule_rules.
    Zero code change required.
    """
    from datetime import date, timedelta
    db = SessionLocal()
    try:
        from models import (
            NotificationScheduleRule,
            ScheduleFrequency,
            TestingRequest,
            TestingRequestStatus,
        )
        from services.notification_service import NotificationService
        nsvc = NotificationService(db)
        today = date.today()

        # Cooldown days are now part of ScheduleFrequency.days — no separate dict needed.
        # Use ScheduleFrequency.cooldown(freq_str, default=N) for safe lookup.

        # Load all active rules
        all_rules = (
            db.query(NotificationScheduleRule)
            .filter(NotificationScheduleRule.is_active.is_(True))
            .all()
        )
        if not all_rules:
            logger.debug("[Notif] No active NotificationScheduleRules — skipping")
            return

        # Build per-org rule map; org-specific overrides global for same key
        from collections import defaultdict
        org_rules: dict = defaultdict(dict)   # org_id → {rule_key → rule}
        global_rules: dict = {}               # rule_key → rule

        for rule in all_rules:
            # Key includes offset_days and trigger_on_status so identical
            # event_type+trigger_type combos with different parameters coexist.
            key = (rule.event_type, rule.trigger_type,
                   rule.offset_days, rule.trigger_on_status)
            if rule.organization_id is None:
                global_rules[key] = rule
            else:
                org_rules[rule.organization_id][key] = rule

        # All statuses that represent an "open" test request
        open_statuses = (
            TestingRequestStatus.submitted,
            TestingRequestStatus.assigned,
            TestingRequestStatus.accepted,
            TestingRequestStatus.in_progress,
        )

        # Load all open TRs (with and without due_date for status_transition rules)
        requests = (
            db.query(TestingRequest)
            .filter(TestingRequest.status.in_(open_statuses))
            .all()
        )

        fired_total = 0

        def _evaluate_simple(rule, due, req_status_str: str) -> bool:
            """
            Evaluate simple column-based trigger conditions.
            Returns True if the rule matches this TR.
            """
            tt = rule.trigger_type
            off = rule.offset_days or 0

            if tt == "due_soon":
                if due is None:
                    return False
                window_end = today + timedelta(days=off)
                return today <= due <= window_end

            elif tt == "overdue":
                if due is None:
                    return False
                return due < today

            elif tt == "escalation":
                if due is None:
                    return False
                cutoff = today - timedelta(days=off)
                return due < cutoff

            elif tt == "status_transition":
                on_status = rule.trigger_on_status
                return bool(on_status and req_status_str == on_status)

            elif tt == "both":
                # BOTH time condition AND status condition must be true
                # Time condition: overdue by at least offset_days
                time_ok = False
                if due is not None:
                    cutoff = today - timedelta(days=off)
                    time_ok = due < cutoff if off > 0 else due < today

                on_status = rule.trigger_on_status
                status_ok = bool(on_status and req_status_str == on_status)
                return time_ok and status_ok

            elif tt == "recurring":
                # Pure frequency-based trigger — no date condition.
                # The cadence is enforced entirely by the cooldown dedup check below.
                return True

            return False

        def _evaluate_advanced(cond: dict, due, req_status_str: str) -> bool:
            """
            Evaluate advanced_conditions JSON rule.

            Supported format:
              { "and": [ <condition>, ... ] }
              { "or":  [ <condition>, ... ] }
              { "type": "due_soon",   "offset_days": N }
              { "type": "overdue",    "min_days": N }
              { "type": "status",     "on_status": "..." }
            """
            if "and" in cond:
                return all(
                    _evaluate_advanced(c, due, req_status_str)
                    for c in cond["and"]
                )
            if "or" in cond:
                return any(
                    _evaluate_advanced(c, due, req_status_str)
                    for c in cond["or"]
                )
            t = cond.get("type", "")
            if t == "due_soon":
                if due is None:
                    return False
                off = int(cond.get("offset_days", 15))
                return today <= due <= today + timedelta(days=off)
            if t in ("overdue", "overdue_by"):
                if due is None:
                    return False
                min_days = int(cond.get("min_days", cond.get("offset_days", 0)))
                return due < today - timedelta(days=min_days)
            if t == "status":
                return req_status_str == cond.get("on_status", "")
            return False

        # ── Pass 1: digest notifications grouped by (org, department, rule) ──────
        #
        # Instead of firing one notification per request (which floods recipients
        # with N emails for N overdue requests), we:
        #   1. Evaluate every rule against every open request
        #   2. Group matching requests by (org_id, department_id, event_type)
        #   3. Fire ONE digest notification per group with an HTML table of all
        #      matching requests — department_id scoping ensures each dept only
        #      sees its own requests
        #   4. Dedup at group level: skip the whole group if already sent today
        #
        from collections import defaultdict as _ddict
        from models import NotificationLog
        from datetime import datetime as _dt

        # digest_groups[(org_id, dept_id, event_type, rule_key)] = [req, ...]
        digest_groups: dict = _ddict(list)

        for req in requests:
            req_org = req.organization_id
            req_dept = getattr(req, "department_id", None)
            req_status_str = (
                req.status.value
                if hasattr(req.status, "value")
                else str(req.status or "")
            )
            try:
                due = (
                    req.due_date.date()
                    if req.due_date and hasattr(req.due_date, "date")
                    else req.due_date
                )
            except Exception:
                due = None

            req_cat = getattr(req.request_category, "value",
                              str(req.request_category or ""))
            req_wf  = nsvc._workflow_type(req) or ""

            # Merge global + org rules (skip recurring — handled in pass 2)
            effective: dict = {
                k: v for k, v in {**global_rules, **(org_rules.get(req_org, {}))}.items()
                if v.trigger_type != "recurring"
            }

            for key, rule in effective.items():
                event_type = key[0]
                try:
                    # ── Category filter ────────────────────────────────────
                    if rule.applicable_categories:
                        if req_cat not in rule.applicable_categories:
                            continue

                    # ── Equipment type filter ──────────────────────────────
                    eq_types = list(getattr(rule, "applicable_equipment_types", None) or [])
                    if eq_types:
                        _eq_obj = getattr(req, "equipment_type", None)
                        req_eq_type = (_eq_obj.name if _eq_obj else "") or ""
                        if req_eq_type not in eq_types:
                            continue

                    # ── Activity type filter (advanced_conditions) ─────────
                    adv_pre = getattr(rule, "advanced_conditions", None)
                    if adv_pre and isinstance(adv_pre, dict):
                        act_types = adv_pre.get("activity_types") or []
                        if act_types:
                            _tt_obj = getattr(req, "test_type", None)
                            req_activity = (_tt_obj.name if _tt_obj else "") or ""
                            if req_activity not in act_types:
                                continue

                    # ── Workflow type filter ───────────────────────────────
                    wf_types = list(getattr(rule, "applicable_workflow_types", None) or [])
                    if wf_types and req_wf and req_wf not in wf_types:
                        continue

                    # ── Evaluate trigger condition ─────────────────────────
                    adv = getattr(rule, "advanced_conditions", None)
                    if adv and set(adv.keys()) - {"activity_types"}:
                        matches = _evaluate_advanced(adv, due, req_status_str)
                    else:
                        matches = _evaluate_simple(rule, due, req_status_str)

                    if matches:
                        group_key = (req_org, req_dept, event_type, key)
                        digest_groups[group_key].append((req, due, rule))

                except Exception as _e:
                    logger.warning(
                        f"[Notif] Rule {event_type} eval failed for req {req.id}: {_e}"
                    )

        # ── Fire one digest per (org, department, event_type) group ───────────
        for (req_org, req_dept, event_type, rule_key), group in digest_groups.items():
            try:
                rule      = group[0][2]
                rule_freq = getattr(rule, "frequency", None)
                freq_str  = (
                    rule_freq.value
                    if rule_freq and hasattr(rule_freq, "value")
                    else (rule_freq or None)
                )
                cooldown_days = ScheduleFrequency.cooldown(freq_str, default=1)
                cutoff_dt = _dt.combine(
                    today - timedelta(days=cooldown_days - 1),
                    _dt.min.time()
                )

                # ── Dedup: skip if already sent for this org+dept+event today ─
                already = (
                    db.query(NotificationLog.id)
                    .filter(
                        NotificationLog.organization_id == req_org,
                        NotificationLog.event_type      == event_type,
                        NotificationLog.cts             >= cutoff_dt,
                        NotificationLog.source_id.in_(
                            [r.id for r, _, _ in group]
                        ),
                    )
                    .first()
                )
                if already:
                    continue

                # ── Build digest table ─────────────────────────────────────
                # Columns driven by rule.digest_columns (configured in the
                # Notification Center UI). Falls back to DEFAULT_DIGEST_COLUMNS
                # when NULL.
                table_html = NotificationService.build_digest_table(
                    group, today,
                    columns=getattr(rule, "digest_columns", None),
                )

                # ── Representative values for subject line ──────────────────
                first_req, first_due, _ = group[0]
                first_eq = (
                    getattr(getattr(first_req, "equipment", None), "ueic", "")
                    or getattr(getattr(first_req, "equipment_type", None), "name", "")
                    or "Equipment"
                )
                dept_name = getattr(getattr(first_req, "department", None), "name", "") or ""

                nsvc.fire(
                    event_type=event_type,
                    context={
                        # Digest-level variables
                        "digest_table":    table_html,
                        "digest_count":    str(len(group)),
                        "dept.name":       dept_name,
                        # Per-request fallbacks (used by SMS / inapp templates)
                        "equipment":       first_eq,
                        "equipment.ueic":  first_eq,
                        "request.number":  first_req.request_number or "",
                        "request.due_date": str(first_due or ""),
                        "due_date":        str(first_due or ""),
                        "days_remaining":  str(max((first_due - today).days, 0)) if first_due and first_due >= today else "0",
                        "days_overdue":    str(max((today - first_due).days, 0)) if first_due and first_due < today else "0",
                    },
                    organization_id=req_org,
                    department_id=req_dept,
                    source_id=first_req.id,
                    source_type="testing_request",
                    severity=rule.severity,
                    workflow_type=nsvc._workflow_type(first_req),
                    equipment_type=nsvc._equipment_type(first_req),
                    test_type=nsvc._test_type(first_req),
                )
                fired_total += len(group)

            except Exception as _e:
                logger.warning(
                    f"[Notif] Digest fire failed for {event_type} "
                    f"org={req_org} dept={req_dept}: {_e}"
                )

        # ── Pass 2: aggregate notifications (recurring trigger type) ──────────
        #
        # Each recurring rule fires ONE notification per org covering ALL matching
        # open requests — instead of one notification per request.  This is the
        # correct model for digest-style rules ("Weekly Open Tests Summary", etc.).
        #
        recurring_rules = [r for r in all_rules if r.trigger_type == "recurring"]

        if recurring_rules:
            from collections import defaultdict as _ddict
            from models import NotificationLog
            from datetime import datetime as _dt

            # Group open requests by org_id for fast lookup
            by_org: dict = _ddict(list)
            for req in requests:
                by_org[req.organization_id].append(req)

            for rule in recurring_rules:
                event_type = rule.event_type
                rule_freq  = getattr(rule, "frequency", None)
                freq_str   = (
                    rule_freq.value
                    if rule_freq and hasattr(rule_freq, "value")
                    else (rule_freq or None)
                )
                # Recurring rules default to weekly if no frequency set
                cooldown_days = ScheduleFrequency.cooldown(freq_str, default=7)
                cutoff_dt = _dt.combine(
                    today - timedelta(days=cooldown_days - 1),
                    _dt.min.time()
                )

                # Determine which orgs this rule applies to
                if rule.organization_id:
                    target_orgs = [rule.organization_id]
                else:
                    # Global rule: applies to every org that has open requests
                    target_orgs = list(by_org.keys())

                for org_id in target_orgs:
                    org_reqs = by_org.get(org_id, [])
                    if not org_reqs:
                        continue

                    # Apply category filter
                    if rule.applicable_categories:
                        filtered = [
                            r for r in org_reqs
                            if getattr(r.request_category, "value",
                                       str(r.request_category or ""))
                               in rule.applicable_categories
                        ]
                    else:
                        filtered = org_reqs

                    if not filtered:
                        continue

                    # Dedup at org level — source_id IS NULL for aggregate logs
                    try:
                        already = (
                            db.query(NotificationLog.id)
                            .filter(
                                NotificationLog.organization_id == org_id,
                                NotificationLog.event_type == event_type,
                                NotificationLog.source_id.is_(None),
                                NotificationLog.cts >= cutoff_dt,
                            )
                            .first()
                        )
                        if already:
                            continue

                        nsvc.notify_aggregate_summary(
                            event_type=event_type,
                            requests=filtered,
                            organization_id=org_id,
                            severity=rule.severity,
                        )
                        fired_total += 1
                    except Exception as _e:
                        logger.warning(
                            f"[Notif] Recurring rule {event_type} failed for org {org_id}: {_e}"
                        )

        if fired_total:
            logger.info(f"[Notif] Schedule job total fired={fired_total}")

    except Exception as e:
        logger.error(f"[Notif] Schedule notification job error: {e}")
    finally:
        db.close()


scheduler.add_job(
    _check_schedule_notifications,
    trigger="cron",
    hour=7,
    minute=0,
    id="schedule_notification_job",
)


# Monthly MIS Report (runs on the 1st of each month at 06:00 UTC)
# Collects per-org stats for the previous calendar month and fires
# notify_monthly_mis_report() → sends to Senior Management / Supervisory roles.
def _run_monthly_mis_report():
    """
    On the 1st of each month, count:
      - tests completed in the previous month
      - currently overdue open requests
      - eval_critical events triggered in the previous month
    Then fire notify_monthly_mis_report() per active organisation.
    """
    from datetime import date, datetime, timezone as _tz
    db = SessionLocal()
    try:
        from models import (
            TestingRequest,
            TestingRequestStatus,
            NotificationLog,
            Organization,
        )
        from services.notification_service import NotificationService

        today = date.today()
        # Only fire on the 1st; guard against accidental double-runs
        if today.day != 1:
            logger.debug("[Notif] Monthly MIS job skipped — not the 1st of the month")
            return

        # Stats window = previous calendar month
        this_month_start = datetime(today.year, today.month, 1, tzinfo=_tz.utc)
        # Previous month end = this month start (exclusive upper bound)
        prev_month_end   = this_month_start
        # Previous month start = go back 28–31 days and land on the 1st
        import calendar as _cal
        prev_year  = today.year if today.month > 1 else today.year - 1
        prev_month = today.month - 1 if today.month > 1 else 12
        prev_month_start = datetime(prev_year, prev_month, 1, tzinfo=_tz.utc)
        report_month = prev_month_start.strftime("%B %Y")

        open_statuses = [
            TestingRequestStatus.submitted,
            TestingRequestStatus.assigned,
            TestingRequestStatus.accepted,
            TestingRequestStatus.in_progress,
        ]

        orgs = db.query(Organization).filter(Organization.is_active.is_(True)).all()
        fired = 0

        for org in orgs:
            try:
                tests_completed = db.query(TestingRequest).filter(
                    TestingRequest.organization_id == org.id,
                    TestingRequest.status == TestingRequestStatus.completed,
                    TestingRequest.completed_at >= prev_month_start,
                    TestingRequest.completed_at <  prev_month_end,
                ).count()

                overdue_count = db.query(TestingRequest).filter(
                    TestingRequest.organization_id == org.id,
                    TestingRequest.status.in_(open_statuses),
                    TestingRequest.due_date < datetime(today.year, today.month, today.day,
                                                       tzinfo=_tz.utc),
                ).count()

                critical_count = db.query(NotificationLog).filter(
                    NotificationLog.organization_id == org.id,
                    NotificationLog.event_type == "eval_critical",
                    NotificationLog.cts >= prev_month_start,
                    NotificationLog.cts <  prev_month_end,
                ).count()

                nsvc = NotificationService(db)
                nsvc.notify_monthly_mis_report(
                    report_month=report_month,
                    tests_completed=tests_completed,
                    critical_count=critical_count,
                    overdue_count=overdue_count,
                    organization_id=org.id,
                )
                fired += 1
            except Exception as _oe:
                logger.warning(f"[Notif] MIS report failed for org {org.id}: {_oe}")

        if fired:
            logger.info(f"[Notif] Monthly MIS report fired for {fired} org(s) — {report_month}")

    except Exception as e:
        logger.error(f"[Notif] Monthly MIS report job error: {e}", exc_info=True)
    finally:
        db.close()


scheduler.add_job(
    _run_monthly_mis_report,
    trigger="cron",
    day=1,
    hour=6,
    minute=0,
    id="monthly_mis_report_job",
)


# Annual Audit SLA overdue check (runs daily at 09:00 UTC — design §14H)
def _annual_audit_overdue_check():
    db = SessionLocal()
    try:
        from services.annual_audit_service import AnnualAuditService

        class _SystemUser:
            id = None
            organization_id = None

        result = AnnualAuditService(db).run_overdue_check(_SystemUser())
        if result.get("updated"):
            logger.info(f"[AnnualAudit] Overdue check: {result['updated']} observation(s) updated")
    except Exception as e:
        logger.error(f"[AnnualAudit] Overdue check job error: {e}", exc_info=True)
    finally:
        db.close()


scheduler.add_job(
    _annual_audit_overdue_check,
    trigger="cron",
    hour=9,
    minute=0,
    id="annual_audit_overdue_check_job",
)


# Calibration pre-due check (runs daily at 08:00 UTC)
# Auto-creates new calibration TestingRequests for equipment where
# today >= next_due - lead_days and no open calibration request exists.
def _calibration_pre_due_check():
    db = SessionLocal()
    try:
        from services.calibration_service import CalibrationService
        result = CalibrationService(db).run_pre_due_check()
        if result.get("created"):
            logger.info(
                f"[Calibration] Pre-due check: {result['created']} request(s) auto-created"
            )
    except Exception as e:
        logger.error(f"[Calibration] Pre-due check job error: {e}", exc_info=True)
    finally:
        db.close()


scheduler.add_job(
    _calibration_pre_due_check,
    trigger="cron",
    hour=8,
    minute=0,
    id="calibration_pre_due_check_job",
)


# Scheduled report generation (runs every hour, service decides which are due)
def _run_scheduled_reports():
    from services.reporting_service import run_scheduled_reports
    try:
        run_scheduled_reports(SessionLocal)
    except Exception as e:
        logger.error(f"[Reports] Scheduled report job error: {e}", exc_info=True)


scheduler.add_job(
    _run_scheduled_reports,
    trigger="cron",
    minute=0,   # top of every hour
    id="scheduled_report_job",
)

# ── App Init ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Customer Portal API",
    docs_url=None,   # ✅ disable default /docs (we override below)
    redoc_url=None,
)

# ── Custom Swagger UI ─────────────────────────────────────────────────────────
INTERNAL_SECRET = os.getenv("INTERNAL_SERVICE_SECRET", "")
print(f"[STARTUP] INTERNAL_SERVICE_SECRET loaded: '{INTERNAL_SECRET}'")  # verify in terminal
print(f"[STARTUP] VENDOR_APP_URL: '{os.getenv('VENDOR_APP_URL', 'NOT SET')}'")

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui():
    return HTMLResponse(f"""
<!DOCTYPE html>
<html>
<head>
    <title>Customer Portal API - Swagger UI</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" type="text/css"
          href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
    SwaggerUIBundle({{
        url: "/openapi.json",
        dom_id: '#swagger-ui',
        presets: [
            SwaggerUIBundle.presets.apis,
            SwaggerUIBundle.SwaggerUIStandalonePreset
        ],
        layout: "BaseLayout",
        requestInterceptor: (request) => {{
            request.headers['secret'] = '{INTERNAL_SECRET}';
            return request;
        }}
    }});
</script>
</body>
</html>
""")

@app.get("/redoc", include_in_schema=False)
async def custom_redoc():
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Customer Portal API - ReDoc</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <redoc spec-url='/openapi.json'></redoc>
    <script src="https://cdn.jsdelivr.net/npm/redoc/bundles/redoc.standalone.js"></script>
</body>
</html>
""")

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:53232",
        "http://127.0.0.1:53232",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Global Middleware ─────────────────────────────────────────────────────────
app.middleware("http")(auth_and_privilege_middleware)

security = HTTPBearer()

# ── Routers ───────────────────────────────────────────────────────────────────

# Authentication & Token
app.include_router(token.router)
app.include_router(auth.router)
app.include_router(register.router)
app.include_router(totp.totp_router)

# User & Roles
app.include_router(users.router)
app.include_router(userrole.user_role_router)
app.include_router(role.router)
app.include_router(role_module_privileges.router)

# Master Data & Categories
app.include_router(categories.router)
app.include_router(subcategories.router)
app.include_router(category_master.router)
app.include_router(category_details.router)
app.include_router(products.router)
app.include_router(company_products.router)

# Company & Finance
app.include_router(company_tax_infos.router)
app.include_router(company_tax_documents.router)
app.include_router(bank_document.router)
app.include_router(bank_info.router)
app.include_router(company_product_certificates.router)
app.include_router(company_product_supply_references.router)

# Location & Divisions
app.include_router(divisions.router)
app.include_router(user_addresses.router)
app.include_router(countries.router)
app.include_router(states.router)
app.include_router(cities.router)

# Dashboard, Module & Plan
app.include_router(dashboard.router)
app.include_router(module.router)
app.include_router(plan.router)

# User documents
app.include_router(userdocument.router)

# ERP Sync
app.include_router(sync_full_erp.router)

# KYC
app.include_router(kyc_router)

app.include_router(file_download_router)
app.include_router(erp_router.router)
app.include_router(mongo_router.router)
app.include_router(quotes.router)
app.include_router(zoho_items.router)
app.include_router(zoho_auth.router)
app.include_router(invoices.router)
app.include_router(payments.router)
app.include_router(contacts.router)
app.include_router(retainerinvoices.router)
app.include_router(sales_orders.router)
app.include_router(zoho_dashboard.router)
app.include_router(statements.router)
app.include_router(zoho_register.router)
app.include_router(webhook_zoho.router)
app.include_router(customer_care_router)

# Testing Request System
app.include_router(testing_requests.router)
app.include_router(testing.router)
app.include_router(test_sessions.router)  # NEW: Multi-session testing
app.include_router(session_comments.router)  # NEW: Session comments for approvers
app.include_router(tester_locations.router)  # Tester-to-zone mapping
app.include_router(recommendations.router)
app.include_router(approvals.router)
app.include_router(testing_request_approvals.router)
app.include_router(admin_tester_config.router)
app.include_router(procurement.router)
app.include_router(tester_assignment.router)
app.include_router(org_test_templates.router)
app.include_router(org_test_templates.browser_router)
app.include_router(test_request_schedules.router)
app.include_router(test_schedule_dashboard.router)  # Compliance matrix dashboard
app.include_router(direct_submissions.router)  # NEW: Failure Registry & TA&QC
app.include_router(annual_audits.router)       # Annual Audit observations
app.include_router(test_register.router)       # NEW: Test Register catalogue
app.include_router(cumulative.router)          # Cumulative / Overhaul lifecycle
app.include_router(calibration_router.router)  # Calibration lifecycle
app.include_router(precommission_router.router)  # Pre-Commission QAP

# Equipment Asset Register
app.include_router(equipment.router)
app.include_router(equipment_type_kit_mappings.router)

# Notification & Alert Engine
app.include_router(notifications_router.router)
app.include_router(admin_notifications_router.router)
app.include_router(admin_notification_events_router.router)

# Dashboard KPIs
app.include_router(dashboard_kpi.router)
app.include_router(dashboard_role_kpi.router)

# Reporting Suite
app.include_router(reporting_router.router)
# Analytics Engine
app.include_router(analytics_router.router)

# Organization Multi-Tenancy
app.include_router(organizations.router)
app.include_router(org_departments.router)
app.include_router(org_users.router)
app.include_router(org_roles.router)

# Workflow Engine
app.include_router(workflows.router)

# Repair Lifecycle Workflow
app.include_router(repair_workflow.router)

# Surveillance Workflow (Post-Commissioning Monitoring)
app.include_router(surveillance_workflow.router)
app.include_router(surveillance_dashboard.router)

# Unified Workflow Operations Dashboard
app.include_router(workflow_dashboard.router)

# WebSocket
app.include_router(websocket_routes.router)

# ✅ Vendor Directory — fetches vendors from supplier portal
app.include_router(vendor_directory_router)

# ── Lifecycle ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    scheduler.start()
    logger.info(
        "[Scheduler] APScheduler started — "
        "daily test request job scheduled at 00:00 UTC"
    )
    # Register workflow lifecycle hooks (import = self-registration side-effect)
    import calibration_hooks  # noqa: F401
    import overhaul_hooks  # noqa: F401
    import surveillance_hooks  # noqa: F401
    logger.info("[Hooks] Workflow lifecycle hooks registered")

    # Seed pre-commission QAP workflow stages + org role mappings (idempotent)
    try:
        _db = SessionLocal()
        from seed_precommission_workflow import (
            seed_precommission_stages,
            seed_precommission_role_mappings,
        )
        from models import Organization
        seed_precommission_stages(_db)
        # Seed role mappings only for orgs that have the required OrgRoles
        from models import OrgRole
        _orgs = _db.query(Organization).filter(Organization.is_active.is_(True)).all()
        seeded = 0
        for _org in _orgs:
            has_roles = _db.query(OrgRole).filter_by(
                organization_id=_org.id, name="EE_TLSS"
            ).first()
            if not has_roles:
                continue
            try:
                seed_precommission_role_mappings(_db, _org.id)
                seeded += 1
            except Exception as _re:
                logger.warning(f"[Seed] PCR role mapping failed for org {_org.id}: {_re}")
        _db.close()
        logger.info(f"[Seed] Pre-commission QAP workflow staged + role mappings seeded for {seeded} org(s)")
    except Exception as _e:
        logger.warning(f"[Seed] Pre-commission seed failed on startup (non-fatal): {_e}")

    # Seed DFR + Tan-Delta/IDAX templates — idempotent upsert on every restart
    try:
        _db = SessionLocal()
        from seed import seed_dfr_template, seed_tan_delta_templates
        seed_dfr_template(_db)
        seed_tan_delta_templates(_db)
        _db.close()
        logger.info("[Seed] DFR + Tan-Delta/IDAX templates upserted on startup")
    except Exception as _e:
        logger.warning(f"[Seed] DFR/Tan-Delta template seed failed on startup (non-fatal): {_e}")

    # Seed all notification defaults (event catalogue, variables, templates,
    # schedule rules, routing rules) — idempotent, safe to run on every restart
    try:
        _db = SessionLocal()
        from seed import seed_notification_defaults
        _counts = seed_notification_defaults(_db)
        _db.close()
        _total = sum(_counts.values())
        if _total:
            logger.info(
                f"[Notif] Seeded notification defaults on startup: "
                f"events={_counts['event_catalogue']}, "
                f"vars={_counts['variables']}, "
                f"templates={_counts['templates']}, "
                f"schedule_rules={_counts['schedule_rules']}, "
                f"routing_rules={_counts['routing_rules']}"
            )
    except Exception as _e:
        logger.warning(f"[Notif] Notification seed failed on startup (non-fatal): {_e}")

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown(wait=False)
    logger.info("[Scheduler] APScheduler stopped")
