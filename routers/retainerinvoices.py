from fastapi import APIRouter, Depends, Response, status, HTTPException
from auth_utils import get_current_user
import schemas
from services.retainer_invoice_service import RetainerInvoiceService
from services.zoho_auth_service import get_zoho_access_token
import zohoschemas

router = APIRouter(
    prefix="/zohoretainerinvoices",
    tags=["Retainer Invoices"],
    dependencies=[Depends(get_current_user)]
)

retainer_invoice_service = RetainerInvoiceService()


@router.post("/create", response_model=zohoschemas.RetainerInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_retainer_invoice(payload: zohoschemas.RequestRetainerInvoice, current_user=Depends(get_current_user)):
    """
    Create Retainer Invoice:
    - Creates a new retainer invoice in Zoho Books
    """
    access_token = get_zoho_access_token()
    try:
        invoice = retainer_invoice_service.create_retainer_invoice(access_token, payload)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error while creating retainer invoice: {str(e)}")

    return zohoschemas.RetainerInvoiceResponse(
        message="Retainer invoice created successfully",
        retainerinvoice_id=invoice["retainerinvoice_id"],
        retainerinvoice_number=invoice["retainerinvoice_number"],
        status=invoice["status"]
    )


@router.get("/my", status_code=status.HTTP_200_OK)
def list_my_retainer_invoices(current_user=Depends(get_current_user)):
    """
    List Retainer Invoices for the logged-in customer.
    """
    access_token = get_zoho_access_token()
    try:
        invoices = retainer_invoice_service.list_retainer_invoices_for_customer(access_token, current_user.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching retainer invoices: {str(e)}")

    return {"retainer_invoices": invoices}


@router.put("/review/{retainerinvoice_id}", response_model=zohoschemas.RetainerInvoiceResponse, status_code=status.HTTP_200_OK)
def review_retainer_invoice(retainerinvoice_id: str, payload: zohoschemas.ReviewRetainerInvoice, current_user=Depends(get_current_user)):
    """
    ERP Review Retainer Invoice:
    - Approve or reject draft retainer invoice
    - Add comments or adjustments
    """
    access_token = get_zoho_access_token()
    try:
        updated = retainer_invoice_service.review_retainer_invoice(
            access_token=access_token,
            retainerinvoice_id=retainerinvoice_id,
            payload=payload,
            reviewer_id=current_user.id,
            contact_id=payload.contact_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reviewing retainer invoice: {str(e)}")

    return zohoschemas.RetainerInvoiceResponse(
        message="Retainer invoice reviewed successfully",
        retainerinvoice_id=updated["retainerinvoice_id"],
        retainerinvoice_number=updated["retainerinvoice_number"],
        status=updated["status"]
    )


@router.put("/approve/{retainerinvoice_id}", response_model=zohoschemas.RetainerInvoiceResponse, status_code=status.HTTP_200_OK)
def approve_retainer_invoice(retainerinvoice_id: str, payload: zohoschemas.ApproveRetainerInvoice, current_user=Depends(get_current_user)):
    """
    Customer Approval:
    - Approve or reject reviewed retainer invoice
    """
    access_token = get_zoho_access_token()
    try:
        result = retainer_invoice_service.customer_approve_retainer_invoice(
            access_token=access_token,
            retainerinvoice_id=retainerinvoice_id,
            payload=payload,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error approving retainer invoice: {str(e)}")

    return zohoschemas.RetainerInvoiceResponse(
        message="Customer response recorded",
        retainerinvoice_id=result["retainerinvoice_id"],
        retainerinvoice_number=result["retainerinvoice_number"],
        status=result["status"]
    )


@router.get("/{retainerinvoice_id}", status_code=status.HTTP_200_OK)
def get_retainer_invoice(retainerinvoice_id: str, current_user=Depends(get_current_user)):
    """
    Get Retainer Invoice Details
    """
    access_token = get_zoho_access_token()
    try:
        invoice = retainer_invoice_service.get_retainer_invoice(
            access_token=access_token,
            retainerinvoice_id=retainerinvoice_id,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching retainer invoice details: {str(e)}")

    return invoice

@router.get("/retainerinvoice/{retainerinvoice_id}/pdf", status_code=status.HTTP_200_OK)
def get_retainer_invoice_pdf(retainerinvoice_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()
    try:
        pdf_bytes = retainer_invoice_service.get_retainer_invoice_pdf(access_token, retainerinvoice_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching retainer invoice PDF: {str(e)}")
    return Response(content=pdf_bytes, media_type="application/pdf")
# -----------------------------
# LIST COMMENTS
# -----------------------------
@router.get("/{retainerinvoice_id}/comments", status_code=status.HTTP_200_OK)
def list_retainer_invoice_comments(retainerinvoice_id: str, current_user=Depends(get_current_user)):
    """
    Get list of comments for a Retainer Invoice
    """
    access_token = get_zoho_access_token()
    try:
        comments = retainer_invoice_service.list_comments(
            access_token,
            retainerinvoice_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching comments: {str(e)}")

    return {"comments": comments}


# -----------------------------
# ADD COMMENT
# -----------------------------
@router.post("/{retainerinvoice_id}/comments", status_code=status.HTTP_201_CREATED)
def add_retainer_invoice_comment(
    retainerinvoice_id: str,
    payload: dict,
    current_user=Depends(get_current_user)
):
    """
    Add a comment to Retainer Invoice
    """
    access_token = get_zoho_access_token()

    # Enrich payload with customer context if needed
    payload.setdefault(
        "message",
        f"Comment by {current_user.email}"
    )

    try:
        comment = retainer_invoice_service.add_comment(
            access_token,
            retainerinvoice_id,
            payload
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding comment: {str(e)}")

    return {
        "message": "Comment added successfully",
        "comment": comment
    }


# -----------------------------
# UPDATE COMMENT
# -----------------------------
@router.put("/{retainerinvoice_id}/comments/{comment_id}", status_code=status.HTTP_200_OK)
def update_retainer_invoice_comment(
    retainerinvoice_id: str,
    comment_id: str,
    payload: dict,
    current_user=Depends(get_current_user)
):
    """
    Update an existing comment in a Retainer Invoice
    """
    access_token = get_zoho_access_token()

    try:
        updated = retainer_invoice_service.update_comment(
            access_token,
            retainerinvoice_id,
            comment_id,
            payload
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating comment: {str(e)}")

    return {
        "message": "Comment updated successfully",
        "comment": updated
    }


# -----------------------------
# DELETE COMMENT
# -----------------------------
@router.delete("/{retainerinvoice_id}/comments/{comment_id}", status_code=status.HTTP_200_OK)
def delete_retainer_invoice_comment(
    retainerinvoice_id: str,
    comment_id: str,
    current_user=Depends(get_current_user)
):
    """
    Delete a comment from Retainer Invoice
    """
    access_token = get_zoho_access_token()

    try:
        deleted = retainer_invoice_service.delete_comment(
            access_token,
            retainerinvoice_id,
            comment_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting comment: {str(e)}")

    return {"message": "Comment deleted successfully"}
