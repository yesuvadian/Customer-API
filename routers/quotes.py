from typing import List
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status, HTTPException, Request
from auth_utils import get_current_user
import schemas
from services.quote_service import QuoteService
from services.zoho_auth_service import get_zoho_access_token
import zohoschemas
from services.sales_order_service import SalesOrderService

router = APIRouter(
    prefix="/zohoquotes",
    tags=["Quotes"],
    dependencies=[Depends(get_current_user)]
)

quote_service = QuoteService()
sales_order_service = SalesOrderService()

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

    return zohoschemas.QuoteResponse(
        message="Quote request submitted successfully",
        estimate_id=estimate["estimate_id"],
        estimate_number=estimate["estimate_number"],
        status=estimate["status"]
    )


@router.post(
    "/request_with_vendors",
    response_model=zohoschemas.QuoteResponse,
    status_code=status.HTTP_201_CREATED
)
def request_quote_with_vendors(
    payload: zohoschemas.RequestQuote,
    request: Request,
    current_user=Depends(get_current_user)
):
    """
    Request Quote:
    - Creates DRAFT quote in Zoho Books
    - Finds matching vendors from Vendor App
    """
    access_token = get_zoho_access_token()
    auth_header = request.headers.get("Authorization")

    try:
        # ✅ Step 1: Create draft quote
        estimate = quote_service.create_draft_quote(access_token, payload)

        # ✅ Step 2: Extract item IDs
        zoho_item_ids = [str(item.item_id) for item in payload.items]

        # ✅ Step 3: Fetch vendors from Vendor App
        matched_vendors_raw = quote_service.find_vendors_for_items(
            item_ids=zoho_item_ids,
            auth_header=auth_header
        )

        # ✅ Step 4: Transform vendors
        matched_vendors = [
            {
                "name": f"{v.get('firstname', '')} {v.get('lastname', '')}".strip(),
                "zoho_erp_id": v.get("zoho_erp_id")
            }
            for v in matched_vendors_raw
        ]

        # ✅ Step 5: Return response
        return zohoschemas.QuoteResponse(
            message="Quote request submitted successfully",
            estimate_id=estimate["estimate_id"],
            estimate_number=estimate.get("estimate_number", ""),
            status=estimate["status"],
            matched_vendors=matched_vendors
        )

    except HTTPException as e:
        raise e

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error while creating quote: {str(e)}"
        )   
    
    
@router.post("/assign_vendors/{estimate_id}")
def assign_vendors_to_quote(
    estimate_id: str,
    payload: zohoschemas.AssignVendors,
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()

    # ✅ Validate payload
    if not payload.vendors:
        raise HTTPException(
            status_code=400,
            detail="Vendors list cannot be empty"
        )

    try:
        # 🔥 Transform vendors for service layer
        transformed_vendors = []
        for v in payload.vendors:
            transformed_vendors.append({
                "name": f"{v.get('firstname', '')} {v.get('lastname', '')}".strip(),
                "zoho_erp_id": v.get("zoho_erp_id")
            })

        result = quote_service.assign_vendors_to_quote(
            access_token=access_token,
            estimate_id=estimate_id,
            vendors=transformed_vendors
        )

        return {
            "message": "Vendors assigned successfully",
            "estimate_id": estimate_id,
            "vendors": transformed_vendors,
            "zoho_response": result   # optional but useful for debugging
        }

    except HTTPException as e:
        raise e

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error assigning vendors: {str(e)}"
        )


@router.post(
    "/{estimate_id}/attachment",
    status_code=status.HTTP_201_CREATED
)
def upload_quote_attachment(
    estimate_id: str,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    """
    Upload attachment to a Zoho Books Estimate (Quote)
    """
    access_token = get_zoho_access_token()

    try:
        result = quote_service.upload_attachment(
            access_token=access_token,
            estimate_id=estimate_id,
            file=file,
            uploaded_by=current_user.email
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error uploading attachment: {str(e)}"
        )

    return {
        "message": "Attachment uploaded successfully",
        "file_name": file.filename,
        "estimate_id": estimate_id
    }
@router.post(
    "/enquiry",
    response_model=zohoschemas.QuoteResponse,
    status_code=status.HTTP_201_CREATED
)
def request_quote_with_attachments(
    contact_id: str = Form(...),
    enquiry_description: str = Form(...),
    notes: str | None = Form(None),
    files: List[UploadFile] = File([]),
    current_user=Depends(get_current_user)
):
    """
    Create enquiry draft quote + upload attachments
    """
    access_token = get_zoho_access_token()

    try:
        # 1️⃣ Create enquiry quote
        payload = zohoschemas.RequestQuoteEnquiry(
            contact_id=contact_id,
            enquiry_description=enquiry_description,
            notes=notes
        )

        estimate = quote_service.create_draft_quote_enquiry(
            access_token=access_token,
            payload=payload
        )

        estimate_id = estimate["estimate_id"]
      

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to submit quote enquiry: {str(e)}"
        )

    return zohoschemas.QuoteResponse(
        message="Quote enquiry submitted successfully",
        estimate_id=estimate_id,
        estimate_number=estimate.get("estimate_number", ""),
        status=estimate.get("status", "draft")
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

    return zohoschemas.QuoteResponse(
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
    return zohoschemas.QuoteResponse(
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
@router.put("/{estimate_id}/decline", response_model=zohoschemas.QuoteResponse)
def decline_quote(estimate_id: str, current_user=Depends(get_current_user)):

    access_token = get_zoho_access_token()

    try:
        result = quote_service.update_quote_status(
            access_token,
            estimate_id,
            "declined"
        )

        quote_service.add_comment(
            access_token=access_token,
            estimate_id=estimate_id,
            description="Quote declined by customer.",
            email=current_user.email
        )

        quote = quote_service.get_quote(
            access_token,
            estimate_id,
            current_user.email
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error declining quote: {str(e)}"
        )

    return zohoschemas.QuoteResponse(
        message="Quote declined successfully",
        estimate_id=quote["estimate_id"],
        estimate_number=quote["estimate_number"],
        status=quote["status"]
    )

@router.put("/{estimate_id}/accept")
def accept_quote(
    estimate_id: str,
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()

    try:
        result = quote_service.update_quote_status(
            access_token,
            estimate_id,
            "accepted"
        )

        salesorder = sales_order_service.create_salesorder_from_quote(
            access_token=access_token,
            estimate_id=estimate_id
        )

        quote_service.add_comment(
            access_token=access_token,
            estimate_id=estimate_id,
            description="Quote accepted by customer.",
            email=current_user.email
        )

    except HTTPException as e:
        raise e

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Accept quote failed: {str(e)}"
        )

    return {
        "message": "Quote accepted and Sales Order created",
        "estimate_id": result.get("estimate_id"),
        "salesorder_id": salesorder.get("salesorder_id"),
        "salesorder_number": salesorder.get("salesorder_number")
    }

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
@router.post("/{estimate_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(
    estimate_id: str,
    payload: zohoschemas.CommentCreate,
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()
    try:
        created = quote_service.add_comment(
            access_token=access_token,
            estimate_id=estimate_id,
            description=payload.description,
            email=current_user.email
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error adding comment: {str(e)}"
        )
    return created

# -----------------------------
# Update Comment
# -----------------------------
@router.put("/{estimate_id}/comments/{comment_id}", status_code=status.HTTP_200_OK)
def update_comment(
    estimate_id: str,
    comment_id: str,
    payload: zohoschemas.CommentUpdate,
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()
    try:
        updated = quote_service.update_comment(
            access_token=access_token,
            estimate_id=estimate_id,
            comment_id=comment_id,
            description=payload.description,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error updating comment: {str(e)}"
        )
    return updated
# -----------------------------
# Delete Comment
# -----------------------------
@router.delete("/{estimate_id}/comments/{comment_id}", status_code=status.HTTP_200_OK)
def delete_comment(
    estimate_id: str,
    comment_id: str,
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()
    try:
        result = quote_service.delete_comment(
            access_token=access_token,
            estimate_id=estimate_id,
            comment_id=comment_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error deleting comment: {str(e)}"
        )
    return {"message": "Comment deleted"}
@router.get("/{estimate_id}/comments", status_code=status.HTTP_200_OK)
def list_comments(estimate_id: str, current_user=Depends(get_current_user)):
    """
    List All Comments for a Quote (Customer)
    """
    access_token = get_zoho_access_token()
    try:
        comments = quote_service.get_comments(access_token, estimate_id)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching comments: {str(e)}"
        )
    
    return {"comments": comments}
