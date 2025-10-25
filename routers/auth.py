
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import get_db
from schemas import LoginRequest, LoginResponse, PasswordResetConfirm, PasswordResetRequest, PasswordResetResponse, PlanOut
from auth_utils import login_user, requestpasswordreset, resetpassword
from services.plan_service import PlanService
router = APIRouter(prefix="/auth", tags=["authentication"])




# --------------------------
# LOGIN (POST /auth/)
# --------------------------
@router.post("/login", name="login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    User login.

    Validates credentials, checks account status and lockouts,
    then returns an access token with user details, roles, and privileges.
    """
    return login_user(db=db, email=request.email, password=request.password)

@router.post("/request-password-reset", response_model=PasswordResetResponse)
def request_password_reset(
    request: Request,                    # ✅ Just type annotate
    data: PasswordResetRequest,          # Body param
    db: Session = Depends(get_db),       # Dependency
):
    reset_link = requestpasswordreset(db, data.email, request)
    return {
        "message": "Password reset link generated successfully",
        "reset_link": reset_link
    }

@router.get("/plans", response_model=List[PlanOut])
def get_plans(skip: int = 0, limit: int = 100, search: str | None = None, db: Session = Depends(get_db)):
    """Get all active plans"""
    return PlanService.get_plans(db, skip=skip, limit=limit, search=search, active_only=True)

# --------------------------
# RESET PASSWORD
# --------------------------
@router.post("/reset-password", status_code=status.HTTP_200_OK)
def reset_password(data: PasswordResetConfirm, db: Session = Depends(get_db)):
    """
    Reset password using token and validate against password history.
    """
    resetpassword(db, data.token, data.new_password)
    return {"message": "Password reset successful"}