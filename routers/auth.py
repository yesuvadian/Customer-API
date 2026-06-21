from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from schemas import (
    LoginRequest, LoginResponse,
    PasswordResetConfirm, PasswordResetRequest,
    PasswordResetResponse, PlanOut, RefreshTokenRequest
)
from auth_utils import build_user_privileges, get_current_user, login_user, requestpasswordreset, resetpassword
from models import User
from services.auth_service import AuthService
from services.plan_service import PlanService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    print("[DEBUG-START] Login endpoint called!")
    result = login_user(db=db, email=request.email, password=request.password)
    print("[DEBUG-AFTER-LOGIN] Got result from login_user")

    # TEMP FIX: Manually inject dashboard_type by querying DB directly
    from sqlalchemy import text
    user_id = result["user"]["id"]

    # Query default_module_path — from org role first, then user's own setting
    query = text("""
        SELECT m.path
        FROM public.org_user_roles our
        JOIN public.org_roles oroles ON our.org_role_id = oroles.id
        LEFT JOIN public.modules m ON oroles.default_module_id = m.id
        WHERE our.user_id = :user_id AND our.is_active = true
        LIMIT 1
    """)

    result_row = db.execute(query, {"user_id": user_id}).fetchone()
    default_module_path = result_row[0] if (result_row and result_row[0]) else None

    # Fallback: System Admin has no org_user_roles entry — use the is_system_admin org role's default module
    if not default_module_path:
        fallback_query = text("""
            SELECT m.path
            FROM public.org_roles oroles
            LEFT JOIN public.modules m ON oroles.default_module_id = m.id
            WHERE oroles.is_system_admin = true AND oroles.is_active = true
            LIMIT 1
        """)
        fallback_row = db.execute(fallback_query).fetchone()
        default_module_path = fallback_row[0] if (fallback_row and fallback_row[0]) else None

    print(f"[DEBUG] user_id: {user_id}")
    print(f"[DEBUG] default_module_path: {default_module_path}")

    result["user"]["default_module_path"] = default_module_path
    return result


@router.get("/me")
def get_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return fresh user profile including department_id (no re-login needed)."""
    from models import OrgUserRole
    roles = db.query(OrgUserRole).filter(
        OrgUserRole.user_id == current_user.id,
        OrgUserRole.is_active == True,
    ).all()
    role_names = [r.org_role.name for r in roles if r.org_role]
    primary_dept_id = None
    if roles:
        primary_dept_id = roles[0].department_id
    if primary_dept_id is None and getattr(current_user, 'department_id', None):
        primary_dept_id = current_user.department_id
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "firstname": current_user.firstname,
        "lastname": current_user.lastname,
        "phone_number": current_user.phone_number,
        "is_active": current_user.isactive,
        "email_confirmed": current_user.email_confirmed,
        "phone_confirmed": current_user.phone_confirmed,
        "usertype": current_user.usertype,
        "organization_id": str(current_user.organization_id) if current_user.organization_id else None,
        "department_id": str(primary_dept_id) if primary_dept_id else None,
        "roles": role_names,
        "cts": current_user.cts,
        "mts": current_user.mts,
    }


@router.get("/privileges")
def get_privileges(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return fresh privilege dict for the current user (no re-login needed)."""
    return build_user_privileges(db, current_user.id)


@router.post("/refresh")
def refresh_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    return AuthService.refresh_access_token(
        db=db,
        refresh_token=payload.refresh_token
    )


@router.post("/request-password-reset", response_model=PasswordResetResponse)
def request_password_reset(
    request: Request,
    data: PasswordResetRequest,
    db: Session = Depends(get_db),
):
    reset_link = requestpasswordreset(db, data.email, request)
    return {
        "message": "Password reset link generated successfully",
        "reset_link": reset_link
    }


@router.get("/plans", response_model=List[PlanOut])
def get_plans(
    skip: int = 0,
    limit: int = 100,
    search: str | None = None,
    db: Session = Depends(get_db)
):
    return PlanService.get_plans(
        db, skip=skip, limit=limit, search=search, active_only=True
    )


@router.post("/reset-password")
def reset_password(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    resetpassword(db, data.token, data.new_password)
    return {"message": "Password reset successful"}
