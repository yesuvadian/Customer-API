from sqlalchemy.orm import Session
from sqlalchemy import exists
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
        """
        Return YES/NO flags for each pending KYC section.
        If ALL are True → KYC Completed
        If ANY is False → KYC Pending
        """

        sections = {
            "Product Documents": db.query(
                exists().where(
                    UserDocument.user_id == user_id,
                    UserDocument.pending_kyc.is_(True)
                )
            ).scalar(),

            "Bank Documents": db.query(
                exists().where(
                    CompanyBankInfo.company_id == user_id,
                    CompanyBankDocument.company_bank_info_id == CompanyBankInfo.id,
                    CompanyBankDocument.pending_kyc.is_(True)
                )
            ).scalar(),

            "Company Tax Documents": db.query(
                exists().where(
                    CompanyTaxInfo.company_id == user_id,
                    CompanyTaxDocument.company_tax_info_id == CompanyTaxInfo.id,
                    CompanyTaxDocument.pending_kyc.is_(True)
                )
            ).scalar(),

            "Product Mappings": db.query(
                exists().where(
                    CompanyProduct.company_id == user_id,
                    CompanyProduct.pending_kyc.is_(True)
                )
            ).scalar(),

            "Product Certificates": db.query(
                exists().where(
                    CompanyProductCertificate.company_product_id == CompanyProduct.id,
                    CompanyProduct.company_id == user_id,
                    CompanyProductCertificate.pending_kyc.is_(True)
                )
            ).scalar(),

            "Supply References Documents": db.query(
                exists().where(
                    CompanyProductSupplyReference.company_product_id == CompanyProduct.id,
                    CompanyProduct.company_id == user_id,
                    CompanyProductSupplyReference.pending_kyc.is_(True)
                )
            ).scalar(),
        }

        # 🔍 Check if ALL are True
        all_true = all(sections.values())

        return {
            "status": "KYC Completed" if all_true else "KYC Pending",
            "details": sections,   # <-- return section-wise details also
        }

