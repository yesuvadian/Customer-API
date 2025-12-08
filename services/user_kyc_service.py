from sqlalchemy.orm import Session
from sqlalchemy import exists, and_, func
from uuid import UUID

from models import (
    CategoryDetails,
    CategoryMaster,
    UserDocument,
    CompanyBankInfo, CompanyBankDocument,
    CompanyTaxInfo, CompanyTaxDocument,
    CompanyProduct,
)


class UserKYCService:

    @classmethod
    def get_all_pending_kyc(cls, db: Session, user_id: UUID):

        sections = {
            # 1️⃣ Product Documents
            "Product Documents":cls.update_kyc_status_if_any_product_complete(db, user_id,"Company Documents") ,

            # 2️⃣ Bank Documents
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
        }

        all_true = all(sections.values())

        return {
            "status": "KYC Completed" if all_true else "KYC Pending",
            "details": sections,
        }
    @classmethod
    def update_kyc_status_if_any_product_complete(cls,db: Session, user_id: UUID, master_name: str):
        """
        Updates pending_kyc = TRUE for all UserDocument rows of a user
        if any of the user's products meet the required category detail count.
        """

        # 1️⃣ Get all distinct product_ids for this user
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
        product_ids = [p[0] for p in product_ids]  # unpack tuples

        # 2️⃣ Check each product for strict count match
        for product_id in product_ids:

            # Count required category details
            required_count = (
                db.query(func.count(CategoryDetails.id))
                .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                .filter(CategoryMaster.name == master_name)
                .scalar()
            )

            # Count uploaded documents for this user + product
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

            # 3️⃣ If any product meets the count criteria → update all user documents
            if uploaded_count == required_count:
                (
                    db.query(UserDocument)
                    .filter(UserDocument.user_id == user_id)
                    .update({UserDocument.pending_kyc: True}, synchronize_session=False)
                )
                db.commit()
                return True  # KYC updated as complete

        return False  # No product fully completed yet

    @classmethod
    def get_erp_ready_documents_grouped_by_company_product(db: Session, master_name: str):
        """
        Returns a dictionary where the key is (company_id, product_id)
        and value is the list of UserDocument rows that:
            - Have all required category details uploaded
            - pending_kyc = TRUE
            - erp_sync_status = 'pending'
        Only groups matching required_count == uploaded_count are included.
        """

        # 1️⃣ Get all distinct (user_id, company_id, product_id) combinations
        # Note: assuming company_id is in UserDocument.user.division.company or some field
        # Here I’ll assume you have company_id in UserDocument via a relationship
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

        # 2️⃣ For each pair, check strict KYC completion
        for user_id, product_id in pairs:

            # Count required category details
            required_count = (
                db.query(func.count(CategoryDetails.id))
                .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                .filter(CategoryMaster.name == master_name)
                .scalar()
            )

            # Count uploaded documents for this user + product
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

            # Only include groups where counts match
            if required_count == uploaded_count:

                # Fetch all UserDocument rows for this group
                user_docs = (
                    db.query(UserDocument)
                    .join(CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id)
                    .join(CategoryMaster, CategoryDetails.category_master_id == CategoryMaster.id)
                    .filter(UserDocument.user_id == user_id)
                    .filter(UserDocument.company_product_id == product_id)
                    .filter(CategoryMaster.name == master_name)
                    .filter(UserDocument.pending_kyc == True)           # Completed
                    .filter(UserDocument.erp_sync_status == "pending")  # Not yet synced
                    .filter(UserDocument.is_active == True)
                    .all()
                )

                if user_docs:
                    # Here key can be user_id + product_id or company_id + product_id
                    # If company_id is needed, fetch via user -> division -> company
                    result[(user_id, product_id)] = user_docs

        return result

