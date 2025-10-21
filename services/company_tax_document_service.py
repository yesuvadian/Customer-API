from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyTaxDocument

class CompanyTaxDocumentService:

    @classmethod
    def get_document(cls, db: Session, doc_id: int):
        return db.query(CompanyTaxDocument).filter(CompanyTaxDocument.id == doc_id).first()

    @classmethod
    def get_documents(cls, db: Session, company_tax_info_id: int):
        return db.query(CompanyTaxDocument).filter(CompanyTaxDocument.company_tax_info_id == company_tax_info_id).all()

    @classmethod
    def create_document(cls, db: Session, company_tax_info_id: int, file_name: str, file_data: bytes, file_type: str):
        doc = CompanyTaxDocument(
            company_tax_info_id=company_tax_info_id,
            file_name=file_name,
            file_data=file_data,
            file_type=file_type
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    @classmethod
    def delete_document(cls, db: Session, doc_id: int):
        doc = cls.get_document(db, doc_id)
        if doc:
            db.delete(doc)
            db.commit()
        return doc
