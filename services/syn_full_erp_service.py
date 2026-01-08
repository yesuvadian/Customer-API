import base64
import datetime
from operator import or_
from bson.binary import Binary
import asyncpg
from sqlalchemy import UUID, func
from sqlalchemy.orm import Session
from datetime import date
from fastapi import HTTPException, status
from config import POSTGRES_CONFIG
from models import (
    CategoryDetails, CategoryMaster, CompanyProduct, Product, ProductCategory, ProductSubCategory, User, UserAddress, UserDocument, UserRole, CompanyBankInfo,
    CompanyTaxInfo, CompanyBankDocument, CompanyTaxDocument
)
from models import UserDocument
from models import Division
from services.erp_service import ERPService
from services.mongo_service import MongoService
 
class ERPSyncService:
    
    def safe_int(val):
            try:
                return int(val) if val is not None else None
            except (TypeError, ValueError):
                return None
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
            User.plan_id != None
        ).all()
 
        if not users:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No pending users found"
            )
 
        insert_payload = []
        update_payload = []
 
        for user in users:
 
            # ---------------- Primary Address (Office always wins) ----------------

            # 1️⃣ Office address (HIGHEST priority)
            primary_address = (
                db.query(UserAddress)
                .filter(
                    UserAddress.user_id == user.id,
                    UserAddress.address_type == "office"
                )
                .order_by(UserAddress.id.asc())
                .first()
            )

            # 2️⃣ If no office → fallback to existing primary
            if not primary_address:
                primary_address = (
                    db.query(UserAddress)
                    .filter(
                        UserAddress.user_id == user.id,
                        UserAddress.is_primary.is_(True)
                    )
                    .first()
                )

            # 3️⃣ If still none → pick any
            if not primary_address:
                primary_address = (
                    db.query(UserAddress)
                    .filter(UserAddress.user_id == user.id)
                    .order_by(UserAddress.id.asc())
                    .first()
                )

            # 4️⃣ No address → error
            if not primary_address:
                raise HTTPException(
                    status_code=400,
                    detail=f"No address found for user {user.id}"
                )

            # 5️⃣ Enforce rules:
            #    - office = true
            #    - communication = false

            db.query(UserAddress).filter(
                UserAddress.user_id == user.id
            ).update(
                {UserAddress.is_primary: False},
                synchronize_session="fetch"
            )

            primary_address.is_primary = True
            db.add(primary_address)
            db.flush()



 
            missing = []
            if not primary_address.city or not primary_address.city.erp_external_id:
                missing.append("city")
            if not primary_address.state or not primary_address.state.erp_external_id:
                missing.append("state")
            if not primary_address.country or not primary_address.country.erp_external_id:
                missing.append("country")
 
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing address ERP mapping {missing} for user {user.id}"
                )
 
            # ---------------- Other Info ----------------
            tax_info = db.query(CompanyTaxInfo).filter(
                CompanyTaxInfo.company_id == user.id
            ).first()
 
            bank_info = db.query(CompanyBankInfo).filter(
                CompanyBankInfo.company_id == user.id
            ).first()
 
            user_role = db.query(UserRole).filter(
                UserRole.user_id == user.id
            ).first()
 
            # ---------------- Party Payload ----------------
            partymast = {
                "docdate": None,
                "title": "Mr.",
                "partyid": f"{user.firstname or ''} {user.lastname or ''}".strip(),
                "partyname": f"{user.firstname or ''} {user.lastname or ''}".strip(),
                "vtype": "SUPPLIER [GOODS]",
                "gaccountname": 1591714846604,
                "typename": "REGISTERED",
                "gstpartytype": "DOMESTIC",
                "grade": "A",
                "mobile": user.phone_number,
                "email": user.email,
                "phoneno": user.phone_number,
                "joindate": (
                    user_role.assigned_at.date()
                    if user_role and user_role.assigned_at
                    else None
                ),
                "activeyn": "YES" if user.isactive else "NO",
                "tdspartyyn": "NO",
 
                # -------- Address --------
                "add1": primary_address.address_line1,
                "add2": primary_address.address_line2 or "",
                "add3": "",
                "city": cls.safe_int(primary_address.city.erp_external_id),
                "bcs_state": cls.safe_int(primary_address.state.erp_external_id),
                "country": cls.safe_int(primary_address.country.erp_external_id),
 
                # -------- Tax --------
                "panno": tax_info.pan if tax_info else None,
                "gstno": tax_info.gstin if tax_info else None,
                "gstnumsuf": tax_info.gstin[-3:] if tax_info and tax_info.gstin else None,

                # -------- Bank --------
                "acno": bank_info.account_number if bank_info else None,
                "bname": bank_info.bank_name if bank_info else None,
                "bankbranch": bank_info.branch_name if bank_info else None,
                "baccountname": bank_info.account_holder_name if bank_info else None,
                "ifsccode": bank_info.ifsc if bank_info else None,
 
                # -------- Meta --------
                "versionid": str(user.id),
                "projectid": "AVPPC_HESCOM",
                "rolename": "LICENSE_ROLE",
                "partycat": "SUPPLIER",
                "createdfrom": "APP",
                "partystatus":"PENDING",
                "is_cancelled":"F",
                "approvalstatus": "APPROVED"
            }
 
            data = {"partymast": partymast}
 
            # ---------------- INSERT vs UPDATE ----------------
            if user.erp_external_id:
                partymast["partymastid"] = user.erp_external_id
                update_payload.append(data)
            else:
                insert_payload.append(data)

        db.commit()

 
        return {
            "insert": insert_payload,
            "update": update_payload
        }
 
 
   

    def extract_gst_percentage(gst_slab_obj) -> float:
        """
        Extract GST % from a CategoryDetails object.
        Returns 0.0 if gst_slab_obj is None or name is invalid.
        """
        if not gst_slab_obj:
            return 0.0
        try:
            return float(gst_slab_obj)
        except ValueError:
            return 0.0



    def erp_str(val: str, max_len: int):
        if not val:
            return None
        return val.strip()[:max_len]

    
    @classmethod
    async def build_itemmaster_json(cls, db: Session):
        from sqlalchemy.orm import joinedload
        from sqlalchemy import or_
        
        products = db.query(Product).options(joinedload(Product.gst_slab)).filter(
            or_(
                Product.erp_sync_status == "pending",
                Product.erp_sync_status.is_(None)
            )
        ).all()

        if not products:
            raise HTTPException(status_code=404, detail="No pending products to sync")

        insert_payload = []
        update_payload = []

        for p in products:
            sku = p.sku or ""
            desc = f"{p.name}-{p.material_code}" if p.name and p.material_code else ""

            # ---------------- ITEMMASTER ----------------
            itemmaster = {
                "subgroup": p.category_obj.id if p.category_obj else None,
                "subgroup2": p.subcategory_obj.id if p.subcategory_obj else None,
                "itemid": f"{sku}-{desc}",
                "itemdesc": cls.erp_str(desc,400),
                "sku": sku,
                "sellingrate": p.selling_price,
                "purchaserate": p.cost_price,
                "itemcode": p.material_code,
                "createdfrom": "APP",
                "maingroup": 1,
                "is_cancelled": "F"
            }

            # ---------------- ITEMTAX ----------------
            gst_name = p.gst_slab.name if p.gst_slab else None
            igst_per = cls.extract_gst_percentage(gst_name)

            # ⚡ Await async HSN ID
            hsn_id = await ERPService.get_or_create_hsncode_id(p.hsn_code, p.description)

            itemtax = {
                "igstper": igst_per,
                "hsncode": hsn_id
            }

            # ---------------- UPDATE ----------------
            if p.erp_external_id:
                itemmaster["itemmasterid"] = p.erp_external_id
                update_payload.append({
                    "itemmaster": itemmaster,
                    "itemtax": itemtax
                })
            else:
                insert_payload.append({
                    "itemmaster": itemmaster,
                    "itemtax": itemtax
                })

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
            # Skip if user ERP ID is missing
            if not user.erp_external_id:
                continue
 
            # Skip if division ERP ID is missing
            if not division or not division.erp_external_id:
                continue
 
            efffromdate = date.today()
 
           
           
 
            data = {
                "ombasic": {
                    "partyid": int(user.erp_external_id),
                    "branchid": int(division.erp_external_id),
                    "omno": doc.om_number,
                    "omdate": efffromdate,
                    "is_cancelled":"F"
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
                    "category_detail_name": td.category_detail.name,
                    "folder_name": folder_name
                }
                for td in tax_docs
            ]
 
            bank_docs_json = [
                {
                    "file_name": bd.file_name,
                    "file_data": bd.file_data,
                    "category_detail_name": bd.document_type_detail.name,
                    "folder_name": folder_name
                }
                for bd in bank_docs
            ]
 
            user_docs_json = [
                {
                    "file_name": ud.document_name,
                    "file_data": ud.file_data,
                    "category_detail_name": ud.categorydetails.name,
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
    async def fetch_and_insert_partymastdoc(cls, db: Session, folder_name: str = None):
        users = db.query(User).filter(User.erp_external_id.isnot(None)).all()
        inserted_results = []
 
        # Initialize ERP pool once
        await ERPService.init_pool()
 
        # Helper to get master ID
        def get_master_id(name):
            return db.query(CategoryMaster.id).filter(CategoryMaster.name == name).scalar()
 
        company_master_id = get_master_id("Company Documents")
        tax_master_id = get_master_id("Tax Documents")
        bank_master_id = get_master_id("Bank Document Types")
 
        for user in users:
            erp_id = user.erp_external_id
            user_id = user.id
 
            # Check if master is complete
            def is_master_complete(master_id):
                required_count = db.query(func.count(CategoryDetails.id)).filter(
                    CategoryDetails.category_master_id == master_id
                ).scalar()
                uploaded_count = db.query(func.count(UserDocument.id)).join(
                    CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id
                ).filter(
                    UserDocument.user_id == user_id,
                    CategoryDetails.category_master_id == master_id,
                    UserDocument.is_active == True
                ).scalar()
                return uploaded_count == required_count
 
            include_company = is_master_complete(company_master_id)
            include_tax = is_master_complete(tax_master_id)
            include_bank = is_master_complete(bank_master_id)
 
            if not any([include_company, include_tax, include_bank]):
                continue
 
            all_docs = db.query(UserDocument, CategoryDetails).join(
                CategoryDetails, UserDocument.category_detail_id == CategoryDetails.id
            ).filter(
                UserDocument.user_id == user_id,
                CategoryDetails.category_master_id.in_([
                    company_master_id if include_company else -1,
                    tax_master_id if include_tax else -1,
                    bank_master_id if include_bank else -1
                ])
            ).all()
 
            for doc, cat in all_docs:
                # Convert file_data to Mongo Binary
                mongo_binary = None
                if doc.file_data:
                    if isinstance(doc.file_data, memoryview):
                        file_bytes = bytes(doc.file_data)
                    else:
                        file_bytes = doc.file_data
                    mongo_binary = Binary(file_bytes)
 
                mongo_payload = {
                    "filename": doc.document_name,
                    "filetype": getattr(doc, "content_type", None),  # fixed field
                    "fileContent": mongo_binary,
                    "foldername": folder_name
                }
 
                # Insert into Mongo (sync call; safe if fast)
                try:
                    mongo_result = MongoService.insert(mongo_payload)
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"Mongo insert failed: {str(e)}"
                    )   
                mongo_id = mongo_result.get("id") or str(mongo_result.get("_id"))
 
                partymastdoc_payload = [{
                    "partymastdoc": {
                        "partymastdocid": None,
                        "partymastid": int(erp_id),
                        "doctype": cat.name,
                        "objectid": mongo_id,
                        "attachfilename": mongo_payload["filename"]
                    }
                }]
 
                # Insert into ERP asynchronously
                insert_response = await ERPService.insert_data(partymastdoc_payload)
                inserted_results.extend(insert_response)
 
        return inserted_results
 
 
 
    @classmethod
    def build_omdetail(cls, db: Session, ombasic_id: str, company_id: UUID):
        """
        Returns repeated JSON blocks in the exact format:
        [
            {"omdetail": {...}},
            {"omdetail": {...}}
        ]
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
 
            user_doc = (
                db.query(UserDocument)
                .filter(
                    UserDocument.user_id == company_id,
                    UserDocument.expiry_date.isnot(None)
                )
                .order_by(UserDocument.expiry_date.desc())
                .first()
            )
 
            if not user_doc:
                continue
 
            block = {
                "omdetail": {
                    "ombasicid": ombasic_id,
                    "itemid": int(product.erp_external_id),
                    "expdate": user_doc.expiry_date
 
                }
            }
 
            output_blocks.append(block)
 
        # Return **after** processing all products
        return output_blocks
    
    # =====================================
    # BUILD IGDETAIL JSON (PARENT CATEGORY)
    # =====================================
    @classmethod
    def build_igdetail_json(cls, db: Session):
        """
        Build IGDETAIL payload
        - Only for NEW categories
        - Already synced categories are skipped
        """

        categories = db.query(ProductCategory).filter(
            ProductCategory.erp_sync_status == "pending",
            ProductCategory.is_active == True
        ).all()

        # ✅ DO NOT THROW ERROR
        if not categories:
            return {
                "insert": [],
                "update": []
            }

        insert_payload = []
        update_payload = []

        for cat in categories:
            data = {
                "igdetail": {
                    "igbasicid": 1,
                    "subgroup": cat.name,
                    "maingroup": "RAW MATERIALS",
                    "mgcode": "RM"
                }
            }

            # -------- UPDATE --------
            if cat.erp_external_id:
                data["igdetail"]["igdetailid"] = int(cat.erp_external_id)
                update_payload.append(data)

            # -------- INSERT --------
            else:
                insert_payload.append(data)

        return {
            "insert": insert_payload,
            "update": update_payload
        }

    # =====================================
    # BUILD IGSDETAIL (FOR NEW CATEGORY)
    # =====================================
    @classmethod
    def build_igsdetail_json(cls, db: Session, igdetail_id: int, category_id: int):
        """
        Build IGSDETAIL for newly created category
        """

        subcategories = db.query(ProductSubCategory).filter(
            ProductSubCategory.category_id == category_id,
            ProductSubCategory.is_active == True,
            ProductSubCategory.erp_sync_status == "pending"
        ).all()

        blocks = []

        for sub in subcategories:
            blocks.append({
                "igsdetail": {
                    "igbasicid": 1,
                    "igdetailid": igdetail_id,
                    "subgroup2": sub.name
                }
            })

        return blocks

    # =====================================
    # BUILD IGSDETAIL ONLY (EXISTING CATEGORY)
    # =====================================
    @classmethod
    def build_igsdetail_only(cls, db: Session):
        """
        Build IGSDETAIL payload for NEW subcategories
        under already synced categories
        """

        subcategories = (
            db.query(ProductSubCategory)
            .join(ProductCategory)
            .filter(
                ProductSubCategory.erp_sync_status == "pending",
                ProductSubCategory.is_active == True,
                ProductCategory.erp_external_id.isnot(None)
            )
            .all()
        )

        payload = []

        for sub in subcategories:
            payload.append({
                "igsdetail": {
                    "igbasicid": 1,
                    "igdetailid": int(sub.category.erp_external_id),
                    "subgroup2": sub.name
                }
            })

        return payload
    