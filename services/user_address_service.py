from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from models import UserAddress
from utils.common_service import UTCDateTimeMixin
import uuid


class UserAddressService(UTCDateTimeMixin):
    """
    Service layer for managing UserAddress entities.
    Follows the same structure and conventions as UserService.
    """

    # --------------------------
    # CREATE
    # --------------------------
    @classmethod
    def create_user_address(cls, db: Session, address_data):
        """
        Create a new user address.
        """
        # Check if user already has a primary address of same type
        if address_data.is_primary:
            existing_primary = (
                db.query(UserAddress)
                .filter(
                    UserAddress.user_id == address_data.user_id,
                    UserAddress.address_type == address_data.address_type,
                    UserAddress.is_primary.is_(True),
                )
                .first()
            )
            if existing_primary:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Primary address for this type already exists."
                )

        db_address = UserAddress(
            user_id=address_data.user_id,
            address_type=address_data.address_type,
            address_line1=address_data.address_line1,
            address_line2=address_data.address_line2,
            state_id=address_data.state_id,
            country_id=address_data.country_id,
            postal_code=address_data.postal_code,
            is_primary=address_data.is_primary or False,
            created_by=address_data.created_by,
            cts=cls._utc_now(),
            mts=cls._utc_now(),
        )

        db.add(db_address)
        db.commit()
        db.refresh(db_address)
        return db_address

    # --------------------------
    # READ
    # --------------------------
    @classmethod
    def get_user_address(cls, db: Session, address_id: int):
        address = db.query(UserAddress).filter(UserAddress.id == address_id).first()
        if not address:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Address not found"
            )
        return address

    @classmethod
    def get_user_addresses(cls, db: Session, user_id: uuid.UUID, skip: int = 0, limit: int = 100):
        return (
            db.query(UserAddress)
            .filter(UserAddress.user_id == user_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    @classmethod
    def get_primary_address(cls, db: Session, user_id: uuid.UUID, address_type: str | None = None):
        query = db.query(UserAddress).filter(
            UserAddress.user_id == user_id,
            UserAddress.is_primary.is_(True),
        )
        if address_type:
            query = query.filter(UserAddress.address_type == address_type)
        return query.first()

    # --------------------------
    # UPDATE
    # --------------------------
    @classmethod
    def update_user_address(cls, db: Session, address_id: int, updates: dict):
        db_address = db.query(UserAddress).filter(UserAddress.id == address_id).first()
        if not db_address:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Address not found"
            )

        for key, value in updates.items():
            if hasattr(db_address, key):
                setattr(db_address, key, value)

        db_address.mts = cls._utc_now()
        db.commit()
        db.refresh(db_address)
        return db_address

    # --------------------------
    # DELETE
    # --------------------------
    @classmethod
    def delete_user_address(cls, db: Session, address_id: int):
        db_address = db.query(UserAddress).filter(UserAddress.id == address_id).first()
        if not db_address:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Address not found"
            )
        db.delete(db_address)
        db.commit()
        return {"detail": "Address deleted successfully."}

    # --------------------------
    # SEARCH
    # --------------------------
    @classmethod
    def search_addresses(
        cls,
        db: Session,
        user_id: uuid.UUID | None = None,
        query: str | None = None,
        address_type: str | None = None,
        state_id: int | None = None,
        country_id: int | None = None,
        is_primary: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ):
        """
        Flexible search with multiple filters (similar to get_users).
        """
        q = db.query(UserAddress)

        if user_id:
            q = q.filter(UserAddress.user_id == user_id)
        if address_type:
            q = q.filter(UserAddress.address_type.ilike(f"%{address_type}%"))
        if state_id:
            q = q.filter(UserAddress.state_id == state_id)
        if country_id:
            q = q.filter(UserAddress.country_id == country_id)
        if is_primary is not None:
            q = q.filter(UserAddress.is_primary == is_primary)
        if query:
            q = q.filter(
                or_(
                    UserAddress.address_line1.ilike(f"%{query}%"),
                    UserAddress.address_line2.ilike(f"%{query}%"),
                    UserAddress.postal_code.ilike(f"%{query}%"),
                )
            )

        return q.offset(skip).limit(limit).all()
