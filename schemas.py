import uuid
from enum import Enum as PyEnum
from pydantic import BaseModel, EmailStr, Field, constr
from typing import Annotated, Dict, List, Literal, Optional
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
    email: str

    firstname: Optional[str] = None
    lastname: Optional[str] = None
    phone_number: Optional[str] = None

    is_active: bool
    email_confirmed: bool
    phone_confirmed: bool

    usertype: Optional[str] = None
    organization_id: Optional[str] = None
    department_id: Optional[str] = None  # User's assigned department
    default_module_path: Optional[str] = None  # Default module path to navigate on login

    cts: datetime
    mts: datetime

    roles: list[str]
    plan: Optional[UserPlanResponse] = None

    class Config:
        from_attributes = True



    
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
    can_approve: bool = False
    can_assign: bool = False


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
    can_approve: Optional[bool] = None
    can_assign: Optional[bool] = None
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
    is_active: bool = True        # ✅ FIXED (not Optional)


class CategoryMasterCreate(CategoryMasterBase):
    created_by: Optional[UUID] = None


class CategoryMasterUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: bool | None = None   # ✅ allows omission, not null

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
    is_active: bool = True          # ✅ FIXED
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


# ==========================================
# Testing Request Schemas
# ==========================================

class TestingRequestCreate(BaseModel):
    title: str
    description: Optional[str] = None
    transformer_type: Optional[str] = None
    transformer_rating: Optional[str] = None
    manufacturer: Optional[str] = None
    serial_number: Optional[str] = None
    equipment_type_id: Optional[int] = None
    test_type_id: Optional[int] = None

    # Equipment Asset Register link (auto-fills equipment_type_id, nameplate fields, location)
    equipment_id: Optional[UUID] = None

    # Request category: test | maintenance | inspection | repair_lifecycle
    request_category: Optional[Literal["test", "maintenance", "inspection", "repair_lifecycle", "failure_registry", "taqc_inspection"]] = "test"

    # New department-based location
    organization_id: Optional[UUID] = None
    department_id: Optional[UUID] = None

    # Legacy location fields (optional for backward compatibility)
    zone: Optional[str] = None
    ce_circle: Optional[str] = None
    se_division: Optional[str] = None
    ee_subdivision: Optional[str] = None
    aee_section: Optional[str] = None
    ae_je: Optional[str] = None

    assigned_tester_id: Optional[UUID] = None
    priority: Optional[str] = "normal"
    requested_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    scheduled_start_date: Optional[datetime] = None  # NEW: For scheduled tests
    notes: Optional[str] = None

    # Multi-session support
    is_multi_session: Optional[bool] = False
    total_sessions_planned: Optional[int] = None
    session_interval_days: Optional[int] = None

class TestingRequestUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    transformer_type: Optional[str] = None
    transformer_rating: Optional[str] = None
    manufacturer: Optional[str] = None
    serial_number: Optional[str] = None
    equipment_type_id: Optional[int] = None
    test_type_id: Optional[int] = None
    assigned_tester_id: Optional[UUID] = None

    # Equipment Asset Register link
    equipment_id: Optional[UUID] = None

    # Request category
    request_category: Optional[Literal["test", "maintenance", "inspection", "repair_lifecycle"]] = None

    # New department-based location
    organization_id: Optional[UUID] = None
    department_id: Optional[UUID] = None

    # Legacy location fields
    zone: Optional[str] = None
    ce_circle: Optional[str] = None
    se_division: Optional[str] = None
    ee_subdivision: Optional[str] = None
    aee_section: Optional[str] = None
    ae_je: Optional[str] = None

    priority: Optional[str] = None
    requested_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    scheduled_start_date: Optional[datetime] = None  # NEW
    notes: Optional[str] = None

    # Multi-session support
    is_multi_session: Optional[bool] = None
    total_sessions_planned: Optional[int] = None
    session_interval_days: Optional[int] = None

class TestingRequestAssign(BaseModel):
    tester_id: UUID

class TestingRequestResponse(BaseModel):
    id: UUID
    request_number: str
    title: str
    description: Optional[str] = None
    transformer_type: Optional[str] = None
    transformer_rating: Optional[str] = None
    manufacturer: Optional[str] = None
    serial_number: Optional[str] = None
    equipment_type_id: Optional[int] = None
    test_type_id: Optional[int] = None
    equipment_type_name: Optional[str] = None
    equipment_name: Optional[str] = None  # Alias for Flutter UI
    test_type_name: Optional[str] = None

    # Equipment Asset Register
    equipment_id: Optional[UUID] = None
    equipment_ueic: Optional[str] = None  # Computed from equipment relationship
    bay_number: Optional[str] = None      # Computed from equipment.bay_number
    serial_in_bay: Optional[str] = None   # Computed from equipment.serial_in_bay

    # Request category
    request_category: Optional[str] = "test"

    # New department-based location
    organization_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    department_name: Optional[str] = None  # Computed field

    # Legacy location fields
    zone: Optional[str] = None
    ce_circle: Optional[str] = None
    se_division: Optional[str] = None
    ee_subdivision: Optional[str] = None
    aee_section: Optional[str] = None
    ae_je: Optional[str] = None

    status: str
    priority: Optional[str] = None
    originator_id: UUID
    originator_name: Optional[str] = None
    requester_email: Optional[str] = None  # For Flutter UI (originator email)
    assigned_tester_id: Optional[UUID] = None
    assigned_tester_name: Optional[str] = None
    assigned_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    requested_date: Optional[datetime] = None
    due_date: Optional[datetime] = None
    scheduled_start_date: Optional[datetime] = None  # NEW
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None
    rejection_reason: Optional[str] = None

    # Multi-session support
    is_multi_session: Optional[bool] = False
    total_sessions_planned: Optional[int] = None
    session_interval_days: Optional[int] = None
    session_count: int = 0  # Computed field
    session_types: Optional[list] = None  # From template e.g. ["FACTORY","SITE_RECEIPT","ON_BED"]

    # Lifecycle flags — stamped at creation from template flags
    is_cumulative: Optional[bool] = False
    is_calibration: Optional[bool] = False

        # ─────────────────────────────────────────────
    # Repair Workflow Projection
    # ─────────────────────────────────────────────

    repair_workflow_id: Optional[str] = None

    repair_current_stage: Optional[str] = None

    repair_status: Optional[str] = None

    repair_progress: Optional[int] = None
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# Test Request Schedule Schemas
# ==========================================

class ScheduleFrequencyEnum(str, PyEnum):
    daily = "daily"
    weekly = "weekly"
    biweekly = "biweekly"
    monthly = "monthly"
    quarterly = "quarterly"
    semi_annual = "semi_annual"
    yearly = "yearly"
    triennial = "triennial"


class TestRequestScheduleCreate(BaseModel):
    equipment_type_id: int
    test_type_id: int
    title: str
    frequency: ScheduleFrequencyEnum
    advance_days: int = 15
    end_date: Optional[datetime] = None
    description: Optional[str] = None
    oem_reference: Optional[str] = None
    revised_periodicity_days: Optional[int] = None
    priority: Optional[str] = None
    notes: Optional[str] = None
    request_category: Optional[Literal["test", "maintenance"]] = "test"


class TestRequestScheduleUpdate(BaseModel):
    title: Optional[str] = None
    frequency: Optional[ScheduleFrequencyEnum] = None
    advance_days: Optional[int] = None
    end_date: Optional[datetime] = None
    is_active: Optional[bool] = None
    oem_reference: Optional[str] = None
    revised_periodicity_days: Optional[int] = None
    description: Optional[str] = None


class TestRequestScheduleCreateByType(BaseModel):
    equipment_type_id: int
    test_type_id: int
    frequency: ScheduleFrequencyEnum
    advance_days: int = 1
    end_date: Optional[datetime] = None


class TestRequestScheduleResponse(BaseModel):
    id: UUID
    test_request_id: UUID
    organization_id: UUID
    frequency: str
    start_date: datetime
    end_date: Optional[datetime] = None
    next_run_date: datetime
    last_run_date: Optional[datetime] = None
    advance_days: int
    is_active: bool
    cts: datetime
    mts: datetime

    class Config:
        from_attributes = True


class TestRequestScheduleLogResponse(BaseModel):
    id: UUID
    schedule_id: UUID
    generated_request_id: Optional[UUID] = None
    run_date: datetime
    status: str
    error_message: Optional[str] = None
    cts: datetime

    class Config:
        from_attributes = True


# ==========================================
# Test Result Schemas
# ==========================================

class TestResultCreate(BaseModel):
    test_name: str
    test_category: Optional[str] = None
    result_value: Optional[str] = None
    result_unit: Optional[str] = None
    pass_fail: Optional[str] = None
    remarks: Optional[str] = None
    organization_id: Optional[UUID] = None

class TestResultResponse(BaseModel):
    id: UUID
    testing_request_id: UUID
    test_session_id: Optional[UUID] = None  # Session this result belongs to
    organization_id: Optional[UUID] = None
    test_name: str
    test_category: Optional[str] = None
    result_value: Optional[str] = None
    result_unit: Optional[str] = None
    pass_fail: Optional[str] = None
    remarks: Optional[str] = None
    file_name: Optional[str] = None
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    template_key: Optional[str] = None
    test_data: Optional[dict] = None
    overall_result: Optional[str] = None
    replacement_products: Optional[list] = None
    evaluation_result: Optional[dict] = None  # {overall, evaluated_at, fields}
    tested_by: Optional[UUID] = None
    tested_at: Optional[datetime] = None
    image_count: int = 0
    images: List["TestResultImageResponse"] = []
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# Structured Test Result Schemas (JSONB)
# ==========================================

class TestResultStructuredCreate(BaseModel):
    template_key: str
    test_data: dict
    overall_result: Optional[str] = None
    remarks: Optional[str] = None
    replacement_products: Optional[list] = None
    organization_id: Optional[UUID] = None
    test_session_id: Optional[UUID] = None  # Link result to specific session

class TestResultImageResponse(BaseModel):
    id: UUID
    file_name: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    caption: Optional[str] = None
    download_url: Optional[str] = None
    cts: Optional[datetime] = None

    class Config:
        from_attributes = True

class TestResultStructuredResponse(BaseModel):
    id: UUID
    testing_request_id: UUID
    test_session_id: Optional[UUID] = None  # Session this result belongs to
    organization_id: Optional[UUID] = None
    test_name: str
    template_key: Optional[str] = None
    test_data: Optional[dict] = None
    overall_result: Optional[str] = None
    remarks: Optional[str] = None
    replacement_products: Optional[list] = None
    evaluation_result: Optional[dict] = None  # {overall, evaluated_at, fields:[{key,label,value,unit,status,thresholds}]}
    tested_by: Optional[UUID] = None
    tested_at: Optional[datetime] = None
    images: List[TestResultImageResponse] = []
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None
    # Template column definitions per table field — used by Flutter approval/review
    # screens to render table data with correct column order and labels.
    # { "dfr_measurements": [{key, label, type}, ...], "analysis_results": [...] }
    table_columns: Optional[dict] = None

    class Config:
        from_attributes = True


# ==========================================
# Test Session Schemas (Multi-day/Multi-session Testing)
# ==========================================

class TestSessionCreate(BaseModel):
    session_number: int
    session_name: Optional[str] = None
    session_date: datetime
    scheduled_date: Optional[datetime] = None
    template_key: Optional[str] = None
    notes: Optional[str] = None
    weather_conditions: Optional[str] = None
    environmental_factors: Optional[str] = None
    organization_id: Optional[UUID] = None

class TestSessionUpdate(BaseModel):
    session_name: Optional[str] = None
    session_date: Optional[datetime] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    weather_conditions: Optional[str] = None
    environmental_factors: Optional[str] = None
    conducted_by: Optional[UUID] = None
    witnessed_by: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

class TestSessionResponse(BaseModel):
    id: UUID
    testing_request_id: UUID
    organization_id: Optional[UUID] = None
    session_number: int
    session_name: Optional[str] = None
    session_date: datetime
    scheduled_date: Optional[datetime] = None
    status: str
    template_key: Optional[str] = None
    notes: Optional[str] = None
    weather_conditions: Optional[str] = None
    environmental_factors: Optional[str] = None
    conducted_by: Optional[UUID] = None
    witnessed_by: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    reading_count: int = 0
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# Test Session Reading Schemas
# ==========================================

class TestSessionReadingCreate(BaseModel):
    reading_number: int
    reading_time: datetime
    reading_data: dict
    equipment_serial: Optional[str] = None
    calibration_date: Optional[datetime] = None
    remarks: Optional[str] = None
    result_status: Optional[str] = None

class TestSessionReadingUpdate(BaseModel):
    reading_time: Optional[datetime] = None
    reading_data: Optional[dict] = None
    equipment_serial: Optional[str] = None
    calibration_date: Optional[datetime] = None
    remarks: Optional[str] = None
    result_status: Optional[str] = None

class TestSessionReadingImageResponse(BaseModel):
    id: UUID
    file_name: str
    file_type: Optional[str] = None
    file_size: Optional[int] = None
    caption: Optional[str] = None
    download_url: Optional[str] = None
    sort_order: int
    cts: Optional[datetime] = None

    class Config:
        from_attributes = True

class TestSessionReadingResponse(BaseModel):
    id: UUID
    test_session_id: UUID
    reading_number: int
    reading_time: datetime
    reading_data: dict
    equipment_serial: Optional[str] = None
    calibration_date: Optional[datetime] = None
    remarks: Optional[str] = None
    result_status: Optional[str] = None
    image_count: int = 0
    images: List[TestSessionReadingImageResponse] = []
    recorded_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# Session Comment Schemas
# ==========================================

class SessionCommentCreate(BaseModel):
    comment: str

class SessionCommentResponse(BaseModel):
    id: str
    session_id: str
    comment: str
    author_id: str
    author_name: str
    author_role: Optional[str] = None
    created_at: Optional[str] = None
    modified_at: Optional[str] = None
    is_edited: bool = False

    class Config:
        from_attributes = True


# ==========================================
# Recommendation Schemas
# ==========================================

class RecommendationCreate(BaseModel):
    testing_request_id: UUID
    recommendation_type: str
    summary: str
    detailed_notes: Optional[str] = None
    organization_id: Optional[UUID] = None
    # next_action dispatch — set by Tester when submitting result
    next_action: Optional[str] = None          # none|maintenance|inspection|repair_cycle|replacement
    schedule_frequency: Optional[str] = None   # yearly|quarterly|monthly|semi_annual etc.
    test_types: Optional[list] = None          # [{id, name}] — recommended follow-up test types

class RecommendationUpdate(BaseModel):
    recommendation_type: Optional[str] = None
    summary: Optional[str] = None
    detailed_notes: Optional[str] = None
    next_action: Optional[str] = None
    schedule_frequency: Optional[str] = None
    test_types: Optional[list] = None

class ApprovalAction(BaseModel):
    notes: Optional[str] = None
    # Approver can confirm / override the tester's schedule before dispatch
    schedule_start_date: Optional[str] = None   # ISO 8601 UTC
    schedule_end_date:   Optional[str] = None   # ISO 8601 UTC (optional)
    schedule_frequency:  Optional[str] = None   # "monthly"|"quarterly"|"yearly"|…

class SubmitTestResultsBody(BaseModel):
    replacement_products: Optional[list] = None  # [{item_id, item_name, category, quantity}, ...]
    # Recommendation fields — when provided, a recommendation is created/updated directly
    recommendation_type: Optional[str] = None   # pass | fail | conditional | retest
    summary: Optional[str] = None
    detailed_notes: Optional[str] = None
    next_action: Optional[str] = None           # none | test | maintenance | inspection | repair_cycle | replacement
    schedule_frequency: Optional[str] = None    # daily | weekly | biweekly | monthly | quarterly | semi_annual | yearly | triennial
    schedule_start_date: Optional[str] = None   # YYYY-MM-DD — from wizard schedule picker
    schedule_end_date: Optional[str] = None     # YYYY-MM-DD — from wizard schedule picker
    test_types: Optional[list] = None           # [{id, name}] — recommended follow-up test types


class RecommendationResponse(BaseModel):
    id: UUID
    testing_request_id: UUID
    organization_id: Optional[UUID] = None
    recommendation_type: str
    summary: str
    detailed_notes: Optional[str] = None
    replacement_products: Optional[list] = None
    next_action: Optional[str] = None
    schedule_frequency: Optional[str] = None
    test_types: Optional[list] = None          # [{id, name}] — recommended follow-up test types
    approval_status: Optional[str] = None
    approved_by: Optional[UUID] = None
    approved_by_name: Optional[str] = None   # resolved display name
    approved_at: Optional[datetime] = None
    approval_notes: Optional[str] = None
    submitted_by: Optional[UUID] = None
    submitted_by_name: Optional[str] = None  # resolved display name
    submitted_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None
    # Enriched from related TR + equipment
    request_number: Optional[str] = None
    request_title: Optional[str] = None
    equipment_ueic: Optional[str] = None
    equipment_type_name: Optional[str] = None

    class Config:
        from_attributes = True


# ==========================================
# Procurement Request Schemas
# ==========================================

class ProcurementRequestCreate(BaseModel):
    testing_request_id: UUID
    recommendation_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    estimated_cost: Optional[float] = None
    quantity: Optional[int] = None
    specifications: Optional[str] = None

class ProcurementRequestUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    estimated_cost: Optional[float] = None
    quantity: Optional[int] = None
    specifications: Optional[str] = None

class ProcurementRequestResponse(BaseModel):
    id: UUID
    procurement_number: str
    testing_request_id: UUID
    recommendation_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    title: str
    description: Optional[str] = None
    status: Optional[str] = None
    estimated_cost: Optional[float] = None
    quantity: Optional[int] = None
    specifications: Optional[str] = None
    raised_by: UUID
    raised_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# OrgTestTemplate Schemas
# ==========================================

class OrgTestTemplateCreate(BaseModel):
    template_key: str
    test_type_id: Optional[int] = None
    template_data: dict
    org_id: Optional[UUID] = None

class OrgTestTemplateUpdate(BaseModel):
    template_data: dict

class OrgTestTemplateResponse(BaseModel):
    id: UUID
    org_id: Optional[UUID] = None
    template_key: str
    test_type_id: Optional[int] = None
    template_data: dict
    is_system: bool = True
    version: int = 1


# ==========================================
# Organization Schemas
# ==========================================

class OrganizationBase(BaseModel):
    name: str
    code: str
    display_name: Optional[str] = None
    organization_type: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    primary_email: Optional[str] = None
    primary_phone: Optional[str] = None

class OrganizationCreate(OrganizationBase):
    plan_id: Optional[UUID] = None
    is_active: bool = True
    settings: Optional[Dict] = {}

class OrganizationUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    organization_type: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    primary_email: Optional[str] = None
    primary_phone: Optional[str] = None
    is_active: Optional[bool] = None
    is_verified: Optional[bool] = None
    plan_id: Optional[UUID] = None
    subscription_start_date: Optional[datetime] = None
    subscription_end_date: Optional[datetime] = None
    settings: Optional[Dict] = None

class OrganizationOut(OrganizationBase):
    id: UUID
    is_active: bool
    is_verified: bool
    plan_id: Optional[UUID] = None
    subscription_start_date: Optional[datetime] = None
    subscription_end_date: Optional[datetime] = None
    settings: Optional[Dict] = None
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None
    erp_sync_status: Optional[str] = None
    erp_external_id: Optional[str] = None

    class Config:
        from_attributes = True


# ==========================================
# Organization Department Schemas
# ==========================================

class OrgDepartmentBase(BaseModel):
    name: str
    code: Optional[str] = None
    description: Optional[str] = None
    parent_department_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None

class OrgDepartmentCreate(OrgDepartmentBase):
    organization_id: UUID
    is_active: bool = True

class OrgDepartmentUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    parent_department_id: Optional[UUID] = None
    manager_id: Optional[UUID] = None
    is_active: Optional[bool] = None

class OrgDepartmentOut(OrgDepartmentBase):
    id: UUID
    organization_id: UUID
    is_active: bool
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None
    erp_sync_status: Optional[str] = None
    erp_external_id: Optional[str] = None

    class Config:
        from_attributes = True


# ==========================================
# Organization Role Schemas
# ==========================================

class OrgRoleBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_org_admin: bool = False
    is_dept_admin: bool = False

class OrgRoleCreate(OrgRoleBase):
    organization_id: UUID
    role_type: str = "custom"
    is_active: bool = True

class OrgRoleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_org_admin: Optional[bool] = None
    is_dept_admin: Optional[bool] = None
    is_active: Optional[bool] = None

class OrgRoleOut(OrgRoleBase):
    id: UUID
    organization_id: UUID
    role_type: str
    is_active: bool
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# Organization User Role Schemas
# ==========================================

class OrgUserRoleBase(BaseModel):
    user_id: UUID
    org_role_id: UUID
    department_id: Optional[UUID] = None

class OrgUserRoleCreate(OrgUserRoleBase):
    assigned_by: Optional[UUID] = None
    is_active: bool = True

class OrgUserRoleUpdate(BaseModel):
    is_active: Optional[bool] = None

class OrgUserRoleOut(OrgUserRoleBase):
    id: UUID
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[UUID] = None
    is_active: bool

    class Config:
        from_attributes = True


# ==========================================
# Organization Role Permission Schemas
# ==========================================

class OrgRolePermissionBase(BaseModel):
    org_role_id: UUID
    module_id: int
    can_view: bool = False
    can_add: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_approve: bool = False
    can_assign: bool = False
    can_export: bool = False
    can_import: bool = False

class OrgRolePermissionCreate(OrgRolePermissionBase):
    pass

class OrgRolePermissionUpdate(BaseModel):
    can_view: Optional[bool] = None
    can_add: Optional[bool] = None
    can_edit: Optional[bool] = None
    can_delete: Optional[bool] = None
    can_approve: Optional[bool] = None
    can_assign: Optional[bool] = None
    can_export: Optional[bool] = None
    can_import: Optional[bool] = None

class OrgRolePermissionOut(OrgRolePermissionBase):
    id: UUID
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# Bulk Permission Set Schema
# ==========================================

class PermissionSet(BaseModel):
    module_id: int
    can_view: bool = False
    can_add: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_approve: bool = False
    can_assign: bool = False
    can_export: bool = False
    can_import: bool = False

class BulkPermissionUpdate(BaseModel):
    permissions: List[PermissionSet]


# ==========================================
# Organization User Create Schema
# ==========================================

class OrgUserCreate(BaseModel):
    email: EmailStr
    password: str
    firstname: str
    lastname: Optional[str] = None
    phone_number: str
    employee_id: Optional[str] = None
    department_id: Optional[UUID] = None
    role_ids: Optional[List[UUID]] = []
    isactive: bool = True

class OrgUserUpdate(BaseModel):
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    phone_number: Optional[str] = None
    employee_id: Optional[str] = None
    department_id: Optional[UUID] = None
    isactive: Optional[bool] = None


# ==========================================
# Role Assignment Schema
# ==========================================

class RoleAssignment(BaseModel):
    org_role_id: UUID
    department_id: Optional[UUID] = None


# ==========================================
# Organization User with Roles Schema
# ==========================================

class OrgUserRoleInfo(BaseModel):
    """Role information for user display"""
    role_id: UUID
    role_name: str
    is_org_admin: bool
    is_dept_admin: bool
    department_id: Optional[UUID] = None
    is_active: bool

    class Config:
        from_attributes = True


class OrgUserWithRoles(BaseModel):
    """User schema with role information"""
    id: UUID
    email: str
    firstname: Optional[str] = None
    lastname: Optional[str] = None
    phone_number: str
    organization_id: Optional[UUID] = None
    employee_id: Optional[str] = None
    department_id: Optional[UUID] = None
    isactive: bool
    usertype: Optional[str] = None
    email_confirmed: bool
    phone_confirmed: bool
    cts: datetime
    mts: datetime
    roles: List[OrgUserRoleInfo] = []

    class Config:
        from_attributes = True


# ==========================================
# Organization Invitation Schemas
# ==========================================

class OrgInvitationCreate(BaseModel):
    email: EmailStr
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    org_role_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    expires_in_days: int = 7

class OrgInvitationOut(BaseModel):
    id: UUID
    organization_id: UUID
    email: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    org_role_id: Optional[UUID] = None
    department_id: Optional[UUID] = None
    invitation_token: str
    expires_at: datetime
    status: str
    accepted_at: Optional[datetime] = None
    accepted_by_user_id: Optional[UUID] = None
    invited_by: UUID
    cts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# Role Template Schemas
# ==========================================

class RoleTemplateCreate(BaseModel):
    name: str
    description: Optional[str] = None
    is_org_admin: bool = False
    is_dept_admin: bool = False
    auto_provision: bool = False
    permissions_template: Optional[List[Dict]] = []

class RoleTemplateOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    is_org_admin: bool
    is_dept_admin: bool
    auto_provision: bool
    permissions_template: Optional[List[Dict]] = []
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ==========================================
# Organization with Admin User (for creation)
# ==========================================

class OrganizationWithAdmin(BaseModel):
    organization: OrganizationCreate
    admin_email: EmailStr
    admin_password: str
    admin_firstname: str
    admin_lastname: Optional[str] = None
    admin_phone: str


# ==========================================
# WORKFLOW ENGINE SCHEMAS
# ==========================================

# ---------- Workflow Schemas ----------

class WorkflowCreate(BaseModel):
    """Schema for creating a workflow"""
    name: str
    description: Optional[str] = None
    workflow_type: str  # 'testing_request', 'approval', 'procurement'
    organization_id: Optional[UUID] = None
    is_active: bool = True
    version: int = 1


class WorkflowUpdate(BaseModel):
    """Schema for updating a workflow"""
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class WorkflowResponse(BaseModel):
    """Schema for workflow response"""
    id: UUID
    name: str
    description: Optional[str] = None
    workflow_type: str
    organization_id: Optional[UUID] = None
    is_active: bool
    version: int
    created_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Workflow State Schemas ----------

class WorkflowStateCreate(BaseModel):
    """Schema for creating a workflow state"""
    workflow_id: UUID
    state_code: str  # 'draft', 'submitted', 'approved'
    state_name: str
    description: Optional[str] = None
    state_type: str = 'intermediate'  # 'initial', 'intermediate', 'final', 'cancelled'
    color: str = '#3FA9F5'
    icon: str = 'circle'
    display_order: int = 0
    is_active: bool = True


class WorkflowStateUpdate(BaseModel):
    """Schema for updating a workflow state"""
    state_name: Optional[str] = None
    description: Optional[str] = None
    state_type: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class WorkflowStateResponse(BaseModel):
    """Schema for workflow state response"""
    id: UUID
    workflow_id: UUID
    state_code: str
    state_name: str
    description: Optional[str] = None
    state_type: str
    color: str
    icon: str
    display_order: int
    is_active: bool
    created_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Workflow Transition Schemas ----------

class WorkflowTransitionCreate(BaseModel):
    """Schema for creating a workflow transition"""
    workflow_id: UUID
    from_state_id: UUID
    to_state_id: UUID
    transition_name: str  # 'Submit', 'Approve', 'Reject'
    action_code: str  # 'submit', 'approve', 'reject'
    description: Optional[str] = None
    conditions: Optional[Dict] = None
    button_label: Optional[str] = None
    button_color: str = '#3FA9F5'
    icon: str = 'arrow_forward'
    requires_comment: bool = False
    display_order: int = 0
    is_active: bool = True


class WorkflowTransitionUpdate(BaseModel):
    """Schema for updating a workflow transition"""
    transition_name: Optional[str] = None
    action_code: Optional[str] = None
    description: Optional[str] = None
    conditions: Optional[Dict] = None
    button_label: Optional[str] = None
    button_color: Optional[str] = None
    icon: Optional[str] = None
    requires_comment: Optional[bool] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


class WorkflowTransitionResponse(BaseModel):
    """Schema for workflow transition response"""
    id: UUID
    workflow_id: UUID
    from_state_id: UUID
    to_state_id: UUID
    transition_name: str
    action_code: str
    description: Optional[str] = None
    conditions: Optional[Dict] = None
    button_label: Optional[str] = None
    button_color: str
    icon: str
    requires_comment: bool
    display_order: int
    is_active: bool
    created_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Permission Matrix Schemas ----------

class PermissionMatrixCreate(BaseModel):
    """Schema for creating a permission matrix entry"""
    workflow_id: UUID
    transition_id: UUID
    role_id: UUID
    scope_type: str = 'exact'  # 'exact', 'department_tree', 'organization', 'any'
    department_type_id: Optional[UUID] = None
    can_execute: bool = True
    can_view: bool = True
    requires_approval: bool = False
    conditions: Optional[Dict] = None
    priority: int = 0
    is_active: bool = True


class PermissionMatrixUpdate(BaseModel):
    """Schema for updating a permission matrix entry"""
    scope_type: Optional[str] = None
    department_type_id: Optional[UUID] = None
    can_execute: Optional[bool] = None
    can_view: Optional[bool] = None
    requires_approval: Optional[bool] = None
    conditions: Optional[Dict] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class PermissionMatrixResponse(BaseModel):
    """Schema for permission matrix response"""
    id: UUID
    workflow_id: UUID
    transition_id: UUID
    role_id: UUID
    scope_type: str
    department_type_id: Optional[UUID] = None
    can_execute: bool
    can_view: bool
    requires_approval: bool
    conditions: Optional[Dict] = None
    priority: int
    is_active: bool
    created_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None

    class Config:
        from_attributes = True


# ---------- Workflow Audit Log Schemas ----------

class WorkflowAuditLogCreate(BaseModel):
    """Schema for creating a workflow audit log entry"""
    workflow_id: UUID
    entity_type: str  # 'testing_request', 'purchase_order'
    entity_id: UUID
    transition_id: Optional[UUID] = None
    from_state_id: Optional[UUID] = None
    to_state_id: Optional[UUID] = None
    action_code: Optional[str] = None
    performed_by: Optional[UUID] = None
    user_role_id: Optional[UUID] = None
    user_department_id: Optional[UUID] = None
    comment: Optional[str] = None
    metadata: Optional[Dict] = None
    success: bool = True
    error_message: Optional[str] = None


class WorkflowAuditLogResponse(BaseModel):
    """Schema for workflow audit log response"""
    id: UUID
    workflow_id: UUID
    entity_type: str
    entity_id: UUID
    transition_id: Optional[UUID] = None
    from_state_id: Optional[UUID] = None
    to_state_id: Optional[UUID] = None
    action_code: Optional[str] = None
    performed_by: Optional[UUID] = None
    performed_at: Optional[datetime] = None
    user_role_id: Optional[UUID] = None
    user_department_id: Optional[UUID] = None
    comment: Optional[str] = None
    metadata: Optional[Dict] = None
    success: bool
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


# ---------- Complex Workflow Schemas ----------

class WorkflowWithStates(WorkflowResponse):
    """Workflow with its states included"""
    states: List[WorkflowStateResponse] = []


class WorkflowWithTransitions(WorkflowResponse):
    """Workflow with its states and transitions"""
    states: List[WorkflowStateResponse] = []
    transitions: List[WorkflowTransitionResponse] = []


class WorkflowFullDetail(WorkflowResponse):
    """Complete workflow with states, transitions, and permissions"""
    states: List[WorkflowStateResponse] = []
    transitions: List[WorkflowTransitionResponse] = []
    permission_entries: List[PermissionMatrixResponse] = []


class AvailableTransitionResponse(BaseModel):
    """Schema for available transitions for a user"""
    transition_id: UUID
    transition_name: str
    action_code: str
    to_state_code: str
    to_state_name: str
    button_label: Optional[str] = None
    button_color: str
    icon: str
    requires_comment: bool


class PerformTransitionRequest(BaseModel):
    """Schema for performing a transition"""
    entity_type: str  # 'testing_request'
    entity_id: UUID
    transition_id: UUID
    comment: Optional[str] = None
    metadata: Optional[Dict] = None


class PerformTransitionResponse(BaseModel):
    """Schema for transition execution response"""
    success: bool
    message: str
    new_state: Optional[WorkflowStateResponse] = None
    audit_log_id: Optional[UUID] = None


# ==========================================
# Testing Request Approval Workflow Schemas
# ==========================================

# Alias for testing request output in approval workflow
TestingRequestOut = TestingRequestResponse


class TesterInfo(BaseModel):
    """Information about a tester user for assignment"""
    user_id: str
    email: str
    name: str
    department_id: Optional[str] = None
    active_requests: int  # Current workload

    class Config:
        from_attributes = True


class ApproverTesterSelection(BaseModel):
    """Request body for approver selecting a tester"""
    tester_role_id: UUID  # Which tester role was selected
    tester_id: UUID       # Which specific user was chosen
    comment: Optional[str] = None  # Optional approval comment

    class Config:
        from_attributes = True


class BatchApproverTesterSelection(BaseModel):
    """Request body for batch-approving multiple testing requests to one tester"""
    request_ids: List[UUID]
    tester_role_id: UUID
    tester_id: UUID
    comment: Optional[str] = None

    class Config:
        from_attributes = True


class BatchApprovalResult(BaseModel):
    """Per-request outcome inside a batch approval response"""
    request_id: str
    request_number: Optional[str] = None
    success: bool
    message: str


class BatchApprovalResponse(BaseModel):
    """Response from batch approve-and-assign"""
    total: int
    succeeded: int
    failed: int
    results: List[BatchApprovalResult]


class RejectionRequest(BaseModel):
    """Request body for rejecting a testing request"""
    rejection_comment: str  # Required rejection reason

    class Config:
        from_attributes = True


class ApprovalResponse(BaseModel):
    """Response from approval/rejection action"""
    success: bool
    message: str
    testing_request_id: str
    assigned_tester_id: Optional[str] = None
    assigned_tester_email: Optional[str] = None
    new_status: str
    # Populated by initial-approve: the auto-created child TR
    child_tr_id: Optional[str] = None
    child_tr_number: Optional[str] = None

    class Config:
        from_attributes = True


# ==========================================
# Equipment Asset Register Schemas
# ==========================================

class EquipmentCreate(BaseModel):
    organization_id: Optional[UUID] = None
    department_id: UUID
    equipment_type_id: int
    voltage_class: str  # Required — used for UEIC generation and test threshold lookups
    bay_number: Optional[str] = None
    nameplate_data: Optional[dict] = None
    commissioned_date: Optional[datetime] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    factory_serial_number: Optional[str] = None
    year_of_manufacture: Optional[int] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phase: Optional[str] = None
    ct_ratio_actual: Optional[str] = None
    ct_ratio_current: Optional[str] = None
    pt_ratio: Optional[str] = None
    vector_group: Optional[str] = None
    impedance_pct: Optional[float] = None
    precommission_request_id: Optional[UUID] = None   # optional PCR link on registration


class EquipmentUpdate(BaseModel):
    nameplate_data: Optional[dict] = None
    voltage_class: Optional[str] = None
    bay_number: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    factory_serial_number: Optional[str] = None
    year_of_manufacture: Optional[int] = None
    commissioned_date: Optional[datetime] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    phase: Optional[str] = None
    ct_ratio_actual: Optional[str] = None
    ct_ratio_current: Optional[str] = None
    pt_ratio: Optional[str] = None
    vector_group: Optional[str] = None
    impedance_pct: Optional[float] = None


class EquipmentChainRef(BaseModel):
    """Lightweight reference used inside EquipmentResponse for chain links."""
    id: UUID
    ueic: str
    status: str
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    commissioned_date: Optional[datetime] = None
    retired_date: Optional[datetime] = None

    class Config:
        from_attributes = True


class EquipmentResponse(BaseModel):
    id: UUID
    ueic: str
    organization_id: UUID
    department_id: UUID
    equipment_type_id: int
    equipment_type_name: Optional[str] = None
    department_name: Optional[str] = None
    voltage_class: Optional[str] = None
    bay_number: Optional[str] = None
    serial_in_bay: Optional[str] = None
    nameplate_data: Optional[dict] = None
    status: str
    # Replacement chain (bidirectional)
    replaces_equipment_id: Optional[UUID] = None
    replaces_equipment: Optional[EquipmentChainRef] = None
    replaced_by_id: Optional[UUID] = None
    replaced_by: Optional[EquipmentChainRef] = None
    replacement_reason_type: Optional[str] = None
    commissioned_date: Optional[datetime] = None
    retired_date: Optional[datetime] = None
    retirement_reason: Optional[str] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    factory_serial_number: Optional[str] = None
    year_of_manufacture: Optional[int] = None
    phase: Optional[str] = None
    ct_ratio_actual: Optional[str] = None
    ct_ratio_current: Optional[str] = None
    pt_ratio: Optional[str] = None
    vector_group: Optional[str] = None
    impedance_pct: Optional[float] = None
    created_by: Optional[UUID] = None
    modified_by: Optional[UUID] = None
    cts: Optional[datetime] = None
    mts: Optional[datetime] = None
    latitude: Optional[float] = None   
    longitude: Optional[float] = None

    class Config:
        from_attributes = True


class EquipmentRetireRequest(BaseModel):
    reason: str


class EquipmentReplaceRequest(BaseModel):
    reason: str
    reason_type: str = "other"          # "recommendation_compliance" | "other"
    recommendation_id: Optional[UUID] = None  # required when reason_type="recommendation_compliance"
    nameplate_data: Optional[dict] = None
    commissioned_date: Optional[datetime] = None
    manufacturer: Optional[str] = None
    model_number: Optional[str] = None
    factory_serial_number: Optional[str] = None
    year_of_manufacture: Optional[int] = None
    phase: Optional[str] = None
    ct_ratio_actual: Optional[str] = None
    ct_ratio_current: Optional[str] = None
    pt_ratio: Optional[str] = None
    vector_group: Optional[str] = None
    impedance_pct: Optional[float] = None


class EquipmentCountResponse(BaseModel):
    active: int = 0
    retired: int = 0
    scrapped: int = 0
    under_repair: int = 0
    total: int = 0


# =============================================================================
# Repair Workflow Schemas
# =============================================================================

class RepairStageCreate(BaseModel):
    name: str
    code: str
    sequence: int
    weight: int = 10
    is_mandatory: bool = True


class RepairStageUpdate(BaseModel):
    name: Optional[str] = None
    sequence: Optional[int] = None
    weight: Optional[int] = None
    is_active: Optional[bool] = None
    is_mandatory: Optional[bool] = None


class RepairRoleAssignment(BaseModel):
    role_id: UUID
    can_edit: bool = False
    can_approve: bool = False
    can_assign: bool = False


class RepairTransitionUpsert(BaseModel):
    from_stage_id: UUID
    to_stage_id: Optional[UUID] = None   # None = terminal (end of workflow)
    action: str                          # "approve" | "reject"


class RepairWorkflowStartRequest(BaseModel):
    equipment_id: UUID
    source_failure_id: Optional[UUID] = None


class RepairWorkflowResponse(BaseModel):
    id: UUID
    equipment_id: Optional[UUID] = None
    current_stage_id: Optional[UUID] = None
    status: str
    progress: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RepairAdvanceRequest(BaseModel):
    remarks: Optional[str] = None


class RepairSaveDataRequest(BaseModel):
    form_data: dict


class RepairAssignRequest(BaseModel):
    assign_to_user_id: UUID


class RepairSubmitRequest(BaseModel):
    remarks: Optional[str] = None


class RepairCancelRequest(BaseModel):
    reason: Optional[str] = None


class RepairStageDefResponse(BaseModel):
    id: UUID
    name: str
    code: str
    sequence: int
    weight: int
    is_active: bool
    is_mandatory: bool
    template_id: Optional[UUID] = None
    roles: List[dict] = []
    transitions: List[dict] = []

    class Config:
        from_attributes = True


# Backward-compat alias (old router used RepairWorkflowCreate)
RepairWorkflowCreate = RepairWorkflowStartRequest
