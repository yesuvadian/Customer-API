from fastapi import APIRouter, Depends, Response, status, HTTPException, Body
from auth_utils import get_current_user
import schemas
from services.invoice_services import InvoiceService
from services.zoho_auth_service import get_zoho_access_token
import zohoschemas

router = APIRouter(
    prefix="/zohoinvoices",
    tags=["Invoices"],
    dependencies=[Depends(get_current_user)]
)

invoice_service = InvoiceService()


@router.post("/create", response_model=zohoschemas.InvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_invoice(payload: zohoschemas.RequestInvoice, current_user=Depends(get_current_user)):
    """
    Create Invoice:
    - Creates a new invoice in Zoho Books
    """
    access_token = get_zoho_access_token()
    try:
        invoice = invoice_service.create_invoice(access_token, payload)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error while creating invoice: {str(e)}")

    return zohoschemas.InvoiceResponse(
        message="Invoice created successfully",
        invoice_id=invoice["invoice_id"],
        invoice_number=invoice["invoice_number"],
        status=invoice["status"]
    )


@router.get("/my", status_code=status.HTTP_200_OK)
def list_my_invoices(current_user=Depends(get_current_user)):
    """
    List Invoices for the logged-in customer.
    """
    access_token = get_zoho_access_token()
    try:
        invoices = invoice_service.list_invoices_for_customer(access_token, current_user.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching invoices: {str(e)}")

    return {"invoices": invoices}


@router.put("/review/{invoice_id}", response_model=zohoschemas.InvoiceResponse, status_code=status.HTTP_200_OK)
def review_invoice(invoice_id: str, payload: zohoschemas.ReviewInvoice, current_user=Depends(get_current_user)):
    """
    ERP Review Invoice:
    - Approve or reject draft invoice
    - Add comments or adjustments
    """
    access_token = get_zoho_access_token()
    try:
        updated = invoice_service.review_invoice(
            access_token=access_token,
            invoice_id=invoice_id,
            payload=payload,
            reviewer_id=current_user.id,
            contact_id=payload.contact_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reviewing invoice: {str(e)}")

    return zohoschemas.InvoiceResponse(
        message="Invoice reviewed successfully",
        invoice_id=updated["invoice_id"],
        invoice_number=updated["invoice_number"],
        status=updated["status"]
    )


@router.put("/approve/{invoice_id}", response_model=zohoschemas.InvoiceResponse, status_code=status.HTTP_200_OK)
def approve_invoice(invoice_id: str, payload: zohoschemas.ApproveInvoice, current_user=Depends(get_current_user)):
    """
    Customer Approval:
    - Approve or reject reviewed invoice
    """
    access_token = get_zoho_access_token()
    try:
        result = invoice_service.customer_approve_invoice(
            access_token=access_token,
            invoice_id=invoice_id,
            payload=payload,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error approving invoice: {str(e)}")

    return zohoschemas.InvoiceResponse(
        message="Customer response recorded",
        invoice_id=result["invoice_id"],
        invoice_number=result["invoice_number"],
        status=result["status"]
    )


@router.get("/{invoice_id}", status_code=status.HTTP_200_OK)
def get_invoice(invoice_id: str, current_user=Depends(get_current_user)):
    """
    Get Invoice Details
    """
    access_token = get_zoho_access_token()
    try:
        invoice = invoice_service.get_invoice(
            access_token=access_token,
            invoice_id=invoice_id,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching invoice details: {str(e)}")

    return invoice
@router.get("/{invoice_id}/pdf", status_code=status.HTTP_200_OK)
def get_invoice_pdf(invoice_id: str, current_user=Depends(get_current_user)):
    """
    Get Invoice PDF:
    - Returns the PDF view of a Zoho Books invoice
    """
    access_token = get_zoho_access_token()
    try:
        pdf_bytes = invoice_service.get_invoice_pdf(access_token, invoice_id)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching invoice PDF: {str(e)}")

    # Return raw PDF stream with correct headers
    return Response(content=pdf_bytes, media_type="application/pdf")
# =====================================================
# GET ALL COMMENTS FOR INVOICE
# =====================================================
@router.get("/{invoice_id}/comments", status_code=status.HTTP_200_OK)
def get_invoice_comments(invoice_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()
    try:
        comments = invoice_service.get_invoice_comments(access_token, invoice_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching invoice comments: {str(e)}")
    return {"comments": comments}


# =====================================================
# ADD NEW COMMENT
# =====================================================
@router.post("/{invoice_id}/comments", status_code=status.HTTP_201_CREATED)
def add_invoice_comment(
    invoice_id: str,
    payload: dict = Body(...),
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()
    try:
        created = invoice_service.add_invoice_comment(access_token, invoice_id, payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding comment: {str(e)}")
    return {"message": "Comment added", "comment": created}


# =====================================================
# UPDATE A COMMENT
# =====================================================
@router.put("/{invoice_id}/comments/{comment_id}", status_code=status.HTTP_200_OK)
def update_invoice_comment(
    invoice_id: str,
    comment_id: str,
    payload: dict = Body(...),
    current_user=Depends(get_current_user),
):
    access_token = get_zoho_access_token()
    try:
        updated = invoice_service.update_invoice_comment(
            access_token, invoice_id, comment_id, payload
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating comment: {str(e)}")
    return {"message": "Comment updated", "comment": updated}


# =====================================================
# DELETE A COMMENT
# =====================================================
@router.delete("/{invoice_id}/comments/{comment_id}", status_code=status.HTTP_200_OK)
def delete_invoice_comment(invoice_id: str, comment_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()
    try:
        invoice_service.delete_invoice_comment(access_token, invoice_id, comment_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting comment: {str(e)}")
    return {"message": "Comment deleted"}