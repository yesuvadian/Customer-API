from fastapi import HTTPException,status
from sqlalchemy.orm import Session
#from auth_utils import get_password_hash
from models import User
from schemas import UserCreate
from datetime import datetime, timezone
import uuid

import schemas
from security_utils import get_password_hash
from utils.common_service import UTCDateTimeMixin
class UserService(UTCDateTimeMixin):

    @classmethod
    def get_user(cls,db: Session, user_id: uuid.UUID):
        return db.query(User).filter(User.id == user_id).first()
    @classmethod
    def get_users(cls,db: Session, skip: int = 0, limit: int = 100, search: str = None):
        query = db.query(User)
        if search:
            query = query.filter(User.email.ilike(f"%{search}%"))
        return query.offset(skip).limit(limit).all()
    @classmethod
    def get_user_by_email(cls,db: Session, email: str):
        """
        Retrieve a single user by email.
        Raises HTTPException if not found (optional).
        """
        user = db.query(User).filter(User.email == email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        return user
    @classmethod
    def create_user(cls,db: Session, user: schemas.UserCreate):
        # Check if email already exists
        existing_user_email = db.query(User).filter(User.email == user.email).first()
        if existing_user_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        
        # Check if phone number already exists
        existing_user_phone = db.query(User).filter(User.phone_number == user.phone_number).first()
        if existing_user_phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Phone number already registered"
            )
        
        # Hash the password
        hashed_pw = get_password_hash(user.password)
        
        # Create user
        db_user = User(
            email=user.email,
            password_hash=hashed_pw,
            firstname=user.firstname,
            lastname=user.lastname,
            phone_number=user.phone_number,
            mts=cls._utc_now(),
            cts=cls._utc_now()
        )
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        
        return db_user

    @classmethod
    def update_user(cls,db: Session, user_id: uuid.UUID, updates: dict):
        db_user = db.query(User).filter(User.id == user_id).first()
        if not db_user:
            return None
        for key, value in updates.items():
            setattr(db_user, key, value)
        db_user.mts = cls._utc_now(),
        db.commit()
        db.refresh(db_user)
        return db_user

    def delete_user(cls,db: Session, user_id: uuid.UUID):
        db_user = db.query(User).filter(User.id == user_id).first()
        if db_user:
            db.delete(db_user)
            db.commit()
        return db_user
