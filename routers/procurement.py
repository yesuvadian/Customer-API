from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from schemas import ProcurementRequestCreate, ProcurementRequestUpdate, ProcurementRequestResponse
from services.procurement_service import ProcurementService

router = APIRouter(
    prefix="/validation_requests",
    tags=["validation_requests"],
    dependencies=[Depends(get_current_user)],
)


@router.post("/", response_model=ProcurementRequestResponse)
def create_procurement_request(
    data: ProcurementRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.create_procurement(data.dict(), raised_by=current_user.id)


@router.get("/", response_model=List[ProcurementRequestResponse])
def list_procurement_requests(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = None,
    raised_by: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.get_procurements(
        skip=skip,
        limit=limit,
        status_filter=status,
        raised_by=raised_by,
    )


@router.get("/{procurement_id}", response_model=ProcurementRequestResponse)
def get_procurement_request(
    procurement_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.get_procurement(procurement_id)


@router.put("/{procurement_id}", response_model=ProcurementRequestResponse)
def update_procurement_request(
    procurement_id: UUID,
    data: ProcurementRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.update_procurement(procurement_id, data.dict(exclude_unset=True), modified_by=current_user.id)


@router.put("/{procurement_id}/complete", response_model=ProcurementRequestResponse)
def complete_procurement(
    procurement_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = ProcurementService(db)
    return service.complete_procurement(procurement_id, modified_by=current_user.id)
