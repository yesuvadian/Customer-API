from fastapi import Request, HTTPException, status
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Module, UserRole, RoleModulePrivilege, User
import auth_utils

PUBLIC_ENDPOINTS = ["/token", "/docs", "/openapi.json", "/redoc", "/register/","/auth/"]

METHOD_ACTION_MAP = {
    "GET": "can_view",
    "POST": "can_add",
    "PUT": "can_edit",
    "DELETE": "can_delete",
}


async def auth_and_privilege_middleware(request: Request, call_next):
    # Allow public endpoints
    path = request.url.path
    if any(path.startswith(p) for p in PUBLIC_ENDPOINTS):
        return await call_next(request) 

    db: Session = SessionLocal()
    try:
        # --- Extract Bearer token ---
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unauthorized: Missing or invalid token header",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = auth_header.split(" ")[1]
        payload = auth_utils.decode_access_token(token)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # --- Fetch user from DB ---
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing user ID")

        user = db.query(User).filter_by(id=user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        # Attach user object to request
        request.state.user = user

        # --- Privilege check ---
        path_parts = request.url.path.strip("/").split("/")
        module_name = path_parts[0] if path_parts else None
        endpoint_name = request.scope.get("endpoint").__name__ if request.scope.get("endpoint") else ""
        action = None

        if "search" in endpoint_name:
            action = "can_search"
        elif "export" in endpoint_name:
            action = "can_export"
        else:
            action = METHOD_ACTION_MAP.get(request.method)

        if module_name and action:
            module = db.query(Module).filter_by(name=module_name).first()
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

        # --- Request passes ---
        response = await call_next(request)
        return response

    finally:
        db.close()
