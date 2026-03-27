from fastapi import APIRouter, Depends, HTTPException, status
from auth_utils import get_current_user
from services.bill_service import BillService
import uuid

router = APIRouter(
    prefix="/localbills",
    tags=["Local Bills"],
    dependencies=[Depends(get_current_user)]
)

bill_service = BillService()


@router.get("/my-bills", status_code=status.HTTP_200_OK)
def list_my_bills(current_user=Depends(get_current_user)):
    """
    List bills for the logged-in customer from local database
    """
    try:
        contact_id = current_user.email
        bills = bill_service.get_bills_for_customer(contact_id)
        return {"bills": bills}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching bills: {str(e)}")


@router.get("/{identifier}", status_code=status.HTTP_200_OK)
def get_bill(identifier: str, current_user=Depends(get_current_user)):
    """
    Get bill by either UUID or bill number
    """
    try:
        contact_id = current_user.email
        
        # Check if identifier is a valid UUID
        try:
            bill_uuid = uuid.UUID(identifier)
            # It's a UUID, search by ID
            bill = bill_service.get_bill(str(bill_uuid), contact_id)
        except ValueError:
            # Not a UUID, treat as bill number
            bills = bill_service.get_bills_for_customer(contact_id)
            bill = None
            for b in bills:
                if b.get("bill_number") == identifier:
                    bill = b
                    break
        
        if not bill:
            raise HTTPException(status_code=404, detail="Bill not found")
        
        return bill
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching bill: {str(e)}")