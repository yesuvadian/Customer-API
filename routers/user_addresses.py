from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
import uuid

from auth_utils import get_current_user
from database import get_db
from schemas import UserAddressCreate, UserAddressOut, UserAddressUpdate
from services.user_address_service import UserAddressService

router = APIRouter(
    prefix="/addresses",
    tags=["addresses"],
    dependencies=[Depends(get_current_user)]
)

address_service = UserAddressService()


# --------------------------
# CREATE
# --------------------------
@router.post("", response_model=UserAddressOut, status_code=status.HTTP_201_CREATED)
def create_address(address: UserAddressCreate, db: Session = Depends(get_db)):
    return address_service.create_user_address(db, address)


# --------------------------
# READ
# --------------------------
@router.get("/{address_id}", response_model=UserAddressOut)
def get_address(address_id: int, db: Session = Depends(get_db)):
    return address_service.get_user_address(db, address_id)


@router.get("/user/{user_id}", response_model=list[UserAddressOut])
def get_addresses_for_user(
    user_id: uuid.UUID,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    return address_service.get_user_addresses(db, user_id, skip=skip, limit=limit)


@router.get("/user/{user_id}/primary", response_model=UserAddressOut | None)
def get_primary_address(
    user_id: uuid.UUID,
    address_type: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return address_service.get_primary_address(db, user_id, address_type)


# --------------------------
# SEARCH ✅ moved route to avoid conflict
# --------------------------
@router.get("/search", response_model=list[UserAddressOut])
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


# --------------------------
# UPDATE
# --------------------------
@router.put("/{address_id}", response_model=UserAddressOut)
def update_address(
    address_id: int,
    updates: UserAddressUpdate,
    db: Session = Depends(get_db),
):
    return address_service.update_user_address(
        db, address_id, updates.dict(exclude_unset=True)
    )


# --------------------------
# DELETE
# --------------------------
@router.delete("/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_address(address_id: int, db: Session = Depends(get_db)):
    address_service.delete_user_address(db, address_id)
    return {"detail": "Address deleted successfully."}
