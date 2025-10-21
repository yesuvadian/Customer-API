from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyProduct


class CompanyProductService:

    @classmethod
    def get_company_product(cls, db: Session, company_product_id: int):
        return db.query(CompanyProduct).filter(CompanyProduct.id == company_product_id).first()

    @classmethod
    def get_company_products(cls, db: Session, company_id: str, skip: int = 0, limit: int = 100):
        return (
            db.query(CompanyProduct)
            .filter(CompanyProduct.company_id == company_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    @classmethod
    def assign_product(cls, db: Session, company_id: str, product_id: int, price: float, stock: int | None = 0):
        existing = db.query(CompanyProduct).filter(
            CompanyProduct.company_id == company_id,
            CompanyProduct.product_id == product_id
        ).first()

        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product already assigned to this company")

        cp = CompanyProduct(company_id=company_id, product_id=product_id, price=price, stock=stock)
        db.add(cp)
        db.commit()
        db.refresh(cp)
        return cp

    @classmethod
    def update_company_product(cls, db: Session, company_product_id: int, updates: dict):
        cp = cls.get_company_product(db, company_product_id)
        if not cp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company product not found")
        for key, value in updates.items():
            setattr(cp, key, value)
        db.commit()
        db.refresh(cp)
        return cp

    @classmethod
    def delete_company_product(cls, db: Session, company_product_id: int):
        cp = cls.get_company_product(db, company_product_id)
        if cp:
            db.delete(cp)
            db.commit()
        return cp
