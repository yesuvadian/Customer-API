from fastapi import APIRouter, Depends, status, HTTPException,Response
from auth_utils import get_current_user
import schemas
from services.payment_service import PaymentService
from services.zoho_auth_service import get_zoho_access_token
import zohoschemas

router = APIRouter(
    prefix="/zohopayments",
    tags=["Customer Payments"],
    dependencies=[Depends(get_current_user)]
)

payment_service = PaymentService()


@router.post("/create", response_model=zohoschemas.PaymentResponse, status_code=status.HTTP_201_CREATED)
def create_payment(payload: zohoschemas.RequestPayment, current_user=Depends(get_current_user)):
    """
    Create Customer Payment:
    - Records a payment against an invoice in Zoho Books
    """
    access_token = get_zoho_access_token()
    try:
        payment = payment_service.create_payment(access_token, payload)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error while creating payment: {str(e)}")

    return schemas.PaymentResponse(
        message="Payment created successfully",
        payment_id=payment["payment_id"],
        payment_number=payment["payment_number"],
        status=payment["status"]
    )


@router.get("/my", status_code=status.HTTP_200_OK)
def list_my_payments(current_user=Depends(get_current_user)):
    """
    List Payments for the logged-in customer.
    """
    access_token = get_zoho_access_token()
    try:
        payments = payment_service.list_payments_for_customer(access_token, current_user.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching payments: {str(e)}")

    return {"payments": payments}


@router.get("/{payment_id}", status_code=status.HTTP_200_OK)
def get_payment(payment_id: str, current_user=Depends(get_current_user)):
    """
    Get Payment Details
    """
    access_token = get_zoho_access_token()
    try:
        payment = payment_service.get_payment(
            access_token=access_token,
            payment_id=payment_id,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching payment details: {str(e)}")

    return payment


@router.put("/review/{payment_id}", response_model=zohoschemas.PaymentResponse, status_code=status.HTTP_200_OK)
def review_payment(payment_id: str, payload: zohoschemas.ReviewPayment, current_user=Depends(get_current_user)):
    """
    ERP Review Payment:
    - Approve or reject recorded payment
    - Add comments or adjustments
    """
    access_token = get_zoho_access_token()
    try:
        updated = payment_service.review_payment(
            access_token=access_token,
            payment_id=payment_id,
            payload=payload,
            reviewer_id=current_user.id,
            contact_id=payload.contact_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reviewing payment: {str(e)}")

    return zohoschemas.PaymentResponse(
        message="Payment reviewed successfully",
        payment_id=updated["payment_id"],
        payment_number=updated["payment_number"],
        status=updated["status"]
    )


@router.put("/approve/{payment_id}", response_model=zohoschemas.PaymentResponse, status_code=status.HTTP_200_OK)
def approve_payment(payment_id: str, payload: zohoschemas.ApprovePayment, current_user=Depends(get_current_user)):
    """
    Customer Approval:
    - Approve or reject reviewed payment
    """
    access_token = get_zoho_access_token()
    try:
        result = payment_service.customer_approve_payment(
            access_token=access_token,
            payment_id=payment_id,
            payload=payload,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error approving payment: {str(e)}")

    return zohoschemas.PaymentResponse(
        message="Customer response recorded",
        payment_id=result["payment_id"],
        payment_number=result["payment_number"],
        status=result["status"]
    )
@router.get("/payment/{payment_id}/pdf", status_code=status.HTTP_200_OK)
def get_payment_pdf(payment_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()
    try:
        pdf_bytes = payment_service.get_payment_pdf(access_token, payment_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching payment PDF: {str(e)}")
    return Response(content=pdf_bytes, media_type="application/pdf")
