from fastapi import APIRouter, Depends
from auth_utils import get_current_user
from services.zoho_item_service import ZohoItemService

router = APIRouter(
    prefix="/zohoitems",
    tags=["Zoho Items"]
)

item_service = ZohoItemService()


@router.get("/")
def list_items(
    page: int = 1,
    per_page: int = 200,
    search: str | None = None
):
    """
    Fetch Zoho Books items (products/services)
    """
    return item_service.get_items(
        page=page,
        per_page=per_page,
        search_text=search
    )
@router.get("/taxes")
def list_taxes():
    """
    Fetch all taxes configured in Zoho Books.
    Useful for retrieving tax_id values required in quotes/invoices.
    """
    return item_service.get_taxes()
