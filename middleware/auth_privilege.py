from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Module, UserRole, RoleModulePrivilege, User, OrgUserRole, OrgRolePermission
import auth_utils
from fastapi import Request

async def auth_and_privilege_middleware(request: Request, call_next):

    # ✅ Allow CORS preflight requests (VERY IMPORTANT)
    if request.method == "OPTIONS":
        return await call_next(request)

    # ---- existing auth logic below ----

# --------------------------------------------------
# Public endpoints (NO authentication required)
# --------------------------------------------------
PUBLIC_ENDPOINTS = [
    "/",            # local root
    "/api",         # production root
    "/api/",        # production root with slash
    "/token",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/register/",
    "/auth/",
    "/public/",
    "/files/",
    "/zoho_register/",
    "/zohocontacts/",
    "/health",      # external load-test monitoring poll - no auth token available
    "/billing/webhook",   # Razorpay webhook — no auth
    "/billing/plans",     # Plan list — no auth needed
]
ZOHO_PREFIXES = (
    "/zoho",
    "/webhooks/zoho",
)

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
    # 3. Allow Zoho webhooks (FIXED)
    # --------------------------------------------------
    if path.startswith("/webhooks/zoho"):
        print("✅ Skipping auth for Zoho webhook")
        return await call_next(request)

    # --------------------------------------------------
    # 4. Allow public endpoints
    # --------------------------------------------------
    if any(path.startswith(p) for p in PUBLIC_ENDPOINTS):
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
            import os
            from models import Organization
            from datetime import datetime, timezone
            org = db.query(Organization).filter_by(id=user.organization_id).first()
            license_enforce = os.getenv("LICENSE_ENFORCE", "false").lower() == "true"
            if license_enforce:
                if org and not org.is_active:
                    raise HTTPException(
                        status_code=403,
                        detail="Your organisation has been disabled. Please contact support.",
                    )
                # Orgs managed by the license server: expiry is enforced via the
                # license server banner + upgrade flow, not local trial_end_date.
                if org and not org.license_server_org_id:
                    now = datetime.now(timezone.utc)
                    if org.is_trial and org.trial_end_date:
                        trial_end = org.trial_end_date if org.trial_end_date.tzinfo else org.trial_end_date.replace(tzinfo=timezone.utc)
                        if trial_end < now:
                            if org.trial_status != "expired":
                                org.trial_status = "expired"
                                try:
                                    db.commit()
                                except Exception:
                                    db.rollback()
                            raise HTTPException(
                                status_code=403,
                                detail="TRIAL_EXPIRED",
                            )
                    if not org.is_trial and org.subscription_end_date:
                        sub_end = org.subscription_end_date if org.subscription_end_date.tzinfo else org.subscription_end_date.replace(tzinfo=timezone.utc)
                        if sub_end < now:
                            if org.subscription_status != "expired":
                                org.subscription_status = "expired"
                                try:
                                    db.commit()
                                except Exception:
                                    db.rollback()
                            raise HTTPException(
                                status_code=403,
                                detail="SUBSCRIPTION_EXPIRED",
                            )

        request.state.user = user

        # --------------------------------------------------
        # Skip privilege check for KYC
        # --------------------------------------------------
        if path.startswith("/kyc/"):
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
            return await call_next(request)

        # --------------------------------------------------
        # Skip privilege check for /modules/**
        # --------------------------------------------------
        if module_name == "modules":
            return await call_next(request)

        # --------------------------------------------------
        # Allow list endpoints (GET /products)
        # --------------------------------------------------
        if request.method == "GET" and len(parts) == 1:
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
        elif "approve" in endpoint_name or "reject" in endpoint_name:
            action = "can_approve"
        elif "assign" in endpoint_name:
            action = "can_assign"
        else:
            action = METHOD_ACTION_MAP.get(request.method)

        if not action:
            return await call_next(request)

        # --------------------------------------------------
        # MODULE CHECK
        # --------------------------------------------------
        resolved_module_name = API_TO_MODULE_PATH.get(module_name, module_name)
        module = db.query(Module).filter_by(path=resolved_module_name).first()
        if not module:
            return await call_next(request)

        # --------------------------------------------------
        # PRIVILEGE CHECK — org role system (OrgUserRole → OrgRolePermission)
        # --------------------------------------------------
        org_user_roles = db.query(OrgUserRole).filter_by(user_id=user.id, is_active=True).all()
        if org_user_roles:
            org_role_ids = [r.org_role_id for r in org_user_roles]
            allowed = (
                db.query(OrgRolePermission)
                .filter(
                    OrgRolePermission.org_role_id.in_(org_role_ids),
                    OrgRolePermission.module_id == module.id,
                    getattr(OrgRolePermission, action) == True,
                )
                .first()
            )
            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied for '{action}' on '{module_name}'",
                )
            return await call_next(request)

        # --------------------------------------------------
        # Fallback — old UserRole system
        # --------------------------------------------------
        try:
            user_roles = db.query(UserRole).filter_by(user_id=user.id).all()
            if not user_roles:
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
                    detail=f"Access denied for '{action}' on '{module_name}'",
                )
        except Exception as e:
            print(f"[INFO] Role system error in middleware: {e}")
            db.rollback()
            return await call_next(request)

        # --------------------------------------------------
        # ALL GOOD
        # --------------------------------------------------
        return await call_next(request)

    finally:
        db.close()
