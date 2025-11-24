from fastapi import HTTPException, status
from sqlalchemy import UUID
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from typing import List
from models import CompanyProduct, Product


class CompanyProductService:

    @classmethod
    def get_company_product(cls, db: Session, company_product_id: int):
        return db.query(CompanyProduct).filter(CompanyProduct.id == company_product_id).first()

    
    @classmethod
    def get_company_product_list(cls, db: Session, company_id: str):
        records = (
            db.query(CompanyProduct)
            .filter(CompanyProduct.company_id == company_id)
            .all()
        )

        result = []
        for cp in records:
            product = cp.product  # relationship

            result.append({
                "company_product_id": cp.id,
                "product_id": product.id,
                "name": product.name,
                "sku": product.sku,
                "category_id": product.category_id,
                "subcategory_id": product.subcategory_id,
                "description": product.description,
            })

        return result

    @classmethod
    def get_company_products(cls, db: Session, company_id: str, skip: int = 0, limit: int = 100):
        products = (
            db.query(CompanyProduct)
            .filter(CompanyProduct.company_id == company_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Convert SQLAlchemy models to plain dicts
        result = []
        for p in products:
            prod_name = p.product.name if p.product else "Unknown Product"
            prod_sku = p.product.sku if p.product else ""
            result.append({
                "id": p.id,
                "company_id": str(p.company_id),  # UUID → string
                "product_id": p.product_id,
                "price": p.price,
                "stock": p.stock_quantity or 0,
               "product": {
                    "id": p.product_id,
                    "name": prod_name,
                    "sku": prod_sku
                }
            })

        return result



    @classmethod
    def bulk_assign(cls, db: Session, company_id: str, product_ids: List[int]):
        try:
            # 1️⃣ Delete existing mappings
            db.query(CompanyProduct).filter(
                CompanyProduct.company_id == company_id
            ).delete()

            # 2️⃣ Add new mappings
            assigned = []
            for pid in product_ids:
                cp = CompanyProduct(
                    company_id=company_id,
                    product_id=pid,
                    price=0.0
                )
                db.add(cp)
                assigned.append(cp)

            # ✅ Commit once at the end
            db.commit()
            return assigned

        except Exception as e:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Bulk assignment failed: {str(e)}"
            )


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

