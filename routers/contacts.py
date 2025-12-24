from fastapi import APIRouter, Depends, status, HTTPException
from auth_utils import get_current_user
from services.contact_service import ContactService
from services.zoho_auth_service import get_zoho_access_token
import schemas
import zohoschemas

router = APIRouter(
    prefix="/zohocontacts",
    tags=["Contacts"],
    # dependencies=[Depends(get_current_user)]
)

contact_service = ContactService()


@router.post("/", response_model=zohoschemas.ContactResponse, status_code=status.HTTP_201_CREATED)
def create_contact(payload: zohoschemas.CreateContact):
    """
    Create Zoho Contact:
    - Creates a new contact in Zoho Books with portal disabled
    """
    access_token = get_zoho_access_token()
    try:
        contact = contact_service.create_contact(access_token, payload)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating contact: {str(e)}")

    return zohoschemas.ContactResponse(
        message="Contact created successfully",
        contact_id=contact["contact_id"],
        contact_name=contact["contact_name"],
        company_name=contact.get("company_name", ""),
        is_portal_enabled=contact.get("is_portal_enabled", False)
    )