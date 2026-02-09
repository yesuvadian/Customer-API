from fastapi import APIRouter, Depends, Response, HTTPException
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
    Fetch Zoho Inventory items (products/services).
    Includes backend-friendly image URLs for items with attachments.
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


@router.get("/{item_id}/image")
def get_item_image(item_id: str):
    """
    Proxy Zoho item image so frontend doesn’t need Zoho auth.
    Returns the actual image file for the given item_id.
    """
    try:
        return item_service.get_item_image(item_id)
    except HTTPException as e:
        raise e