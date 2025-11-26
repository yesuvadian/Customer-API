from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyTaxDocument, CompanyTaxInfo
from uuid import UUID # ✅ Add UUID import

class CompanyTaxDocumentService:
    # ... (Generic CRUD methods unchanged)

    # =====================================================
    # Company ID–based operations
    # =====================================================
    @classmethod
    def get_tax_info_by_company(cls, db: Session, company_id: UUID): # ✅ Change type from str to UUID
        """Get the CompanyTaxInfo row for a company (required to link documents)"""
        # SQLAlchemy can query UUID column directly with a UUID object
        tax_info = db.query(CompanyTaxInfo).filter(CompanyTaxInfo.company_id == company_id).first()
        if not tax_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company tax info not found for this company"
            )
        return tax_info

    @classmethod
    def get_documents_by_company(cls, db: Session, company_id: UUID): # ✅ Change type from str to UUID
        """Fetch all documents for a given company ID"""
        tax_info = cls.get_tax_info_by_company(db, company_id)
        return db.query(CompanyTaxDocument).filter(
            CompanyTaxDocument.company_tax_info_id == tax_info.id
        ).all()

    @classmethod
    def create_document_for_company(cls, db: Session, company_id: UUID, file_name: str, file_data: bytes, file_type: str): # ✅ Change type from str to UUID
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
    # ...