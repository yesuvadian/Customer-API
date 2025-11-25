import os
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
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
def get_company_documents(company_id: UUID, db: Session = Depends(get_db)): # <--- 2. CHANGED TYPE TO UUID
    docs = service.get_documents_by_company(db, str(company_id)) # <--- Pass as str() if service expects str
    if not docs:
        return []

    return [
        {
            "id": d.id,
            "file_name": d.file_name,
            "file_type": d.file_type,
        }
        for d in docs
    ]


# =====================================================
# 📤 Upload a new document for a company (with file size validation)
# =====================================================
@router.post("/company/{company_id}", status_code=status.HTTP_201_CREATED)
def upload_company_document(
    company_id: UUID, # <--- 3. CHANGED TYPE TO UUID
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Upload a document and automatically associate it with the company's tax info.
    """
    try:
        file_data = file.file.read()

        # 🧩 Validate file size
        if len(file_data) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Max size allowed: {MAX_FILE_SIZE_KB} KB",
            )

        doc = service.create_document_for_company(
            db=db,
            company_id=company_id,# <--- Pass as str() if service expects str
            file_name=file.filename,
            file_data=file_data,
            file_type=file.content_type,
        )
        return {"id": doc.id, "file_name": doc.file_name, "file_type": doc.file_type}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload document: {e}"
        )


# =====================================================
# ✏️ Update (replace) an existing document by ID (with size check) (No change needed)
# =====================================================
@router.put("/{doc_id}")
def update_company_document(
    doc_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """
    Replace an existing document file (update name/type/content).
    """
    try:
        file_data = file.file.read()

        # 🧩 Validate file size
        if len(file_data) > MAX_FILE_SIZE_BYTES:
            # ... (rest of the code unchanged)
            pass

        # ... (rest of the code unchanged)
    except HTTPException as e:
        raise e
    except Exception as e:
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
def upload_document(company_id: UUID, file: UploadFile = File(...), db: Session = Depends(get_db)): # <--- 5. CHANGED TYPE TO UUID
    file_data = file.file.read()
    if len(file_data) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail=f"File exceeds {MAX_FILE_SIZE_KB} KB limit")

    doc = service.create_document_for_company(
        db,
        company_id=str(company_id),
        file_name=file.filename,
        file_data=file_data,
        file_type=file.content_type,
    )
    return {"id": doc.id, "file_name": doc.file_name, "file_type": doc.file_type}