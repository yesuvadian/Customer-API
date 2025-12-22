from fastapi import APIRouter, Depends
from auth_utils import get_current_user
from services.zoho_dashboard_service import zoho_dashboard_service
from services.zoho_contact_service import ZohoContactService


router = APIRouter(prefix="/zoho/dashboard", tags=["Zoho Dashboard"])

contact_service = ZohoContactService()

@router.get("/my")
def get_dashboard_summary(current_user = Depends(get_current_user)):
    contact = contact_service.get_contact_id_by_email(current_user.email)
    contact_id = contact.get("contact_id")

    return {
        "code": 0,
        "message": "success",
        "data": zoho_dashboard_service.build_dashboard_summary(contact_id)
    }
