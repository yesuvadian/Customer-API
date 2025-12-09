from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from models import CompanyTaxDocument, CompanyTaxInfo


class CompanyTaxDocumentService:

    # =====================================================
    # Helpers
    # =====================================================

    @classmethod
    def get_document(cls, db: Session, document_id: int):
        return db.query(CompanyTaxDocument).filter(
            CompanyTaxDocument.id == document_id
        ).first()

    @classmethod
    def delete_document(cls, db: Session, document_id: int):
        doc = cls.get_document(db, document_id)
        if not doc:
            return None

        db.delete(doc)
        db.commit()
        return doc

    # =====================================================
    # Company Operations
    # =====================================================

    @classmethod
    def get_tax_info_by_company(cls, db: Session, company_id: UUID):
        tax_info = db.query(CompanyTaxInfo).filter(
            CompanyTaxInfo.company_id == company_id
        ).first()

        if not tax_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company tax info not found for this company"
            )

        return tax_info

    @classmethod
    def get_documents_by_company(cls, db: Session, company_id: UUID):
        tax_info = cls.get_tax_info_by_company(db, company_id)
        return db.query(CompanyTaxDocument).filter(
            CompanyTaxDocument.company_tax_info_id == tax_info.id
        ).all()

    # =====================================================
    # Unique Category Check
    # =====================================================

    @classmethod
    def document_exists_for_category(cls, db: Session, tax_info_id: int, category_detail_id: int):
        return db.query(CompanyTaxDocument).filter(
            CompanyTaxDocument.company_tax_info_id == tax_info_id,
            CompanyTaxDocument.category_detail_id == category_detail_id
        ).first()

    # =====================================================
    # Create Document
    # =====================================================

    @classmethod
    def create_document_for_company(
        cls,
        db: Session,
        company_id: UUID,
        category_detail_id: int,
        file_name: str,
        file_data: bytes,
        file_type: str
    ):

        tax_info = cls.get_tax_info_by_company(db, company_id)

        # 🚫 Prevent uploading more than one document for same category
        existing = cls.document_exists_for_category(db, tax_info.id, category_detail_id)
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Document already exists for this category (category_detail_id={category_detail_id})"
            )

        doc = CompanyTaxDocument(
            company_tax_info_id=tax_info.id,
            category_detail_id=category_detail_id,
            file_name=file_name,
            file_data=file_data,
            file_type=file_type
        )

        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc
