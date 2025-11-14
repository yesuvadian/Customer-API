from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from uuid import UUID
from datetime import datetime

from schemas import UserDocumentCreate, UserDocumentResponse, UserDocumentUpdate
from services.userdocumentservice import UserDocumentService

router = APIRouter(
    prefix="/user-documents",
    tags=["user-documents"],
    dependencies=[Depends(get_current_user)]
)

@router.post("/", response_model=UserDocumentResponse)
async def create_user_document(
    user_id: UUID = Form(...),
    division = relationship("Division", back_populates="documents", foreign_keys=[division_id]),
    division_id = Column(UUID(as_uuid=True), ForeignKey("public.divisions.id")),
    document_name: str = Form(...),
    om_number: Optional[str] = Form(None),
    expiry_date: Optional[datetime] = Form(None),
    file_data: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    service = UserDocumentService(db)
    contents = await file_data.read()

    document = service.create_document(
        user_id=user_id,
        division = relationship("Division", back_populates="documents", foreign_keys=[division_id]),
        division_id = Column(UUID(as_uuid=True), ForeignKey("public.divisions.id")),
        document_name=document_name,
        document_type=file_data.content_type,
        file_data=contents,
        file_size=len(contents),
        content_type=file_data.content_type,
        om_number=om_number,
        expiry_date=expiry_date
    )
    return document



# ----------------- READ -----------------
@router.get("/{document_id}", response_model=UserDocumentResponse)
def get_user_document(document_id: UUID, db: Session = Depends(get_db)):
    service = UserDocumentService(db)
    try:
        return service.get_document(document_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ----------------- LIST -----------------
@router.get("/", response_model=List[UserDocumentResponse])
def list_user_documents(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    service = UserDocumentService(db)
    return service.db.query(service.db_model).offset(skip).limit(limit).all()


@router.get("/user/{user_id}", response_model=List[UserDocumentResponse])
def list_documents_by_user(user_id: UUID, db: Session = Depends(get_db)):
    service = UserDocumentService(db)
    return service.list_documents_by_user(user_id)


@router.get("/expired", response_model=List[UserDocumentResponse])
def list_expired_documents(as_of: Optional[datetime] = None, db: Session = Depends(get_db)):
    service = UserDocumentService(db)
    return service.list_expired_documents(as_of=as_of)


# ----------------- UPDATE -----------------
@router.put("/{document_id}", response_model=UserDocumentResponse)
def update_user_document(document_id: UUID, document: UserDocumentUpdate, db: Session = Depends(get_db)):
    service = UserDocumentService(db)
    try:
        return service.update_document(
            document_id=document_id,
            om_number=document.om_number,
            expiry_date=document.expiry_date,
            is_active=document.is_active,
            document_url=document.document_url,
            modified_by=document.modified_by
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ----------------- DELETE -----------------
@router.delete("/{document_id}", response_model=dict)
def delete_user_document(document_id: UUID, db: Session = Depends(get_db)):
    service = UserDocumentService(db)
    try:
        service.delete_document(document_id)
        return {"message": "User document deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
