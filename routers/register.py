import json
from typing import List
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile,status
import httpx
from sqlalchemy.orm import Session

from auth_utils import get_registration_user
from config import MAX_FILE_SIZE_KB, NOMINATIM_URL
from database import get_db
from routers.company_tax_documents import MAX_FILE_SIZE_BYTES
import schemas
from services.companybankdocument_service import CompanyBankDocumentService
from services.companybankinfo_service import CompanyBankInfoService
from services.country_service import CountryService
from services.state_service import StateService
from services.user_service import UserService  # import the class
from services.user_address_service import UserAddressService
from services.company_tax_service import CompanyTaxService
from services.company_tax_document_service import CompanyTaxDocumentService
from utils.email_service import EmailService

router = APIRouter(prefix="/register", tags=["register"])
address_service = UserAddressService()
# Instantiate the service
user_service_instance = UserService()
countryservice = CountryService()
stateservice = StateService()
taxservice = CompanyTaxService()
taxdocumentservice = CompanyTaxDocumentService()
ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png"}
@router.post("/", response_model=schemas.User)
def create_user(user: schemas.UserRegistor, db: Session = Depends(get_db)):
    """Create a new user."""
    return user_service_instance.create_user(db, user)
@router.get("/countries", response_model=list[schemas.CountryOut])
def list_allcountries(skip: int = 0, limit: int = 100, search: str = None, db: Session = Depends(get_db)):
    return countryservice.get_countries(db, skip=skip, limit=limit, search=search)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import pyotp
from datetime import datetime, timedelta



# Simple in-memory storage for demo (replace with Redis or DB)
otp_store = {}

TOTP_INTERVAL = 120  # seconds (2 minutes)

class OTPRequest(BaseModel):
    email: str | None = None
    phone: str | None = None


@router.post("/generate-otp")
def generate_otp(payload: OTPRequest):
    """Generate and send OTP (email preferred, fallback to phone)"""
    if not payload.email and not payload.phone:
        raise HTTPException(status_code=400, detail="Email or phone required")

    # Create or reuse a TOTP secret for this user (could be stored in DB)
    totp_secret = pyotp.random_base32()

    # Generate OTP
    otp = pyotp.TOTP(totp_secret, interval=TOTP_INTERVAL).now()

    # Send via your helper
    if payload.email:
            # ✅ Instantiate EmailService and send the OTP
        email_service = EmailService()
        email_service.send_totp(payload.email, otp)
    #elif payload.phone:
        #SMSService.send_totp(payload.phone, otp)

    # Store for verification
    otp_store[payload.email or payload.phone] = {
        "otp": otp,
        "secret": totp_secret,
        "expires_at": datetime.utcnow() + timedelta(seconds=TOTP_INTERVAL),
    }

    return {"message": "OTP sent successfully"}
class VerifyOTPRequest(BaseModel):
    email: str | None = None
    phone: str | None = None
    otp: str




@router.post("/verify-otp")
def verify_otp(payload: VerifyOTPRequest):
    """Verify OTP for email or phone"""
    key = payload.email or payload.phone
    if not key:
        raise HTTPException(status_code=400, detail="Email or phone required")

    record = otp_store.get(key)
    if not record:
        raise HTTPException(status_code=404, detail="No OTP found or expired")

    # Check expiry
    if datetime.utcnow() > record["expires_at"]:
        del otp_store[key]
        raise HTTPException(status_code=400, detail="OTP expired")

    # Verify
    totp = pyotp.TOTP(record["secret"], interval=TOTP_INTERVAL)
    is_valid = totp.verify(payload.otp, valid_window=1)

    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid OTP")

    # Clear OTP after verification
    del otp_store[key]

    return {"verified": True}

@router.get("/states", response_model=list[schemas.StateOut])
def list_allstates(
    skip: int = 0,
    limit: int = 100,
    search: str | None = Query(None),
    country_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    List states, optionally filtered by `country_id` and/or `search`.
    """
    return stateservice.get_states(
        db, skip=skip, limit=limit, search=search, country_id=country_id
    )
@router.get("/check-email")
def check_email_exists(email: str = Query(...), db: Session = Depends(get_db)):
    exists = user_service_instance.is_email_exists(db, email)
    return {"exists": exists}


@router.get("/check-phone")
def check_phone_exists(phone: str = Query(...), db: Session = Depends(get_db)):
    exists = user_service_instance.is_phone_exists(db, phone)
    return {"exists": exists}

@router.post("/bank-info", response_model=schemas.CompanyBankInfoSchema, status_code=201)
def create_bank_info_reg(
    data: schemas.CompanyBankInfoCreateSchema,
    db: Session = Depends(get_db)
):
    return CompanyBankInfoService.create_bank_info(
        db=db,
        company_id=data.company_id,  # ✅ use company_id as user_id
        data=data.dict(exclude={"company_id"})
    )

@router.post("/addresses", response_model=schemas.UserAddressOut, status_code=status.HTTP_201_CREATED)
def create_address_reg(address: schemas.UserAddressCreate, db: Session = Depends(get_db)):
    return address_service.create_user_address(db, address)


@router.post("/bank_documents", response_model=schemas.CompanyBankDocumentSchema)
async def upload_bank_document_reg(
    bank_info_id: int = Form(...),
    document_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    file_data = await file.read()

    return CompanyBankDocumentService.create_document(
        db=db,
        bank_info_id=bank_info_id,
        file_name=file.filename,
        file_data=file_data,
        file_type=file.content_type,
        document_type=document_type,
    )
# =====================================================
# 📤 Upload a new document for a company (with file size validation)
# =====================================================
@router.post("/tax-documents/{company_id}", status_code=status.HTTP_201_CREATED)
async def upload_tax_document_reg(
    company_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload tax related document and link to company tax info record
    """
    try:
        file_data = await file.read()

        # ✅ Validate size
        if len(file_data) > MAX_FILE_SIZE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Max allowed: {MAX_FILE_SIZE_KB} KB",
            )

        # ✅ Validate MIME types
        if file.content_type not in ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only PDF / JPG / PNG allowed",
            )

        # ✅ Save document via service
        saved_doc = taxdocumentservice.create_document_for_company(
            db=db,
            company_id=company_id,
            file_name=file.filename,
            file_data=file_data,
            file_type=file.content_type,
        )

        return {
            "id": saved_doc.id,
            "company_id": company_id,
            "file_name": saved_doc.file_name,
            "file_type": saved_doc.file_type,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload failed: {str(e)}",
        )


@router.get("/reverse-geocode")
async def reverse_geocode(
    lat: float = Query(...),
    lon: float = Query(...)
):
    params = {
        "lat": lat,
        "lon": lon,
        "format": "json",
        "addressdetails": 1,
    }

    headers = {
        "User-Agent": "dine_eaze_app"   # REQUIRED by Nominatim
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(NOMINATIM_URL, params=params, headers=headers)
    
    return response.json()
@router.post("/tax-info", response_model=schemas.CompanyTaxInfoOut, status_code=status.HTTP_201_CREATED)
def create_company_tax_info_reg(tax_info: schemas.CompanyTaxInfoCreate, db: Session = Depends(get_db)):
    """Create a new tax info record (generic)"""
    return taxservice.create_tax_info(
        db,
        company_id=tax_info.company_id,
        pan=tax_info.pan,
        gstin=tax_info.gstin,
        tan=tax_info.tan,
       # state_id=tax_info.state_id,
        financial_year=tax_info.financial_year
    )

@router.post("/complete", status_code=201)
async def complete_registration(
    payload: str = Form(...),  # JSON string
    files: List[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """
    Bulk onboarding:
    Creates user, both addresses, bank info, tax info
    Uploads bank + tax documents in one submission.
    """
    try:
        data = json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # ✅ Required sections
    required_keys = ["account", "office_address", "bank", "tax_info"]
    for key in required_keys:
        if key not in data:
            raise HTTPException(status_code=400, detail=f"Missing `{key}` in payload")

    documents_meta = data.get("documents", [])
    tax_docs_meta = data.get("tax_documents", [])

    try:
        with db.begin():  # ✅ ensures rollback on failure
            # ✅ 1️⃣ Create User / Company
            new_user = user_service_instance.create_user(db, data["account"])

            # ✅ 2️⃣ Office Address
            office = data["office_address"]
            office["user_id"] = new_user.id
            office["is_primary"] = True
            office["address_type"] = "corporate"
            address_service.create_user_address(db, office)

            # ✅ 3️⃣ Communication Address (Optional)
            comm = data.get("comm_address")
            if comm:
                comm["user_id"] = new_user.id
                comm["is_primary"] = False
                comm["address_type"] = "other"
                address_service.create_user_address(db, comm)

            # ✅ 4️⃣ Bank Info
            bank_payload = data["bank"]
            bank_obj = CompanyBankInfoService.create_bank_info(
                db, company_id=new_user.id, data=bank_payload
            )

            # 🔄 Attach files to metadata through field_name match
            file_map = {f"file_{i}": files[i] for i in range(len(files or []))}

            # ✅ 5️⃣ Bank Documents
            for meta in documents_meta:
                field_name = meta.get("field_name")
                upload = file_map.get(field_name)

                if not upload:
                    raise HTTPException(status_code=400, detail=f"Missing bank doc for {field_name}")

                data_bytes = await upload.read()
                if upload.content_type not in ALLOWED_MIME_TYPES:
                    raise HTTPException(status_code=400, detail="Invalid bank document format")
                if len(data_bytes) > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(status_code=400, detail="Bank document too large")

                CompanyBankDocumentService.create_document(
                    db=db,
                    bank_info_id=bank_obj.id,
                    file_name=upload.filename,
                    file_data=data_bytes,
                    file_type=upload.content_type,
                    document_type=meta.get("document_type"),
                )

            # ✅ 6️⃣ Tax Info
            tax_info = data["tax_info"]
            tax_obj = taxservice.create_tax_info(db, tax_info)

            # ✅ 7️⃣ Tax Documents
            for meta in tax_docs_meta:
                field_name = meta.get("field_name")
                upload = file_map.get(field_name)

                if not upload:
                    raise HTTPException(status_code=400, detail=f"Missing tax doc for {field_name}")

                data_bytes = await upload.read()
                if upload.content_type not in ALLOWED_MIME_TYPES:
                    raise HTTPException(status_code=400, detail="Invalid tax document format")
                if len(data_bytes) > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(status_code=400, detail="Tax document too large")

                taxdocumentservice.create_document_for_company(
                    db=db,
                    company_id=new_user.id,
                    file_name=upload.filename,
                    file_data=data_bytes,
                    file_type=upload.content_type,
                )

        return {"id": new_user.id, "message": "Registration completed successfully"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")