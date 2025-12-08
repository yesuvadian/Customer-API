from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from fastapi import Response

from auth_utils import get_current_user
from database import get_db
from schemas import CompanyBankDocumentSchema, CompanyBankInfoUpdateSchema
from services.companybankdocument_service import CompanyBankDocumentService


router = APIRouter(
    prefix="/bank_documents",
    tags=["vendor-bank-documents"],
    dependencies=[Depends(get_current_user)]
)

@router.get("/{bank_info_id}", response_model=list[CompanyBankDocumentSchema])
def list_bank_documents(bank_info_id: int, db: Session = Depends(get_db)):
    return CompanyBankDocumentService.get_documents_by_bank_info(db, bank_info_id)

# In bank_document.py

@router.post("/", response_model=CompanyBankDocumentSchema)
async def upload_bank_document(
    bank_info_id: int = Form(...),
    file: UploadFile = File(...),
    category_detail_id: int = Form(...),
    db: Session = Depends(get_db)
):
    file_data = await file.read()

    return CompanyBankDocumentService.create_document(
        db,
        bank_info_id=bank_info_id,
        file_name=file.filename,
        file_data=file_data,
        file_type=file.content_type,
        # CHANGE: Passed the new argument with the correct name
        category_detail_id=category_detail_id
    )

@router.put("/{document_id}", response_model=CompanyBankDocumentSchema)
async def update_bank_document(
    document_id: int,
    # CHANGE: Receive updates as a Pydantic schema object in the request body
    updates: CompanyBankInfoUpdateSchema, 
    db: Session = Depends(get_db)
):
    return CompanyBankDocumentService.update_document(
        db,
        document_id,
        # CHANGE: Convert the schema to a dictionary, excluding fields the user didn't set
        updates.dict(exclude_unset=True)
    )

@router.delete("/{document_id}", status_code=204)
def delete_bank_document(document_id: int, db: Session = Depends(get_db)):
    CompanyBankDocumentService.delete_document(db, document_id)
    return Response(status_code=204)
