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
