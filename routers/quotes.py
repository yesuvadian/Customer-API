from fastapi import APIRouter, Depends, Response, status, HTTPException
from auth_utils import get_current_user
import schemas
from services.quote_service import QuoteService
from services.zoho_auth_service import get_zoho_access_token
import zohoschemas

router = APIRouter(
    prefix="/zohoquotes",
    tags=["Quotes"],
    dependencies=[Depends(get_current_user)]
)

quote_service = QuoteService()

# -----------------------------
# Request Quote (Customer)
# -----------------------------
@router.post("/request", response_model=zohoschemas.QuoteResponse, status_code=status.HTTP_201_CREATED)
def request_quote(payload: zohoschemas.RequestQuote, current_user=Depends(get_current_user)):
    """
    Request Quote:
    - Creates DRAFT quote in Zoho Books
    - Sales team completes & sends
    """
    access_token = get_zoho_access_token()

    try:
        estimate = quote_service.create_draft_quote(access_token, payload)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error while creating quote: {str(e)}"
        )

    return schemas.QuoteResponse(
        message="Quote request submitted successfully",
        estimate_id=estimate["estimate_id"],
        estimate_number=estimate["estimate_number"],
        status=estimate["status"]
    )

# -----------------------------
# List Quotes (Customer)
# -----------------------------
@router.get("/my", status_code=status.HTTP_200_OK)
def list_my_quotes(current_user=Depends(get_current_user)):
    """
    List Quotes for the logged-in customer.
    """
    access_token = get_zoho_access_token()
    try:
        quotes = quote_service.list_quotes_for_customer(access_token, current_user.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching quotes: {str(e)}")

    return {"quotes": quotes}

# -----------------------------
# ERP Review Quote
# -----------------------------
@router.put("/review/{estimate_id}", response_model=zohoschemas.QuoteResponse, status_code=status.HTTP_200_OK)
def review_quote(estimate_id: str, payload: zohoschemas.ReviewQuote, current_user=Depends(get_current_user)):
    """
    ERP Review Quote:
    - Approve or reject draft quote
    - Add comments or adjustments
    """
    access_token = get_zoho_access_token()
    try:
        updated = quote_service.review_quote(
            access_token,
            estimate_id,
            payload,
            reviewer_id=current_user.email,
            contact_id=payload.contact_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reviewing quote: {str(e)}")

    return schemas.QuoteResponse(
        message="Quote reviewed successfully",
        estimate_id=updated["estimate_id"],
        estimate_number=updated["estimate_number"],
        status=updated["status"]
    )

# -----------------------------
# Customer Approval
# -----------------------------
@router.put("/approve/{estimate_id}", response_model=zohoschemas.QuoteResponse, status_code=status.HTTP_200_OK)
def approve_quote(estimate_id: str, payload: zohoschemas.ApproveQuote, current_user=Depends(get_current_user)):
    """
    Customer Approval:
    - Approve or reject reviewed quote
    """
    access_token = get_zoho_access_token()
    try:
        result = quote_service.customer_approve_quote(
            access_token,
            estimate_id,
            payload,
            customer_id=current_user.email
        )   
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error in customer approval: {str(e)}")    
    return schemas.QuoteResponse(
        message="Quote approval recorded successfully", 
        estimate_id=result["estimate_id"],
        estimate_number=result["estimate_number"],  
        status=result["status"]
    )       

@router.get("/{estimate_id}", status_code=status.HTTP_200_OK)
def get_quote(estimate_id: str, current_user=Depends(get_current_user)):
        """
        Get Quote Details
        """
        access_token = get_zoho_access_token()
        try:
            quote = quote_service.get_quote(
                access_token=access_token,
                estimate_id=estimate_id,
                contact_id=current_user.email
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error fetching quote details: {str(e)}")

        return quote
@router.put("/{estimate_id}/decline", response_model=zohoschemas.QuoteResponse, status_code=status.HTTP_200_OK)
def decline_quote(estimate_id: str, current_user=Depends(get_current_user)):
    """
    Decline Quote:
    - Marks a Zoho Books estimate as declined
    """
    access_token = get_zoho_access_token()
    try:
        result = quote_service.update_quote_status(access_token, estimate_id, "declined")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error declining quote: {str(e)}")

    return schemas.QuoteResponse(
        message="Quote declined successfully",
        estimate_id=result["estimate_id"],
        estimate_number=result["estimate_number"],
        status=result["status"]
    )


@router.put("/{estimate_id}/accept", response_model=zohoschemas.QuoteResponse, status_code=status.HTTP_200_OK)
def accept_quote(estimate_id: str, current_user=Depends(get_current_user)):
    """
    Accept Quote:
    - Marks a Zoho Books estimate as accepted
    """
    access_token = get_zoho_access_token()
    try:
        result = quote_service.update_quote_status(access_token, estimate_id, "accepted")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error accepting quote: {str(e)}")

    return schemas.QuoteResponse(
        message="Quote accepted successfully",
        estimate_id=result["estimate_id"],
        estimate_number=result["estimate_number"],
        status=result["status"]
    )
@router.get("/{estimate_id}/pdf", status_code=status.HTTP_200_OK)
def get_quote_pdf(estimate_id: str, current_user=Depends(get_current_user)):
    """
    Get Quote (Estimate) PDF:
    - Returns the PDF view of a Zoho Books estimate
    """
    access_token = get_zoho_access_token()
    try:
        pdf_bytes = quote_service.get_quote_pdf(access_token, estimate_id)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching quote PDF: {str(e)}")

    # Return raw PDF stream with correct headers
    return Response(content=pdf_bytes, media_type="application/pdf")
