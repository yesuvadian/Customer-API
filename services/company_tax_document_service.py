from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyTaxDocument, CompanyTaxInfo


class CompanyTaxDocumentService:

    # =====================================================
    # Generic CRUD by document ID
    # =====================================================
    @classmethod
    def get_document(cls, db: Session, doc_id: int):
        """Fetch document by ID"""
        return db.query(CompanyTaxDocument).filter(CompanyTaxDocument.id == doc_id).first()

    @classmethod
    def delete_document(cls, db: Session, doc_id: int):
        """Delete document by ID"""
        doc = cls.get_document(db, doc_id)
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        db.delete(doc)
        db.commit()
        return doc

    @classmethod
    def update_document(cls, db: Session, doc_id: int, file_name: str = None, file_data: bytes = None, file_type: str = None):
        """Replace or rename an existing document"""
        doc = cls.get_document(db, doc_id)
        if not doc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

        if file_name:
            doc.file_name = file_name
        if file_data:
            doc.file_data = file_data
        if file_type:
            doc.file_type = file_type

        db.commit()
        db.refresh(doc)
        return doc

    # =====================================================
    # Company ID–based operations
    # =====================================================
    @classmethod
    def get_tax_info_by_company(cls, db: Session, company_id: str):
        """Get the CompanyTaxInfo row for a company (required to link documents)"""
        tax_info = db.query(CompanyTaxInfo).filter(CompanyTaxInfo.company_id == company_id).first()
        if not tax_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company tax info not found for this company"
            )
        return tax_info

    @classmethod
    def get_documents_by_company(cls, db: Session, company_id: str):
        """Fetch all documents for a given company ID"""
        tax_info = cls.get_tax_info_by_company(db, company_id)
        return db.query(CompanyTaxDocument).filter(
            CompanyTaxDocument.company_tax_info_id == tax_info.id
        ).all()

    @classmethod
    def create_document_for_company(cls, db: Session, company_id: str, file_name: str, file_data: bytes, file_type: str):
        """Create a document for a company (auto-links to CompanyTaxInfo)"""
        tax_info = cls.get_tax_info_by_company(db, company_id)
        doc = CompanyTaxDocument(
            company_tax_info_id=tax_info.id,
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