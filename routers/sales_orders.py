from fastapi import APIRouter, Depends, Response, status, HTTPException
from auth_utils import get_current_user
import schemas
from services.sales_order_service import SalesOrderService
from services.zoho_auth_service import get_zoho_access_token
import zohoschemas

router = APIRouter(
    prefix="/zohoorders",
    tags=["Sales Orders"],
    dependencies=[Depends(get_current_user)]
)

sales_order_service = SalesOrderService()


@router.post("/request", response_model=zohoschemas.SalesOrderResponse, status_code=status.HTTP_201_CREATED)
def request_sales_order(payload: zohoschemas.RequestSalesOrder, current_user=Depends(get_current_user)):
    """
    Request Sales Order:
    - Creates DRAFT sales order in Zoho Books
    - ERP/Sales team completes & sends
    """
    access_token = get_zoho_access_token()
    try:
        order = sales_order_service.create_draft_order(access_token, payload)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error while creating sales order: {str(e)}")

    return zohoschemas.SalesOrderResponse(
        message="Sales order request submitted successfully",
        salesorder_id=order["salesorder_id"],
        salesorder_number=order["salesorder_number"],
        status=order["status"]
    )


@router.get("/my", status_code=status.HTTP_200_OK)
def list_my_orders(current_user=Depends(get_current_user)):
    """
    List Sales Orders for the logged-in customer.
    """
    access_token = get_zoho_access_token()
    try:
        orders = sales_order_service.list_orders_for_customer(access_token, current_user.email)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching sales orders: {str(e)}")

    return {"orders": orders}


@router.put("/review/{salesorder_id}", response_model=zohoschemas.SalesOrderResponse, status_code=status.HTTP_200_OK)
def review_order(salesorder_id: str, payload: zohoschemas.ReviewSalesOrder, current_user=Depends(get_current_user)):
    """
    ERP Review Sales Order:
    - Approve or reject draft order
    - Add comments or adjustments
    """
    access_token = get_zoho_access_token()
    try:
        updated = sales_order_service.review_order(
            access_token=access_token,
            salesorder_id=salesorder_id,
            payload=payload,
            reviewer_id=current_user.email,
            contact_id=payload.contact_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reviewing sales order: {str(e)}")

    return schemas.SalesOrderResponse(
        message="Sales order reviewed successfully",
        salesorder_id=updated["salesorder_id"],
        salesorder_number=updated["salesorder_number"],
        status=updated["status"]
    )


@router.put("/approve/{salesorder_id}", response_model=zohoschemas.SalesOrderResponse, status_code=status.HTTP_200_OK)
def approve_order(salesorder_id: str, payload: zohoschemas.ApproveSalesOrder, current_user=Depends(get_current_user)):
    """
    Customer Approval:
    - Approve or reject reviewed sales order
    """
    access_token = get_zoho_access_token()
    try:
        result = sales_order_service.customer_approve_order(
            access_token=access_token,
            salesorder_id=salesorder_id,
            payload=payload,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error approving sales order: {str(e)}")

    return schemas.SalesOrderResponse(
        message="Customer response recorded",
        salesorder_id=result["salesorder_id"],
        salesorder_number=result["salesorder_number"],
        status=result["status"]
    )


@router.get("/{salesorder_id}", status_code=status.HTTP_200_OK)
def get_order(salesorder_id: str, current_user=Depends(get_current_user)):
    """
    Get Sales Order Details
    """
    access_token = get_zoho_access_token()
    try:
        order = sales_order_service.get_order(
            access_token=access_token,
            salesorder_id=salesorder_id,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching sales order details: {str(e)}")

    return order


# ------------------------------------
# COMMENTS: ADD
# ------------------------------------
@router.post("/{salesorder_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(salesorder_id: str, payload: dict, current_user=Depends(get_current_user)):
    """
    Add a comment to a Sales Order
    """
    access_token = get_zoho_access_token()
    
    description = payload.get("description", "")
    show_to_client = payload.get("show_comment_to_clients", True)
    
    try:
        result = sales_order_service.add_comment(
            access_token=access_token,
            salesorder_id=salesorder_id,
            description=description,
            show_to_client=show_to_client
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding comment: {str(e)}")

    return result
# ------------------------------------
# COMMENTS: UPDATE
# ------------------------------------
@router.put("/{salesorder_id}/comments/{comment_id}", status_code=status.HTTP_200_OK)
def update_comment(salesorder_id: str, comment_id: str, payload: dict, current_user=Depends(get_current_user)):
    """
    Update an existing comment
    """
    access_token = get_zoho_access_token()
    desc = payload.get("description", "")

    try:
        result = sales_order_service.update_comment(
            access_token=access_token,
            salesorder_id=salesorder_id,
            comment_id=comment_id,
            description=desc
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating comment: {str(e)}")

    return result
# ------------------------------------
# COMMENTS: DELETE
# ------------------------------------
@router.delete("/{salesorder_id}/comments/{comment_id}", status_code=status.HTTP_200_OK)
def delete_comment(salesorder_id: str, comment_id: str, current_user=Depends(get_current_user)):
    """
    Delete a comment from Sales Order
    """
    access_token = get_zoho_access_token()

    try:
        result = sales_order_service.delete_comment(
            access_token=access_token,
            salesorder_id=salesorder_id,
            comment_id=comment_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting comment: {str(e)}")

    return result
# ------------------------------------
# COMMENTS: LIST
# ------------------------------------
@router.get("/{salesorder_id}/comments", status_code=status.HTTP_200_OK)
def get_comments(salesorder_id: str, current_user=Depends(get_current_user)):
    """
    Get all comments for a Sales Order
    """
    access_token = get_zoho_access_token()

    try:
        comments = sales_order_service.get_comments(
            access_token=access_token,
            salesorder_id=salesorder_id
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching comments: {str(e)}")

    return {"comments": comments}
@router.get("/{salesorder_id}/pdf", status_code=status.HTTP_200_OK)
def get_order_pdf(salesorder_id: str, current_user=Depends(get_current_user)):
    """
    Get Sales Order PDF
    """
    access_token = get_zoho_access_token()
    try:
        pdf_bytes = sales_order_service.get_order_pdf(
            access_token=access_token,
            salesorder_id=salesorder_id
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching sales order PDF: {str(e)}"
        )

    return Response(content=pdf_bytes, media_type="application/pdf")
