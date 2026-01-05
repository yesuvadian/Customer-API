from sqlalchemy.orm import Session
from sqlalchemy import exists, and_, func
from uuid import UUID

from models import (
    UserAddress,
    CategoryDetails,
    CategoryMaster,
    UserDocument,
    CompanyBankInfo, CompanyBankDocument,
    CompanyTaxInfo, CompanyTaxDocument,
    CompanyProduct,
)


class UserKYCService:

    @classmethod
    def has_office_address(cls, db: Session, user_id: UUID) -> bool:
        return db.query(
            exists().where(
                and_(
                    UserAddress.user_id == user_id,
                    UserAddress.address_type == "office"
                )
            )
        ).scalar()

    @classmethod
    def get_all_pending_kyc(cls, db: Session, user_id: UUID):

        sections = {
            # 0️⃣ Office Address (ADDED)
            "Office Address": cls.has_office_address(db, user_id),

            # 1️⃣ Product Documents (UNCHANGED)
            "Product Documents": cls.update_kyc_status_if_any_product_complete(
                db, user_id, "Company Documents"
            ),

            # 2️⃣ Bank Documents (UNCHANGED)
            "Bank Documents": db.query(
                exists().where(
                    and_(
                        CompanyBankInfo.company_id == user_id,
                        CompanyBankDocument.company_bank_info_id == CompanyBankInfo.id,
                        CompanyBankDocument.pending_kyc == True
                    )
                )
            ).scalar(),

            # 3️⃣ Tax Documents (UNCHANGED)
            "Company Tax Documents": db.query(
                exists().where(
                    and_(
                        CompanyTaxInfo.company_id == user_id,
                        CompanyTaxDocument.company_tax_info_id == CompanyTaxInfo.id,
                        CompanyTaxDocument.pending_kyc == True
                    )
                )
            ).scalar(),

            # 4️⃣ Product Mappings (UNCHANGED)
            "Product Mappings": db.query(
                exists().where(
                    and_(
                        CompanyProduct.company_id == user_id,
                        CompanyProduct.pending_kyc == True
                    )
                )
            ).scalar(),
        }

        all_true = all(sections.values())

        return {
            "status": "KYC Completed" if all_true else "KYC Pending",
            "details": sections,
        }

    @classmethod
    def update_kyc_status_if_any_product_complete(
        cls, db: Session, user_id: UUID, master_name: str
    ):
        """
        Updates pending_kyc = TRUE for all UserDocument rows of a user
        if any of the user's products meet the required category detail count.
        """

        product_ids = (
            db.query(UserDocument.company_product_id)
            .join(CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id)
            .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
            .filter(UserDocument.user_id == user_id)
            .filter(CategoryMaster.name == master_name)
            .filter(UserDocument.is_active == True)
            .distinct()
            .all()
        )
        product_ids = [p[0] for p in product_ids]

        for product_id in product_ids:

            required_count = (
                db.query(func.count(CategoryDetails.id))
                .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                .filter(CategoryMaster.name == master_name)
                .scalar()
            )

            uploaded_count = (
                db.query(func.count(UserDocument.id))
                .join(CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id)
                .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                .filter(UserDocument.user_id == user_id)
                .filter(UserDocument.company_product_id == product_id)
                .filter(CategoryMaster.name == master_name)
                .filter(UserDocument.is_active == True)
                .scalar()
            )

            if uploaded_count == required_count:
                (
                    db.query(UserDocument)
                    .filter(UserDocument.user_id == user_id)
                    .update({UserDocument.pending_kyc: True}, synchronize_session=False)
                )
                db.commit()
                return True

        return False

    @classmethod
    def get_erp_ready_documents_grouped_by_company_product(
        db: Session, master_name: str
    ):
        """
        Returns ERP-ready grouped documents
        """

        pairs = (
            db.query(
                UserDocument.user_id,
                UserDocument.company_product_id
            )
            .join(CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id)
            .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
            .filter(CategoryMaster.name == master_name)
            .filter(UserDocument.is_active == True)
            .distinct()
            .all()
        )

        result = {}

        for user_id, product_id in pairs:

            required_count = (
                db.query(func.count(CategoryDetails.id))
                .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                .filter(CategoryMaster.name == master_name)
                .scalar()
            )

            uploaded_count = (
                db.query(func.count(UserDocument.id))
                .join(CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id)
                .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                .filter(UserDocument.user_id == user_id)
                .filter(UserDocument.company_product_id == product_id)
                .filter(CategoryMaster.name == master_name)
                .filter(UserDocument.is_active == True)
                .scalar()
            )

            if required_count == uploaded_count:
                user_docs = (
                    db.query(UserDocument)
                    .join(CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id)
                    .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                    .filter(UserDocument.user_id == user_id)
                    .filter(UserDocument.company_product_id == product_id)
                    .filter(CategoryMaster.name == master_name)
                    .filter(UserDocument.pending_kyc == True)
                    .filter(UserDocument.erp_sync_status == "pending")
                    .filter(UserDocument.is_active == True)
                    .all()
                )

                if user_docs:
                    result[(user_id, product_id)] = user_docs

        return result
