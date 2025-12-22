from fastapi import APIRouter, Depends, status, HTTPException
from auth_utils import get_current_user
from services.statement_service import StatementService
from services.zoho_auth_service import get_zoho_access_token

router = APIRouter(
    prefix="/zohostatements",
    tags=["Statements"],
    dependencies=[Depends(get_current_user)]
)

statement_service = StatementService()

@router.post("/{contact_id}/email", status_code=status.HTTP_200_OK)
def email_statement(contact_id: str, current_user=Depends(get_current_user)):
    """
    Email Customer Statement:
    - Sends the statement to the customer via email
    """
    access_token = get_zoho_access_token()
    try:
        result = statement_service.email_customer_statement(access_token, contact_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error emailing statement: {str(e)}")
    return {"message": "Statement emailed successfully", "result": result}

@router.get("/{contact_id}/email", status_code=status.HTTP_200_OK)
def get_statement_email_history(contact_id: str, current_user=Depends(get_current_user)):
    """
    Get Statement Email History:
    - Returns list of statement emails sent to the customer
    """
    access_token = get_zoho_access_token()
    try:
        history = statement_service.get_statement_email_history(access_token, contact_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching statement email history: {str(e)}")
    return {"history": history}

@router.post("/statement/{contact_id}/email", status_code=status.HTTP_200_OK)
def email_statement_pdf(contact_id: str, current_user=Depends(get_current_user)):
    access_token = get_zoho_access_token()
    try:
        result = statement_service.email_customer_statement(access_token, contact_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error emailing statement PDF: {str(e)}")
    return {"message": "Statement emailed successfully", "result": result}
