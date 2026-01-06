import uuid
from pydantic import BaseModel, EmailStr, Field, constr
from typing import Annotated, Dict, List, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class CategorySchema(BaseModel):
    id: int
    name: str

class ProductSubCategorySchema(BaseModel):
    id: int
    name: str
    description: Optional[str]
    category_id: int
    category: Optional[CategorySchema] = None

    class Config:
        orm_mode = True

class UserBase(BaseModel):
    email: EmailStr
    firstname: Optional[str]
    lastname: Optional[str]
    phone_number: str
    plan_id: Optional[UUID] = None   # ✅ ADD THIS



class QuoteItem(BaseModel):
    item_id: str
    quantity: int

class RequestQuote(BaseModel):
    contact_id: str
    items: List[QuoteItem]
    notes: Optional[str] = None

class UserCreate(UserBase):
    password: str

class User(UserBase):
    id: UUID
    isactive: bool
    
    # ✅ NEW FIELD (nullable)
    usertype: Optional[str] = None
     # ✅ NEW FIELD
    zoho_erp_id: Optional[str] = None
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

# -------------------------
# Schema for updating an entry
# -------------------------
class CompanyTaxInfoUpdate(BaseModel):
    pan: Optional[Annotated[str, "max_length=10"]] = None
    gstin: Optional[Annotated[str, "max_length=15"]] = None
    tan: Optional[Annotated[str, "max_length=10"]] = None
    state_id: Optional[int] = None
    financial_year: Optional[str] = None

class CompanyTaxInfoBase(BaseModel):
    pan: Optional[str] = None
    gstin: Optional[str] = None
    tan: Optional[str] = None
    financial_year: str

class CompanyTaxInfoCreate(CompanyTaxInfoBase):
    company_id: UUID   # ✅ FIXED (was int)

class CompanyTaxInfoOut(BaseModel):
    id: int
    company_id: UUID  # ✅ FIXED
    pan: Optional[str] = None
    gstin: Optional[str] = None
    tan: Optional[str] = None
    financial_year: str
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: datetime
    mts: datetime

    model_config = {
        "from_attributes": True
    }



class CountryOut(BaseModel):
    id: int
    name: str
    code: Optional[str] = None

    class Config:
        orm_mode = True


class StateOut(BaseModel):
    id: int
    name: str
    code: Optional[str] = None
    country_id: Optional[int] = None

    class Config:
        orm_mode = True

class CityBase(BaseModel):
    name: str = Field(..., max_length=100)
    code: Optional[str] = Field(None, max_length=10, description="Optional unique code for the city")
    state_id: int = Field(..., description="ID of the State the city belongs to")
class CityCreate(BaseModel):
    name: str
    state_id: int
    erp_external_id: Optional[str] = None  # allow setting it on creation
class CityUpdate(BaseModel):
    name: Optional[str] = None
    state_id: Optional[int] = None
    erp_external_id: Optional[str] = None  # allow updating

class CityOut(BaseModel):
    id: int
    name: str
    state_id: int
    erp_external_id: Optional[str] = None  # ✅ kept

    class Config:
        orm_mode = True


class UserMinimalOut(BaseModel):
    id: uuid.UUID
    email: str
    firstname: Optional[str] = None
    lastname: Optional[str] = None

    class Config:
        orm_mode = True
class UserAddressUpdate(BaseModel):
    address_type: Optional[str] = Field(None, max_length=50)
    is_primary: Optional[bool] = None
    address_line1: Optional[str] = Field(None, max_length=255)
    address_line2: Optional[str] = Field(None, max_length=255)
    postal_code: Optional[str] = Field(None, max_length=20)
    state_id: Optional[int] = None
    city_id: Optional[int] = None
    country_id: Optional[int] = None
    modified_by: Optional[uuid.UUID] = None

    class Config:
        orm_mode = True
class UserAddressCreate(BaseModel):
    user_id: uuid.UUID = Field(..., description="UUID of the user who owns this address")
    address_type: str = Field(..., max_length=50, description="Type of address (e.g., billing, shipping)")
    is_primary: bool = Field(default=False, description="Whether this is the primary address")
    address_line1: str = Field(..., max_length=255)
    address_line2: Optional[str] = Field(None, max_length=255)
    city_id: Optional[int] = Field(None, description="City ID Foreign Key")
    state_id: Optional[int] = Field(None, description="Foreign key reference to states table")
    country_id: Optional[int] = Field(None, description="Foreign key reference to countries table")
    postal_code: Optional[str] = Field(None, max_length=20)

    latitude: Optional[float] = Field(None, description="Latitude for the address")
    longitude: Optional[float] = Field(None, description="Longitude for the address")

    created_by: Optional[uuid.UUID] = None
    modified_by: Optional[uuid.UUID] = None

    class Config:
        orm_mode = True

class CompanyBankDocumentCreateSchema(BaseModel):
    """
    Use this for create endpoints. File binary is uploaded via UploadFile in the endpoint,
    so only metadata fields are here.
    """
    company_bank_info_id: int = Field(..., description="FK to CompanyBankInfo")
    category_detail_id: int = Field(..., description="FK to CategoryDetails for Document Type (e.g., Cancelled Cheque Detail ID)")
    file_name: str = Field(..., max_length=255)
    file_type: Optional[str] = Field(None, max_length=100)  # e.g. application/pdf
class CompanyBankDocumentUpdateSchema(BaseModel):
    """
    Partial update. Exclude unset fields when passing to service (updates.dict(exclude_unset=True)).
    """
    category_detail_id: Optional[int] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    is_verified: Optional[bool] = None
    verified_by: Optional[str] = None  # UUID as str
    verified_at: Optional[datetime] = None

class CompanyBankDocumentBase(BaseModel):
    file_name: str
    file_type: Optional[str] = None


class CompanyBankDocumentSchema(BaseModel):
    id: int
    company_bank_info_id: int

    category_detail_id: int | None = None   # 🔥 ADD THIS LINE

    file_name: str
    file_type: Optional[str] = None
    file_url: Optional[str] = None
    download_url: Optional[str] = None
    is_verified: Optional[bool] = None
    verified_by: Optional[str] = None
    verified_at: Optional[datetime] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    document_type_detail: Optional['CategoryDetailsResponse'] = None

    class Config:
        orm_mode = True



class CompanyBankInfoBase(BaseModel):
    bank_name: str = Field(..., max_length=255)
    account_number: str = Field(..., max_length=50)
    account_type_detail_id: Optional[int] = None
    ifsc: str = Field(..., max_length=20)
    branch_name: Optional[str] = None
    account_holder_name: Optional[str] = None

class CompanyBankInfoUpdateSchema(BaseModel):
    #company_id: UUID  # ✅ from client
    bank_name: Optional[str] = None
    account_number: Optional[str] = None
    ifsc: Optional[str] = None
    branch_name: Optional[str] = None
    account_holder_name: Optional[str] = None
    is_primary: bool = True
    account_type_detail_id: Optional[int] = None


class CompanyBankInfoCreateSchema(BaseModel):
    company_id: UUID  # ✅ from client
    account_holder_name: str
    account_number: str
    account_type_detail_id: int
    ifsc: str
    bank_name: str
    branch_name: Optional[str] = None
    is_primary: bool = True


class CompanyBankInfoSchema(CompanyBankInfoBase):
    id: int
    company_id: UUID
    account_type_detail: Optional['CategoryDetailsResponse'] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        orm_mode = True




class UserAddressOut(BaseModel):
    id: int
    user_id: uuid.UUID
    address_type: str
    is_primary: bool
    address_line1: str
    address_line2: Optional[str] = None
    city_id: Optional[int] = None                         # ✅ Added
    state_id: Optional[int] = None
    country_id: Optional[int] = None
    postal_code: Optional[str] = None
    latitude: Optional[float] = None                   # ✅ Added
    longitude: Optional[float] = None                  # ✅ Added
    created_by: Optional[uuid.UUID] = None
    modified_by: Optional[uuid.UUID] = None
    cts: datetime
    mts: datetime

    # Related objects
    state: Optional[StateOut] = None
    country: Optional[CountryOut] = None
    creator: Optional[UserMinimalOut] = None
    modifier: Optional[UserMinimalOut] = None

    class Config:
        orm_mode = True


class ProductCategorySchema(BaseModel):
    id: int
    name: str
    description: str | None = None

    class Config:
        orm_mode = True  # allows SQLAlchemy models to be returned directly
class ProductSubCategorySchema(BaseModel):
    id: int
    name: str
    category_id: int | None = None
    description: str | None = None

    class Config:
        orm_mode = True  # allows SQLAlchemy model instances to be returned


class CompanyProductBulkAssignRequest(BaseModel):
    company_id: str
    products: List[dict]  # each dict: {product_id, price, stock}
class UserPlanResponse(BaseModel):
    id: str
    planname: str
    plan_description: Optional[str] = None
    plan_limit: Optional[int] = None
    # duration_days: Optional[int] = None  # Uncomment if you include it later
# ------------------------------
# Pydantic Schemas
# ------------------------------
class PlanCreate(BaseModel):
    planname: str
    plan_description: str | None = None
    plan_limit: int = 0
    isactive: bool = True

class PlanUpdate(BaseModel):
    planname: str | None = None
    plan_description: str | None = None
    plan_limit: int | None = None
    isactive: bool | None = None

from pydantic import BaseModel, Field
from uuid import UUID

class PlanOut(BaseModel):
    id: UUID
    planname: str
    plan_description: Optional[str] = None  # ✅ Use same name as DB field
    plan_limit: int
    isactive: bool

    class Config:
        orm_mode = True

    class Config:
        orm_mode = True


class ProductCreateSchema(BaseModel):
    name: str
    sku: str
    category_id: Optional[int] = None
    subcategory_id: Optional[int] = None
    description: Optional[str] = None
      # ✅ FIX: reference GST slab, not percentage
    gst_slab_id: Optional[int] = None
    hsn_code: Optional[str] = None
    gst_percentage: Optional[float] = None
    material_code: Optional[str] = None
    selling_price: Optional[float] = None
    cost_price: Optional[float] = None




class CompanyAssignedProductSchema(BaseModel):
    company_product_id: int
    product_id: int
    name: str
    sku: str
    category_id: int | None = None
    subcategory_id: int | None = None
    description: str | None = None

    class Config:
        orm_mode = True

class IdList(BaseModel):
    ids: List[int]





class ProductUpdateSchema(BaseModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    category_id: Optional[int] = None
    subcategory_id: Optional[int] = None
    description: Optional[str] = None

    hsn_code: Optional[str] = None
    gst_slab_id: Optional[int] = None   # ✅ REPLACED
    material_code: Optional[str] = None
    selling_price: Optional[float] = None
    cost_price: Optional[float] = None



class ProductSchema(BaseModel):
    id: int
    name: str
    sku: str

    category_id: int | None = None
    subcategory_id: int | None = None
    description: str | None = None

    hsn_code: str | None = None
    gst_slab_id: int | None = None     # ✅ REPLACED
    material_code: str | None = None
    selling_price: float | None = None
    cost_price: float | None = None

    # Audit
    created_by: UUID | None = None
    modified_by: UUID | None = None
    cts: datetime | None = None
    mts: datetime | None = None

    class Config:
        from_attributes = True  # Pydantic v2


class CompanyProductSchema(BaseModel):
    id: int
    company_id: str
    product_id: int
    price: float
    stock: int | None = 0
    stock: int | None = 0
    class Config:
        orm_mode = True  # allows SQLAlchemy model instances to be returned
        allow_population_by_field_name = True


from typing import List, Optional
from pydantic import BaseModel

class QuickRegister(BaseModel):
    firstname: str
    email: str
    phone_number: str
    product_ids: List[int] = []

class QuickRegisterResponse(BaseModel):
    id: UUID
    firstname: str
    email: str
    phone_number: str
    product_ids: List[int] = []

    class Config:
        orm_mode = True


    
class LoginRequest(BaseModel):
    email: str
    password: str


class ModuleBase(BaseModel):
    name: str
    description: Optional[str] = None
    path: Optional[str] = None
    group_name: Optional[str] = None

class ModuleCreate(ModuleBase):
    pass

class ModuleUpdate(ModuleBase):
    is_active: Optional[bool] = None

class ModuleResponse(ModuleBase):
    id: int
    is_active: bool

    class Config:
        orm_mode = True



class RefreshTokenRequest(BaseModel):
    refresh_token: str

class UserRegistor(BaseModel):
    email: EmailStr
    password: str
    firstname: str
    lastname: str
    phone_number: str

    plan_id: UUID | None = None
    isactive: bool = True

    # ✅ ADD THESE
    usertype: str | None = None
    zoho_erp_id: str | None = None

    class Config:
        from_attributes = True

    
class UserResponse(BaseModel):
    id: UUID
    email: EmailStr
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    phone_number: str | None = None
    is_active: bool
    email_confirmed: bool
    phone_confirmed: bool
    cts: datetime  # created timestamp
    mts: datetime  # modified timestamp
    roles: list[str]
    plan: Optional[UserPlanResponse] = None  # ✅ added plan here

    class Config:
        orm_mode = True  # allows Pydantic to read from SQLAlchemy models


    
class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserResponse
    privileges: Dict[str, Dict[str, bool]]

class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., example="eyJhbGciOiJIUzI1NiIs...")
    new_password: str = Field(..., example="NewStrongPass@123")


class PasswordResetResponse(BaseModel):
    message: str
    reset_link: str

# -------- Role Schemas --------
class RoleBase(BaseModel):
    name: str
    description: Optional[str] = None

class RoleCreate(RoleBase):
    created_by: Optional[UUID]

class RoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    modified_by: Optional[UUID] = None

class RoleResponse(RoleBase):
    id: int
    created_by: Optional[UUID]
    modified_by: Optional[UUID]
    cts: datetime
    mts: datetime

    class Config:
        orm_mode = True





class UserRolesBulkCreate(BaseModel):
    user_id: int
    role_ids: List[int]  # List of role IDs to assign



class UserRoleCreate(BaseModel):
    user_id: UUID
    role_id: int

# -------- UserRole Schemas --------
class UserRolesBulkCreate(BaseModel):
    assignments: List[UserRoleCreate]

class UserRoleUpdate(BaseModel):
    role_id: int

class UserRoleResponse(BaseModel):
    user_id: UUID
    role_id: int
    assigned_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        orm_mode = True




class RoleModulePrivilegeBase(BaseModel):
    role_id: int
    module_id: int
    can_add: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_search: bool = False
    can_import: bool = False
    can_export: bool = False
    can_view: bool = False


class RoleModulePrivilegeCreate(RoleModulePrivilegeBase):
    created_by: Optional[UUID] = None


class RoleModulePrivilegeUpdate(BaseModel):
    can_add: Optional[bool] = None
    can_edit: Optional[bool] = None
    can_delete: Optional[bool] = None
    can_search: Optional[bool] = None
    can_import: Optional[bool] = None
    can_export: Optional[bool] = None
    can_view: Optional[bool] = None
    modified_by: Optional[UUID] = None


class RoleModulePrivilegeResponse(RoleModulePrivilegeBase):
    id: int
    created_by: Optional[UUID]
    modified_by: Optional[UUID]
    cts: datetime
    mts: datetime

    class Config:
        orm_mode = True
        arbitrary_types_allowed = True
        exclude = {"created_user", "modified_user", "role", "module"}


# -----------------------------
# Certificate Schemas
# -----------------------------
class CompanyProductCertificateOut(BaseModel):
    id: int
    company_product_id: int
    file_name: str
    file_type: Optional[str]
    file_size: Optional[int]
    issued_date: Optional[datetime]
    expiry_date: Optional[datetime]
    cts: datetime
    mts: datetime

    class Config:
        orm_mode = True


# -----------------------------
# Supply Reference Schemas
# -----------------------------
class CompanyProductSupplyReferenceOut(BaseModel):
    id: int
    company_product_id: int
    file_name: str
    file_type: Optional[str]
    file_size: Optional[int]
    description: Optional[str]
    customer_name: Optional[str]
    reference_date: Optional[datetime]
    cts: datetime
    mts: datetime

    class Config:
        orm_mode = True


# ---------- Division ----------
class DivisionBase(BaseModel):
    division_name: str
    description: Optional[str] = None

class DivisionCreate(DivisionBase):
    pass

class DivisionUpdate(DivisionBase):
    pass

class DivisionResponse(DivisionBase):
    id: UUID
    division_name: str
    cts: datetime
    mts: datetime
    class Config:
        orm_mode = True

# schema.py

# 1. Add a simple schema for the Product details
class ProductSimpleSchema(BaseModel):
    id: int
    name: str
    sku: Optional[str] = None
    
    class Config:
        orm_mode = True

# 2. Update CompanyProductSchema to include the nested product
class CompanyProductSchema(BaseModel):
    id: int
    company_id: UUID
    product_id: int
    price: float
    stock_quantity: Optional[int] = 0
    
    # 🌟 ADD THIS: This allows the nested relationship to be serialized
    product: Optional[ProductSimpleSchema] = None 

    class Config:
        orm_mode = True
        allow_population_by_field_name = True


class UserDocumentBase(BaseModel):

    document_name: str

    document_type: Optional[str] = None

    document_url: Optional[str] = None

    file_size: Optional[int] = None

    content_type: Optional[str] = None

    om_number: Optional[str] = None

    expiry_date: Optional[datetime] = None

    is_active: Optional[bool] = True

   

    # 🌟 ADDED NEW FIELD

    company_product_id: Optional[int] = None



class UserDocumentCreate(UserDocumentBase):

    user_id: UUID

    uploaded_by: Optional[UUID] = None

    file_data: Optional[bytes] = None



class UserDocumentUpdate(BaseModel):

    om_number: Optional[str] = None

    expiry_date: Optional[datetime] = None

    is_active: Optional[bool] = None

    document_url: Optional[str] = None

    modified_by: Optional[UUID] = None

   

    # 🌟 ADDED NEW FIELD

    company_product_id: Optional[int] = None





class UserDocumentResponse(UserDocumentBase):

    id: UUID

    user_id: UUID

    uploaded_by: Optional[UUID]

    uploaded_at: datetime

    # Assuming DivisionResponse and CategoryDetailsResponse exist

    division: 'DivisionResponse'

    category_details: Optional['CategoryDetailsResponse'] = None

   

    # 🌟 ADDED NEW FIELD AND NESTED SCHEMA

    company_product_id: Optional[int] = None # Include the raw ID

    company_product: Optional[CompanyProductSchema] = None # Include the nested schema for relationships



    class Config:

        orm_mode = True

class CategoryMasterBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: Optional[bool] = True

class CategoryMasterCreate(CategoryMasterBase):
    created_by: Optional[UUID] = None

class CategoryMasterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    modified_by: Optional[UUID] = None

class CategoryMasterResponse(CategoryMasterBase):
    id: int
    created_by: Optional[UUID]
    modified_by: Optional[UUID]
    cts: datetime
    mts: datetime

    class Config:
        orm_mode = True  # Use 'from_attributes = True' if using Pydantic v2

# ==========================================
# 2. Category Details Schemas
# ==========================================

class CategoryDetailsBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_active: Optional[bool] = True
    category_master_id: int

class CategoryDetailsCreate(CategoryDetailsBase):
    created_by: Optional[UUID] = None

class CategoryDetailsUpdate(BaseModel):
    category_master_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    modified_by: Optional[UUID] = None

class CategoryDetailsResponse(CategoryDetailsBase):
    id: int
    created_by: Optional[UUID]
    modified_by: Optional[UUID]
    cts: datetime
    mts: datetime
    
    # Nested Relationship (Like 'division' in your reference)
    master: Optional[CategoryMasterResponse] = None 

    class Config:
        orm_mode = True