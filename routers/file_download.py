from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from database import get_db
from uuid import UUID

from services.userdocumentservice import UserDocumentService
from services.companybankdocument_service import CompanyBankDocumentService
from services.company_tax_document_service import CompanyTaxDocumentService

router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[]   # No authentication required
)

@router.get("/{document_id}")
def download_file(document_id: str, db: Session = Depends(get_db)):

    # 1️⃣ Try User Document (UUID)
    try:
        uuid_id = UUID(document_id)
        doc = UserDocumentService(db).get_document(uuid_id)
        if doc:
            return _stream_doc(doc)
    except ValueError:
        pass

    # 2️⃣ Try Bank Documents (INT)
    if document_id.isdigit():
        doc = CompanyBankDocumentService.get_document(db, int(document_id))
        if doc:
            return _stream_doc(doc)

        # 3️⃣ Try Tax Documents (INT)
        doc = CompanyTaxDocumentService.get_document(db, int(document_id))
        if doc:
            return _stream_doc(doc)

    raise HTTPException(404, "Document not found")


def _stream_doc(doc):
    # Detect content type safely
    content_type = (
        getattr(doc, "content_type", None)
        or getattr(doc, "file_type", None)
        or "application/octet-stream"
    )

    file_name = (
        getattr(doc, "document_name", None)
        or getattr(doc, "file_name", None)
        or "file"
    )

    # If stored in DB (byte data)
    if getattr(doc, "file_data", None):
        return StreamingResponse(
            iter([doc.file_data]),
            media_type=content_type,
            headers={
                "Content-Disposition": f'inline; filename="{file_name}"'
            }
        )

    # If stored as file path
    if getattr(doc, "document_url", None):
        return FileResponse(
            doc.document_url,
            media_type=content_type,
            filename=file_name
        )

    raise HTTPException(status_code=404, detail="File missing")

