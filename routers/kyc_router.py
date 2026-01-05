from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from uuid import UUID

from auth_utils import get_current_user
from database import get_db
from services.user_kyc_service import UserKYCService

router = APIRouter(
    prefix="/kyc",
    tags=["KYC Status"],
    dependencies=[Depends(get_current_user)]
)

@router.get(
    "/{user_id}",
    summary="Check pending KYC sections",
    description="Returns YES/NO flags for each pending KYC section"
)
def get_pending_kyc(user_id: UUID, db: Session = Depends(get_db)):
    """
    Returns YES/NO flags for all pending KYC sections.
    """
    try:
        return UserKYCService.get_all_pending_kyc(db, user_id)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
