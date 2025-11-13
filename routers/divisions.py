from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from uuid import UUID

from schemas import DivisionCreate, DivisionResponse, DivisionUpdate
from services.divisionservice import DivisionService

router = APIRouter(
    prefix="/divisions",
    tags=["divisions"],
    dependencies=[Depends(get_current_user)]
)


@router.post("/", response_model=DivisionResponse)
def create_division(division: DivisionCreate, db: Session = Depends(get_db)):
    service = DivisionService(db)
    try:
        return service.create_division(
            division_name=division.division_name,
            description=division.description
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{division_id}", response_model=DivisionResponse)
def get_division(division_id: UUID, db: Session = Depends(get_db)):
    service = DivisionService(db)
    try:
        return service.get_division(division_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/", response_model=List[DivisionResponse])
def list_divisions(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    service = DivisionService(db)
    return service.list_divisions(skip=skip, limit=limit)


@router.put("/{division_id}", response_model=DivisionResponse)
def update_division(division_id: UUID, division: DivisionUpdate, db: Session = Depends(get_db)):
    service = DivisionService(db)
    try:
        return service.update_division(
            division_id=division_id,
            division_name=division.division_name,
            description=division.description
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{division_id}", response_model=dict)
def delete_division(division_id: UUID, db: Session = Depends(get_db)):
    service = DivisionService(db)
    try:
        service.delete_division(division_id)
        return {"message": "Division deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
