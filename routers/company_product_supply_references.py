from fastapi import APIRouter, Depends, Form, UploadFile, File, HTTPException, status, Query
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db

from schemas import CompanyProductSupplyReferenceOut
from services.companyproductsupplyReference_service import CompanyProductSupplyReferenceService


router = APIRouter(
    prefix="/company_product_supply_references",
    tags=["company product supply references"],
    dependencies=[Depends(get_current_user)],
)

service = CompanyProductSupplyReferenceService()


@router.get("/", response_model=list[CompanyProductSupplyReferenceOut])
def list_references(
    company_product_id: int = Query(...),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    return service.get_references(db, company_product_id, skip, limit)


@router.post("/", response_model=CompanyProductSupplyReferenceOut, status_code=status.HTTP_201_CREATED)
async def upload_reference(
    company_product_id: int = Query(...),

    description: str | None = Form(None),
    customer_name: str | None = Form(None),
    reference_date: str | None = Form(None),

    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    file_data = await file.read()

    return service.create_reference(
        db=db,
        company_product_id=company_product_id,
        file_name=file.filename,
        file_type=file.content_type,
        file_size=len(file_data),
        file_data=file_data,
        description=description,
        customer_name=customer_name,
        reference_date=reference_date,
        created_by=str(current_user.id),
    )



@router.get("/{ref_id}", response_model=CompanyProductSupplyReferenceOut)
def get_reference(ref_id: int, db: Session = Depends(get_db)):
    ref = service.get_reference(db, ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found")
    return ref

from fastapi import Form

@router.patch("/{ref_id}", response_model=CompanyProductSupplyReferenceOut)
async def update_reference(
    ref_id: int,
    description: str | None = Form(None),
    customer_name: str | None = Form(None),
    reference_date: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user = Depends(get_current_user)
):
    return service.update_reference(
        db=db,
        ref_id=ref_id,
        description=description,
        customer_name=customer_name,
        reference_date=reference_date,
        modified_by=str(current_user.id)
    )

@router.delete("/{ref_id}")
def delete_reference(ref_id: int, db: Session = Depends(get_db)):
    return service.delete_reference(db, ref_id)
