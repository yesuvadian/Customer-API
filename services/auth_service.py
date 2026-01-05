from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from datetime import timedelta

from auth_utils import create_access_token, create_refresh_token
from models import UserSession
from utils.common_service import UTCDateTimeMixin
from config import SECRET_KEY, ALGORITHM, REFRESH_TOKEN_EXPIRE_DAYS
#from security import create_access_token, create_refresh_token


class AuthService:

    @classmethod
    def refresh_access_token(cls, db: Session, refresh_token: str) -> dict:
        """
        Validate refresh token, verify session, and issue a new access token.
        """

        # 1️⃣ Decode refresh token
        try:
            payload = jwt.decode(
                refresh_token,
                SECRET_KEY,
                algorithms=[ALGORITHM]
            )
            user_id = payload.get("sub")
            if not user_id:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token"
                )
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token"
            )

        # 2️⃣ Fetch session
        session = (
            db.query(UserSession)
            .filter(
                UserSession.refresh_token == refresh_token,
                UserSession.user_id == user_id
            )
            .first()
        )

        if not session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session not found"
            )

        # 3️⃣ Check session expiration
        now = UTCDateTimeMixin._utc_now()
        if session.expires_at and UTCDateTimeMixin._make_aware(session.expires_at) < now:
            db.delete(session)
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session expired"
            )

        # 4️⃣ Generate new tokens (ROTATION ENABLED)
        new_access_token = create_access_token({"sub": str(user_id)})
        new_refresh_token = create_refresh_token(str(user_id))

        session.access_token = new_access_token
        session.refresh_token = new_refresh_token
        session.expires_at = now + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

        db.commit()

        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token,
            "token_type": "bearer"
        }
