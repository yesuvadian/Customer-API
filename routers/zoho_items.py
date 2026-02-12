from fastapi import APIRouter
from services.zoho_item_service import ZohoItemService, CreateItemRequest

router = APIRouter(prefix="/zohoitems", tags=["Zoho Items"])
service = ZohoItemService()


@router.get("/")
def get_items(page: int = 1, per_page: int = 200, search_text: str | None = None):
    return service.get_items(page=page, per_page=per_page, search_text=search_text)


@router.post("/", status_code=201)
def create_item(payload: CreateItemRequest):
    return service.create_item(payload)


@router.get("/taxes")
def get_taxes():
    return service.get_taxes()


@router.get("/{item_id}/image")
def get_item_image(item_id: str):
    return service.get_item_image(item_id)
