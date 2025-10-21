from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import Country

class CountryService:

    @classmethod
    def get_country(cls, db: Session, country_id: int):
        return db.query(Country).filter(Country.id == country_id).first()

    @classmethod
    def get_countries(cls, db: Session, skip: int = 0, limit: int = 100, search: str = None):
        query = db.query(Country)
        if search:
            query = query.filter(Country.name.ilike(f"%{search}%"))
        return query.offset(skip).limit(limit).all()

    @classmethod
    def create_country(cls, db: Session, name: str, code: str | None = None):
        existing = db.query(Country).filter(Country.name == name).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Country already exists")
        country = Country(name=name, code=code)
        db.add(country)
        db.commit()
        db.refresh(country)
        return country

    @classmethod
    def update_country(cls, db: Session, country_id: int, updates: dict):
        country = cls.get_country(db, country_id)
        if not country:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Country not found")
        for key, value in updates.items():
            setattr(country, key, value)
        db.commit()
        db.refresh(country)
        return country

    @classmethod
    def delete_country(cls, db: Session, country_id: int):
        country = cls.get_country(db, country_id)
        if country:
            db.delete(country)
            db.commit()
        return country
