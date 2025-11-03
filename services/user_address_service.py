from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_
from models import AddressTypeEnum, UserAddress
from models import User




from utils.common_service import UTCDateTimeMixin
import uuid


class UserAddressService(UTCDateTimeMixin):
    """
    Service layer for managing UserAddress entities,
    aligned with the latest Address model.
    """

    # --------------------------
    # CREATE
    # --------------------------
    @classmethod
    def create_user_address(cls, db: Session, address_data):
        """
        Create a new user address.
        """

        # ✅ Validate associated user exists
        user = db.query(User).filter(User.id == address_data.user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )

        # ✅ Validate address_type enum
        if address_data.address_type not in AddressTypeEnum.__members__:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid address_type"
            )

        # ✅ Ensure single primary for each type per user
        if address_data.is_primary:
            existing_primary = (
                db.query(UserAddress)
                .filter(
                    UserAddress.user_id == address_data.user_id,
                    UserAddress.address_type == address_data.address_type,
                    UserAddress.is_primary.is_(True)
                )
                .first()
            )
            if existing_primary:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Primary address already exists for this type"
                )

        new_addr = UserAddress(
            user_id=address_data.user_id,
            address_type=address_data.address_type,
            is_primary=address_data.is_primary or False,
            address_line1=address_data.address_line1,
            address_line2=address_data.address_line2,
            city=address_data.city,
            state_id=address_data.state_id,
            country_id=address_data.country_id,
            postal_code=address_data.postal_code,
            latitude=address_data.latitude,
            longitude=address_data.longitude,
            created_by=address_data.created_by,
            cts=cls._utc_now(),
            mts=cls._utc_now(),
        )

        db.add(new_addr)
        db.commit()
        db.refresh(new_addr)
        return new_addr

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
    def get_primary_address(cls, db: Session, user_id: uuid.UUID, address_type: str):
        return (
            db.query(UserAddress)
            .filter(
                UserAddress.user_id == user_id,
                UserAddress.address_type == address_type,
                UserAddress.is_primary.is_(True)
            )
            .first()
        )

    # --------------------------
    # UPDATE
    # --------------------------
    @classmethod
    def update_user_address(cls, db: Session, address_id: int, updates: dict):
        address = cls.get_user_address(db, address_id)

        # ✅ If changing type, validate enum
        if "address_type" in updates:
            if updates["address_type"] not in AddressTypeEnum.__members__:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid address_type"
                )

        # ✅ Enforce single primary address per type per user
        if updates.get("is_primary"):
            existing_primary = (
                db.query(UserAddress)
                .filter(
                    UserAddress.user_id == address.user_id,
                    UserAddress.address_type == address.address_type,
                    UserAddress.is_primary.is_(True),
                    UserAddress.id != address_id,
                )
                .first()
            )
            if existing_primary:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Another primary address already exists"
                )

        # ✅ Apply only attribute fields existing in model
        for key, value in updates.items():
            if hasattr(address, key):
                setattr(address, key, value)

        address.mts = cls._utc_now()
        db.commit()
        db.refresh(address)
        return address

    # --------------------------
    # DELETE
    # --------------------------
    @classmethod
    def delete_user_address(cls, db: Session, address_id: int):
        address = cls.get_user_address(db, address_id)
        db.delete(address)
        db.commit()
        return {"detail": "Address deleted successfully"}

    # --------------------------
    # SEARCH / FILTER
    # --------------------------
    @classmethod
    def search_addresses(
        cls,
        db: Session,
        user_id: uuid.UUID | None = None,
        address_type: str | None = None,
        query: str | None = None,
        state_id: int | None = None,
        country_id: int | None = None,
        is_primary: bool | None = None,
        skip: int = 0,
        limit: int = 100,
    ):
        """
        Powerful search with multiple filters.
        """
        q = db.query(UserAddress)

        if user_id:
            q = q.filter(UserAddress.user_id == user_id)
        if address_type:
            q = q.filter(UserAddress.address_type == address_type)
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
                    UserAddress.city.ilike(f"%{query}%"),
                    UserAddress.postal_code.ilike(f"%{query}%"),
                )
            )

        return q.offset(skip).limit(limit).all()
