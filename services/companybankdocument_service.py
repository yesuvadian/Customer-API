from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyBankDocument


class CompanyBankDocumentService:

    @classmethod
    def get_document(cls, db: Session, document_id: int):
        return db.query(CompanyBankDocument).filter(CompanyBankDocument.id == document_id).first()

    @classmethod
    def get_documents_by_bank_info(cls, db: Session, bank_info_id: int):
        return (
            db.query(CompanyBankDocument)
            .filter(CompanyBankDocument.company_bank_info_id == bank_info_id)
            .all()
        )

    @classmethod
    def create_document(cls, db: Session, *, bank_info_id: int, file_name: str, file_data: bytes, file_type: str | None = None,
                         category_detail_id: int | None = None):
        document = CompanyBankDocument(
            company_bank_info_id=bank_info_id,
            file_name=file_name,
            file_data=file_data,
            file_type=file_type,
            # CHANGE: Map to the correct model field
            category_detail_id=category_detail_id
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document

    @classmethod
    def update_document(cls, db: Session, document_id: int, updates: dict):
        document = cls.get_document(db, document_id)
        if not document:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Bank document not found"
            )

        for key, value in updates.items():
            if hasattr(document, key):
                setattr(document, key, value)

        db.commit()
        db.refresh(document)
        return document

    @classmethod
    def delete_document(cls, db: Session, document_id: int):
        doc = db.query(CompanyBankDocument).filter(CompanyBankDocument.id == document_id).first()

        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")

        db.delete(doc)
        db.commit() 
