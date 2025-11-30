# cities.py
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional
from auth_utils import get_current_user  # Assuming this utility is available
from database import get_db  # Assuming this utility is available
from schemas import CityCreate, CityOut, CityUpdate
from services.city_service import CityService  # Adjust import path as needed

router = APIRouter(
    prefix="/cities",
    tags=["cities"],
    dependencies=[Depends(get_current_user)]
)

service = CityService()

# GET - List all cities
@router.get("/", response_model=list[CityOut])
def list_cities(
    skip: int = 0,
    limit: int = 100,
    search: Optional[str] = None,
    state_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    """List cities with optional search and state filter"""
    return service.get_cities(db, skip=skip, limit=limit, search=search, state_id=state_id)


# POST - Create a new city
@router.post("/", response_model=CityOut, status_code=status.HTTP_201_CREATED)
def create_city(city: CityCreate, db: Session = Depends(get_db)):
    """Create a city with optional code and ERP external ID"""
    return service.create_city(
        db,
        name=city.name,
        state_id=city.state_id,
        code=getattr(city, "code", None),
        erp_external_id=getattr(city, "erp_external_id", None)
    )


# GET - Retrieve a single city
@router.get("/{city_id}", response_model=CityOut)
def get_city(city_id: int, db: Session = Depends(get_db)):
    """Fetch a single city by ID"""
    city = service.get_city(db, city_id)
    return city


# PUT - Update an existing city
@router.put("/{city_id}", response_model=CityOut)
def update_city(city_id: int, updates: CityUpdate, db: Session = Depends(get_db)):
    """Update a city using only the provided fields"""
    # For Pydantic v2
    update_data = updates.model_dump(exclude_unset=True)
    return service.update_city(db, city_id, update_data)


# DELETE - Delete a city
@router.delete("/{city_id}", response_model=CityOut)
def delete_city(city_id: int, db: Session = Depends(get_db)):
    """Delete a city"""
    deleted_city = service.delete_city(db, city_id)
    if not deleted_city:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="City not found")
    return deleted_city
