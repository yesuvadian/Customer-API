from sqlalchemy.orm import Session
from fastapi import HTTPException, status
from models import (
    Product, User, UserAddress, UserRole, CompanyBankInfo,
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
                "partymastid": user.erp_external_id if user.erp_external_id else "",
                "docdate": "",
                "title": "Mr.",
                "partyid": str(user.id),
                "partyname": f"{user.firstname or ''} {user.lastname or ''}".strip(),
                "vtype": "SUPPLIER [GOODS]",
                "agroupname": "",
                "typename": "",
                "gstpartytype": "",
                "grade": "",
                "mobile": user.phone_number,
                "email": user.email,
                "phoneno": user.phone_number,
                "joindate": user_role.assigned_at.date() if user_role and user_role.assigned_at else "",
                "trialfor": "",
                "plrelation": "",
                "dedtype": "",
                "evaldate": "",
                "natureofbusiness": "",
                "status": "",
                "activeyn": "YES" if user.isactive else "NO",  # <-- UPDATED
                "tdspartyyn": "",
                "typeofded": "",
                "add1": primary_address.address_line1 if primary_address else "",
                "add2": primary_address.address_line2 if primary_address else "",
                "add3": "",
                "city": primary_address.city if primary_address else "",
                "bcs_state": primary_address.state.name if primary_address and primary_address.state else "",
                "country": primary_address.country.name if primary_address and primary_address.country else "",
                "panno": tax_info.pan if tax_info else "",
                "gstnumsuf": "",
                "gstno": tax_info.gstin if tax_info else "",
                "gstdate": "",
                "acno": bank_info.account_number if bank_info else "",
                "bname": bank_info.bank_name if bank_info else "",
                "bankbranch": bank_info.branch_name if bank_info else "",
                "branchcode": "",
                "baccountname": bank_info.account_holder_name if bank_info else "",
                "ifsccode": bank_info.ifsc if bank_info else ""
            }

            # -------- Step 4: Documents JSON --------
            partymastdoc = {
                "partymastid": user.erp_external_id if user.erp_external_id else "",
                "empdocuid": bank_document.id if bank_document else "",
                "doctype": bank_document.document_type.value if bank_document else "",
                "attachfilename": bank_document.file_name if bank_document else ""
            }

            # -------- Step 5: TDS JSON --------
            tdssection = {
                "partymastid": user.erp_external_id if user.erp_external_id else "",
                "tdssectionid": tax_document.id if tax_document else "",
                "taxtype": tax_document.file_type if tax_document else "",
                "tdsper": ""
            }

            # -------- Append to Final Result --------
            final_result.append({
                "partymast": partymast,
                "partymastdoc": partymastdoc,
                "tdssection": tdssection
            })

        return final_result

    
    @classmethod
    def build_itemmaster_json(cls, db: Session):
        """
        Fetch all products and return each under its own 'Itemmaster' key.
        """
        products = db.query(Product).all()  # You can filter for unsynced if needed

        if not products:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No products found"
            )

        result = []
        for p in products:
            result.append({
                "itemmaster": {
                    "itemmasterid": products.erp_external_id if p.erp_external_id else "",
                    "subgroup": p.category_obj.name if p.category_obj else "",
                    "subgroup2": p.subcategory_obj.name if p.subcategory_obj else "",
                    "itemid": p.sku,
                    "itemdesc": p.description
                }
                
            })

        return result
