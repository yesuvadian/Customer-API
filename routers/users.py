from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
import schemas
from services.user_service import UserService  # import class directly

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
