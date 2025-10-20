from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session
from datetime import timedelta
from database import get_db
from auth_utils import authenticate_user, create_access_token, create_refresh_token, ACCESS_TOKEN_EXPIRE_MINUTES

router = APIRouter(tags=["Auth"])

@router.post("/token")
def login_for_access_token(
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...)
):
    result = authenticate_user(db, username, password)

    if "error" in result:
        raise HTTPException(status_code=result["status"], detail=result["error"])

    user = result["user"]

    access_token = create_access_token(
        data={"sub": str(user.id)},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )

    refresh_token = create_refresh_token(str(user.id))

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }
