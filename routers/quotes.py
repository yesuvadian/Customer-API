from fastapi import APIRouter, status, HTTPException
from auth_utils import get_current_user
import schemas
from services.quote_service import QuoteService
from services.zoho_auth_service import get_zoho_access_token

router = APIRouter(
    prefix="/zohoquotes",
    tags=["Quotes"],
)

quote_service = QuoteService()


@router.post("/request", status_code=status.HTTP_201_CREATED)
def request_quote(payload: schemas.RequestQuote):
    """
    Request Quote:
    - Creates DRAFT quote in Zoho Books
    - Sales team completes & sends
    """

    access_token = get_zoho_access_token()

    try:
        estimate = quote_service.create_draft_quote(access_token, payload)
    except HTTPException as e:
        # bubble up service errors
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error while creating quote: {str(e)}"
        )
        
    return {
        "message": "Quote request submitted successfully",
        "estimate_id": estimate["estimate_id"],
        "estimate_number": estimate["estimate_number"],
        "status": estimate["status"]
    }