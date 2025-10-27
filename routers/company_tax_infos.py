from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from schemas import CompanyTaxInfoCreate, CompanyTaxInfoUpdate, CompanyTaxInfoOut
from services.company_tax_service import CompanyTaxService

router = APIRouter(
    prefix="/company_tax_info",
    tags=["company_tax_info"],
    dependencies=[Depends(get_current_user)]
)

service = CompanyTaxService()

# =====================================================
# Existing endpoints (by tax_id)
# =====================================================

@router.get("/", response_model=list[CompanyTaxInfoOut])
def list_company_tax_infos(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    """Fetch all company tax infos (paginated)"""
    return service.get_company_tax_infos(db, skip=skip, limit=limit)


@router.post("/", response_model=CompanyTaxInfoOut, status_code=status.HTTP_201_CREATED)
def create_company_tax_info(tax_info: CompanyTaxInfoCreate, db: Session = Depends(get_db)):
    """Create a new tax info record (generic)"""
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
    """Fetch tax info by tax_id"""
    tax_info = service.get_tax_info(db, tax_id)
    if not tax_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tax info not found")
    return tax_info


@router.put("/{tax_id}", response_model=CompanyTaxInfoOut)
def update_company_tax_info(tax_id: int, updates: CompanyTaxInfoUpdate, db: Session = Depends(get_db)):
    """Update tax info by tax_id"""
    return service.update_tax_info(db, tax_id, updates.dict(exclude_unset=True))


@router.delete("/{tax_id}", response_model=CompanyTaxInfoOut)
def delete_company_tax_info(tax_id: int, db: Session = Depends(get_db)):
    """Delete tax info by tax_id"""
    return service.delete_tax_info(db, tax_id)


# =====================================================
# New endpoints (by company_id)
# =====================================================

@router.get("/company/{company_id}", response_model=CompanyTaxInfoOut)
def get_tax_info_by_company(company_id: str, db: Session = Depends(get_db)):
    """
    Fetch tax info for a specific company by company_id.
    Returns 404 if not found.
    """
    return service.get_by_company_id(db, company_id)


@router.post("/company/{company_id}", response_model=CompanyTaxInfoOut, status_code=status.HTTP_201_CREATED)
def create_tax_info_for_company(company_id: str, tax_info: CompanyTaxInfoCreate, db: Session = Depends(get_db)):
    """
    Create a tax info record for a specific company.
    Raises 400 if a record already exists for that company.
    """
    return service.create_for_company(db, company_id, tax_info.dict(exclude_unset=True))


@router.put("/company/{company_id}", response_model=CompanyTaxInfoOut)
def update_tax_info_for_company(company_id: str, updates: CompanyTaxInfoUpdate, db: Session = Depends(get_db)):
    """
    Update existing tax info for a specific company.
    Raises 404 if no record exists for that company.
    """
    return service.update_for_company(db, company_id, updates.dict(exclude_unset=True))
