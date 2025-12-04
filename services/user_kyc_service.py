from sqlalchemy.orm import Session
from sqlalchemy import exists, and_
from uuid import UUID

from models import (
    UserDocument,
    CompanyBankInfo, CompanyBankDocument,
    CompanyTaxInfo, CompanyTaxDocument,
    CompanyProduct,
    CompanyProductCertificate,
    CompanyProductSupplyReference,
)


class UserKYCService:

    @classmethod
    def get_all_pending_kyc(cls, db: Session, user_id: UUID):

        sections = {
            # 1️⃣ Product Documents
            "Product Documents": db.query(
                exists().where(
                    and_(
                        UserDocument.user_id == user_id,
                        UserDocument.pending_kyc == True
                    )
                )
            ).scalar(),

            # 2️⃣ Bank Documents (FIXED JOIN)
            "Bank Documents": db.query(
                exists().where(
                    and_(
                        CompanyBankInfo.company_id == user_id,
                        CompanyBankDocument.company_bank_info_id == CompanyBankInfo.id,
                        CompanyBankDocument.pending_kyc == True
                    )
                )
            ).scalar(),

            # 3️⃣ Tax Documents
            "Company Tax Documents": db.query(
                exists().where(
                    and_(
                        CompanyTaxInfo.company_id == user_id,
                        CompanyTaxDocument.company_tax_info_id == CompanyTaxInfo.id,
                        CompanyTaxDocument.pending_kyc == True
                    )
                )
            ).scalar(),

            # 4️⃣ Product Mappings
            "Product Mappings": db.query(
                exists().where(
                    and_(
                        CompanyProduct.company_id == user_id,
                        CompanyProduct.pending_kyc == True
                    )
                )
            ).scalar(),

            # 5️⃣ Product Certificates
            "Product Certificates": db.query(
                exists().where(
                    and_(
                        CompanyProductCertificate.company_product_id == CompanyProduct.id,
                        CompanyProduct.company_id == user_id,
                        CompanyProductCertificate.pending_kyc == True
                    )
                )
            ).scalar(),

            # 6️⃣ Supply References
            "Supply References Documents": db.query(
                exists().where(
                    and_(
                        CompanyProductSupplyReference.company_product_id == CompanyProduct.id,
                        CompanyProduct.company_id == user_id,
                        CompanyProductSupplyReference.pending_kyc == True
                    )
                )
            ).scalar(),
        }

        all_true = all(sections.values())

        return {
            "status": "KYC Completed" if all_true else "KYC Pending",
            "details": sections,
        }
