from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from uuid import UUID

from auth_utils import get_current_user
from database import get_db
from models import Plan
#from plan_service import PlanService
from pydantic import BaseModel

from schemas import PlanCreate, PlanOut, PlanUpdate
from services.plan_service import PlanService

router = APIRouter(prefix="/plans", tags=["Plans"],dependencies=[Depends(get_current_user)])



# ------------------------------
# GET /plans
# ------------------------------
@router.get("", response_model=List[PlanOut])
def get_active_plans(skip: int = 0, limit: int = 100, search: str | None = None, db: Session = Depends(get_db)):
    """Get all active plans"""
    return PlanService.get_plans(db, skip=skip, limit=limit, search=search, active_only=True)

# ------------------------------
# GET /plans/{plan_id}
# ------------------------------
@router.get("/{plan_id}", response_model=PlanOut)
def get_plan(plan_id: UUID, db: Session = Depends(get_db)):
    return PlanService.get_plan(db, plan_id)

# ------------------------------
# POST /plans
# ------------------------------
@router.post("", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(plan: PlanCreate, db: Session = Depends(get_db)):
    return PlanService.create_plan(
        db,
        planname=plan.planname,
        plan_description=plan.plan_description,
        plan_limit=plan.plan_limit,
        isactive=plan.isactive
    )

# ------------------------------
# PUT /plans/{plan_id}
# ------------------------------
@router.put("/{plan_id}", response_model=PlanOut)
def update_plan(plan_id: UUID, updates: PlanUpdate, db: Session = Depends(get_db)):
    updates_dict = updates.dict(exclude_unset=True)
    return PlanService.update_plan(db, plan_id, updates_dict)

# ------------------------------
# DELETE /plans/{plan_id}
# ------------------------------
@router.delete("/{plan_id}", response_model=PlanOut)
def delete_plan(plan_id: UUID, db: Session = Depends(get_db)):
    return PlanService.delete_plan(db, plan_id)
