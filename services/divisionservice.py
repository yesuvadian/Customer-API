from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from uuid import UUID
from models import Division


class DivisionService:
    def __init__(self, db: Session):
        self.db = db

    # ----------------- CREATE -----------------
    def create_division(
        self,
        division_name: str,
        description: Optional[str] = None
    ) -> Division:
        division = Division(division_name=division_name, description=description)
        self.db.add(division)
        try:
            self.db.commit()
            self.db.refresh(division)
            return division
        except IntegrityError:
            self.db.rollback()
            raise ValueError(f"Division with name '{division_name}' already exists.")

    # ----------------- READ -----------------
    def get_division(self, division_id: UUID) -> Division:
        division = self.db.get(Division, division_id)
        if not division:
            raise ValueError(f"Division with id '{division_id}' not found.")
        return division

    def get_division_by_name(self, division_name: str) -> Division:
        division = self.db.query(Division).filter(Division.division_name == division_name).first()
        if not division:
            raise ValueError(f"Division with name '{division_name}' not found.")
        return division

    # ----------------- LIST -----------------
    def list_divisions(self, skip: int = 0, limit: int = 100) -> List[Division]:
        return self.db.query(Division).offset(skip).limit(limit).all()

    # ----------------- UPDATE -----------------
    def update_division(
        self,
        division_id: UUID,
        division_name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Division:
        division = self.get_division(division_id)

        if division_name is not None:
            division.division_name = division_name
        if description is not None:
            division.description = description

        try:
            self.db.commit()
            self.db.refresh(division)
            return division
        except IntegrityError:
            self.db.rollback()
            raise ValueError(f"Division with name '{division_name}' already exists.")

    # ----------------- DELETE -----------------
    def delete_division(self, division_id: UUID) -> bool:
        division = self.get_division(division_id)
        self.db.delete(division)
        self.db.commit()
        return True
