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
from routers import repair_workflow, websocket_routes
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
    test_register,       # NEW: Test Register — periodic maintenance catalogue
)

# Organization Multi-Tenancy
from routers import organizations, org_departments, org_users, org_roles

# Equipment Asset Register
from routers import equipment

# Notification & Alert Engine
from routers import notifications as notifications_router
from routers import admin_notifications as admin_notifications_router

# Dashboard KPIs
from routers import dashboard_kpi

# Reporting Suite
from routers import reporting as reporting_router

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
)


# Overdue & due-reminder check (runs daily at 07:00 UTC)
def _check_overdue_and_due_reminders():
    """
    Scan open testing requests:
    • due_date passed → notify_overdue
    • due_date within 3 days → notify_due_reminder
    """
    from datetime import date, timedelta
    db = SessionLocal()
    try:
        from models import TestingRequest, TestingRequestStatus
        from services.notification_service import NotificationService
        nsvc = NotificationService(db)
        today = date.today()
        reminder_cutoff = today + timedelta(days=3)

        open_statuses = (
            TestingRequestStatus.submitted,
            TestingRequestStatus.assigned,
            TestingRequestStatus.accepted,
            TestingRequestStatus.in_progress,
        )
        requests = (
            db.query(TestingRequest)
            .filter(
                TestingRequest.status.in_(open_statuses),
                TestingRequest.due_date.isnot(None),
            )
            .all()
        )
        overdue = 0
        reminded = 0
        for req in requests:
            try:
                due = req.due_date.date() if hasattr(req.due_date, "date") else req.due_date
                if due < today:
                    nsvc.notify_overdue(req)
                    overdue += 1
                elif due <= reminder_cutoff:
                    nsvc.notify_due_reminder(req)
                    reminded += 1
            except Exception as _e:
                logger.warning(f"[Notif] Overdue check failed for req {req.id}: {_e}")
        if overdue or reminded:
            logger.info(f"[Notif] Overdue alerts: {overdue}, Due reminders: {reminded}")
    except Exception as e:
        logger.error(f"[Notif] Overdue check job error: {e}")
    finally:
        db.close()


scheduler.add_job(
    _check_overdue_and_due_reminders,
    trigger="cron",
    hour=7,
    minute=0,
    id="overdue_due_reminder_job",
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
app.include_router(direct_submissions.router)  # NEW: Failure Registry & TA&QC
app.include_router(test_register.router)       # NEW: Test Register catalogue

# Equipment Asset Register
app.include_router(equipment.router)

# Notification & Alert Engine
app.include_router(notifications_router.router)
app.include_router(admin_notifications_router.router)

# Dashboard KPIs
app.include_router(dashboard_kpi.router)

# Reporting Suite
app.include_router(reporting_router.router)

# Organization Multi-Tenancy
app.include_router(organizations.router)
app.include_router(org_departments.router)
app.include_router(org_users.router)
app.include_router(org_roles.router)

# Workflow Engine
app.include_router(workflows.router)

# WebSocket
app.include_router(websocket_routes.router)
app.include_router(repair_workflow.router)

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
    # Seed default notification templates + variables (idempotent)
    try:
        _db = SessionLocal()
        from services.notification_service import seed_default_templates, seed_default_variables
        seeded_t = seed_default_templates(_db)
        seeded_v = seed_default_variables(_db)
        if seeded_t:
            logger.info(f"[Notif] Seeded {seeded_t} default notification template(s) on startup")
        if seeded_v:
            logger.info(f"[Notif] Seeded {seeded_v} default notification variable(s) on startup")
        _db.close()
    except Exception as _e:
        logger.warning(f"[Notif] Seed failed on startup (non-fatal): {_e}")

@app.on_event("shutdown")
async def shutdown_event():
    scheduler.shutdown(wait=False)
    logger.info("[Scheduler] APScheduler stopped")