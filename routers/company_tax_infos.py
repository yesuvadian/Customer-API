from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from schemas import CompanyTaxInfoCreate, CompanyTaxInfoUpdate, CompanyTaxInfoOut
from services.company_tax_service import CompanyTaxService

router = APIRouter(prefix="/company_tax_info", tags=["company_tax_info"],dependencies=[Depends(get_current_user)])
service = CompanyTaxService()

@router.get("/", response_model=list[CompanyTaxInfoOut])
def list_company_tax_infos(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return service.get_company_tax_infos(db, skip=skip, limit=limit)

@router.post("/", response_model=CompanyTaxInfoOut)
def create_company_tax_info(tax_info: CompanyTaxInfoCreate, db: Session = Depends(get_db)):
    return service.create_tax_info(
        db,
        company_id=tax_info.company_id,
        pan=tax_info.pan,
        gstin=tax_info.gstin,
        tan=tax_info.tan,
        state_id=tax_info.state_id,
        financial_year=tax_info.financial_year
    )

@router.get("/{tax_id}", response_model=CompanyTaxInfoOut)
def get_company_tax_info(tax_id: int, db: Session = Depends(get_db)):
    tax_info = service.get_tax_info(db, tax_id)
    if not tax_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tax info not found")
    return tax_info

@router.put("/{tax_id}", response_model=CompanyTaxInfoOut)
def update_company_tax_info(tax_id: int, updates: CompanyTaxInfoUpdate, db: Session = Depends(get_db)):
    return service.update_tax_info(db, tax_id, updates.dict(exclude_unset=True))

@router.delete("/{tax_id}", response_model=CompanyTaxInfoOut)
def delete_company_tax_info(tax_id: int, db: Session = Depends(get_db)):
    return service.delete_tax_info(db, tax_id)
