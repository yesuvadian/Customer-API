from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from schemas import (
    LoginRequest, LoginResponse,
    PasswordResetConfirm, PasswordResetRequest,
    PasswordResetResponse, PlanOut, RefreshTokenRequest
)
from auth_utils import login_user, requestpasswordreset, resetpassword
from services.auth_service import AuthService
from services.plan_service import PlanService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    return login_user(db=db, email=request.email, password=request.password)


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
