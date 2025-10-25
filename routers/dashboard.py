from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from auth_utils import get_current_user
from database import get_db
from services.dashboard_service import DashboardService
#from dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"],dependencies=[Depends(get_current_user)])

@router.get("/")
def get_dashboard(db: Session = Depends(get_db)):
    return {
        "total_products": DashboardService.total_products(db),
        "total_users": DashboardService.total_users(db),
        "total_users_with_plan": DashboardService.total_users_with_plan(db),
        "users_by_plan": DashboardService.users_by_plan(db),
        "total_vendors": DashboardService.total_vendors(db),
        "vendors_by_plan": DashboardService.vendors_by_plan(db),
        "products_by_category": DashboardService.products_by_category(db),
        "products_by_subcategory": DashboardService.products_by_subcategory(db)
    }
