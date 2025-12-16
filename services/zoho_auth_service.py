import time
import requests
from fastapi import HTTPException
import config

# ------------------------------
# Module-level token cache
# ------------------------------
_access_token: str | None = None
_expiry_time: float = 0


def get_zoho_access_token() -> str:
    """
    Return a cached Zoho access token or refresh it if expired.
    Uses application-level OAuth.
    """
    global _access_token, _expiry_time

    # Reuse token if still valid (60s buffer)
    if _access_token and time.time() < (_expiry_time - 60):
        return _access_token

    response = requests.post(
        f"{config.ZOHO_ACCOUNTS_BASE}/oauth/v2/token",
        params={
            "refresh_token": config.ZOHO_REFRESH_TOKEN,
            "client_id": config.ZOHO_CLIENT_ID,
            "client_secret": config.ZOHO_CLIENT_SECRET,
            "grant_type": "refresh_token"
        },
        timeout=10
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Failed to refresh Zoho access token",
                "response": response.text
            }
        )

    data = response.json()

    if "access_token" not in data:
        raise HTTPException(
            status_code=500,
            detail="Zoho response missing access_token"
        )

    _access_token = data["access_token"]
    _expiry_time = time.time() + int(data.get("expires_in", 3600))

    return _access_token
