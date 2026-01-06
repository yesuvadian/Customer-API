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
        payload = await ERPSyncService.build_itemmaster_json(db)
        insert_payload = payload.get("insert", [])
        update_payload = payload.get("update", [])

        insert_result = []
        update_result = []
        synced_product_ids = []

        # ------------------ INSERT ------------------
        if insert_payload:
            insert_result = await ERPService.insert_item_with_tax(insert_payload)

            for rec in insert_result:
                item = rec.get("itemmaster")
                if not item:
                    continue

                erp_id = item.get("itemmasterid")
                sku = item.get("sku")       # ✅ Correct mapping

                if not sku or not erp_id:
                    continue

                product = (
                    db.query(Product)
                    .filter(Product.sku == sku)
                    .first()
                )

                if product:
                    product.erp_external_id = erp_id
                    synced_product_ids.append(product.id)

            db.commit()

        # ------------------ UPDATE ------------------
        if update_payload:
            update_result = await ERPService.update_data(update_payload)

            for rec in update_result:
                item = rec.get("itemmaster")
                if not item:
                    continue

                sku = item.get("sku")      # ✅ Correct mapping

                if not sku:
                    continue

                product = (
                    db.query(Product)
                    .filter(Product.sku == sku)
                    .first()
                )

                if product:
                    synced_product_ids.append(product.id)

        # ----------- MARK SYNC COMPLETED ------------
        if synced_product_ids:
            db.query(Product).filter(
                Product.id.in_(synced_product_ids)
            ).update(
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
            return {
                "status": "success",
                "message": "No pending products to sync",
                "inserted": [],
                "updated": []
            }
        raise e

    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))



@router.get("/sync_ombasic")
async def sync_erp_ombasic(db: Session = Depends(get_db)):
    try:
        await ERPService.init_pool()

        payload = ERPSyncService.build_ombasic_json(db)
        insert_payload = payload.get("insert", [])
        update_payload = payload.get("update", [])

        inserted = []
        updated = []
        omdetail_inserted = []
        omdetail_updated = []
        synced_doc_ids = []

        # ================== INSERT ==================
        if insert_payload:
            inserted_list = await ERPService.insert_data(insert_payload)

            for item in inserted_list:
                if "ombasic" not in item:
                    continue

                rec = item["ombasic"]
                omno = rec.get("omno")
                ombasicid = rec.get("ombasicid")

                doc = db.query(UserDocument).filter(
                    UserDocument.om_number == omno
                ).first()

                if not doc:
                    continue

                # Save ERP ID
                doc.erp_external_id = ombasicid
                doc.erp_sync_status = "completed"
                synced_doc_ids.append(doc.id)
                user_id = doc.user_id

                db.commit()
                inserted.append(rec)

                # -------- OMDDETAIL INSERT (BATCH) --------
                details = ERPSyncService.build_omdetail(
                    db=db,
                    ombasic_id=ombasicid,
                    company_id=user_id
                )

                if details:
                    import asyncio
                    await asyncio.sleep(0.5)  # allow ERP to commit OMBASIC

                    result = await ERPService.insert_data(details)
                    omdetail_inserted.extend(result)

        # ================== UPDATE ==================
        if update_payload:
            updated_list = await ERPService.update_data(update_payload)

            for item in updated_list:
                if "ombasic" not in item:
                    continue

                rec = item["ombasic"]
                omno = rec.get("omno")

                doc = db.query(UserDocument).filter(
                    UserDocument.om_number == omno
                ).first()

                if not doc:
                    continue

                doc.erp_sync_status = "completed"
                synced_doc_ids.append(doc.id)
                user_id = doc.user_id
                ombasicid = doc.erp_external_id

                db.commit()
                updated.append(rec)

                # -------- OMDDETAIL UPDATE (BATCH) --------
                details = ERPSyncService.build_omdetail(
                    db=db,
                    ombasic_id=ombasicid,
                    company_id=user_id
                )

                if details:
                    import asyncio
                    await asyncio.sleep(0.5)

                    result = await ERPService.update_data(details)
                    omdetail_updated.extend(result)

        return {
            "status": "success",
            "ombasic_inserted": inserted,
            "ombasic_updated": updated,
            "omdetail_inserted": omdetail_inserted,
            "omdetail_updated": omdetail_updated,
            "synced_document_ids": synced_doc_ids
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))



@router.post("/sync_erp_vendor_documents")
async def sync_erp_vendor_documents(
    folder_name: str = "vendor",
    db: Session = Depends(get_db)
):
    try:
        await ERPService.init_pool()  # always initialize connection pool

        # MUST await because the service method is async
        data = await ERPSyncService.fetch_and_insert_partymastdoc(
            db=db,
            folder_name=folder_name
        )

        return {
            "status": "success",
            "message": f"{len(data)} documents synced",
            "inserted": data
        }

    except AttributeError:
        raise HTTPException(
            status_code=500,
            detail="Error: fetch_and_insert_partymastdoc() not found or not marked async"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

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