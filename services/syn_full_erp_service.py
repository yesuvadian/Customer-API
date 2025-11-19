from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from models import (
    User, UserAddress, UserRole, CompanyBankInfo,
    CompanyTaxInfo, CompanyBankDocument, CompanyTaxDocument
)

class ERPService:

    @classmethod
    def build_party_json(cls, db: Session):
        """
        Fetch complete ERP party JSON for ALL users
        whose ERP sync status is 'pending' or NULL.
        """

        # -------- Step 1: Fetch all pending/unsynced users --------
        users = (
            db.query(User)
                .filter(
                    (User.erp_sync_status == None) | (User.erp_sync_status == "pending")
                )
                .all()
        )

        if not users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No pending users found"
            )

        final_result = []   # to store JSON for each user

        # -------- Step 2: Loop through users & fetch related tables --------
        for user in users:
            primary_address = (
                db.query(UserAddress)
                .filter(UserAddress.user_id == user.id, UserAddress.is_primary == True)
                .first()
            )

            tax_info = (
                db.query(CompanyTaxInfo)
                .filter(CompanyTaxInfo.company_id == user.id)
                .first()
            )

            bank_info = (
                db.query(CompanyBankInfo)
                .filter(CompanyBankInfo.company_id == user.id)
                .first()
            )

            user_role = (
                db.query(UserRole)
                .filter(UserRole.user_id == user.id)
                .first()
            )

            tax_document = (
                db.query(CompanyTaxDocument)
                .join(CompanyTaxInfo, CompanyTaxInfo.id == CompanyTaxDocument.company_tax_info_id)
                .filter(CompanyTaxInfo.company_id == user.id)
                .first()
            )

            bank_document = (
                db.query(CompanyBankDocument)
                .join(CompanyBankInfo, CompanyBankInfo.id == CompanyBankDocument.company_bank_info_id)
                .filter(CompanyBankInfo.company_id == user.id)
                .first()
            )

            # -------- Step 3: Partymast JSON --------
            partymast = {
                "partymastid": None,
                "docdate": None,
                "title": "Mr.",
                "partyid": str(user.id),
                "partyname": f"{user.firstname or ''} {user.lastname or ''}".strip(),
                "vtype": "SUPPLIER [GOODS]",
                "agroupname": None,
                "typename": None,
                "gstpartytype": None,
                "grade": None,
                "mobile": user.phone_number,
                "email": user.email,
                "phoneno": user.phone_number,
                "joindate": user_role.assigned_at if user_role else None,
                "trialfor": None,
                "plrelation": None,
                "dedtype": None,
                "evaldate": None,
                "natureofbusiness": None,
                "status": None,
                "activeyn": user.isactive,
                "tdspartyyn": None,
                "typeofded": None,
                "add1": primary_address.address_line1 if primary_address else None,
                "add2": primary_address.address_line2 if primary_address else None,
                "add3": None,
                "city": primary_address.city if primary_address else None,
                "bcs_state": primary_address.state.name if primary_address and primary_address.state else None,
                "country": primary_address.country.name if primary_address and primary_address.country else None,
                "panno": tax_info.pan if tax_info else None,
                "gstnumsuf": None,
                "gstno": tax_info.gstin if tax_info else None,
                "gstdate": None,
                "acno": bank_info.account_number if bank_info else None,
                "bname": bank_info.bank_name if bank_info else None,
                "bankbranch": bank_info.branch_name if bank_info else None,
                "branchcode": None,
                "baccountname": bank_info.account_holder_name if bank_info else None,
                "ifsccode": bank_info.ifsc if bank_info else None
            }

            # -------- Step 4: Documents JSON --------
            partymastdoc = {
                "partymastid": None,
                "empdocuid": bank_document.id if bank_document else None,
                "doctype": bank_document.document_type.value if bank_document else None,
                "attachfilename": bank_document.file_name if bank_document else None
            }

            # -------- Step 5: TDS JSON --------
            tdssection = {
                "partymastid": None,
                "tdssectionid": tax_document.id if tax_document else None,
                "taxtype": tax_document.file_type if tax_document else None,
                "tdsper": None
            }

            # -------- Append to Final Result --------
            final_result.append({
                "partymast": partymast,
                "partymastdoc": partymastdoc,
                "tdssection": tdssection
            })

        return final_result
