from typing import List, Optional
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, Query
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from uuid import UUID
from datetime import datetime,timezone

from schemas import UserDocumentCreate, UserDocumentResponse, UserDocumentUpdate
from services.userdocumentservice import UserDocumentService
from utils.common_service import UTCDateTimeMixin

router = APIRouter(
    prefix="/user_documents",
    tags=["user-documents"],
    dependencies=[Depends(get_current_user)]
)

@router.post("/", response_model=UserDocumentResponse)
async def create_user_document(
    user_id: UUID = Form(...),
    division_id: UUID = Form(...),
    document_name: str = Form(...),
    document_type: str = Form(...),
    category_detail_id: Optional[int] = Form(None),
    company_product_id: Optional[int] = Form(None), 
    om_number: Optional[str] = Form(None),
    expiry_date_str: Optional[str] = Form(None, alias="expiry_date"), 
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    service = UserDocumentService(db)

    # Read file
    contents = await file.read()

    # Convert expiry_date string to datetime object
    expiry_date_dt = None
    if expiry_date_str:
        try:
            date_part = expiry_date_str.split('T')[0]
            naive_dt = datetime.strptime(date_part, '%Y-%m-%d')
            expiry_date_dt = UTCDateTimeMixin._make_aware(naive_dt)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Invalid expiry_date format. Must be in YYYY-MM-DD format."
            )

    # -----------------------------
    # 🔥 WRAP CREATE IN TRY/EXCEPT
    # -----------------------------
    try:
        document = service.create_document(
            user_id=user_id,
            division_id=division_id,
            document_name=document_name,
            document_type=document_type,
            document_url=None,
            file_data=contents,
            file_size=len(contents),
            content_type=file.content_type,
            category_detail_id=category_detail_id,
            company_product_id=company_product_id, 
            om_number=om_number,
            expiry_date=expiry_date_dt
        )
        return document

    except ValueError as e:
        # Convert ValueError to HTTP 400
        raise HTTPException(status_code=400, detail=str(e))


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
    # Assuming service.db_model is available or you replace it with the correct model class
    return service.db.query(service.db_model).offset(skip).limit(limit).all()


@router.get("/user/{user_id}", response_model=List[UserDocumentResponse])
def list_documents_by_user(
    user_id: UUID,
    division_id: UUID = Query(...),
    company_product_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    service = UserDocumentService(db)
    return service.list_documents_by_filters(user_id, division_id, company_product_id)



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
    
@router.delete("/bulk/delete", response_model=dict)
def delete_documents_by_filters(
    user_id: UUID = Query(...),
    division_id: UUID = Query(...),
    category_detail_id: int = Query(...),
    company_product_id: Optional[int] = Query(None),  # ✅ ADD THIS
    db: Session = Depends(get_db),
):
    service = UserDocumentService(db)

    deleted_count = service.delete_by_filters(
        user_id=user_id,
        division_id=division_id,
        category_detail_id=category_detail_id,
        company_product_id=company_product_id  # ✅ PASS THIS
    )

    return {
        "message": f"Deleted {deleted_count} document(s) successfully.",
        "deleted_count": deleted_count
    }