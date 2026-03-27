from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import uuid

class Bill(BaseModel):
    id: uuid.UUID
    bill_number: Optional[str] = None
    payment_id: Optional[str] = None
    invoice_id: str
    invoice_number: Optional[str] = None
    contact_id: Optional[str] = None
    amount: float
    payment_mode: Optional[str] = None
    reference_number: Optional[str] = None
    payment_date: Optional[str] = None
    status: Optional[str] = "open"
    created_by: Optional[str] = None
    vendor_id: Optional[uuid.UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class BillCreate(BaseModel):
    bill_number: str
    payment_id: str
    invoice_id: str
    invoice_number: Optional[str] = None
    contact_id: Optional[str] = None
    amount: float
    payment_mode: Optional[str] = None
    reference_number: Optional[str] = None
    payment_date: Optional[str] = None
    status: str = "open"
    created_by: Optional[str] = None
    vendor_id: Optional[uuid.UUID] = None

class BillResponse(BaseModel):
    bill_id: uuid.UUID
    bill_number: str
    invoice_number: Optional[str] = None
    amount: float
    status: str
    created_at: Optional[datetime] = None