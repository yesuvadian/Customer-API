from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
#from schemas import CountryCreate, CountryUpdate, CountryOut
from schemas import CountryCreate, CountryOut, CountryUpdate
from services.country_service import CountryService

router = APIRouter(prefix="/countries", tags=["countries"],dependencies=[Depends(get_current_user)])
service = CountryService()

@router.get("/", response_model=list[CountryOut])
def list_countries(skip: int = 0, limit: int = 100, search: str = None, db: Session = Depends(get_db)):
    return service.get_countries(db, skip=skip, limit=limit, search=search)

@router.post("/", response_model=CountryOut)
def create_country(country: CountryCreate, db: Session = Depends(get_db)):
    return service.create_country(db, name=country.name, code=country.code)

@router.get("/{country_id}", response_model=CountryOut)
def get_country(country_id: int, db: Session = Depends(get_db)):
    country = service.get_country(db, country_id)
    if not country:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Country not found")
    return country

@router.put("/{country_id}", response_model=CountryOut)
def update_country(country_id: int, updates: CountryUpdate, db: Session = Depends(get_db)):
    return service.update_country(db, country_id, updates.dict(exclude_unset=True))

@router.delete("/{country_id}", response_model=CountryOut)
def delete_country(country_id: int, db: Session = Depends(get_db)):
    return service.delete_country(db, country_id)
