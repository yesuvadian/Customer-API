from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from services.company_tax_document_service import CompanyTaxDocumentService

router = APIRouter(prefix="/company_tax_documents", tags=["company_tax_documents"],dependencies=[Depends(get_current_user)])
service = CompanyTaxDocumentService()

@router.get("/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    doc = service.get_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {
        "id": doc.id,
        "company_tax_info_id": doc.company_tax_info_id,
        "file_name": doc.file_name,
        "file_type": doc.file_type
    }

@router.post("/")
def upload_document(company_tax_info_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_data = file.file.read()
    doc = service.create_document(db, company_tax_info_id, file.filename, file_data, file.content_type)
    return {"id": doc.id, "file_name": doc.file_name}

@router.delete("/{doc_id}")
def delete_document(doc_id: int, db: Session = Depends(get_db)):
    doc = service.delete_document(db, doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"detail": "Document deleted"}
