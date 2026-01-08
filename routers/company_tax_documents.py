import os
from uuid import UUID
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    status
)
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from services.company_tax_document_service import CompanyTaxDocumentService

# Load env
load_dotenv()
MAX_FILE_SIZE_KB = int(os.getenv("MAX_FILE_SIZE_KB", 10000))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_KB * 1024

router = APIRouter(
    prefix="/company_tax_documents",
    tags=["company_tax_documents"],
    dependencies=[Depends(get_current_user)],
)

service = CompanyTaxDocumentService()


# =====================================================
# GET SINGLE DOCUMENT
# =====================================================
@router.get("/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = service.get_document(db, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    return {
        "id": doc.id,
        "company_tax_info_id": doc.company_tax_info_id,
        "category_detail_id": doc.category_detail_id,
        "file_name": doc.file_name,
        "file_type": doc.file_type,
    }


# =====================================================
# GET ALL DOCUMENTS FOR COMPANY
# =====================================================
@router.get("/company/{company_id}")
def get_company_documents(company_id: UUID, db: Session = Depends(get_db)):
    docs = service.get_documents_by_company(db, company_id)

    return [
        {
            "id": d.id,
            "company_tax_info_id": d.company_tax_info_id,
            "category_detail_id": d.category_detail_id,
            "file_name": d.file_name,
            "file_type": d.file_type,
            "pending_kyc": d.pending_kyc,
            "cts": d.cts,
            "mts": d.mts,

            # ✅ THIS FIXES YOUR ISSUE
                    "document_type_detail": (
                        {
                            "id": d.category_detail.id,
                            "name": d.category_detail.name,
                        }
                        if d.category_detail_id
                        else None
                    ),

        }
        for d in docs
    ]



# =====================================================
# UPLOAD DOCUMENT (ONE PER CATEGORY)
# =====================================================
@router.post("/company/{company_id}", status_code=status.HTTP_201_CREATED)
def upload_company_document(
    company_id: UUID,
    category_detail_id: int = Form(...),  # <-- REQUIRED
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        file_data = file.file.read()

        # Validate file size
        if len(file_data) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                400,
                f"File too large. Max size allowed: {MAX_FILE_SIZE_KB} MB"
            )

        doc = service.create_document_for_company(
            db=db,
            company_id=company_id,
            category_detail_id=category_detail_id,
            file_name=file.filename,
            file_data=file_data,
            file_type=file.content_type,
        )

        return {
            "id": doc.id,
            "company_tax_info_id": doc.company_tax_info_id,
            "category_detail_id": doc.category_detail_id,
            "file_name": doc.file_name,
            "file_type": doc.file_type,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to upload document: {e}")


# =====================================================
# DELETE DOCUMENT
# =====================================================
@router.delete("/{doc_id}", status_code=204)
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    deleted = service.delete_document(db, doc_id)

    if not deleted:
        raise HTTPException(404, "Document not found")

    return
