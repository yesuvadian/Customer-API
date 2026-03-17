import requests
from fastapi import HTTPException
import config
from services.zoho_auth_service import get_zoho_access_token
#from services.zoho_token_service import get_zoho_access_token


def zoho_request(method: str, path: str, *, params=None, json=None):
    """
    Generic Zoho Books API caller
    Automatically handles OAuth token
    """

    access_token = get_zoho_access_token()

    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.request(
            method=method,
            url=f"{config.ZOHO_API_BASE}/books/v3{path}",
            headers=headers,
            params=params,
            json=json,
            timeout=15
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "message": "Zoho Books API is unavailable",
                "service": config.ZOHO_API_BASE,
                "error": str(exc),
            },
        ) from exc

    return response
