from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
#from services.company_product_service import CompanyProductService
from schemas import CompanyProductSchema
from services.companyproduct_service import CompanyProductService  # <-- Pydantic schema

router = APIRouter(prefix="/company-products", tags=["company-products"])

@router.get("/{company_id}", response_model=list[CompanyProductSchema])
def list_company_products(company_id: str, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return CompanyProductService.get_company_products(db, company_id, skip, limit)

@router.get("/detail/{company_product_id}", response_model=CompanyProductSchema)
def get_company_product(company_product_id: int, db: Session = Depends(get_db)):
    cp = CompanyProductService.get_company_product(db, company_product_id)
    if not cp:
        raise HTTPException(status_code=404, detail="Company product not found")
    return cp

@router.post("/", response_model=CompanyProductSchema)
def assign_product(company_id: str, product_id: int, price: float, stock: int | None = 0, db: Session = Depends(get_db)):
    return CompanyProductService.assign_product(db, company_id, product_id, price, stock)

@router.put("/{company_product_id}", response_model=CompanyProductSchema)
def update_company_product(company_product_id: int, updates: dict, db: Session = Depends(get_db)):
    return CompanyProductService.update_company_product(db, company_product_id, updates)

@router.delete("/{company_product_id}", response_model=CompanyProductSchema)
def delete_company_product(company_product_id: int, db: Session = Depends(get_db)):
    return CompanyProductService.delete_company_product(db, company_product_id)
