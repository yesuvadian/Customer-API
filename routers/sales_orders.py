from fastapi import APIRouter, Depends, Response, status, HTTPException
from auth_utils import get_current_user
import schemas
from services.sales_order_service import SalesOrderService
from services.zoho_auth_service import get_zoho_access_token
import zohoschemas
from fastapi import UploadFile, File, Form

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

# =====================================================
# UPLOAD GRN (Sales Order)
# =====================================================
@router.post("/{salesorder_id}/grn", status_code=status.HTTP_201_CREATED)
def upload_grn(
    salesorder_id: str,
    cf_grn_number: str = Form(...),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()

    try:
        result = sales_order_service.upload_grn_attachment(
            access_token=access_token,
            salesorder_id=salesorder_id,
            cf_grn_number=cf_grn_number,
            file=file,
            uploaded_by=current_user.email
        )
    except HTTPException as e:
        raise e  # preserve real status code
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error uploading GRN: {str(e)}"
        )


    return {
        "message": "GRN uploaded successfully",
        "salesorder_id": salesorder_id,
        "cf_grn_number": cf_grn_number,
        "file_name": file.filename
    }

# =====================================================
# UPLOAD PO (Sales Order)
# =====================================================
@router.post("/{salesorder_id}/po", status_code=status.HTTP_201_CREATED)
def upload_po(
    salesorder_id: str,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()

    result = sales_order_service.upload_po_attachment(
        access_token=access_token,
        salesorder_id=salesorder_id,
        file=file,
        uploaded_by=current_user.email
    )

    return {
        "message": "PO uploaded successfully",
        "salesorder_id": salesorder_id,
        "file_name": file.filename
    }

@router.put("/{salesorder_id}/po", status_code=status.HTTP_200_OK)
def update_po(
    salesorder_id: str,
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()

    try:
        sales_order_service.upload_po_attachment(
            access_token=access_token,
            salesorder_id=salesorder_id,
            file=file,
            uploaded_by=current_user.email
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error updating PO: {str(e)}"
        )

    return {
        "message": "PO updated successfully",
        "salesorder_id": salesorder_id,
        "file_name": file.filename
    }

@router.put("/{salesorder_id}/grn", status_code=status.HTTP_200_OK)
def update_grn(
    salesorder_id: str,
    cf_grn_number: str = Form(...),
    file: UploadFile = File(...),
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()

    try:
        sales_order_service.update_grn_attachment(
            access_token=access_token,
            salesorder_id=salesorder_id,
            cf_grn_number=cf_grn_number,
            file=file,
            uploaded_by=current_user.email
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error updating GRN: {str(e)}"
        )

    return {
        "message": "GRN updated successfully",
        "salesorder_id": salesorder_id,
        "cf_grn_number": cf_grn_number,
        "file_name": file.filename
    }

@router.get("/{salesorder_id}/po/pdf")
def get_po_pdf(salesorder_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()

    pdf_bytes = sales_order_service.get_attachment_pdf_by_prefix(
        access_token,
        salesorder_id,
        prefix="_po"
    )

    return Response(content=pdf_bytes, media_type="application/pdf")


@router.get("/{salesorder_id}/grn/pdf")
def get_grn_pdf(salesorder_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()

    pdf_bytes = sales_order_service.get_attachment_pdf_by_prefix(
        access_token,
        salesorder_id,
        prefix="_grn"
    )

    return Response(content=pdf_bytes, media_type="application/pdf")

# =====================================================
# GET GRN DATA (Number + File)
# =====================================================
@router.get("/{salesorder_id}/grn", status_code=status.HTTP_200_OK)
def get_grn_data(salesorder_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()

    try:
        grn_data = sales_order_service.get_grn_data(
            access_token=access_token,
            salesorder_id=salesorder_id,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching GRN: {str(e)}")

    return grn_data

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

@router.get("/{salesorder_id}/attachments", status_code=status.HTTP_200_OK)
def list_attachments(salesorder_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()

    try:
        order = sales_order_service.get_order(
            access_token=access_token,
            salesorder_id=salesorder_id,
            contact_id=current_user.email
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    documents = order.get("documents", [])

    attachments = [
        {
            "attachment_id": doc.get("document_id"),
            "file_name": doc.get("file_name"),
            "file_type": doc.get("file_type"),
            "file_size": doc.get("file_size"),
            "uploaded_on": doc.get("uploaded_on"),
        }
        for doc in documents
    ]

    return {"attachments": attachments}

@router.get("/{salesorder_id}/attachments/{attachment_id}")
def download_attachment(
    salesorder_id: str,
    attachment_id: str,
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()

    file_bytes = sales_order_service.download_attachment(
        access_token,
        salesorder_id,
        attachment_id
    )

    return Response(content=file_bytes, media_type="application/octet-stream")

@router.delete("/{salesorder_id}/po", status_code=status.HTTP_200_OK)
def delete_po(salesorder_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()

    try:
        sales_order_service.delete_attachment_by_prefix(
            access_token=access_token,
            salesorder_id=salesorder_id,
            prefix="_po"
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting PO: {str(e)}"
        )

    return {"message": "PO deleted successfully"}

@router.delete("/{salesorder_id}/grn", status_code=status.HTTP_200_OK)
def delete_grn(salesorder_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()

    try:
        sales_order_service.delete_attachment_by_prefix(
            access_token=access_token,
            salesorder_id=salesorder_id,
            prefix="_grn"
        )

        # Optional: also clear GRN number
        sales_order_service.update_grn_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            grn_number=""
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting GRN: {str(e)}"
        )

    return {"message": "GRN deleted successfully"}

# =====================================================
# DELETE ONLY GRN NUMBER
# =====================================================
@router.delete("/{salesorder_id}/grn/number", status_code=status.HTTP_200_OK)
def delete_grn_number(salesorder_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()

    try:
        sales_order_service.update_grn_number_field(
            access_token=access_token,
            salesorder_id=salesorder_id,
            grn_number=""
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting GRN number: {str(e)}")

    return {"message": "GRN number deleted successfully"}

# =====================================================
# DELETE ONLY GRN FILE
# =====================================================
@router.delete("/{salesorder_id}/grn/file", status_code=status.HTTP_200_OK)
def delete_grn_file(salesorder_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()

    try:
        sales_order_service.delete_attachment_by_prefix(
            access_token=access_token,
            salesorder_id=salesorder_id,
            prefix="_grn"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting GRN file: {str(e)}")

    return {"message": "GRN file deleted successfully"}

@router.delete("/{salesorder_id}/attachments/{attachment_id}")
def delete_attachment(
    salesorder_id: str,
    attachment_id: str,
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()

    result = sales_order_service.delete_attachment(
        access_token,
        salesorder_id,
        attachment_id
    )

    return result

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
            show_to_client=show_to_client,
            email=current_user.email
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

@router.get("/{salesorder_id}/vendor-shipment")
def get_vendor_shipment_details(
    salesorder_id: str,
    current_user=Depends(get_current_user)
):
    access_token = get_zoho_access_token()

    return sales_order_service.get_vendor_shipment_details(
        access_token=access_token,
        salesorder_id=salesorder_id,
        contact_id=current_user.email
    )