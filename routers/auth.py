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

    # Query default_module_path directly from database
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

    print(f"[DEBUG] user_id: {user_id}")
    print(f"[DEBUG] default_module_path: {default_module_path}")

    result["user"]["default_module_path"] = default_module_path
    return result


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
