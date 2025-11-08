from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db

from schemas import CompanyProductSupplyReferenceOut
from services.companyproductsupplyReference_service import CompanyProductSupplyReferenceService


router = APIRouter(
    prefix="/company-product-supply-references",
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
    description: str | None = None,
    customer_name: str | None = None,
    reference_date: str | None = None,
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


@router.delete("/{ref_id}")
def delete_reference(ref_id: int, db: Session = Depends(get_db)):
    return service.delete_reference(db, ref_id)
