import os
from typing import Optional
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
from dotenv import load_dotenv
from uuid import UUID # <--- 1. ADD THIS IMPORT

from auth_utils import get_current_user
from database import get_db
from services.company_tax_document_service import CompanyTaxDocumentService

# Load environment variables
load_dotenv()
MAX_FILE_SIZE_KB = int(os.getenv("MAX_FILE_SIZE_KB", 500))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_KB * 1024

router = APIRouter(
    prefix="/company_tax_documents",
    tags=["company_tax_documents"],
    dependencies=[Depends(get_current_user)]
)

service = CompanyTaxDocumentService()


# =====================================================
# 📄 Get single document by ID (No change needed)
# =====================================================
@router.get("/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = service.get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return {
        "id": doc.id,
        "company_tax_info_id": doc.company_tax_info_id,
        "file_name": doc.file_name,
        "file_type": doc.file_type,
    }


# =====================================================
# 🏢 Get all documents for a company
# =====================================================
@router.get("/company/{company_id}")
def get_company_tax_documents(company_id: UUID, db: Session = Depends(get_db)):
    docs = service.get_documents_by_company(db, company_id)

    return [
        {
            "id": d.id,
            "company_tax_info_id": d.company_tax_info_id,
            "file_name": d.file_name,
            "file_type": d.file_type,
            "document_type": d.category_detail.name if d.category_detail else None,
            "pending_kyc": d.pending_kyc,
               # ✅ Timestamps
            "cts": d.cts,
            "mts": d.mts,
        }
        for d in docs
    ]




@router.put("/{doc_id}")
def update_company_document(
    doc_id: int,
    file: UploadFile = File(...),
    category_detail_id: Optional[int] = None, # <-- New Parameter
    db: Session = Depends(get_db)
):
    """
    Replace an existing document file (update name/type/content) and optional category.
    """
    try:
        # 1. READ THE FILE DATA (THIS WAS MISSING)
        file_data = file.file.read()

        # 2. FILE SIZE VALIDATION (This was implied by your comments)
        if len(file_data) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Max size allowed: {MAX_FILE_SIZE_KB} KB",
            )
        
        # 3. Call the updated service method
        updated_doc = service.update_document(
            db=db,
            doc_id=doc_id,
            file_name=file.filename,
            file_data=file_data,
            file_type=file.content_type,
            category_detail_id=category_detail_id # <-- Pass the new parameter
        )
        return {"id": updated_doc.id, "file_name": updated_doc.file_name, "file_type": updated_doc.file_type}
        
    except HTTPException as e:
        # Re-raise explicit HTTP exceptions (e.g., 400 for size, 404 from service)
        raise e
    except Exception as e:
        # Catch all other exceptions and return a 500
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating document: {e}"
        )

# =====================================================
# 🗑️ Delete document (No change needed)
# =====================================================
@router.delete("/{doc_id}")
def delete_company_document(doc_id: int, db: Session = Depends(get_db)):
    try:
        deleted_doc = service.delete_document(db, doc_id)
        # ... (rest of the code unchanged)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting document: {e}"
        )
@router.get("/company/{company_id}")
def list_documents(company_id: UUID, db: Session = Depends(get_db)): # <--- 4. CHANGED TYPE TO UUID
    docs = service.get_documents_by_company(db, str(company_id))
    return [
        {
            "id": d.id,
            "company_tax_info_id": d.company_tax_info_id,
            "file_name": d.file_name,
            "file_type": d.file_type,
        }
        for d in docs
    ]

@router.post("/company/{company_id}")
async def create_tax_document(
    company_id: str,
    category_detail_id: int = Form(...),   # ⬅ Make required (same as bank)
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        print("📌 DEBUG RECEIVED category_detail_id =", category_detail_id)
        # Read file content
        file_data = await file.read()

     

      

        # Save via service
        saved_doc = service.create_document_for_company(
            db=db,
            company_id=company_id,
            file_name=file.filename,
            file_data=file_data,
            file_type=file.content_type,
            category_detail_id=category_detail_id,
        )

        # Response
        return {
            "id": saved_doc.id,
            "company_id": company_id,
            "category_detail_id": category_detail_id,
            "file_name": saved_doc.file_name,
            "file_type": saved_doc.file_type,
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}",
        )
