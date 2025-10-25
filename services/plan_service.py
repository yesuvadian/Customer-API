from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from models import Plan

class PlanService:

    @classmethod
    def get_plans(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None, active_only: bool = True):
        query = db.query(Plan)
        
        if active_only:
            query = query.filter(Plan.isactive == True)
        
        if search:
            query = query.filter(Plan.planname.ilike(f"%{search}%"))
        
        return query.offset(skip).limit(limit).all()

    @classmethod
    def get_plans(cls, db: Session, skip: int = 0, limit: int = 100, search: str | None = None, active_only: bool = True):
        query = db.query(Plan)
        
        if active_only:
            query = query.filter(Plan.isactive == True)
        
        if search:
            query = query.filter(Plan.planname.ilike(f"%{search}%"))
        
        return query.offset(skip).limit(limit).all()

    @classmethod
    def create_plan(cls, db: Session, planname: str, plan_description: str | None = None, plan_limit: int = 0, isactive: bool = True, created_by: UUID | None = None):
        existing = db.query(Plan).filter(Plan.planname == planname).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Plan with this name already exists")
        
        plan = Plan(
            planname=planname,
            plan_description=plan_description,
            plan_limit=plan_limit,
            isactive=isactive,
            created_by=created_by
        )
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return plan

    @classmethod
    def update_plan(cls, db: Session, plan_id: UUID, updates: dict):
        plan = cls.get_plan(db, plan_id)
        for key, value in updates.items():
            if hasattr(plan, key):
                setattr(plan, key, value)
        db.commit()
        db.refresh(plan)
        return plan

    @classmethod
    def delete_plan(cls, db: Session, plan_id: UUID):
        plan = cls.get_plan(db, plan_id)
        db.delete(plan)
        db.commit()
        return plan
