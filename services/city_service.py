# city_service.py
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from models import City, State  # Adjust import paths if needed


class CityService:

    @classmethod
    def get_city(cls, db: Session, city_id: int) -> City:
        """Fetch a single city by ID"""
        city = db.query(City).filter(City.id == city_id).first()
        if not city:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"City ID {city_id} not found"
            )
        return city

    @classmethod
    def get_cities(
        cls,
        db: Session,
        skip: int = 0,
        limit: int = 10000,
        search: Optional[str] = None,
        state_id: Optional[int] = None
    ) -> List[City]:
        """Fetch cities with optional filters"""
        query = db.query(City)

        if state_id is not None:
            query = query.filter(City.state_id == state_id)

        if search:
            query = query.filter(City.name.ilike(f"%{search}%"))

        return query.offset(skip).limit(limit).all()

    @classmethod
    def create_city(
        cls,
        db: Session,
        name: str,
        state_id: int,
        erp_external_id: Optional[str] = None
    ) -> City:
        """Create a new city with validations"""
        # Check if state exists
        state = db.query(State).filter(State.id == state_id).first()
        if not state:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"State ID {state_id} not found"
            )

        # Check for duplicate city in the same state
        existing = db.query(City).filter(
            City.name == name,
            City.state_id == state_id
        ).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"City '{name}' already exists in state ID {state_id}"
            )

        city = City(
            name=name,
            state_id=state_id,
            erp_external_id=erp_external_id
        )
        db.add(city)
        try:
            db.commit()
            db.refresh(city)
            return city
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error creating city: {str(e)}"
            )

    @classmethod
    def update_city(cls, db: Session, city_id: int, updates: Dict[str, Any]) -> City:
        """Update an existing city"""
        city = cls.get_city(db, city_id)

        # Only update allowed fields
        allowed_fields = {"name", "state_id", "erp_external_id"}
        for key, value in updates.items():
            if key in allowed_fields:
                setattr(city, key, value)

        # Validate state_id if being updated
        if "state_id" in updates:
            state = db.query(State).filter(State.id == updates["state_id"]).first()
            if not state:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"State ID {updates['state_id']} not found"
                )

        try:
            db.commit()
            db.refresh(city)
            return city
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error updating city: {str(e)}"
            )

    @classmethod
    def delete_city(cls, db: Session, city_id: int) -> Optional[City]:
        """Delete a city"""
        city = cls.get_city(db, city_id)
        db.delete(city)
        try:
            db.commit()
            return city
        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error deleting city: {str(e)}"
            )
