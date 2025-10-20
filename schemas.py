from pydantic import BaseModel, EmailStr
from typing import Optional
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
