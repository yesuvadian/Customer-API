import datetime
from operator import or_
import asyncpg
from sqlalchemy import UUID, func
from sqlalchemy.orm import Session
from datetime import date
from fastapi import HTTPException, status
from config import POSTGRES_CONFIG
from models import (
    CategoryDetails, CategoryMaster, CompanyProduct, Product, User, UserAddress, UserDocument, UserRole, CompanyBankInfo,
    CompanyTaxInfo, CompanyBankDocument, CompanyTaxDocument
)
from models import UserDocument
from models import Division
from services.erp_service import ERPService
from services.mongo_service import MongoService

class ERPSyncService:

    @classmethod
    def build_party_json(cls, db: Session):
        """
        Build ERP Party JSON payload.
        - Only include users with erp_sync_status = 'pending' or NULL
        - If user has erp_external_id → UPDATE payload
        - Else → INSERT payload
        """

        # Fetch users pending ERP sync
        users = db.query(User).filter(
            (User.erp_sync_status == None) | (User.erp_sync_status == "pending"),
            User.plan_id != None  # Only users with a plan
        ).all()

        if not users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No pending users found"
            )

        insert_payload = []
        update_payload = []

        for user in users:
            primary_address = db.query(UserAddress).filter(
                UserAddress.user_id == user.id,
                UserAddress.is_primary == True
            ).first()

            tax_info = db.query(CompanyTaxInfo).filter(
                CompanyTaxInfo.company_id == user.id
            ).first()

            bank_info = db.query(CompanyBankInfo).filter(
                CompanyBankInfo.company_id == user.id
            ).first()

            user_role = db.query(UserRole).filter(
                UserRole.user_id == user.id
            ).first()

            # -------- Party JSON --------
            partymast = {
                "docdate": None,
                "title": "Mr.",
                "partyid": f"{user.firstname or ''} {user.lastname or ''}".strip(),
                "partyname": f"{user.firstname or ''} {user.lastname or ''}".strip(),
                "vtype": "SUPPLIER [GOODS]",
                "agroupname": 1591714846604,
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
                "city": int(primary_address.city.erp_external_id) if primary_address else None,
                "bcs_state": int(primary_address.state.erp_external_id) if primary_address and primary_address.state else None,
                "country": int(primary_address.country.erp_external_id) if primary_address and primary_address.country else None,
                "panno": tax_info.pan if tax_info else None,
                "gstnumsuf": None,
                "gstno": tax_info.gstin if tax_info else None,
                "gstdate": None,
                "acno": bank_info.account_number if bank_info else None,
                "bname": bank_info.bank_name if bank_info else None,
                "bankbranch": bank_info.branch_name if bank_info else None,
                "branchcode": None,
                "baccountname": bank_info.account_holder_name if bank_info else None,
                "ifsccode": bank_info.ifsc if bank_info else None,
                "versionid": str(user.id),
                "projectid": "AVPPC_HESCOM",
                "rolename": "LICENSE_ROLE"
            }

            data = {"partymast": partymast}

            # -------- INSERT vs UPDATE --------
            if user.erp_external_id:
                data["partymast"]["partymastid"] = user.erp_external_id
                update_payload.append(data)
            else:
                insert_payload.append(data)

        return {
            "insert": insert_payload,
            "update": update_payload
        }


    
    @classmethod
    def build_itemmaster_json(cls, db: Session):
        """
        Build itemmaster JSON payload for ERP.
        - Only include products with erp_sync_status = 'pending'
        - If product has erp_external_id → UPDATE payload
        - Else → INSERT payload
        """

      # Fetch products that need syncing (pending or NULL)
        products = db.query(Product).filter(
            or_(
                Product.erp_sync_status == "pending",
                Product.erp_sync_status.is_(None)
            )
        ).all()
        if not products:
            raise HTTPException(
                status_code=404,
                detail="No pending products to sync"
            )

        insert_payload = []
        update_payload = []

        for p in products:
            data = {
                "itemmaster": {
                    "subgroup": p.category_obj.id if p.category_obj else None,
                    "subgroup2": p.subcategory_obj.id if p.subcategory_obj else None,
                    "itemid": p.sku,
                    "itemdesc": p.description,
                    "createdfrom": "APP",
                    "maingroup":1
 
                    
                }
            }

            # -------- UPDATE case --------
            if p.erp_external_id:
                data["itemmaster"]["itemmasterid"] = p.erp_external_id
                update_payload.append(data)

            # -------- INSERT case --------
            else:
                # For insert, do not send ERP ID
                insert_payload.append(data)

        return {
            "insert": insert_payload,
            "update": update_payload
        }

    @classmethod
    def build_ombasic_json(cls, db: Session):
        """
        Build ombasic JSON similar to branchmast JSON structure.
        - Include only documents with erp_sync_status='pending'
        - Skip users who already have any completed ombasic record
        - If doc.erp_external_id → UPDATE payload
        - If doc.erp_external_id is NULL → INSERT payload
        - Only include valid docs (omno & expiry_date)
        """

        # Fetch all pending docs
        docs = db.query(UserDocument).filter(
            UserDocument.erp_sync_status == "pending"
        ).all()

        if not docs:
            raise HTTPException(404, "No pending OM documents to sync")

        insert_payload = []
        update_payload = []
        processed_users = set()

        for doc in docs:
            user = doc.user
            if not user:
                continue

            # ⛔ Skip if user has ANY completed OM sync earlier
            has_completed = db.query(UserDocument).filter(
                UserDocument.user_id == user.id,
                UserDocument.erp_sync_status == "completed"
            ).first()

            if has_completed:
                continue

            # ⛔ If user already included in this batch → skip
            if user.id in processed_users:
                continue

            # ❌ Invalid doc → keep as pending, do not include in payload
            if not doc.om_number or not doc.expiry_date:
                doc.erp_sync_status = "pending"
                continue

            division = doc.division
            efffromdate = date.today()
            efftodate = doc.expiry_date.date()

            data = {
                "ombasic": {
                    "partyid": user.erp_external_id,
                    "branchid": division.erp_external_id if division else None,
                    "omno": doc.om_number,
                    "efffromdate": efffromdate.strftime("%Y-%m-%d"),
                    "efftodate": efftodate.strftime("%Y-%m-%d")
                }
            }

            # ---------------- UPDATE CASE ----------------
            if doc.erp_external_id:
                data["ombasic"]["ombasicid"] = doc.erp_external_id
                update_payload.append(data)

            # ---------------- INSERT CASE ----------------
            else:
                # No ombasicid — ERP will generate new one
                insert_payload.append(data)

            processed_users.add(user.id)
            doc.erp_sync_status = "completed"

        db.commit()

        return {
            "insert": insert_payload,
            "update": update_payload
        }


    @classmethod
    def build_vendor_json(cls, db: Session, folder_name: str = "vendor"):
        """
        Build vendor JSON for all users with non-null plan_id,
        grouped by erp_external_id.
        Each user/company will include:
          - bank_documents
          - tax_documents
          - user_documents
        """
        users = (
            db.query(User)
            .filter(
                ((User.erp_sync_status == None) | (User.erp_sync_status == "pending")) &
                (User.plan_id != None)  # <-- Only users with a plan
            )
            .all()
        )

        if not users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No pending users with plan found"
            )

        final_result = {}

        for user in users:
            erp_id = user.erp_external_id or str(user.id)

            # Fetch related documents
            tax_docs = (
                db.query(CompanyTaxDocument)
                .join(CompanyTaxInfo, CompanyTaxInfo.id == CompanyTaxDocument.company_tax_info_id)
                .filter(CompanyTaxInfo.company_id == user.id)
                .all()
            )

            bank_docs = (
                db.query(CompanyBankDocument)
                .join(CompanyBankInfo, CompanyBankInfo.id == CompanyBankDocument.company_bank_info_id)
                .filter(CompanyBankInfo.company_id == user.id)
                .all()
            )

            user_docs = (
                db.query(UserDocument)
                .filter(UserDocument.user_id == user.id)
                .all()
            )

            # Prepare JSON lists
            tax_docs_json = [
                {
                    "file_name": td.file_name,
                    "file_data": td.file_data,
                    "category_detail_name": td.category_detail_name,
                    "folder_name": folder_name
                }
                for td in tax_docs
            ]

            bank_docs_json = [
                {
                    "file_name": bd.file_name,
                    "file_data": bd.file_data,
                    "category_detail_name": bd.category_detail_name,
                    "folder_name": folder_name
                }
                for bd in bank_docs
            ]

            user_docs_json = [
                {
                    "file_name": ud.document_name,
                    "file_data": ud.file_data,
                    "category_detail_name": ud.category_detail_name,
                    "folder_name": folder_name
                }
                for ud in user_docs
            ]

            final_result[erp_id] = {
                "bank_documents": bank_docs_json,
                "tax_documents": tax_docs_json,
                "user_documents": user_docs_json
            }

            # Mark all documents as synced
            for doc in tax_docs + bank_docs + user_docs:
                doc.erp_sync_status = "completed"

            # Mark user ERP sync as completed
            user.erp_sync_status = "completed"

        db.commit()
        return final_result
    @classmethod
    def build_branchmast_json(cls, db: Session):
        """
        Build branchmast JSON payload for ERP.
        - Only include divisions with erp_sync_status = 'pending'
        - If division has erp_external_id → UPDATE payload
        - Else → INSERT payload
        """

        # Get all divisions with code and pending ERP sync
        divisions = db.query(Division).filter(
            Division.code != None,
            Division.erp_sync_status == "pending"
        ).all()

        if not divisions:
            raise HTTPException(404, "No pending divisions to sync")

        insert_payload = []
        update_payload = []

        for division in divisions:

            data = {
                "branchmast": {
                    "branchid": division.division_name,
                    "branchname": division.division_name
                }
            }

            # -------- UPDATE case --------
            if division.erp_external_id:
                data["branchmast"]["branchmastid"] = division.erp_external_id
                update_payload.append(data)

            # -------- INSERT case --------
            else:
                # For insert, DO NOT send ID → ERP will generate new one
                insert_payload.append(data)

        return {
            "insert": insert_payload,
            "update": update_payload
        }

    @classmethod
    async def init_pool(cls):
        if cls.pool is None:
            cls.pool = await asyncpg.create_pool(**POSTGRES_CONFIG)

    @classmethod
    async def fetch_and_insert_partymastdoc(cls, db: Session):
        users = db.query(User).filter(User.erp_external_id.isnot(None)).all()
        inserted_results = []

        for user in users:
            erp_id = user.erp_external_id
            user_id = user.id

            def get_master_id(name):
                return db.query(CategoryMaster.id).filter(CategoryMaster.name == name).scalar()

            company_master_id = get_master_id("Company Documents")
            tax_master_id = get_master_id("Tax Documents")
            bank_master_id = get_master_id("Bank Document Types")

            # Check master completion
            def is_master_complete(master_id):
                required_count = (
                    db.query(func.count(CategoryDetails.id))
                    .filter(CategoryDetails.category_master_id == master_id)
                    .scalar()
                )
                uploaded_count = (
                    db.query(func.count(UserDocument.id))
                    .filter(UserDocument.user_id == user_id)
                    .join(CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id)
                    .filter(CategoryDetails.category_master_id == master_id)
                    .filter(UserDocument.is_active == True)
                    .scalar()
                )
                return uploaded_count == required_count

            include_company = is_master_complete(company_master_id)
            include_tax = is_master_complete(tax_master_id)
            include_bank = is_master_complete(bank_master_id)

            if not any([include_company, include_tax, include_bank]):
                continue

            all_docs = (
                db.query(UserDocument, CategoryDetails)
                .join(CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id)
                .filter(
                    UserDocument.user_id == user_id,
                    CategoryDetails.category_master_id.in_([
                        company_master_id if include_company else -1,
                        tax_master_id if include_tax else -1,
                        bank_master_id if include_bank else -1
                    ])
                )
                .all()
            )

            for doc, cat in all_docs:
                mongo_payload = {
                    "filename": doc.file_url.split("/")[-1] if doc.file_url else "1.doc",
                    "filedata": doc.file_data or [],
                    "foldername": "vendor"
                }

                mongo_result = MongoService.insert(mongo_payload)
                mongo_id = mongo_result["id"]

                partymastdoc_payload = [{
                    "partymastdoc": {
                        "partymastdocid": None,
                        "partymastid": erp_id,
                        "doctype": cat.name,
                        "objected": mongo_id,
                        "attachfilename": mongo_payload["filename"]
                    }
                }]

                await cls.init_pool()
                result = await cls.insert_data(partymastdoc_payload)
                inserted_results.extend(result)

        return inserted_results
    @classmethod
    def build_omdetail(cls, db: Session, ombasic_id: str, company_id: UUID):
        """
        Returns a list of key-value pairs exactly in the repeated JSON format required:
        
        "omdetail": { ... },
        "omdetail": { ... }
        """
        company_products = (
            db.query(CompanyProduct)
            .filter(CompanyProduct.company_id == company_id)
            .all()
        )

        output_blocks = []

        for cp in company_products:
            product = db.query(Product).filter(Product.id == cp.product_id).first()
            if not product or not product.erp_external_id:
                continue

            block = (
                '"omdetail": {\n'
                f'  "ombasicid": "{ombasic_id}",\n'
                f'  "itemid": "{product.erp_external_id}"\n'
                '}'
            )

            output_blocks.append(block)

        # Join with commas EXACTLY like your format
        return ",\n\n".join(output_blocks)

