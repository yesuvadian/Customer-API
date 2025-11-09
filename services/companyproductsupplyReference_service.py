from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyProductSupplyReference


class CompanyProductSupplyReferenceService:

    @classmethod
    def get_reference(cls, db: Session, ref_id: int):
        return db.query(CompanyProductSupplyReference).filter(
            CompanyProductSupplyReference.id == ref_id
        ).first()

    @classmethod
    def get_references(
        cls,
        db: Session,
        company_product_id: int,
        skip: int = 0,
        limit: int = 100,
    ):
        return (
            db.query(CompanyProductSupplyReference)
            .filter(
                CompanyProductSupplyReference.company_product_id
                == company_product_id
            )
            .offset(skip)
            .limit(limit)
            .all()
        )

    @classmethod
    def create_reference(
        cls,
        db: Session,
        company_product_id: int,
        file_name: str,
        file_type: str,
        file_size: int,
        file_data: bytes,
        description: str | None = None,
        customer_name: str | None = None,
        reference_date=None,
        created_by: str | None = None,
    ):
        reference = CompanyProductSupplyReference(
            company_product_id=company_product_id,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            file_data=file_data,
            description=description,
            customer_name=customer_name,
            reference_date=reference_date,
            created_by=created_by,
        )
        db.add(reference)
        db.commit()
        db.refresh(reference)
        return reference
    @classmethod
    def update_reference(
    self,
    db: Session,
    ref_id: int,
    description: str | None = None,
    customer_name: str | None = None,
    reference_date: str | None = None,
    modified_by: str | None = None,
):
        ref = db.query(CompanyProductSupplyReference).filter_by(id=ref_id).first()
        if not ref:
            raise HTTPException(status_code=404, detail="Reference not found")

        if description is not None:
            ref.description = description

        if customer_name is not None:
            ref.customer_name = customer_name

        if reference_date is not None:
            ref.reference_date = reference_date

        ref.modified_by = modified_by

        db.commit()
        db.refresh(ref)
        return ref


    @classmethod
    def delete_reference(cls, db: Session, ref_id: int):
        reference = cls.get_reference(db, ref_id)
        if not reference:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Supply reference not found",
            )
        db.delete(reference)
        db.commit()
        return {"message": "Reference deleted successfully"}
