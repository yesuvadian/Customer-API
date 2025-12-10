from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from services.erp_service import ERPService
from services.syn_full_erp_service import  ERPSyncService
from fastapi import Query

from models import Division, Product, User, UserDocument

router = APIRouter(prefix="/erp", tags=["ERP Sync"],dependencies=[Depends(get_current_user)])

@router.post(
    "/sync_erp_vendor",
    summary="Sync pending vendor data to ERP",
    description="Sync all users whose ERP status is pending or NULL."
)
async def sync_erp_vendor(db: Session = Depends(get_db)):
    """
    Sync ERP vendor data for all users whose ERP sync status is pending or NULL.
    Handles INSERT and UPDATE separately.
    """
    try:
        await ERPService.init_pool()  # ensure asyncpg pool is ready

        payload = ERPSyncService.build_party_json(db)

        insert_payload = payload.get("insert", [])
        update_payload = payload.get("update", [])

        insert_result = []
        update_result = []

        # ------------------------------------------------------------------
        # INSERT LOGIC (No erp_external_id)
        # ------------------------------------------------------------------
        if insert_payload:
            insert_result = await ERPService.insert_data(insert_payload)

            # Save returned ERP IDs to user table
            for rec in insert_result:
                if "partymast" in rec:
                    new_id = rec["partymast"]["partymastid"]
                    user_id = rec["partymast"]["versionid"]

                    user = db.query(User).filter(User.id == user_id).first()
                    if user:
                        user.erp_external_id = new_id
                        user.erp_sync_status = "completed"
                        db.add(user)

            db.commit()

        # ------------------------------------------------------------------
        # UPDATE LOGIC (Has erp_external_id)
        # ------------------------------------------------------------------
        if update_payload:
            update_result = await ERPService.update_data(update_payload)

            # Mark these users as completed
            update_user_ids = [
                item["partymast"]["versionid"]
                for item in update_payload
            ]
            db.query(User).filter(User.id.in_(update_user_ids)).update(
                {User.erp_sync_status: "completed"},
                synchronize_session=False
            )
            db.commit()

        # ------------------------------------------------------------------
        # FINAL RESPONSE
        # ------------------------------------------------------------------
        return {
            "status": "success",
            "inserted": insert_result,
            "updated": update_result
        }

    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            return {
                "status": "no-pending-users",
                "inserted": [],
                "updated": []
            }
        raise e

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get(
    "/sync_products",
    summary="Sync products to ERP",
    description="Fetch all products in ERP Itemmaster format and sync."
)
async def sync_erp_products(db: Session = Depends(get_db)):
    try:
        # Ensure PostgreSQL pool is ready
        await ERPService.init_pool()

        # Build ERP payload
        payload = ERPSyncService.build_itemmaster_json(db)
        insert_payload = payload.get("insert", [])
        update_payload = payload.get("update", [])

        insert_result = []
        update_result = []

        synced_product_ids = []

        # ---------- INSERT ----------
        if insert_payload:
            insert_result = await ERPService.insert_data(insert_payload)

            # Save returned erp_external_id into Product table
            for rec in insert_result:
                item = rec.get("itemmaster")
                if item:
                    erp_id = item.get("itemmasterid")
                    sku = item.get("itemid")

                    product = db.query(Product).filter(Product.sku == sku).first()
                    if product:
                        product.erp_external_id = erp_id
                        synced_product_ids.append(product.id)
                        db.add(product)

            db.commit()

        # ---------- UPDATE ----------
        if update_payload:
            update_result = await ERPService.update_data(update_payload)

            # Track updated products
            for rec in update_result:
                item = rec.get("itemmaster")
                if item:
                    sku = item.get("itemid")
                    product = db.query(Product).filter(Product.sku == sku).first()
                    if product:
                        synced_product_ids.append(product.id)

        # ---------- MARK ERP SYNC COMPLETED ----------
        if synced_product_ids:
            db.query(Product).filter(Product.id.in_(synced_product_ids)).update(
                {"erp_sync_status": "completed"},
                synchronize_session=False
            )
            db.commit()

        return {
            "status": "success",
            "inserted": insert_result,
            "updated": update_result
        }

    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            return []
        raise e

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
# =========================================
# Endpoint: Fetch and Insert Party Mast Docs
# =========================================
@router.post("/sync_partymastdoc", summary="Fetch documents and insert into Mongo + Postgres")
async def sync_partymastdoc(db: Session = Depends(get_db)):
    """
    Fetch all user documents, insert each into MongoDB, then wrap and insert
    into PostgreSQL as 'partymastdoc' entries.
    """
    try:
        # Ensure PostgreSQL pool is initialized
        await ERPService.init_pool()

        # Call the class method to fetch docs, insert into MongoDB, then Postgres
        inserted_results = await ERPService.fetch_and_insert_partymastdoc(db)

        return {
            "status": "success",
            "message": f"{len(inserted_results)} documents processed",
            "data": inserted_results
        }

    except AttributeError:
        # Likely cause: method not defined or wrong import
        raise HTTPException(
            status_code=500,
            detail="ERPService.fetch_and_insert_partymastdoc method not found. Ensure it is defined with @classmethod."
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------------- New endpoint ----------------
@router.get("/sync_ombasic")
async def sync_erp_ombasic(db: Session = Depends(get_db)):
    try:
        await ERPService.init_pool()

        payload = ERPSyncService.build_ombasic_json(db)
        insert_payload = payload.get("insert")
        update_payload = payload.get("update")

        inserted = None
        updated = None
        omdetail_inserted = None
        omdetail_updated = None
        synced_doc_id = None

        # ---------- INSERT ----------
        if insert_payload:
            inserted_list = await ERPService.insert_data([insert_payload])
            rec = inserted_list[0]["ombasic"]
            omno = rec["omno"]
            ombasicid = rec["ombasicid"]

            doc = db.query(UserDocument).filter(
                UserDocument.om_number == omno
            ).first()

            if doc:
                doc.erp_external_id = ombasicid
                doc.erp_sync_status = "completed"
                synced_doc_id = doc.id
                user_id = doc.user_id

            db.commit()
            inserted = rec

            # ---------- OMDTAIL ----------
            omdetail_inserted = ERPSyncService.build_omdetail(
                db=db,
                ombasic_id=ombasicid,
                company_id=user_id
            )

            # Send directly without wrapping
            await ERPService.insert_data(omdetail_inserted)

        # ---------- UPDATE ----------
        if update_payload:
            updated_list = await ERPService.update_data([update_payload])
            rec = updated_list[0]["ombasic"]
            omno = rec["omno"]

            doc = db.query(UserDocument).filter(
                UserDocument.om_number == omno
            ).first()

            if doc:
                doc.erp_sync_status = "completed"
                synced_doc_id = doc.id
                user_id = doc.user_id

            db.commit()
            updated = rec

            # ---------- OMDTAIL ----------
            omdetail_updated = ERPSyncService.build_omdetail(
                db=db,
                ombasic_id=doc.erp_external_id,
                company_id=user_id
            )

            await ERPService.update_data(omdetail_updated)

        return {
            "status": "success",
            "ombasic_inserted": inserted,
            "ombasic_updated": updated,
            "omdetail_inserted": omdetail_inserted,
            "omdetail_updated": omdetail_updated,
            "synced_document_id": synced_doc_id
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))




@router.get(
    "/sync_vendor_documents",
    summary="Fetch vendor documents grouped by ERP ID",
    description="Returns bank, tax, and user documents for all vendor users grouped by ERP external ID. Only includes users with a plan_id."
)
def sync_erp_vendor_documents(
    folder_name: str = Query("vendor", description="Folder name for documents"),
    db: Session = Depends(get_db)
):
    """
    Fetch all vendor documents, group by erp_external_id, mark ERP sync as completed.
    Optionally specify `folder_name` for the documents.
    """
    try:
        data = ERPSyncService.build_vendor_json(db, folder_name=folder_name)
    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            return {}
        raise e

    return data
@router.get("/sync_branchmast")
async def sync_erp_branchmast(db: Session = Depends(get_db)):
    try:
        # Ensure PostgreSQL pool is ready
        await ERPService.init_pool()

        # Build ERP payload
        payload = ERPSyncService.build_branchmast_json(db)
        insert_payload = payload.get("insert", [])
        update_payload = payload.get("update", [])

        insert_result = []
        update_result = []

        synced_division_ids = []

        # ---------- INSERT ----------
        if insert_payload:
            insert_result = await ERPService.insert_data(insert_payload)

            # Save returned erp_external_id into Division table
            for rec in insert_result:
                branch = rec.get("branchmast")
                if branch:
                    branch_id = branch.get("branchmastid")
                    branch_name = branch.get("branchname")

                    division = db.query(Division).filter(
                        Division.division_name == branch_name
                    ).first()

                    if division:
                        division.erp_external_id = branch_id
                        synced_division_ids.append(division.id)
                        db.add(division)

            db.commit()

        # ---------- UPDATE ----------
        if update_payload:
            update_result = await ERPService.update_data(update_payload)

            # Mark divisions updated as synced
            for rec in update_result:
                branch = rec.get("branchmast")
                if branch:
                    branch_name = branch.get("branchname")
                    division = db.query(Division).filter(
                        Division.division_name == branch_name
                    ).first()
                    if division:
                        synced_division_ids.append(division.id)

        # ---------- MARK ERP SYNC COMPLETED ----------
        if synced_division_ids:
            db.query(Division).filter(Division.id.in_(synced_division_ids)).update(
                {"erp_sync_status": "completed"},
                synchronize_session=False
            )
            db.commit()

        return {
            "status": "success",
            "inserted": insert_result,
            "updated": update_result
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



