from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
import uuid

from database import get_db
from schemas import UserAddressCreate, UserAddressOut, UserAddressUpdate
from services.user_address_service import UserAddressService
#import schemas

router = APIRouter(prefix="/addresses", tags=["addresses"])

# Instantiate service
address_service = UserAddressService()


# --------------------------
# CREATE
# --------------------------
@router.post("/", response_model=UserAddressOut, status_code=status.HTTP_201_CREATED)
def create_address(address: UserAddressCreate, db: Session = Depends(get_db)):
    """
    Create a new user address.
    """
    return address_service.create_user_address(db, address)


# --------------------------
# READ
# --------------------------
@router.get("/{address_id}", response_model=UserAddressOut)
def get_address(address_id: int, db: Session = Depends(get_db)):
    """
    Retrieve a single user address by ID.
    """
    return address_service.get_user_address(db, address_id)


@router.get("/user/{user_id}", response_model=list[UserAddressOut])
def get_addresses_for_user(
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """
    Retrieve all addresses for a user.
    """
    return address_service.get_user_addresses(db, user_id, skip=skip, limit=limit)


@router.get("/user/{user_id}/primary", response_model=UserAddressOut | None)
def get_primary_address(
    user_id: uuid.UUID,
    address_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    Get a user's primary address (optionally filter by type).
    """
    return address_service.get_primary_address(db, user_id, address_type)


# --------------------------
# UPDATE
# --------------------------
@router.put("/{address_id}", response_model=UserAddressOut)
def update_address(address_id: int, updates: UserAddressUpdate, db: Session = Depends(get_db)):
    """
    Update an existing address.
    """
    return address_service.update_user_address(db, address_id, updates.dict(exclude_unset=True))


# --------------------------
# DELETE
# --------------------------
@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(address_id: int, db: Session = Depends(get_db)):
    """
    Delete a user address.
    """
    address_service.delete_user_address(db, address_id)
    return {"detail": "Address deleted successfully."}


# --------------------------
# SEARCH
# --------------------------
@router.get("/", response_model=list[UserAddressOut])
def search_addresses(
    db: Session = Depends(get_db),
    user_id: uuid.UUID | None = Query(None),
    query: str | None = Query(None),
    address_type: str | None = Query(None),
    state_id: int | None = Query(None),
    country_id: int | None = Query(None),
    is_primary: bool | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, le=500),
):
    """
    Search addresses with optional filters (user_id, type, text, etc.).
    """
    return address_service.search_addresses(
        db=db,
        user_id=user_id,
        query=query,
        address_type=address_type,
        state_id=state_id,
        country_id=country_id,
        is_primary=is_primary,
        skip=skip,
        limit=limit,
    )
