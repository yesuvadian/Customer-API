from fastapi import HTTPException,status
from sqlalchemy.orm import Session
#from auth_utils import get_password_hash
from models import User, UserSession, CompanyProduct, Product # Assuming CompanyProduct and Product are in models
from schemas import UserCreate
from datetime import datetime, timezone
import uuid
from sqlalchemy import or_# <--- Import 'and_' for combined filtering

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
    def create_user(cls,db: Session, user: schemas.UserRegistor):
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
            plan_id=user.plan_id,
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
    @staticmethod
    def logout_user(db: Session, user_id: str, refresh_token: str | None = None) -> int:
        """
        Revoke active sessions for the user.
        If refresh_token is provided, only that session is revoked.
        Returns the number of sessions revoked.
        """
        now = UTCDateTimeMixin._utc_now()

        query = db.query(UserSession).filter(UserSession.user_id == user_id)

        if refresh_token:
            query = query.filter(UserSession.refresh_token == refresh_token)

        sessions = query.all()

        if not sessions:
            return 0

        for session in sessions:
            session.revoked_at = now

        db.commit()
        return len(sessions)
    
    @classmethod
    def get_users_by_product_search(
        cls,
        db: Session,
        search_term: str | None = None, # Single search term
        skip: int = 0,
        limit: int = 100
    ):
        """
        Filters distinct users who are linked to a product where the search_term
        matches the product name, SKU, OR description.
        """
        query = db.query(User).distinct()

        # 1. Join User to CompanyProduct (User.id == CompanyProduct.company_id)
        query = query.join(
            CompanyProduct,
            User.id == CompanyProduct.company_id
        )

        # 2. Join CompanyProduct to Product (CompanyProduct.product_id == Product.id)
        query = query.join(
            Product,
            CompanyProduct.product_id == Product.id
        )

        # Build the filter conditions
        if search_term:
            # Use ilike for case-insensitive partial match
            search_pattern = f"%{search_term}%"
            
            # Use OR to check the search_term against all three fields
            filter_condition = or_(
                Product.name.ilike(search_pattern),
                Product.sku.ilike(search_pattern),
                Product.description.ilike(search_pattern)
            )
            
            # Apply the combined filter
            query = query.filter(filter_condition)
            
        # Apply pagination and return results
        return query.offset(skip).limit(limit).all()