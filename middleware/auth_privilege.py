from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Module, UserRole, RoleModulePrivilege, User
import auth_utils

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
    "/files/",
    "/zoho_register/",
    "/zohocontacts/",
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
    # 3. Allow Zoho webhooks
    # --------------------------------------------------
    if path.startswith("/zoho"):
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
        else:
            action = METHOD_ACTION_MAP.get(request.method)

        if not action:
            return await call_next(request)

        # --------------------------------------------------
        # MODULE CHECK
        # --------------------------------------------------
        module = db.query(Module).filter_by(path=module_name).first()
        if not module:
            raise HTTPException(
                status_code=404,
                detail=f'Module "{module_name}" not registered',
            )

        # --------------------------------------------------
        # USER ROLES
        # --------------------------------------------------
        user_roles = db.query(UserRole).filter_by(user_id=user.id).all()
        if not user_roles:
            raise HTTPException(
                status_code=403,
                detail="User has no assigned roles",
            )

        role_ids = [r.role_id for r in user_roles]

        # --------------------------------------------------
        # PRIVILEGE CHECK
        # --------------------------------------------------
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

        # --------------------------------------------------
        # ALL GOOD
        # --------------------------------------------------
        return await call_next(request)

    finally:
        db.close()
