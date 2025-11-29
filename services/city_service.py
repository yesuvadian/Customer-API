# city_service.py
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import City # Assuming your model is in city_model.py
from typing import Optional

class CityService:

    @classmethod
    def get_cities(cls, db: Session, skip: int = 0, limit: int = 100, search: str = None, state_id: int = None) -> list[City]: # <-- ADD state_id
        query = db.query(City)
        
        if state_id: # <-- NEW FILTER
            query = query.filter(City.state_id == state_id)
            
        if search:
            query = query.filter(City.name.ilike(f"%{search}%") | City.code.ilike(f"%{search}%")) 
            
        return query.offset(skip).limit(limit).all()

    @classmethod
    def create_city(cls, db: Session, name: str, state_id: int, code: str | None = None) -> City: # <-- ADDED code
        # Check for existing city with the same name and state_id 
        existing_name_state = db.query(City).filter(
            City.name == name,
            City.state_id == state_id
        ).first()
        if existing_name_state:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"City '{name}' already exists in state ID {state_id}")
        
        city = City(name=name, code=code, state_id=state_id) # <-- Used code
        db.add(city)
        try:
            db.commit()
            db.refresh(city)
            return city
        except Exception as e:
            db.rollback()
            # Catch DB-specific errors like unique constraint violation for 'code'
            if "cities_code_key" in str(e):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"City code '{code}' is already in use.")
            raise

    @classmethod
    def update_city(cls, db: Session, city_id: int, updates: dict) -> City:
        city = cls.get_city(db, city_id)
        if not city:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="City not found")
            
        for key, value in updates.items():
            setattr(city, key, value)
            
        try:
            db.commit()
            db.refresh(city)
            return city
        except Exception as e:
            db.rollback()
            # Catch unique constraint violation for 'code' during update
            if "cities_code_key" in str(e):
                code_value = updates.get("code", "N/A")
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"City code '{code_value}' is already in use by another city.")
            raise

    @classmethod
    def delete_city(cls, db: Session, city_id: int) -> Optional[City]:
        city = cls.get_city(db, city_id)
        if city:
            db.delete(city)
            db.commit()
        return city