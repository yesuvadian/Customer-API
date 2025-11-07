from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from models import CompanyProductCertificate


class CompanyProductCertificateService:

    @classmethod
    def get_certificate(cls, db: Session, cert_id: int):
        return db.query(CompanyProductCertificate).filter(
            CompanyProductCertificate.id == cert_id
        ).first()

    @classmethod
    def get_certificates(
        cls,
        db: Session,
        company_product_id: int,
        skip: int = 0,
        limit: int = 100,
    ):
        return (
            db.query(CompanyProductCertificate)
            .filter(CompanyProductCertificate.company_product_id == company_product_id)
            .offset(skip)
            .limit(limit)
            .all()
        )

    @classmethod
    def create_certificate(
        cls,
        db: Session,
        company_product_id: int,
        file_name: str,
        file_type: str,
        file_size: int,
        file_data: bytes,
        created_by: str | None = None,
        issued_date=None,
        expiry_date=None,
    ):
        certificate = CompanyProductCertificate(
            company_product_id=company_product_id,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            file_data=file_data,
            issued_date=issued_date,
            expiry_date=expiry_date,
            created_by=created_by,
        )
        db.add(certificate)
        db.commit()
        db.refresh(certificate)
        return certificate

    @classmethod
    def update_certificate(cls, db: Session, cert_id: int, updates: dict):
        certificate = cls.get_certificate(db, cert_id)
        if not certificate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certificate not found",
            )
        for key, value in updates.items():
            setattr(certificate, key, value)

        db.commit()
        db.refresh(certificate)
        return certificate

    @classmethod
    def delete_certificate(cls, db: Session, cert_id: int):
        certificate = cls.get_certificate(db, cert_id)
        if not certificate:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Certificate not found",
            )
        db.delete(certificate)
        db.commit()
        return {"message": "Certificate deleted successfully"}
