from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
import zohoschemas
from database import get_db
from auth_utils import get_current_user
from services.contact_service import ContactService
from typing import List

from services.zoho_auth_service import get_zoho_access_token

# We reuse your existing UserService for email/phone checks
from services.user_service import UserService 

router = APIRouter(prefix="/zoho-register", tags=["zoho_registration"])
user_service_instance = UserService()
# zoho_service = ContactService()
contact_service = ContactService()

# ------------------------------------------------------------------
# STEP 0: SHARED VALIDATION (Reused from register.py)
# ------------------------------------------------------------------

@router.get("/check-email")
def check_zoho_email(email: str = Query(...), db: Session = Depends(get_db)):
    """Check if email is already taken before starting Zoho registration."""
    exists = user_service_instance.is_email_exists(db, email)
    return {"exists": exists}

# ------------------------------------------------------------------
# THE 3-STEP FLOW & FINAL COMPLETION
# ------------------------------------------------------------------

@router.post("/zohocontacts", response_model=zohoschemas.ContactResponse, status_code=status.HTTP_201_CREATED)
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