from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyBankDocument, CompanyBankInfo


class CompanyBankDocumentService:

    # =====================================================
    # Helpers
    # =====================================================

    @classmethod
    def get_document(cls, db: Session, document_id: int):
        return db.query(CompanyBankDocument).filter(
            CompanyBankDocument.id == document_id
        ).first()

    @classmethod
    def get_bank_info(cls, db: Session, bank_info_id: int):
        bank_info = db.query(CompanyBankInfo).filter(
            CompanyBankInfo.id == bank_info_id
        ).first()

        if not bank_info:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Company bank info not found"
            )

        return bank_info

    @classmethod
    def get_documents_by_bank_info(cls, db: Session, bank_info_id: int):
        cls.get_bank_info(db, bank_info_id)  # validate
        return db.query(CompanyBankDocument).filter(
            CompanyBankDocument.company_bank_info_id == bank_info_id
        ).all()

    # =====================================================
    # Unique Category Check (SAME AS TAX)
    # =====================================================

    @classmethod
    def document_exists_for_category(
        cls,
        db: Session,
        bank_info_id: int,
        category_detail_id: int
    ):
        return db.query(CompanyBankDocument).filter(
            CompanyBankDocument.company_bank_info_id == bank_info_id,
            CompanyBankDocument.category_detail_id == category_detail_id
        ).first()

    # =====================================================
    # Create Document (TAX-STYLE)
    # =====================================================

    @classmethod
    def create_document(
        cls,
        db: Session,
        bank_info_id: int,
        category_detail_id: int,
        file_name: str,
        file_data: bytes,
        file_type: str
    ):
        cls.get_bank_info(db, bank_info_id)

        # 🚫 Prevent duplicate category documents
        existing = cls.document_exists_for_category(
            db, bank_info_id, category_detail_id
        )
        if existing:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Document already exists for this category "
                    f"(category_detail_id={category_detail_id})"
                )
            )

        doc = CompanyBankDocument(
            company_bank_info_id=bank_info_id,
            category_detail_id=category_detail_id,
            file_name=file_name,
            file_data=file_data,
            file_type=file_type
        )

        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    # =====================================================
    # Delete
    # =====================================================

    @classmethod
    def delete_document(cls, db: Session, document_id: int):
        doc = cls.get_document(db, document_id)
        if not doc:
            raise HTTPException(
                status_code=404,
                detail="Bank document not found"
            )

        db.delete(doc)
        db.commit()
        return doc
