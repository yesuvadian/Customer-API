from fastapi import Request, HTTPException
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Module, UserRole, RoleModulePrivilege, User
import auth_utils

PUBLIC_ENDPOINTS = [
    "/token", "/docs", "/openapi.json", "/redoc",
    "/register/", "/auth/", "/files/", "/zoho_register/", "/zohocontacts/"
]

METHOD_ACTION_MAP = {
    "GET": "can_view",
    "POST": "can_add",
    "PUT": "can_edit",
    "DELETE": "can_delete",
}


async def auth_and_privilege_middleware(request: Request, call_next):
    raw_path = request.url.path.lower()
    path = raw_path[4:] if raw_path.startswith("/api/") else raw_path
    # -------------------------------------------------------
    # 1. Allow OPTIONS (CORS preflight)
    # -------------------------------------------------------
    if request.method == "OPTIONS":
        return await call_next(request)

    # -------------------------------------------------------
    # 2. Allow all Zoho webhooks / APIs as public
    #    Example:
    #    /zoho/token, /zoho/items, /zohoquotes, /zohoanything
    # -------------------------------------------------------
    if path.startswith("/zoho"):
        return await call_next(request)

    # -------------------------------------------------------
    # 3. Allow other public endpoints
    # -------------------------------------------------------
    if any(path.startswith(p) for p in PUBLIC_ENDPOINTS):
        return await call_next(request)

    # -------------------------------------------------------
    # 4. DB session for privileged checks
    # -------------------------------------------------------
    db: Session = SessionLocal()
    try:
        # ---------------- TOKEN VALIDATION ----------------
        auth_header = request.headers.get("Authorization") \
            or request.headers.get("authorization")

        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Unauthorized: Missing or invalid token")

        token = auth_header.split(" ")[1]
        payload = auth_utils.decode_access_token(token)
        if not payload:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        user_id = payload.get("sub")
        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        request.state.user = user

        # -------------------------------------------------------
        # Skip privilege check for /kyc/**
        # -------------------------------------------------------
        if path.startswith("/kyc/"):
            return await call_next(request)

        # -------------------------------------------------------
        # Extract module name from URL
        # -------------------------------------------------------
        parts = request.url.path.strip("/").split("/")
        module_name = parts[0] if parts else None

        # -------------------------------------------------------
        # Skip privilege check for /modules/**
        # used for role privileges screen in UI
        # -------------------------------------------------------
        if module_name == "modules":
            return await call_next(request)

        # -------------------------------------------------------
        # Allow list endpoints such as:
        # GET /products/ (listing)
        # -------------------------------------------------------
        if request.method == "GET" and len(parts) == 1:
            return await call_next(request)

        # -------------------------------------------------------
        # Determine privilege action
        # -------------------------------------------------------
        endpoint_name = request.scope.get("endpoint").__name__ \
            if request.scope.get("endpoint") else ""

        action = None
        if "search" in endpoint_name:
            action = "can_search"
        elif "export" in endpoint_name:
            action = "can_export"
        else:
            action = METHOD_ACTION_MAP.get(request.method)

        # If module name or action undefined, skip checks
        if not module_name or not action:
            return await call_next(request)

        # ---------------- MODULE + PRIVILEGE CHECK ----------------
        module = db.query(Module).filter_by(path=module_name).first()
        if not module:
            raise HTTPException(status_code=404, detail=f'Module "{module_name}" not registered')

        user_roles = db.query(UserRole).filter_by(user_id=user.id).all()
        if not user_roles:
            raise HTTPException(status_code=403, detail="User has no assigned roles")

        role_ids = [r.role_id for r in user_roles]

        allowed = db.query(RoleModulePrivilege).filter(
            RoleModulePrivilege.role_id.in_(role_ids),
            RoleModulePrivilege.module_id == module.id,
            getattr(RoleModulePrivilege, action) == True
        ).first()

        if not allowed:
            raise HTTPException(
                status_code=403,
                detail=f"Access denied for action '{action}' on module '{module_name}'"
            )

        return await call_next(request)

    finally:
        db.close()
