from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyTaxInfo

class CompanyTaxService:

    @classmethod
    def get_tax_info(cls, db: Session, tax_id: int):
        return db.query(CompanyTaxInfo).filter(CompanyTaxInfo.id == tax_id).first()

    @classmethod
    def get_company_tax_infos(cls, db: Session, skip: int = 0, limit: int = 100):
        return db.query(CompanyTaxInfo).offset(skip).limit(limit).all()

    @classmethod
    def create_tax_info(cls, db: Session, company_id, pan, gstin=None, tan=None, state_id=None, financial_year=None):
        # Optional: add uniqueness checks for PAN/GSTIN/TAN
        existing = db.query(CompanyTaxInfo).filter((CompanyTaxInfo.pan == pan) | 
                                                   (CompanyTaxInfo.gstin == gstin) | 
                                                   (CompanyTaxInfo.tan == tan)).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="PAN/GSTIN/TAN already exists")
        tax_info = CompanyTaxInfo(
            company_id=company_id,
            pan=pan,
            gstin=gstin,
            tan=tan,
            state_id=state_id,
            financial_year=financial_year
        )
        db.add(tax_info)
        db.commit()
        db.refresh(tax_info)
        return tax_info

    @classmethod
    def update_tax_info(cls, db: Session, tax_id: int, updates: dict):
        tax_info = cls.get_tax_info(db, tax_id)
        if not tax_info:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tax info not found")
        for key, value in updates.items():
            setattr(tax_info, key, value)
        db.commit()
        db.refresh(tax_info)
        return tax_info

    @classmethod
    def delete_tax_info(cls, db: Session, tax_id: int):
        tax_info = cls.get_tax_info(db, tax_id)
        if tax_info:
            db.delete(tax_info)
            db.commit()
        return tax_info
