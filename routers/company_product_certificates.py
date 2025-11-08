from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db


from schemas import CompanyProductCertificateOut
from services.companyproductcertificate_service import CompanyProductCertificateService


router = APIRouter(
    prefix="/company-product-certificates",
    tags=["company product certificates"],
    dependencies=[Depends(get_current_user)],
)

service = CompanyProductCertificateService()


@router.get("/", response_model=list[CompanyProductCertificateOut])
def list_certificates(
    company_product_id: int = Query(...),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    return service.get_certificates(db, company_product_id, skip, limit)


@router.post("/", response_model=CompanyProductCertificateOut, status_code=status.HTTP_201_CREATED)
async def upload_certificate(
    company_product_id: int = Query(...),
    issued_date: str | None = None,
    expiry_date: str | None = None,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user)
):
    file_data = await file.read()

    return service.create_certificate(
        db=db,
        company_product_id=company_product_id,
        file_name=file.filename,
        file_type=file.content_type,
        file_size=len(file_data),
        file_data=file_data,
        created_by=str(current_user.id),
        issued_date=issued_date,
        expiry_date=expiry_date,
    )


@router.get("/{cert_id}", response_model=CompanyProductCertificateOut)
def get_certificate(cert_id: int, db: Session = Depends(get_db)):
    cert = service.get_certificate(db, cert_id)
    if not cert:
        raise HTTPException(status_code=404, detail="Certificate not found")
    return cert


@router.delete("/{cert_id}")
def delete_certificate(cert_id: int, db: Session = Depends(get_db)):
    return service.delete_certificate(db, cert_id)

@router.get("/check/{company_product_id}")
def check_certificates(
    company_product_id: int,
    db: Session = Depends(get_db)
):
    return service.check_documents(db, company_product_id)
