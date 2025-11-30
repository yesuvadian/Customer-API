from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from auth_utils import get_current_user
from database import get_db
from schemas import CompanyBankDocumentSchema
from services.companybankdocument_service import CompanyBankDocumentService


router = APIRouter(
    prefix="/bank_documents",
    tags=["vendor-bank-documents"],
    dependencies=[Depends(get_current_user)]
)

@router.get("/{bank_info_id}", response_model=list[CompanyBankDocumentSchema])
def list_bank_documents(bank_info_id: int, db: Session = Depends(get_db)):
    return CompanyBankDocumentService.get_documents_by_bank_info(db, bank_info_id)

@router.post("/", response_model=CompanyBankDocumentSchema)
async def upload_bank_document(
    bank_info_id: int = Form(...),  # Now 'Form' is defined
    file: UploadFile = File(...),
    document_type: str | None = Form(None),
    db: Session = Depends(get_db)
):
    file_data = await file.read()

    return CompanyBankDocumentService.create_document(
        db,
        bank_info_id=bank_info_id,
        file_name=file.filename,
        file_data=file_data,
        file_type=file.content_type,
        document_type=document_type
    )

@router.put("/{document_id}", response_model=CompanyBankDocumentSchema)
async def update_bank_document(
    document_id: int,
    document_type: str | None = None,
    db: Session = Depends(get_db)
):
    return CompanyBankDocumentService.update_document(
        db,
        document_id,
        {"document_type": document_type}
    )

@router.delete("/{document_id}", response_model=CompanyBankDocumentSchema)
def delete_bank_document(document_id: int, db: Session = Depends(get_db)):
    return CompanyBankDocumentService.delete_document(db, document_id)
