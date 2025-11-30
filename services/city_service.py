# city_service.py
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import City  # Adjust import if your model is elsewhere
from typing import Optional, List, Dict, Any


class CityService:

    @classmethod
    def get_city(cls, db: Session, city_id: int) -> City:
        """Fetch a single city by ID"""
        city = db.query(City).filter(City.id == city_id).first()
        if not city:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="City not found")
        return city

    @classmethod
    def get_cities(
        cls,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        search: Optional[str] = None,
        state_id: Optional[int] = None
    ) -> List[City]:
        """Fetch cities with optional filters"""
        query = db.query(City)

        if state_id is not None:
            query = query.filter(City.state_id == state_id)

        if search:
            query = query.filter(
                City.name.ilike(f"%{search}%") | City.code.ilike(f"%{search}%")
            )

        return query.offset(skip).limit(limit).all()

    @classmethod
    def create_city(
        cls,
        db: Session,
        name: str,
        state_id: int,
        code: Optional[str] = None,
        erp_external_id: Optional[str] = None,
    ) -> City:
        """Create a new city"""
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
            code=code,
            erp_external_id=erp_external_id
        )
        db.add(city)
        try:
            db.commit()
            db.refresh(city)
            return city
        except Exception as e:
            db.rollback()
            if "cities_code_key" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"City code '{code}' is already in use."
                )
            raise

    @classmethod
    def update_city(cls, db: Session, city_id: int, updates: Dict[str, Any]) -> City:
        """Update an existing city"""
        city = cls.get_city(db, city_id)

        for key, value in updates.items():
            setattr(city, key, value)

        try:
            db.commit()
            db.refresh(city)
            return city
        except Exception as e:
            db.rollback()
            if "cities_code_key" in str(e):
                code_value = updates.get("code", "N/A")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"City code '{code_value}' is already in use by another city."
                )
            raise

    @classmethod
    def delete_city(cls, db: Session, city_id: int) -> Optional[City]:
        """Delete a city"""
        city = cls.get_city(db, city_id)
        if city:
            db.delete(city)
            db.commit()
        return city
