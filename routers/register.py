from fastapi import APIRouter, Depends, File, Form, Query, UploadFile,status
from sqlalchemy.orm import Session

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
