from fastapi import APIRouter, Depends, Response, status, HTTPException
from fastapi.params import Query
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
def email_statement(
    contact_id: str,
    organization_id: str = Query(...),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    current_user=Depends(get_current_user)
):
    """
    Sends Customer Statement Email (Zoho Books)
    If start_date and end_date not provided → current month is used.
    """
    access_token = get_zoho_access_token()

    try:
        result = statement_service.email_customer_statement(
            access_token=access_token,
            contact_id=contact_id,
            #organization_id=organization_id,
            start_date=start_date,
            end_date=end_date
        )
        return {"message": "Statement emailed successfully", "result": result}

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error emailing statement: {str(e)}"
        )


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
@router.get("/{contact_id}/pdf", status_code=200)
def get_statement_pdf(
    contact_id: str,
    #organization_id: str = Query(...),
    start_date: str | None = None,
    end_date: str | None = None,
    current_user = Depends(get_current_user)
):
    """
    Returns Customer Statement PDF (binary stream).
    Viewable in browser or downloadable.
    """
    access_token = get_zoho_access_token()

    try:
        pdf_bytes = statement_service.get_statement_pdf(
            access_token=access_token,
            contact_id=contact_id,
            #organization_id=organization_id,
            start_date=start_date,
            end_date=end_date
        )

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=statement_{contact_id}.pdf"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unable to fetch PDF: {str(e)}")
