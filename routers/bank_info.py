from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Form
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from models import User
from schemas import CompanyBankInfoCreateSchema, CompanyBankInfoSchema, CompanyBankInfoUpdateSchema
from services.companybankinfo_service import CompanyBankInfoService

router = APIRouter(
    prefix="/company_bank_info",
    tags=["vendor-bank-info"],
    dependencies=[Depends(get_current_user)]
)

@router.get("/", response_model=list[CompanyBankInfoSchema])
def list_bank_info(db: Session = Depends(get_db)):
    return CompanyBankInfoService.get_vendor_bank_info(db, get_current_user().id)

@router.get("/company/{company_id}", response_model=list[CompanyBankInfoSchema])
def get_bank_info_by_company_id(company_id: UUID, db: Session = Depends(get_db)):
    bank_info = CompanyBankInfoService.get_bank_info_by_company_id(db, company_id)
    if not bank_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No bank info found for this company"
        )
    return bank_info

@router.get("/{bank_info_id}", response_model=CompanyBankInfoSchema)
def get_bank_info(bank_info_id: int, db: Session = Depends(get_db)):
    bank_info = CompanyBankInfoService.get_bank_info(db, bank_info_id)
    if not bank_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bank info not found")
    return bank_info

from fastapi import Form

@router.post("/", response_model=CompanyBankInfoSchema)
def create_bank_info(
    account_holder_name: str = Form(...),
    account_number: str = Form(...),
    ifsc: str = Form(...),
    bank_name: str = Form(...),
    branch_name: str = Form(""),   # FIXED
    account_type_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):

    company_id = UUID(str(current_user.id))

    data = {
        "account_holder_name": account_holder_name,
        "bank_name": bank_name,
        "branch_name": branch_name,
        "account_number": account_number,
        "ifsc": ifsc,
        "account_type_detail_id": account_type_id
    }

    return CompanyBankInfoService.create_bank_info(db, company_id, data)

@router.put("/{bank_info_id}", response_model=CompanyBankInfoSchema)
def update_bank_info(bank_info_id: int, updates: CompanyBankInfoUpdateSchema, db: Session = Depends(get_db)):
    return CompanyBankInfoService.update_bank_info(
        db,
        bank_info_id=bank_info_id,
        updates=updates.dict(exclude_unset=True)
    )

@router.delete("/{bank_info_id}", response_model=CompanyBankInfoSchema)
def delete_bank_info(bank_info_id: int, db: Session = Depends(get_db)):
    return CompanyBankInfoService.delete_bank_info(db, bank_info_id)
