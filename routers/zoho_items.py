from fastapi import APIRouter, HTTPException, Depends
from auth_utils import get_current_user
from services.zoho_item_service import ZohoItemService
from database import SessionLocal
from services.divisionservice import DivisionService

router = APIRouter(
    prefix="/zohoitems",
    tags=["Zoho Items"],
    dependencies=[Depends(get_current_user)]  # 🔐 secured
)

item_service = ZohoItemService()

@router.get("/divisions")
def list_divisions():
    """
    Returns active divisions for dropdowns.
    """
    db = SessionLocal()
    try:
        division_service = DivisionService(db)
        divisions = division_service.list_divisions()

        return [
            d.division_name
            for d in divisions
            if d.is_active
        ]
    finally:
        db.close()
        
@router.get("/")
def list_items(
    page: int = 1,
    per_page: int = 200,
    search: str | None = None,
    division: str | None = None,
):
    return item_service.get_items(
        page=page,
        per_page=per_page,
        search_text=search,
        division=division
    )


@router.get("/taxes")
def list_taxes():
    return item_service.get_taxes()


@router.get("/{item_id}/image")
def get_item_image(item_id: str):
    return item_service.get_item_image(item_id)
