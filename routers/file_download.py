from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from database import get_db
from uuid import UUID

from services.userdocumentservice import UserDocumentService
# from services.bankdocumentservice import BankDocumentService
# from services.taxdocumentservice import TaxDocumentService

router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[]   # No authentication required
)

@router.get("/{document_id}")
def download_file(document_id: UUID, db: Session = Depends(get_db)):
    
    # Try User Document
    try:
        doc = UserDocumentService(db).get_document(document_id)
        return _stream_doc(doc)
    except:
        pass

    # # Try Bank Document
    # try:
    #     doc = BankDocumentService(db).get_document(document_id)
    #     return _stream_doc(doc)
    # except:
    #     pass

    # # Try Tax Document
    # try:
    #     doc = TaxDocumentService(db).get_document(document_id)
    #     return _stream_doc(doc)
    # except:
    #     pass

    raise HTTPException(404, "Document not found")


def _stream_doc(doc):
    # If stored in DB
    if getattr(doc, "file_data", None):
        return StreamingResponse(
            iter([doc.file_data]),
            media_type=doc.content_type or "application/octet-stream",
            headers={
                "Content-Disposition": f"inline; filename={doc.document_name}"
            }
        )

    # If stored as file path
    if getattr(doc, "document_url", None):
        return FileResponse(
            doc.document_url,
            media_type=doc.content_type or "application/octet-stream",
            filename=doc.document_name
        )

    raise HTTPException(404, "File missing")
