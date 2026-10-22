import re

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session
from database import SessionLocal
from models import (
    Module, UserRole, RoleModulePrivilege, User, OrgUserRole, OrgRolePermission,
    TestingRequest, TestResult, TestResultImage, TrWfInstance, TrWfStage,
    TrWfStageInstance, TrWfStageRole,
)
import auth_utils
from middleware.org_auth import has_workflow_module_view
from fastapi import Request

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# --------------------------------------------------
# Modules whose access, for a call scoped to one specific TestingRequest,
# is decided by tr_wf_stage_roles.can_act_as_tester on that request's
# current active workflow stage — NOT by OrgRolePermission. A call to one
# of these modules that isn't scoped to a specific request (no TestingRequest
# UUID in the path — list/reference endpoints like /testing/my-assignments
# or /equipment/types-by-category/12) still falls back to OrgRolePermission,
# since there's no stage to check against.
# --------------------------------------------------
STAGE_BASED_MODULES = {"testing", "testing_requests", "equipment"}

# --------------------------------------------------
# Shared read-only lookups under the testing / testing_requests / equipment
# routers — GET only, matched on the path's second segment.
#
# These routers were built for CM Testing, but TA&QC Inspection, Failure
# Registry, Pre/Post Commissioning, and the Repair / Overhaul / Calibration
# stage forms all reuse them for form templates and reference lists. Since
# the module is resolved from the first path segment alone, a role with full
# access to its own workflow module still got "Access denied for 'can_view'
# on 'testing'" just loading its form. Every endpoint listed here is a
# template or reference list scoped to the caller's own org — no testing
# request, result or asset record is returned. Writes and record-level reads
# on these routers still go through the normal OrgRolePermission check.
# Matching handler-level checks in routers/equipment.py are skipped for the
# same endpoints.
# --------------------------------------------------
SHARED_LOOKUP_GETS = {
    "testing": {"templates"},
    "testing_requests": {
        "department_hierarchy", "department_search", "department_ancestors",
        "equipment_types", "kit-subtypes", "request-categories",
        "test-evaluation-statuses", "lifecycle-types", "all-test-types",
        "dropdown",
    },
    "equipment": {
        "types-by-category", "types-by-test-type", "testing-kits",
        "substations", "divisions", "circles", "zones",
    },
}


def _assigned_current_stage(db, instance, user_id):
    """True if the instance's current in-progress stage is assigned to
    user_id (e.g. an @originator stage, which has no real role to hold) —
    the same rule the approvals queue lists it by."""
    return user_id is not None and (
        db.query(TrWfStageInstance.id)
        .filter(
            TrWfStageInstance.wf_instance_id == instance.id,
            TrWfStageInstance.stage_id == instance.current_stage_id,
            TrWfStageInstance.status == "in_progress",
            TrWfStageInstance.assigned_user_id == user_id,
        )
        .first()
        is not None
    )


def _find_stage_gate(db, parts, org_role_ids, user_id=None, method=None):
    """
    Look for a TestingRequest.id among the URL's path segments. If one is
    found, return True/False for whether the caller's org role(s) are the
    active tester on that request's current active workflow stage — this
    REPLACES the OrgRolePermission check entirely for that call. Returns
    None if no TestingRequest is named in the path, meaning the caller
    should fall back to the normal OrgRolePermission check.

    The user the current stage is assigned to may also read (GET) the
    request, so the item the approvals queue shows them can be opened.
    Writes still need a tester role.

    Checks can_edit OR can_act_as_tester on tr_wf_stage_roles. can_edit is
    the flag the rest of the app already treats as "is the tester for this
    stage" (see overview_dashboard.dart's canTest, which falls back to
    can_edit because can_act_as_tester is inconsistently populated across
    workflows — confirmed live: of 58 tr_wf_stage_roles rows, 17 have
    can_edit=True and only 12 have can_act_as_tester=True, with ZERO
    overlap between the two sets). Checking can_act_as_tester alone here
    meant a tester the rest of the app recognized (can_edit=True) could
    still get a hard 403 fetching their own assigned request's details —
    which is exactly what broke the Testing Kit dropdown on Submit Test
    Results for AE-R&D at the "L4 Test Execution" stage. OR'ing in
    can_act_as_tester keeps the 12 existing grants that rely on it alone
    working unchanged.
    """
    for segment in parts[1:]:
        if not _UUID_RE.match(segment):
            continue
        testing_request = db.query(TestingRequest).filter_by(id=segment).first()
        if not testing_request:
            continue

        instance = (
            db.query(TrWfInstance)
            .filter(
                TrWfInstance.testing_request_id == testing_request.id,
                TrWfInstance.status == "active",
            )
            .first()
        )
        if not instance or not instance.current_stage_id:
            return None

        allowed = (
            db.query(TrWfStageRole)
            .filter(
                TrWfStageRole.stage_id == instance.current_stage_id,
                TrWfStageRole.role_id.in_(org_role_ids),
                or_(
                    TrWfStageRole.can_edit == True,
                    TrWfStageRole.can_act_as_tester == True,
                ),
            )
            .first()
        )
        if allowed:
            return True
        return method == "GET" and _assigned_current_stage(db, instance, user_id)
    return None


def _denied_detail(action, module_name, module):
    """403 text naming the Role Permission module that actually gates the call.

    The URL segment alone ('testing', 'equipment') hid that these routers are
    shared by other features, so whoever configured a role couldn't tell which
    module to grant. The original "Access denied for '<action>' on '<segment>'"
    prefix is kept for anything matching on it.
    """
    return (
        f"Access denied for '{action}' on '{module_name}' - grant it on the "
        f"'{module.name}' module in Role Permission"
    )


def _workflow_viewer(db, testing_request_id, org_role_ids, user_id):
    """True if the caller has a part in the request's workflow: a stage role
    on any stage of its definition (any status, so reviewers and approvers
    who are never the active tester qualify, as do closed requests), or a
    stage instance of it assigned to them (e.g. an @originator stage)."""
    instance = (
        db.query(TrWfInstance)
        .filter(TrWfInstance.testing_request_id == testing_request_id)
        .first()
    )
    if not instance:
        return False
    if instance.wf_definition_id and (
        db.query(TrWfStageRole.id)
        .join(TrWfStage, TrWfStage.id == TrWfStageRole.stage_id)
        .filter(
            TrWfStage.wf_definition_id == instance.wf_definition_id,
            TrWfStageRole.role_id.in_(org_role_ids),
            or_(
                TrWfStageRole.can_view == True,
                TrWfStageRole.can_edit == True,
                TrWfStageRole.can_approve == True,
                TrWfStageRole.can_assign == True,
                TrWfStageRole.can_act_as_tester == True,
            ),
        )
        .first()
        is not None
    ):
        return True
    return user_id is not None and (
        db.query(TrWfStageInstance.id)
        .filter(
            TrWfStageInstance.wf_instance_id == instance.id,
            TrWfStageInstance.assigned_user_id == user_id,
        )
        .first()
        is not None
    )


def _record_access_via_workflow(db, method, parts, org_role_ids, user_id):
    """
    Result and report records that workflow screens (Result Review, the
    approvals queue, Failure Registry, the Repair/Overhaul/Calibration result
    form) read or attach to, granted by the caller's part in the request's
    workflow instead of Testing / CM Testing Request permission:

    - GET /testing/results/{result_id}/preview|pdf
    - GET /testing/results/images/{image_id}
    - GET /testing_requests/{request_id}/report/preview|pdf
        -> _workflow_viewer
    - POST /testing/results/{result_id}/images
        -> active tester on the request's current stage, the same rule
           _find_stage_gate applies to saving the result itself

    The result / image id isn't a TestingRequest id, so _find_stage_gate
    never matched those; the report path names the request, but the gate
    only lets the active tester through. False means "not granted this
    way" — the caller then falls through to the normal checks, so roles
    with Testing / CM Testing Request permission keep working.
    """
    n = len(parts)
    tr_id = None
    if parts[0] == "testing" and n >= 3 and parts[1] == "results":
        if method == "GET" and n == 4 and parts[2] == "images" and _UUID_RE.match(parts[3]):
            image = db.query(TestResultImage).filter_by(id=parts[3]).first()
            result = image and db.query(TestResult).filter_by(id=image.test_result_id).first()
        elif n == 4 and _UUID_RE.match(parts[2]) and (
            (method == "GET" and parts[3] in ("preview", "pdf"))
            or (method == "POST" and parts[3] == "images")
        ):
            result = db.query(TestResult).filter_by(id=parts[2]).first()
        else:
            return False
        tr_id = result.testing_request_id if result else None
    elif (
        parts[0] == "testing_requests" and method == "GET" and n == 4
        and _UUID_RE.match(parts[1]) and parts[2] == "report"
        and parts[3] in ("preview", "pdf")
    ):
        tr_id = parts[1]
    if not tr_id:
        return False

    if method == "POST":
        return bool(_find_stage_gate(db, ["testing", str(tr_id)], org_role_ids))
    return _workflow_viewer(db, tr_id, org_role_ids, user_id)

async def auth_and_privilege_middleware(request: Request, call_next):

    # ✅ Allow CORS preflight requests (VERY IMPORTANT)
    if request.method == "OPTIONS":
        return await call_next(request)

    # ---- existing auth logic below ----

# --------------------------------------------------
# Public endpoints (NO authentication required)
#
# CRITICAL: every real path starts with "/", so a bare "/" or "/api" entry
# here makes `path.startswith(p)` true for EVERY request, bypassing auth and
# the whole privilege system for the entire API — not just the literal root.
# The true root ("/", "/api", "/api/" exactly) is already handled correctly
# above by exact match, so those entries never belonged in a startswith()
# list and have been removed. Keep every future entry here either an exact
# leaf path or a genuine "/namespace/" prefix — never a path fragment that
# could also be the start of something unrelated.
# --------------------------------------------------
PUBLIC_ENDPOINTS = [
    "/token",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/register/",
    "/auth/",
    "/files/",
    "/health",      # external load-test monitoring poll - no auth token available
    "/billing/webhook",   # Razorpay webhook — no auth
    "/billing/plans",     # Plan list — no auth needed
]

# --------------------------------------------------
# Optional-auth endpoints: never require a token (no 401 for a missing or
# invalid one), but if a valid Bearer token IS present, current_user gets
# resolved onto request.state.user same as a normal authenticated request —
# so a route can personalize its response for a logged-in caller while still
# answering an anonymous one. Different from PUBLIC_ENDPOINTS, which never
# even attempts to resolve a user.
# --------------------------------------------------
AUTH_PUBLIC_ENDPOINTS = [
    "/public-config",   # safe non-secret settings (e.g. max_upload_mb) - fetched by the UI before login
]

# --------------------------------------------------
# HTTP method → privilege mapping
# --------------------------------------------------
METHOD_ACTION_MAP = {
    "GET": "can_view",
    "POST": "can_add",
    "PUT": "can_edit",
    "DELETE": "can_delete",
}

# --------------------------------------------------
# API prefix → module path mapping
# Maps backend route prefixes to their registered module path in the modules table
# --------------------------------------------------
API_TO_MODULE_PATH = {
    "billing": "subscription-billing",
}


async def auth_and_privilege_middleware(request: Request, call_next):
    """
    Global authentication + privilege middleware
    """

    # --------------------------------------------------
    # Normalize path
    # Example:
    #   /api/addresses/5 -> /addresses/5
    # --------------------------------------------------
    raw_path = request.url.path.lower()
    path = raw_path[4:] if raw_path.startswith("/api/") else raw_path

    # --------------------------------------------------
    # 1. Allow OPTIONS (CORS preflight)
    # --------------------------------------------------
    if request.method == "OPTIONS":
        return await call_next(request)

    # --------------------------------------------------
    # 2. Allow API root (/api or /)
    # --------------------------------------------------
    if raw_path in ("/", "/api", "/api/"):
        return await call_next(request)

    # --------------------------------------------------
    # 4. Allow public endpoints
    # --------------------------------------------------
    if any(path.startswith(p) for p in PUBLIC_ENDPOINTS):
        return await call_next(request)

    # --------------------------------------------------
    # 4b. Optional-auth endpoints — resolve current_user if a valid token
    # happens to be present, but never reject the request for a missing or
    # invalid one.
    # --------------------------------------------------
    if any(path.startswith(p) for p in AUTH_PUBLIC_ENDPOINTS):
        auth_header = (
            request.headers.get("Authorization")
            or request.headers.get("authorization")
        )
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]
            payload = auth_utils.decode_access_token(token)
            user_id = payload.get("sub") if payload else None
            if user_id:
                db = SessionLocal()
                try:
                    user = db.query(User).filter_by(id=user_id).first()
                    if user:
                        request.state.user = user
                finally:
                    db.close()
        return await call_next(request)

    # --------------------------------------------------
    # DB session
    # --------------------------------------------------
    db: Session = SessionLocal()

    try:
        # --------------------------------------------------
        # AUTHENTICATION
        # --------------------------------------------------
        auth_header = (
            request.headers.get("Authorization")
            or request.headers.get("authorization")
        )

        # Allow token as query param for browser-navigated URLs (HTML/PDF reports)
        if not auth_header:
            q_token = request.query_params.get("token")
            if q_token:
                auth_header = f"Bearer {q_token}"

        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Unauthorized: Missing or invalid token header",
            )

        token = auth_header.split(" ", 1)[1]
        payload = auth_utils.decode_access_token(token)

        if not payload:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token",
            )

        # Payment token (scope=billing) — allow only /billing/* paths
        if payload.get("scope") == "billing":
            if path.startswith("/billing/"):
                db.close()
                return await call_next(request)
            raise HTTPException(status_code=403, detail="Payment token only valid for billing endpoints")

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=401,
                detail="Invalid token payload",
            )

        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(
                status_code=401,
                detail="User not found",
            )

        # Block all requests if the user's organisation is disabled or trial expired
        print(f"[TRIAL-DEBUG] user={user.id} org_id={user.organization_id}")
        if user.organization_id:
            from models import Organization
            from datetime import datetime, timezone
            org = db.query(Organization).filter_by(id=user.organization_id).first()
            print(f"[TRIAL-DEBUG] org={org and org.name} is_trial={org and org.is_trial} trial_end={org and org.trial_end_date} is_active={org and org.is_active}")
            if org and not org.is_active:
                raise HTTPException(
                    status_code=403,
                    detail="Your organisation has been disabled. Please contact support.",
                )
            if org and org.is_trial and org.trial_end_date:
                now = datetime.now(timezone.utc)
                trial_end = org.trial_end_date if org.trial_end_date.tzinfo else org.trial_end_date.replace(tzinfo=timezone.utc)
                print(f"[TRIAL] org={org.name} trial_end={trial_end} now={now} expired={trial_end < now}")
                if trial_end < now:
                    if org.trial_status != "expired":
                        org.trial_status = "expired"
                        try:
                            db.commit()
                        except Exception:
                            db.rollback()
                    raise HTTPException(
                        status_code=403,
                        detail="Your 30-day free trial has ended. Please contact us to continue using the platform.",
                    )

        request.state.user = user

        # --------------------------------------------------
        # Org admins bypass every module/stage-gate check below — the same
        # blanket-access bypass already applied via has_org_admin_role() in
        # routers/equipment.py's _require_permission() and elsewhere.
        # Without it here, an org admin whose role has no TrWfStageRole row
        # for a ticket's CURRENT stage got a hard 403 like any other role —
        # confirmed live: orgadmin@utility.com (is_org_admin=True) 403'd on
        # GET /testing_requests/{id} for a ticket sitting at "L2 Approval &
        # Route", a stage no admin role is (or should need to be)
        # explicitly listed on.
        # --------------------------------------------------
        if auth_utils.has_org_admin_role(user, db):
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # Skip privilege check for KYC
        # --------------------------------------------------
        if path.startswith("/kyc/"):
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # Skip privilege check for logout
        #
        # POST /users/logout was being gated on can_add for the "users"
        # module (POST -> can_add per METHOD_ACTION_MAP) — a role with no
        # user-creation permission (i.e. most roles) couldn't log out at
        # all. Logging out only needs a valid, already-authenticated user
        # (enforced above and by routers/users.py's own get_current_user
        # dependency) — it must never depend on a module permission, same
        # reasoning as the KYC exemption above.
        # --------------------------------------------------
        if path == "/users/logout":
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # Skip privilege check for marking your own bell notifications read
        #
        # PUT /notifications/{id}/read and /notifications/read-all were gated
        # on can_edit for the "notifications" module (PUT -> can_edit), which
        # most roles don't hold (it's the module that also covers template/
        # rule admin) — so opening a notification never cleared its unread
        # dot for them (403, silently swallowed by the bell). Both endpoints
        # only ever touch the caller's own UserNotification rows (filtered by
        # current_user.id in routers/notifications.py), same reasoning as the
        # logout exemption above.
        # --------------------------------------------------
        if request.method == "PUT" and (
            path == "/notifications/read-all"
            or (path.startswith("/notifications/") and path.endswith("/read")
                and path.count("/") == 3)
        ):
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # Extract module name
        # Example:
        #   /addresses/5 -> addresses
        #   /products   -> products
        # --------------------------------------------------
        parts = path.strip("/").split("/")
        module_name = parts[0] if parts else None

        if not module_name:
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # /modules/** — GET only skips the privilege check
        #
        # GET /modules/user (list_user_modules) returns each caller's own
        # permitted module list for their sidebar — every role needs it, and
        # gating "which modules can you see" behind "do you have can_view on
        # modules" is circular. GET /modules itself is already covered by
        # the single-segment-GET rule below, so this only adds /modules/user.
        # POST/PUT/DELETE (create/update/delete Module rows — platform-wide,
        # affecting every org) fall through to the normal OrgRolePermission
        # check like any other module: grant can_add/can_edit/can_delete on
        # the "App Modules" module (id=2) to whichever role should manage it.
        # --------------------------------------------------
        if module_name == "modules" and request.method == "GET":
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # /category_master/** and /category_details/** — GET only skips the
        # privilege check
        #
        # These are the equipment-type / test-type reference lookup used by
        # several already-permitted features (CM Recommendation Config,
        # CM/PM Master Template, ...) to resolve names and populate their
        # equipment-type lists. Gating that lookup behind its own separate,
        # rarely-granted module meant a role with legitimate view access to
        # those features still couldn't see the equipment types they depend
        # on — same "circular permission" problem /modules/user solves
        # above. POST/PUT/DELETE (actually creating/editing/deleting a
        # category master or detail) still requires the normal
        # OrgRolePermission check on that module, same as any other write.
        # --------------------------------------------------
        if module_name in ("category_master", "category_details") and request.method == "GET":
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # Shared template / reference lookups — see SHARED_LOOKUP_GETS
        # --------------------------------------------------
        if (
            request.method == "GET"
            and len(parts) >= 2
            and parts[1] in SHARED_LOOKUP_GETS.get(module_name, ())
        ):
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # Allow list endpoints (GET /products)
        # --------------------------------------------------
        if request.method == "GET" and len(parts) == 1:
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # Determine privilege action
        # --------------------------------------------------
        endpoint = request.scope.get("endpoint")
        endpoint_name = endpoint.__name__ if endpoint else ""

        if "search" in endpoint_name:
            action = "can_search"
        elif "export" in endpoint_name:
            action = "can_export"
        elif request.method == "POST" and module_name == "reports" and (
            (len(parts) == 4 and parts[1] == "definitions" and parts[3] == "run")
            or path == "/reports/consolidated-test-report"
        ):
            # Running a report only generates a file (and emails it) — an
            # export, not an "add". POST mapped these to can_add, which is
            # the permission for creating report *definitions*, so roles
            # holding view/export on Reports still got 403 on ▶ Run.
            # Matched by path: request.scope["endpoint"] isn't set yet when
            # this middleware runs (routing happens after it).
            action = "can_export"
        elif "approve" in endpoint_name or "reject" in endpoint_name:
            action = "can_approve"
        elif "assign" in endpoint_name:
            action = "can_assign"
        else:
            action = METHOD_ACTION_MAP.get(request.method)

        if not action:
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # MODULE CHECK
        # --------------------------------------------------
        resolved_module_name = API_TO_MODULE_PATH.get(module_name, module_name)
        module = db.query(Module).filter_by(path=resolved_module_name).first()
        if not module:
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # PRIVILEGE CHECK — org role system (OrgUserRole → OrgRolePermission)
        # --------------------------------------------------
        org_user_roles = db.query(OrgUserRole).filter_by(user_id=user.id, is_active=True).all()
        if org_user_roles:
            org_role_ids = [r.org_role_id for r in org_user_roles]

            if module_name in STAGE_BASED_MODULES:
                # Before the stage gate: the report path names the request,
                # and the gate alone would refuse its reviewers.
                if _record_access_via_workflow(db, request.method, parts,
                                               org_role_ids, user.id):
                    db.close()
                    return await call_next(request)

                stage_verdict = _find_stage_gate(db, parts, org_role_ids,
                                                 user.id, request.method)
                if stage_verdict is not None:
                    if not stage_verdict:
                        raise HTTPException(
                            status_code=403,
                            detail=(
                                f"Access denied: role is not the active tester "
                                f"for this request's current stage ('{module_name}')"
                            ),
                        )
                    db.close()
                    return await call_next(request)
                # No TestingRequest named in this path (list/reference call) —
                # fall through to the normal OrgRolePermission check below.

            allowed = (
                db.query(OrgRolePermission)
                .filter(
                    OrgRolePermission.org_role_id.in_(org_role_ids),
                    OrgRolePermission.module_id == module.id,
                    getattr(OrgRolePermission, action) == True,
                )
                .first()
            )

            # GET /equipment/{id} — workflow screens (TA&QC, Calibration,
            # Annual Audit, the Repair/Overhaul result form, ...) load the
            # equipment they work on; view on any workflow module is accepted
            # instead of Equipment Registry view. Same rule as the handler's
            # _require_permission(allow_workflow_view=True) in
            # routers/equipment.py (GET /equipment/ never reaches here —
            # single-segment GETs are let through above).
            if (
                not allowed
                and module_name == "equipment"
                and request.method == "GET"
                and len(parts) == 2
                and _UUID_RE.match(parts[1])
                and has_workflow_module_view(org_role_ids, db)
            ):
                allowed = True

            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail=_denied_detail(action, module_name, module),
                )
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # Fallback — old UserRole system
        # --------------------------------------------------
        try:
            user_roles = db.query(UserRole).filter_by(user_id=user.id).all()
            if not user_roles:
                db.close()
                return await call_next(request)

            role_ids = [r.role_id for r in user_roles]
            allowed = (
                db.query(RoleModulePrivilege)
                .filter(
                    RoleModulePrivilege.role_id.in_(role_ids),
                    RoleModulePrivilege.module_id == module.id,
                    getattr(RoleModulePrivilege, action) == True,
                )
                .first()
            )
            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail=_denied_detail(action, module_name, module),
                )
        except Exception as e:
            print(f"[INFO] Role system error in middleware: {e}")
            db.rollback()
            db.close()
            return await call_next(request)

        # --------------------------------------------------
        # ALL GOOD
        # --------------------------------------------------
        db.close()
        return await call_next(request)

    except HTTPException as exc:
        # A middleware registered via app.middleware("http") sits OUTSIDE
        # Starlette's ExceptionMiddleware, so an HTTPException raised in here
        # (every 401/403 above) is NOT auto-converted to a response the way
        # one raised inside a route handler is — left uncaught, it propagates
        # to ServerErrorMiddleware and surfaces to the caller as a bare 500,
        # masking the real 401/403 entirely. Convert it explicitly.
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers or {},
        )
    finally:
        db.close()
