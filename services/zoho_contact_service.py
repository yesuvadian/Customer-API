from fastapi import HTTPException, status
from services.zoho_client import zoho_request
import config


class ZohoContactService:

    def get_contact_id_by_email(self, email: str) -> str:
        """
        Fetch Zoho Books contact_id using customer email
        """

        response = zoho_request(
            method="GET",
            path="/contacts",
            params={
                "organization_id": config.ZOHO_ORG_ID,
                "email": email
            }
        )

        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "message": "Failed to fetch contact from Zoho Books",
                    "zoho_response": response.json()
                }
            )

        data = response.json()
        contacts = data.get("contacts", [])

        if not contacts:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No Zoho contact found for email: {email}"
            )

        # Return the first matching contact
        return contacts[0]
