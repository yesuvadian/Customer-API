from urllib.request import Request
from fastapi import APIRouter, Depends, HTTPException,status
from models import UserSession
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
import schemas
from services.user_service import UserService
from utils.common_service import UTCDateTimeMixin  # import class directly

router = APIRouter(
    prefix="/users",
    tags=["Users"],
    dependencies=[Depends(get_current_user)]  # JWT required for all routes
)


# Instantiate the service
user_service_instance = UserService()

@router.post("/", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    """Create a new user."""
    return user_service_instance.create_user(db, user)


@router.get("/{user_id}", response_model=schemas.User)
def read_user(user_id: str, db: Session = Depends(get_db)):
    """Fetch a user by ID."""
    db_user = user_service_instance.get_user(db, user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user


@router.get("/", response_model=list[schemas.User])
def list_users(skip: int = 0, limit: int = 100, search: str | None = None, db: Session = Depends(get_db)):
    """List users with optional search."""
    return user_service_instance.get_users(db, skip=skip, limit=limit, search=search)

@router.get("/me", response_model=schemas.User)
def read_current_user(current_user: schemas.User = Depends(get_current_user)):
    return current_user

@router.put("/{user_id}", response_model=schemas.User)
def update_user_endpoint(user_id: str, updates: dict, db: Session = Depends(get_db)):
    """Update an existing user."""
    db_user = user_service_instance.update_user(db, user_id, updates)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user


@router.delete("/{user_id}", response_model=schemas.User)
def delete_user_endpoint(user_id: str, db: Session = Depends(get_db)):
    """Delete a user."""
    db_user = user_service_instance.delete_user(db, user_id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    return db_user
@router.post("/logout", status_code=status.HTTP_200_OK)
def logout_user(
    request: Request,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
    refresh_token: str | None = None  # optional: could be passed from client
):
    """
    Logout the current user by revoking the session.
    If refresh_token is provided, only that session is revoked.
    Otherwise, all sessions for the user are revoked.
    """
    now = UTCDateTimeMixin._utc_now()

    query = db.query(UserSession).filter(UserSession.user_id == current_user.id)

    if refresh_token:
        query = query.filter(UserSession.refresh_token == refresh_token)

    sessions = query.all()

    if not sessions:
        raise HTTPException(status_code=404, detail="No active session found")

    for session in sessions:
        session.revoked_at = now

    db.commit()

    return {"detail": f"{len(sessions)} session(s) successfully logged out"}