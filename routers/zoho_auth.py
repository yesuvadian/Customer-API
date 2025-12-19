from fastapi import APIRouter, HTTPException, status, Form
from typing import Optional
import requests
import jwt  # PyJWT
import os

from config import (
    ZOHO_CLIENT_ID, 
    ZOHO_CLIENT_SECRET,
    CALLBACK_URL as ZOHO_REDIRECT_URI,
    ZOHO_OAUTH_TOKEN_URL,
)

router = APIRouter(
    prefix="/zoho",
    tags=["Zoho Auth"],
)


@router.post("/token", status_code=status.HTTP_200_OK)
def exchange_zoho_code(code: str = Form(...)):
    """
    Exchange Authorization Code from Zoho Web OAuth2 Login
    and return tokens + identity.
    """

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code"
        )

    data = {
        "code": code,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "redirect_uri": ZOHO_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    try:
        res = requests.post(
            ZOHO_OAUTH_TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10
        )

        if res.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zoho token exchange failed: {res.text}"
            )

        token_payload = res.json()

        id_token = token_payload.get("id_token")
        access_token = token_payload.get("access_token")

        if not id_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Zoho did not return id_token (OpenID scope required)"
            )

        # Decode ID token (signature skipped because Zoho uses rotating public keys)
        decoded = jwt.decode(id_token, options={"verify_signature": False})

        email = decoded.get("email")
        name = decoded.get("name") or decoded.get("given_name")

        return {
            "access_token": access_token,
            "id_token": id_token,
            "email": email,
            "name": name,
        }

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected Zoho auth exception: {exc}"
        )
