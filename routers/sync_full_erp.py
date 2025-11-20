from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from services.syn_full_erp_service import ERPService


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
