from pydantic import BaseModel, EmailStr, constr
from typing import Annotated, Optional
from uuid import UUID
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    firstname: Optional[str]
    lastname: Optional[str]
    phone_number: str

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: UUID
    isactive: bool
    email_confirmed: bool
    phone_confirmed: bool
    cts: datetime
    mts: datetime

    class Config:
        orm_mode = True

class RoleBase(BaseModel):
    name: str
    description: Optional[str]

class RoleCreate(RoleBase):
    pass

class Role(RoleBase):
    id: int
    cts: datetime
    mts: datetime

    class Config:
        orm_mode = True
# ----------------------
# Country Schemas
# ----------------------
class CountryBase(BaseModel):
    name: str
    code: str  # e.g., "IN" for India

class CountryCreate(CountryBase):
    pass

class CountryUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None

class CountryOut(CountryBase):
    id: int
    cts: Optional[datetime]
    mts: Optional[datetime]

    class Config:
        from_attributes = True  # instead of orm_mode in Pydantic v2
class StateBase(BaseModel):
    name: str
    code: str
    country_id: int

class StateCreate(StateBase):
    pass

class StateUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    country_id: Optional[int] = None

class StateOut(StateBase):
    id: int
    cts: Optional[datetime]
    mts: Optional[datetime]

    class Config:
        from_attributes = True
# -------------------------
# Base schema for shared fields
# -------------------------
class CompanyTaxInfoBase(BaseModel):
    pan: Annotated[str, "max_length=10"]
    gstin: Optional[Annotated[str, "max_length=15"]] = None
    tan: Optional[Annotated[str, "max_length=10"]] = None
    state_id: Optional[int] = None
    financial_year: Optional[str] = None

# -------------------------
# Schema for creating a new entry
# -------------------------
class CompanyTaxInfoCreate(CompanyTaxInfoBase):
    company_id: UUID

# -------------------------
# Schema for updating an entry
# -------------------------
class CompanyTaxInfoUpdate(BaseModel):
    pan: Optional[Annotated[str, "max_length=10"]] = None
    gstin: Optional[Annotated[str, "max_length=15"]] = None
    tan: Optional[Annotated[str, "max_length=10"]] = None
    state_id: Optional[int] = None
    financial_year: Optional[str] = None

# -------------------------
# Schema for reading/output
# -------------------------
class CompanyTaxInfoOut(CompanyTaxInfoBase):
    id: int
    company_id: UUID
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: datetime
    mts: datetime

    model_config = {
        "from_attributes": True  # Pydantic v2 uses model_config instead of Config
    }