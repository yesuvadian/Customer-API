from datetime import date
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from typing import List, Optional
# -----------------------------
# Quote Item
# -----------------------------
class QuoteItem(BaseModel):
    item_id: str = Field(..., description="Zoho Books item_id")
    quantity: int = Field(..., gt=0, description="Quantity requested")

# -----------------------------
# Request Quote (customer)
# -----------------------------
class RequestQuote(BaseModel):
    contact_id: str = Field(
        ...,
        description="Zoho contact_id or customer email. If email is provided, service resolves to contact_id."
    )
    items: List[QuoteItem] = Field(..., description="List of items in the quote")
    notes: Optional[str] = Field(None, description="Optional notes from customer")

# -----------------------------
# ERP Review Quote
# -----------------------------
class ReviewQuote(BaseModel):
    contact_id: str = Field(..., description="Zoho contact_id or email of customer")
    status: str = Field(
        ...,
        #regex="^(approved|rejected)$",
        description="ERP review status: approved or rejected"
    )
    notes: Optional[str] = Field(None, description="ERP reviewer notes")

# -----------------------------
# Customer Approval Quote
# -----------------------------
class ApproveQuote(BaseModel):
    status: str = Field(
        ...,
        #regex="^(accepted|declined)$",
        description="Customer decision: accepted or declined"
    )
    notes: Optional[str] = Field(None, description="Customer notes or feedback")

# -----------------------------
# Quote Response (generic)
# -----------------------------
class QuoteResponse(BaseModel):
    estimate_id: str
    estimate_number: str
    status: str
    message: Optional[str] = None



# -----------------------------
# Sales Order Item
# -----------------------------
class SalesOrderItem(BaseModel):
    item_id: str = Field(..., description="Zoho Books item_id")
    quantity: int = Field(..., gt=0, description="Quantity requested")

# -----------------------------
# Request Sales Order (customer)
# -----------------------------
class RequestSalesOrder(BaseModel):
    contact_id: str = Field(
        ...,
        description="Zoho contact_id or customer email. If email is provided, service resolves to contact_id."
    )
    items: List[SalesOrderItem] = Field(..., description="List of items in the sales order")
    notes: Optional[str] = Field(None, description="Optional notes from customer")

# -----------------------------
# ERP Review Sales Order
# -----------------------------
class ReviewSalesOrder(BaseModel):
    contact_id: str = Field(..., description="Zoho contact_id or email of customer")
    status: str = Field(
        ...,
        #regex="^(approved|rejected)$",
        description="ERP review status: approved or rejected"
    )
    notes: Optional[str] = Field(None, description="ERP reviewer notes")

# -----------------------------
# Customer Approval Sales Order
# -----------------------------
class ApproveSalesOrder(BaseModel):
    status: str = Field(
        ...,
        #regex="^(accepted|declined)$",
        description="Customer decision: accepted or declined"
    )
    notes: Optional[str] = Field(None, description="Customer notes or feedback")

# -----------------------------
# Sales Order Response (generic)
# -----------------------------
class SalesOrderResponse(BaseModel):
    salesorder_id: str
    salesorder_number: str
    status: str
    message: Optional[str] = None




# -----------------------------
# Invoice Item
# -----------------------------
class InvoiceItem(BaseModel):
    item_id: str = Field(..., description="Zoho Books item_id")
    quantity: int = Field(..., gt=0, description="Quantity requested")

# -----------------------------
# Request Invoice (customer)
# -----------------------------
class RequestInvoice(BaseModel):
    contact_id: str = Field(
        ...,
        description="Zoho contact_id or customer email. If email is provided, service resolves to contact_id."
    )
    items: List[InvoiceItem] = Field(..., description="List of items in the invoice")
    notes: Optional[str] = Field(None, description="Optional notes from customer")

# -----------------------------
# ERP Review Invoice
# -----------------------------
class ReviewInvoice(BaseModel):
    contact_id: str = Field(..., description="Zoho contact_id or email of customer")
    status: str = Field(
        ...,
        #regex="^(approved|rejected)$",
        description="ERP review status: approved or rejected"
    )
    notes: Optional[str] = Field(None, description="ERP reviewer notes")

# -----------------------------
# Customer Approval Invoice
# -----------------------------
class ApproveInvoice(BaseModel):
    status: str = Field(
        ...,
        #regex="^(accepted|declined)$",
        description="Customer decision: accepted or declined"
    )
    notes: Optional[str] = Field(None, description="Customer notes or feedback")

# -----------------------------
# Invoice Response (generic)
# -----------------------------
class InvoiceResponse(BaseModel):
    invoice_id: str
    invoice_number: str
    status: str
    message: Optional[str] = None



# -----------------------------
# Retainer Invoice Item
# -----------------------------
class RetainerInvoiceItem(BaseModel):
    item_id: str = Field(..., description="Zoho Books item_id")
    quantity: int = Field(..., gt=0, description="Quantity requested")

# -----------------------------
# Request Retainer Invoice (customer)
# -----------------------------
class RequestRetainerInvoice(BaseModel):
    contact_id: str = Field(
        ...,
        description="Zoho contact_id or customer email. If email is provided, service resolves to contact_id."
    )
    items: List[RetainerInvoiceItem] = Field(..., description="List of items in the retainer invoice")
    notes: Optional[str] = Field(None, description="Optional notes from customer")

# -----------------------------
# ERP Review Retainer Invoice
# -----------------------------
class ReviewRetainerInvoice(BaseModel):
    contact_id: str = Field(..., description="Zoho contact_id or email of customer")
    status: str = Field(
        ...,
        #regex="^(approved|rejected)$",
        description="ERP review status: approved or rejected"
    )
    notes: Optional[str] = Field(None, description="ERP reviewer notes")

# -----------------------------
# Customer Approval Retainer Invoice
# -----------------------------
class ApproveRetainerInvoice(BaseModel):
    status: str = Field(
        ...,
        #regex="^(accepted|declined)$",
        description="Customer decision: accepted or declined"
    )
    notes: Optional[str] = Field(None, description="Customer notes or feedback")

# -----------------------------
# Retainer Invoice Response (generic)
# -----------------------------
class RetainerInvoiceResponse(BaseModel):
    retainerinvoice_id: str
    retainerinvoice_number: str
    status: str
    message: Optional[str] = None
from pydantic import BaseModel, Field
from typing import Optional

# -----------------------------
# Request Customer Payment
# -----------------------------
class InvoicePayment(BaseModel):
    invoice_id: str = Field(
        ...,
        description="Invoice ID to which the payment is applied"
    )
    amount_applied: float = Field(
        ...,
        gt=0,
        description="Amount applied to this invoice"
    )


class RequestPayment(BaseModel):
    contact_id: str = Field(
        ...,
        description="Zoho contact_id or customer email. If email is provided, service resolves to contact_id."
    )
    amount: float = Field(
        ...,
        gt=0,
        description="Total payment amount"
    )
    payment_mode: str = Field(
        ...,
        description="Payment mode e.g. Cash, BankTransfer, CreditCard"
    )
    payment_date: date = Field(
        default_factory=date.today,
        description="Payment date (YYYY-MM-DD)"
    )
    invoices: List[InvoicePayment] = Field(
        ...,
        description="Invoices against which payment is applied"
    )
    reference_number: Optional[str] = Field(
        None,
        description="Transaction reference number"
    )
    description: Optional[str] = Field(
        None,
        description="Optional notes for payment"
    )

    @field_validator("invoices")
    @classmethod
    def validate_invoice_amounts(cls, invoices, info):
        total_applied = sum(i.amount_applied for i in invoices)
        amount = info.data.get("amount")
        if amount is not None and total_applied > amount:
            raise ValueError("Total invoice amounts cannot exceed payment amount")
        return invoices

# -----------------------------
# ERP Review Payment
# -----------------------------
class ReviewPayment(BaseModel):
    contact_id: str = Field(..., description="Zoho contact_id or email of customer")
    status: str = Field(
        ...,
        #regex="^(approved|rejected)$",
        description="ERP review status: approved or rejected"
    )
    notes: Optional[str] = Field(None, description="ERP reviewer notes")

# -----------------------------
# Customer Approval Payment
# -----------------------------
class ApprovePayment(BaseModel):
    status: str = Field(
        ...,
        #regex="^(accepted|declined)$",
        description="Customer decision: accepted or declined"
    )
    notes: Optional[str] = Field(None, description="Customer notes or feedback")

# -----------------------------
# Payment Response (generic)
# -----------------------------
class PaymentResponse(BaseModel):
    payment_id: str
    payment_number: str
    status: str
    message: Optional[str] = None



class ContactTag(BaseModel):
    tag_id: Optional[int] = None
    tag_option_id: Optional[int] = None

class Address(BaseModel):
    attention: Optional[str] = None
    address: str
    street2: Optional[str] = None
    city: str
    state: Optional[str] = None
    state_code: Optional[str] = None
    zip: Optional[int] = None
    country: str
    fax: Optional[str] = None
    phone: Optional[str] = None

class ContactCommunicationPreference(BaseModel):
    is_sms_enabled: Optional[bool] = False
    is_whatsapp_enabled: Optional[bool] = False


class ContactPerson(BaseModel):
    salutation: Optional[str] = None
    first_name: str
    last_name: Optional[str] = None
    email: EmailStr
    phone_number: str | None = None
    email_confirmed: bool = False 
    mobile_confirmed: bool = False
    mobile: str
    designation: Optional[str] = None
    department: Optional[str] = None
    skype: Optional[str] = None
    is_primary_contact: Optional[bool] = False
    communication_preference: Optional[ContactCommunicationPreference] = None
    enable_portal: Optional[bool] = False


class CreateContact(BaseModel):
    contact_name: str
    company_name: Optional[str] = None
    website: Optional[str] = None
    language_code: Optional[str] = "en"
    contact_type: str = "customer"
    customer_sub_type: Optional[str] = "business"
    credit_limit: Optional[int] = None
    pricebook_id: Optional[int] = None
    contact_number: Optional[str] = None
    ignore_auto_number_generation: Optional[bool] = False
    tags: Optional[List[ContactTag]] = None
    is_portal_enabled: Optional[bool] = False
    currency_id: Optional[int] = None
    payment_terms: Optional[int] = None
    payment_terms_label: Optional[str] = None
    notes: Optional[str] = None
    billing_address: Optional[Address] = None
    shipping_address: Optional[Address] = None
    contact_persons: Optional[List[ContactPerson]] = None

    # @model_validator(mode='after')
    # def check_unique_contacts(self) -> 'CreateContact':
    #     if self.contact_persons:
    #         emails = [p.email for p in self.contact_persons]
    #         mobiles = [p.mobile for p in self.contact_persons if p.mobile]

    #         if len(emails) != len(set(emails)):
    #             raise ValueError("Duplicate emails found in contact list")
    #         if len(mobiles) != len(set(mobiles)):
    #             raise ValueError("Duplicate mobile numbers found in contact list")
    #     return self

    
class ContactResponse(BaseModel):
    contact_id: str
    contact_name: str
    company_name: Optional[str]
    is_portal_enabled: bool
    message: Optional[str] = None



    

class CommentCreate(BaseModel):
    description: str

class CommentUpdate(BaseModel):
    description: str
