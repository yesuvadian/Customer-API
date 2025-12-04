from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from services.syn_full_erp_service import ERPService
from fastapi import Query

from models import User

router = APIRouter(prefix="/erp", tags=["ERP Sync"],dependencies=[Depends(get_current_user)])

@router.post(
    "/sync_erp_vendor",                # <-- changed here
    summary="Sync pending vendor data to ERP",
    description="Fetch all vendor users with pending ERP status and return full ERP JSON data."
)
def sync_erp_vendor(db: Session = Depends(get_db)):
    """
    Sync ERP vendor data for all users whose ERP status is 'pending' or NULL.
    """
    try:
        data = ERPService.build_party_json(db)
    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            return []  # return empty list to match response_model
        raise e

    # Update ERP sync status for processed users
    user_ids = [item["partymast"]["versionid"] for item in data]
    if user_ids:
        db.query(User).filter(User.id.in_(user_ids)).update(
            {User.erp_sync_status: "completed"}, synchronize_session=False
        )
        db.commit()

    return data
@router.get(
    "/sync_products",                # <-- changed here
    summary="Sync products to ERP",
    description="Fetch all products in ERP Itemmaster format."
)
def sync_erp_products(db: Session = Depends(get_db)):
    try:
        data = ERPService.build_itemmaster_json(db)
    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            return []
        raise e

    return data
# ---------------- New endpoint ----------------
@router.get(
    "/sync_ombasic",
    summary="Fetch all user documents in ERP ombasic format",
    description="Return ombasic JSON for all user documents; ERP sync status is updated in DB automatically."
)
def sync_erp_ombasic(db: Session = Depends(get_db)):
    """
    Fetch all user_documents, return ombasic JSON, and mark ERP sync as completed.
    """
    try:
        data = ERPService.build_ombasic_json(db)
    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            return []  # Return empty list if no documents found
        raise e

    return data

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
        data = ERPService.build_vendor_json(db, folder_name=folder_name)
    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            return {}
        raise e

    return data
@router.get(
    "/sync_branchmast",
    summary="Sync branchmast data to ERP",
    description="Fetch all users and divisions to build branchmast JSON for ERP."
)
def sync_erp_branchmast(db: Session = Depends(get_db)):
    try:
        data = ERPService.build_branchmast_json(db)
    except HTTPException as e:
        if e.status_code == status.HTTP_404_NOT_FOUND:
            return []  # Return empty list if no users/divisions found
        raise e
    return data