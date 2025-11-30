from typing import Optional
from fastapi import HTTPException, status
from sqlalchemy.orm import Session,joinedload
from models import CompanyTaxDocument, CompanyTaxInfo
from uuid import UUID # ✅ Add UUID import

class CompanyTaxDocumentService:
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
    def get_documents_by_company(cls, db: Session, company_id: UUID):
        """Fetch all tax documents for a given company"""

        tax_info = cls.get_tax_info_by_company(db, company_id)

        return (
            db.query(CompanyTaxDocument)
            .options(joinedload(CompanyTaxDocument.category_detail))   # ✅ load CategoryDetails
            .filter(
                CompanyTaxDocument.company_tax_info_id == tax_info.id
            )
            .all()
        )


    @classmethod
    def create_document_for_company(
        cls, 
        db: Session, 
        company_id: UUID, 
        file_name: str, 
        file_data: bytes, 
        file_type: str, 
        # 👇 ADDED THE OPTIONAL PARAMETER
        category_detail_id: Optional[int] = None 
    ):
        """Create a document for a company (auto-links to CompanyTaxInfo)"""
        tax_info = cls.get_tax_info_by_company(db, company_id)
        
        doc = CompanyTaxDocument(
            company_tax_info_id=tax_info.id,
            file_name=file_name,
            file_data=file_data,
            file_type=file_type,
            # 👇 SAVE THE NEW PARAMETER
            category_detail_id=category_detail_id 
        )
        
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc
    @classmethod
    def update_document(
        cls, 
        db: Session, 
        doc_id: int, 
        file_name: str, 
        file_data: bytes, 
        file_type: str,
        category_detail_id: Optional[int] = None
    ):
        """
        Updates an existing CompanyTaxDocument record with new file content and details.
        """
        # 1. Fetch the existing document
        doc = cls.get_document(db, doc_id)

        # 2. Apply updates
        doc.file_name = file_name
        doc.file_data = file_data # The new file content
        doc.file_type = file_type
        
        if category_detail_id is not None:
             doc.category_detail_id = category_detail_id

        # 3. Mark for ERP resync upon update
        doc.pending_kyc = True
        doc.erp_sync_status = "pending"

        # 4. Commit changes
        db.commit()
        db.refresh(doc)
        
        return doc