from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Module, UserRole, RoleModulePrivilege, User
import auth_utils

PUBLIC_ENDPOINTS = [
    "/token", "/docs", "/openapi.json", "/redoc",
    "/register/", "/auth/", "/files/"
]

METHOD_ACTION_MAP = {
    "GET": "can_view",
    "POST": "can_add",
    "PUT": "can_edit",
    "DELETE": "can_delete",
}


async def auth_and_privilege_middleware(request: Request, call_next):
    path = request.url.path

    # Allow OPTIONS and public endpoints
    if request.method == "OPTIONS" or any(path.startswith(p) for p in PUBLIC_ENDPOINTS):
        return await call_next(request)

    db: Session = SessionLocal()
    try:
        # ---------------- TOKEN VALIDATION ----------------
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
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

        # Skip privilege check for /kyc/**
        if path.startswith("/kyc/"):
            return await call_next(request)

        # ---------------- MODULE NAME ----------------
        parts = request.url.path.strip("/").split("/")
        module_name = parts[0] if parts else None

        # -------------------------------------------------------
        # OPTION-1: Skip privilege check ONLY for /modules/**
        # because these are used in UI role privilege screen
        # -------------------------------------------------------
        if module_name == "modules":
            return await call_next(request)

        # -------------------------------------------------------
        # FIX: Skip privilege check for listing endpoints:
        # Example: GET /products/?skip=0  (products list)
        # Vendor should NOT be blocked for list APIs.
        # -------------------------------------------------------
        if request.method == "GET" and len(parts) == 1:
            # /products/
            return await call_next(request)
        # -------------------------------------------------------

        # Determine permission type for request
        endpoint_name = request.scope.get("endpoint").__name__ if request.scope.get("endpoint") else ""
        action = None

        if "search" in endpoint_name:
            action = "can_search"
        elif "export" in endpoint_name:
            action = "can_export"
        else:
            action = METHOD_ACTION_MAP.get(request.method)

        # If no module or no action → skip
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
