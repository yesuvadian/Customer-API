from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyBankInfo


class CompanyBankInfoService:

    @classmethod
    def get_bank_info(cls, db: Session, bank_info_id: int):
        return db.query(CompanyBankInfo).filter(CompanyBankInfo.id == bank_info_id).first()
    @classmethod
    
    def get_bank_info_by_company_id(cls, db: Session, company_id: UUID):
        return (
            db.query(CompanyBankInfo)
            .filter(CompanyBankInfo.company_id == company_id)
            .all()
        )

    @classmethod
    def get_vendor_bank_info(cls, db: Session, user_id: str):
        return db.query(CompanyBankInfo).filter(CompanyBankInfo.company_id == user_id).all()

    @classmethod
    def create_bank_info(cls, db: Session, company_id: UUID, data: dict):
        bank_info = CompanyBankInfo(
            company_id=company_id,
            **data,
        )
        db.add(bank_info)
        db.commit()
        db.refresh(bank_info)
        return bank_info


    @classmethod
    def update_bank_info(cls, db: Session, bank_info_id: int, updates: dict):
        bank_info = cls.get_bank_info(db, bank_info_id)
        if not bank_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bank info not found"
            )

        for key, value in updates.items():
            if hasattr(bank_info, key):
                setattr(bank_info, key, value)

        db.commit()
        db.refresh(bank_info)
        return bank_info

    @classmethod
    def delete_bank_info(cls, db: Session, bank_info_id: int):
        bank_info = cls.get_bank_info(db, bank_info_id)
        if bank_info:
            db.delete(bank_info)
            db.commit()
        return bank_info
