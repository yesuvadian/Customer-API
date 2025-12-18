import os
from dotenv import load_dotenv
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    status,
    Response
)
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from services.companybankdocument_service import CompanyBankDocumentService

# -----------------------------------------------------
# ENV
# -----------------------------------------------------
load_dotenv()
MAX_FILE_SIZE_KB = int(os.getenv("MAX_FILE_SIZE_KB", 500))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_KB * 1024

router = APIRouter(
    prefix="/bank_documents",
    tags=["vendor-bank-documents"],
    dependencies=[Depends(get_current_user)]
)

service = CompanyBankDocumentService()


# =====================================================
# GET ALL DOCUMENTS FOR BANK INFO
# =====================================================
@router.get("/{bank_info_id}")
def list_bank_documents(bank_info_id: int, db: Session = Depends(get_db)):
    docs = service.get_documents_by_bank_info(db, bank_info_id)

    return [
        {
            "id": d.id,
            "company_bank_info_id": d.company_bank_info_id,
            "category_detail_id": d.category_detail_id,
            "file_name": d.file_name,
            "file_type": d.file_type,
            "cts": d.cts,
            "mts": d.mts,

            # ✅ SAME STRUCTURE AS TAX
            "document_type_detail": (
                {
                    "id": d.category_detail.id,
                    "name": d.category_detail.name,
                }
                if d.category_detail
                else None
            ),
        }
        for d in docs
    ]


# =====================================================
# UPLOAD BANK DOCUMENT (ONE PER CATEGORY)
# =====================================================
@router.post("/", status_code=status.HTTP_201_CREATED)
async def upload_bank_document(
    bank_info_id: int = Form(...),
    category_detail_id: int = Form(...),  # REQUIRED
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        # ✅ SAFE READ (Excel compatible)
        file_data = await file.read()

        # ✅ FILE SIZE CHECK (same as TAX)
        if len(file_data) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Max size allowed: {MAX_FILE_SIZE_KB} KB"
            )

        doc = service.create_document(
            db=db,
            bank_info_id=bank_info_id,
            category_detail_id=category_detail_id,
            file_name=file.filename,
            file_data=file_data,
            file_type=file.content_type,
        )

        return {
            "id": doc.id,
            "company_bank_info_id": doc.company_bank_info_id,
            "category_detail_id": doc.category_detail_id,
            "file_name": doc.file_name,
            "file_type": doc.file_type,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to upload bank document: {e}"
        )


# =====================================================
# DELETE DOCUMENT
# =====================================================
@router.delete("/{document_id}", status_code=204)
def delete_bank_document(document_id: int, db: Session = Depends(get_db)):
    service.delete_document(db, document_id)
    return Response(status_code=204)
