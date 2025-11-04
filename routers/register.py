import json
from typing import List
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile,status
from sqlalchemy.orm import Session

from auth_utils import get_registration_user
from database import get_db
import schemas
from services.companybankdocument_service import CompanyBankDocumentService
from services.companybankinfo_service import CompanyBankInfoService
from services.country_service import CountryService
from services.state_service import StateService
from services.user_service import UserService  # import the class
from services.user_address_service import UserAddressService
router = APIRouter(prefix="/register", tags=["register"])
address_service = UserAddressService()
# Instantiate the service
user_service_instance = UserService()
countryservice = CountryService()
stateservice = StateService()
@router.post("/", response_model=schemas.User)
def create_user(user: schemas.UserRegistor, db: Session = Depends(get_db)):
    """Create a new user."""
    return user_service_instance.create_user(db, user)
@router.get("/countries", response_model=list[schemas.CountryOut])
def list_allcountries(skip: int = 0, limit: int = 100, search: str = None, db: Session = Depends(get_db)):
    return countryservice.get_countries(db, skip=skip, limit=limit, search=search)

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
@router.post("/complete", status_code=201)
async def complete_registration(
    payload: str = Form(...),  # JSON string with full registration data
    files: List[UploadFile] = File([]),  # uploaded documents
    db: Session = Depends(get_db),
):
    """
    payload JSON structure (example):
    {
      "account": { "email": "...", "firstname": "...", "lastname": "...", "phone_number": "...", "password": "...", "plan_id": "..." },
      "office_address": {...},   // address dict
      "comm_address": {...},
      "bank": {...},             // bank metadata (no file)
      "documents": [
         { "field_name": "file_0", "document_type": "bank_passbook" },
         { "field_name": "file_1", "document_type": "pan_card" }
      ]
    }
    The 'field_name' tells server which uploaded file maps to which metadata entry.
    """

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid payload JSON")

    # Server-side validation: basic required keys
    for key in ("account", "office_address", "bank", "documents"):
        if key not in data:
            raise HTTPException(status_code=400, detail=f"Missing '{key}' in payload")

    # Use a transaction: SQLAlchemy Session.begin() (autocommit off)
    try:
        with db.begin():  # on exception, this will rollback
            # 1) create user (account)
            account_payload = data["account"]
            new_user = user_service_instance.create_user(db, account_payload)  # adapt to your service

            # 2) create addresses (office + communication)
            office = data["office_address"]
            office["user_id"] = new_user.id
            office["address_type"] = "corporate"
            address_service.create_user_address(db, office)

            comm = data.get("comm_address")
            if comm:
                comm["user_id"] = new_user.id
                comm["address_type"] = "communication"
                address_service.create_user_address(db, comm)

            # 3) create bank info (link to user/company)
            bank_payload = data["bank"]
            bank_obj = CompanyBankInfoService.create_bank_info(db, company_id=new_user.id, data=bank_payload)

            # 4) handle documents: match metadata to uploaded files
            docs_meta = data["documents"]
            # Build map from field_name -> UploadFile
            file_map = {f"file_{i}": files[i] for i in range(len(files))} if files else {}
            # Alternatively allow any file field names provided by client:
            # file_map = {file.filename: file for file in files}

            for meta in docs_meta:
                field_name = meta.get("field_name")
                document_type = meta.get("document_type")
                if not field_name or not document_type:
                    raise HTTPException(status_code=400, detail="Invalid document metadata")

                upload_file = file_map.get(field_name)
                if upload_file is None:
                    raise HTTPException(status_code=400, detail=f"Missing uploaded file for {field_name}")

                content = await upload_file.read()
                # persist document
                CompanyBankDocumentService.create_document(
                    db=db,
                    bank_info_id=bank_obj.id,
                    file_name=upload_file.filename,
                    file_data=content,
                    file_type=upload_file.content_type,
                    document_type=document_type,
                )

        # Transaction committed successfully
        return {"id": new_user.id, "message": "Registration complete"}
    except Exception as e:
        # Logging recommended
        raise HTTPException(status_code=500, detail=f"Registration failed: {e}")