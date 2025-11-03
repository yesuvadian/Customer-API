from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from schemas import CompanyBankInfoCreateSchema, CompanyBankInfoSchema, CompanyBankInfoUpdateSchema
from services.companybankinfo_service import CompanyBankInfoService

router = APIRouter(
    prefix="/bank_info",
    tags=["vendor-bank-info"],
    dependencies=[Depends(get_current_user)]
)

@router.get("/", response_model=list[CompanyBankInfoSchema])
def list_bank_info(db: Session = Depends(get_db)):
    return CompanyBankInfoService.get_vendor_bank_info(db, get_current_user().id)

@router.get("/{bank_info_id}", response_model=CompanyBankInfoSchema)
def get_bank_info(bank_info_id: int, db: Session = Depends(get_db)):
    bank_info = CompanyBankInfoService.get_bank_info(db, bank_info_id)
    if not bank_info:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Bank info not found")
    return bank_info

@router.post("/", response_model=CompanyBankInfoSchema)
def create_bank_info(data: CompanyBankInfoCreateSchema, db: Session = Depends(get_db)):
    return CompanyBankInfoService.create_bank_info(
        db,
        user_id=get_current_user().id,
        data=data.dict()
    )

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
