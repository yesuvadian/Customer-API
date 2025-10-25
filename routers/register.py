from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
import schemas
from services.user_service import UserService  # import the class

router = APIRouter(prefix="/register", tags=["register"])

# Instantiate the service
user_service_instance = UserService()

@router.post("/", response_model=schemas.User)
def create_user(user: schemas.UserRegistor, db: Session = Depends(get_db)):
    """Create a new user."""
    return user_service_instance.create_user(db, user)
