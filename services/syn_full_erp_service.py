import datetime
from sqlalchemy.orm import Session
from datetime import date
from fastapi import HTTPException, status
from models import (
    Product, User, UserAddress, UserDocument, UserRole, CompanyBankInfo,
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
                "partymastid": user.erp_external_id if user.erp_external_id else None,
                "docdate": None,
                "title": "Mr.",
                "partyid": f"{user.firstname or ''} {user.lastname or ''}".strip(),
                "partyname": f"{user.firstname or ''} {user.lastname or ''}".strip(),
                "vtype": "SUPPLIER [GOODS]",
                "agroupname": 1591714846604,  # Fixed value as per ERP requirement
                "typename": "REGISTERED",
                "gstpartytype": "DOMESTIC",
                "grade": "A",
                "mobile": user.phone_number,
                "email": user.email,
                "phoneno": user.phone_number,
                "joindate": user_role.assigned_at.date() if user_role and user_role.assigned_at else None,
                "trialfor": None,
                "plrelation": None,
                "dedtype": None,
                "evaldate": None,
                "natureofbusiness": None,
                "status": None,
                "activeyn": "YES" if user.isactive else "NO",  
                "tdspartyyn": "NO",
                "typeofded": None,
                "add1": primary_address.address_line1 if primary_address else None,
                "add2": primary_address.address_line2 if primary_address else None,
                "add3": None,
                "city": primary_address.city.erp_external_id if primary_address else None,
                "bcs_state": primary_address.state.erp_external_id if primary_address and primary_address.state else None,
                "country": primary_address.country.erp_external_id if primary_address and primary_address.country else None,
                "panno": tax_info.pan if tax_info else None,
                "gstnumsuf": None,
                "gstno": tax_info.gstin if tax_info else None,
                "gstdate": None,
                "acno": bank_info.account_number if bank_info else None,
                "bname": bank_info.bank_name if bank_info else None,
                "bankbranch": bank_info.branch_name if bank_info else None,
                "branchcode": None,
                "baccountname": bank_info.account_holder_name if bank_info else None,
                "ifsccode": bank_info.ifsc if bank_info else None ,
                "versionid": user.id if user.id else None,
                "projectid": "AVPPC_HESCOM",
                "rolename": "LICENSE_ROLE" 
           }


           

            # -------- Append to Final Result --------
            final_result.append({
                "partymast": partymast
                
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
                    "itemmasterid": products.erp_external_id if p.erp_external_id else None,
                    "subgroup": p.category_obj.name if p.category_obj else None,
                    "subgroup2": p.subcategory_obj.name if p.subcategory_obj else None,
                    "itemid": p.sku,
                    "itemdesc": p.description,
                    "createdfrom": "APP"
                }
            })

        return result
    @classmethod
    def build_ombasic_json(cls, db: Session):
        """
        Only ONE document per user should be synced (ONLY ONCE).
        If user already has a completed document → skip user.
        Valid = omno NOT NULL AND expiry_date NOT NULL.
        """

        # Fetch all user docs (any status)
        user_docs = db.query(UserDocument).all()

        if not user_docs:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No user documents found"
            )

        result = []
        processed_users = set()

        for doc in user_docs:
            user = doc.user
            if not user:
                continue

            # ⛔ If user already has completed doc → skip forever!
            has_completed = db.query(UserDocument).filter(
                UserDocument.user_id == user.id,
                UserDocument.erp_sync_status == "completed"
            ).first()

            if has_completed:
                continue   # This user already synced before, skip completely

            # Skip user if already added in this loop
            if user.id in processed_users:
                continue

            # ❌ Skip invalid docs, mark as pending
            if not doc.om_number or not doc.expiry_date:
                doc.erp_sync_status = "pending"
                continue

            # ✔ Valid document → Build JSON
            division = doc.division
            efffromdate = date.today()
            efftodate = doc.expiry_date.date()

            ombasic_json = {
                "ombasic": {
                    "ombasicid": doc.erp_external_id,
                    "partyid": user.erp_external_id,
                    "branchid": division.erp_external_id if division else None,
                    "omno": doc.om_number,
                    "efffromdate": efffromdate.strftime("%Y-%m-%d"),
                    "efftodate": efftodate.strftime("%Y-%m-%d")
                }
            }

            result.append(ombasic_json)

            # ✅ Mark user as processed
            processed_users.add(user.id)

            # 🔵 Mark this doc as permanently completed
            doc.erp_sync_status = "completed"

        db.commit()
        return result



  